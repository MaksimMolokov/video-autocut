"""
Per-preset music selection profiles.

Each preset declares what kind of audio segment it wants:
energy level, onset density, whether energy should grow, etc.
These profiles drive the sliding-window scoring in MusicSelectionEngine.
"""

from dataclasses import dataclass


@dataclass
class MusicSelectionProfile:
    """Describes the ideal audio segment for a preset style."""

    # Target normalized energy [0.0 – 1.0]
    target_energy_min: float = 0.25
    target_energy_max: float = 0.70

    # Onset density (fraction of frames above 75th-percentile onset threshold)
    min_onset_density: float = 0.0
    max_onset_density: float = 1.0

    # Shape requirements (scored when True)
    require_energy_growth: bool = False   # Energy increases over the window
    require_final_accent: bool = False    # Window ends on a high note
    require_strong_start: bool = False    # Window begins with high energy

    # Score weights — must sum to ≤ 1.0 (remainder is unused)
    weight_energy_fit: float = 0.35
    weight_onset_density: float = 0.20
    weight_energy_growth: float = 0.15
    weight_start_quality: float = 0.15
    weight_end_quality: float = 0.10
    weight_variance_penalty: float = 0.05


# ── Preset profiles ───────────────────────────────────────────────────────────

PRESET_PROFILES: dict[str, MusicSelectionProfile] = {

    # HIGH ENERGY: drop / climax sections ─────────────────────────────────────

    "fast_action_sport": MusicSelectionProfile(
        target_energy_min=0.70, target_energy_max=1.00,
        min_onset_density=0.55,
        require_strong_start=True,
        require_final_accent=True,
        weight_energy_fit=0.35,
        weight_onset_density=0.30,
        weight_start_quality=0.20,
        weight_energy_growth=0.10,
        weight_end_quality=0.05,
        weight_variance_penalty=0.00,
    ),

    "social_media_punchy": MusicSelectionProfile(
        target_energy_min=0.65, target_energy_max=1.00,
        min_onset_density=0.50,
        require_strong_start=True,
        weight_energy_fit=0.30,
        weight_onset_density=0.30,
        weight_start_quality=0.25,
        weight_energy_growth=0.10,
        weight_end_quality=0.05,
        weight_variance_penalty=0.00,
    ),

    "urban_city_rhythm": MusicSelectionProfile(
        target_energy_min=0.55, target_energy_max=0.95,
        min_onset_density=0.45,
        require_energy_growth=True,
        weight_energy_fit=0.25,
        weight_onset_density=0.25,
        weight_energy_growth=0.25,
        weight_start_quality=0.15,
        weight_end_quality=0.10,
        weight_variance_penalty=0.00,
    ),

    "event_highlights": MusicSelectionProfile(
        target_energy_min=0.60, target_energy_max=1.00,
        min_onset_density=0.50,
        require_strong_start=True,
        require_final_accent=True,
        weight_energy_fit=0.30,
        weight_onset_density=0.25,
        weight_start_quality=0.20,
        weight_end_quality=0.15,
        weight_energy_growth=0.10,
        weight_variance_penalty=0.00,
    ),

    # MEDIUM ENERGY: build-up / development sections ──────────────────────────

    "travel_story": MusicSelectionProfile(
        target_energy_min=0.30, target_energy_max=0.75,
        require_energy_growth=True,
        require_final_accent=True,
        weight_energy_fit=0.25,
        weight_energy_growth=0.30,
        weight_end_quality=0.20,
        weight_onset_density=0.15,
        weight_start_quality=0.10,
        weight_variance_penalty=0.00,
    ),

    "business_promo_clean": MusicSelectionProfile(
        target_energy_min=0.40, target_energy_max=0.75,
        min_onset_density=0.25,
        max_onset_density=0.70,
        weight_energy_fit=0.35,
        weight_onset_density=0.20,
        weight_variance_penalty=0.20,
        weight_energy_growth=0.15,
        weight_start_quality=0.10,
        weight_end_quality=0.00,
    ),

    "real_estate_property_tour": MusicSelectionProfile(
        target_energy_min=0.25, target_energy_max=0.60,
        max_onset_density=0.55,
        weight_energy_fit=0.40,
        weight_variance_penalty=0.25,
        weight_onset_density=0.20,
        weight_energy_growth=0.15,
        weight_start_quality=0.00,
        weight_end_quality=0.00,
    ),

    "intelligent_beauty_mix": MusicSelectionProfile(
        target_energy_min=0.35, target_energy_max=0.70,
        require_energy_growth=True,
        require_final_accent=True,
        weight_energy_fit=0.25,
        weight_energy_growth=0.25,
        weight_end_quality=0.20,
        weight_onset_density=0.15,
        weight_start_quality=0.15,
        weight_variance_penalty=0.00,
    ),

    # LOW–MEDIUM ENERGY: cinematic / calm sections ────────────────────────────

    "drone_nature_cinematic": MusicSelectionProfile(
        target_energy_min=0.15, target_energy_max=0.58,
        max_onset_density=0.50,
        require_energy_growth=True,
        weight_energy_fit=0.30,
        weight_energy_growth=0.25,
        weight_variance_penalty=0.20,
        weight_onset_density=0.15,
        weight_start_quality=0.10,
        weight_end_quality=0.00,
    ),

    "drone_landscape_clean": MusicSelectionProfile(
        target_energy_min=0.20, target_energy_max=0.60,
        max_onset_density=0.50,
        weight_energy_fit=0.40,
        weight_variance_penalty=0.25,
        weight_onset_density=0.20,
        weight_energy_growth=0.15,
        weight_start_quality=0.00,
        weight_end_quality=0.00,
    ),

    "calm_minimal_documentary": MusicSelectionProfile(
        target_energy_min=0.08, target_energy_max=0.48,
        max_onset_density=0.40,
        weight_energy_fit=0.40,
        weight_variance_penalty=0.30,
        weight_onset_density=0.20,
        weight_energy_growth=0.10,
        weight_start_quality=0.00,
        weight_end_quality=0.00,
    ),

    # SPORT: high-intensity, beat-heavy sections ──────────────────────────────

    "sport_dynamic_cut": MusicSelectionProfile(
        target_energy_min=0.75, target_energy_max=1.00,
        min_onset_density=0.60,
        require_strong_start=True,
        require_final_accent=True,
        weight_energy_fit=0.30,
        weight_onset_density=0.35,
        weight_start_quality=0.20,
        weight_energy_growth=0.10,
        weight_end_quality=0.05,
        weight_variance_penalty=0.00,
    ),

    "sport_highlight_impact": MusicSelectionProfile(
        target_energy_min=0.70, target_energy_max=1.00,
        min_onset_density=0.50,
        require_energy_growth=True,
        require_final_accent=True,
        weight_energy_fit=0.25,
        weight_onset_density=0.25,
        weight_energy_growth=0.25,
        weight_end_quality=0.15,
        weight_start_quality=0.10,
        weight_variance_penalty=0.00,
    ),

    # EASY MODE: no strong preference ─────────────────────────────────────────

    "easy_mode": MusicSelectionProfile(
        target_energy_min=0.15,
        target_energy_max=0.85,
        weight_energy_fit=0.60,
        weight_onset_density=0.20,
        weight_variance_penalty=0.20,
        weight_energy_growth=0.00,
        weight_start_quality=0.00,
        weight_end_quality=0.00,
    ),
}

_DEFAULT_PROFILE = MusicSelectionProfile()


def get_profile(preset_id: str) -> MusicSelectionProfile:
    """Return the music selection profile for a preset, falling back to default."""
    return PRESET_PROFILES.get(preset_id, _DEFAULT_PROFILE)
