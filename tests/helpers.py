"""
Shared test utilities and synthetic media generation.

Used by all test modules that require real video/audio files.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

# Env flag: set RUN_INTEGRATION_TESTS=0 to skip FFmpeg render tests
RUN_INTEGRATION = os.environ.get('RUN_INTEGRATION_TESTS', '1') == '1'

FFMPEG   = 'ffmpeg'
FFPROBE  = 'ffprobe'

ALL_14_STYLE_IDS = [
    'easy_mode', 'intelligent_beauty_mix', 'drone_nature_cinematic',
    'drone_landscape_clean', 'fast_action_sport', 'urban_city_rhythm',
    'social_media_punchy', 'business_promo_clean', 'real_estate_property_tour',
    'travel_story', 'event_highlights', 'calm_minimal_documentary',
    'sport_dynamic_cut', 'sport_highlight_impact',
    'f1', 'f2', 'f3', 'f4', 'f5', 'f6',
]

# Styles that go through TimelineBuilder (not EasyClipSelector)
TIMELINE_STYLE_IDS = [s for s in ALL_14_STYLE_IDS if s != 'easy_mode']

# Expected transition style groups (for transition tests)
CROSSFADE_STYLES  = {'intelligent_beauty_mix', 'drone_nature_cinematic',
                     'drone_landscape_clean', 'business_promo_clean',
                     'real_estate_property_tour', 'travel_story'}
FLASH_STYLES      = {'fast_action_sport', 'social_media_punchy',
                     'sport_dynamic_cut', 'sport_highlight_impact', 'event_highlights'}
ZOOM_STYLES       = {'urban_city_rhythm'}
FADE_STYLES       = {'calm_minimal_documentary'}
CUT_STYLES        = {'easy_mode'}


def ffmpeg_available() -> bool:
    try:
        subprocess.run([FFMPEG, '-version'], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def create_synthetic_video(
    path: str,
    duration: float = 20.0,
    width: int = 1280,
    height: int = 720,
    color: str = 'blue',
    fps: int = 30,
    motion: bool = False,
) -> bool:
    """Create a synthetic solid-color (or moving) video using FFmpeg."""
    if motion:
        # Use testsrc which has built-in animation (moving text/colors)
        source = f"testsrc=size={width}x{height}:rate={fps}"
    else:
        source = f"color=c={color}:s={width}x{height}:r={fps}"

    cmd = [
        FFMPEG, '-y', '-f', 'lavfi', '-i', source,
        '-t', str(duration),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-preset', 'ultrafast', '-crf', '28',
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    return r.returncode == 0


def create_synthetic_audio(
    path: str,
    duration: float = 30.0,
    freq: float = 440.0,
) -> bool:
    """Create a synthetic sine wave audio file."""
    cmd = [
        FFMPEG, '-y', '-f', 'lavfi',
        '-i', f'sine=frequency={freq}:duration={duration}',
        '-c:a', 'aac', '-b:a', '128k',
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    return r.returncode == 0


def probe_file(path: str) -> dict:
    """Run ffprobe and return full stream+format info as dict."""
    cmd = [
        FFPROBE, '-v', 'error',
        '-show_entries', 'format=duration,bit_rate:stream=codec_type,width,height,duration,r_frame_rate',
        '-of', 'json', str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def get_video_duration(path: str) -> float:
    """Return video stream duration via ffprobe, or 0.0 on error."""
    info = probe_file(path)
    for s in info.get('streams', []):
        if s.get('codec_type') == 'video':
            return float(s.get('duration') or 0)
    return float(info.get('format', {}).get('duration') or 0)


def get_audio_duration(path: str) -> float:
    """Return audio stream duration via ffprobe, or 0.0 on error."""
    info = probe_file(path)
    for s in info.get('streams', []):
        if s.get('codec_type') == 'audio':
            return float(s.get('duration') or 0)
    return 0.0


def get_resolution(path: str):
    """Return (width, height) of first video stream."""
    info = probe_file(path)
    for s in info.get('streams', []):
        if s.get('codec_type') == 'video':
            return int(s.get('width', 0)), int(s.get('height', 0))
    return (0, 0)


# ---------------------------------------------------------------------------
# Minimal stubs for CandidateClip / ClipFeatures (no video_analysis import)
# ---------------------------------------------------------------------------

@dataclass
class StubFeatures:
    sharpness_score:         float = 0.5
    brightness_score:        float = 0.5
    contrast_score:          float = 0.5
    motion_score:            float = 0.5
    camera_stability_score:  float = 0.5
    visual_complexity_score: float = 0.5
    scene_change_score:      float = 0.1
    color_saturation_score:  float = 0.5
    color_diversity_score:   float = 0.5
    action_score:            float = 0.5
    calm_score:              float = 0.5
    technical_quality_score: float = 0.5
    uniqueness_score:        float = 0.5


@dataclass
class StubCandidate:
    source_path: str   = '/fake/video.mp4'
    start:       float = 0.0
    end:         float = 5.0
    duration:    float = 5.0
    is_must_use: bool  = False
    final_score: float = 0.5
    features:    StubFeatures = field(default_factory=StubFeatures)


def make_candidates(
    n: int = 10,
    duration: float = 5.0,
    start_offset: float = 5.0,
    **feat_overrides,
) -> list:
    """Create n StubCandidate objects with varying scores."""
    clips = []
    for i in range(n):
        f = StubFeatures(**feat_overrides) if feat_overrides else StubFeatures()
        c = StubCandidate(
            source_path=f'/fake/v{i % 3}.mp4',
            start=float(i * (duration + 1) + start_offset),
            end=float(i * (duration + 1) + start_offset + duration),
            duration=duration,
            is_must_use=False,
            final_score=float(i + 1) / (n + 1),
            features=f,
        )
        clips.append(c)
    return clips
