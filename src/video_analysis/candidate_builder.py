"""
Candidate Clip Builder - создание кандидатов для включения в итоговое видео
"""

import random
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path

from src.config_loader import Range
from .feature_extractor import ClipFeatures, VideoFeatureExtractor

logger = logging.getLogger(__name__)


@dataclass
class CandidateClip:
    """
    Кандидат для включения в итоговое видео
    """
    source_path: str
    start: float
    end: float
    duration: float
    features: ClipFeatures
    is_must_use: bool = False

    # Scores (будут заполнены позже)
    preset_score: float = 0.0           # Score по весам стратегии
    uniqueness_score: float = 0.0       # Отличие от других клипов
    diversity_penalty: float = 0.0      # Штраф за схожесть с уже выбранными
    previous_usage_penalty: float = 0.0 # Штраф за использование в прошлых рендерах
    final_score: float = 0.0            # Итоговый score

    def __repr__(self):
        flag = "🔵" if self.is_must_use else "🟢"
        return (
            f"{flag} [{self.start:.1f}-{self.end:.1f}s] "
            f"score={self.final_score:.2f} "
            f"motion={self.features.motion_score:.2f} "
            f"stability={self.features.camera_stability_score:.2f}"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'source_path': self.source_path,
            'start': self.start,
            'end': self.end,
            'duration': self.duration,
            'features': self.features.to_dict(),
            'is_must_use': self.is_must_use,
            'preset_score': self.preset_score,
            'uniqueness_score': self.uniqueness_score,
            'final_score': self.final_score
        }


