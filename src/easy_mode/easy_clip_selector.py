"""
Easy Mode Clip Selector

Fast random clip selection from multiple video sources.
No feature extraction, no quality analysis — just ffprobe + random timestamps.
Each run produces a different result unless seed is fixed.
"""

import random
import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class EasyClipSelector:
    """
    Fast random clip selection for Easy mode.

    Skips all visual analysis. Uses ffprobe to get video durations,
    then randomly samples start times within each video.
    """

    @staticmethod
    def get_video_duration(video_path: str) -> Optional[float]:
        """Get video duration via ffprobe (fast, no decoding)."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0",
                    str(video_path)
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception as e:
            logger.debug(f"ffprobe failed for {video_path}: {e}")
        return None

    @staticmethod
    def select_random_clips(
        video_paths: List[str],
        target_duration: float,
        min_clip_duration: float = 2.0,
        max_clip_duration: float = 5.0,
        seed: Optional[int] = None,
        avoid_repeating_same_video: bool = True,
        shuffle_clips: bool = True,
        allow_reuse: bool = True
    ) -> list:
        """
        Randomly select clips from multiple video sources.

        Args:
            video_paths: List of source video file paths
            target_duration: Total desired output duration in seconds
            min_clip_duration: Minimum duration for a single clip
            max_clip_duration: Maximum duration for a single clip
            seed: Optional random seed for reproducible results (None = random each run)
            avoid_repeating_same_video: Weight selection to spread across sources
            shuffle_clips: Shuffle final clip order (True = non-chronological)
            allow_reuse: Allow same video to be used more than once (needed when material is short)

        Returns:
            List of SelectedSegment objects
        """
        from src.segment_selector import SelectedSegment

        rng = random.Random(seed)  # seed=None → system entropy → different each run

        logger.info(
            f"[Easy] Selecting clips: target={target_duration:.1f}s, "
            f"clip={min_clip_duration:.1f}-{max_clip_duration:.1f}s, "
            f"seed={seed}, sources={len(video_paths)}"
        )

        # Discover usable videos via ffprobe
        usable: List[Tuple[str, float]] = []
        for vp in video_paths:
            dur = EasyClipSelector.get_video_duration(vp)
            if dur is not None and dur >= min_clip_duration * 0.5:
                usable.append((vp, dur))
                logger.info(f"[Easy] {Path(vp).name}: {dur:.1f}s — OK")
            else:
                logger.warning(
                    f"[Easy] Skipping {Path(vp).name}: "
                    f"duration={dur:.1f}s" if dur is not None else
                    f"[Easy] Skipping {Path(vp).name}: unreadable"
                )

        if not usable:
            logger.error("[Easy] No usable videos found")
            return []

        # Per-video pick counter for anti-repeat weighting
        pick_counts: dict = {vp: 0 for vp, _ in usable}

        segments = []
        total_duration = 0.0
        # Safety cap: max 5x more iterations than expected clips
        expected_clips = max(1, int(target_duration / max((min_clip_duration + max_clip_duration) / 2, 0.1)))
        max_iterations = expected_clips * 5 + 20

        for _ in range(max_iterations):
            remaining = target_duration - total_duration
            if remaining <= 0:
                break

            # Clip duration: uniform random in [min, max], capped at remaining
            clip_dur = rng.uniform(min_clip_duration, max_clip_duration)
            clip_dur = min(clip_dur, remaining)
            if clip_dur < min_clip_duration * 0.5:
                # Remaining time too small for a meaningful clip
                break

            # Choose video source with optional anti-repeat weighting
            if avoid_repeating_same_video and len(usable) > 1:
                # Lower weight for recently picked videos
                weights = [1.0 / (1.0 + pick_counts[vp] * 0.6) for vp, _ in usable]
                chosen_path, chosen_dur = rng.choices(usable, weights=weights, k=1)[0]
            else:
                chosen_path, chosen_dur = rng.choice(usable)

            pick_counts[chosen_path] += 1

            # Adjust clip duration if video is shorter than desired
            actual_clip_dur = min(clip_dur, chosen_dur)
            max_start = max(0.0, chosen_dur - actual_clip_dur)
            start = rng.uniform(0.0, max_start)
            end = start + actual_clip_dur

            segments.append(SelectedSegment(
                source_path=chosen_path,
                start=start,
                end=end,
                duration=actual_clip_dur,
                is_must_use=False
            ))
            total_duration += actual_clip_dur

            logger.debug(
                f"[Easy] {Path(chosen_path).name} [{start:.1f}–{end:.1f}s] "
                f"({actual_clip_dur:.1f}s) total={total_duration:.1f}s"
            )

        if shuffle_clips and len(segments) > 1:
            rng.shuffle(segments)

        logger.info(
            f"[Easy] Done: {len(segments)} clips, "
            f"total={total_duration:.1f}s / target={target_duration:.1f}s"
        )

        # Log full clip list for debugging
        for i, seg in enumerate(segments, 1):
            logger.info(
                f"[Easy] Clip {i}: {Path(seg.source_path).name} "
                f"[{seg.start:.1f}–{seg.end:.1f}s] ({seg.duration:.1f}s)"
            )

        return segments
