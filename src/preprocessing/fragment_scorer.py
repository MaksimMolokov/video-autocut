"""
Universal Montage Fragment Scorer (Step 2 preprocessing).

Style-agnostic, multi-stage scoring based entirely on classical computed features.
No AI/neural nets/cloud — pure signal processing on per-fragment metrics from the DB.

Algorithm design (based on video quality/highlight-detection research):
────────────────────────────────────────────────────────────────────────
• Sharpness via Laplacian variance: reliable no-reference blur measure
  (already computed by quality_analyzer.py, reused here)
• Per-project percentile calibration: adapts to footage characteristics
  (low-light, telephoto, wide-angle — absolute thresholds fail these)
• Exposure bell curve: soft penalty, not hard cutoff, around 0.50 brightness
• Camera stability: non-linear reward (stable^0.7 amplifies the good)
• Motion quality bell curve: gentle motion (0.3) is montage-ideal;
  static shots get a bonus if very stable (establishing/beauty shots)
• Visual interest: uses cinematic_score as proxy for composition+content
• Dynamic thresholds: p25/p50/p75 percentiles of the project distribution
  ensure we always surface the best available material, regardless of
  absolute quality — and never classify everything as "good" in poor footage

Categories (style-agnostic, pre-montage):
  best   — UMS >= dynamic p75 threshold (≥0.62 absolute floor)
  good   — UMS >= dynamic p50 threshold (≥0.42 absolute floor)
  backup — UMS >= dynamic p25 threshold (≥0.22 absolute floor)
  rejected_by_system — technically broken or below backup threshold

Replacement logic for excluded segments (Step 2):
  1. selected scenes form the primary duration pool
  2. backup scenes form the replacement pool (not shown by default)
  3. if selected duration < target → offer backup scenes as auto-fill
  4. only show warning if backup pool also insufficient
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ── Default calibration used when < 5 fragments are available ────────────────
_DEFAULT_CALIB: Dict[str, float] = {
    'p10_quality':   0.15,
    'p25_quality':   0.30,
    'p50_quality':   0.50,
    'p75_quality':   0.68,
    'p90_quality':   0.80,
    'p50_sharpness': 0.28,
    'n_total':       0.0,
}

# ── Dynamic threshold bounds (prevent being too permissive or too strict) ────
_THR_BEST_MIN,   _THR_BEST_MAX   = 0.62, 0.82
_THR_GOOD_MIN,   _THR_GOOD_MAX   = 0.42, 0.67
_THR_BACKUP_MIN, _THR_BACKUP_MAX = 0.22, 0.48


# ── Public API ────────────────────────────────────────────────────────────────

def calibrate_project_thresholds(fragments: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Compute per-project dynamic thresholds from the fragment quality distribution.

    Why percentile-based: absolute thresholds like min_quality=0.50 silently
    discard good material in legitimately dark, wide-angle, or shallow-DOF
    projects.  Percentile calibration ensures we always find the *best available*
    material rather than demanding an absolute standard that may be wrong.
    """
    valid = [f for f in fragments if (f.get('quality_score') or 0.0) > 0.0]
    if len(valid) < 5:
        return dict(_DEFAULT_CALIB)

    qs = sorted(float(f.get('quality_score') or 0.0) for f in valid)
    sharps = sorted(float(f.get('sharpness') or 0.0) for f in valid)

    def _pct(arr: list, p: float) -> float:
        if not arr:
            return 0.0
        idx = min(int(len(arr) * p / 100.0), len(arr) - 1)
        return float(arr[idx])

    calib = {
        'p10_quality':   _pct(qs, 10),
        'p25_quality':   _pct(qs, 25),
        'p50_quality':   _pct(qs, 50),
        'p75_quality':   _pct(qs, 75),
        'p90_quality':   _pct(qs, 90),
        'p50_sharpness': _pct(sharps, 50),
        'n_total':       float(len(valid)),
    }
    logger.info(
        '[FragmentScorer] Calibration: n=%d  q25=%.3f  q50=%.3f  q75=%.3f  sharp50=%.3f',
        int(calib['n_total']), calib['p25_quality'],
        calib['p50_quality'], calib['p75_quality'], calib['p50_sharpness'],
    )
    return calib


