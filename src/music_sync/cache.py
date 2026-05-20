"""
Caching system for audio analysis results
Stores and retrieves analysis to avoid reprocessing the same audio files
"""

import json
import logging
import hashlib
from pathlib import Path
from typing import Optional
from datetime import datetime

from .models import AudioAnalysis, BeatPoint, EnergySection, EnergyLevel


logger = logging.getLogger(__name__)


class AudioAnalysisCache:
    """Manages caching of audio analysis results"""

    def __init__(self, cache_dir: str = "temp/audio_analysis"):
        """
        Initialize cache manager

        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_hash(self, file_path: str) -> str:
        """
        Calculate hash of audio file for cache key

        Args:
            file_path: Path to audio file

        Returns:
            MD5 hash of file content
        """
        md5 = hashlib.md5()

        try:
            with open(file_path, 'rb') as f:
                # Read in chunks to handle large files
                for chunk in iter(lambda: f.read(8192), b''):
                    md5.update(chunk)
            return md5.hexdigest()
        except Exception as e:
            logger.error(f"Failed to hash file {file_path}: {e}")
            raise

    def _get_cache_path(self, audio_path: str) -> Path:
        """
        Get cache file path for given audio file

        Args:
            audio_path: Path to audio file

        Returns:
            Path to cache file
        """
        file_hash = self._get_file_hash(audio_path)
        audio_name = Path(audio_path).stem
        cache_file = f"{audio_name}_{file_hash}.json"
        return self.cache_dir / cache_file

    def _is_cache_valid(self, cache_path: Path, audio_path: str) -> bool:
        """
        Check if cached analysis is still valid

        Args:
            cache_path: Path to cache file
            audio_path: Path to original audio file

        Returns:
            True if cache is valid
        """
        if not cache_path.exists():
            return False

        try:
            # Check if audio file has been modified after cache creation
            audio_mtime = Path(audio_path).stat().st_mtime
            cache_mtime = cache_path.stat().st_mtime

            if audio_mtime > cache_mtime:
                logger.debug(f"Cache invalidated - audio file modified")
                return False

            return True

        except Exception as e:
            logger.warning(f"Error checking cache validity: {e}")
            return False

    def get(self, audio_path: str) -> Optional[AudioAnalysis]:
        """
        Retrieve cached analysis for audio file

        Args:
            audio_path: Path to audio file

        Returns:
            AudioAnalysis object if cached, None otherwise
        """
        try:
            cache_path = self._get_cache_path(audio_path)

            if not self._is_cache_valid(cache_path, audio_path):
                return None

            logger.info(f"[Cache] Loading analysis from cache: {cache_path.name}")

            with open(cache_path, 'r') as f:
                data = json.load(f)

            # Reconstruct AudioAnalysis object
            analysis = self._deserialize(data)

            logger.info(f"[Cache] Successfully loaded cached analysis")
            return analysis

        except Exception as e:
            logger.warning(f"[Cache] Failed to load from cache: {e}")
            return None

    def save(self, analysis: AudioAnalysis):
        """
        Save analysis to cache

        Args:
            analysis: AudioAnalysis object to cache
        """
        try:
            cache_path = self._get_cache_path(analysis.file_path)

            logger.info(f"[Cache] Saving analysis to cache: {cache_path.name}")

            # Serialize to JSON
            data = self._serialize(analysis)

            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)

            logger.info(f"[Cache] Successfully saved to cache")

        except Exception as e:
            logger.error(f"[Cache] Failed to save to cache: {e}")
            # Don't raise - caching is optional

    def _serialize(self, analysis: AudioAnalysis) -> dict:
        """
        Serialize AudioAnalysis to JSON-compatible dict

        Args:
            analysis: AudioAnalysis object

        Returns:
            Dictionary representation
        """
        return {
            'file_path': analysis.file_path,
            'duration': analysis.duration,
            'sample_rate': analysis.sample_rate,
            'tempo': analysis.tempo,
            'beat_times': analysis.beat_times,
            'beat_points': [
                {
                    'time': bp.time,
                    'strength': bp.strength,
                    'is_strong_beat': bp.is_strong_beat
                }
                for bp in analysis.beat_points
            ],
            'onset_times': analysis.onset_times,
            'onset_strengths': analysis.onset_strengths,
            'energy_curve': analysis.energy_curve,
            'spectral_flux': analysis.spectral_flux,
            'energy_sections': [
                {
                    'start_time': es.start_time,
                    'end_time': es.end_time,
                    'energy_level': es.energy_level.value,
                    'avg_energy': es.avg_energy
                }
                for es in analysis.energy_sections
            ],
            'cached_at': datetime.now().isoformat()
        }

    def _deserialize(self, data: dict) -> AudioAnalysis:
        """
        Deserialize JSON dict to AudioAnalysis object

        Args:
            data: Dictionary representation

        Returns:
            AudioAnalysis object
        """
        analysis = AudioAnalysis(
            file_path=data['file_path'],
            duration=data['duration'],
            sample_rate=data['sample_rate'],
            tempo=data.get('tempo'),
            beat_times=data.get('beat_times', []),
            onset_times=data.get('onset_times', []),
            onset_strengths=data.get('onset_strengths', []),
            energy_curve=data.get('energy_curve', []),
            spectral_flux=data.get('spectral_flux', [])
        )

        # Reconstruct BeatPoint objects
        for bp_data in data.get('beat_points', []):
            beat_point = BeatPoint(
                time=bp_data['time'],
                strength=bp_data.get('strength', 1.0),
                is_strong_beat=bp_data.get('is_strong_beat', False)
            )
            analysis.beat_points.append(beat_point)

        # Reconstruct EnergySection objects
        for es_data in data.get('energy_sections', []):
            energy_section = EnergySection(
                start_time=es_data['start_time'],
                end_time=es_data['end_time'],
                energy_level=EnergyLevel(es_data['energy_level']),
                avg_energy=es_data['avg_energy']
            )
            analysis.energy_sections.append(energy_section)

        return analysis

    def clear(self):
        """Clear all cached analysis files"""
        try:
            count = 0
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
                count += 1

            logger.info(f"[Cache] Cleared {count} cached analysis files")

        except Exception as e:
            logger.error(f"[Cache] Failed to clear cache: {e}")

    def clear_file(self, audio_path: str):
        """
        Clear cache for specific audio file

        Args:
            audio_path: Path to audio file
        """
        try:
            cache_path = self._get_cache_path(audio_path)
            if cache_path.exists():
                cache_path.unlink()
                logger.info(f"[Cache] Cleared cache for {audio_path}")

        except Exception as e:
            logger.error(f"[Cache] Failed to clear cache for {audio_path}: {e}")
