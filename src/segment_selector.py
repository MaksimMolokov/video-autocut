"""
Segment selector - algorithm for choosing video segments
"""

import random
import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
from src.config_loader import Range

logger = logging.getLogger(__name__)

# motion_score = mean_optical_flow_magnitude / MOTION_MAX(50).
# Below this threshold the clip is visually a frozen/static frame.
# ~0.05 = 2.5 px mean flow at 320px width — imperceptible to the eye.
# must_use clips are never removed by this filter.
STILL_MOTION_THRESHOLD = 0.05


@dataclass
class SelectedSegment:
    """A selected video segment for the final output."""
    source_path: str
    start: float
    end: float
    duration: float
    is_must_use: bool

    # Timeline role assigned by TimelineBuilder (default = 'body').
    # Other values: 'intro', 'outro'.
    # Extra transition metadata is set as plain attributes by TimelineBuilder,
    # not declared here to preserve backward compatibility with all callers
    # that construct SelectedSegment without these fields.
    role: str = 'body'

    def __repr__(self):
        flag = "🔵" if self.is_must_use else "🟢"
        role_tag = f" [{self.role}]" if self.role != 'body' else ""
        return f"{flag}{role_tag} [{self.start:.1f}-{self.end:.1f}] ({self.duration:.1f}s)"


class DynamicLevelConfig:
    """Configuration for different dynamic levels"""

    CONFIGS = {
        "slow": {
            "min_segment_duration": 3.0,
            "max_segment_duration": 10.0,
            "preferred_segment_duration": 6.0,
        },
        "balanced": {
            "min_segment_duration": 2.0,
            "max_segment_duration": 6.0,
            "preferred_segment_duration": 4.0,
        },
        "fast": {
            "min_segment_duration": 1.0,
            "max_segment_duration": 4.0,
            "preferred_segment_duration": 2.5,
        }
    }

    @staticmethod
    def get(level: str) -> dict:
        """Get configuration for dynamic level"""
        return DynamicLevelConfig.CONFIGS[level]


