"""
CLI interface for Auto Video Cutter
"""

import sys
import argparse
from pathlib import Path
from typing import Optional

from src.config_loader import ConfigLoader
from src.video_analyzer import VideoAnalyzer
from src.range_manager import RangeManager
from src.segment_selector import SegmentSelector
from src.ffmpeg_renderer import FFmpegRenderer
from src.music_processor import MusicProcessor


class ProgressPrinter:
    """Simple progress printer for CLI"""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def __call__(self, message: str):
        if self.verbose:
            print(f"  {message}")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Auto Video Cutter - Semi-automatic video assembly",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process with default settings
  python -m src.cli project.yaml output.mp4

  # Use a preset
  python -m src.cli project.yaml output.mp4 --preset fast_dynamic

  # Dry run to see what would be done
  python -m src.cli project.yaml output.mp4 --dry-run

  # Set random seed for reproducibility
  python -m src.cli project.yaml output.mp4 --seed 42

Presets:
  slow_cinematic  : Slow dynamic + horizontal format
  balanced_promo  : Balanced dynamic + square format
  fast_dynamic    : Fast dynamic + vertical format
        """
    )

    parser.add_argument(
        "config",
        help="Path to project.yaml configuration file"
    )
    parser.add_argument(
        "output",
        help="Output video file path (e.g., output.mp4)"
    )
    parser.add_argument(
        "--preset",
        choices=["slow_cinematic", "balanced_promo", "fast_dynamic"],
        help="Use a predefined preset (overrides config)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducible segment selection"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually rendering"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output"
    )

    args = parser.parse_args()

    # Setup progress printer
    progress = ProgressPrinter(verbose=not args.quiet)

    try:
        # Step 1: Load configuration
        print("Loading configuration...")
        config = ConfigLoader.load(args.config)
        progress(f"Project: {config.name}")
        progress(f"Sources: {len(config.sources)}")
        progress(f"Target duration: {config.output.target_duration}s")

        # Apply preset if specified
        if args.preset:
            preset_config = ConfigLoader.get_preset(args.preset)
            config.output.format = preset_config["format"]
            config.output.dynamic_level = preset_config["dynamic_level"]
            progress(f"Applied preset: {args.preset}")

        progress(f"Format: {config.output.format} ({config.output.resolution[0]}×{config.output.resolution[1]})")
        progress(f"Dynamic level: {config.output.dynamic_level}")

        # Step 2: Analyze sources
        print("\nAnalyzing video sources...")
        for i, source in enumerate(config.sources):
            progress(f"Source {i+1}: {source.path}")

            # Validate file exists
            if not Path(source.path).exists():
                print(f"✗ Error: Source file not found: {source.path}")
                sys.exit(1)

            # Get video metadata
            metadata = VideoAnalyzer.analyze(source.path)
            progress(f"  Duration: {metadata.duration:.1f}s")
            progress(f"  Resolution: {metadata.resolution}")
            progress(f"  FPS: {metadata.fps:.2f}")

            # Validate ranges
            RangeManager.validate_ranges(source.ranges, metadata.duration)

            # Show range stats
            stats = RangeManager.get_stats(source.ranges, metadata.duration)
            progress(f"  Good footage: {stats.total_good_duration:.1f}s ({stats.num_good} ranges)")
            progress(f"  Must-use footage: {stats.total_must_use_duration:.1f}s ({stats.num_must_use} ranges)")
            progress(f"  Available: {stats.available_duration:.1f}s total")

            if stats.available_duration < config.output.target_duration:
                print(f"✗ Warning: Available footage ({stats.available_duration:.1f}s) "
                      f"is less than target ({config.output.target_duration}s)")

        # Step 3: Select segments
        print("\nSelecting video segments...")
        all_segments = []
        for source in config.sources:
            segments = SegmentSelector.select_segments(
                source_path=source.path,
                ranges=source.ranges,
                target_duration=config.output.target_duration,
                dynamic_level=config.output.dynamic_level,
                seed=args.seed
            )
            all_segments.extend(segments)

        total_duration = SegmentSelector.get_total_duration(all_segments)
        progress(f"Selected {len(all_segments)} segments, total: {total_duration:.1f}s")

        # Show segment details
        must_use_count = sum(1 for s in all_segments if s.is_must_use)
        good_count = len(all_segments) - must_use_count
        progress(f"  Must-use: {must_use_count} segments")
        progress(f"  Good: {good_count} segments")

        # Validate
        try:
            SegmentSelector.validate_segments(all_segments, config.output.target_duration)
            progress("✓ Segments validated")
        except ValueError as e:
            print(f"✗ Warning: {e}")

        # Step 4: Validate music (if provided)
        music_path = None
        if config.music:
            print("\nValidating music...")
            music_path = config.music.path

            if not Path(music_path).exists():
                print(f"✗ Error: Music file not found: {music_path}")
                sys.exit(1)

            music_metadata = MusicProcessor.analyze(music_path)
            progress(f"Music: {music_path}")
            progress(f"  Duration: {music_metadata.duration:.1f}s")
            progress(f"  Codec: {music_metadata.codec}")

            MusicProcessor.validate_music_file(music_path)
            progress("✓ Music validated")

        # Step 5: Dry run or render
        if args.dry_run:
            print("\n=== DRY RUN ===")
            print("Would render the following segments:")
            for i, seg in enumerate(all_segments):
                flag = "🔵 MUST" if seg.is_must_use else "🟢 GOOD"
                print(f"  {i+1:2d}. {flag} [{seg.start:6.1f} - {seg.end:6.1f}] ({seg.duration:5.1f}s) from {Path(seg.source_path).name}")
            print(f"\nTotal output duration: {total_duration:.1f}s")
            print(f"Output format: {config.output.format} ({config.output.resolution[0]}×{config.output.resolution[1]})")
            if music_path:
                print(f"Background music: {Path(music_path).name}")
            print(f"Output file: {args.output}")
            print("\nRun without --dry-run to actually render the video.")
            return

        # Step 6: Render
        print("\nRendering video...")
        progress("This may take several minutes depending on video length...")

        FFmpegRenderer.render(
            segments=all_segments,
            output_config=config.output,
            output_path=args.output,
            music_path=music_path,
            music_fade_in=config.music.fade_in if config.music else 3.0,
            music_fade_out=config.music.fade_out if config.music else 3.0,
            progress_callback=progress
        )

        print(f"\n✓ Video rendered successfully: {args.output}")
        print(f"  Duration: {total_duration:.1f}s")
        print(f"  Resolution: {config.output.resolution[0]}×{config.output.resolution[1]}")
        print(f"  Segments: {len(all_segments)}")

    except KeyboardInterrupt:
        print("\n\n✗ Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        if not args.quiet:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
