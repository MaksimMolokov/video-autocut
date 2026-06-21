"""Suggest montage style based on music energy and tempo (librosa)."""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class MusicProfile:
    tempo: float
    energy: float
    spectral_centroid: float   # brightness of sound
    spectral_rolloff: float    # high-frequency presence
    zero_crossing_rate: float  # percussive noise level
    duration_s: float


@dataclass
class StyleSuggestion:
    style_id: str
    name: str
    reason: str
    confidence: float  # 0.0–1.0


def analyze_music(music_path: str) -> Optional[MusicProfile]:
    """Extract tempo and energy descriptors from an audio file."""
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(music_path, mono=True, duration=120.0)
        tempo_arr, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo = float(tempo_arr) if hasattr(tempo_arr, '__float__') else float(tempo_arr[0])

        energy = float(librosa.feature.rms(y=y).mean())
        centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
        rolloff = float(librosa.feature.spectral_rolloff(y=y, sr=sr).mean())
        zcr = float(librosa.feature.zero_crossing_rate(y).mean())
        duration_s = float(len(y) / sr)

        return MusicProfile(
            tempo=tempo,
            energy=energy,
            spectral_centroid=centroid,
            spectral_rolloff=rolloff,
            zero_crossing_rate=zcr,
            duration_s=duration_s,
        )
    except Exception as e:
        logger.warning(f'[MusicStyleAdvisor] Cannot analyze {music_path}: {e}')
        return None


def suggest_styles(profile: MusicProfile) -> List[StyleSuggestion]:
    """
    Map music characteristics to ordered list of style suggestions (best first).
    """
    suggestions: List[Tuple[float, StyleSuggestion]] = []

    t = profile.tempo
    e = profile.energy
    c = profile.spectral_centroid

    # F4: Impact Sport — fast tempo, high energy, percussive
    f4_score = 0.0
    if t > 128:
        f4_score += 0.4
    elif t > 110:
        f4_score += 0.2
    if e > 0.08:
        f4_score += 0.35
    elif e > 0.05:
        f4_score += 0.15
    if c > 3000:
        f4_score += 0.25
    suggestions.append((f4_score, StyleSuggestion(
        style_id='f4',
        name='F4 Impact Sport',
        reason=f'{t:.0f} BPM, высокая энергия → динамичный монтаж',
        confidence=round(min(1.0, f4_score), 2),
    )))

    # F3: Urban Pulse — medium-fast, energetic, urban/electronic
    f3_score = 0.0
    if 100 < t <= 135:
        f3_score += 0.4
    elif 85 < t <= 100:
        f3_score += 0.2
    if 0.04 < e <= 0.09:
        f3_score += 0.35
    if c > 2500:
        f3_score += 0.25
    suggestions.append((f3_score, StyleSuggestion(
        style_id='f3',
        name='F3 Urban Pulse',
        reason=f'{t:.0f} BPM, яркий звук → городской ритмичный монтаж',
        confidence=round(min(1.0, f3_score), 2),
    )))

    # F2: Cinematic — mid tempo, moderate energy, smooth
    f2_score = 0.0
    if 75 < t <= 115:
        f2_score += 0.4
    elif t <= 75:
        f2_score += 0.15
    if 0.02 < e <= 0.065:
        f2_score += 0.35
    if c < 2800:
        f2_score += 0.25
    suggestions.append((f2_score, StyleSuggestion(
        style_id='f2',
        name='F2 Cinematic Velocity',
        reason=f'{t:.0f} BPM, умеренная энергия → кинематографичный монтаж',
        confidence=round(min(1.0, f2_score), 2),
    )))

    # F5: Premium Brand — slow, very low energy, clean
    f5_score = 0.0
    if t < 90:
        f5_score += 0.4
    if e < 0.04:
        f5_score += 0.4
    if c < 2000:
        f5_score += 0.2
    suggestions.append((f5_score, StyleSuggestion(
        style_id='f5',
        name='F5 Premium Brand',
        reason=f'{t:.0f} BPM, тихая атмосферная музыка → премиум-плавный монтаж',
        confidence=round(min(1.0, f5_score), 2),
    )))

    # F6: Dream Travel — slow/mid tempo, warm, atmospheric
    f6_score = 0.0
    if t < 110:
        f6_score += 0.35
    if 0.01 < e < 0.06:
        f6_score += 0.35
    if profile.zero_crossing_rate < 0.06:
        f6_score += 0.30   # low noise = clean atmospheric track
    suggestions.append((f6_score, StyleSuggestion(
        style_id='f6',
        name='F6 Dream Travel',
        reason=f'{t:.0f} BPM, атмосферная музыка → travel-монтаж',
        confidence=round(min(1.0, f6_score), 2),
    )))

    suggestions.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in suggestions]


def get_top_suggestions(music_path: str, n: int = 2) -> List[StyleSuggestion]:
    profile = analyze_music(music_path)
    if profile is None:
        return []
    all_sug = suggest_styles(profile)
    return all_sug[:n]


def format_suggestion(s: StyleSuggestion) -> str:
    bar = '█' * int(s.confidence * 10) + '░' * (10 - int(s.confidence * 10))
    return f'{s.name}  [{bar}] {s.confidence:.0%}  — {s.reason}'
