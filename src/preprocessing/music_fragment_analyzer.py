"""
Music fragment analyzer for the preprocessing stage.
Wraps existing music_sync.MusicAnalyzer + AdvancedMusicAnalyzer to produce
montage-worthy segments without duplicating existing logic.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

try:
    from src.music_sync.analyzer import MusicAnalyzer
    from src.music_sync.models import TrackSection, EnergyLevel
    MUSIC_SYNC_AVAILABLE = True
except ImportError:
    MUSIC_SYNC_AVAILABLE = False
    logger.warning('[MusicFragmentAnalyzer] music_sync not available; music preprocessing disabled')

# Map TrackSection enum names to UI fragment types
_SECTION_TO_TYPE: Dict[str, str] = {
    'INTRO':      'intro',
    'BUILDUP':    'buildup',
    'DROP':       'drop',
    'CHORUS':     'peak',
    'VERSE':      'calm',
    'BRIDGE':     'loopable',
    'BREAKDOWN':  'calm',
    'OUTRO':      'outro',
    'UNKNOWN':    'calm',
}

# Russian labels for fragment types
FRAGMENT_TYPE_LABELS: Dict[str, str] = {
    'intro':    'Вступление',
    'buildup':  'Нарастание',
    'drop':     'Дроп / энергичный',
    'peak':     'Кульминация / Припев',
    'calm':     'Спокойный участок',
    'loopable': 'Ритмичный / повторяемый',
    'outro':    'Финал',
}

# Emoji per type
FRAGMENT_TYPE_EMOJI: Dict[str, str] = {
    'intro':    '🌅',
    'buildup':  '📈',
    'drop':     '⚡',
    'peak':     '🔥',
    'calm':     '🌊',
    'loopable': '🔁',
    'outro':    '🏁',
}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def analyze_music_for_preprocessing(
    audio_path: str,
    db,
    force: bool = False,
) -> List[Dict[str, Any]]:
    """
    Analyze audio file and return montage-worthy segments.
    Uses existing MusicAnalyzer (music_sync module) — no new analysis logic.
    Results are cached in DB; pass force=True to re-analyze.

    Returns list of fragment dicts compatible with AnalysisDB.save_music_fragments().
    Empty list when librosa/music_sync unavailable or file missing.
    """
    if not MUSIC_SYNC_AVAILABLE:
        logger.error('[MusicFragmentAnalyzer] music_sync unavailable')
        return []

    audio_file = Path(audio_path)
    if not audio_file.exists():
        logger.error(f'[MusicFragmentAnalyzer] File not found: {audio_path}')
        return []

    if not force and db.is_music_analyzed(audio_path):
        logger.info(f'[MusicFragmentAnalyzer] Cache hit for {audio_file.name}')
        return db.get_music_fragments(audio_path)

    logger.info(f'[MusicFragmentAnalyzer] Analyzing {audio_file.name}')
    try:
        analyzer = MusicAnalyzer(cache_enabled=False)
        analysis = analyzer.analyze(audio_path)
        fragments = _analysis_to_fragments(analysis)
        db.save_music_fragments(audio_path, fragments)
        logger.info(f'[MusicFragmentAnalyzer] {len(fragments)} fragments saved')
        return db.get_music_fragments(audio_path)  # return DB rows so IDs are populated
    except Exception as exc:
        logger.error(f'[MusicFragmentAnalyzer] Failed: {exc}')
        return []


def fragment_type_label(ftype: str) -> str:
    return FRAGMENT_TYPE_LABELS.get(ftype, ftype)


def fragment_type_emoji(ftype: str) -> str:
    return FRAGMENT_TYPE_EMOJI.get(ftype, '🎵')


# ------------------------------------------------------------------
# Conversion: AudioAnalysis → List[fragment dict]
# ------------------------------------------------------------------

def _analysis_to_fragments(analysis) -> List[Dict[str, Any]]:
    fragments = []

    # Primary source: structure sections from AdvancedMusicAnalyzer
    if analysis.structure_sections:
        for sec in analysis.structure_sections:
            if sec.duration < 5.0:
                continue
            ftype = _SECTION_TO_TYPE.get(sec.section_type.name, 'calm')
            energy   = _section_energy(sec.start_time, sec.end_time, analysis)
            rhythm   = _section_rhythm(sec.start_time, sec.end_time, analysis)
            beat_cl  = _section_beat_clarity(sec.start_time, sec.end_time, analysis)
            score    = _montage_score(ftype, energy, rhythm, beat_cl, sec, analysis)
            fragments.append({
                'start_s':          sec.start_time,
                'end_s':            sec.end_time,
                'duration_s':       sec.duration,
                'fragment_type':    ftype,
                'energy_score':     round(energy, 3),
                'rhythm_score':     round(rhythm, 3),
                'beat_clarity':     round(beat_cl, 3),
                'montage_score':    round(score, 3),
                'reason':           _reason(ftype, energy, rhythm, beat_cl),
                'warnings':         _warnings(sec.duration, energy),
                'selected_by_system': int(score >= 0.60),
                'excluded_by_user': 0,
                'status':           'recommended',
            })

    # Fallback: energy sections when structure detection found nothing
    if not fragments and analysis.energy_sections:
        for sec in analysis.energy_sections:
            if sec.duration < 8.0:
                continue
            if MUSIC_SYNC_AVAILABLE:
                ftype = (
                    'drop' if sec.energy_level == EnergyLevel.HIGH else
                    ('calm' if sec.energy_level == EnergyLevel.LOW else 'intro')
                )
            else:
                ftype = 'calm'
            energy   = sec.avg_energy
            rhythm   = _section_rhythm(sec.start_time, sec.end_time, analysis)
            beat_cl  = _section_beat_clarity(sec.start_time, sec.end_time, analysis)
            score    = energy * 0.5 + rhythm * 0.3 + beat_cl * 0.2
            fragments.append({
                'start_s':          sec.start_time,
                'end_s':            sec.end_time,
                'duration_s':       sec.duration,
                'fragment_type':    ftype,
                'energy_score':     round(energy, 3),
                'rhythm_score':     round(rhythm, 3),
                'beat_clarity':     round(beat_cl, 3),
                'montage_score':    round(score, 3),
                'reason':           _reason(ftype, energy, rhythm, beat_cl),
                'warnings':         _warnings(sec.duration, energy),
                'selected_by_system': int(score >= 0.55),
                'excluded_by_user': 0,
                'status':           'recommended',
            })

    # Sort by score, tag the best
    fragments.sort(key=lambda x: x['montage_score'], reverse=True)
    if fragments:
        fragments[0]['status'] = 'best'

    return fragments


# ------------------------------------------------------------------
# Metric helpers (reuse AudioAnalysis data, no new calculations)
# ------------------------------------------------------------------

def _section_energy(start: float, end: float, analysis) -> float:
    """Relative mean RMS energy in this time window (0–1 relative to track max)."""
    curve = analysis.energy_curve
    if not curve or analysis.duration <= 0:
        return 0.5
    n = len(curve)
    dur = analysis.duration
    i0 = max(0, int(start / dur * n))
    i1 = min(n, max(i0 + 1, int(end / dur * n)))
    window = curve[i0:i1]
    if not window:
        return 0.5
    mx = max(curve)
    return float(sum(window) / len(window) / mx) if mx > 0 else 0.5


def _section_rhythm(start: float, end: float, analysis) -> float:
    """Beat density in section normalised to [0, 1] (3 beats/s = 1.0)."""
    if not analysis.beat_times:
        return 0.0
    dur = end - start
    if dur <= 0:
        return 0.0
    count = sum(1 for t in analysis.beat_times if start <= t <= end)
    return min(1.0, count / dur / 3.0)


def _section_beat_clarity(start: float, end: float, analysis) -> float:
    """Mean beat strength in section (already normalised 0–1 by MusicAnalyzer)."""
    if not analysis.beat_points:
        return 0.0
    strengths = [b.strength for b in analysis.beat_points if start <= b.time <= end]
    if not strengths:
        return 0.0
    return min(1.0, sum(strengths) / len(strengths))


def _montage_score(ftype: str, energy: float, rhythm: float, beat_cl: float, section, analysis) -> float:
    base = energy * 0.40 + rhythm * 0.35 + beat_cl * 0.25
    type_bonus = {'drop': 0.10, 'peak': 0.10, 'buildup': 0.06, 'intro': 0.05,
                  'outro': 0.03, 'loopable': 0.02, 'calm': 0.0}.get(ftype, 0.0)
    peak_bonus = 0.0
    for pt in getattr(analysis, 'peak_times', []):
        if section.start_time <= pt <= section.end_time:
            peak_bonus = 0.08
            break
    return min(1.0, base + type_bonus + peak_bonus)


def _reason(ftype: str, energy: float, rhythm: float, beat_cl: float) -> str:
    parts = {
        'intro':    'хорошее вступление',
        'buildup':  'нарастающая динамика',
        'drop':     'энергичный дроп',
        'peak':     'кульминация трека',
        'calm':     'спокойный фрагмент',
        'outro':    'хороший финал',
        'loopable': 'стабильный ритмичный участок',
    }
    desc = [parts.get(ftype, 'подходит для монтажа')]
    if energy > 0.70:
        desc.append('высокая энергия')
    if beat_cl > 0.70:
        desc.append('чёткий ритм')
    elif rhythm > 0.60:
        desc.append('плотный ритм')
    return '; '.join(desc)


def _warnings(duration: float, energy: float) -> str:
    w = []
    if duration < 10.0:
        w.append('короткий участок')
    if energy < 0.15:
        w.append('очень тихий')
    return '; '.join(w)
