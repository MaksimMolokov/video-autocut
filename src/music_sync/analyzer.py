"""
Music analyzer using librosa
Extracts tempo, beats, onsets, and energy from audio files
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np

try:
    import librosa
    import librosa.beat
    import librosa.onset
    import librosa.feature
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    logging.warning("librosa not available. Music sync features will be disabled.")

from .models import AudioAnalysis, BeatPoint, EnergySection, EnergyLevel
from .cache import AudioAnalysisCache


logger = logging.getLogger(__name__)


class MusicAnalyzer:
    """Analyzes music files to extract tempo, beats, and energy information"""

    def __init__(self, cache_enabled: bool = True, cache_dir: str = "temp/audio_analysis"):
        """
        Initialize music analyzer

        Args:
            cache_enabled: Whether to enable caching of analysis results
            cache_dir: Directory for cache storage
        """
        self.cache_enabled = cache_enabled

        if not LIBROSA_AVAILABLE:
            raise ImportError(
                "librosa is required for music analysis. "
                "Install it with: pip install librosa"
            )

        # Initialize cache if enabled
        if cache_enabled:
            self.cache = AudioAnalysisCache(cache_dir)
        else:
            self.cache = None

    def analyze(
        self,
        audio_path: str,
        analyze_beats: bool = True,
        analyze_onsets: bool = True,
        analyze_energy: bool = True
    ) -> AudioAnalysis:
        """
        Perform complete analysis of audio file

        Args:
            audio_path: Path to audio file
            analyze_beats: Whether to perform beat detection
            analyze_onsets: Whether to perform onset detection
            analyze_energy: Whether to analyze energy levels

        Returns:
            AudioAnalysis object with all extracted features

        Raises:
            FileNotFoundError: If audio file doesn't exist
            RuntimeError: If analysis fails
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Check cache first
        if self.cache_enabled and self.cache:
            cached_analysis = self.cache.get(audio_path)
            if cached_analysis is not None:
                logger.info(f"[MusicAnalyzer] Using cached analysis for: {audio_file.name}")
                return cached_analysis

        logger.info(f"[MusicAnalyzer] Analyzing: {audio_file.name}")

        try:
            # Load audio
            y, sr = librosa.load(audio_path, sr=None, mono=True)
            duration = float(librosa.get_duration(y=y, sr=sr))

            logger.info(f"[MusicAnalyzer] Duration: {duration:.1f}s, Sample rate: {sr}Hz")

            # Create analysis object
            analysis = AudioAnalysis(
                file_path=str(audio_path),
                duration=duration,
                sample_rate=sr
            )

            # Tempo and beat analysis
            if analyze_beats:
                self._analyze_beats(y, sr, analysis)

            # Onset detection
            if analyze_onsets:
                self._analyze_onsets(y, sr, analysis)

            # Energy analysis
            if analyze_energy:
                self._analyze_energy(y, sr, analysis)

            # Advanced analysis (structure and mood detection)
            # Import here to avoid circular dependency
            from .advanced_analyzer import AdvancedMusicAnalyzer
            analysis = AdvancedMusicAnalyzer.analyze_full(analysis)

            logger.info(f"[MusicAnalyzer] Analysis complete:")
            logger.info(f"  - Tempo: {analysis.tempo:.1f} BPM" if analysis.tempo else "  - Tempo: not detected")
            logger.info(f"  - Beats: {len(analysis.beat_times)}")
            logger.info(f"  - Onsets: {len(analysis.onset_times)}")
            logger.info(f"  - Energy sections: {len(analysis.energy_sections)}")
            logger.info(f"  - Structure sections: {len(analysis.structure_sections)}")
            logger.info(f"  - Detected mood: {analysis.detected_mood.value} ({analysis.mood_confidence:.2f})")
            logger.info(f"  - Peaks: {len(analysis.peak_times)}, Drops: {len(analysis.drop_times)}")

            # Save to cache
            if self.cache_enabled and self.cache:
                self.cache.save(analysis)

            return analysis

        except Exception as e:
            logger.error(f"[MusicAnalyzer] Failed to analyze {audio_path}: {e}")
            raise RuntimeError(f"Music analysis failed: {e}") from e

    def _analyze_beats(self, y: np.ndarray, sr: int, analysis: AudioAnalysis):
        """
        Analyze tempo and beats

        Args:
            y: Audio time series
            sr: Sample rate
            analysis: AudioAnalysis object to populate
        """
        try:
            # Detect tempo and beats
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)

            analysis.tempo = float(tempo)
            analysis.beat_times = beat_times.tolist()

            # Create BeatPoint objects
            # Estimate beat strengths (simple approach: use onset strength)
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            beat_strengths = []

            for beat_frame in beat_frames:
                if beat_frame < len(onset_env):
                    strength = onset_env[beat_frame]
                    beat_strengths.append(strength)
                else:
                    beat_strengths.append(0.0)

            # Normalize strengths
            if beat_strengths:
                max_strength = max(beat_strengths)
                if max_strength > 0:
                    beat_strengths = [s / max_strength for s in beat_strengths]

            # Detect strong beats (downbeats)
            # Simple heuristic: beats with strength > 0.7 are considered strong
            for i, (time, strength) in enumerate(zip(beat_times, beat_strengths)):
                is_strong = strength > 0.7 or (i % 4 == 0)  # Every 4th beat or high strength
                beat_point = BeatPoint(
                    time=float(time),
                    strength=float(strength),
                    is_strong_beat=is_strong
                )
                analysis.beat_points.append(beat_point)

            logger.debug(f"  Detected {len(analysis.beat_points)} beats at {analysis.tempo:.1f} BPM")

        except Exception as e:
            logger.warning(f"  Beat detection failed: {e}")
            analysis.tempo = None
            analysis.beat_times = []
            analysis.beat_points = []

    def _analyze_onsets(self, y: np.ndarray, sr: int, analysis: AudioAnalysis):
        """
        Detect onset events (attacks/transients)

        Args:
            y: Audio time series
            sr: Sample rate
            analysis: AudioAnalysis object to populate
        """
        try:
            # Detect onsets
            onset_frames = librosa.onset.onset_detect(y=y, sr=sr, backtrack=True)
            onset_times = librosa.frames_to_time(onset_frames, sr=sr)

            # Get onset strengths
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            onset_strengths = []

            for frame in onset_frames:
                if frame < len(onset_env):
                    onset_strengths.append(onset_env[frame])
                else:
                    onset_strengths.append(0.0)

            # Normalize
            if onset_strengths:
                max_strength = max(onset_strengths)
                if max_strength > 0:
                    onset_strengths = [s / max_strength for s in onset_strengths]

            analysis.onset_times = onset_times.tolist()
            analysis.onset_strengths = onset_strengths

            logger.debug(f"  Detected {len(onset_times)} onsets")

        except Exception as e:
            logger.warning(f"  Onset detection failed: {e}")
            analysis.onset_times = []
            analysis.onset_strengths = []

    def _analyze_energy(self, y: np.ndarray, sr: int, analysis: AudioAnalysis):
        """
        Analyze energy levels over time

        Args:
            y: Audio time series
            sr: Sample rate
            analysis: AudioAnalysis object to populate
        """
        try:
            # Calculate RMS energy
            rms = librosa.feature.rms(y=y)[0]

            # Calculate spectral flux
            spectral_flux = np.sqrt(np.mean(np.diff(
                librosa.feature.spectral_centroid(y=y, sr=sr)
            ) ** 2, axis=0))

            # Store energy curve
            analysis.energy_curve = rms.tolist()
            analysis.spectral_flux = spectral_flux.tolist()

            # Detect energy sections
            sections = self._detect_energy_sections(rms, sr, analysis.duration)
            analysis.energy_sections = sections

            logger.debug(f"  Detected {len(sections)} energy sections")

        except Exception as e:
            logger.warning(f"  Energy analysis failed: {e}")
            analysis.energy_curve = []
            analysis.spectral_flux = []
            analysis.energy_sections = []

    def _detect_energy_sections(
        self,
        rms: np.ndarray,
        sr: int,
        duration: float,
        window_sec: float = 2.0
    ) -> List[EnergySection]:
        """
        Divide audio into sections based on energy levels

        Args:
            rms: RMS energy values
            sr: Sample rate
            duration: Total duration
            window_sec: Window size for averaging

        Returns:
            List of EnergySection objects
        """
        sections = []

        # Calculate hop length (assuming default librosa hop_length=512)
        hop_length = 512
        frame_duration = hop_length / sr

        # Smooth energy curve with moving average
        window_frames = int(window_sec / frame_duration)
        if window_frames > len(rms):
            window_frames = len(rms) // 2

        if window_frames < 1:
            window_frames = 1

        smoothed = np.convolve(rms, np.ones(window_frames) / window_frames, mode='same')

        # Normalize
        if smoothed.max() > 0:
            smoothed = smoothed / smoothed.max()

        # Classify energy levels using quantiles
        # Low: 0-33%, Medium: 33-66%, High: 66-100%
        q33 = np.quantile(smoothed, 0.33)
        q66 = np.quantile(smoothed, 0.66)

        def classify_energy(value: float) -> EnergyLevel:
            if value < q33:
                return EnergyLevel.LOW
            elif value < q66:
                return EnergyLevel.MEDIUM
            else:
                return EnergyLevel.HIGH

        # Create sections by grouping consecutive frames with same energy level
        current_level = classify_energy(smoothed[0])
        section_start = 0.0
        section_energies = [smoothed[0]]

        for i in range(1, len(smoothed)):
            level = classify_energy(smoothed[i])
            time = i * frame_duration

            if level != current_level:
                # End current section
                section = EnergySection(
                    start_time=section_start,
                    end_time=time,
                    energy_level=current_level,
                    avg_energy=float(np.mean(section_energies))
                )
                sections.append(section)

                # Start new section
                current_level = level
                section_start = time
                section_energies = [smoothed[i]]
            else:
                section_energies.append(smoothed[i])

        # Add final section
        if section_energies:
            section = EnergySection(
                start_time=section_start,
                end_time=duration,
                energy_level=current_level,
                avg_energy=float(np.mean(section_energies))
            )
            sections.append(section)

        # Merge very short sections (< 1 second)
        merged_sections = self._merge_short_sections(sections, min_duration=1.0)

        return merged_sections

    def _merge_short_sections(
        self,
        sections: List[EnergySection],
        min_duration: float = 1.0
    ) -> List[EnergySection]:
        """
        Merge sections that are too short

        Args:
            sections: List of sections
            min_duration: Minimum section duration

        Returns:
            Merged list of sections
        """
        if not sections:
            return []

        merged = []
        current = sections[0]

        for next_section in sections[1:]:
            if current.duration < min_duration:
                # Merge with next
                current = EnergySection(
                    start_time=current.start_time,
                    end_time=next_section.end_time,
                    energy_level=next_section.energy_level,  # Take next section's level
                    avg_energy=(current.avg_energy + next_section.avg_energy) / 2
                )
            else:
                merged.append(current)
                current = next_section

        # Add last section
        merged.append(current)

        return merged


if __name__ == "__main__":
    # Test analyzer
    logging.basicConfig(level=logging.DEBUG)

    if LIBROSA_AVAILABLE:
        print("✓ librosa available")
        print("  Run with actual audio file to test:")
        print('  analyzer = MusicAnalyzer()')
        print('  analysis = analyzer.analyze("path/to/audio.mp3")')
    else:
        print("✗ librosa not available - install with: pip install librosa")
