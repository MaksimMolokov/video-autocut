"""
Video pre-processing filter — detects problematic segments before main editing.

Detects:
  camera_raise_lower  — camera being put down / picked up (dark + zero motion)
  technical_pause     — static scene with no meaningful motion
  text_overlay        — on-screen text / SMS / UI overlays (dense edges + still)

Output: good ranges (complement of detected bad segments) ready for the
selection pipeline.
"""

import cv2
import numpy as np
import subprocess
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from src.config_loader import Range

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DetectedSegment:
    start: float
    end: float
    problem_type: str   # 'camera_raise_lower' | 'technical_pause' | 'text_overlay'
    confidence: float   # 0.0–1.0


@dataclass
class PreprocessResult:
    video_path: str
    original_duration: float
    detected_segments: List[DetectedSegment]
    bad_ranges: List[Range]
    good_ranges: List[Range]
    filtered_duration: float
    stats: dict = field(default_factory=dict)


@dataclass
class PreprocessOptions:
    detect_camera_moves: bool = True
    detect_pauses: bool = True
    detect_text: bool = False

    # Detection thresholds
    dark_threshold: float = 0.10          # brightness below this → dark frame
    still_threshold: float = 0.04         # motion below this → no motion
    camera_move_min_duration: float = 0.3 # seconds of dark+still to flag as camera move
    pause_min_duration: float = 1.5       # seconds of stillness to flag as technical pause
    text_edge_threshold: float = 0.14     # edge density above this → text candidate
    text_motion_max: float = 0.04         # max motion for a text frame
    text_min_duration: float = 0.5        # minimum text segment duration to flag

    # Scan settings
    scan_fps: float = 3.0      # frames per second during scanning
    min_good_segment: float = 1.0  # discard good gaps shorter than this (seconds)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class VideoPreprocessor:
    """Scan video for problematic segments and return usable Range list."""

    @staticmethod
    def analyze(
        video_path: str,
        video_duration: float,
        options: Optional[PreprocessOptions] = None,
        progress_callback=None,
    ) -> PreprocessResult:
        """
        Scan video and return good ranges (complement of detected bad segments).

        Args:
            video_path:        Path to video file.
            video_duration:    Total duration in seconds (from ffprobe).
            options:           Detection options and thresholds.
            progress_callback: Optional callable(fraction: float, msg: str).
        """
        if options is None:
            options = PreprocessOptions()

        def _cb(frac, msg):
            if progress_callback:
                try:
                    progress_callback(frac, msg)
                except Exception:
                    pass

        _cb(0.0, "Сканирование кадров...")
        frame_data = VideoPreprocessor._scan_frames(
            video_path, video_duration, options.scan_fps
        )

        if not frame_data:
            return PreprocessResult(
                video_path=video_path,
                original_duration=video_duration,
                detected_segments=[],
                bad_ranges=[],
                good_ranges=[Range(start=0.0, end=video_duration, type="good")],
                filtered_duration=video_duration,
                stats={'error': 'no_frames'},
            )

        detected: List[DetectedSegment] = []

        if options.detect_camera_moves:
            _cb(0.4, "Поиск подъёма/опускания камеры...")
            segs = VideoPreprocessor._detect_camera_moves(
                frame_data, options.dark_threshold,
                options.still_threshold, options.camera_move_min_duration,
            )
            detected.extend(segs)

        if options.detect_pauses:
            _cb(0.6, "Поиск технических пауз...")
            segs = VideoPreprocessor._detect_pauses(
                frame_data, options.still_threshold, options.pause_min_duration,
            )
            detected.extend(segs)

        if options.detect_text:
            _cb(0.8, "Поиск текста на экране...")
            segs = VideoPreprocessor._detect_text_overlay(
                frame_data, options.text_edge_threshold,
                options.text_motion_max, options.text_min_duration,
            )
            detected.extend(segs)

        _cb(0.95, "Формирование диапазонов...")
        bad_ranges = VideoPreprocessor._segments_to_ranges(detected, video_duration)
        good_ranges = VideoPreprocessor._invert_ranges(
            bad_ranges, video_duration, options.min_good_segment
        )
        filtered_duration = sum(r.end - r.start for r in good_ranges)

        stats = {
            'camera_moves':   sum(1 for s in detected if s.problem_type == 'camera_raise_lower'),
            'pauses':         sum(1 for s in detected if s.problem_type == 'technical_pause'),
            'text_overlays':  sum(1 for s in detected if s.problem_type == 'text_overlay'),
            'removed_seconds': round(video_duration - filtered_duration, 1),
            'good_segments':  len(good_ranges),
        }

        logger.info(
            f"[Preprocessor] {video_path}: "
            f"camera={stats['camera_moves']} pauses={stats['pauses']} "
            f"text={stats['text_overlays']} removed={stats['removed_seconds']}s"
        )

        _cb(1.0, "Готово")
        return PreprocessResult(
            video_path=video_path,
            original_duration=video_duration,
            detected_segments=detected,
            bad_ranges=bad_ranges,
            good_ranges=good_ranges,
            filtered_duration=filtered_duration,
            stats=stats,
        )

    # -----------------------------------------------------------------------
    # Frame scanning
    # -----------------------------------------------------------------------

    @staticmethod
    def _scan_frames(video_path: str, duration: float, fps: float) -> list:
        """
        Extract frames at `fps` rate and return per-frame feature dicts.
        Each dict: {t, brightness, motion, edge_density}
        """
        interval = 1.0 / max(fps, 0.1)
        timestamps = []
        t = 0.0
        while t < duration:
            timestamps.append(t)
            t += interval

        results = []
        prev_gray = None

        for ts in timestamps:
            frame = VideoPreprocessor._extract_frame(video_path, ts)
            if frame is None:
                results.append({'t': ts, 'brightness': None, 'motion': None, 'edge_density': None})
                prev_gray = None
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            brightness = float(gray.mean()) / 255.0

            edges = cv2.Canny(gray, 50, 150)
            edge_density = float(edges.sum()) / max(1, edges.size * 255)

            motion = 0.0
            if prev_gray is not None:
                try:
                    flow = cv2.calcOpticalFlowFarneback(
                        prev_gray, gray, None,
                        pyr_scale=0.5, levels=2, winsize=8,
                        iterations=2, poly_n=5, poly_sigma=1.1, flags=0,
                    )
                    mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
                    motion = float(mag.mean()) / 10.0
                except Exception:
                    motion = 0.0

            results.append({
                't': ts,
                'brightness': brightness,
                'motion': motion,
                'edge_density': edge_density,
            })
            prev_gray = gray.copy()

        return results

    @staticmethod
    def _extract_frame(video_path: str, timestamp: float) -> Optional[np.ndarray]:
        """Extract one frame at timestamp via ffmpeg fast-seek."""
        try:
            r = subprocess.run(
                [
                    'ffmpeg', '-hwaccel', 'auto',
                    '-ss', f'{max(0.0, timestamp):.3f}',
                    '-i', str(video_path),
                    '-vframes', '1',
                    '-vf', 'scale=320:-1',
                    '-f', 'image2pipe', '-vcodec', 'mjpeg', '-',
                ],
                capture_output=True,
                timeout=15,
            )
            if r.returncode != 0 or not r.stdout:
                return None
            arr = np.frombuffer(r.stdout, np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            return None

    # -----------------------------------------------------------------------
    # Detectors
    # -----------------------------------------------------------------------

    @staticmethod
    def _detect_camera_moves(
        frame_data: list,
        dark_thresh: float,
        still_thresh: float,
        min_dur: float,
    ) -> List[DetectedSegment]:
        """Dark + no-motion sustained segments → camera raise/lower events."""
        return VideoPreprocessor._run_detector(
            frame_data,
            condition=lambda fd: (
                fd['brightness'] is not None
                and fd['brightness'] < dark_thresh
                and (fd['motion'] is None or fd['motion'] < still_thresh)
            ),
            problem_type='camera_raise_lower',
            min_dur=min_dur,
            confidence_fn=lambda fd: min(1.0, 1.0 - fd['brightness'] / max(dark_thresh, 1e-6)),
        )

    @staticmethod
    def _detect_pauses(
        frame_data: list,
        still_thresh: float,
        min_dur: float,
    ) -> List[DetectedSegment]:
        """Sustained near-zero motion → technical pause."""
        return VideoPreprocessor._run_detector(
            frame_data,
            condition=lambda fd: (
                fd['motion'] is not None and fd['motion'] < still_thresh
            ),
            problem_type='technical_pause',
            min_dur=min_dur,
            confidence_fn=lambda fd: 0.8,
        )

    @staticmethod
    def _detect_text_overlay(
        frame_data: list,
        edge_thresh: float,
        motion_max: float,
        min_dur: float,
    ) -> List[DetectedSegment]:
        """High edge density + low motion → on-screen text / UI overlay."""
        return VideoPreprocessor._run_detector(
            frame_data,
            condition=lambda fd: (
                fd['edge_density'] is not None
                and fd['edge_density'] > edge_thresh
                and (fd['motion'] is None or fd['motion'] < motion_max)
            ),
            problem_type='text_overlay',
            min_dur=min_dur,
            confidence_fn=lambda fd: min(1.0, fd['edge_density'] / max(edge_thresh, 1e-6)),
        )

    @staticmethod
    def _run_detector(
        frame_data: list,
        condition,
        problem_type: str,
        min_dur: float,
        confidence_fn,
    ) -> List[DetectedSegment]:
        """Generic state-machine detector: enter/exit segment on condition."""
        segments = []
        in_seg = False
        seg_start = 0.0
        last_confidence = 0.8

        for fd in frame_data:
            active = condition(fd)
            if active:
                if not in_seg:
                    in_seg = True
                    seg_start = fd['t']
                last_confidence = confidence_fn(fd)
            else:
                if in_seg:
                    dur = fd['t'] - seg_start
                    if dur >= min_dur:
                        segments.append(DetectedSegment(
                            start=seg_start, end=fd['t'],
                            problem_type=problem_type,
                            confidence=last_confidence,
                        ))
                    in_seg = False

        if in_seg and frame_data:
            last_t = frame_data[-1]['t']
            dur = last_t - seg_start
            if dur >= min_dur:
                segments.append(DetectedSegment(
                    start=seg_start, end=last_t,
                    problem_type=problem_type,
                    confidence=last_confidence,
                ))

        return segments

    # -----------------------------------------------------------------------
    # Range helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _segments_to_ranges(
        segments: List[DetectedSegment], total_duration: float
    ) -> List[Range]:
        """Merge overlapping detected segments into bad Range objects."""
        if not segments:
            return []

        sorted_segs = sorted(segments, key=lambda s: s.start)
        cur_start, cur_end = sorted_segs[0].start, sorted_segs[0].end
        merged = []

        for seg in sorted_segs[1:]:
            if seg.start <= cur_end + 0.2:
                cur_end = max(cur_end, seg.end)
            else:
                merged.append(Range(
                    start=max(0.0, cur_start),
                    end=min(total_duration, cur_end),
                    type='bad',
                ))
                cur_start, cur_end = seg.start, seg.end

        merged.append(Range(
            start=max(0.0, cur_start),
            end=min(total_duration, cur_end),
            type='bad',
        ))
        return merged

    @staticmethod
    def _invert_ranges(
        bad_ranges: List[Range], total_duration: float, min_good: float
    ) -> List[Range]:
        """Good ranges = complement of bad_ranges within [0, total_duration]."""
        if not bad_ranges:
            return [Range(start=0.0, end=total_duration, type='good')]

        good = []
        prev_end = 0.0

        for r in sorted(bad_ranges, key=lambda r: r.start):
            gap = r.start - prev_end
            if gap >= min_good:
                good.append(Range(start=prev_end, end=r.start, type='good'))
            prev_end = r.end

        tail = total_duration - prev_end
        if tail >= min_good:
            good.append(Range(start=prev_end, end=total_duration, type='good'))

        if not good:
            # Nothing survived — return whole video to avoid empty pipeline
            good.append(Range(start=0.0, end=total_duration, type='good'))

        return good
