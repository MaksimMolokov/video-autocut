"""
F1IntroRenderer — composite-frame intro for the F1 montage style.

The intro block consists of two parts:

  Part 1 — Composite frame (~2 s):
    • A black screen on which 5 vertical stripe images snap in one by one
      (sharp, instant appearance — no fade/dissolve).
    • Each stripe is a genuine VERTICAL CROP from a full-resolution still
      frame chosen from the source videos.  The frame is scaled so its
      HEIGHT fills the output frame; then a narrow vertical slice is cropped
      from it.  This preserves the natural visual density of the original
      image — no squishing, no stretching, no miniature-copy effect.
    • After all 5 stripes appear the completed composite is held briefly.

  Part 2 — Rapid-cut block (~1 s):
    • 10 micro-clips × 0.1 s, full-frame, from distinct source positions.

Both parts are concatenated into one MP4 that the GUI render pipeline
prepends to the main edit.

Config reference (all values tunable via F1_CONFIG):
  intro_total_duration    — total length of Part 1 (s)
  stripe_appearance_delay — delay between consecutive stripe snaps (s)
  intro_hold_duration     — hold time after all stripes appear (s)
  stripes_count           — number of vertical stripes (default 5)
  stripe_crop_bias        — crop position: 0=left, 0.5=center, 1=right
  rapid_count             — number of micro-clips in Part 2
  rapid_clip_dur          — duration of each micro-clip (s)
  min_source_spacing      — minimum gap (s) between picks from same file
"""

from __future__ import annotations

import logging
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


# ── Configuration ──────────────────────────────────────────────────────────────

F1_CONFIG: dict = {
    # Part 1 — composite-frame intro timings
    # 5 stripes × 0.12 s = 0.60 s appearance + 0.60 s hold = 1.20 s total
    'intro_total_duration':    1.2,    # total length of the intro block (s)
    'stripe_appearance_delay': 0.12,   # delay between consecutive stripe snaps (s)
    'intro_hold_duration':     0.40,   # approximate hold after last stripe appears

    # Stripe geometry
    'stripes_count':           5,
    'stripe_crop_bias':        0.5,    # 0=left, 0.5=center, 1=right of scaled frame

    # Part 2 — rapid-cut block  (10 × 0.10 s = 1.0 s)
    # Total intro MP4 ≈ 1.2 s + 1.0 s = 2.2 s
    'rapid_count':             10,
    'rapid_clip_dur':          0.10,   # seconds per micro-clip

    # Selection diversity
    'min_source_spacing':      3.0,    # min seconds between picks from same source file
}


# ── Source descriptor ──────────────────────────────────────────────────────────

@dataclass
class _Src:
    source_path: str
    start:       float
    duration:    float
    energy:      float = 0.5     # combined motion + action score
    sharpness:   float = 0.5
    brightness:  float = 0.5


# ── Public API ─────────────────────────────────────────────────────────────────