class SegmentSelector:
    """Selects video segments based on configuration"""

    @staticmethod
    def select_segments(
        source_path: str,
        ranges: List[Range],
        target_duration: float,
        dynamic_level: str,
        seed: int = None
    ) -> List[SelectedSegment]:
        """
        Select video segments to match target duration

        Args:
            source_path: Path to source video file
            ranges: List of Range objects (good/bad/must_use)
            target_duration: Desired total duration in seconds
            dynamic_level: "slow", "balanced", or "fast"
            seed: Random seed for reproducibility (optional)

        Returns:
            List of SelectedSegment objects

        Raises:
            ValueError: If not enough usable footage
        """
        if seed is not None:
            random.seed(seed)

        config = DynamicLevelConfig.get(dynamic_level)

        # Separate must_use from good ranges
        must_use_ranges = [r for r in ranges if r.type == "must_use"]
        good_ranges = [r for r in ranges if r.type == "good"]

        # Start with must_use segments (these are mandatory)
        selected = []
        total_duration = 0.0

        for r in must_use_ranges:
            # Split large must_use ranges if needed
            segments = SegmentSelector._split_range_into_segments(
                r, config["max_segment_duration"]
            )
            for seg_start, seg_end in segments:
                seg_duration = seg_end - seg_start
                selected.append(SelectedSegment(
                    source_path=source_path,
                    start=seg_start,
                    end=seg_end,
                    duration=seg_duration,
                    is_must_use=True
                ))
                total_duration += seg_duration

        # Check if must_use already exceeds target
        if total_duration >= target_duration:
            # Trim to fit target
            return SegmentSelector._trim_to_target(selected, target_duration)

        # Calculate remaining duration needed
        remaining_duration = target_duration - total_duration

        # Select from good ranges to fill remaining duration
        good_segments = SegmentSelector._select_from_good_ranges(
            source_path=source_path,
            good_ranges=good_ranges,
            remaining_duration=remaining_duration,
            config=config
        )

        selected.extend(good_segments)

        # Sort by start time
        selected.sort(key=lambda s: s.start)

        return selected

    @staticmethod
    def _split_range_into_segments(
        range_obj: Range,
        max_segment_duration: float
    ) -> List[Tuple[float, float]]:
        """
        Split a range into segments respecting max duration

        Returns:
            List of (start, end) tuples
        """
        segments = []
        current = range_obj.start

        while current < range_obj.end:
            segment_end = min(current + max_segment_duration, range_obj.end)
            segments.append((current, segment_end))
            current = segment_end

        return segments

    @staticmethod
    def _select_from_good_ranges(
        source_path: str,
        good_ranges: List[Range],
        remaining_duration: float,
        config: dict
    ) -> List[SelectedSegment]:
        """
        Select segments from good ranges to fill remaining duration

        Uses a greedy algorithm with randomization:
        1. Shuffle good ranges for variety
        2. From each range, extract segments matching preferred duration
        3. Continue until target duration is reached
        """
        if not good_ranges:
            raise ValueError("Not enough usable footage to reach target duration")

        selected = []
        total_selected = 0.0

        min_dur = config["min_segment_duration"]
        max_dur = config["max_segment_duration"]
        preferred_dur = config["preferred_segment_duration"]

        # Shuffle ranges for variety
        shuffled_ranges = good_ranges.copy()
        random.shuffle(shuffled_ranges)

        # Keep cycling through ranges until we have enough
        range_idx = 0
        attempts = 0
        max_attempts = len(shuffled_ranges) * 10  # Prevent infinite loop

        while total_selected < remaining_duration and attempts < max_attempts:
            attempts += 1

            # Get current range
            current_range = shuffled_ranges[range_idx % len(shuffled_ranges)]
            range_idx += 1

            # Skip if range is too short
            if current_range.duration < min_dur:
                continue

            # Calculate segment duration
            needed = remaining_duration - total_selected
            segment_duration = min(
                max_dur,
                max(min_dur, min(needed, preferred_dur))
            )

            # Can't fit minimum segment? Try to use what's left
            if needed < min_dur:
                segment_duration = needed

            # Pick random start within range
            max_start = current_range.end - segment_duration
            if max_start < current_range.start:
                continue

            segment_start = random.uniform(current_range.start, max_start)
            segment_end = segment_start + segment_duration

            # Add segment
            selected.append(SelectedSegment(
                source_path=source_path,
                start=segment_start,
                end=segment_end,
                duration=segment_duration,
                is_must_use=False
            ))
            total_selected += segment_duration

        # Check if we got enough footage
        if total_selected < remaining_duration * 0.9:  # Allow 10% tolerance
            raise ValueError(
                f"Not enough usable footage: need {remaining_duration:.1f}s, "
                f"got {total_selected:.1f}s"
            )

        return selected

    @staticmethod
    def _trim_to_target(
        segments: List[SelectedSegment],
        target_duration: float
    ) -> List[SelectedSegment]:
        """
        Trim segments list to match target duration

        Removes or trims the last segment to fit exactly
        """
        if not segments:
            return []

        total = 0.0
        result = []

        for seg in segments:
            if total + seg.duration <= target_duration:
                # Fits completely
                result.append(seg)
                total += seg.duration
            else:
                # Need to trim this segment
                remaining = target_duration - total
                if remaining > 0:
                    trimmed = SelectedSegment(
                        source_path=seg.source_path,
                        start=seg.start,
                        end=seg.start + remaining,
                        duration=remaining,
                        is_must_use=seg.is_must_use
                    )
                    result.append(trimmed)
                break

        return result

    @staticmethod
    def select_segments_multi_source(
        sources: List[dict],
        target_duration: float,
        dynamic_level: str,
        alternate_sources: bool = True,
        seed: int = None
    ) -> List[SelectedSegment]:
        """
        Select segments from multiple video sources with smart alternation

        Args:
            sources: List of dicts with 'path', 'ranges', 'duration'
            target_duration: Target total duration
            dynamic_level: "slow", "balanced", or "fast"
            alternate_sources: If True, alternate between sources
            seed: Random seed

        Returns:
            List of SelectedSegment objects, alternating between sources
        """
        if seed is not None:
            random.seed(seed)

        config = DynamicLevelConfig.get(dynamic_level)
        all_segments = []

        if not alternate_sources or len(sources) == 1:
            # Old behavior: process each source independently
            for source in sources:
                segments = SegmentSelector.select_segments(
                    source_path=source['path'],
                    ranges=source['ranges'],
                    target_duration=target_duration / len(sources),  # Divide equally
                    dynamic_level=dynamic_level,
                    seed=seed
                )
                all_segments.extend(segments)
            return all_segments

        # New behavior: alternate between sources
        # Track used time ranges for each source to avoid duplicates
        used_ranges = {source['path']: [] for source in sources}

        total_collected = 0.0
        source_idx = 0
        max_attempts = target_duration * 10  # Prevent infinite loop
        attempts = 0

        while total_collected < target_duration and attempts < max_attempts:
            attempts += 1

            # Get current source (round-robin)
            source = sources[source_idx % len(sources)]
            source_idx += 1

            source_path = source['path']
            ranges = source['ranges']

            # How much more do we need?
            remaining = target_duration - total_collected

            # Separate must_use from good
            must_use = [r for r in ranges if r.type == "must_use"]
            good = [r for r in ranges if r.type == "good"]

            # Prefer must_use first, then good
            available_ranges = must_use if must_use else good
            if not available_ranges:
                continue

            # Pick a random range that hasn't been fully used
            random.shuffle(available_ranges)

            selected_range = None
            for r in available_ranges:
                # Check if this range has unused portions
                if not SegmentSelector._is_range_exhausted(r, used_ranges[source_path], config["min_segment_duration"]):
                    selected_range = r
                    break

            if not selected_range:
                # This source is exhausted, try next
                continue

            # Calculate segment duration
            segment_duration = min(
                config["max_segment_duration"],
                max(config["min_segment_duration"], min(remaining, config["preferred_segment_duration"]))
            )

            # Find unused portion in the range
            segment_start, segment_end = SegmentSelector._find_unused_segment(
                selected_range,
                used_ranges[source_path],
                segment_duration,
                config["min_segment_duration"]
            )

            if segment_start is None:
                continue

            # Create segment
            actual_duration = segment_end - segment_start
            new_segment = SelectedSegment(
                source_path=source_path,
                start=segment_start,
                end=segment_end,
                duration=actual_duration,
                is_must_use=(selected_range.type == "must_use")
            )

            all_segments.append(new_segment)
            used_ranges[source_path].append((segment_start, segment_end))
            total_collected += actual_duration

        return all_segments

    @staticmethod
    def _is_range_exhausted(
        range_obj: Range,
        used_segments: List[Tuple[float, float]],
        min_duration: float
    ) -> bool:
        """Check if a range has any unused portions left"""
        if not used_segments:
            return False

        # Check if there's any gap of at least min_duration
        sorted_used = sorted(used_segments)

        # Check before first used segment
        if sorted_used[0][0] - range_obj.start >= min_duration:
            return False

        # Check between used segments
        for i in range(len(sorted_used) - 1):
            gap = sorted_used[i+1][0] - sorted_used[i][1]
            if gap >= min_duration:
                return False

        # Check after last used segment
        if range_obj.end - sorted_used[-1][1] >= min_duration:
            return False

        return True

    @staticmethod
    def _find_unused_segment(
        range_obj: Range,
        used_segments: List[Tuple[float, float]],
        desired_duration: float,
        min_duration: float
    ) -> Tuple[float, float]:
        """
        Find an unused portion of the range for the segment

        Returns:
            (start, end) or (None, None) if no space available
        """
        if not used_segments:
            # Entire range is available
            start = range_obj.start
            end = min(start + desired_duration, range_obj.end)
            return (start, end)

        sorted_used = sorted(used_segments)

        # Try to find gap between used segments or at edges
        available_gaps = []

        # Gap before first used segment
        if sorted_used[0][0] - range_obj.start >= min_duration:
            available_gaps.append((range_obj.start, sorted_used[0][0]))

        # Gaps between used segments
        for i in range(len(sorted_used) - 1):
            gap_start = sorted_used[i][1]
            gap_end = sorted_used[i+1][0]
            if gap_end - gap_start >= min_duration:
                available_gaps.append((gap_start, gap_end))

        # Gap after last used segment
        if range_obj.end - sorted_used[-1][1] >= min_duration:
            available_gaps.append((sorted_used[-1][1], range_obj.end))

        if not available_gaps:
            return (None, None)

        # Pick random gap
        gap_start, gap_end = random.choice(available_gaps)
        available_duration = gap_end - gap_start

        # Calculate actual segment within this gap
        actual_duration = min(desired_duration, available_duration)

        # Random start within the gap
        max_start = gap_end - actual_duration
        segment_start = random.uniform(gap_start, max_start) if max_start > gap_start else gap_start
        segment_end = segment_start + actual_duration

        return (segment_start, segment_end)

    @staticmethod
    def get_total_duration(segments: List[SelectedSegment]) -> float:
        """Calculate total duration of selected segments"""
        return sum(s.duration for s in segments)

    @staticmethod
    def validate_segments(
        segments: List[SelectedSegment],
        target_duration: float,
        tolerance: float = 0.1
    ) -> bool:
        """
        Validate that segments meet target duration within tolerance

        Args:
            segments: List of selected segments
            target_duration: Target duration in seconds
            tolerance: Allowed deviation as fraction (0.1 = 10%)

        Returns:
            True if valid

        Raises:
            ValueError: If segments are invalid
        """
        if not segments:
            raise ValueError("No segments selected")

        total = SegmentSelector.get_total_duration(segments)
        lower_bound = target_duration * (1 - tolerance)
        upper_bound = target_duration * (1 + tolerance)

        if not (lower_bound <= total <= upper_bound):
            raise ValueError(
                f"Total duration ({total:.1f}s) outside target range "
                f"[{lower_bound:.1f}s - {upper_bound:.1f}s]"
            )

        return True

    @staticmethod
    def select_segments_with_strategy(
        source_path: str,
        ranges: List[Range],
        target_duration: float,
        preset_id: str,
        project_dir: Optional[Path] = None,
        use_clip_selection: bool = True,
        seed: int = None,
        return_candidates: bool = False,
    ):
        """
        Выбрать сегменты используя clip selection strategy из пресета

        КЛЮЧЕВОЙ МЕТОД для preset-specific clip selection

        Args:
            source_path: Path to source video file
            ranges: List of Range objects (good/bad/must_use)
            target_duration: Desired total duration in seconds
            preset_id: ID пресета (определяет стратегию)
            project_dir: Path to project directory (for render history)
            use_clip_selection: If True, use new clip selection system
            seed: Random seed for reproducibility

        Returns:
            List of SelectedSegment objects

        Flow:
        1. Build candidate clips from ranges
        2. Extract features for each candidate
        3. Get strategy from StrategyRegistry by preset_id
        4. Filter candidates by strategy rules
        5. Compute preset_score for each
        6. Apply diversity penalty
        7. Apply previous_usage_penalty from render history
        8. Select best clips for target_duration
        9. Order clips by ordering_type
        10. Return as List[SelectedSegment]
        """
        if not use_clip_selection:
            # Fallback to old method
            logger.info("Using legacy selection method (clip_selection disabled)")
            dynamic_level = "balanced"  # Default
            return SegmentSelector.select_segments(
                source_path, ranges, target_duration, dynamic_level, seed
            )

        logger.info(f"[ClipSelection] Preset: {preset_id}")
        logger.info(f"[ClipSelection] Target duration: {target_duration:.1f}s")

        try:
            # Import here to avoid circular imports
            from src.video_analysis import CandidateClipBuilder
            from src.clip_selection import (
                StrategyRegistry, ClipScorer, DiversitySelector,
                OrderingEngine, RenderHistory
            )

            # Separate ranges by type
            good_ranges = [r for r in ranges if r.type == "good"]
            must_use_ranges = [r for r in ranges if r.type == "must_use"]

            # Get strategy
            strategy = StrategyRegistry.get_strategy(preset_id)
            logger.info(f"[ClipSelection] Strategy: {strategy.get_strategy_name()}")

            # Determine min/max duration from preset settings
            min_duration = 2.0
            max_duration = 6.0
            try:
                from src.presets import PresetRegistry
                from pathlib import Path as _Path
                _presets_dir = _Path(__file__).parent.parent / "presets"
                _registry = PresetRegistry(_presets_dir)
                _preset = _registry.get_preset(preset_id)
                if _preset:
                    min_duration = _preset.settings.clip_selection.segment_min_duration
                    max_duration = _preset.settings.clip_selection.segment_max_duration
                    logger.info(f"[ClipSelection] Clip duration from preset: {min_duration:.1f}s - {max_duration:.1f}s")
            except Exception as _e:
                logger.warning(f"[ClipSelection] Could not load preset settings, using defaults: {_e}")

            # 1. Build candidate clips
            logger.info(f"[ClipSelection] Building candidates from {len(good_ranges)} good ranges and {len(must_use_ranges)} must_use ranges...")

            candidates = CandidateClipBuilder.build_candidates(
                video_path=source_path,
                good_ranges=good_ranges,
                must_use_ranges=must_use_ranges,
                min_duration=min_duration,
                max_duration=max_duration,
                overlap_ratio=0.1,
                sample_rate=3
            )

            logger.info(f"[ClipSelection] Candidate clips: {len(candidates)}")

            if not candidates:
                logger.warning("[ClipSelection] No candidates created, using fallback")
                return SegmentSelector.select_segments(
                    source_path, ranges, target_duration, "balanced", seed
                )

            # 1.5. Universal still-frame filter — all presets, all styles.
            # Removes clips where nothing is happening (frozen/static frame).
            # must_use clips are exempt; clips with missing features are kept.
            _pre_still = candidates
            candidates = [
                c for c in candidates
                if c.is_must_use
                or c.features is None
                or c.features.motion_score >= STILL_MOTION_THRESHOLD
            ]
            _n_removed = len(_pre_still) - len(candidates)
            if _n_removed:
                logger.info(
                    f"[ClipSelection] Still-frame filter: removed {_n_removed}/{len(_pre_still)} "
                    f"static clips (motion_score < {STILL_MOTION_THRESHOLD})"
                )
            if not candidates:
                logger.warning("[ClipSelection] Still-frame filter removed all candidates — restoring pool")
                candidates = _pre_still

            # 2. Filter by strategy
            logger.info("[ClipSelection] Applying strategy filter...")
            candidates = strategy.filter_candidates(candidates)
            logger.info(f"[ClipSelection] After filtering: {len(candidates)} candidates")

            # 3. Compute uniqueness
            logger.info("[ClipSelection] Computing uniqueness scores...")
            candidates = DiversitySelector.compute_uniqueness_scores(candidates)

            # 4. Score by strategy
            logger.info("[ClipSelection] Computing preset scores...")
            candidates = ClipScorer.score_clips(candidates, strategy)

            # 5. Apply render history penalty
            if project_dir:
                try:
                    history = RenderHistory(project_dir)
                    used_clips = history.get_used_clips(limit=3)
                    if used_clips:
                        logger.info(f"[ClipSelection] Found {len(used_clips)} previously used clips")
                        candidates = RenderHistory.apply_previous_usage_penalty(
                            candidates, used_clips, penalty=0.5
                        )
                except Exception as e:
                    logger.warning(f"[ClipSelection] Render history failed: {e}")

            # 6. Compute final scores
            candidates = ClipScorer.compute_final_scores(candidates)

            # Early exit: return all scored candidates for TimelineBuilder
            if return_candidates:
                logger.info(f"[ClipSelection] Returning {len(candidates)} scored candidates")
                return candidates

            # 7. Select with diversity
            # Estimate how many clips we need
            avg_clip_duration = (min_duration + max_duration) / 2
            target_clip_count = int(target_duration / avg_clip_duration * 1.5)  # 50% buffer

            logger.info(f"[ClipSelection] Selecting {target_clip_count} clips with diversity...")

            selected = DiversitySelector.select_with_diversity(
                candidates,
                target_count=target_clip_count,
                diversity_threshold=strategy.get_diversity_threshold(),
                randomness=strategy.get_randomness_level()
            )

            logger.info(f"[ClipSelection] Selected {len(selected)} clips")

            # 8. Trim to target duration
            selected_sorted = sorted(selected, key=lambda c: c.final_score, reverse=True)
            final_selected = []
            total_duration = 0.0

            for clip in selected_sorted:
                if total_duration + clip.duration <= target_duration * 1.1:  # 10% tolerance
                    final_selected.append(clip)
                    total_duration += clip.duration

                if total_duration >= target_duration:
                    break

            logger.info(f"[ClipSelection] Final selection: {len(final_selected)} clips, total {total_duration:.1f}s")

            # 9. Order by strategy
            ordering_type = strategy.get_ordering_type()
            logger.info(f"[ClipSelection] Ordering: {ordering_type}")

            ordered = OrderingEngine.order_clips(final_selected, ordering_type)

            # Log selected clips
            for i, clip in enumerate(ordered[:5], 1):  # Log first 5
                logger.info(
                    f"[ClipSelected #{i}] {Path(clip.source_path).name} "
                    f"{clip.start:.1f}s-{clip.end:.1f}s "
                    f"score={clip.final_score:.2f} "
                    f"motion={clip.features.motion_score:.2f} "
                    f"stability={clip.features.camera_stability_score:.2f}"
                )

            if len(ordered) > 5:
                logger.info(f"[ClipSelected] ... and {len(ordered) - 5} more clips")

            # 10. Convert to SelectedSegment
            result = [
                SelectedSegment(
                    source_path=clip.source_path,
                    start=clip.start,
                    end=clip.end,
                    duration=clip.duration,
                    is_must_use=clip.is_must_use
                )
                for clip in ordered
            ]

            # 11. Save to render history
            if project_dir:
                try:
                    history = RenderHistory(project_dir)
                    render_record = RenderHistory.create_render_record(
                        preset_id=preset_id,
                        target_duration=target_duration,
                        selected_clips=ordered
                    )
                    history.add_render(render_record)
                    logger.info(f"[ClipSelection] Saved to render history: {render_record.render_id}")
                except Exception as e:
                    logger.warning(f"[ClipSelection] Failed to save render history: {e}")

            return result

        except Exception as e:
            logger.error(f"[ClipSelection] Strategy-based selection failed: {e}", exc_info=True)
            logger.warning("[ClipSelection] Falling back to legacy selection method")
            try:
                return SegmentSelector.select_segments(
                    source_path, ranges, target_duration, "balanced", seed
                )
            except ValueError as ve:
                logger.warning(f"[ClipSelection] Legacy fallback also failed ({ve}), returning partial result")
                # Return whatever we can from the ranges
                partial = []
                total = 0.0
                good = [r for r in ranges if r.type in ("good", "must_use")]
                for r in good:
                    if total >= target_duration:
                        break
                    take = min(r.duration, target_duration - total)
                    if take > 0.5:
                        partial.append(SelectedSegment(
                            source_path=source_path,
                            start=r.start,
                            end=r.start + take,
                            duration=take,
                            is_must_use=(r.type == "must_use")
                        ))
                        total += take
                if partial:
                    logger.info(f"[ClipSelection] Returning {len(partial)} partial segments ({total:.1f}s)")
                return partial


if __name__ == "__main__":
    # Test segment selector
    test_ranges = [
        Range(start=5.0, end=15.0, type="good"),
        Range(start=20.0, end=35.0, type="must_use"),
        Range(start=55.0, end=70.0, type="good"),
        Range(start=75.0, end=95.0, type="good"),
    ]

    print("Testing SegmentSelector...")

    for level in ["slow", "balanced", "fast"]:
        print(f"\n{level.upper()} dynamic level:")
        segments = SegmentSelector.select_segments(
            source_path="test.mp4",
            ranges=test_ranges,
            target_duration=60.0,
            dynamic_level=level,
            seed=42  # For reproducible results
        )

        total = SegmentSelector.get_total_duration(segments)
        print(f"  Selected {len(segments)} segments, total: {total:.1f}s")
        for seg in segments:
            print(f"    {seg}")

        try:
            SegmentSelector.validate_segments(segments, 60.0)
            print(f"  ✓ Valid")
        except ValueError as e:
            print(f"  ✗ {e}")
