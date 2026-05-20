"""
Audio Analyzer - анализ аудиофайлов для интеллектуального выбора фрагментов
"""

import logging
import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AudioFeatures:
    """
    Признаки аудиофайла для выбора лучшего фрагмента
    """
    duration: float  # Длительность в секундах

    # Energy profile
    rms_energy: np.ndarray  # RMS energy по времени
    energy_timestamps: np.ndarray  # Временные метки

    # Onset detection
    onset_strength: Optional[np.ndarray] = None
    onset_times: Optional[np.ndarray] = None

    # Tempo and rhythm
    tempo: Optional[float] = None
    beat_times: Optional[np.ndarray] = None

    # Spectral features
    spectral_centroid: Optional[np.ndarray] = None

    # Derived features
    avg_energy: float = 0.0
    max_energy: float = 0.0
    energy_variance: float = 0.0


class AudioAnalyzer:
    """
    Анализ аудиофайлов с помощью librosa
    """

    @staticmethod
    def analyze(audio_path: str) -> Optional[AudioFeatures]:
        """
        Анализировать аудиофайл

        Args:
            audio_path: Path to audio file

        Returns:
            AudioFeatures object or None if analysis failed
        """
        try:
            import librosa

            logger.info(f"Analyzing audio: {Path(audio_path).name}")

            # Load audio
            y, sr = librosa.load(audio_path, sr=None)
            duration = librosa.get_duration(y=y, sr=sr)

            logger.debug(f"Audio loaded: duration={duration:.1f}s, sr={sr}Hz")

            # 1. RMS Energy
            hop_length = 512
            rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
            times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

            # 2. Onset Strength (для поиска активных участков)
            onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
            onset_times = times

            # 3. Tempo and beats (опционально)
            try:
                tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
                # librosa >= 0.10 may return tempo as a 1-element ndarray
                tempo = float(np.atleast_1d(tempo)[0])
                beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)
            except Exception as e:
                logger.debug(f"Beat tracking failed: {e}")
                tempo = None
                beat_times = None

            # 4. Spectral centroid (для оценки яркости звука)
            try:
                spec_cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop_length)[0]
            except Exception as e:
                logger.debug(f"Spectral centroid failed: {e}")
                spec_cent = None

            # Derived features
            avg_energy = float(np.mean(rms))
            max_energy = float(np.max(rms))
            energy_variance = float(np.var(rms))

            features = AudioFeatures(
                duration=duration,
                rms_energy=rms,
                energy_timestamps=times,
                onset_strength=onset_env,
                onset_times=onset_times,
                tempo=tempo,
                beat_times=beat_times,
                spectral_centroid=spec_cent,
                avg_energy=avg_energy,
                max_energy=max_energy,
                energy_variance=energy_variance
            )

            tempo_display = f"{float(tempo):.1f}" if tempo is not None else 'N/A'
            logger.info(
                f"Audio analysis complete: "
                f"avg_energy={avg_energy:.3f}, max_energy={max_energy:.3f}, "
                f"tempo={tempo_display}"
            )

            return features

        except ImportError:
            logger.error("librosa not installed. Install with: pip install librosa")
            return None
        except Exception as e:
            logger.error(f"Failed to analyze audio {audio_path}: {e}")
            return None

    @staticmethod
    def get_energy_profile(features: AudioFeatures, window_sec: float = 2.0) -> List[Tuple[float, float]]:
        """
        Получить профиль энергии по времени

        Args:
            features: AudioFeatures object
            window_sec: Window size in seconds

        Returns:
            List of (timestamp, energy) tuples
        """
        if features.rms_energy is None or features.energy_timestamps is None:
            return []

        # Усреднить энергию по окнам
        window_samples = int(window_sec / (features.energy_timestamps[1] - features.energy_timestamps[0]))

        profile = []
        for i in range(0, len(features.rms_energy), window_samples):
            window_energy = features.rms_energy[i:i+window_samples]
            if len(window_energy) > 0:
                timestamp = features.energy_timestamps[i]
                energy = float(np.mean(window_energy))
                profile.append((timestamp, energy))

        return profile

    @staticmethod
    def find_climax(features: AudioFeatures) -> float:
        """
        Найти кульминацию трека (момент максимальной энергии + onset)

        Returns:
            Timestamp of climax in seconds
        """
        if features.onset_strength is None:
            # Fallback to max energy
            max_idx = np.argmax(features.rms_energy)
            return float(features.energy_timestamps[max_idx])

        # Combine energy and onset strength
        combined = features.rms_energy * 0.6 + features.onset_strength * 0.4

        # Find peak
        peak_idx = np.argmax(combined)
        return float(features.energy_timestamps[peak_idx])

    @staticmethod
    def find_stable_section(features: AudioFeatures, duration: float) -> float:
        """
        Найти стабильный участок заданной длительности

        Стабильный = средняя энергия, низкая дисперсия

        Args:
            features: AudioFeatures object
            duration: Required duration in seconds

        Returns:
            Start timestamp of stable section
        """
        window_samples = int(duration / (features.energy_timestamps[1] - features.energy_timestamps[0]))

        best_start = 0.0
        min_variance = float('inf')

        for i in range(0, len(features.rms_energy) - window_samples):
            window = features.rms_energy[i:i+window_samples]
            variance = np.var(window)
            avg_energy = np.mean(window)

            # Prefer medium energy with low variance
            score = variance - abs(avg_energy - features.avg_energy) * 0.5

            if score < min_variance:
                min_variance = score
                best_start = features.energy_timestamps[i]

        return float(best_start)


if __name__ == "__main__":
    # Test audio analyzer
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.audio.audio_analyzer <audio_path>")
        sys.exit(1)

    audio_path = sys.argv[1]
    print(f"Analyzing {audio_path}...")

    features = AudioAnalyzer.analyze(audio_path)

    if features:
        print(f"\n✓ Analysis complete:")
        print(f"  Duration: {features.duration:.1f}s")
        print(f"  Avg Energy: {features.avg_energy:.3f}")
        print(f"  Max Energy: {features.max_energy:.3f}")
        print(f"  Tempo: {f'{float(features.tempo):.1f}' if features.tempo is not None else 'N/A'} BPM")

        climax = AudioAnalyzer.find_climax(features)
        print(f"  Climax at: {climax:.1f}s")

        stable = AudioAnalyzer.find_stable_section(features, 60.0)
        print(f"  Stable section (60s): {stable:.1f}s")
    else:
        print("✗ Analysis failed")