class F1IntroRenderer:

    @staticmethod
    def render_f1_intro(
        candidates: list,
        output_path: str,
        out_w: int,
        out_h: int,
        seed: int = 42,
        beats: Optional[List[float]] = None,
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """
        Render the F1 intro block to *output_path* (MP4 at out_w × out_h).

        Args:
            candidates:        CandidateClip objects with .source_path,
                               .start, .end, .duration, .features
            output_path:       Destination file (overwritten if exists)
            out_w, out_h:      Must match the main edit resolution
            seed:              Variant seed — different seed → different clips
            beats:             Optional beat timestamps (unused currently)
            progress_callback: Optional callable(str) for progress messages

        Returns:
            True on success.
        """
        cb  = _make_cb(progress_callback)
        rng = random.Random(seed + 5555)
        cfg = F1_CONFIG

        cb(f"[F1Intro] Building intro  resolution={out_w}×{out_h}  seed={seed}")

        sources = _candidates_to_sources(candidates)
        if not sources:
            cb("[F1Intro] No usable candidates — intro skipped")
            return False

        with tempfile.TemporaryDirectory() as _tmp:
            tmp = Path(_tmp)

            # ── Part 1: composite-frame intro ──────────────────────────────────

            stripe_srcs = _select_stripes(sources, cfg['stripes_count'], rng)
            cb(f"[F1Intro] Stripe frames ({len(stripe_srcs)} selected):")
            for i, s in enumerate(stripe_srcs):
                frame_ts = s.start + s.duration * 0.40
                cb(
                    f"  stripe {i+1}/{cfg['stripes_count']}: "
                    f"{Path(s.source_path).name}  "
                    f"clip_start={s.start:.1f}s  frame@{frame_ts:.1f}s  "
                    f"energy={s.energy:.2f}  sharpness={s.sharpness:.2f}"
                )

            # Stripe widths — equal slices; last stripe absorbs rounding remainder
            sw           = out_w // cfg['stripes_count']
            last_sw      = out_w - sw * (cfg['stripes_count'] - 1)
            stripe_widths = [sw] * (cfg['stripes_count'] - 1) + [last_sw]

            # Extract a vertical crop from each selected frame
            stripe_pngs: List[Optional[Path]] = []
            for i, (src, sw_i) in enumerate(zip(stripe_srcs, stripe_widths)):
                png = _extract_stripe(
                    src=src, stripe_w=sw_i, out_h=out_h,
                    bias=cfg['stripe_crop_bias'],
                    idx=i, tmp=tmp, cb=cb,
                )
                stripe_pngs.append(png)

            # Replace failed extractions with nearest valid PNG
            valid = [p for p in stripe_pngs if p is not None and p.exists()]
            if not valid:
                cb("[F1Intro] All stripe extractions failed — intro skipped")
                return False

            safe_pngs: List[Path] = []
            fallback = valid[-1]
            for p in stripe_pngs:
                safe_pngs.append(p if (p and p.exists()) else fallback)

            # Render the composite-frame intro video
            intro_mp4 = tmp / "intro_composite.mp4"
            ok_intro  = _render_composite_intro(
                stripe_pngs=safe_pngs,
                stripe_widths=stripe_widths[:len(safe_pngs)],
                output_path=str(intro_mp4),
                out_w=out_w, out_h=out_h,
                cfg=cfg, cb=cb,
            )
            if not ok_intro:
                cb("[F1Intro] Composite intro render failed — intro skipped")
                return False

            # ── Part 2: rapid-cut block ────────────────────────────────────────

            exclude_keys = {(s.source_path, round(s.start, 0)) for s in stripe_srcs}
            rapid_srcs   = _select_rapid(
                sources, cfg['rapid_count'],
                random.Random(seed + 9999), exclude_keys,
            )

            cb(f"[F1Intro] Rapid-cut micro-clips ({len(rapid_srcs)} selected):")
            for i, s in enumerate(rapid_srcs):
                cb(
                    f"  rapid {i+1}: {Path(s.source_path).name} "
                    f"@{s.start:.1f}s  energy={s.energy:.2f}"
                )

            rapid_mp4 = tmp / "intro_rapid.mp4"
            ok_rapid  = _render_rapid(
                rapid_srcs, str(rapid_mp4), out_w, out_h, cfg, beats, cb,
            )

            # ── Concat both parts ──────────────────────────────────────────────
            if ok_rapid and rapid_mp4.exists():
                ok = _concat_parts([intro_mp4, rapid_mp4], output_path, cb)
            else:
                cb("[F1Intro] Rapid block skipped — using composite intro only")
                shutil.copy2(str(intro_mp4), output_path)
                ok = True

            if ok:
                dur = _probe_duration(output_path)
                cb(f"[F1Intro] Done → {Path(output_path).name}  ({dur:.1f}s total)")
            return ok


# ── Candidate → source conversion ─────────────────────────────────────────────

def _make_cb(fn: Optional[Callable]) -> Callable:
    def cb(msg: str):
        logger.info(msg)
        if fn:
            try:
                fn(msg)
            except Exception:
                pass
    return cb


def _candidates_to_sources(candidates: list) -> List[_Src]:
    srcs: List[_Src] = []
    for c in candidates:
        try:
            f   = c.features
            mot = getattr(f, 'motion_score',    0.5) if f else 0.5
            act = getattr(f, 'action_score',    0.5) if f else 0.5
            shp = getattr(f, 'sharpness_score', 0.5) if f else 0.5
            bri = getattr(f, 'brightness_score',0.5) if f else 0.5
            srcs.append(_Src(
                source_path = c.source_path,
                start       = float(c.start),
                duration    = float(c.duration),
                energy      = mot * 0.6 + act * 0.4,
                sharpness   = float(shp),
                brightness  = float(bri),
            ))
        except Exception:
            continue
    # Sort: high energy + sharp + bright first (best frames for the intro)
    srcs.sort(
        key=lambda s: s.energy * 0.5 + s.sharpness * 0.3 + s.brightness * 0.2,
        reverse=True,
    )
    return srcs


# ── Selection helpers ──────────────────────────────────────────────────────────

def _select_stripes(
    sources: List[_Src],
    n: int,
    rng: random.Random,
) -> List[_Src]:
    """
    Pick n high-quality, visually distinct source clips for stripe extraction.
    Maximises source-file diversity first, then time-range diversity.
    """
    selected: List[_Src] = []
    used_keys: set = set()

    by_path: dict = {}
    for s in sources:
        by_path.setdefault(s.source_path, []).append(s)

    paths = list(by_path.keys())
    rng.shuffle(paths)

    # One best-scoring clip per unique source file
    for path in paths:
        if len(selected) >= n:
            break
        for cand in by_path[path]:
            key = (cand.source_path, round(cand.start, 0))
            if key not in used_keys:
                selected.append(cand)
                used_keys.add(key)
                break

    # Supplement with time-range diversity within same files
    spacing = F1_CONFIG['min_source_spacing']
    if len(selected) < n:
        for s in sources:
            if len(selected) >= n:
                break
            key = (s.source_path, round(s.start, 0))
            if key in used_keys:
                continue
            too_close = any(
                sel.source_path == s.source_path
                and abs(sel.start - s.start) < spacing
                for sel in selected
            )
            if too_close:
                continue
            selected.append(s)
            used_keys.add(key)

    # Last resort: any remaining unique position
    for s in sources:
        if len(selected) >= n:
            break
        key = (s.source_path, round(s.start, 0))
        if key not in used_keys:
            selected.append(s)
            used_keys.add(key)

    rng.shuffle(selected)
    return selected[:n]


def _select_rapid(
    sources: List[_Src],
    n: int,
    rng: random.Random,
    exclude_keys: set,
) -> List[_Src]:
    """Pick n distinct positions for the rapid-cut block."""
    expanded: List[_Src] = []
    for s in sources:
        expanded.append(s)
        if s.duration > 1.0:
            expanded.append(_Src(
                s.source_path, s.start + s.duration * 0.35,
                max(0.3, s.duration * 0.2),
                s.energy, s.sharpness, s.brightness,
            ))
        if s.duration > 2.0:
            expanded.append(_Src(
                s.source_path, s.start + s.duration * 0.65,
                max(0.3, s.duration * 0.2),
                s.energy, s.sharpness, s.brightness,
            ))

    rng.shuffle(expanded)
    selected: List[_Src] = []
    used: set = set()

    for s in expanded:
        if len(selected) >= n:
            break
        key = (s.source_path, round(s.start, 1))
        if key in used or key in exclude_keys:
            continue
        selected.append(s)
        used.add(key)

    for s in expanded:     # relax exclusion if still short
        if len(selected) >= n:
            break
        key = (s.source_path, round(s.start, 1))
        if key not in used:
            selected.append(s)
            used.add(key)

    return selected[:n]


# ── Frame extraction ───────────────────────────────────────────────────────────

def _extract_stripe(
    src: _Src,
    stripe_w: int,
    out_h: int,
    bias: float,
    idx: int,
    tmp: Path,
    cb: Callable,
) -> Optional[Path]:
    """
    Extract a vertical stripe (stripe_w × out_h pixels) from a single frame.

    How it works:
      1. Seek to start + duration*0.40 (a visually strong point in the clip).
      2. Scale the frame so that its HEIGHT equals out_h.
         Width scales proportionally — for a 16:9 landscape source this
         produces a wide scaled frame (~3400 px for out_h=1920).
      3. Crop stripe_w pixels horizontally from position
         (scaled_width − stripe_w) × bias.
         bias=0.5 → centre crop; 0=left edge; 1=right edge.

    This gives a genuine vertical slice of the scene at natural density —
    NOT a squeezed copy of the whole frame.
    """
    out_png  = tmp / f"stripe_{idx:02d}.png"

    # bias_expr evaluated by FFmpeg at runtime: iw = scaled width
    bias_expr = f"({bias:.4f})*(iw-{stripe_w})"

    vf = (
        f"scale=-2:{out_h},"                          # scale to height
        f"crop={stripe_w}:{out_h}:{bias_expr}:0"      # vertical slice
    )

    def _try(ts: float) -> bool:
        if out_png.exists():
            out_png.unlink()
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{ts:.3f}",
            "-i", src.source_path,
            "-vframes", "1",
            "-vf", vf,
            "-q:v", "2",
            str(out_png),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            cb(f"[F1Intro]   stripe {idx} FFmpeg error @{ts:.1f}s: "
               f"{r.stderr[-120:].strip()}")
            return False
        if not out_png.exists() or out_png.stat().st_size < 500:
            cb(f"[F1Intro]   stripe {idx}: empty result @{ts:.1f}s")
            return False
        return True

    try:
        timestamps = [
            src.start + src.duration * 0.40,
            src.start + src.duration * 0.20,
            src.start + 0.1,
        ]
        ok = False
        for ts in timestamps:
            ok = _try(ts)
            if ok:
                break

        if ok:
            kb = out_png.stat().st_size // 1024
            cb(f"[F1Intro]   stripe {idx}: {stripe_w}×{out_h} PNG  {kb} KB")
            return out_png
        cb(f"[F1Intro]   stripe {idx}: all attempts failed")
        return None

    except Exception as exc:
        cb(f"[F1Intro]   stripe {idx} exception: {exc}")
        return None


# ── Composite-frame intro renderer ─────────────────────────────────────────────

def _render_composite_intro(
    stripe_pngs: List[Path],
    stripe_widths: List[int],
    output_path: str,
    out_w: int,
    out_h: int,
    cfg: dict,
    cb: Callable,
) -> bool:
    """
    Compose the stripe PNGs into a video where each stripe snaps in sharply.

    Timeline:
      t = 0              → black frame (only background visible)
      t = 0              → stripe 0 snaps in
      t = delay          → stripe 1 snaps in
      t = 2*delay        → stripe 2 snaps in
      ...
      t = (n-1)*delay    → stripe n-1 snaps in
      t = (n-1)*delay .. intro_total_duration → full composite held

    No fade, no dissolve — `overlay:enable='gte(t,T)'` gives a sharp snap.

    FFmpeg inputs:
      [0]  lavfi black background, duration = intro_total_duration
      [1]  stripe 0 PNG (looped still image)
      [2]  stripe 1 PNG
      ...
      [n]  stripe n-1 PNG
    """
    n         = len(stripe_pngs)
    delay     = cfg['stripe_appearance_delay']
    total_dur = cfg['intro_total_duration']

    # Build per-input flags
    cmd_inputs: List[str] = [
        "-t", f"{total_dur:.3f}",
        "-f", "lavfi",
        "-i", f"color=black:s={out_w}x{out_h}:r=30",
    ]
    for png in stripe_pngs:
        cmd_inputs += ["-loop", "1", "-t", f"{total_dur:.3f}", "-i", str(png)]

    # Build filter_complex: chain of overlays
    x_pos   = 0
    current = "[0:v]"
    filter_parts: List[str] = []

    for i, (png_path, sw) in enumerate(zip(stripe_pngs, stripe_widths)):
        appear_t  = i * delay
        out_label = f"[v{i}]"
        filter_parts.append(
            f"{current}[{i+1}:v]"
            f"overlay=x={x_pos}:y=0:enable='gte(t,{appear_t:.3f})'"
            f"{out_label}"
        )
        current  = out_label
        x_pos   += sw

    filter_complex = ";".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y"]
        + cmd_inputs
        + [
            "-filter_complex", filter_complex,
            "-map", current,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-r", "30", "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]
    )

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            cb(f"[F1Intro] composite FFmpeg error:\n{r.stderr[-500:]}")
            return False
        cb(
            f"[F1Intro] Composite intro OK  "
            f"({n} stripes  delay={delay}s  total={total_dur:.1f}s)"
        )
        return True
    except Exception as exc:
        cb(f"[F1Intro] composite exception: {exc}")
        return False


