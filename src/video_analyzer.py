"""
Video analyzer using ffprobe to extract metadata
"""

import json
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class VideoMetadata:
    """Video file metadata"""
    path: str
    duration: float  # seconds
    width: int
    height: int
    fps: float
    codec: str
    bitrate: Optional[int] = None  # bits per second

    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio"""
        return self.width / self.height

    @property
    def resolution(self) -> str:
        """Get resolution as string"""
        return f"{self.width}×{self.height}"


class VideoAnalyzer:
    """Analyzes video files using ffprobe"""

    @staticmethod
    def analyze(video_path: str | Path) -> VideoMetadata:
        """
        Analyze video file and extract metadata

        Args:
            video_path: Path to video file

        Returns:
            VideoMetadata object

        Raises:
            FileNotFoundError: If video file doesn't exist
            RuntimeError: If ffprobe fails
        """
        video_path = Path(video_path)

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Run ffprobe to get JSON metadata
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,codec_name,bit_rate:format=duration",
            "-of", "json",
            str(video_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffprobe failed: {e.stderr}")
        except FileNotFoundError:
            raise RuntimeError(
                "ffprobe not found. Please install FFmpeg: "
                "https://ffmpeg.org/download.html"
            )

        # Parse JSON output
        data = json.loads(result.stdout)

        if "streams" not in data or len(data["streams"]) == 0:
            raise RuntimeError(f"No video stream found in {video_path}")

        stream = data["streams"][0]
        format_data = data.get("format", {})

        # Extract metadata
        width = int(stream["width"])
        height = int(stream["height"])
        codec = stream["codec_name"]

        # Parse frame rate (can be "30/1" or "30000/1001")
        fps_str = stream["r_frame_rate"]
        num, denom = map(int, fps_str.split("/"))
        fps = num / denom

        # Duration (in seconds)
        duration = float(format_data.get("duration", 0))

        # Bitrate (optional)
        bitrate = None
        if "bit_rate" in stream:
            bitrate = int(stream["bit_rate"])

        return VideoMetadata(
            path=str(video_path),
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            codec=codec,
            bitrate=bitrate
        )

    @staticmethod
    def check_ffmpeg_available() -> bool:
        """
        Check if ffmpeg and ffprobe are available

        Returns:
            True if both are available, False otherwise
        """
        try:
            subprocess.run(
                ["ffprobe", "-version"],
                capture_output=True,
                check=True
            )
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    @staticmethod
    def get_ffmpeg_version() -> str:
        """
        Get FFmpeg version string

        Returns:
            Version string (e.g., "4.4.2")

        Raises:
            RuntimeError: If ffmpeg is not available
        """
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                check=True
            )
            # First line contains version: "ffmpeg version 4.4.2 ..."
            first_line = result.stdout.split('\n')[0]
            version = first_line.split()[2]
            return version
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("FFmpeg is not available")


if __name__ == "__main__":
    # Test video analyzer
    import sys

    if len(sys.argv) < 2:
        # Check FFmpeg availability
        if VideoAnalyzer.check_ffmpeg_available():
            version = VideoAnalyzer.get_ffmpeg_version()
            print(f"✓ FFmpeg is available (version {version})")
            print("\nUsage: python -m src.video_analyzer <path/to/video.mp4>")
        else:
            print("✗ FFmpeg/ffprobe not found")
            print("\nPlease install FFmpeg:")
            print("  macOS: brew install ffmpeg")
            print("  Ubuntu: sudo apt-get install ffmpeg")
            print("  Windows: Download from https://ffmpeg.org/download.html")
        sys.exit(1)

    try:
        metadata = VideoAnalyzer.analyze(sys.argv[1])
        print(f"✓ Video analyzed successfully")
        print(f"  Path: {metadata.path}")
        print(f"  Duration: {metadata.duration:.2f}s")
        print(f"  Resolution: {metadata.resolution}")
        print(f"  Aspect ratio: {metadata.aspect_ratio:.2f}")
        print(f"  FPS: {metadata.fps:.2f}")
        print(f"  Codec: {metadata.codec}")
        if metadata.bitrate:
            print(f"  Bitrate: {metadata.bitrate / 1_000_000:.2f} Mbps")
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)
