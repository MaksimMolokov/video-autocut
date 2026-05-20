"""
Music sync integration
Bridges music_sync module with segment_selector for music-synchronized video editing
"""

import logging
from typing import List, Optional
from pathlib import Path

from src.segment_selector import SelectedSegment
from src.music_sync import (
    MusicAnalyzer,
    MusicSyncSettings as InternalMusicSyncSettings,
    create_strategy,
    AudioAnalysisCache
)
from src.effects_config import MusicSyncSettings, MusicSyncMode


logger = logging.getLogger(__name__)


class MusicSyncIntegration:
    """Integrates music synchronization with video segment selection"""

    def __init__(self, cache_enabled: bool = True):
        """
        Initialize music sync integration

        Args:
            cache_enabled: Whether to enable audio analysis caching
        """
        self.analyzer = MusicAnalyzer(cache_enabled=cache_enabled)
        self.cache_enabled = cache_enabled

    def select_segments_with_music_sync(
        self,
        music_path: str,
        sources: List[dict],
        target_duration: float,
        dynamic_level: str,
        music_settings: MusicSyncSettings,
        seed: int = None
    ) -> List[SelectedSegment]:
        """
        Select video segments synchronized to music

        Args:
            music_path: Path to music file
            sources: List of video source dicts with 'path', 'ranges', 'duration'
            target_duration: Target video duration
            dynamic_level: slow/balanced/fast
            music_settings: Music sync configuration
            seed: Random seed for reproducibility

        Returns:
            List of SelectedSegment objects synchronized to music

        Raises:
            ValueError: If music sync fails or insufficient footage
        """
        if not music_settings.enabled or music_settings.mode == MusicSyncMode.NONE:
            logger.info("[MusicSync] Music sync disabled, skipping")
            return []

        logger.info(f"[MusicSync] Starting music-synchronized segment selection")
        logger.info(f"  Mode: {music_settings.mode.value}")
        logger.info(f"  Music: {Path(music_path).name}")
        logger.info(f"  Target duration: {target_duration:.1f}s")

        try:
            # Step 1: Analyze music
            logger.info("[MusicSync] Step 1: Analyzing music...")
            audio_analysis = self.analyzer.analyze(music_path)

            # Step 2: Convert settings and create strategy
            logger.info(f"[MusicSync] Step 2: Creating {music_settings.mode.value} strategy...")
            internal_settings = self._convert_settings(music_settings)
            strategy = create_strategy(internal_settings)

            # Step 3: Prepare available segments from all sources
            logger.info("[MusicSync] Step 3: Preparing available video segments...")
            available_segments = self._prepare_segments_from_sources(sources, dynamic_level)

            if not available_segments:
                raise ValueError("No available video segments for music sync")

            logger.info(f"  Available segments: {len(available_segments)}")

            # Step 4: Build cut plan based on music
            logger.info("[MusicSync] Step 4: Building cut plan...")
            cut_plan = strategy.build_cut_plan(
                audio_analysis=audio_analysis,
                available_segments=available_segments,
                target_duration=target_duration,
                dynamic_level=dynamic_level
            )

            logger.info(f"[MusicSync] Cut plan created:")
            logger.info(f"  Total cuts: {len(cut_plan.cut_points)}")
            logger.info(f"  Total duration: {sum(cut_plan.segment_durations):.1f}s")

            # Step 5: Map cut plan to selected segments
            logger.info("[MusicSync] Step 5: Mapping cut plan to video segments...")
            selected_segments = self._map_cut_plan_to_segments(
                cut_plan=cut_plan,
                available_segments=available_segments
            )

            logger.info(f"[MusicSync] ✓ Successfully created {len(selected_segments)} synchronized segments")

            return selected_segments

        except Exception as e:
            logger.error(f"[MusicSync] Failed: {e}")

            # Try fallback mode if configured
            if music_settings.fallback_mode and music_settings.fallback_mode != music_settings.mode.value:
                logger.warning(f"[MusicSync] Attempting fallback to {music_settings.fallback_mode}...")
                try:
                    fallback_settings = MusicSyncSettings(
                        enabled=True,
                        mode=MusicSyncMode(music_settings.fallback_mode)
                    )
                    return self.select_segments_with_music_sync(
                        music_path=music_path,
                        sources=sources,
                        target_duration=target_duration,
                        dynamic_level=dynamic_level,
                        music_settings=fallback_settings,
                        seed=seed
                    )
                except Exception as fallback_error:
                    logger.error(f"[MusicSync] Fallback also failed: {fallback_error}")

            raise

    def _convert_settings(self, settings: MusicSyncSettings) -> InternalMusicSyncSettings:
        """
        Convert GUI MusicSyncSettings to internal module settings

        Args:
            settings: GUI settings

        Returns:
            Internal music sync settings
        """
        return InternalMusicSyncSettings(
            mode=settings.mode.value,
            fallback_mode=settings.fallback_mode,
            beat_source=settings.beat_source,
            cut_every_n_beats=settings.cut_every_n_beats,
            prefer_strong_beats=settings.prefer_strong_beats,
            allow_offbeat_cuts=settings.allow_offbeat_cuts,
            beat_tolerance=settings.beat_tolerance,
            min_clip_duration=settings.min_clip_duration,
            max_clip_duration=settings.max_clip_duration,
            low_energy_clip_duration=settings.low_energy_clip_duration,
            medium_energy_clip_duration=settings.medium_energy_clip_duration,
            high_energy_clip_duration=settings.high_energy_clip_duration,
            use_beats_inside_sections=settings.use_beats_inside_sections,
            climax_priority=settings.climax_priority,
            energy_window_size=settings.energy_window_size
        )

    def _prepare_segments_from_sources(
        self,
        sources: List[dict],
        dynamic_level: str
    ) -> List[SelectedSegment]:
        """
        Prepare pool of available segments from all sources

        Args:
            sources: List of video source dicts
            dynamic_level: slow/balanced/fast

        Returns:
            List of all available SelectedSegment objects
        """
        all_segments = []

        for source in sources:
            source_path = source['path']
            ranges = source['ranges']

            # Get all good and must_use ranges
            usable_ranges = [r for r in ranges if r.type in ("good", "must_use")]

            for range_obj in usable_ranges:
                # Create a segment for each usable range
                # The music sync strategy will pick and trim these as needed
                segment = SelectedSegment(
                    source_path=source_path,
                    start=range_obj.start,
                    end=range_obj.end,
                    duration=range_obj.duration,
                    is_must_use=(range_obj.type == "must_use")
                )
                all_segments.append(segment)

        return all_segments

    def _map_cut_plan_to_segments(
        self,
        cut_plan,
        available_segments: List[SelectedSegment]
    ) -> List[SelectedSegment]:
        """
        Map cut plan to actual video segments

        Args:
            cut_plan: CutPlan from music sync strategy
            available_segments: Pool of available segments

        Returns:
            List of SelectedSegment objects for rendering
        """
        selected = []

        for cut_point, duration in zip(cut_plan.cut_points, cut_plan.segment_durations):
            # Get the source segment indicated by the cut plan
            source_idx = cut_point.source_segment_idx % len(available_segments)
            source_segment = available_segments[source_idx]

            # Trim the source segment to the required duration
            # Try to use a portion from the middle for variety
            max_start = source_segment.end - duration
            if max_start < source_segment.start:
                # Segment too short, use what we have
                trimmed_segment = source_segment
            else:
                # Use a portion from somewhere in the middle
                import random
                segment_start = random.uniform(source_segment.start, max_start)
                segment_end = segment_start + duration

                trimmed_segment = SelectedSegment(
                    source_path=source_segment.source_path,
                    start=segment_start,
                    end=segment_end,
                    duration=duration,
                    is_must_use=source_segment.is_must_use
                )

            selected.append(trimmed_segment)

        return selected


