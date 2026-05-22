"""
F1 Main-Edit Timeline Builder

Builds the watchable main-edit body that follows the F1 intro block.

The rapid/aggressive content is ENTIRELY handled by f1_renderer.py:
  • Part 1 — composite still-frame (5 vertical stripes, ~1.2 s)
  • Part 2 — rapid-cut micro-clips (10 × 0.1 s = 1.0 s)
  Total intro ≈ 2.2 s

This module builds ONLY the main body that comes after the intro.
Every clip here must be long enough to be comfortably watchable —
no rapid cuts, no flicker, no micro-fragments.

Clip duration formula (beat-synced):
  groups = round(preferred_clip / beat_interval)   # nearest beat multiple
  clip_dur = clamp(groups × beat_interval, main_min_clip, main_max_clip)

Example at 120 BPM (beat_interval = 0.50 s):
  groups = round(2.80 / 0.50) = 6  →  clip_dur = 6 × 0.50 = 3.00 s  ✓

After building, an anti-flicker validation pass checks that:
  • No clip is below hard_min_clip (1.50 s)
  • No 10-second window has more than anti_flicker_max_cuts cuts
Both violations are logged; under-floor clips are dropped with a warning.
"""

from __future__ import annotations

import logging
import random
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────────────────

F1_PHASE_CONFIG: dict = {
    # Main-edit clip durations
    'main_min_clip':          1.80,  # preferred lower bound (s)
    'main_preferred_clip':    2.80,  # target for beat-grouping calculation (s)
    'main_max_clip':          4.00,  # preferred upper bound (s)
    'main_hard_min_clip':     1.50,  # absolute floor — clips below this are dropped
    'main_hard_max_clip':     4.50,  # absolute ceiling — clips are capped here
    'main_beat_grouping':    'auto', # 'auto' or int (explicit beats-per-clip)

    # Anti-flicker validation (applied after body is built)
    'anti_flicker_window':   10.0,   # rolling window length (s)
    'anti_flicker_max_cuts':  5,     # max cuts allowed in any window of that length

    # Shared
    'min_source_gap':         2.0,   # min seconds between reuses of same source position
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _compute_main_clip_dur(beat_interval: float, cfg: dict) -> Tuple[float, int]:
    """
    Return (clip_dur, beat_groups) for the main edit.

    With 'auto' grouping we find the beat count whose product falls closest to
    preferred_clip within [main_min_clip, main_max_clip].  If beat_interval is
    very large (slow music) we still cap at main_hard_max_clip.
    """
    beat_iv = max(0.05, beat_interval)
    grouping = cfg['main_beat_grouping']

    if grouping == 'auto':
        preferred = cfg['main_preferred_clip']
        groups = max(1, round(preferred / beat_iv))
        clip_dur = groups * beat_iv
        # If the computed value is out of range, nudge the group count
        while clip_dur < cfg['main_min_clip'] and groups < 20:
            groups += 1
            clip_dur = groups * beat_iv
        while clip_dur > cfg['main_max_clip'] and groups > 1:
            groups -= 1
            clip_dur = groups * beat_iv
    else:
        groups = max(1, int(grouping))
        clip_dur = groups * beat_iv

    clip_dur = _clamp(clip_dur, cfg['main_hard_min_clip'], cfg['main_hard_max_clip'])
    return clip_dur, groups


def _pick_subseg(
    candidates,
    desired_dur: float,
    hard_min: float,
    rng: random.Random,
    used_ranges: Dict[str, List[Tuple[float, float]]],
    avoid_path: str = '',
    min_source_gap: float = 2.0,
):
    """
    Pick a CandidateClip and carve a sub-segment of *desired_dur* from it.

    Skips candidates whose available duration is below *hard_min*.
    Falls back to any candidate (ignoring collision checks) if nothing works.
    Returns a SelectedSegment or None.
    """
    from src.segment_selector import SelectedSegment

    # Prefer a different source file to avoid consecutive same-source cuts
    eligible = [c for c in candidates if c.source_path != avoid_path]
    if not eligible:
        eligible = list(candidates)

    # Bias toward higher-scoring candidates (top half first, shuffled)
    top_n = max(1, len(eligible) // 2)
    top_pool = sorted(eligible, key=lambda c: c.final_score, reverse=True)[:top_n]
    rest = [c for c in eligible if c not in top_pool]
    rng.shuffle(top_pool)
    rng.shuffle(rest)
    ordered = top_pool + rest

    for c in ordered:
        avail = c.end - c.start
        if avail < hard_min:
            continue  # candidate too short for watchable main edit

        clip_dur = min(desired_dur, avail)

        max_offset = max(0.0, avail - clip_dur)
        offset = rng.uniform(0.0, max_offset)
        seg_start = c.start + offset
        seg_end = seg_start + clip_dur

        # Avoid overlapping an already-used window in this file
        taken = used_ranges.get(c.source_path, [])
        collision = any(
            seg_start < ue - min_source_gap and seg_end > us + min_source_gap
            for us, ue in taken
        )
        if collision:
            continue

        used_ranges.setdefault(c.source_path, []).append((seg_start, seg_end))

        seg = SelectedSegment(
            source_path=c.source_path,
            start=seg_start,
            end=seg_end,
            duration=clip_dur,
            is_must_use=False,
        )
        seg.role = 'body'
        return seg

    # Hard fallback: ignore collision checks, take first long-enough candidate
    for c in eligible:
        avail = c.end - c.start
        if avail < hard_min:
            continue
        clip_dur = min(desired_dur, avail)
        seg = SelectedSegment(
            source_path=c.source_path,
            start=c.start,
            end=c.start + clip_dur,
            duration=clip_dur,
            is_must_use=False,
        )
        seg.role = 'body'
        return seg

    return None  # truly no usable candidates


def _anti_flicker_pass(
    segments: list,
    cfg: dict,
    cb: Callable,
) -> Tuple[list, int, float]:
    """
    Validate and clean the segment list:
      1. Drop clips below hard_min_clip and log count.
      2. Report any 10-second windows with too many cuts (no auto-removal,
         just logging — the duration fix in _pick_subseg handles the root cause).

    Returns (cleaned_segments, n_dropped, avg_dur_after).
    """
    hard_min = cfg['main_hard_min_clip']
    window   = cfg['anti_flicker_window']
    max_cuts = cfg['anti_flicker_max_cuts']

    # 1. Drop too-short clips
    n_dropped = 0
    clean: list = []
    for s in segments:
        if s.duration < hard_min:
            cb(
                f"[F1 Anti-flicker] Dropped short clip "
                f"{s.duration:.2f}s < hard_min={hard_min}s "
                f"({s.source_path.split('/')[-1]}@{s.start:.1f}s)"
            )
            n_dropped += 1
        else:
            clean.append(s)

    # 2. Sliding window check (report only)
    flicker_windows = 0
    if clean:
        t = 0.0
        timestamps: List[float] = []
        for s in clean:
            timestamps.append(t)
            t += s.duration

        for i, t_start in enumerate(timestamps):
            t_end = t_start + window
            cuts_in_window = sum(
                1 for ts in timestamps[i:] if ts < t_end
            )
            if cuts_in_window > max_cuts:
                flicker_windows += 1

    if flicker_windows:
        cb(
            f"[F1 Anti-flicker] WARNING: {flicker_windows} window(s) exceed "
            f"{max_cuts} cuts per {window:.0f}s — consider raising main_min_clip"
        )

    avg_dur = (
        sum(s.duration for s in clean) / len(clean) if clean else 0.0
    )

    cb(
        f"[F1 Anti-flicker] dropped={n_dropped}  "
        f"remaining={len(clean)}  avg_dur={avg_dur:.2f}s  "
        f"flicker_windows={flicker_windows}"
    )
    return clean, n_dropped, avg_dur


# ── Public API ──────────────────────────────────────────────────────────────────

def build_f1_phased_body(
    candidates,
    target_duration: float,
    beat_interval: float,
    phase_config: Optional[dict] = None,
    seed: int = 0,
    cb: Optional[Callable[[str], None]] = None,
) -> list:
    """
    Build the F1 main-edit body (watchable, beat-synced clips).

    The aggressive/rapid content is the f1_renderer's job.  This function
    produces ONLY the calm, readable part that comes after.

    Args:
        candidates:      CandidateClip objects from video analysis
                         (should be 1.5–4.5 s long per f1.yaml settings)
        target_duration: Total body duration to fill (seconds)
        beat_interval:   Seconds per beat (60 / BPM); 0.5 = 120 BPM default
        phase_config:    Override dict for F1_PHASE_CONFIG keys
        seed:            RNG seed for reproducibility
        cb:              Progress/logging callback

    Returns:
        List of SelectedSegment objects (watchable main edit)
    """
    if cb is None:
        cb = lambda m: logger.info(m)

    if not candidates:
        cb("[F1 Main-edit] No candidates — returning empty body")
        return []

    cfg = {**F1_PHASE_CONFIG, **(phase_config or {})}
    rng = random.Random(seed)

    # ── Compute beat-synced clip duration ─────────────────────────────────────
    beat_iv = max(0.05, beat_interval)
    clip_dur, beat_groups = _compute_main_clip_dur(beat_iv, cfg)

    cb(
        f"[F1 Main-edit] START  "
        f"beat_interval={beat_iv:.3f}s ({60/beat_iv:.1f} BPM)  "
        f"beat_grouping=auto → {beat_groups} beats/clip  "
        f"clip_dur={clip_dur:.2f}s  "
        f"body_budget={target_duration:.1f}s"
    )
    cb(
        f"[F1 Main-edit] clip range: "
        f"hard_min={cfg['main_hard_min_clip']:.1f}s  "
        f"preferred={cfg['main_min_clip']:.1f}–{cfg['main_max_clip']:.1f}s  "
        f"hard_max={cfg['main_hard_max_clip']:.1f}s"
    )

    used_ranges: Dict[str, List[Tuple[float, float]]] = {}
    hard_min  = cfg['main_hard_min_clip']
    min_gap   = cfg['min_source_gap']
    segments: list = []
    elapsed   = 0.0
    prev_path = ''

    # ── Fill budget with watchable clips ──────────────────────────────────────
    while elapsed < target_duration - 0.10:
        remaining = target_duration - elapsed
        desired   = min(clip_dur, remaining)

        # Don't create a tiny tail segment — stop if remaining < hard_min
        if remaining < hard_min * 0.9:
            break

        seg = _pick_subseg(
            candidates, desired, hard_min,
            rng, used_ranges,
            avoid_path=prev_path,
            min_source_gap=min_gap,
        )

        if seg is None:
            cb(f"[F1 Main-edit] No more usable candidates after {len(segments)} clips")
            break

        segments.append(seg)
        elapsed   += seg.duration
        prev_path  = seg.source_path

    if not segments:
        cb("[F1 Main-edit] WARNING: zero clips built — check candidate durations")
        return []

    raw_avg = elapsed / len(segments)
    cb(
        f"[F1 Main-edit] Raw fill: {len(segments)} clips  "
        f"actual={elapsed:.2f}s / budget={target_duration:.1f}s  "
        f"avg_dur={raw_avg:.2f}s"
    )

    # ── Anti-flicker validation ───────────────────────────────────────────────
    segments, n_dropped, final_avg = _anti_flicker_pass(segments, cfg, cb)

    # ── Summary log ──────────────────────────────────────────────────────────
    if segments:
        min_dur = min(s.duration for s in segments)
        max_dur = max(s.duration for s in segments)
        total   = sum(s.duration for s in segments)
        cb(
            f"[F1 Main-edit] DONE  "
            f"clips={len(segments)}  total={total:.2f}s  "
            f"avg={final_avg:.2f}s  min={min_dur:.2f}s  max={max_dur:.2f}s  "
            f"dropped={n_dropped}"
        )
    else:
        cb("[F1 Main-edit] DONE — empty body (no candidates met duration floor)")

    return segments
