"""
Effects and presets configuration system
Manages visual styles, transitions, speed effects, and color grading
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum


class TransitionType(Enum):
    """Available transition types"""
    CUT = "cut"
    CROSSFADE = "crossfade"
    FADE = "fade"
    ZOOM = "zoom"
    SWIPE = "swipe"
    BLUR = "blur"
    FLASH = "flash"


class SpeedMode(Enum):
    """Speed effect modes"""
    NONE = "none"
    SLOW_MOTION = "slow_motion"
    SPEED_UP = "speed_up"
    SPEED_RAMP = "speed_ramp"
    AUTO_DYNAMIC = "auto_dynamic"


class ColorStyle(Enum):
    """Color grading styles"""
    NONE = "none"
    BASIC_ENHANCE = "basic_enhance"
    CINEMATIC = "cinematic"
    NATURAL = "natural"
    WARM = "warm"
    HIGH_CONTRAST = "high_contrast"


class MusicSyncMode(Enum):
    """Music synchronization modes"""
    NONE = "none"
    SIMPLE_TEMPO = "simple_tempo"
    BEAT_SYNC = "beat_sync"
    DYNAMIC_SYNC = "dynamic_sync"


@dataclass
class TransitionSettings:
    """Transition configuration"""
    enabled: bool = True
    type: TransitionType = TransitionType.CUT
    duration: float = 0.3  # seconds
    intensity: str = "medium"  # low, medium, high
    randomize: bool = False


@dataclass
class SpeedEffectSettings:
    """Speed effect configuration"""
    enabled: bool = False
    mode: SpeedMode = SpeedMode.NONE
    slow_motion_factor: float = 0.75  # 0.5 = 50% speed
    speed_up_factor: float = 1.25  # 1.5 = 150% speed
    intensity: str = "medium"


@dataclass
class ColorSettings:
    """Color grading configuration"""
    enabled: bool = False
    style: ColorStyle = ColorStyle.NONE
    brightness: float = 0.0  # -1.0 to 1.0
    contrast: float = 0.0  # -1.0 to 1.0
    saturation: float = 0.0  # -1.0 to 1.0
    temperature: float = 0.0  # -1.0 to 1.0
    vignette: bool = False


@dataclass
class QualityFilterSettings:
    """Quality filter configuration"""
    enabled: bool = False
    remove_blurry: bool = False
    remove_dark: bool = False
    remove_overexposed: bool = False
    remove_shaky: bool = False
    stabilization: str = "none"  # none, light, medium


@dataclass
class MusicSyncSettings:
    """Music synchronization configuration"""
    enabled: bool = False
    mode: MusicSyncMode = MusicSyncMode.NONE
    fallback_mode: str = "simple_tempo"

    # Beat sync settings
    beat_source: str = "beats"  # beats, onsets, or both
    cut_every_n_beats: int = 4  # Cut every N beats
    prefer_strong_beats: bool = True  # Prefer downbeats
    allow_offbeat_cuts: bool = True  # Allow cuts between beats if needed
    beat_tolerance: float = 0.1  # seconds

    # Clip duration constraints
    min_clip_duration: float = 1.0
    max_clip_duration: float = 4.0

    # Dynamic sync energy-based durations (min, max) tuples
    low_energy_clip_duration: tuple = (4.0, 7.0)
    medium_energy_clip_duration: tuple = (2.0, 4.0)
    high_energy_clip_duration: tuple = (0.8, 2.5)

    # Advanced options
    use_beats_inside_sections: bool = True  # Use beats within energy sections
    climax_priority: bool = False  # Give more clips to climax sections
    energy_window_size: float = 2.0  # Window for energy analysis in seconds


@dataclass
class OverlaySettings:
    """Text and graphics overlay configuration"""
    title_enabled: bool = False
    title_text: str = ""
    title_duration: float = 2.0

    logo_enabled: bool = False
    logo_path: str = ""
    logo_position: str = "top_right"  # top_left, top_right, bottom_left, bottom_right
    logo_opacity: float = 0.85

    watermark_enabled: bool = False
    watermark_text: str = ""


@dataclass
class EffectsConfiguration:
    """Complete effects configuration"""
    transitions: TransitionSettings
    speed_effects: SpeedEffectSettings
    color: ColorSettings
    quality_filters: QualityFilterSettings
    music_sync: MusicSyncSettings
    overlays: OverlaySettings


class StylePresets:
    """Predefined style presets"""

    PRESETS = {
        "clean_basic": {
            "name": "Clean Basic",
            "emoji": "✨",
            "description": "Простая аккуратная сборка без лишних эффектов",
            "dynamic_level": "balanced",
            "transitions": TransitionSettings(
                enabled=True,
                type=TransitionType.CUT,
                duration=0.0
            ),
            "speed_effects": SpeedEffectSettings(
                enabled=False
            ),
            "color": ColorSettings(
                enabled=False
            ),
            "music_sync": MusicSyncSettings(
                enabled=False
            )
        },

        "cinematic_nature": {
            "name": "Cinematic Nature",
            "emoji": "🏔️",
            "description": "Природа, горы, море, пейзажи, дрон-съёмка",
            "dynamic_level": "slow",
            "transitions": TransitionSettings(
                enabled=True,
                type=TransitionType.CROSSFADE,
                duration=0.6,
                intensity="medium"
            ),
            "speed_effects": SpeedEffectSettings(
                enabled=True,
                mode=SpeedMode.SLOW_MOTION,
                slow_motion_factor=0.85,
                intensity="light"
            ),
            "color": ColorSettings(
                enabled=True,
                style=ColorStyle.WARM,
                saturation=0.1,
                contrast=0.05
            ),
            "music_sync": MusicSyncSettings(
                enabled=False
            )
        },

        "dynamic_sport": {
            "name": "Dynamic Sport",
            "emoji": "🚴",
            "description": "Велосипед, спорт, FPV, авто, активное движение",
            "dynamic_level": "fast",
            "transitions": TransitionSettings(
                enabled=True,
                type=TransitionType.FLASH,
                duration=0.2,
                intensity="high"
            ),
            "speed_effects": SpeedEffectSettings(
                enabled=True,
                mode=SpeedMode.SPEED_RAMP,
                intensity="medium"
            ),
            "color": ColorSettings(
                enabled=True,
                style=ColorStyle.HIGH_CONTRAST,
                saturation=0.15,
                contrast=0.1
            ),
            "music_sync": MusicSyncSettings(
                enabled=True,
                mode=MusicSyncMode.SIMPLE_TEMPO
            )
        },

        "business_promo": {
            "name": "Business Promo",
            "emoji": "💼",
            "description": "Ролики для бизнеса, услуг, объектов, сайта",
            "dynamic_level": "balanced",
            "transitions": TransitionSettings(
                enabled=True,
                type=TransitionType.FADE,
                duration=0.4,
                intensity="low"
            ),
            "speed_effects": SpeedEffectSettings(
                enabled=False
            ),
            "color": ColorSettings(
                enabled=True,
                style=ColorStyle.BASIC_ENHANCE,
                brightness=0.05,
                contrast=0.05
            ),
            "music_sync": MusicSyncSettings(
                enabled=False
            )
        },

        "social_reels": {
            "name": "Social Reels",
            "emoji": "📱",
            "description": "Instagram Reels, TikTok, YouTube Shorts",
            "dynamic_level": "fast",
            "transitions": TransitionSettings(
                enabled=True,
                type=TransitionType.ZOOM,
                duration=0.3,
                intensity="medium"
            ),
            "speed_effects": SpeedEffectSettings(
                enabled=True,
                mode=SpeedMode.AUTO_DYNAMIC,
                intensity="medium"
            ),
            "color": ColorSettings(
                enabled=True,
                style=ColorStyle.HIGH_CONTRAST,
                saturation=0.2,
                contrast=0.1
            ),
            "music_sync": MusicSyncSettings(
                enabled=True,
                mode=MusicSyncMode.SIMPLE_TEMPO
            )
        }
    }

    @staticmethod
    def get_preset(preset_name: str) -> Dict[str, Any]:
        """Get preset configuration by name"""
        return StylePresets.PRESETS.get(preset_name, StylePresets.PRESETS["clean_basic"])

    @staticmethod
    def list_presets() -> Dict[str, Dict[str, str]]:
        """List all available presets with basic info"""
        return {
            key: {
                "name": preset["name"],
                "emoji": preset["emoji"],
                "description": preset["description"]
            }
            for key, preset in StylePresets.PRESETS.items()
        }

    @staticmethod
    def create_effects_config(preset_name: str, overrides: Optional[Dict] = None) -> EffectsConfiguration:
        """
        Create EffectsConfiguration from preset with optional overrides

        Args:
            preset_name: Name of preset to use
            overrides: Optional dict to override specific settings

        Returns:
            EffectsConfiguration object
        """
        preset = StylePresets.get_preset(preset_name)

        config = EffectsConfiguration(
            transitions=preset.get("transitions", TransitionSettings()),
            speed_effects=preset.get("speed_effects", SpeedEffectSettings()),
            color=preset.get("color", ColorSettings()),
            quality_filters=QualityFilterSettings(),  # Not in presets by default
            music_sync=preset.get("music_sync", MusicSyncSettings()),
            overlays=OverlaySettings()  # Not in presets by default
        )

        # Apply overrides if provided
        if overrides:
            if "transitions" in overrides:
                for key, value in overrides["transitions"].items():
                    setattr(config.transitions, key, value)
            if "speed_effects" in overrides:
                for key, value in overrides["speed_effects"].items():
                    setattr(config.speed_effects, key, value)
            if "color" in overrides:
                for key, value in overrides["color"].items():
                    setattr(config.color, key, value)
            # ... and so on for other sections

        return config


if __name__ == "__main__":
    # Test presets
    print("Available presets:")
    for key, info in StylePresets.list_presets().items():
        print(f"  {info['emoji']} {info['name']}: {info['description']}")

    print("\nTesting Cinematic Nature preset:")
    config = StylePresets.create_effects_config("cinematic_nature")
    print(f"  Transitions: {config.transitions.type.value}, duration: {config.transitions.duration}s")
    print(f"  Speed: {config.speed_effects.mode.value}, factor: {config.speed_effects.slow_motion_factor}")
    print(f"  Color: {config.color.style.value}")