def integrate_music_sync_with_selection(
    music_path: Optional[str],
    sources: List[dict],
    target_duration: float,
    dynamic_level: str,
    music_settings: MusicSyncSettings,
    seed: int = None
) -> List[SelectedSegment]:
    """
    Main integration function - use music sync if enabled, otherwise normal selection

    Args:
        music_path: Path to music file (optional)
        sources: Video sources
        target_duration: Target duration
        dynamic_level: Dynamic level setting
        music_settings: Music sync settings
        seed: Random seed

    Returns:
        List of SelectedSegment objects
    """
    # Check if music sync should be used
    if (music_path and
        music_settings.enabled and
        music_settings.mode != MusicSyncMode.NONE and
        Path(music_path).exists()):

        try:
            integration = MusicSyncIntegration(cache_enabled=True)
            return integration.select_segments_with_music_sync(
                music_path=music_path,
                sources=sources,
                target_duration=target_duration,
                dynamic_level=dynamic_level,
                music_settings=music_settings,
                seed=seed
            )
        except Exception as e:
            logger.error(f"Music sync failed, falling back to normal selection: {e}")

    # Fallback to normal segment selection
    from src.segment_selector import SegmentSelector
    logger.info("Using standard segment selection (no music sync)")

    return SegmentSelector.select_segments_multi_source(
        sources=sources,
        target_duration=target_duration,
        dynamic_level=dynamic_level,
        alternate_sources=len(sources) > 1,
        seed=seed
    )