def compute_ums(frag: Dict[str, Any], calib: Dict[str, float]) -> float:
    """
    Universal Montage Score (0–1).  Style-agnostic.

    Answers: "Can this fragment be used in ANY montage?"
    Does NOT depend on target style (sport / cinematic / travel / etc.).

    Components:
      38% — technical quality  (sharpness, exposure, stability, contrast)
      23% — motion quality     (smooth gentle motion vs chaos vs dead-still)
      17% — visual interest    (cinematic, colorfulness, composition, saliency)
      18% — existing pipeline  (already-computed quality_score)
       4% — temporal coherence penalty (internal-cut detection)
    """
    sharpness          = float(frag.get('sharpness')          or 0.0)
    brightness         = float(frag.get('brightness')         or 0.0)
    stability          = float(frag.get('stability')          or 0.0)
    contrast           = float(frag.get('contrast')           or 0.0)
    motion             = float(frag.get('motion')             or 0.0)
    cinematic          = float(frag.get('cinematic_score')    or 0.0)
    quality            = float(frag.get('quality_score')      or 0.0)
    colorfulness       = float(frag.get('colorfulness')       or 0.0)
    composition_score  = float(frag.get('composition_score')  or 0.0)
    temporal_coherence = float(frag.get('temporal_coherence') or 1.0)  # default 1=good
    saliency_score     = float(frag.get('saliency_score')     or 0.0)

    # ── Technical quality ────────────────────────────────────────────────────
    p50_sharp = max(0.05, calib.get('p50_sharpness', 0.28))
    rel_sharp = min(1.0, sharpness / p50_sharp)
    adj_sharp = 0.55 * rel_sharp + 0.45 * sharpness

    exposure_dev = abs(brightness - 0.50) * 1.80
    exposure_q   = max(0.0, 1.0 - exposure_dev) ** 0.65
    stab_q       = stability ** 0.70

    tech_score = (
        0.42 * adj_sharp +
        0.30 * exposure_q +
        0.23 * stab_q +
        0.05 * min(1.0, contrast)
    )

    # ── Motion quality ───────────────────────────────────────────────────────
    motion_dev   = abs(motion - 0.30) / 0.70
    motion_bell  = max(0.0, 1.0 - motion_dev)
    static_bonus = max(0.0, (stability - 0.75) * 1.60)
    motion_q     = max(motion_bell, 0.25 + min(0.50, static_bonus))

    # ── Visual interest ──────────────────────────────────────────────────────
    visual_score = (
        0.45 * cinematic        +
        0.18 * min(1.0, contrast) +
        0.13 * motion_q         +
        0.12 * colorfulness     +
        0.07 * composition_score +
        0.05 * saliency_score
    )

    # ── Temporal coherence penalty ───────────────────────────────────────────
    # Low coherence = colour distribution changes sharply = fragment spans a cut.
    # Soft sigmoid penalty: gentle above 0.70, harsh below 0.40.
    coh_penalty = max(0.0, min(1.0, (temporal_coherence - 0.40) / 0.30))

    # ── Universal Montage Score ──────────────────────────────────────────────
    ums = (
        0.38 * tech_score   +
        0.23 * motion_q     +
        0.17 * visual_score +
        0.18 * quality      +
        0.04 * coh_penalty
    )
    return round(min(1.0, max(0.0, ums)), 4)


def assign_category(ums: float, calib: Dict[str, float], is_rejected: bool = False) -> str:
    """
    Assign fragment category using dynamic project-calibrated thresholds.

    Thresholds are clamped to absolute bounds so that:
      - Good footage in a rich project still has a meaningful 'best' tier
      - Poor footage in a weak project surfaces its best material as 'good/backup'
        rather than marking everything 'rejected'
    """
    if is_rejected:
        return 'rejected_by_system'

    p75 = float(calib.get('p75_quality', 0.68))
    p50 = float(calib.get('p50_quality', 0.50))
    p25 = float(calib.get('p25_quality', 0.30))

    thr_best   = max(_THR_BEST_MIN,   min(_THR_BEST_MAX,   p75))
    thr_good   = max(_THR_GOOD_MIN,   min(_THR_GOOD_MAX,   p50))
    thr_backup = max(_THR_BACKUP_MIN, min(_THR_BACKUP_MAX, p25))

    if ums >= thr_best:    return 'best'
    if ums >= thr_good:    return 'good'
    if ums >= thr_backup:  return 'backup'
    return 'rejected_by_system'


def score_fragments(
    fragments: List[Dict[str, Any]],
) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    """
    Compute UMS + assign categories for all fragments in one pass.

    Returns (calibration_dict, enriched_fragments_list).
    Each fragment in the returned list is a new dict with added fields:
      'ums_score'  float   universal montage score
      'category'   str     best / good / backup / rejected_by_system
    Original dicts are NOT mutated.
    """
    calib = calibrate_project_thresholds(fragments)
    enriched: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {
        'best': 0, 'good': 0, 'backup': 0, 'rejected_by_system': 0,
    }

    for f in fragments:
        ef = dict(f)
        is_rejected = bool(ef.get('is_rejected', False))
        ums = compute_ums(ef, calib)
        cat = assign_category(ums, calib, is_rejected)
        ef['ums_score'] = ums
        ef['category'] = cat
        counts[cat] = counts.get(cat, 0) + 1
        enriched.append(ef)

    logger.info(
        '[FragmentScorer] %d fragments scored: best=%d good=%d backup=%d rejected=%d',
        len(enriched), counts['best'], counts['good'],
        counts['backup'], counts['rejected_by_system'],
    )
    return calib, enriched


