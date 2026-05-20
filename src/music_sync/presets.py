"""
Music sync presets system
Defines ready-to-use editing styles that automatically configure all sync parameters
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from enum import Enum


class MusicSyncPreset(Enum):
    """Available music sync presets"""
    DYNAMIC = "dynamic"  # Энергичные ролики, реклама, спорт
    NATURE = "nature"  # Природа, пейзажи, путешествия
    DANCE = "dance"  # Танцы, вечеринки, клубные видео
    CINEMATIC = "cinematic"  # Кинематографичный монтаж
    SOCIAL = "social"  # Reels, Shorts, TikTok
    CALM_STORY = "calm_story"  # Спокойная история
    MANUAL = "manual"  # Ручная настройка


class TransitionStyle(Enum):
    """Transition style for video cuts"""
    SHARP = "sharp"  # Резкие склейки
    SMOOTH = "smooth"  # Плавные переходы
    MIXED = "mixed"  # Смешанные
    FADE = "fade"  # Fade in/out
    SPEED_RAMP = "speed_ramp"  # Speed ramp transitions


class MotionPriority(Enum):
    """Priority for motion in video clips"""
    LOW = "low"  # Предпочтение спокойным кадрам
    MEDIUM = "medium"  # Сбалансированно
    HIGH = "high"  # Предпочтение динамичным кадрам


class BeatSensitivity(Enum):
    """Sensitivity to music beats"""
    NONE = "none"  # Не синхронизировать с битами
    LOW = "low"  # Слабая чувствительность
    MEDIUM = "medium"  # Средняя чувствительность
    HIGH = "high"  # Высокая чувствительность
    VERY_HIGH = "very_high"  # Очень высокая чувствительность


@dataclass
class AdvancedSyncSettings:
    """Advanced synchronization settings"""

    # === Beat synchronization ===
    beat_sensitivity: BeatSensitivity = BeatSensitivity.MEDIUM
    sync_to_strong_beats_only: bool = False  # Синхронизация только к сильным битам
    sync_to_bass: bool = True  # Учитывать бас
    sync_to_vocals: bool = False  # Учитывать вокал
    beat_tolerance: float = 0.15  # Допуск для выравнивания по битам (секунды)

    # === Energy adaptation ===
    energy_sensitivity: float = 0.7  # Чувствительность к изменению энергии (0.0-1.0)
    adapt_to_energy_changes: bool = True  # Адаптировать монтаж под изменения энергии
    emphasize_climax: bool = True  # Усиливать динамику на кульминации
    emphasize_drop: bool = True  # Усиливать динамику на дропе
    calm_intro_outro: bool = True  # Спокойное начало и конец

    # === Clip duration ===
    min_clip_duration: float = 0.8  # Минимальная длительность клипа (секунды)
    max_clip_duration: float = 8.0  # Максимальная длительность клипа (секунды)
    target_avg_duration: float = 3.0  # Целевая средняя длительность
    allow_short_inserts: bool = True  # Разрешить короткие быстрые вставки
    allow_long_shots: bool = True  # Разрешить длинные атмосферные кадры
    prevent_too_frequent_cuts: bool = False  # Ограничить слишком частую смену
    prevent_too_static: bool = True  # Ограничить слишком статичные сцены

    # === Editing dynamics ===
    overall_dynamics: float = 0.5  # Общая динамичность монтажа (0.0-1.0)
    gradual_buildup: bool = True  # Плавное нарастание динамики
    intensify_on_chorus: bool = True  # Усиление на припеве
    reduce_on_calm_parts: bool = True  # Снижение на спокойных частях
    auto_tempo_adaptation: bool = True  # Автоматическая смена темпа
    cut_aggressiveness: float = 0.5  # Агрессивность склеек (0.0-1.0)

    # === Transitions ===
    transition_style: TransitionStyle = TransitionStyle.MIXED
    transition_frequency: float = 0.3  # Частота использования переходов (0.0-1.0)
    use_fades: bool = True
    use_speed_ramps: bool = False
    match_cut_preference: bool = False

    # === Clip selection ===
    motion_priority: MotionPriority = MotionPriority.MEDIUM
    stable_shot_priority: bool = False  # Приоритет стабильным кадрам
    quality_filter_enabled: bool = True  # Фильтрация некачественных кадров
    exclude_shaky: bool = True  # Исключить трясущиеся фрагменты
    exclude_dark: bool = True  # Исключить тёмные фрагменты
    exclude_weak_visual: bool = True  # Исключить визуально слабые сцены
    preserve_important_scenes: bool = True  # Сохранять важные сцены

    # === Music structure analysis ===
    detect_music_structure: bool = True  # Определять структуру трека
    adapt_to_intro: bool = True  # Адаптировать монтаж ко вступлению
    adapt_to_verse: bool = True  # Адаптировать к куплету
    adapt_to_chorus: bool = True  # Адаптировать к припеву
    adapt_to_bridge: bool = True  # Адаптировать к бриджу
    adapt_to_outro: bool = True  # Адаптировать к финалу

    # === Smart modes ===
    smart_beat_priority: bool = True  # Умный выбор важных битов
    visual_music_matching: bool = True  # Сопоставление видео с характером музыки
    mood_adaptive: bool = False  # Адаптация под настроение музыки
    energy_curve_sync: bool = True  # Синхронизация по кривой энергии


class PresetDefinitions:
    """Preset configurations"""

    PRESETS: Dict[MusicSyncPreset, Dict[str, Any]] = {

        MusicSyncPreset.DYNAMIC: {
            "name": "Dynamic",
            "emoji": "⚡",
            "description": "Энергичные ролики, реклама, спорт, дрон-съёмка",
            "settings": AdvancedSyncSettings(
                # High beat sensitivity
                beat_sensitivity=BeatSensitivity.VERY_HIGH,
                sync_to_strong_beats_only=False,
                sync_to_bass=True,
                beat_tolerance=0.1,

                # High energy adaptation
                energy_sensitivity=0.9,
                adapt_to_energy_changes=True,
                emphasize_climax=True,
                emphasize_drop=True,
                calm_intro_outro=False,

                # Short clips
                min_clip_duration=0.5,
                max_clip_duration=3.0,
                target_avg_duration=1.5,
                allow_short_inserts=True,
                allow_long_shots=False,
                prevent_too_frequent_cuts=False,
                prevent_too_static=True,

                # High dynamics
                overall_dynamics=0.9,
                gradual_buildup=True,
                intensify_on_chorus=True,
                reduce_on_calm_parts=False,
                auto_tempo_adaptation=True,
                cut_aggressiveness=0.8,

                # Sharp transitions
                transition_style=TransitionStyle.SHARP,
                transition_frequency=0.2,
                use_fades=False,
                use_speed_ramps=True,

                # Motion priority
                motion_priority=MotionPriority.HIGH,
                stable_shot_priority=False,
                quality_filter_enabled=True,
                exclude_shaky=False,  # Динамика важнее стабильности

                # Structure
                detect_music_structure=True,
                smart_beat_priority=True,
                visual_music_matching=True,
                energy_curve_sync=True
            )
        },

        MusicSyncPreset.NATURE: {
            "name": "Nature",
            "emoji": "🏔️",
            "description": "Природа, пейзажи, путешествия, спокойные видео",
            "settings": AdvancedSyncSettings(
                # Low beat sensitivity
                beat_sensitivity=BeatSensitivity.LOW,
                sync_to_strong_beats_only=True,
                sync_to_bass=False,
                beat_tolerance=0.3,

                # Moderate energy adaptation
                energy_sensitivity=0.4,
                adapt_to_energy_changes=True,
                emphasize_climax=False,
                emphasize_drop=False,
                calm_intro_outro=True,

                # Long clips
                min_clip_duration=3.0,
                max_clip_duration=10.0,
                target_avg_duration=6.0,
                allow_short_inserts=False,
                allow_long_shots=True,
                prevent_too_frequent_cuts=True,
                prevent_too_static=False,

                # Low dynamics
                overall_dynamics=0.3,
                gradual_buildup=True,
                intensify_on_chorus=False,
                reduce_on_calm_parts=True,
                auto_tempo_adaptation=True,
                cut_aggressiveness=0.2,

                # Smooth transitions
                transition_style=TransitionStyle.SMOOTH,
                transition_frequency=0.8,
                use_fades=True,
                use_speed_ramps=False,

                # Stable shots
                motion_priority=MotionPriority.LOW,
                stable_shot_priority=True,
                quality_filter_enabled=True,
                exclude_shaky=True,

                # Structure
                detect_music_structure=True,
                smart_beat_priority=True,
                visual_music_matching=True,
                energy_curve_sync=True
            )
        },

        MusicSyncPreset.DANCE: {
            "name": "Dance",
            "emoji": "💃",
            "description": "Танцы, вечеринки, клубные видео, выступления",
            "settings": AdvancedSyncSettings(
                # Very high beat sensitivity
                beat_sensitivity=BeatSensitivity.VERY_HIGH,
                sync_to_strong_beats_only=True,  # Важны сильные доли
                sync_to_bass=True,
                beat_tolerance=0.05,  # Очень точная синхронизация

                # Energy adaptation
                energy_sensitivity=0.7,
                adapt_to_energy_changes=True,
                emphasize_climax=True,
                emphasize_drop=True,
                calm_intro_outro=False,

                # Medium clips
                min_clip_duration=1.0,
                max_clip_duration=4.0,
                target_avg_duration=2.5,
                allow_short_inserts=True,
                allow_long_shots=False,
                prevent_too_frequent_cuts=False,
                prevent_too_static=True,

                # High dynamics
                overall_dynamics=0.8,
                gradual_buildup=False,
                intensify_on_chorus=True,
                reduce_on_calm_parts=False,
                auto_tempo_adaptation=True,
                cut_aggressiveness=0.6,

                # Mixed transitions
                transition_style=TransitionStyle.SHARP,
                transition_frequency=0.1,
                use_fades=False,
                use_speed_ramps=False,

                # Motion preservation
                motion_priority=MotionPriority.HIGH,
                stable_shot_priority=False,
                quality_filter_enabled=True,
                preserve_important_scenes=True,  # Не обрывать танцевальные движения

                # Structure
                detect_music_structure=True,
                smart_beat_priority=True,
                visual_music_matching=True,
                energy_curve_sync=True
            )
        },

        MusicSyncPreset.CINEMATIC: {
            "name": "Cinematic",
            "emoji": "🎬",
            "description": "Кинематографичный монтаж, презентации, атмосферные видео",
            "settings": AdvancedSyncSettings(
                # Medium beat sensitivity
                beat_sensitivity=BeatSensitivity.MEDIUM,
                sync_to_strong_beats_only=True,
                sync_to_bass=False,
                beat_tolerance=0.2,

                # Moderate energy adaptation
                energy_sensitivity=0.6,
                adapt_to_energy_changes=True,
                emphasize_climax=True,  # Кульминация важна
                emphasize_drop=True,
                calm_intro_outro=True,

                # Medium-long clips
                min_clip_duration=2.0,
                max_clip_duration=7.0,
                target_avg_duration=4.0,
                allow_short_inserts=False,
                allow_long_shots=True,
                prevent_too_frequent_cuts=True,
                prevent_too_static=False,

                # Medium dynamics
                overall_dynamics=0.5,
                gradual_buildup=True,
                intensify_on_chorus=True,
                reduce_on_calm_parts=True,
                auto_tempo_adaptation=True,
                cut_aggressiveness=0.3,

                # Smooth transitions
                transition_style=TransitionStyle.SMOOTH,
                transition_frequency=0.6,
                use_fades=True,
                use_speed_ramps=False,
                match_cut_preference=True,

                # Quality priority
                motion_priority=MotionPriority.MEDIUM,
                stable_shot_priority=True,
                quality_filter_enabled=True,
                exclude_shaky=True,
                exclude_dark=True,
                exclude_weak_visual=True,

                # Structure
                detect_music_structure=True,
                adapt_to_intro=True,
                adapt_to_verse=True,
                adapt_to_chorus=True,
                adapt_to_outro=True,
                smart_beat_priority=True,
                visual_music_matching=True,
                mood_adaptive=True
            )
        },

        MusicSyncPreset.SOCIAL: {
            "name": "Social",
            "emoji": "📱",
            "description": "Reels, Shorts, TikTok - короткие цепляющие ролики",
            "settings": AdvancedSyncSettings(
                # Very high beat sensitivity
                beat_sensitivity=BeatSensitivity.VERY_HIGH,
                sync_to_strong_beats_only=False,
                sync_to_bass=True,
                beat_tolerance=0.1,

                # Very high energy
                energy_sensitivity=1.0,
                adapt_to_energy_changes=True,
                emphasize_climax=True,
                emphasize_drop=True,
                calm_intro_outro=False,  # Быстрый старт

                # Very short clips
                min_clip_duration=0.5,
                max_clip_duration=2.5,
                target_avg_duration=1.2,
                allow_short_inserts=True,
                allow_long_shots=False,
                prevent_too_frequent_cuts=False,
                prevent_too_static=True,

                # Maximum dynamics
                overall_dynamics=1.0,
                gradual_buildup=False,  # Сразу в действие
                intensify_on_chorus=True,
                reduce_on_calm_parts=False,
                auto_tempo_adaptation=True,
                cut_aggressiveness=0.9,

                # Sharp, fast transitions
                transition_style=TransitionStyle.SHARP,
                transition_frequency=0.1,
                use_fades=False,
                use_speed_ramps=True,

                # Maximum motion
                motion_priority=MotionPriority.HIGH,
                stable_shot_priority=False,
                quality_filter_enabled=True,
                exclude_shaky=False,
                exclude_dark=True,
                exclude_weak_visual=True,  # Только яркие кадры

                # Structure
                detect_music_structure=True,
                smart_beat_priority=True,
                visual_music_matching=True,
                energy_curve_sync=True
            )
        },

        MusicSyncPreset.CALM_STORY: {
            "name": "Calm Story",
            "emoji": "📖",
            "description": "Спокойная история, семейные видео, рассказы",
            "settings": AdvancedSyncSettings(
                # Low beat sensitivity
                beat_sensitivity=BeatSensitivity.LOW,
                sync_to_strong_beats_only=True,
                sync_to_bass=False,
                beat_tolerance=0.4,

                # Low energy adaptation
                energy_sensitivity=0.3,
                adapt_to_energy_changes=True,
                emphasize_climax=False,
                emphasize_drop=False,
                calm_intro_outro=True,

                # Long clips
                min_clip_duration=3.0,
                max_clip_duration=12.0,
                target_avg_duration=7.0,
                allow_short_inserts=False,
                allow_long_shots=True,
                prevent_too_frequent_cuts=True,
                prevent_too_static=False,

                # Very low dynamics
                overall_dynamics=0.2,
                gradual_buildup=True,
                intensify_on_chorus=False,
                reduce_on_calm_parts=True,
                auto_tempo_adaptation=False,  # Естественный темп
                cut_aggressiveness=0.1,

                # Very smooth transitions
                transition_style=TransitionStyle.FADE,
                transition_frequency=0.9,
                use_fades=True,
                use_speed_ramps=False,

                # Natural flow
                motion_priority=MotionPriority.LOW,
                stable_shot_priority=True,
                quality_filter_enabled=True,
                exclude_shaky=True,
                preserve_important_scenes=True,

                # Structure
                detect_music_structure=False,  # Не агрессивно следовать структуре
                smart_beat_priority=True,
                visual_music_matching=False,  # Сохранить естественность
                mood_adaptive=True
            )
        }
    }

    @staticmethod
    def get_preset(preset: MusicSyncPreset) -> AdvancedSyncSettings:
        """Get preset settings"""
        if preset == MusicSyncPreset.MANUAL:
            # Return default settings for manual mode
            return AdvancedSyncSettings()

        preset_data = PresetDefinitions.PRESETS.get(preset)
        if preset_data:
            return preset_data["settings"]

        # Fallback to default
        return AdvancedSyncSettings()

    @staticmethod
    def get_preset_info(preset: MusicSyncPreset) -> Dict[str, str]:
        """Get preset metadata"""
        preset_data = PresetDefinitions.PRESETS.get(preset)
        if preset_data:
            return {
                "name": preset_data["name"],
                "emoji": preset_data["emoji"],
                "description": preset_data["description"]
            }
        return {"name": "Unknown", "emoji": "❓", "description": ""}

    @staticmethod
    def list_presets() -> Dict[MusicSyncPreset, Dict[str, str]]:
        """List all available presets"""
        return {
            preset: PresetDefinitions.get_preset_info(preset)
            for preset in MusicSyncPreset
            if preset != MusicSyncPreset.MANUAL
        }


# Helper functions
def get_preset_description(preset: MusicSyncPreset) -> str:
    """Get user-friendly description of a preset"""
    descriptions = {
        MusicSyncPreset.DYNAMIC: "Быстрый, энергичный монтаж с короткими клипами и резкими переходами. Идеально для динамичных видео и экшена.",
        MusicSyncPreset.NATURE: "Спокойный, плавный монтаж с длинными клипами. Отлично для природы, пейзажей, медитативных видео.",
        MusicSyncPreset.DANCE: "Агрессивный ритмичный монтаж, синхронизированный точно по битам. Для танцевальной, электронной музыки.",
        MusicSyncPreset.CINEMATIC: "Эпичный кинематографичный стиль с акцентом на кульминации. Для трейлеров, драматических видео.",
        MusicSyncPreset.SOCIAL: "Быстрый монтаж для коротких видео в соцсети. Динамично, с упором на первые секунды.",
        MusicSyncPreset.CALM_STORY: "Размеренный повествовательный стиль с плавными переходами. Для историй, документальных видео.",
        MusicSyncPreset.MANUAL: "Полный контроль над всеми параметрами синхронизации."
    }
    return descriptions.get(preset, "Пользовательская конфигурация")


# Validation functions
def validate_settings(settings: AdvancedSyncSettings) -> tuple[bool, Optional[str]]:
    """
    Validate sync settings for conflicts and invalid values

    Returns:
        (is_valid, error_message)
    """
    # Check duration constraints
    if settings.min_clip_duration >= settings.max_clip_duration:
        return False, "Минимальная длительность клипа должна быть меньше максимальной"

    if settings.target_avg_duration < settings.min_clip_duration:
        return False, "Целевая средняя длительность меньше минимальной"

    if settings.target_avg_duration > settings.max_clip_duration:
        return False, "Целевая средняя длительность больше максимальной"

    # Check value ranges
    if not (0.0 <= settings.energy_sensitivity <= 1.0):
        return False, "Чувствительность к энергии должна быть от 0.0 до 1.0"

    if not (0.0 <= settings.overall_dynamics <= 1.0):
        return False, "Общая динамичность должна быть от 0.0 до 1.0"

    if not (0.0 <= settings.cut_aggressiveness <= 1.0):
        return False, "Агрессивность склеек должна быть от 0.0 до 1.0"

    if not (0.0 <= settings.transition_frequency <= 1.0):
        return False, "Частота переходов должна быть от 0.0 до 1.0"

    if settings.beat_tolerance < 0:
        return False, "Допуск для битов не может быть отрицательным"

    # All checks passed
    return True, None


# Alias for backward compatibility with GUI
PRESET_CONFIGS = PresetDefinitions.PRESETS