# ── Rapid-cut renderer ─────────────────────────────────────────────────────────

def _render_rapid(
    rapid: List[_Src],
    output_path: str,
    out_w: int,
    out_h: int,
    cfg: dict,
    beats: Optional[List[float]],
    cb: Callable,
) -> bool:
    """
    Render rapid-cut block: each clip is rapid_clip_dur seconds long,
    full-frame (out_w × out_h), centre-cropped from the source.
    """
    if not rapid:
        return False

    clip_dur = cfg['rapid_clip_dur']

    with tempfile.TemporaryDirectory() as _tmp:
        tmp        = Path(_tmp)
        clip_files: List[Path] = []

        for i, s in enumerate(rapid):
            out_clip = tmp / f"r{i:03d}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{s.start:.3f}",
                "-t",  f"{clip_dur:.3f}",
                "-i",  s.source_path,
                "-vf", (
                    # Scale to fill height, then centre-crop to full output size
                    f"scale=-2:{out_h},"
                    f"crop={out_w}:{out_h}:(iw-{out_w})/2:0,"
                    f"fps=30,format=yuv420p"
                ),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-r", "30", "-pix_fmt", "yuv420p",
                "-an",
                str(out_clip),
            ]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=30)
                if r.returncode == 0 and out_clip.exists() and out_clip.stat().st_size > 1024:
                    clip_files.append(out_clip)
            except Exception:
                continue

        if not clip_files:
            cb("[F1Intro] No rapid clips rendered")
            return False

        concat_list = tmp / "rapid.txt"
        with open(concat_list, "w") as fh:
            for cf in clip_files:
                fh.write(f"file '{cf.absolute()}'\n")

        cmd2 = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            output_path,
        ]
        try:
            r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
            if r2.returncode != 0:
                cb(f"[F1Intro] rapid concat error: {r2.stderr[-200:]}")
                return False
            cb(f"[F1Intro] Rapid cuts OK ({len(clip_files)} clips × {clip_dur}s)")
            return True
        except Exception as exc:
            cb(f"[F1Intro] rapid concat exception: {exc}")
            return False


# ── Utility ────────────────────────────────────────────────────────────────────

def _concat_parts(parts: List[Path], output_path: str, cb: Callable) -> bool:
    """Concatenate intro parts (composite + rapid) into the final intro file."""
    existing = [p for p in parts if p.exists()]
    if not existing:
        return False
    if len(existing) == 1:
        shutil.copy2(str(existing[0]), output_path)
        return True

    with tempfile.TemporaryDirectory() as _tmp:
        lst = Path(_tmp) / "parts.txt"
        with open(lst, "w") as fh:
            for p in existing:
                fh.write(f"file '{p.absolute()}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(lst),
            "-c", "copy",
            output_path,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                cb(f"[F1Intro] final concat error: {r.stderr[-200:]}")
                return False
            return True
        except Exception as exc:
            cb(f"[F1Intro] final concat exception: {exc}")
            return False


def _probe_duration(path: str) -> float:
    """Return media duration via ffprobe, or 0.0 on failure."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             path],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0
