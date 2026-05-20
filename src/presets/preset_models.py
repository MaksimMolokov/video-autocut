"""
Data models for preset system
Defines all settings structures for video editing presets
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class DynamicLevel(Enum):
    """Dynamic level of editing"""
    SLOW = "slow"
    BALANCED = "balanced"
    FAST = "fast"
    CUSTOM = "custom"


class TransitionType(Enum):
    """Available transition types"""
    CUT = "cut"
    FADE = "fade"
    CROSSFADE = "crossfade"
    FLASH = "flash"
    BLUR = "blur"
    ZOOM = "zoom"
    WHIP_PAN = "whip_pan"  # May not be implemented yet


class SpeedEffectMode(Enum):
    """Speed effect modes"""
    NONE = "none"
    SLOW_MOTION = "slow_motion"
    SPEED_UP = "speed_up"
    SPEED_RAMP = "speed_ramp"


class ColorStyle(Enum):
    """Color grading styles"""
    NONE = "none"
    NATURAL = "natural"
    WARM = "warm"
    CINEMATIC_WARM = "cinematic_warm"
    CLEAN_BRIGHT = "clean_bright"
    CLEAN_CONTRAST = "clean_contrast"
    HIGH_CONTRAST = "high_contrast"
    PUNCHY = "punchy"
    NATURAL_BRIGHT = "natural_bright"


class MusicSyncMode(Enum):
    """Music synchronization modes"""
    NONE = "none"
    SIMPLE_TEMPO = "simple_tempo"
    BEAT_SYNC = "beat_sync"
    DYNAMIC_SYNC = "dynamic_sync"


class ExportFormat(Enum):
    """Export format presets"""
    ORIGINAL = "original"
    HORIZONTAL_16_9 = "horizontal_16_9"
    VERTICAL_9_16 = "vertical_9_16"
    SQUARE_1_1 = "square_1_1"


class ExportQuality(Enum):
    """Export quality settings"""
    FAST = "fast"
    BALANCED = "balanced"
    HIGH = "high"


class StabilizationLevel(Enum):
    """Video stabilization levels"""
    NONE = "none"
    LIGHT = "light"
    MEDIUM = "medium"


class Intensity(Enum):
    """Effect intensity levels"""
    LIGHT = "light"
    MEDIUM = "medium"
    HIGH = "high"


class LogoPosition(Enum):
    """Logo overlay position"""
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


class AudioSelectionMode(Enum):
    """Audio fragment selection modes"""
    FROM_START = "from_start"
    MANUAL_RANGE = "manual_range"
    AUTO_HIGHLIGHT = "auto_highlight"
    AUTO_ENERGY = "auto_energy"
    AUTO_BALANCED = "auto_balanced"
    AUTO_CINEMATIC = "auto_cinematic"
    AUTO_DYNAMIC = "auto_dynamic"


class FitMode(Enum):
    """Video fit modes for aspect ratio conversion"""
    FILL = "fill"  # Fill frame, crop excess
    FIT = "fit"  # Fit entire video, may have bars
    BLUR_BACKGROUND = "blur_background"  # Fit with blurred background
    STRETCH = "stretch"  # Stretch to fit (distorts)
    ORIGINAL = "original"  # Keep original


class CropPosition(Enum):
    """Crop position when filling frame"""
    CENTER = "center"
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    SMART = "smart"  # Future: smart detection


@dataclass
class ClipSelectionSettings:
    """Clip selection and duration settings"""
    segment_min_duration: float = 2.0
    segment_max_duration: float = 5.0


@dataclass
class TransitionSettings:
    """Transition settings"""
    enabled: bool = True
    type: TransitionType = TransitionType.CUT
    duration: float = 0.3
    randomize: bool = False


@dataclass
class SpeedEffectSettings:
    """Speed effect settings"""
    enabled: bool = False
    mode: SpeedEffectMode = SpeedEffectMode.NONE
    slow_motion_factor: float = 0.85  # 0.5 = 50% speed
    speed_up_factor: float = 1.15  # 1.5 = 150% speed
    intensity: Intensity = Intensity.MEDIUM


@dataclass
class ColorSettings:
    """Color grading settings"""
    enabled: bool = False
    style: ColorStyle = ColorStyle.NATURAL
    intensity: Intensity = Intensity.MEDIUM


@dataclass
class MusicSyncSettings:
    """Music synchronization settings"""
    enabled: bool = True
    mode: MusicSyncMode = MusicSyncMode.SIMPLE_TEMPO


@dataclass
class QualityFilterSettings:
    """Quality filtering and stabilization"""
    enabled: bool = True
    remove_blurry: bool = True
    remove_dark: bool = True
    remove_shaky: bool = False
    stabilization: StabilizationLevel = StabilizationLevel.NONE


@dataclass
class TitleSettings:
    """Title overlay settings"""
    enabled: bool = False
    text: str = ""
    duration: float = 2.0


@dataclass
class LogoSettings:
    """Logo overlay settings"""
    enabled: bool = False
    file: str = ""
    position: LogoPosition = LogoPosition.TOP_RIGHT
    opacity: float = 0.85


@dataclass
class WatermarkSettings:
    """Watermark settings"""
    enabled: bool = False
    text: str = ""


@dataclass
class OverlaySettings:
    """All overlay settings"""
    title: TitleSettings = field(default_factory=TitleSettings)
    logo: LogoSettings = field(default_factory=LogoSettings)
    watermark: WatermarkSettings = field(default_factory=WatermarkSettings)


@dataclass
class ExportSettings:
    """Export configuration"""
    format: ExportFormat = ExportFormat.ORIGINAL
    resolution: Optional[str] = None  # e.g., "1920x1080"
    quality: ExportQuality = ExportQuality.HIGH
    hardware_acceleration: str = "auto"


@dataclass
class AudioSelectionSettings:
    """Audio fragment selection settings"""
    enabled: bool = True
    mode: AudioSelectionMode = AudioSelectionMode.AUTO_HIGHLIGHT

    # Manual range settings
    manual_start: Optional[float] = None  # seconds
    manual_end: Optional[float] = None  # seconds

    # Avoidance settings
    avoid_intro: bool = True
    avoid_intro_seconds: float = 10.0
    avoid_last_seconds: bool = True
    avoid_last_seconds_count: float = 8.0

    # Analysis settings
    analysis_window_sec: float = 2.0
    hop_sec: float = 0.5

    # Selection preferences
    prefer_energy: bool = True
    prefer_stability: bool = True
    prefer_climax: bool = True

    # Audio processing
    fade_in: float = 1.5
    fade_out: float = 2.5
    loop_audio_if_short: bool = False

    # Fallback
    fallback_mode: AudioSelectionMode = AudioSelectionMode.FROM_START


@dataclass
class FramingSettings:
    """Video framing and aspect ratio settings"""
    output_format: ExportFormat = ExportFormat.ORIGINAL
    resolution: Optional[str] = None  # Override resolution
    fit_mode: FitMode = FitMode.FILL
    allow_crop: bool = True
    avoid_black_bars: bool = True
    crop_position: CropPosition = CropPosition.CENTER


@dataclass
class ClipStrategySettings:
    """
    Настройки стратегии выбора фрагментов

    Определяет, как пресет выбирает фрагменты видео
    """
    # Основная стратегия
    mode: str = "balanced"  # nature_cinematic, action_sport, travel_story, etc.

    # Веса признаков (0.0 - 2.0)
    weight_sharpness: float = 1.0
    weight_brightness: float = 0.8
    weight_contrast: float = 0.7
    weight_motion: float = 0.5
    weight_stability: float = 1.0
    weight_visual_complexity: float = 0.8
    weight_uniqueness: float = 1.0
    weight_action: float = 0.5
    weight_calm: float = 0.5
    weight_technical_quality: float = 1.0

    # Правила отбора
    prefer_stable_clips: bool = True
    prefer_long_clips: bool = False
    prefer_high_motion: bool = False
    avoid_shaky_clips: bool = True
    avoid_static_clips: bool = False

    # Структура ролика
    ordering_type: str = "smooth_progression"

    # Разнообразие
    diversity_enabled: bool = True
    diversity_threshold: float = 0.3

    # Случайность
    randomness_enabled: bool = True
    randomness_level: float = 0.3

    # Избегание повторов
    avoid_previous_renders: bool = True
    previous_usage_penalty: float = 0.5


@dataclass
class PresetSettings:
    """Complete preset settings configuration"""
    dynamic_level: DynamicLevel = DynamicLevel.BALANCED
    clip_selection: ClipSelectionSettings = field(default_factory=ClipSelectionSettings)
    clip_strategy: ClipStrategySettings = field(default_factory=ClipStrategySettings)
    transitions: TransitionSettings = field(default_factory=TransitionSettings)
    speed_effects: SpeedEffectSettings = field(default_factory=SpeedEffectSettings)
    color: ColorSettings = field(default_factory=ColorSettings)
    music_sync: MusicSyncSettings = field(default_factory=MusicSyncSettings)
    quality_filters: QualityFilterSettings = field(default_factory=QualityFilterSettings)
    overlays: OverlaySettings = field(default_factory=OverlaySettings)
    audio_selection: AudioSelectionSettings = field(default_factory=AudioSelectionSettings)
    framing: FramingSettings = field(default_factory=FramingSettings)
    export: ExportSettings = field(default_factory=ExportSettings)


@dataclass
class Preset:
    """Complete preset definition"""
    preset_id: str
    name: str
    description: str
    recommended_for: List[str] = field(default_factory=list)
    settings: PresetSettings = field(default_factory=PresetSettings)
    emoji: str = "🎬"  # Visual identifier for UI

    def to_dict(self) -> Dict[str, Any]:
        """Convert preset to dictionary for YAML serialization"""
        return {
            'preset_id': self.preset_id,
            'name': self.name,
            'description': self.description,
            'emoji': self.emoji,
            'recommended_for': self.recommended_for,
            'settings': self._settings_to_dict(self.settings)
        }

    def _settings_to_dict(self, settings: PresetSettings) -> Dict[str, Any]:
        """Convert settings to dictionary"""
        return {
            'dynamic_level': settings.dynamic_level.value,
            'clip_selection': {
                'segment_min_duration': settings.clip_selection.segment_min_duration,
                'segment_max_duration': settings.clip_selection.segment_max_duration
            },
            'transitions': {
                'enabled': settings.transitions.enabled,
                'type': settings.transitions.type.value,
                'duration': settings.transitions.duration,
                'randomize': settings.transitions.randomize
            },
            'speed_effects': {
                'enabled': settings.speed_effects.enabled,
                'mode': settings.speed_effects.mode.value,
                'slow_motion_factor': settings.speed_effects.slow_motion_factor,
                'speed_up_factor': settings.speed_effects.speed_up_factor,
                'intensity': settings.speed_effects.intensity.value
            },
            'color': {
                'enabled': settings.color.enabled,
                'style': settings.color.style.value,
                'intensity': settings.color.intensity.value
            },
            'music_sync': {
                'enabled': settings.music_sync.enabled,
                'mode': settings.music_sync.mode.value
            },
            'quality_filters': {
                'enabled': settings.quality_filters.enabled,
                'remove_blurry': settings.quality_filters.remove_blurry,
                'remove_dark': settings.quality_filters.remove_dark,
                'remove_shaky': settings.quality_filters.remove_shaky,
                'stabilization': settings.quality_filters.stabilization.value
            },
            'export': {
                'format': settings.export.format.value,
                'quality': settings.export.quality.value
            }
        }


class EditMode(Enum):
    """Edit mode types"""
    PRESET = "preset"
    PRESET_WITH_MANUAL_OVERRIDES = "preset_with_manual_overrides"
    MANUAL = "manual"


@dataclass
class ProjectEditMode:
    """Project edit mode configuration"""
    type: EditMode = EditMode.MANUAL
    selected_preset: Optional[str] = None
    manual_overrides: bool = False
