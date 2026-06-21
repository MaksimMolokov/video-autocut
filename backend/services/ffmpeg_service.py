"""
FFmpegService — safe FFmpeg subprocess wrapper (TZ section 4, 9).

NEVER builds commands via string concatenation.
ALL paths and parameters passed as list args to avoid injection.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class FFmpegError(Exception):
    pass


class FFmpegService:
    """Safe FFmpeg wrapper: all calls via list args, never shell=True."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe") -> None:
        self.ffmpeg = ffmpeg_bin
        self.ffprobe = ffprobe_bin

    # ── Probe ──────────────────────────────────────────────────────────────────

    def probe(self, input_path: str) -> Dict:
        """Return {duration_s, fps, width, height, codec, has_audio}."""
        import json
        cmd = [
            self.ffprobe, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            input_path,
        ]
        result = self._run(cmd, capture_output=True)
        data = json.loads(result.stdout)
        video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

        fps = 0.0
        fps_str = video.get("r_frame_rate", "0/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) else 0.0

        return {
            "duration_s": float(data.get("format", {}).get("duration", 0)),
            "fps": round(fps, 3),
            "width": int(video.get("width", 0)),
            "height": int(video.get("height", 0)),
            "codec": video.get("codec_name", "unknown"),
            "has_audio": audio is not None,
            "file_size": int(data.get("format", {}).get("size", 0)),
        }

    def get_rotation(self, input_path: str) -> int:
        """Return video rotation in degrees (0, 90, 180, 270)."""
        import json
        cmd = [
            self.ffprobe, "-v", "quiet",
            "-select_streams", "v:0",
            "-print_format", "json",
            "-show_entries", "stream_tags=rotate:stream_side_data=rotation",
            input_path,
        ]
        try:
            result = self._run(cmd, capture_output=True)
            data = json.loads(result.stdout)
            streams = data.get("streams", [{}])
            tags = streams[0].get("tags", {}) if streams else {}
            side_data = streams[0].get("side_data_list", [{}]) if streams else [{}]
            rot = tags.get("rotate") or side_data[0].get("rotation", "0") if side_data else "0"
            return int(str(rot).lstrip("-"))
        except Exception:
            return 0

    # ── Extract segment ────────────────────────────────────────────────────────

    def extract_segment(
        self,
        input_path: str,
        output_path: str,
        start_s: float,
        duration_s: float,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        crop_strategy: str = "center",
        saliency_center: Optional[Tuple[float, float]] = None,
    ) -> None:
        """Extract and scale/crop a segment. Output is normalized h264/yuv420p."""
        vf = self._build_vf(width, height, crop_strategy, saliency_center)

        cmd = [
            self.ffmpeg, "-y",
            "-ss", str(start_s),
            "-i", input_path,
            "-t", str(duration_s),
            "-vf", vf,
            "-r", str(fps),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]
        self._run(cmd)

    # ── Concatenate ────────────────────────────────────────────────────────────

    def concat_segments(
        self,
        segment_paths: List[str],
        output_path: str,
        transition_type: str = "cut",
        transition_dur: float = 0.3,
    ) -> None:
        """Concatenate pre-scaled segments. Uses concat demuxer (fast) or xfade."""
        if transition_type == "cut" or len(segment_paths) < 2:
            self._concat_demuxer(segment_paths, output_path)
        else:
            self._concat_xfade(segment_paths, output_path, transition_type, transition_dur)

    def _concat_demuxer(self, paths: List[str], output_path: str) -> None:
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            for p in paths:
                f.write(f"file '{p}'\n")
            list_path = f.name
        try:
            cmd = [
                self.ffmpeg, "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                output_path,
            ]
            self._run(cmd)
        finally:
            os.unlink(list_path)

    def _concat_xfade(self, paths: List[str], output_path: str,
                      transition: str, dur: float) -> None:
        if len(paths) == 1:
            import shutil
            shutil.copy(paths[0], output_path)
            return

        # Build xfade filter chain
        inputs = []
        for p in paths:
            inputs += ["-i", p]

        # Compute offsets: need duration of each segment
        offsets = []
        accumulated = 0.0
        for p in paths[:-1]:
            info = self.probe(p)
            seg_dur = info["duration_s"]
            accumulated += seg_dur - dur
            offsets.append(max(0.0, accumulated))

        filter_parts = []
        prev = "[0:v]"
        for i, offset in enumerate(offsets):
            out = f"[v{i+1}]" if i < len(offsets) - 1 else "[vout]"
            xf_transition = _XFADE_MAP.get(transition, "fade")
            filter_parts.append(
                f"{prev}[{i+1}:v]xfade=transition={xf_transition}:"
                f"duration={dur}:offset={offset:.3f}{out}"
            )
            prev = out

        cmd = inputs + [
            self.ffmpeg, "-y",
        ] + inputs + [
            "-filter_complex", ";".join(filter_parts),
            "-map", "[vout]",
            "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            output_path,
        ]
        # Rebuild properly
        cmd = [self.ffmpeg, "-y"] + inputs + [
            "-filter_complex", ";".join(filter_parts),
            "-map", "[vout]",
            "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            output_path,
        ]
        self._run(cmd)

    # ── Add music ──────────────────────────────────────────────────────────────

    def add_music(
        self,
        video_path: str,
        music_path: str,
        output_path: str,
        music_start_s: float = 0.0,
        music_end_s: Optional[float] = None,
        fade_in_s: float = 1.0,
        fade_out_s: float = 2.0,
        music_volume: float = 1.0,
    ) -> None:
        """Mix music into video with fade in/out."""
        video_info = self.probe(video_path)
        video_dur = video_info["duration_s"]

        music_dur = (music_end_s - music_start_s) if music_end_s else video_dur
        fade_out_start = max(0.0, music_dur - fade_out_s)

        audio_filter = (
            f"atrim=start={music_start_s}:duration={music_dur},"
            f"afade=t=in:st=0:d={fade_in_s},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_s},"
            f"volume={music_volume}"
        )

        cmd = [
            self.ffmpeg, "-y",
            "-i", video_path,
            "-i", music_path,
            "-filter_complex", f"[1:a]{audio_filter}[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]
        self._run(cmd)

    # ── Watermark ─────────────────────────────────────────────────────────────

    def add_watermark(
        self,
        input_path: str,
        output_path: str,
        text: str,
        position: str = "bottom_right",
        opacity: float = 0.7,
    ) -> None:
        x, y = _WATERMARK_POSITIONS.get(position, ("w-tw-20", "h-th-20"))
        drawtext = (
            f"drawtext=text='{text}':"
            f"fontcolor=white@{opacity}:fontsize=28:"
            f"x={x}:y={y}:"
            f"shadowcolor=black@0.5:shadowx=2:shadowy=2"
        )
        cmd = [
            self.ffmpeg, "-y",
            "-i", input_path,
            "-vf", drawtext,
            "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            output_path,
        ]
        self._run(cmd)

    # ── Preview ───────────────────────────────────────────────────────────────

    def make_preview(self, input_path: str, output_path: str, quality: str = "480p") -> None:
        """Quick 480p or 720p preview render."""
        height = 480 if quality == "480p" else 720
        cmd = [
            self.ffmpeg, "-y",
            "-i", input_path,
            "-vf", f"scale=-2:{height}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ]
        self._run(cmd)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_vf(
        self,
        width: int,
        height: int,
        crop_strategy: str,
        saliency_center: Optional[Tuple[float, float]],
    ) -> str:
        """Build FFmpeg -vf filter for scaling + cropping."""
        if crop_strategy == "smart" and saliency_center:
            cx, cy = saliency_center
            # Crop around saliency center, then scale
            return (
                f"scale='if(gt(iw/ih,{width}/{height}),{height}*iw/ih,{width})':'if(gt(iw/ih,{width}/{height}),{height},iw*{height}/ih)',"
                f"crop={width}:{height}:x=max(0\\,min(iw-{width}\\,(iw*{cx:.3f})-{width//2})):y=max(0\\,min(ih-{height}\\,(ih*{cy:.3f})-{height//2})),"
                f"setsar=1"
            )
        if crop_strategy in ("center", "smart"):
            return (
                f"scale='if(gt(iw/ih,{width}/{height}),{height}*iw/ih,{width})':"
                f"'if(gt(iw/ih,{width}/{height}),{height},iw*{height}/ih)',"
                f"crop={width}:{height},"
                f"setsar=1"
            )
        # fit with blur background (for vertical format with horizontal source)
        return (
            f"split[main][bg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=20:1[blurred];"
            f"[main]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[blurred][fg]overlay=(W-w)/2:(H-h)/2"
        )

    def _run(
        self,
        cmd: List[str],
        capture_output: bool = False,
        progress_cb: Optional[Callable] = None,
    ) -> subprocess.CompletedProcess:
        logger.debug("[FFmpeg] %s", " ".join(str(c) for c in cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=capture_output,
                check=True,
            )
            return result
        except subprocess.CalledProcessError as e:
            stderr = e.stderr if capture_output else ""
            raise FFmpegError(f"FFmpeg failed: {stderr[-500:] if stderr else 'unknown error'}") from e
        except FileNotFoundError:
            raise FFmpegError(f"FFmpeg binary not found: {cmd[0]}")


_XFADE_MAP = {
    "crossfade": "fade",
    "fade": "fade",
    "flash": "fadewhite",
    "zoom": "zoompan",
    "blur": "hblur",
    "wipe": "wipeleft",
}

_WATERMARK_POSITIONS = {
    "bottom_right": ("w-tw-20", "h-th-20"),
    "bottom_left": ("20", "h-th-20"),
    "top_right": ("w-tw-20", "20"),
    "top_left": ("20", "20"),
    "center": ("(w-tw)/2", "(h-th)/2"),
}
