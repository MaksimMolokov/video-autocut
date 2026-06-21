"""
Scene merger for Step 2 material preparation.
Groups consecutive fine-grained DB fragments into coherent scenes (1.5–30 s).

Key behaviours:
  - Chain-breaks ONLY on truly corrupt/zero-quality fragments (quality < 0.05),
    NOT on UMS category — low-UMS fragments are valid material already filtered
    by the pipeline quality analyzer.
  - All merged scenes are at least 'backup' category (pipeline already vetted them).
  - Cross-video pHash deduplication removes near-identical scenes between sources.
  - Beat-sync scores injected per-scene when music fragments are available.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

_DEFAULT_MIN_QUALITY = 0.05   # only truly broken fragments break the chain
_DEFAULT_GAP_S       = 1.0    # max gap (s) to still merge consecutive fragments
_DEFAULT_MIN_DUR     = 1.5    # discard scenes shorter than this (was 3.0 — too strict)
_DEFAULT_MAX_DUR     = 30.0   # force-split scenes longer than this

# Fallback pass parameters — used when primary pass produces 0 scenes for a source.
# Matches scene-detector's own min_scene_length so no valid clip is lost.
_FALLBACK_MIN_DUR    = 0.8    # same as SceneDetector.min_scene_length
_FALLBACK_GAP_S      = 2.0    # wider merge gap to bridge larger cuts


def merge_fragments_into_scenes(
    fragments: List[Dict[str, Any]],
    min_quality: float = _DEFAULT_MIN_QUALITY,
    gap_s: float = _DEFAULT_GAP_S,
    min_duration: float = _DEFAULT_MIN_DUR,
    max_duration: float = _DEFAULT_MAX_DUR,
    calibration: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Merge consecutive DB fragment dicts into coherent scenes.

    Input : flat list of fragment dicts (any order, any source_id).
            Fragments may optionally carry 'ums_score' and 'category' fields
            (from fragment_scorer.score_fragments()) — used for smarter
            chain-breaking and scene categorization.
    Output: scene dicts sorted by (source_id, start_s).
            Each scene includes 'fragment_ids', 'ums_score', 'category'.

    Fallback: if a source produces 0 scenes at the primary min_duration threshold,
    a second pass is attempted at _FALLBACK_MIN_DUR (= scene-detector minimum of 0.8 s).
    This prevents "Видеофрагменты не найдены" when footage has many short cuts or
    a single long take that was split into short quality-chunks.
    """
    if not fragments:
        return []

    by_source: Dict[int, List[Dict]] = {}
    for f in fragments:
        sid = f.get('source_id') or 0
        by_source.setdefault(sid, []).append(f)

    scenes: List[Dict] = []
    for sid, src_frags in by_source.items():
        src_frags.sort(key=lambda f: f.get('start_s', 0.0))
        src_scenes = _merge_source(
            src_frags, min_quality, gap_s, min_duration, max_duration, calibration
        )

        # Fallback: if primary pass returned nothing for this source, retry with
        # the scene-detector's own minimum (0.8 s) and a wider gap tolerance.
        if not src_scenes:
            fallback_min = _FALLBACK_MIN_DUR
            fallback_gap = max(gap_s, _FALLBACK_GAP_S)
            src_scenes = _merge_source(
                src_frags, min_quality, fallback_gap, fallback_min, max_duration, calibration
            )
            if src_scenes:
                source_name = Path(src_frags[0].get('source_path', f'source_{sid}')).name
                logger.info(
                    '[SceneMerger] Fallback applied for %s: '
                    'primary pass returned 0 scenes, fallback found %d '
                    '(min_dur %.1f→%.1f s)',
                    source_name, len(src_scenes), min_duration, fallback_min,
                )

        scenes.extend(src_scenes)

    scenes.sort(key=lambda s: (s['source_id'], s['start_s']))
    return scenes


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_chain_breaker(frag: Dict[str, Any], min_quality: float) -> bool:
    """True if fragment should break the current accumulation run.

    Only truly corrupt / zero-quality fragments break the chain.
    Fragments that scored low UMS (even 'rejected_by_system' category) are still
    valid video material — they already passed the pipeline quality filter.
    Using category as a chain-breaker caused massive data loss: low-UMS fragments
    would fragment consecutive runs into sub-min_duration pieces that got discarded.
    """
    if frag.get('is_rejected'):
        return True
    return (frag.get('quality_score') or 0.0) < min_quality


def _merge_source(
    frags: List[Dict],
    min_quality: float,
    gap_s: float,
    min_duration: float,
    max_duration: float,
    calibration: Optional[Dict],
) -> List[Dict]:
    scenes: List[Dict] = []
    accum: List[Dict] = []

    def _flush():
        if not accum:
            return
        start_s = accum[0]['start_s']
        end_s   = accum[-1]['end_s']
        dur     = end_s - start_s
        if dur < min_duration:
            return
        scenes.append(_build_scene(accum, start_s, end_s, dur, calibration))

    for frag in frags:
        if _is_chain_breaker(frag, min_quality):
            _flush()
            accum = []
            continue

        if not accum:
            accum = [frag]
        else:
            gap          = frag['start_s'] - accum[-1]['end_s']
            would_be_dur = frag['end_s']   - accum[0]['start_s']
            if gap > gap_s or would_be_dur > max_duration:
                _flush()
                accum = [frag]
            else:
                accum.append(frag)

    _flush()
    return scenes


