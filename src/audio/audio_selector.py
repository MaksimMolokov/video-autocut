"""
Audio Selector - интеллектуальный выбор фрагмента аудио
"""

import logging
import numpy as np
from enum import Enum
from typing import Tuple, Optional
from dataclasses import dataclass

from .audio_analyzer import AudioAnalyzer, AudioFeatures

logger = logging.getLogger(__name__)


class AudioSelectionMode(Enum):
    """Режимы выбора аудио"""
    FROM_START = "from_start"
    AUTO_ENERGY = "auto_energy"
    AUTO_HIGHLIGHT = "auto_highlight"
    AUTO_BALANCED = "auto_balanced"
    AUTO_CINEMATIC = "auto_cinematic"
    AUTO_DYNAMIC = "auto_dynamic"


@dataclass
class AudioSelection:
    """Результат выбора аудио"""
    start_time: float
    end_time: float
    duration: float
    mode: AudioSelectionMode
    reason: str


class AudioSelector:
    """
    Интеллектуальный выбор фрагмента аудио

    КРИТИЧЕСКИ ВАЖНО: не брать начало трека по умолчанию!
    """

    @staticmethod
    def select_audio_fragment(
        audio_path: str,
        target_duration: float,
        mode: AudioSelectionMode = AudioSelectionMode.AUTO_HIGHLIGHT
    ) -> AudioSelection:
        """
        Выбрать лучший фрагмент аудио

        Args:
            audio_path: Path to audio file
            target_duration: Required duration in seconds
            mode: Selection mode

        Returns:
            AudioSelection object
        """
        logger.info(
            f"Selecting audio fragment: mode={mode.value}, "
            f"target_duration={target_duration:.1f}s"
        )

        # Analyze audio
        features = AudioAnalyzer.analyze(audio_path)

        if features is None:
            logger.warning("Audio analysis failed, using fallback")
            return AudioSelector._fallback_from_start(target_duration, "analysis_failed")

        audio_duration = features.duration

        # If audio shorter than target, use entire audio
        if audio_duration <= target_duration:
            logger.info(f"Audio ({audio_duration:.1f}s) <= target ({target_duration:.1f}s), using entire audio")
            return AudioSelection(
                start_time=0.0,
                end_time=audio_duration,
                duration=audio_duration,
                mode=mode,
                reason="audio_shorter_than_target"
            )

        # Select based on mode
        try:
            if mode == AudioSelectionMode.FROM_START:
                return AudioSelector._from_start(target_duration)

            elif mode == AudioSelectionMode.AUTO_ENERGY:
                return AudioSelector._auto_energy(features, target_duration)

            elif mode == AudioSelectionMode.AUTO_HIGHLIGHT:
                return AudioSelector._auto_highlight(features, target_duration)

            elif mode == AudioSelectionMode.AUTO_BALANCED:
                return AudioSelector._auto_balanced(features, target_duration)

            elif mode == AudioSelectionMode.AUTO_CINEMATIC:
                return AudioSelector._auto_cinematic(features, target_duration)

            elif mode == AudioSelectionMode.AUTO_DYNAMIC:
                return AudioSelector._auto_dynamic(features, target_duration)

            else:
                logger.warning(f"Unknown mode {mode}, using fallback")
                return AudioSelector._fallback_from_start(target_duration, "unknown_mode")

        except Exception as e:
            logger.error(f"Selection failed for mode {mode}: {e}")
            return AudioSelector._fallback_from_start(target_duration, f"error: {e}")

    @staticmethod
    def _from_start(duration: float) -> AudioSelection:
        """Режим: взять с начала"""
        return AudioSelection(
            start_time=0.0,
            end_time=duration,
            duration=duration,
            mode=AudioSelectionMode.FROM_START,
            reason="explicit_from_start_mode"
        )

    @staticmethod
    def _auto_energy(features: AudioFeatures, duration: float) -> AudioSelection:
        """
        AUTO_ENERGY: ищет участок с максимальной энергией

        Критерии:
        - Высокая средняя энергия
        - Высокая onset density
        - Сильный ритм
        """
        window_samples = int(duration / (features.energy_timestamps[1] - features.energy_timestamps[0]))

        best_start = 0.0
        max_score = 0.0

        for i in range(0, len(features.rms_energy) - window_samples, 10):  # Step by 10 for performance
            window_energy = features.rms_energy[i:i+window_samples]
            avg_energy = np.mean(window_energy)

            # Onset density in this window
            if features.onset_strength is not None:
                window_onset = features.onset_strength[i:i+window_samples]
                onset_density = np.sum(window_onset > np.percentile(features.onset_strength, 75))
            else:
                onset_density = 0

            # Combined score
            score = avg_energy * 0.7 + (onset_density / window_samples) * 0.3

            if score > max_score:
                max_score = score
                best_start = features.energy_timestamps[i]

        end_time = min(best_start + duration, features.duration)

        logger.info(
            f"AUTO_ENERGY selected: {best_start:.1f}s-{end_time:.1f}s "
            f"(avg_energy={max_score:.3f})"
        )

        return AudioSelection(
            start_time=best_start,
            end_time=end_time,
            duration=end_time - best_start,
            mode=AudioSelectionMode.AUTO_ENERGY,
            reason=f"highest_average_energy + high_onset_density (score={max_score:.3f})"
        )

    @staticmethod
    def _auto_highlight(features: AudioFeatures, duration: float) -> AudioSelection:
        """
        AUTO_HIGHLIGHT: ищет кульминацию трека

        Критерии:
        - Максимальная энергия
        - Высокая onset strength
        - Пик интенсивности
        """
        # Find climax
        climax_time = AudioAnalyzer.find_climax(features)

        # Center window around climax
        start_time = max(0, climax_time - duration / 2)
        end_time = min(start_time + duration, features.duration)

        # Adjust if hit end
        if end_time >= features.duration:
            end_time = features.duration
            start_time = max(0, end_time - duration)

        logger.info(
            f"AUTO_HIGHLIGHT selected: {start_time:.1f}s-{end_time:.1f}s "
            f"(centered on climax at {climax_time:.1f}s)"
        )

        return AudioSelection(
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time,
            mode=AudioSelectionMode.AUTO_HIGHLIGHT,
            reason=f"climax_centered (climax_at={climax_time:.1f}s)"
        )

    @staticmethod
    def _auto_balanced(features: AudioFeatures, duration: float) -> AudioSelection:
        """
        AUTO_BALANCED: ищет стабильный участок со средней энергией

        Критерии:
        - Средняя энергия (близкая к avg)
        - Низкая дисперсия
        - Без резких скачков
        """
        best_start = AudioAnalyzer.find_stable_section(features, duration)
        end_time = min(best_start + duration, features.duration)

        logger.info(
            f"AUTO_BALANCED selected: {best_start:.1f}s-{end_time:.1f}s "
            f"(stable medium energy)"
        )

        return AudioSelection(
            start_time=best_start,
            end_time=end_time,
            duration=end_time - best_start,
            mode=AudioSelectionMode.AUTO_BALANCED,
            reason="stable_medium_energy + low_variance"
        )

    @staticmethod
    def _auto_cinematic(features: AudioFeatures, duration: float) -> AudioSelection:
        """
        AUTO_CINEMATIC: ищет плавный атмосферный участок

        Критерии:
        - Стабильная энергия
        - Низкая дисперсия
        - Без резких onset
        """
        window_samples = int(duration / (features.energy_timestamps[1] - features.energy_timestamps[0]))

        best_start = 0.0
        min_variance = float('inf')

        for i in range(0, len(features.rms_energy) - window_samples, 10):
            window_energy = features.rms_energy[i:i+window_samples]
            variance = np.var(window_energy)

            # Penalize high onset activity
            if features.onset_strength is not None:
                window_onset = features.onset_strength[i:i+window_samples]
                onset_activity = np.mean(window_onset)
                score = variance + onset_activity * 0.5
            else:
                score = variance

            if score < min_variance:
                min_variance = score
                best_start = features.energy_timestamps[i]

        end_time = min(best_start + duration, features.duration)

        logger.info(
            f"AUTO_CINEMATIC selected: {best_start:.1f}s-{end_time:.1f}s "
            f"(low_variance={min_variance:.3f})"
        )

        return AudioSelection(
            start_time=best_start,
            end_time=end_time,
            duration=end_time - best_start,
            mode=AudioSelectionMode.AUTO_CINEMATIC,
            reason=f"stable_energy + low_abrupt_changes (variance={min_variance:.3f})"
        )

    @staticmethod
    def _auto_dynamic(features: AudioFeatures, duration: float) -> AudioSelection:
        """
        AUTO_DYNAMIC: ищет участок с ростом энергии

        Критерии:
        - Начало: низкая/средняя энергия
        - Развитие: рост энергии
        - Финал: высокая энергия
        """
        window_samples = int(duration / (features.energy_timestamps[1] - features.energy_timestamps[0]))

        best_start = 0.0
        max_growth = 0.0

        for i in range(0, len(features.rms_energy) - window_samples, 10):
            window = features.rms_energy[i:i+window_samples]

            # Calculate energy growth
            first_third = np.mean(window[:len(window)//3])
            last_third = np.mean(window[-len(window)//3:])
            growth = last_third - first_third

            if growth > max_growth:
                max_growth = growth
                best_start = features.energy_timestamps[i]

        end_time = min(best_start + duration, features.duration)

        logger.info(
            f"AUTO_DYNAMIC selected: {best_start:.1f}s-{end_time:.1f}s "
            f"(energy_growth={max_growth:.3f})"
        )

        return AudioSelection(
            start_time=best_start,
            end_time=end_time,
            duration=end_time - best_start,
            mode=AudioSelectionMode.AUTO_DYNAMIC,
            reason=f"energy_growth (delta={max_growth:.3f})"
        )

    @staticmethod
    def _fallback_from_start(duration: float, reason: str) -> AudioSelection:
        """Fallback: взять с начала"""
        logger.warning(f"Fallback to from_start because: {reason}")
        return AudioSelection(
            start_time=0.0,
            end_time=duration,
            duration=duration,
            mode=AudioSelectionMode.FROM_START,
            reason=f"fallback: {reason}"
        )


if __name__ == "__main__":
    # Test audio selector
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.audio.audio_selector <audio_path> [duration] [mode]")
        sys.exit(1)

    audio_path = sys.argv[1]
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    mode_str = sys.argv[3] if len(sys.argv) > 3 else "auto_highlight"

    mode = AudioSelectionMode(mode_str)

    print(f"Selecting audio fragment:")
    print(f"  File: {audio_path}")
    print(f"  Duration: {duration}s")
    print(f"  Mode: {mode.value}\n")

    selection = AudioSelector.select_audio_fragment(audio_path, duration, mode)

    print(f"\n✓ Selection complete:")
    print(f"  Range: {selection.start_time:.1f}s - {selection.end_time:.1f}s")
    print(f"  Duration: {selection.duration:.1f}s")
    print(f"  Reason: {selection.reason}")
