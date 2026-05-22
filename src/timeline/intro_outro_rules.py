"""
Per-style intro/outro rules.

Each style declares:
  - how to score/select the opening and closing video segments
  - which segments are forbidden at start/end
  - which video transitions to apply at start/end
  - how to pick audio start/end points

Architectural rule: no style sets output format or target duration.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class VideoIntroRule:
    """Rules for selecting and rendering the opening video segment."""

    # Scoring weights keyed by ClipFeatures field name.
    # Positive = prefer; negative = penalize.
    weights: Dict[str, float] = field(default_factory=dict)

    # Conditions that disqualify a clip from being the intro.
    # Tokens: 'black_frame','blur','shaky','no_subject','high_motion','low_motion',
    #         'camera_starting','scene_change','low_action','low_brightness'
    forbidden: List[str] = field(default_factory=list)

    # Hard thresholds — clips below/above are excluded before scoring.
    min_sharpness:   float = 0.25
    min_brightness:  float = 0.15
    min_action:      float = 0.0   # some styles need action at start
    max_calm:        float = 1.0   # sports styles ban calm intros
    min_stability:   float = 0.0   # cinematic styles prefer stability

    # Skip the first N seconds of any source clip (camera just turned on).
    skip_source_start_sec: float = 1.0

    # FFmpeg transition applied to the very first extracted segment.
    # Tokens: 'clean_cut','fade_in','beat_flash','zoom_in','cinematic_crossfade'
    start_transition: str = 'clean_cut'
    start_transition_duration: float = 0.0   # seconds for fade/crossfade


@dataclass
class VideoOutroRule:
    """Rules for selecting and rendering the closing video segment."""

    weights: Dict[str, float] = field(default_factory=dict)
    forbidden: List[str] = field(default_factory=list)

    min_sharpness:  float = 0.25
    min_brightness: float = 0.15
    min_action:     float = 0.0
    max_shakiness:  float = 1.0

    # Skip the last N seconds of any source clip (camera being lowered).
    skip_source_end_sec: float = 1.0

    # FFmpeg transition applied to the very last extracted segment.
    # Tokens: 'clean_cut','fade_out','beat_cut','flash_impact',
    #         'freeze_final','cinematic_fade'
    end_transition: str = 'fade_out'
    end_transition_duration: float = 0.8


@dataclass
class AudioIntroRule:
    """Rules for choosing where in the audio track to start."""

    # 'phrase_start'  — first low-energy boundary after avoid_sec
    # 'beat_start'    — next beat after avoid_sec
    # 'drop_start'    — next high-energy onset after avoid_sec
    # 'soft_fade'     — anywhere, just add fade-in
    # 'from_start'    — beginning of track (Easy mode)
    mode: str = 'phrase_start'

    fade_in_sec: float = 1.0
    avoid_first_sec: float = 5.0    # skip track intro (silence / DJ tag)
    prefer_energy: bool = False
    prefer_stability: bool = True


@dataclass
class AudioOutroRule:
    """Rules for choosing where in the audio track to end."""

    # 'phrase_fade_end'  — fade out finishing on a phrase boundary
    # 'beat_cut_end'     — hard cut on beat
    # 'punch_end'        — very short fade on a strong beat/accent
    # 'soft_fade_end'    — anywhere, gentle fade
    mode: str = 'phrase_fade_end'

    fade_out_sec: float = 1.5
    avoid_last_sec: float = 5.0     # skip track outro (silence / DJ outro)


@dataclass
class IntroOutroProfile:
    """Complete intro/outro configuration for one style."""

    preset_id: str
    video_intro: VideoIntroRule
    video_outro: VideoOutroRule
    audio_intro: AudioIntroRule
    audio_outro: AudioOutroRule

    # Narrative structure type (used by TimelineBuilder for body ordering).
    # 'simple'          — no special ordering
    # 'story_arc'       — calm → development → climax → resolution
    # 'energy_peak'     — ramp up → peak → short outro
    # 'buildup_impact'  — buildup → explosive climax (sports)
    # 'beauty_arc'      — good → better → best (visual quality growth)
    narrative: str = 'simple'


# ── Helper ────────────────────────────────────────────────────────────────────

def _w(**kw) -> Dict[str, float]:
    return dict(kw)


# ── Per-style profiles ────────────────────────────────────────────────────────

STYLE_PROFILES: Dict[str, IntroOutroProfile] = {

    # ── 1. Easy ────────────────────────────────────────────────────────────────
    "easy_mode": IntroOutroProfile(
        preset_id="easy_mode",
        video_intro=VideoIntroRule(
            weights=_w(sharpness_score=1.2, brightness_score=1.0,
                       technical_quality_score=1.0),
            forbidden=['black_frame', 'blur', 'camera_starting'],
            min_sharpness=0.20, min_brightness=0.15,
            skip_source_start_sec=0.5,
            start_transition='clean_cut',
        ),
        video_outro=VideoOutroRule(
            weights=_w(camera_stability_score=1.2, sharpness_score=1.0,
                       brightness_score=0.8),
            forbidden=['black_frame', 'blur', 'camera_ending'],
            skip_source_end_sec=0.5,
            end_transition='fade_out', end_transition_duration=0.8,
        ),
        audio_intro=AudioIntroRule(mode='soft_fade', fade_in_sec=1.5,
                                   avoid_first_sec=0.0),
        audio_outro=AudioOutroRule(mode='soft_fade_end', fade_out_sec=2.0),
        narrative='simple',
    ),

    # ── 2. Intelligent Beauty Mix ──────────────────────────────────────────────
    "intelligent_beauty_mix": IntroOutroProfile(
        preset_id="intelligent_beauty_mix",
        video_intro=VideoIntroRule(
            weights=_w(
                sharpness_score=1.3, brightness_score=1.0,
                camera_stability_score=1.2, uniqueness_score=1.1,
                color_saturation_score=0.9,
                motion_score=-0.3,       # prefer calm establishing shot
                action_score=-0.4,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_starting',
                       'low_brightness'],
            min_sharpness=0.30, min_brightness=0.20, min_stability=0.40,
            skip_source_start_sec=1.0,
            start_transition='cinematic_crossfade', start_transition_duration=0.8,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                sharpness_score=1.3, camera_stability_score=1.2,
                brightness_score=1.0, uniqueness_score=1.3,
                color_saturation_score=1.1, visual_complexity_score=1.0,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_ending'],
            skip_source_end_sec=1.0,
            end_transition='cinematic_fade', end_transition_duration=1.2,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=1.5,
                                   avoid_first_sec=8.0, prefer_stability=True),
        audio_outro=AudioOutroRule(mode='phrase_fade_end', fade_out_sec=2.5,
                                   avoid_last_sec=6.0),
        narrative='beauty_arc',
    ),

    # ── 3. Drone Nature Cinematic ──────────────────────────────────────────────
    "drone_nature_cinematic": IntroOutroProfile(
        preset_id="drone_nature_cinematic",
        video_intro=VideoIntroRule(
            weights=_w(
                camera_stability_score=1.6, sharpness_score=1.2,
                brightness_score=1.0, calm_score=1.4,
                visual_complexity_score=1.1, color_saturation_score=1.0,
                motion_score=0.4,          # gentle drone motion is ok
                action_score=-0.6,         # no action at start
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_starting',
                       'low_brightness', 'high_motion'],
            min_sharpness=0.30, min_brightness=0.20,
            min_stability=0.50, max_calm=1.0,
            skip_source_start_sec=1.5,
            start_transition='cinematic_crossfade', start_transition_duration=1.2,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                camera_stability_score=1.5, sharpness_score=1.2,
                brightness_score=1.1, calm_score=1.4,
                color_saturation_score=1.2, visual_complexity_score=1.0,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_ending'],
            skip_source_end_sec=1.5,
            end_transition='cinematic_fade', end_transition_duration=1.5,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=2.0,
                                   avoid_first_sec=8.0, prefer_stability=True),
        audio_outro=AudioOutroRule(mode='phrase_fade_end', fade_out_sec=2.5,
                                   avoid_last_sec=6.0),
        narrative='story_arc',
    ),

    # ── 4. Drone Landscape Clean ───────────────────────────────────────────────
    "drone_landscape_clean": IntroOutroProfile(
        preset_id="drone_landscape_clean",
        video_intro=VideoIntroRule(
            weights=_w(
                camera_stability_score=1.7, sharpness_score=1.5,
                brightness_score=1.2, visual_complexity_score=1.0,
                calm_score=1.3, motion_score=0.2,
                action_score=-0.5,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_starting',
                       'high_motion'],
            min_sharpness=0.35, min_brightness=0.25, min_stability=0.55,
            skip_source_start_sec=1.5,
            start_transition='fade_in', start_transition_duration=0.8,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                camera_stability_score=1.6, sharpness_score=1.4,
                brightness_score=1.1, visual_complexity_score=1.0,
                calm_score=1.2,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_ending'],
            skip_source_end_sec=1.5,
            end_transition='fade_out', end_transition_duration=1.2,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=1.5,
                                   avoid_first_sec=5.0, prefer_stability=True),
        audio_outro=AudioOutroRule(mode='phrase_fade_end', fade_out_sec=2.0,
                                   avoid_last_sec=5.0),
        narrative='simple',
    ),

    # ── 5. Fast Action Sport ───────────────────────────────────────────────────
    "fast_action_sport": IntroOutroProfile(
        preset_id="fast_action_sport",
        video_intro=VideoIntroRule(
            weights=_w(
                motion_score=1.8, action_score=1.8, sharpness_score=1.2,
                visual_complexity_score=1.0, brightness_score=0.8,
                calm_score=-1.5, camera_stability_score=-0.3,
            ),
            forbidden=['black_frame', 'blur', 'camera_starting',
                       'low_motion', 'low_action'],
            min_sharpness=0.25, min_brightness=0.15,
            min_action=0.30, max_calm=0.40,
            skip_source_start_sec=0.5,
            start_transition='beat_flash', start_transition_duration=0.2,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                action_score=2.0, motion_score=1.6, sharpness_score=1.2,
                visual_complexity_score=1.0, brightness_score=0.7,
                calm_score=-1.5,
            ),
            forbidden=['black_frame', 'blur', 'camera_ending', 'low_action'],
            min_action=0.25,
            skip_source_end_sec=0.5,
            end_transition='flash_impact', end_transition_duration=0.2,
        ),
        audio_intro=AudioIntroRule(mode='beat_start', fade_in_sec=0.3,
                                   avoid_first_sec=4.0, prefer_energy=True),
        audio_outro=AudioOutroRule(mode='punch_end', fade_out_sec=0.6,
                                   avoid_last_sec=4.0),
        narrative='energy_peak',
    ),

    # ── 6. Urban City Rhythm ───────────────────────────────────────────────────
    "urban_city_rhythm": IntroOutroProfile(
        preset_id="urban_city_rhythm",
        video_intro=VideoIntroRule(
            weights=_w(
                motion_score=1.2, visual_complexity_score=1.4,
                contrast_score=1.2, sharpness_score=1.1,
                brightness_score=0.9, action_score=1.0,
                calm_score=-0.8,
            ),
            forbidden=['black_frame', 'blur', 'camera_starting', 'low_brightness'],
            min_sharpness=0.25, min_brightness=0.15,
            skip_source_start_sec=0.5,
            start_transition='zoom_in', start_transition_duration=0.35,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                visual_complexity_score=1.4, contrast_score=1.3,
                sharpness_score=1.2, brightness_score=1.0,
                action_score=0.8,
            ),
            forbidden=['black_frame', 'blur', 'camera_ending'],
            skip_source_end_sec=0.5,
            end_transition='beat_cut', end_transition_duration=0.0,
        ),
        audio_intro=AudioIntroRule(mode='beat_start', fade_in_sec=0.7,
                                   avoid_first_sec=5.0, prefer_energy=True),
        audio_outro=AudioOutroRule(mode='beat_cut_end', fade_out_sec=1.0,
                                   avoid_last_sec=4.0),
        narrative='energy_peak',
    ),

    # ── 7. Social Media Punchy ─────────────────────────────────────────────────
    "social_media_punchy": IntroOutroProfile(
        preset_id="social_media_punchy",
        video_intro=VideoIntroRule(
            weights=_w(
                action_score=1.5, brightness_score=1.2, contrast_score=1.2,
                sharpness_score=1.1, motion_score=1.3, uniqueness_score=1.0,
                calm_score=-1.5,
            ),
            forbidden=['black_frame', 'blur', 'camera_starting', 'low_action',
                       'low_brightness'],
            min_sharpness=0.25, min_brightness=0.20, min_action=0.25,
            skip_source_start_sec=0.3,
            start_transition='beat_flash', start_transition_duration=0.15,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                action_score=1.6, brightness_score=1.2, contrast_score=1.2,
                sharpness_score=1.1, motion_score=1.2,
            ),
            forbidden=['black_frame', 'blur', 'camera_ending', 'low_action'],
            min_action=0.20,
            skip_source_end_sec=0.3,
            end_transition='beat_cut', end_transition_duration=0.0,
        ),
        audio_intro=AudioIntroRule(mode='drop_start', fade_in_sec=0.3,
                                   avoid_first_sec=3.0, prefer_energy=True),
        audio_outro=AudioOutroRule(mode='punch_end', fade_out_sec=0.6,
                                   avoid_last_sec=3.0),
        narrative='energy_peak',
    ),

    # ── 8. Business Promo Clean ────────────────────────────────────────────────
    "business_promo_clean": IntroOutroProfile(
        preset_id="business_promo_clean",
        video_intro=VideoIntroRule(
            weights=_w(
                sharpness_score=1.6, brightness_score=1.4,
                camera_stability_score=1.4, technical_quality_score=1.3,
                visual_complexity_score=0.8,
                action_score=-0.5, motion_score=-0.3,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_starting',
                       'high_motion', 'low_brightness'],
            min_sharpness=0.35, min_brightness=0.25, min_stability=0.40,
            skip_source_start_sec=1.0,
            start_transition='fade_in', start_transition_duration=0.5,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                sharpness_score=1.5, brightness_score=1.3,
                camera_stability_score=1.3, technical_quality_score=1.2,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_ending'],
            skip_source_end_sec=1.0,
            end_transition='fade_out', end_transition_duration=1.0,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=1.2,
                                   avoid_first_sec=5.0, prefer_stability=True),
        audio_outro=AudioOutroRule(mode='soft_fade_end', fade_out_sec=1.5,
                                   avoid_last_sec=5.0),
        narrative='simple',
    ),

    # ── 9. Real Estate / Property Tour ────────────────────────────────────────
    "real_estate_property_tour": IntroOutroProfile(
        preset_id="real_estate_property_tour",
        video_intro=VideoIntroRule(
            weights=_w(
                camera_stability_score=1.7, sharpness_score=1.5,
                brightness_score=1.4, visual_complexity_score=0.9,
                calm_score=1.3,
                action_score=-0.8, motion_score=-0.4,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_starting',
                       'high_motion', 'low_brightness'],
            min_sharpness=0.35, min_brightness=0.25, min_stability=0.55,
            skip_source_start_sec=1.5,
            start_transition='fade_in', start_transition_duration=0.6,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                camera_stability_score=1.6, sharpness_score=1.5,
                brightness_score=1.3, calm_score=1.2,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_ending',
                       'high_motion'],
            skip_source_end_sec=1.5,
            end_transition='cinematic_fade', end_transition_duration=1.2,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=1.5,
                                   avoid_first_sec=5.0, prefer_stability=True),
        audio_outro=AudioOutroRule(mode='soft_fade_end', fade_out_sec=2.0,
                                   avoid_last_sec=5.0),
        narrative='simple',
    ),

    # ── 10. Travel Story ──────────────────────────────────────────────────────
    "travel_story": IntroOutroProfile(
        preset_id="travel_story",
        video_intro=VideoIntroRule(
            weights=_w(
                uniqueness_score=1.2, sharpness_score=1.1,
                brightness_score=1.1, color_saturation_score=1.1,
                motion_score=0.5, camera_stability_score=0.9,
                calm_score=0.8, action_score=0.4,
            ),
            forbidden=['black_frame', 'blur', 'camera_starting', 'low_brightness'],
            min_sharpness=0.25, min_brightness=0.20,
            skip_source_start_sec=1.0,
            start_transition='cinematic_crossfade', start_transition_duration=0.7,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                color_saturation_score=1.3, brightness_score=1.2,
                sharpness_score=1.2, uniqueness_score=1.1,
                calm_score=1.0, camera_stability_score=1.0,
            ),
            forbidden=['black_frame', 'blur', 'camera_ending'],
            skip_source_end_sec=1.0,
            end_transition='cinematic_fade', end_transition_duration=1.2,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=1.5,
                                   avoid_first_sec=6.0, prefer_energy=True,
                                   prefer_stability=True),
        audio_outro=AudioOutroRule(mode='phrase_fade_end', fade_out_sec=2.0,
                                   avoid_last_sec=5.0),
        narrative='story_arc',
    ),

    # ── 11. Event Highlights ──────────────────────────────────────────────────
    "event_highlights": IntroOutroProfile(
        preset_id="event_highlights",
        video_intro=VideoIntroRule(
            weights=_w(
                brightness_score=1.3, motion_score=1.3, action_score=1.3,
                color_saturation_score=1.2, sharpness_score=1.0,
                visual_complexity_score=0.9, calm_score=-0.8,
            ),
            forbidden=['black_frame', 'blur', 'camera_starting', 'low_brightness'],
            min_sharpness=0.20, min_brightness=0.20, min_action=0.15,
            skip_source_start_sec=0.5,
            start_transition='beat_flash', start_transition_duration=0.3,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                action_score=1.7, brightness_score=1.3, motion_score=1.2,
                color_saturation_score=1.1, sharpness_score=1.0,
            ),
            forbidden=['black_frame', 'blur', 'camera_ending'],
            min_action=0.10,
            skip_source_end_sec=0.5,
            end_transition='flash_impact', end_transition_duration=0.3,
        ),
        audio_intro=AudioIntroRule(mode='beat_start', fade_in_sec=0.7,
                                   avoid_first_sec=4.0, prefer_energy=True),
        audio_outro=AudioOutroRule(mode='beat_cut_end', fade_out_sec=1.0,
                                   avoid_last_sec=4.0),
        narrative='energy_peak',
    ),

    # ── 12. Calm Minimal Documentary ──────────────────────────────────────────
    "calm_minimal_documentary": IntroOutroProfile(
        preset_id="calm_minimal_documentary",
        video_intro=VideoIntroRule(
            weights=_w(
                camera_stability_score=1.7, sharpness_score=1.5,
                brightness_score=1.1, calm_score=1.5,
                technical_quality_score=1.2, visual_complexity_score=0.8,
                motion_score=-0.8, action_score=-1.0,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_starting',
                       'high_motion', 'low_action'],  # 'low_action' here = no fast-paced
            min_sharpness=0.30, min_brightness=0.20, min_stability=0.50,
            skip_source_start_sec=1.0,
            start_transition='fade_in', start_transition_duration=0.8,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                camera_stability_score=1.6, calm_score=1.5,
                sharpness_score=1.3, technical_quality_score=1.2,
                brightness_score=1.0,
            ),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_ending'],
            skip_source_end_sec=1.0,
            end_transition='fade_out', end_transition_duration=1.5,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=2.0,
                                   avoid_first_sec=6.0, prefer_stability=True),
        audio_outro=AudioOutroRule(mode='phrase_fade_end', fade_out_sec=2.0,
                                   avoid_last_sec=6.0),
        narrative='simple',
    ),

    # ── 13. Sport Dynamic Cut ──────────────────────────────────────────────────
    "sport_dynamic_cut": IntroOutroProfile(
        preset_id="sport_dynamic_cut",
        video_intro=VideoIntroRule(
            weights=_w(
                motion_score=2.2, action_score=2.0, sharpness_score=1.2,
                visual_complexity_score=1.0, brightness_score=0.8,
                calm_score=-2.0, camera_stability_score=-0.5,
            ),
            forbidden=['black_frame', 'blur', 'camera_starting',
                       'low_motion', 'low_action'],
            min_sharpness=0.20, min_brightness=0.10,
            min_action=0.35, max_calm=0.30,
            skip_source_start_sec=0.3,
            start_transition='beat_flash', start_transition_duration=0.15,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                action_score=2.2, motion_score=1.8, sharpness_score=1.2,
                visual_complexity_score=1.0, brightness_score=0.8,
                calm_score=-2.0,
            ),
            forbidden=['black_frame', 'blur', 'camera_ending', 'low_action',
                       'low_motion'],
            min_action=0.30,
            skip_source_end_sec=0.3,
            end_transition='flash_impact', end_transition_duration=0.15,
        ),
        audio_intro=AudioIntroRule(mode='drop_start', fade_in_sec=0.2,
                                   avoid_first_sec=3.0, prefer_energy=True),
        audio_outro=AudioOutroRule(mode='punch_end', fade_out_sec=0.4,
                                   avoid_last_sec=3.0),
        narrative='buildup_impact',
    ),

    # ── 15. F1 — Ultra-dynamic beat-driven montage ────────────────────────────
    # The split-screen intro is generated separately by F1IntroRenderer.
    # This profile governs the first/last clips of the *main edit* only.
    "f1": IntroOutroProfile(
        preset_id="f1",
        video_intro=VideoIntroRule(
            weights=_w(
                motion_score=2.5, action_score=2.5, sharpness_score=1.0,
                visual_complexity_score=1.1, brightness_score=0.8,
                calm_score=-2.5, camera_stability_score=-0.5,
            ),
            forbidden=['black_frame', 'blur', 'camera_starting', 'low_motion', 'low_action'],
            min_sharpness=0.20, min_brightness=0.10,
            min_action=0.30, max_calm=0.25,
            skip_source_start_sec=0.3,
            start_transition='beat_flash', start_transition_duration=0.1,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                action_score=2.5, motion_score=2.0, sharpness_score=1.0,
                visual_complexity_score=1.0, brightness_score=0.7,
                calm_score=-2.5,
            ),
            forbidden=['black_frame', 'blur', 'camera_ending', 'low_action', 'low_motion'],
            min_action=0.25,
            skip_source_end_sec=0.3,
            end_transition='flash_impact', end_transition_duration=0.1,
        ),
        audio_intro=AudioIntroRule(mode='drop_start', fade_in_sec=0.2,
                                   avoid_first_sec=3.0, prefer_energy=True),
        audio_outro=AudioOutroRule(mode='punch_end', fade_out_sec=0.4,
                                   avoid_last_sec=3.0),
        narrative='buildup_impact',
    ),

    # ── 16. F2 — Cinematic Velocity Flow ─────────────────────────────────────
    "f2": IntroOutroProfile(
        preset_id="f2",
        video_intro=VideoIntroRule(
            weights=_w(camera_stability_score=1.8, sharpness_score=1.6,
                       brightness_score=1.2, visual_complexity_score=1.2,
                       motion_score=1.0, calm_score=0.6,
                       action_score=-0.4),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_starting', 'low_brightness'],
            min_sharpness=0.25, min_brightness=0.18, min_stability=0.30,
            skip_source_start_sec=1.0,
            start_transition='cinematic_crossfade', start_transition_duration=0.8,
        ),
        video_outro=VideoOutroRule(
            weights=_w(camera_stability_score=1.6, sharpness_score=1.5,
                       brightness_score=1.2, visual_complexity_score=1.1,
                       color_saturation_score=1.0, calm_score=0.8),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_ending'],
            skip_source_end_sec=1.0,
            end_transition='cinematic_fade', end_transition_duration=1.0,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=1.2,
                                   avoid_first_sec=5.0, prefer_stability=True),
        audio_outro=AudioOutroRule(mode='phrase_fade_end', fade_out_sec=1.5,
                                   avoid_last_sec=5.0),
        narrative='beauty_arc',
    ),

    # ── 17. F3 — Urban Pulse Cut ──────────────────────────────────────────────
    "f3": IntroOutroProfile(
        preset_id="f3",
        video_intro=VideoIntroRule(
            weights=_w(motion_score=1.8, action_score=1.6, visual_complexity_score=1.4,
                       contrast_score=1.2, sharpness_score=1.2, brightness_score=0.9,
                       calm_score=-1.0),
            forbidden=['black_frame', 'blur', 'camera_starting', 'low_brightness', 'low_motion'],
            min_sharpness=0.22, min_brightness=0.12, min_action=0.20, max_calm=0.60,
            skip_source_start_sec=0.5,
            start_transition='zoom_in', start_transition_duration=0.25,
        ),
        video_outro=VideoOutroRule(
            weights=_w(motion_score=1.4, action_score=1.4, visual_complexity_score=1.4,
                       contrast_score=1.2, sharpness_score=1.2),
            forbidden=['black_frame', 'blur', 'camera_ending'],
            min_action=0.15,
            skip_source_end_sec=0.5,
            end_transition='beat_cut', end_transition_duration=0.0,
        ),
        audio_intro=AudioIntroRule(mode='beat_start', fade_in_sec=0.4,
                                   avoid_first_sec=3.0, prefer_energy=True),
        audio_outro=AudioOutroRule(mode='punch_end', fade_out_sec=0.8,
                                   avoid_last_sec=3.0),
        narrative='energy_peak',
    ),

    # ── 18. F4 — Impact Sport Machine ────────────────────────────────────────
    "f4": IntroOutroProfile(
        preset_id="f4",
        video_intro=VideoIntroRule(
            weights=_w(motion_score=2.5, action_score=2.5, sharpness_score=1.2,
                       visual_complexity_score=1.2, brightness_score=0.7,
                       calm_score=-2.5, camera_stability_score=-0.5),
            forbidden=['black_frame', 'blur', 'camera_starting', 'low_motion',
                       'low_action', 'low_brightness'],
            min_sharpness=0.18, min_brightness=0.10, min_action=0.30, max_calm=0.25,
            skip_source_start_sec=0.3,
            start_transition='beat_flash', start_transition_duration=0.1,
        ),
        video_outro=VideoOutroRule(
            weights=_w(action_score=2.5, motion_score=2.2, sharpness_score=1.2,
                       visual_complexity_score=1.2, calm_score=-2.0),
            forbidden=['black_frame', 'blur', 'camera_ending', 'low_action', 'low_motion'],
            min_action=0.28,
            skip_source_end_sec=0.3,
            end_transition='flash_impact', end_transition_duration=0.1,
        ),
        audio_intro=AudioIntroRule(mode='drop_start', fade_in_sec=0.15,
                                   avoid_first_sec=2.0, prefer_energy=True),
        audio_outro=AudioOutroRule(mode='punch_end', fade_out_sec=0.4,
                                   avoid_last_sec=2.0),
        narrative='buildup_impact',
    ),

    # ── 19. F5 — Premium Brand Smooth ────────────────────────────────────────
    "f5": IntroOutroProfile(
        preset_id="f5",
        video_intro=VideoIntroRule(
            weights=_w(sharpness_score=2.0, brightness_score=1.5,
                       camera_stability_score=2.0, technical_quality_score=1.5,
                       visual_complexity_score=1.2, color_saturation_score=1.0,
                       calm_score=1.5, action_score=-0.8, motion_score=-0.3),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_starting',
                       'low_brightness', 'high_motion'],
            min_sharpness=0.30, min_brightness=0.22, min_stability=0.45, max_calm=1.0,
            skip_source_start_sec=1.2,
            start_transition='cinematic_crossfade', start_transition_duration=1.0,
        ),
        video_outro=VideoOutroRule(
            weights=_w(sharpness_score=2.0, camera_stability_score=1.8,
                       brightness_score=1.4, color_saturation_score=1.2,
                       technical_quality_score=1.4, visual_complexity_score=1.0,
                       calm_score=1.4),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_ending'],
            min_sharpness=0.28, min_brightness=0.20,
            skip_source_end_sec=1.2,
            end_transition='cinematic_fade', end_transition_duration=1.5,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=2.0,
                                   avoid_first_sec=8.0, prefer_stability=True),
        audio_outro=AudioOutroRule(mode='phrase_fade_end', fade_out_sec=2.5,
                                   avoid_last_sec=6.0),
        narrative='beauty_arc',
    ),

    # ── 20. F6 — Dream Travel Atmosphere ─────────────────────────────────────
    "f6": IntroOutroProfile(
        preset_id="f6",
        video_intro=VideoIntroRule(
            weights=_w(sharpness_score=1.5, brightness_score=1.4,
                       camera_stability_score=1.4, visual_complexity_score=1.4,
                       color_saturation_score=1.2, uniqueness_score=1.6,
                       motion_score=0.6, action_score=0.2, calm_score=0.6),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_starting', 'low_brightness'],
            min_sharpness=0.22, min_brightness=0.15, min_stability=0.20,
            skip_source_start_sec=1.0,
            start_transition='fade_in', start_transition_duration=0.6,
        ),
        video_outro=VideoOutroRule(
            weights=_w(sharpness_score=1.5, brightness_score=1.4,
                       camera_stability_score=1.3, color_saturation_score=1.2,
                       uniqueness_score=1.5, visual_complexity_score=1.2,
                       calm_score=0.8),
            forbidden=['black_frame', 'blur', 'shaky', 'camera_ending'],
            skip_source_end_sec=1.0,
            end_transition='fade_out', end_transition_duration=1.2,
        ),
        audio_intro=AudioIntroRule(mode='phrase_start', fade_in_sec=1.5,
                                   avoid_first_sec=6.0, prefer_stability=True),
        audio_outro=AudioOutroRule(mode='phrase_fade_end', fade_out_sec=2.0,
                                   avoid_last_sec=5.0),
        narrative='story_arc',
    ),

    # ── 14. Sport Highlight Impact ─────────────────────────────────────────────
    "sport_highlight_impact": IntroOutroProfile(
        preset_id="sport_highlight_impact",
        video_intro=VideoIntroRule(
            weights=_w(
                action_score=1.6, motion_score=1.3, sharpness_score=1.2,
                visual_complexity_score=1.0, brightness_score=0.9,
                calm_score=-0.5,
            ),
            forbidden=['black_frame', 'blur', 'camera_starting'],
            min_sharpness=0.20, min_brightness=0.15, min_action=0.20,
            skip_source_start_sec=0.5,
            # intro is a "buildup" so start slightly calmer than body
            start_transition='beat_flash', start_transition_duration=0.2,
        ),
        video_outro=VideoOutroRule(
            weights=_w(
                action_score=2.3, motion_score=1.8, sharpness_score=1.2,
                visual_complexity_score=1.1, brightness_score=0.9,
                calm_score=-1.5,
            ),
            forbidden=['black_frame', 'blur', 'camera_ending', 'low_action'],
            min_action=0.25,
            skip_source_end_sec=0.5,
            end_transition='freeze_final', end_transition_duration=0.5,
        ),
        audio_intro=AudioIntroRule(mode='beat_start', fade_in_sec=0.5,
                                   avoid_first_sec=4.0, prefer_energy=True),
        audio_outro=AudioOutroRule(mode='beat_cut_end', fade_out_sec=0.8,
                                   avoid_last_sec=4.0),
        narrative='buildup_impact',
    ),
}

# ── Fallback ───────────────────────────────────────────────────────────────────

_DEFAULT_PROFILE = IntroOutroProfile(
    preset_id='_default',
    video_intro=VideoIntroRule(
        weights=_w(sharpness_score=1.0, brightness_score=1.0,
                   camera_stability_score=1.0),
        forbidden=['black_frame', 'blur', 'camera_starting'],
    ),
    video_outro=VideoOutroRule(
        weights=_w(sharpness_score=1.0, brightness_score=1.0),
        forbidden=['black_frame', 'blur', 'camera_ending'],
    ),
    audio_intro=AudioIntroRule(),
    audio_outro=AudioOutroRule(),
    narrative='simple',
)


def get_profile(preset_id: str) -> IntroOutroProfile:
    """Return the IntroOutroProfile for preset_id, or a safe default."""
    return STYLE_PROFILES.get(preset_id, _DEFAULT_PROFILE)
