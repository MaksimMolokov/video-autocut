"""
Music processor for background audio processing
"""

import subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class MusicMetadata:
    """Music file metadata"""
    path: str
    duration: float  # seconds
    codec: str
    bitrate: Optional[int] = None  # bits per second
    sample_rate: Optional[int] = None  # Hz


class MusicProcessor:
    """Processes background music for video"""

    @staticmethod
    def analyze(music_path: str | Path) -> MusicMetadata:
        """
        Analyze music file and extract metadata

        Args:
            music_path: Path to music file

        Returns:
            MusicMetadata object

        Raises:
            FileNotFoundError: If music file doesn't exist
            RuntimeError: If ffprobe fails
        """
        music_path = Path(music_path)

        if not music_path.exists():
            raise FileNotFoundError(f"Music file not found: {music_path}")

        # Run ffprobe to get audio stream info
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,bit_rate,sample_rate:format=duration",
            "-of", "default=noprint_wrappers=1",
            str(music_path)
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

        # Parse output (key=value format)
        data = {}
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                data[key] = value

        # Extract metadata
        codec = data.get('codec_name', 'unknown')
        duration = float(data.get('duration', 0))

        bitrate = None
        if 'bit_rate' in data:
            bitrate = int(data['bit_rate'])

        sample_rate = None
        if 'sample_rate' in data:
            sample_rate = int(data['sample_rate'])

        return MusicMetadata(
            path=str(music_path),
            duration=duration,
            codec=codec,
            bitrate=bitrate,
            sample_rate=sample_rate
        )

    @staticmethod
    def trim_and_fade(
        music_path: str,
        output_path: str,
        duration: float,
        fade_in: float = 3.0,
        fade_out: float = 3.0
    ):
        """
        Trim music to specified duration and add fade in/out

        Args:
            music_path: Input music file path
            output_path: Output music file path
            duration: Target duration in seconds
            fade_in: Fade in duration in seconds
            fade_out: Fade out duration in seconds

        Raises:
            RuntimeError: If processing fails
        """
        # Build audio filter
        fade_out_start = max(0, duration - fade_out)
        audio_filter = (
            f"atrim=0:{duration},"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start}:d={fade_out}"
        )

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", music_path,
            "-af", audio_filter,
            "-c:a", "aac",
            "-b:a", "128k",
            output_path
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to process music: {e.stderr}")

    @staticmethod
    def loop_to_duration(
        music_path: str,
        output_path: str,
        target_duration: float,
        fade_in: float = 3.0,
        fade_out: float = 3.0
    ):
        """
        Loop music to reach target duration with fade in/out

        Useful when music track is shorter than video

        Args:
            music_path: Input music file path
            output_path: Output music file path
            target_duration: Target duration in seconds
            fade_in: Fade in duration in seconds
            fade_out: Fade out duration in seconds

        Raises:
            RuntimeError: If processing fails
        """
        # Get music duration
        metadata = MusicProcessor.analyze(music_path)

        if metadata.duration >= target_duration:
            # Music is long enough, just trim
            MusicProcessor.trim_and_fade(
                music_path, output_path, target_duration, fade_in, fade_out
            )
            return

        # Calculate how many loops we need
        num_loops = int(target_duration / metadata.duration) + 1

        # Build filter to loop
        fade_out_start = max(0, target_duration - fade_out)
        audio_filter = (
            f"aloop=loop={num_loops}:size={int(metadata.duration * metadata.sample_rate or 44100)},"
            f"atrim=0:{target_duration},"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start}:d={fade_out}"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i", music_path,
            "-af", audio_filter,
            "-c:a", "aac",
            "-b:a", "128k",
            output_path
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to loop music: {e.stderr}")

    @staticmethod
    def validate_music_file(music_path: str) -> bool:
        """
        Validate that music file is usable

        Args:
            music_path: Path to music file

        Returns:
            True if valid

        Raises:
            ValueError: If file is invalid
        """
        try:
            metadata = MusicProcessor.analyze(music_path)
        except (FileNotFoundError, RuntimeError) as e:
            raise ValueError(f"Invalid music file: {e}")

        if metadata.duration <= 0:
            raise ValueError(f"Music file has no duration: {music_path}")

        if metadata.codec == "unknown":
            raise ValueError(f"Unknown audio codec in {music_path}")

        return True


if __name__ == "__main__":
    # Test music processor
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.music_processor <path/to/music.mp3>")
        print("\nThis will analyze the music file and show its metadata.")
        sys.exit(1)

    try:
        metadata = MusicProcessor.analyze(sys.argv[1])
        print(f"✓ Music analyzed successfully")
        print(f"  Path: {metadata.path}")
        print(f"  Duration: {metadata.duration:.2f}s")
        print(f"  Codec: {metadata.codec}")
        if metadata.bitrate:
            print(f"  Bitrate: {metadata.bitrate / 1000:.0f} kbps")
        if metadata.sample_rate:
            print(f"  Sample rate: {metadata.sample_rate} Hz")

        # Validate
        MusicProcessor.validate_music_file(sys.argv[1])
        print(f"\n✓ Music file is valid")
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)