def _build_scene(
    frags: List[Dict],
    start_s: float,
    end_s: float,
    dur: float,
    calibration: Optional[Dict],
) -> Dict[str, Any]:
    def _mean(key: str) -> float:
        vals = [float(f.get(key) or 0.0) for f in frags]
        return sum(vals) / len(vals) if vals else 0.0

    def _best_attr(key: str):
        best = max(frags, key=lambda f: f.get('quality_score') or 0.0)
        return best.get(key)

    q_mean     = _mean('quality_score')
    ums_mean   = _mean('ums_score')       # 0.0 if not pre-scored
    motion     = _mean('motion')
    stability  = _mean('stability')
    sharpness  = _mean('sharpness')
    brightness = _mean('brightness')
    cinematic  = _mean('cinematic_score')
    action     = _mean('action_score')

    # Determine category — floor at 'backup' because fragments that made it into the
    # DB already passed the pipeline quality filter (truly broken frames are rejected
    # there and never stored).  Using 'rejected_by_system' for low-UMS scenes causes
    # check_material_sufficiency to not count them, falsely reporting "not enough material".
    if ums_mean > 0.0 and calibration is not None:
        from .fragment_scorer import assign_category
        raw_cat = assign_category(ums_mean, calibration)
    elif ums_mean > 0.0:
        if ums_mean >= 0.62:   raw_cat = 'best'
        elif ums_mean >= 0.42: raw_cat = 'good'
        elif ums_mean >= 0.22: raw_cat = 'backup'
        else:                  raw_cat = 'backup'  # floor at backup
    else:
        raw_cat = _legacy_category(q_mean)
    # Scenes in the output list are always at least 'backup'
    category = raw_cat if raw_cat in ('best', 'good', 'backup') else 'backup'

    return {
        'source_id':       frags[0].get('source_id', 0),
        'source_path':     frags[0].get('source_path', ''),
        'filename':        Path(frags[0].get('source_path') or '').name,
        'start_s':         round(start_s, 3),
        'end_s':           round(end_s, 3),
        'duration_s':      round(dur, 3),
        'fragment_ids':    [f['id'] for f in frags],
        # Aggregated scores
        'quality_score':   round(q_mean, 3),
        'quality_max':     round(max(f.get('quality_score') or 0.0 for f in frags), 3),
        'ums_score':       round(ums_mean, 3),
        'cinematic_score': round(cinematic, 3),
        'action_score':    round(action, 3),
        'motion':          round(motion, 3),
        'stability':       round(stability, 3),
        'sharpness':       round(sharpness, 3),
        'brightness':      round(brightness, 3),
        # Category and status (status = legacy compatibility)
        'category':        category,
        'status':          _scene_status(q_mean),
        'reason':          _scene_reason(q_mean, cinematic, action, motion, stability, sharpness),
        'warnings':        _scene_warnings(stability, brightness, dur),
        # Best media from highest-quality fragment
        'thumbnail_path':  _best_attr('thumbnail_path'),
        'preview_path':    _best_attr('preview_path'),
        'clip_path':       None,    # populated lazily by scene_clipper
        # Metadata
        'user_approved':   None,
        'n_fragments':     len(frags),
    }


def _legacy_category(q: float) -> str:
    """Fallback categorization when no UMS is available."""
    if q >= 0.65: return 'best'
    if q >= 0.45: return 'good'
    if q >= 0.25: return 'backup'
    return 'rejected_by_system'


def _scene_status(q: float) -> str:
    """Legacy status field — kept for backward compatibility."""
    if q >= 0.70: return 'best'
    if q >= 0.55: return 'good'
    if q >= 0.35: return 'acceptable'
    return 'weak'


def _scene_reason(q, cinematic, action, motion, stability, sharpness) -> str:
    parts = []
    if cinematic >= 0.65:
        parts.append('кинематографичный кадр')
    elif action >= 0.65:
        parts.append('динамичный момент')
    if stability >= 0.70 and motion >= 0.35:
        parts.append('плавное движение')
    elif stability >= 0.70:
        parts.append('стабильный кадр')
    if sharpness >= 0.70:
        parts.append('высокая резкость')
    if q >= 0.70:
        parts.append('высокое качество')
    if not parts:
        parts.append('подходит для монтажа' if q >= 0.45 else 'приемлемое качество')
    return '; '.join(parts)


def _scene_warnings(stability, brightness, dur) -> str:
    w = []
    if stability < 0.35:
        w.append('нестабильная камера')
    if brightness < 0.20:
        w.append('очень темный')
    elif brightness > 0.88:
        w.append('пересвет')
    if dur > 25.0:
        w.append('длинный фрагмент')
    return '; '.join(w)