def check_material_sufficiency(
    scenes: List[Dict[str, Any]],
    target_duration: float,
    rejected_fids: set,
) -> Dict[str, Any]:
    """
    Compute whether selected material covers the target duration.

    Returns a dict with:
      selected_dur   — duration of best+good scenes not rejected by user
      backup_dur     — duration of backup scenes not rejected by user
      total_dur      — selected + backup
      has_enough     — selected_dur >= target (1.5× safety margin)
      has_with_backup— total_dur >= target
      shortage       — how many seconds short (0 if enough)
      n_best         — count of best scenes
      n_good         — count of good scenes
      n_backup       — count of backup scenes
      n_rejected_user— count of user-rejected scenes
    """
    n_best = n_good = n_backup = n_rej_user = 0
    selected_dur = backup_dur = 0.0

    for s in scenes:
        fids = set(s.get('fragment_ids') or [])
        user_rejected = bool(fids & rejected_fids) if rejected_fids else False
        cat = s.get('category', 'good')
        dur = float(s.get('duration_s', 0.0))

        if user_rejected:
            n_rej_user += 1
            continue

        if cat == 'best':
            n_best += 1
            selected_dur += dur
        elif cat == 'good':
            n_good += 1
            selected_dur += dur
        elif cat == 'backup':
            n_backup += 1
            backup_dur += dur

    need = target_duration * 1.5   # 1.5× safety margin ensures variety for the editor
    total_dur = selected_dur + backup_dur

    return {
        'selected_dur':    round(selected_dur, 1),
        'backup_dur':      round(backup_dur, 1),
        'total_dur':       round(total_dur, 1),
        'target_duration': target_duration,
        # has_enough: selected alone covers 1.5× target (comfortable surplus)
        'has_enough':      selected_dur >= need,
        # has_with_backup: backup bridges the gap to cover at least the bare target
        'has_with_backup': total_dur >= target_duration,
        'shortage':        round(max(0.0, need - selected_dur), 1),
        'n_best':          n_best,
        'n_good':          n_good,
        'n_backup':        n_backup,
        'n_rejected_user': n_rej_user,
    }


def build_diagnostic_report(
    fragments: List[Dict[str, Any]],
    calib: Dict[str, float],
    scenes: List[Dict[str, Any]],
    target_duration: float,
) -> Dict[str, Any]:
    """
    Build a diagnostic report for logging and UI display in _run_prep_analysis.

    Reports per-source fragment counts, scene pool sizes, and material sufficiency.
    """
    source_ids = sorted({f.get('source_id', 0) for f in fragments})
    per_source: Dict[int, Dict[str, int]] = {}
    per_source_path: Dict[int, str] = {}

    for f in fragments:
        sid = int(f.get('source_id') or 0)
        cat = f.get('category', 'rejected_by_system')
        key = 'rejected' if cat == 'rejected_by_system' else cat
        per_source.setdefault(sid, {'best': 0, 'good': 0, 'backup': 0, 'rejected': 0})
        per_source[sid][key] += 1
        if 'source_path' in f and sid not in per_source_path:
            per_source_path[sid] = str(f['source_path'])

    cat_counts = {
        'best':   sum(1 for s in scenes if s.get('category') == 'best'),
        'good':   sum(1 for s in scenes if s.get('category') == 'good'),
        'backup': sum(1 for s in scenes if s.get('category') == 'backup'),
        'total':  len(scenes),
    }

    sufficiency = check_material_sufficiency(scenes, target_duration, set())

    diag: Dict[str, Any] = {
        'n_videos':          len(source_ids),
        'n_raw_fragments':   len(fragments),
        'calib':             calib,
        'per_source':        per_source,
        'per_source_path':   per_source_path,
        'scene_counts':      cat_counts,
        'sufficiency':       sufficiency,
        'target_duration':   target_duration,
    }

    # Log summary
    logger.info(
        '[FragmentScorer] Diagnostic: %d videos, %d raw frags → %d scenes '
        '(best=%d good=%d backup=%d).  Material: %.0fs / %.0fs target',
        diag['n_videos'], diag['n_raw_fragments'],
        cat_counts['total'], cat_counts['best'], cat_counts['good'],
        cat_counts['backup'],
        sufficiency['selected_dur'], target_duration,
    )
    for sid in source_ids:
        pc = per_source.get(sid, {})
        sp = per_source_path.get(sid, f'source_{sid}')
        import os
        fname = os.path.basename(sp)
        logger.info(
            '  Video %s: best=%d good=%d backup=%d rejected=%d',
            fname, pc.get('best', 0), pc.get('good', 0),
            pc.get('backup', 0), pc.get('rejected', 0),
        )
    return diag
