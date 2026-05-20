"""
Preset system for video editing
Provides ready-to-use editing templates with predefined settings
"""

from .preset_models import (
    ClipSelectionSettings,
    TransitionSettings,
    SpeedEffectSettings,
    ColorSettings,
    QualityFilterSettings,
    MusicSyncSettings,
    ExportSettings,
    OverlaySettings,
    PresetSettings,
    Preset,
    EditMode
)

from .preset_loader import PresetLoader
from .preset_validator import PresetValidator
from .preset_registry import PresetRegistry, PresetApplier

__all__ = [
    'ClipSelectionSettings',
    'TransitionSettings',
    'SpeedEffectSettings',
    'ColorSettings',
    'QualityFilterSettings',
    'MusicSyncSettings',
    'ExportSettings',
    'OverlaySettings',
    'PresetSettings',
    'Preset',
    'EditMode',
    'PresetLoader',
    'PresetValidator',
    'PresetRegistry',
    'PresetApplier'
]
