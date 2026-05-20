"""
Range manager for handling good/bad/must_use video ranges
"""

from typing import List, Tuple
from dataclasses import dataclass
from src.config_loader import Range


@dataclass
class RangeStats:
    """Statistics about ranges in a source"""
    total_good_duration: float
    total_must_use_duration: float
    total_bad_duration: float
    num_good: int
    num_must_use: int
    num_bad: int
    source_duration: float

    @property
    def available_duration(self) -> float:
        """Total duration available for selection (good + must_use)"""
        return self.total_good_duration + self.total_must_use_duration

    @property
    def good_ratio(self) -> float:
        """Ratio of good footage to total duration"""
        if self.source_duration == 0:
            return 0
        return self.total_good_duration / self.source_duration


class RangeManager:
    """Manages video ranges and provides utilities for range operations"""

    @staticmethod
    def validate_ranges(ranges: List[Range], video_duration: float) -> bool:
        """
        Validate that ranges don't overlap and are within video duration

        Args:
            ranges: List of Range objects
            video_duration: Total duration of the video

        Returns:
            True if valid

        Raises:
            ValueError: If ranges are invalid
        """
        # Check each range is within video duration
        for r in ranges:
            if r.start < 0:
                raise ValueError(f"Range start cannot be negative: {r.start}")
            if r.end > video_duration:
                raise ValueError(
                    f"Range end ({r.end}s) exceeds video duration ({video_duration}s)"
                )

        # Check for overlaps
        sorted_ranges = sorted(ranges, key=lambda r: r.start)
        for i in range(len(sorted_ranges) - 1):
            current = sorted_ranges[i]
            next_range = sorted_ranges[i + 1]
            if current.end > next_range.start:
                raise ValueError(
                    f"Ranges overlap: [{current.start}-{current.end}] "
                    f"and [{next_range.start}-{next_range.end}]"
                )

        return True

    @staticmethod
    def get_stats(ranges: List[Range], video_duration: float) -> RangeStats:
        """
        Calculate statistics about ranges

        Args:
            ranges: List of Range objects
            video_duration: Total duration of the video

        Returns:
            RangeStats object
        """
        good_ranges = [r for r in ranges if r.type == "good"]
        must_use_ranges = [r for r in ranges if r.type == "must_use"]
        bad_ranges = [r for r in ranges if r.type == "bad"]

        total_good = sum(r.duration for r in good_ranges)
        total_must_use = sum(r.duration for r in must_use_ranges)
        total_bad = sum(r.duration for r in bad_ranges)

        return RangeStats(
            total_good_duration=total_good,
            total_must_use_duration=total_must_use,
            total_bad_duration=total_bad,
            num_good=len(good_ranges),
            num_must_use=len(must_use_ranges),
            num_bad=len(bad_ranges),
            source_duration=video_duration
        )

    @staticmethod
    def filter_by_type(ranges: List[Range], range_type: str) -> List[Range]:
        """
        Filter ranges by type

        Args:
            ranges: List of Range objects
            range_type: "good", "bad", or "must_use"

        Returns:
            Filtered list of ranges
        """
        return [r for r in ranges if r.type == range_type]

    @staticmethod
    def merge_adjacent_ranges(ranges: List[Range], max_gap: float = 0.5) -> List[Range]:
        """
        Merge adjacent ranges of the same type if gap between them is small

        Args:
            ranges: List of Range objects
            max_gap: Maximum gap (in seconds) to consider ranges adjacent

        Returns:
            List of merged ranges
        """
        if not ranges:
            return []

        # Group by type
        by_type = {}
        for r in ranges:
            if r.type not in by_type:
                by_type[r.type] = []
            by_type[r.type].append(r)

        # Merge within each type
        merged = []
        for range_type, type_ranges in by_type.items():
            sorted_ranges = sorted(type_ranges, key=lambda r: r.start)

            current = sorted_ranges[0]
            for next_range in sorted_ranges[1:]:
                gap = next_range.start - current.end
                if gap <= max_gap:
                    # Merge: extend current to cover next
                    current = Range(
                        start=current.start,
                        end=next_range.end,
                        type=range_type
                    )
                else:
                    # Gap too large, save current and start new
                    merged.append(current)
                    current = next_range

            # Don't forget the last one
            merged.append(current)

        return sorted(merged, key=lambda r: r.start)

    @staticmethod
    def split_range(range_obj: Range, split_points: List[float]) -> List[Range]:
        """
        Split a range into multiple ranges at specified points

        Args:
            range_obj: Range to split
            split_points: List of timestamps where to split (must be within range)

        Returns:
            List of split ranges

        Raises:
            ValueError: If split points are invalid
        """
        # Validate split points
        for point in split_points:
            if not (range_obj.start < point < range_obj.end):
                raise ValueError(
                    f"Split point {point} is outside range "
                    f"[{range_obj.start}-{range_obj.end}]"
                )

        # Sort split points
        points = sorted(split_points)

        # Create split ranges
        result = []
        current_start = range_obj.start

        for point in points:
            result.append(Range(
                start=current_start,
                end=point,
                type=range_obj.type
            ))
            current_start = point

        # Add final range
        result.append(Range(
            start=current_start,
            end=range_obj.end,
            type=range_obj.type
        ))

        return result

    @staticmethod
    def get_usable_ranges(ranges: List[Range]) -> List[Range]:
        """
        Get all usable ranges (good + must_use), sorted by start time

        Args:
            ranges: List of Range objects

        Returns:
            List of usable ranges, sorted by start time
        """
        usable = [r for r in ranges if r.type in ("good", "must_use")]
        return sorted(usable, key=lambda r: r.start)


if __name__ == "__main__":
    # Test range manager
    test_ranges = [
        Range(start=5.0, end=15.0, type="good"),
        Range(start=20.0, end=35.0, type="must_use"),
        Range(start=40.0, end=50.0, type="bad"),
        Range(start=55.0, end=70.0, type="good"),
    ]

    video_duration = 100.0

    print("Testing RangeManager...")

    # Validate
    try:
        RangeManager.validate_ranges(test_ranges, video_duration)
        print("✓ Ranges are valid")
    except ValueError as e:
        print(f"✗ Validation failed: {e}")

    # Stats
    stats = RangeManager.get_stats(test_ranges, video_duration)
    print(f"\n✓ Range statistics:")
    print(f"  Good ranges: {stats.num_good} ({stats.total_good_duration}s)")
    print(f"  Must-use ranges: {stats.num_must_use} ({stats.total_must_use_duration}s)")
    print(f"  Bad ranges: {stats.num_bad} ({stats.total_bad_duration}s)")
    print(f"  Available duration: {stats.available_duration}s")
    print(f"  Good ratio: {stats.good_ratio:.1%}")

    # Filter
    good_only = RangeManager.filter_by_type(test_ranges, "good")
    print(f"\n✓ Good ranges: {len(good_only)}")

    # Usable
    usable = RangeManager.get_usable_ranges(test_ranges)
    print(f"✓ Usable ranges: {len(usable)}")

    # Split
    split = RangeManager.split_range(test_ranges[0], [8.0, 12.0])
    print(f"\n✓ Split range [5-15] at [8, 12]:")
    for r in split:
        print(f"  [{r.start}-{r.end}]")
