"""
FFmpeg renderer - generates FFmpeg commands and renders video
"""

import json
import logging
import math
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from src.segment_selector import SelectedSegment
from src.config_loader import OutputConfig
from src.effects_config import EffectsConfiguration
from src.effects_engine import EffectsEngine

logger = logging.getLogger(__name__)

# Vertical adaptation modes — used when output is portrait (9:16) and
# source is landscape.  Kept as plain strings so callers need no import.
VERTICAL_MODE_CENTER_CROP = "center_crop"   # default: fill frame, crop centre
VERTICAL_MODE_FIT_BLUR    = "fit_blur"      # full image + blurred BG
VERTICAL_MODE_LEFT_CROP   = "left_crop"     # keep left portion
VERTICAL_MODE_RIGHT_CROP  = "right_crop"    # keep right portion

# All intermediate segments are normalised to these values so that
# the concat demuxer gets a uniform stream and produces a stable output.
_NORM_FPS     = 30
_NORM_PIXFMT  = "yuv420p"


class FFmpegRenderer:
    """Renders final video using FFmpeg"""

    @staticmethod
    def render(
        segments: List[SelectedSegment],
        output_config: OutputConfig,
        output_path: str,
        music_path: Optional[str] = None,
        music_fade_in: float = 3.0,
        music_fade_out: float = 3.0,
        music_start_time: float = 0.0,
        voiceover_path: Optional[str] = None,
        voiceover_volume: float = 0.9,
        music_volume: float = 0.3,
        subtitle_path: Optional[str] = None,
        effects_config: Optional[EffectsConfiguration] = None,
        progress_callback=None,
        vertical_mode: str = VERTICAL_MODE_CENTER_CROP,
        # Transition parameters (from TimelineBuilder / style settings)
        between_clip_transition: str = 'none',
        between_clip_transition_dur: float = 0.5,
    ) -> bool:
        """
        Render final video from segments.

        Args:
            segments:          List of SelectedSegment objects
            output_config:     OutputConfig with format and resolution
            output_path:       Path for output video file
            music_path:        Optional path to background music
            music_fade_in:     Music fade-in duration (seconds)
            music_fade_out:    Music fade-out duration (seconds)
            effects_config:    Optional effects configuration
            progress_callback: Optional callback(str) for progress messages
            vertical_mode:     Adaptation mode for vertical output
                               (center_crop | fit_blur | left_crop | right_crop)

        Returns:
            True if successful

        Raises:
            RuntimeError: If rendering fails
        """
        if not segments:
            raise ValueError("No segments to render")

        # Get resolution
        width, height = output_config.resolution

        # Create temporary directory for intermediate files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Step 1: Extract and scale segments
            segment_files = FFmpegRenderer._extract_segments(
                segments, width, height, temp_path, progress_callback, vertical_mode,
                effects_config=effects_config,
            )

            # Step 2: Concatenate segments
            # Use xfade transitions when a non-trivial transition is requested
            # and segment count is manageable; otherwise use fast concat demuxer.
            video_no_audio = temp_path / "video_no_audio.mp4"

            # TR-1 (ROADMAP Фаза 7): per-cut переходы из seg.transition_to_next.
            # 'cut'/'match_cut' → почти нулевая длительность (жёсткий рез);
            # 'crossfade' → реальный кроссфейд. Применяем, только если есть хотя бы
            # один кроссфейд (иначе быстрый concat-демультиплексор дешевле).
            per_cut = [getattr(s, "transition_to_next", None) for s in segments[:-1]]
            _has_per_cut = any(t for t in per_cut)
            _any_crossfade = any(t == "crossfade" for t in per_cut)

            _use_xfade = (
                between_clip_transition not in ('none', 'cut', 'clean_cut', '')
                and len(segment_files) <= 20
                and between_clip_transition_dur > 0.05
            )
            if _has_per_cut and _any_crossfade and len(segment_files) <= 20:
                # Смешанные переходы: резы — concat, кроссфейды — xfade между прогонами.
                cross = max(0.2, between_clip_transition_dur if between_clip_transition_dur > 0.05 else 0.4)
                if progress_callback:
                    progress_callback(
                        f"[Transitions] Per-cut: {sum(1 for t in per_cut if t=='crossfade')} "
                        f"crossfade / {sum(1 for t in per_cut if t!='crossfade')} match-cut"
                    )
                FFmpegRenderer._concatenate_mixed(
                    segment_files, video_no_audio,
                    transitions=[t or "cut" for t in per_cut], crossfade_dur=cross,
                )
            elif _use_xfade:
                if progress_callback:
                    progress_callback(
                        f"[Transitions] Applying {between_clip_transition} "
                        f"({between_clip_transition_dur}s) to {len(segment_files)} segments"
                    )
                FFmpegRenderer._concatenate_with_xfade(
                    segment_files, video_no_audio,
                    transition_type=between_clip_transition,
                    transition_dur=between_clip_transition_dur,
                )
            else:
                concat_file = temp_path / "concat_list.txt"
                FFmpegRenderer._create_concat_file(segment_files, concat_file)
                FFmpegRenderer._concatenate_segments(concat_file, video_no_audio)

            # Sanity-check the silent video before adding music.
            # If this is short the output will freeze — better to know now.
            silent_check = FFmpegRenderer._validate_output(
                str(video_no_audio),
                output_config.target_duration,
                progress_callback,
            )
            if not silent_check.get("ok"):
                logger.warning(
                    f"[Render] Silent video duration mismatch: {silent_check.get('error')}"
                )

            # Step 3: Add audio tracks
            # When subtitles will be burned we need an intermediate file
            _audio_out = output_path if not subtitle_path else str(temp_path / "with_audio.mp4")

            if voiceover_path and music_path:
                FFmpegRenderer._add_multi_track_audio(
                    video_no_audio, voiceover_path, music_path, _audio_out,
                    music_fade_in, music_fade_out, music_start_time,
                    voiceover_volume, music_volume,
                )
            elif voiceover_path:
                FFmpegRenderer._add_voiceover_only(
                    video_no_audio, voiceover_path, _audio_out, voiceover_volume,
                )
            elif music_path:
                FFmpegRenderer._add_music(
                    video_no_audio, music_path, _audio_out,
                    music_fade_in, music_fade_out, music_start_time,
                )
            else:
                FFmpegRenderer._copy_file(video_no_audio, _audio_out)

            # Step 3b: Burn-in subtitles (requires re-encode of video track)
            if subtitle_path and Path(subtitle_path).exists():
                if progress_callback:
                    progress_callback("[Subtitles] Burning subtitles into video…")
                FFmpegRenderer._burn_subtitles(_audio_out, subtitle_path, output_path)

        # Step 4: Post-render validation on the final file.
        final_check = FFmpegRenderer._validate_output(
            output_path,
            output_config.target_duration,
            progress_callback,
        )
        if not final_check.get("ok"):
            logger.error(
                f"[Render] FINAL OUTPUT VALIDATION FAILED: {final_check.get('error')}"
            )

        return True

    @staticmethod
    def _probe_orientation(video_path: str) -> dict:
        """
        Probe source video dimensions and rotation metadata via ffprobe.

        Returns a dict with:
            display_width, display_height  — effective display dimensions
                                             (swapped when rotate=90/270)
            rotation                       — raw rotate tag in degrees (0 if absent)
            orientation                    — "horizontal" | "vertical" | "square"
        Returns {} on any ffprobe failure.
        """
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:stream_tags=rotate",
            "-of", "json",
            str(video_path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return {}
            data = json.loads(result.stdout)
            stream = data.get("streams", [{}])[0]
            raw_w = int(stream.get("width", 0) or 0)
            raw_h = int(stream.get("height", 0) or 0)
            rotation = 0
            tags = stream.get("tags", {}) or {}
            if "rotate" in tags:
                try:
                    rotation = int(tags["rotate"])
                except (ValueError, TypeError):
                    pass
            # Swap for 90°/270° rotated clips (common on iOS/Android)
            if abs(rotation) in (90, 270):
                disp_w, disp_h = raw_h, raw_w
            else:
                disp_w, disp_h = raw_w, raw_h
            if disp_w > disp_h:
                orientation = "horizontal"
            elif disp_h > disp_w:
                orientation = "vertical"
            else:
                orientation = "square"
            return {
                "display_width": disp_w,
                "display_height": disp_h,
                "rotation": rotation,
                "orientation": orientation,
            }
        except Exception:
            return {}

    @staticmethod
    def _build_video_filter(
        out_w: int,
        out_h: int,
        vertical_mode: str,
        face_center_x: float = 0.5,
    ) -> str:
        """
        Build the -vf filter string for segment extraction.

        For non-vertical output: standard letterbox/pillarbox (black bars are
        intentional for 16:9 and 1:1 formats).

        For vertical output (out_h > out_w): fills the entire frame without
        black bars using the selected vertical_mode:
          center_crop  — scale to fill, crop centre (default)
          left_crop    — scale to fill, crop from left
          right_crop   — scale to fill, crop from right
          fit_blur     — sentinel: caller must use _build_filter_complex_blur()

        face_center_x: normalized horizontal face position (0=left, 1=right).
          When in center_crop mode and face_center_x != 0.5, the crop is
          shifted toward the face so the subject stays in frame.

        All crop expressions use FFmpeg's runtime variables (iw, ow) so they
        work correctly regardless of the actual source resolution.
        """
        is_vertical = out_h > out_w

        if not is_vertical:
            return (
                f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2"
            )

        if vertical_mode == VERTICAL_MODE_FIT_BLUR:
            return "__FILTER_COMPLEX__"

        if vertical_mode == VERTICAL_MODE_LEFT_CROP:
            crop_x = "0"
        elif vertical_mode == VERTICAL_MODE_RIGHT_CROP:
            crop_x = "iw-ow"
        else:
            # center_crop: shift crop toward detected face/subject when available.
            if abs(face_center_x - 0.5) > 0.08:
                # crop_x = (iw-ow) * factor. factor = clamp(center, 0.05..0.95) is
                # always in [0,1] ⇒ результат всегда в [0, iw-ow], clip() не нужен.
                # ВАЖНО: не использовать clip()/min()/max() здесь — запятые внутри
                # функции ломают разбор filtergraph (ffmpeg видит ',' как разделитель
                # фильтров → "No such filter: '0'"). Поэтому только умножение.
                factor = max(0.05, min(0.95, face_center_x))
                crop_x = f"(iw-ow)*{factor:.4f}"
            else:
                crop_x = "(iw-ow)/2"

        return (
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h}:{crop_x}:0"
        )

    @staticmethod
    def _build_filter_complex_blur(out_w: int, out_h: int) -> str:
        """
        filter_complex for 'fit with blur background' vertical mode.

        The source video is split into two streams:
          [bg] — scaled to fill the entire frame and heavily blurred
          [fg] — scaled to fit entirely within the frame (no crop, no bars)
        Both are composited; [fg] is centred over [blurred bg].
        """
        return (
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur=20:1[bg];"
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[out]"
        )

    @staticmethod
    def _validate_segment(seg_file: Path) -> dict:
        """
        Quick ffprobe sanity-check on an extracted intermediate segment.

        Returns a dict:
            ok       — True if the file has a valid video stream with duration > 0.1s
            duration — video stream duration in seconds (0 if not found)
            error    — human-readable reason when ok=False, else None
        """
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type,duration",
            "-of", "json",
            str(seg_file),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return {"ok": False, "duration": 0.0, "error": "ffprobe non-zero exit"}
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if not streams:
                return {"ok": False, "duration": 0.0, "error": "no video stream"}
            dur = float(streams[0].get("duration") or 0)
            if dur < 0.05:
                return {"ok": False, "duration": dur, "error": f"duration={dur:.3f}s too short"}
            return {"ok": True, "duration": dur, "error": None}
        except Exception as exc:
            return {"ok": False, "duration": 0.0, "error": str(exc)}

    @staticmethod
    def _validate_output(
        output_path: str,
        target_duration: float,
        progress_callback=None,
    ) -> dict:
        """
        Post-render ffprobe validation.

        Compares video stream duration, audio stream duration and container
        duration against the target.  Logs a clear warning when the video
        stream is shorter than the audio stream (the "frozen video / music
        continues" symptom).

        Returns dict: ok, container_dur, video_dur, audio_dur, gap, error.
        """
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,duration:format=duration",
            "-of", "json",
            str(output_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode != 0:
                return {"ok": False, "error": "ffprobe failed on output file"}

            data          = json.loads(result.stdout)
            container_dur = float(data.get("format", {}).get("duration") or 0)
            video_dur     = 0.0
            audio_dur     = 0.0

            for s in data.get("streams", []):
                d = float(s.get("duration") or 0)
                if s.get("codec_type") == "video" and d > video_dur:
                    video_dur = d
                elif s.get("codec_type") == "audio" and d > audio_dur:
                    audio_dur = d

            gap = audio_dur - video_dur          # positive = audio is longer
            ok  = video_dur >= target_duration * 0.90 and gap < 3.0

            summary = (
                f"[OutputValidation] container={container_dur:.2f}s  "
                f"video={video_dur:.2f}s  audio={audio_dur:.2f}s  "
                f"target={target_duration:.2f}s"
            )
            if gap > 1.0:
                summary += (
                    f"  ⚠ AUDIO IS {gap:.1f}s LONGER THAN VIDEO — "
                    f"this causes frozen video / music continues symptom"
                )
            elif not ok:
                short = target_duration - video_dur
                summary += f"  ⚠ video is {short:.1f}s shorter than target"

            logger.info(summary)
            if progress_callback:
                progress_callback(summary)

            return {
                "ok":            ok,
                "container_dur": container_dur,
                "video_dur":     video_dur,
                "audio_dur":     audio_dur,
                "gap":           gap,
                "error":         None if ok else summary,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _extract_segments(
        segments: List[SelectedSegment],
        width: int,
        height: int,
        temp_path: Path,
        progress_callback,
        vertical_mode: str = VERTICAL_MODE_CENTER_CROP,
        effects_config: Optional["EffectsConfiguration"] = None,
    ) -> List[Path]:
        """
        Extract, scale and adapt segments to temporary files.

        For vertical output formats the correct adaptation filter is applied
        (no black bars); for horizontal/square the standard letterbox is used.

        Returns:
            List of paths to extracted segment files
        """
        segment_files = []
        _ori_cache: dict = {}   # avoid re-probing same source file

        for i, seg in enumerate(segments):
            output_file = temp_path / f"segment_{i:04d}.mp4"

            # Probe source orientation for logging (cached per path)
            if seg.source_path not in _ori_cache:
                _ori_cache[seg.source_path] = FFmpegRenderer._probe_orientation(
                    seg.source_path
                )
            ori = _ori_cache[seg.source_path]

            if progress_callback:
                if ori:
                    dw = ori.get("display_width", "?")
                    dh = ori.get("display_height", "?")
                    orient = ori.get("orientation", "?")
                    rot_note = (
                        f" [rotate={ori['rotation']}°]" if ori.get("rotation") else ""
                    )
                    progress_callback(
                        f"Segment {i+1}/{len(segments)}: {dw}×{dh}{rot_note}"
                        f" ({orient}) → {width}×{height} [{vertical_mode}]"
                    )
                else:
                    progress_callback(f"Extracting segment {i+1}/{len(segments)}")

            # Base FFmpeg command.
            # -r and -pix_fmt normalise every segment to the same FPS and pixel
            # format so that the concat demuxer (-c copy) receives a uniform
            # stream.  Without this, mixing 24/30/59.94 fps sources causes
            # timebase discontinuities that manifest as frozen video after N
            # seconds in most players.
            cmd_base = [
                "ffmpeg", "-y",
                "-ss", str(seg.start),
                "-i", seg.source_path,
                "-t", str(seg.duration),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-r", str(_NORM_FPS),
                "-pix_fmt", _NORM_PIXFMT,
                "-an",
            ]

            # Smart reframing (ROADMAP Фаза 4, RF-1): per-segment crop center.
            # Priority: explicit crop_center_x (set by SmartCrop in the frontend) →
            # legacy candidate features → frame centre.
            _face_cx = getattr(seg, 'crop_center_x', None)
            if _face_cx is None:
                _face_cx = 0.5
                try:
                    from src.video_analysis.candidate_builder import CandidateClip
                    if hasattr(seg, '_candidate') and seg._candidate is not None:
                        f = seg._candidate.features
                        if f is not None:
                            _face_cx = getattr(f, 'face_center_x', 0.5)
                except Exception:
                    pass
            vf = FFmpegRenderer._build_video_filter(width, height, vertical_mode, float(_face_cx))

            # Per-segment visual transitions (intro fade-in / outro fade-out).
            seg_role = getattr(seg, 'role', 'body')
            fade_filters = FFmpegRenderer._build_role_fade_filters(seg, seg_role)

            # Build optional color grading + vignette filters from effects_config
            _color_filters = ""
            if effects_config is not None and effects_config.color.enabled:
                try:
                    from src.effects_engine import EffectsEngine
                    cf = EffectsEngine.generate_color_filter(
                        effects_config.color.style,
                        effects_config.color.brightness,
                        effects_config.color.contrast,
                        effects_config.color.saturation,
                        effects_config.color.temperature,
                    )
                    if cf:
                        _color_filters = "," + cf
                    if effects_config.color.vignette:
                        _color_filters += ",vignette=PI/4"
                except Exception:
                    pass

            if vf == "__FILTER_COMPLEX__":
                fc_base = FFmpegRenderer._build_filter_complex_blur(width, height)
                norm_fade = f"fps={_NORM_FPS},format={_NORM_PIXFMT}"
                if fade_filters:
                    norm_fade += "," + fade_filters
                if _color_filters:
                    norm_fade += _color_filters
                fc = fc_base.replace(
                    "[out]",
                    f"[outraw];[outraw]{norm_fade}[out]"
                )
                cmd = cmd_base + [
                    "-filter_complex", fc,
                    "-map", "[out]",
                    str(output_file),
                ]
            else:
                vf_full = vf + f",fps={_NORM_FPS},format={_NORM_PIXFMT}"
                if fade_filters:
                    vf_full += "," + fade_filters
                if _color_filters:
                    vf_full += _color_filters
                cmd = cmd_base + ["-vf", vf_full, str(output_file)]

            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                err_msg = f"Segment {i+1} encode failed: {e.stderr[-300:]}"
                logger.error(err_msg)
                if progress_callback:
                    progress_callback(f"⚠ {err_msg}", "WARNING")
                # Skip this segment rather than aborting the whole render.
                continue

            # Validate the output file before adding it to the concat list.
            v = FFmpegRenderer._validate_segment(output_file)
            if not v["ok"]:
                warn = f"Segment {i+1} validation failed ({v['error']}) — skipping"
                logger.warning(warn)
                if progress_callback:
                    progress_callback(warn, "WARNING")
                continue

            segment_files.append(output_file)

        if not segment_files:
            raise RuntimeError(
                "All segments failed to render. Check source video files and logs."
            )

        total_extracted = sum(
            FFmpegRenderer._validate_segment(f)["duration"] for f in segment_files
        )
        logger.info(
            f"[Segments] Extracted {len(segment_files)}/{len(segments)} segments, "
            f"total duration = {total_extracted:.2f}s"
        )
        if progress_callback:
            progress_callback(
                f"Segments: {len(segment_files)}/{len(segments)} OK, "
                f"total = {total_extracted:.1f}s"
            )

        return segment_files

    # ── Transition helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _build_role_fade_filters(seg: SelectedSegment, role: str) -> str:
        """
        Build FFmpeg vf fade filter string for intro/outro segments.

        Returns an empty string for body segments.
        """
        if role == 'intro':
            transition = getattr(seg, 'start_transition', 'clean_cut')
            dur = getattr(seg, 'start_transition_duration', 0.0)
            if transition == 'fade_in' and dur > 0:
                return f"fade=t=in:st=0:d={dur}"
            if transition in ('cinematic_crossfade', 'cinematic_fade') and dur > 0:
                return f"fade=t=in:st=0:d={dur}"
            if transition == 'beat_flash' and dur > 0:
                # Fast brightness flash: very short fade in
                return f"fade=t=in:st=0:d={min(dur, 0.15)}"
            if transition == 'zoom_in' and dur > 0:
                # Zoom via scale: start zoomed and scale back — approximation with vf
                # (true zoom needs filter_complex; here we use fade as fallback)
                return f"fade=t=in:st=0:d={dur}"
            return ""

        if role == 'outro':
            transition = getattr(seg, 'end_transition', 'fade_out')
            dur = getattr(seg, 'end_transition_duration', 0.8)
            fade_start = max(0.0, seg.duration - dur)
            if transition in ('fade_out', 'cinematic_fade') and dur > 0:
                return f"fade=t=out:st={fade_start:.3f}:d={dur}"
            if transition in ('flash_impact', 'beat_cut') and dur > 0:
                # Quick bright flash then cut
                return f"fade=t=out:st={fade_start:.3f}:d={min(dur, 0.2)}"
            if transition == 'freeze_final':
                # Freeze is handled at the concat level (repeat last frame);
                # here just do a fast fade so we don't hard-cut.
                return f"fade=t=out:st={fade_start:.3f}:d={min(dur, 0.3)}"
            return ""

        return ""

    @staticmethod
    def _concatenate_with_xfade(
        segment_files: List[Path],
        output_file: Path,
        transition_type: str = 'fade',
        transition_dur: float = 0.5,
        transition_durs: Optional[List[float]] = None,
    ):
        """
        Concatenate segments using FFmpeg xfade filter for real between-clip
        transitions (crossfade, flash, zoom).

        Falls back to concat demuxer when segment count > 20 or on any error,
        because the filter_complex grows linearly and can exceed FFmpeg limits.

        Supported transition_type values (xfade filter tokens):
          'fade', 'wipeleft', 'wiperight', 'slideleft', 'slideright',
          'circleopen', 'pixelize', 'hblur', 'radial', 'zoomin'

        transition_durs (ROADMAP Фаза 7, TR-1): необязательный список длительностей
        переходов ПО ГРАНИЦАМ (len = n-1). Match-cut/cut-on-action получают почти
        нулевую длительность (~1 кадр = жёсткий рез), «рваные» стыки — реальный
        кроссфейд. Если None — используется единый transition_dur для всех границ.
        """
        n = len(segment_files)
        if n == 0:
            raise RuntimeError("No segment files to concatenate")
        if n == 1:
            import shutil
            shutil.copy2(segment_files[0], output_file)
            return
        if n > 20:
            # Too many segments for filter_complex — use concat demuxer
            logger.warning(
                f"[XFade] {n} segments > 20 limit — falling back to concat demuxer"
            )
            FFmpegRenderer._concatenate_segments_simple(segment_files, output_file)
            return

        try:
            # Probe durations
            durations = []
            for f in segment_files:
                v = FFmpegRenderer._validate_segment(f)
                durations.append(v.get('duration', 2.0))

            # Build filter_complex
            inputs = []
            for f in segment_files:
                inputs += ["-i", str(f)]

            # Map transition type to xfade token
            xfade_map = {
                'fade': 'fade', 'crossfade': 'fade',
                'flash': 'fade',          # xfade has no flash; fade is closest
                'zoom_in': 'zoomin', 'zoom': 'zoomin',
                'cinematic_crossfade': 'fade', 'cinematic_fade': 'fade',
                'beat_flash': 'fade', 'clean_cut': 'fade',
            }
            xf = xfade_map.get(transition_type, 'fade')
            d_uniform = max(0.05, min(transition_dur, 1.0))

            filter_parts = []
            current_label = "[0:v]"
            offset = 0.0

            for idx in range(1, n):
                # Длительность перехода для ЭТОЙ границы (TR-1: per-cut).
                if transition_durs is not None and idx - 1 < len(transition_durs):
                    d = max(0.03, min(float(transition_durs[idx - 1]), 1.0))
                else:
                    d = d_uniform
                prev_dur = durations[idx - 1]
                offset += prev_dur - d
                offset = max(0.01, offset)
                out_label = f"[v{idx}]"
                filter_parts.append(
                    f"{current_label}[{idx}:v]"
                    f"xfade=transition={xf}:duration={d:.3f}:offset={offset:.3f}"
                    f"{out_label}"
                )
                current_label = out_label

            filter_complex = ";".join(filter_parts)

            cmd = (
                ["ffmpeg", "-y"]
                + inputs
                + ["-filter_complex", filter_complex,
                   "-map", current_label,
                   "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                   "-pix_fmt", _NORM_PIXFMT,
                   str(output_file)]
            )

            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"[XFade] Concatenated {n} segments with {xf} transition")

        except subprocess.CalledProcessError as e:
            logger.warning(
                f"[XFade] xfade failed ({e.stderr[-200:]}), "
                f"falling back to concat demuxer"
            )
            FFmpegRenderer._concatenate_segments_simple(segment_files, output_file)

    @staticmethod
    def _concatenate_mixed(
        segment_files: List[Path],
        output_file: Path,
        transitions: List[str],
        crossfade_dur: float = 0.4,
    ):
        """Смешанные переходы по границам (ROADMAP Фаза 7, TR-1).

        ``transitions`` (len = n-1): 'crossfade' или иное (рез). Жёсткие резы
        НЕ прогоняются через xfade (это ломает цепочку при крошечной длительности) —
        вместо этого соседние «cut»-сегменты склеиваются concat-демультиплексором
        без потерь, а xfade применяется ТОЛЬКО между получившимися «прогонами».
        """
        n = len(segment_files)
        if n <= 1:
            FFmpegRenderer._concatenate_segments_simple(segment_files, output_file)
            return
        # Сгруппировать в «прогоны», разделённые границами-кроссфейдами.
        runs: List[List[Path]] = []
        cur: List[Path] = [segment_files[0]]
        for i, t in enumerate(transitions[: n - 1]):
            if t == "crossfade":
                runs.append(cur)
                cur = [segment_files[i + 1]]
            else:
                cur.append(segment_files[i + 1])
        runs.append(cur)

        if len(runs) == 1:                      # кроссфейдов нет → быстрый concat
            FFmpegRenderer._concatenate_segments_simple(runs[0], output_file)
            return

        # Каждый прогон → отдельный файл (жёсткая склейка без потерь).
        run_files: List[Path] = []
        for j, run in enumerate(runs):
            if len(run) == 1:
                run_files.append(run[0])
            else:
                rf = output_file.parent / f"run_{j:03d}.mp4"
                FFmpegRenderer._concatenate_segments_simple(run, rf)
                run_files.append(rf)
        # Между прогонами — равномерный кроссфейд (надёжная ветка xfade).
        FFmpegRenderer._concatenate_with_xfade(
            run_files, output_file, transition_type="fade", transition_dur=crossfade_dur
        )

    @staticmethod
    def _concatenate_segments_simple(segment_files: List[Path], output_file: Path):
        """Fast concat demuxer path (no transitions, -c copy)."""
        import tempfile as _tf
        with _tf.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
            for f in segment_files:
                tmp.write(f"file '{f.absolute()}'\n")
            tmp_path = tmp.name
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", tmp_path, "-c", "copy", str(output_file),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Concat fallback failed: {e.stderr}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @staticmethod
    def _create_concat_file(segment_files: List[Path], concat_file: Path):
        """
        Create FFmpeg concat file format

        Format:
        file '/path/to/segment1.mp4'
        file '/path/to/segment2.mp4'
        """
        with open(concat_file, 'w') as f:
            for seg_file in segment_files:
                # Use absolute path and escape quotes
                abs_path = seg_file.absolute()
                f.write(f"file '{abs_path}'\n")

    @staticmethod
    def _concatenate_segments(concat_file: Path, output_file: Path):
        """
        Concatenate normalised segments using the FFmpeg concat demuxer.

        All intermediate files are already at _NORM_FPS / _NORM_PIXFMT / libx264,
        so -c copy is safe and avoids a second full re-encode pass.
        """
        # Count how many files are in the concat list (for logging)
        try:
            lines = [l for l in concat_file.read_text().splitlines() if l.startswith("file ")]
            logger.info(f"[Concat] Joining {len(lines)} segment(s)")
        except Exception:
            pass

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_file),
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to concatenate segments: {e.stderr}")

    @staticmethod
    def _add_music(
        video_path: Path,
        music_path: str,
        output_path: str,
        fade_in: float,
        fade_out: float,
        music_start_time: float = 0.0
    ):
        """
        Add background music with guaranteed 100% audio coverage.

        Strategy:
        - If music window (start_time → end_of_file) covers the video: simple atrim.
        - If music is shorter than video: loop the music window using multiple
          input copies and FFmpeg concat, then trim to exact video duration.

        Removes -shortest entirely — we explicitly trim audio to video duration.
        """
        video_dur  = FFmpegRenderer._get_duration(video_path)
        music_dur  = FFmpegRenderer._get_media_duration(music_path)

        # Available audio from the chosen start point to end of file
        available  = max(0.01, music_dur - music_start_time)
        music_end  = music_dur  # end of the audio window

        needs_loop    = available < video_dur
        loops_needed  = math.ceil(video_dur / available) if needs_loop else 1
        loops_needed  = min(loops_needed, 12)  # safety cap

        fade_out_start = max(0.0, video_dur - fade_out)

        if not needs_loop:
            # ── SIMPLE CASE: music window covers the full video ───────────────
            # Use duration= (not end=) so we never overshoot the file's end.
            audio_filter = (
                f"[1:a]"
                f"atrim=start={music_start_time}:duration={video_dur},"
                f"asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={fade_in},"
                f"afade=t=out:st={fade_out_start}:d={fade_out}"
                f"[a]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", music_path,
                "-filter_complex", audio_filter,
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ]

        else:
            # ── LOOP CASE: music window is shorter than video ─────────────────
            # Add one -i music_path per loop iteration; concat all windows;
            # trim the result to exact video duration.
            inputs       = ["-i", str(video_path)]
            filter_parts = []
            loop_labels  = []

            for i in range(loops_needed):
                inputs.extend(["-i", music_path])
                label = f"[lp{i}]"
                loop_labels.append(label)
                filter_parts.append(
                    f"[{i + 1}:a]"
                    f"atrim=start={music_start_time}:end={music_end},"
                    f"asetpts=PTS-STARTPTS"
                    f"{label}"
                )

            # Concat all loop segments into one stream
            concat_in = "".join(loop_labels)
            filter_parts.append(
                f"{concat_in}concat=n={loops_needed}:v=0:a=1[looped]"
            )

            # Trim to exact video duration, reset timestamps, add fades
            filter_parts.append(
                f"[looped]"
                f"atrim=0:{video_dur},"
                f"asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={fade_in},"
                f"afade=t=out:st={fade_out_start}:d={fade_out}"
                f"[a]"
            )

            cmd = ["ffmpeg", "-y"] + inputs + [
                "-filter_complex", ";".join(filter_parts),
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to add music: {e.stderr}")

    @staticmethod
    def _burn_subtitles(video_path: str, srt_path: str, output_path: str) -> None:
        """Re-encode video with subtitles burned in via the subtitles vf filter."""
        # Escape colons/backslashes in path for FFmpeg filter syntax
        safe_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"subtitles='{safe_srt}':force_style='FontSize=18,PrimaryColour=&H00FFFFFF&,OutlineColour=&H00000000&,Outline=2'",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "copy",
            output_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to burn subtitles: {e.stderr[-400:]}")

    @staticmethod
    def _add_voiceover_only(
        video_path: Path,
        voiceover_path: str,
        output_path: str,
        voiceover_volume: float = 0.9,
    ):
        """Attach a single voiceover track, trimmed to video duration."""
        video_dur = FFmpegRenderer._get_duration(video_path)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", voiceover_path,
            "-filter_complex",
            f"[1:a]volume={voiceover_volume},atrim=0:{video_dur},"
            f"asetpts=PTS-STARTPTS[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            output_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to add voiceover: {e.stderr[-400:]}")

    @staticmethod
    def _add_multi_track_audio(
        video_path: Path,
        voiceover_path: str,
        music_path: str,
        output_path: str,
        music_fade_in: float = 3.0,
        music_fade_out: float = 3.0,
        music_start_time: float = 0.0,
        voiceover_volume: float = 0.9,
        music_volume: float = 0.3,
    ):
        """Mix voiceover (0.9 vol) + background music (0.3 vol) over video."""
        video_dur = FFmpegRenderer._get_duration(video_path)
        music_dur = FFmpegRenderer._get_media_duration(music_path)
        available = max(0.01, music_dur - music_start_time)
        needs_loop = available < video_dur
        loops_needed = min(math.ceil(video_dur / available), 12) if needs_loop else 1
        fade_out_start = max(0.0, video_dur - music_fade_out)

        # Build inputs: [0]=video, [1]=voiceover, [2..N]=music copies
        inputs = ["-i", str(video_path), "-i", voiceover_path]
        for _ in range(loops_needed):
            inputs += ["-i", music_path]

        filter_parts = []

        # Voiceover stream
        filter_parts.append(
            f"[1:a]volume={voiceover_volume},"
            f"atrim=0:{video_dur},asetpts=PTS-STARTPTS[vo]"
        )

        # Music: loop if needed, then trim + fades + volume
        if needs_loop:
            loop_labels = []
            for i in range(loops_needed):
                lbl = f"[lp{i}]"
                loop_labels.append(lbl)
                filter_parts.append(
                    f"[{i+2}:a]"
                    f"atrim=start={music_start_time}:end={music_dur},"
                    f"asetpts=PTS-STARTPTS{lbl}"
                )
            concat_in = "".join(loop_labels)
            filter_parts.append(f"{concat_in}concat=n={loops_needed}:v=0:a=1[looped]")
            filter_parts.append(
                f"[looped]atrim=0:{video_dur},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={music_fade_in},"
                f"afade=t=out:st={fade_out_start}:d={music_fade_out},"
                f"volume={music_volume}[mu]"
            )
        else:
            filter_parts.append(
                f"[2:a]atrim=start={music_start_time}:duration={video_dur},"
                f"asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={music_fade_in},"
                f"afade=t=out:st={fade_out_start}:d={music_fade_out},"
                f"volume={music_volume}[mu]"
            )

        # Merge voiceover + music
        filter_parts.append("[vo][mu]amix=inputs=2:duration=longest:normalize=0[a]")

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + [
                "-filter_complex", ";".join(filter_parts),
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                output_path,
            ]
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to mix audio tracks: {e.stderr[-400:]}")

    @staticmethod
    def _get_media_duration(file_path: str) -> float:
        """Get duration of any media file (audio or video) via ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError):
            return 0.0

    @staticmethod
    def _copy_file(source: Path, destination: str):
        """
        Copy file using FFmpeg to ensure correct format
        """
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(source),
            "-c", "copy",
            destination
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to copy file: {e.stderr}")

    @staticmethod
    def _get_duration(video_path: Path) -> float:
        """
        Get video duration using ffprobe
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError) as e:
            raise RuntimeError(f"Failed to get video duration: {e}")

    @staticmethod
    def render_fast_preview(
        segments: List[SelectedSegment],
        output_path: str,
        output_format: str = "horizontal",
        music_path: Optional[str] = None,
        music_start_time: float = 0.0,
        vertical_mode: str = VERTICAL_MODE_CENTER_CROP,
        progress_callback=None,
    ) -> bool:
        """
        Fast low-resolution preview render — ~10x faster than final render.

        Uses 480p, ultrafast preset, simple concat (no transitions), minimal
        color processing. Suitable for checking rhythm and clip selection before
        committing to a full-quality render.

        Args:
            segments:          Selected segments to preview.
            output_path:       Output file path (.mp4).
            output_format:     "horizontal" | "vertical" | "square"
            music_path:        Optional background music.
            music_start_time:  Music start offset in seconds.
            vertical_mode:     Crop mode for vertical output.
            progress_callback: Optional callable(str).

        Returns:
            True on success, False on failure.
        """
        if not segments:
            return False

        def _cb(msg):
            if progress_callback:
                try:
                    progress_callback(msg)
                except Exception:
                    pass

        # Preview resolutions (short side ≤ 480px)
        preview_res = {
            "horizontal": (854, 480),
            "vertical":   (480, 854),
            "square":     (480, 480),
        }
        width, height = preview_res.get(output_format, (854, 480))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            segment_files = []

            _cb(f"[Preview] Extracting {len(segments)} segments at {width}×{height}…")
            for i, seg in enumerate(segments):
                out_seg = tmp_path / f"seg_{i:04d}.mp4"

                # Build scale+crop filter for this segment
                if output_format == "vertical" and vertical_mode == VERTICAL_MODE_FIT_BLUR:
                    vf = (
                        f"[0:v]split[main][blur];"
                        f"[blur]scale={width}:{height}:force_original_aspect_ratio=increase,"
                        f"crop={width}:{height},boxblur=20:5[bg];"
                        f"[main]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
                        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
                    )
                else:
                    vf = (
                        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                        f"crop={width}:{height}"
                    )

                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{seg.start:.3f}",
                    "-i", str(seg.source_path),
                    "-t",  f"{seg.duration:.3f}",
                    "-vf", vf,
                    "-r",  "30",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf",    "35",
                    "-pix_fmt", "yuv420p",
                    "-an",
                    str(out_seg),
                ]
                try:
                    subprocess.run(cmd, capture_output=True, timeout=120, check=True)
                    segment_files.append(out_seg)
                except subprocess.CalledProcessError as e:
                    _cb(f"[Preview] Segment {i} failed, skipping: {e}")
                except subprocess.TimeoutExpired:
                    _cb(f"[Preview] Segment {i} timed out, skipping")

            if not segment_files:
                return False

            # Concat
            concat_list = tmp_path / "preview_concat.txt"
            with open(concat_list, "w") as f:
                for sf in segment_files:
                    f.write(f"file '{sf}'\n")

            video_silent = tmp_path / "preview_silent.mp4"
            _cb("[Preview] Concatenating…")
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-f", "concat", "-safe", "0",
                        "-i", str(concat_list),
                        "-c", "copy",
                        str(video_silent),
                    ],
                    capture_output=True, timeout=120, check=True,
                )
            except subprocess.CalledProcessError:
                return False

            # Add music (simple mix, no fade processing)
            if music_path and Path(music_path).exists():
                video_dur = sum(s.duration for s in segments)
                _cb("[Preview] Adding music…")
                try:
                    subprocess.run(
                        [
                            "ffmpeg", "-y",
                            "-i", str(video_silent),
                            "-ss", f"{music_start_time:.3f}",
                            "-i", str(music_path),
                            "-map", "0:v",
                            "-map", "1:a",
                            "-c:v", "copy",
                            "-c:a", "aac", "-b:a", "96k",
                            "-t",   f"{video_dur:.3f}",
                            "-shortest",
                            str(output_path),
                        ],
                        capture_output=True, timeout=120, check=True,
                    )
                except subprocess.CalledProcessError:
                    # fallback: no audio
                    import shutil
                    shutil.copy2(str(video_silent), str(output_path))
            else:
                import shutil
                shutil.copy2(str(video_silent), str(output_path))

        _cb(f"[Preview] Done → {output_path}")
        return Path(output_path).exists()

    # ------------------------------------------------------------------
    # Post-render utilities
    # ------------------------------------------------------------------

    @staticmethod
    def extract_thumbnail(
        video_path: str,
        output_path: str,
        timestamp: Optional[float] = None,
    ) -> bool:
        """
        Extract a single frame from *video_path* and save it as a JPEG thumbnail.
        If *timestamp* is None, seeks to 5% into the video (auto-picks a frame
        that avoids the black/fade at the very start).
        Returns True on success.
        """
        try:
            if timestamp is None:
                # Probe duration then pick 5%
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                    capture_output=True, text=True, timeout=10,
                )
                try:
                    dur = float(probe.stdout.strip())
                except (ValueError, TypeError):
                    dur = 10.0
                timestamp = max(0.1, dur * 0.05)

            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", f"{timestamp:.3f}",
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-vf", "scale=1280:-1",
                    "-q:v", "3",
                    str(output_path),
                ],
                capture_output=True, timeout=30,
            )
            return result.returncode == 0 and Path(output_path).exists()
        except Exception as e:
            logger.warning(f"extract_thumbnail failed: {e}")
            return False

    @staticmethod
    def apply_watermark(
        video_path: str,
        output_path: str,
        text: Optional[str] = None,
        image_path: Optional[str] = None,
        position: str = "bottom_right",
        opacity: float = 0.7,
        font_size: int = 36,
    ) -> bool:
        """
        Add a text or image watermark to *video_path* and save to *output_path*.
        *position*: top_left | top_right | bottom_left | bottom_right | center
        Returns True on success.  Either *text* or *image_path* must be provided.
        """
        if not text and not image_path:
            raise ValueError("Provide text or image_path for watermark")

        _positions = {
            "top_left":     ("10",          "10"),
            "top_right":    ("W-w-10",      "10"),
            "bottom_left":  ("10",          "H-h-10"),
            "bottom_right": ("W-w-10",      "H-h-10"),
            "center":       ("(W-w)/2",     "(H-h)/2"),
        }
        px, py = _positions.get(position, _positions["bottom_right"])

        try:
            if text:
                # Escape special chars for drawtext
                safe_text = text.replace("'", "\\'").replace(":", "\\:")
                vf = (
                    f"drawtext=text='{safe_text}':"
                    f"fontsize={font_size}:"
                    f"fontcolor=white@{opacity}:"
                    f"shadowcolor=black@0.5:shadowx=2:shadowy=2:"
                    f"x={px}:y={py}"
                )
            else:
                vf = (
                    f"movie='{image_path}'[wm];"
                    f"[in][wm]overlay={px}:{py}:alpha=premultiplied"
                )

            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(video_path),
                    "-vf", vf,
                    "-c:a", "copy",
                    "-preset", "fast",
                    str(output_path),
                ],
                capture_output=True, timeout=600,
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"apply_watermark failed: {e}")
            return False

    @staticmethod
    def check_stabilization_available() -> bool:
        """Return True if libvidstab is available in the local ffmpeg build."""
        try:
            result = subprocess.run(
                ["ffmpeg", "-filters"],
                capture_output=True, text=True, timeout=10,
            )
            return "vidstabdetect" in result.stdout
        except Exception:
            return False

    @staticmethod
    def stabilize_video(
        input_path: str,
        output_path: str,
        shakiness: int = 5,
        smoothing: int = 15,
        progress_callback=None,
    ) -> bool:
        """
        Two-pass video stabilization using libvidstab.
        Returns True on success.  Requires ffmpeg built with libvidstab.
        """
        def _cb(msg):
            if progress_callback:
                try:
                    progress_callback(msg)
                except Exception:
                    pass

        if not FFmpegRenderer.check_stabilization_available():
            _cb("[Stabilize] libvidstab not available — skipping")
            return False

        try:
            with tempfile.TemporaryDirectory() as tmp:
                transforms = Path(tmp) / "transforms.trf"

                # Pass 1: detect
                _cb("[Stabilize] Pass 1: motion detection…")
                r1 = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(input_path),
                        "-vf", f"vidstabdetect=shakiness={shakiness}:accuracy=15"
                              f":result={transforms}",
                        "-f", "null", "-",
                    ],
                    capture_output=True, timeout=600,
                )
                if r1.returncode != 0:
                    _cb("[Stabilize] Pass 1 failed")
                    return False

                # Pass 2: transform
                _cb("[Stabilize] Pass 2: stabilizing…")
                r2 = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(input_path),
                        "-vf", f"vidstabtransform=zoom=1:smoothing={smoothing}"
                              f":input={transforms}",
                        "-c:a", "copy",
                        str(output_path),
                    ],
                    capture_output=True, timeout=600,
                )
                if r2.returncode != 0:
                    _cb("[Stabilize] Pass 2 failed")
                    return False

            _cb(f"[Stabilize] Done → {output_path}")
            return True
        except Exception as e:
            _cb(f"[Stabilize] Error: {e}")
            return False

    @staticmethod
    def generate_preview_command(
        segments: List[SelectedSegment],
        output_config: OutputConfig
    ) -> str:
        """
        Generate a preview FFmpeg command (for debugging/dry-run)

        Returns:
            FFmpeg command as string
        """
        width, height = output_config.resolution

        # Create filter complex for preview
        filter_parts = []
        for i, seg in enumerate(segments):
            filter_parts.append(
                f"[0:v]trim={seg.start}:{seg.end},setpts=PTS-STARTPTS,"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2[v{i}]"
            )

        concat_inputs = "".join(f"[v{i}]" for i in range(len(segments)))
        filter_complex = ";".join(filter_parts) + f";{concat_inputs}concat=n={len(segments)}:v=1[out]"

        cmd_parts = [
            "ffmpeg",
            "-i", segments[0].source_path,
            "-filter_complex", f'"{filter_complex}"',
            "-map", '"[out]"',
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "output.mp4"
        ]

        return " ".join(cmd_parts)


if __name__ == "__main__":
    # Test - just show what commands would be generated
    from src.config_loader import Range, OutputConfig
    from src.segment_selector import SegmentSelector

    test_ranges = [
        Range(start=5.0, end=15.0, type="good"),
        Range(start=20.0, end=35.0, type="must_use"),
    ]

    segments = SegmentSelector.select_segments(
        source_path="test.mp4",
        ranges=test_ranges,
        target_duration=30.0,
        dynamic_level="balanced",
        seed=42
    )

    output_config = OutputConfig(
        target_duration=30.0,
        format="horizontal",
        dynamic_level="balanced"
    )

    print("Preview FFmpeg command:")
    print()
    print(FFmpegRenderer.generate_preview_command(segments, output_config))
    print()
    print("Note: Actual rendering would use segment extraction method for reliability")