class CandidateClipBuilder:
    """
    Построение списка candidate clips из good_ranges
    """

    MAX_CANDIDATES_PER_RANGE = 12  # Hard cap — each candidate = 3 ffmpeg seeks ~1.5s
    MAX_WORKERS = 4               # Parallel ffmpeg calls per range

    @staticmethod
    def build_candidates(
        video_path: str,
        good_ranges: List[Range],
        must_use_ranges: List[Range],
        min_duration: float,
        max_duration: float,
        overlap_ratio: float = 0.0,  # Перекрытие между соседними клипами (0.0 - 0.5)
        sample_rate: int = 3  # Для feature extraction
    ) -> List[CandidateClip]:
        """
        Создать список candidate clips из ranges

        Args:
            video_path: Path to video file
            good_ranges: List of good ranges
            must_use_ranges: List of must_use ranges
            min_duration: Minimum clip duration
            max_duration: Maximum clip duration
            overlap_ratio: Overlap between adjacent clips (0.0 = no overlap, 0.5 = 50% overlap)
            sample_rate: Sample rate for feature extraction

        Returns:
            List of CandidateClip objects with extracted features
        """
        logger.info(
            f"Building candidates from {len(good_ranges)} good ranges "
            f"and {len(must_use_ranges)} must_use ranges"
        )

        candidates = []
        tasks = []

        # Collect all ranges (must_use first, then good)
        for r in must_use_ranges:
            tasks.append((r, True))
        for r in good_ranges:
            tasks.append((r, False))

        # Build candidates in parallel using ThreadPoolExecutor
        def _build_one(args):
            range_obj, is_must_use = args
            return CandidateClipBuilder._split_range_into_candidates(
                video_path=video_path,
                range_obj=range_obj,
                min_duration=min_duration,
                max_duration=max_duration,
                overlap_ratio=overlap_ratio,
                is_must_use=is_must_use,
                sample_rate=sample_rate
            )

        with ThreadPoolExecutor(max_workers=CandidateClipBuilder.MAX_WORKERS) as executor:
            futures = {executor.submit(_build_one, t): t for t in tasks}
            for future in as_completed(futures):
                try:
                    clips = future.result()
                    candidates.extend(clips)
                except Exception as e:
                    logger.warning(f"Range processing failed: {e}")

        logger.info(f"Created {len(candidates)} candidate clips")
        return candidates

    @staticmethod
    def _split_range_into_candidates(
        video_path: str,
        range_obj: Range,
        min_duration: float,
        max_duration: float,
        overlap_ratio: float = 0.0,
        is_must_use: bool = False,
        sample_rate: int = 3
    ) -> List[CandidateClip]:
        """
        Нарезать range на candidate clips

        Стратегия:
        - Если range короткий (< max_duration), создать один клип
        - Иначе создать несколько клипов со sliding window

        Args:
            overlap_ratio: 0.0 = no overlap, 0.5 = 50% overlap
        """
        range_duration = range_obj.duration

        # Если range слишком короткий, пропустить
        if range_duration < min_duration:
            logger.debug(
                f"Range [{range_obj.start}-{range_obj.end}] too short "
                f"({range_duration:.1f}s < {min_duration:.1f}s), skipping"
            )
            return []

        candidates = []

        # Если range короткий, создать один клип
        if range_duration <= max_duration:
            features = VideoFeatureExtractor.extract_features(
                video_path=video_path,
                start_time=range_obj.start,
                end_time=range_obj.end,
                sample_rate=sample_rate
            )

            if features:
                candidates.append(CandidateClip(
                    source_path=video_path,
                    start=range_obj.start,
                    end=range_obj.end,
                    duration=range_duration,
                    features=features,
                    is_must_use=is_must_use
                ))

            return candidates

        # Иначе создать несколько клипов со sliding window
        preferred_duration = (min_duration + max_duration) / 2.0
        step = preferred_duration * (1.0 - overlap_ratio)

        # Evenly-spaced starts, capped at MAX_CANDIDATES_PER_RANGE
        all_starts = []
        current_start = range_obj.start
        while current_start + min_duration <= range_obj.end:
            all_starts.append(current_start)
            current_start += step

        # If too many, subsample evenly to stay under the cap
        cap = CandidateClipBuilder.MAX_CANDIDATES_PER_RANGE
        if len(all_starts) > cap:
            indices = [int(i * (len(all_starts) - 1) / (cap - 1)) for i in range(cap)]
            all_starts = [all_starts[i] for i in indices]

        for start in all_starts:
            clip_duration = random.uniform(
                max(min_duration, preferred_duration * 0.9),
                min(max_duration, preferred_duration * 1.1)
            )
            clip_end = min(start + clip_duration, range_obj.end)

            if clip_end - start < min_duration:
                continue

            features = VideoFeatureExtractor.extract_features(
                video_path=video_path,
                start_time=start,
                end_time=clip_end,
                sample_rate=sample_rate
            )

            if features:
                candidates.append(CandidateClip(
                    source_path=video_path,
                    start=start,
                    end=clip_end,
                    duration=clip_end - start,
                    features=features,
                    is_must_use=is_must_use
                ))

        return candidates

    @staticmethod
    def filter_by_technical_quality(
        candidates: List[CandidateClip],
        min_sharpness: float = 0.2,
        min_brightness: float = 0.15,
        max_brightness: float = 0.95,
        min_stability: float = 0.0
    ) -> List[CandidateClip]:
        """
        Отфильтровать кандидатов по техническому качеству

        Убирает:
        - Слишком размытые клипы
        - Слишком темные или слишком яркие клипы
        - Слишком трясущиеся клипы (optional)

        Returns:
            Filtered list of candidates
        """
        filtered = []
        removed_count = 0

        for clip in candidates:
            f = clip.features

            # Check sharpness
            if f.sharpness_score < min_sharpness:
                logger.debug(f"Filtered out {clip.source_path} [{clip.start:.1f}s]: too blurry")
                removed_count += 1
                continue

            # Check brightness
            if f.brightness_score < min_brightness or f.brightness_score > max_brightness:
                logger.debug(
                    f"Filtered out {clip.source_path} [{clip.start:.1f}s]: "
                    f"bad brightness ({f.brightness_score:.2f})"
                )
                removed_count += 1
                continue

            # Check stability (optional)
            if min_stability > 0.0 and f.camera_stability_score < min_stability:
                logger.debug(
                    f"Filtered out {clip.source_path} [{clip.start:.1f}s]: too shaky"
                )
                removed_count += 1
                continue

            filtered.append(clip)

        if removed_count > 0:
            logger.info(
                f"Filtered out {removed_count} clips by technical quality "
                f"({len(filtered)}/{len(candidates)} remaining)"
            )

        return filtered

    @staticmethod
    def build_candidates_multi_source(
        sources: List[Dict[str, Any]],
        min_duration: float,
        max_duration: float,
        overlap_ratio: float = 0.0,
        sample_rate: int = 3
    ) -> List[CandidateClip]:
        """
        Build candidates from multiple video sources

        Args:
            sources: List of dicts with 'path', 'good_ranges', 'must_use_ranges'
            min_duration: Minimum clip duration
            max_duration: Maximum clip duration
            overlap_ratio: Overlap ratio
            sample_rate: Sample rate for feature extraction

        Returns:
            List of CandidateClip objects from all sources
        """
        all_candidates = []

        for source in sources:
            video_path = source['path']
            good_ranges = source.get('good_ranges', [])
            must_use_ranges = source.get('must_use_ranges', [])

            candidates = CandidateClipBuilder.build_candidates(
                video_path=video_path,
                good_ranges=good_ranges,
                must_use_ranges=must_use_ranges,
                min_duration=min_duration,
                max_duration=max_duration,
                overlap_ratio=overlap_ratio,
                sample_rate=sample_rate
            )

            all_candidates.extend(candidates)

        logger.info(
            f"Built {len(all_candidates)} total candidates from {len(sources)} sources"
        )

        return all_candidates


if __name__ == "__main__":
    # Test candidate builder
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.video_analysis.candidate_builder <video_path>")
        sys.exit(1)

    video_path = sys.argv[1]

    # Create test ranges
    test_ranges = [
        Range(start=5.0, end=25.0, type="good"),
        Range(start=30.0, end=50.0, type="good"),
    ]

    must_use_ranges = [
        Range(start=60.0, end=70.0, type="must_use"),
    ]

    print(f"Building candidates from {video_path}...")
    print(f"  Good ranges: {len(test_ranges)}")
    print(f"  Must-use ranges: {len(must_use_ranges)}")

    candidates = CandidateClipBuilder.build_candidates(
        video_path=video_path,
        good_ranges=test_ranges,
        must_use_ranges=must_use_ranges,
        min_duration=3.0,
        max_duration=8.0,
        overlap_ratio=0.2
    )

    print(f"\n✓ Built {len(candidates)} candidates:\n")
    for i, clip in enumerate(candidates, 1):
        print(f"{i}. {clip}")

    # Filter by quality
    print(f"\nFiltering by technical quality...")
    filtered = CandidateClipBuilder.filter_by_technical_quality(
        candidates,
        min_sharpness=0.3,
        min_brightness=0.2,
        max_brightness=0.9
    )

    print(f"\n✓ {len(filtered)} candidates passed quality filter")