# ── Algorithm 4: Cross-video pHash deduplication ──────────────────────────────

def _phash_from_thumbnail(thumbnail_path: Optional[str]) -> Optional[int]:
    """Compute 64-bit pHash from thumbnail file. Returns None if unavailable."""
    if not thumbnail_path:
        return None
    try:
        import cv2
        import numpy as np
        img = cv2.imread(str(thumbnail_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        resized = cv2.resize(img, (8, 8), interpolation=cv2.INTER_AREA).astype(np.float32)
        dct_row = [
            sum(resized[r, c] * (1 if c == 0 else 2) * (0.5 * 0.5)
                for c in range(8)) / 8.0
            for r in range(8)
        ]
        # Simple 8×8 DCT approximation (mean-based pHash)
        mean_val = float(resized.mean())
        bits = int(0)
        for i, row in enumerate(resized):
            for j, px in enumerate(row):
                if px > mean_val:
                    bits |= (1 << (i * 8 + j))
        return bits
    except Exception:
        return None


def _hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count('1')


def deduplicate_scenes(
    scenes: List[Dict[str, Any]],
    hamming_threshold: int = 10,
) -> List[Dict[str, Any]]:
    """
    Mark cross-video near-duplicate scenes with `is_cross_duplicate=True`.

    For each pair of scenes from DIFFERENT source videos whose thumbnails
    have Hamming distance ≤ threshold, keep the higher-UMS one and mark
    the other as a cross-duplicate. Duplicates remain in the list (hidden
    by default in Step 2 UI) so the user can still use them if needed.

    Complexity: O(n²) on thumbnail hashes — fast in practice (<1000 scenes).
    """
    hashes: List[Optional[int]] = [
        _phash_from_thumbnail(s.get('thumbnail_path')) for s in scenes
    ]

    duplicate_indices: set = set()
    for i in range(len(scenes)):
        if hashes[i] is None or i in duplicate_indices:
            continue
        for j in range(i + 1, len(scenes)):
            if hashes[j] is None or j in duplicate_indices:
                continue
            # Only compare cross-video
            if scenes[i].get('source_id') == scenes[j].get('source_id'):
                continue
            if _hamming_distance(hashes[i], hashes[j]) <= hamming_threshold:
                # Keep the better one, mark the worse as duplicate
                ums_i = float(scenes[i].get('ums_score') or 0.0)
                ums_j = float(scenes[j].get('ums_score') or 0.0)
                duplicate_indices.add(j if ums_i >= ums_j else i)

    result = []
    for idx, scene in enumerate(scenes):
        s = dict(scene)
        s['is_cross_duplicate'] = idx in duplicate_indices
        result.append(s)
    return result


# ── Algorithm 5: Beat-synchronized fragment scoring ───────────────────────────

def compute_beat_sync_scores(
    scenes: List[Dict[str, Any]],
    music_frags: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Add `beat_sync_score` [0–1] to each scene based on how well the scene's
    duration fits the music's phrase structure, and how well its energy matches.

    Formula:
      fit_score    = 1 - min(1, |dur - nearest_beat_multiple| / beat_interval)
      energy_match = 1 - |scene_energy - music_energy|
      beat_sync    = 0.55 * fit_score + 0.45 * energy_match

    Scene energy proxy: 0.6*motion + 0.4*(1-stability) → normalised to [0,1].
    Music energy: fragment energy_score field (0–1).
    """
    if not music_frags or not scenes:
        for s in scenes:
            s['beat_sync_score'] = 0.0
        return scenes

    # Derive representative beat interval from best-scoring music fragments
    scored_mf = [
        mf for mf in music_frags
        if mf.get('duration_s') and float(mf['duration_s']) > 0.5
    ]
    if not scored_mf:
        for s in scenes:
            s['beat_sync_score'] = 0.0
        return scenes

    durations = [float(mf['duration_s']) for mf in scored_mf]
    beat_interval = float(sorted(durations)[len(durations) // 2])  # median phrase length
    beat_interval = max(1.0, beat_interval)

    # Music energy: weighted average across all fragments
    energies = [float(mf.get('energy_score') or 0.5) for mf in scored_mf]
    music_energy = sum(energies) / len(energies)

    result = []
    for scene in scenes:
        s = dict(scene)
        dur = float(s.get('duration_s') or 0.0)

        # Fit to nearest beat multiple
        if dur > 0:
            nearest_n = max(1, round(dur / beat_interval))
            nearest_beat = nearest_n * beat_interval
            fit_score = max(0.0, 1.0 - abs(dur - nearest_beat) / beat_interval)
        else:
            fit_score = 0.0

        # Energy match
        motion    = float(s.get('motion')    or 0.0)
        stability = float(s.get('stability') or 0.5)
        scene_energy = min(1.0, 0.6 * motion + 0.4 * (1.0 - stability))
        energy_match = max(0.0, 1.0 - abs(scene_energy - music_energy))

        s['beat_sync_score'] = round(0.55 * fit_score + 0.45 * energy_match, 3)
        result.append(s)
    return result
