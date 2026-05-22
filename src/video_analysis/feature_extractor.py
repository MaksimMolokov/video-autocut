"""
Video Feature Extractor - извлечение признаков из видеофрагментов
Использует ffmpeg (fast seek) + OpenCV для анализа visual features.
"""

import cv2
import subprocess
import numpy as np
import logging
from dataclasses import dataclass, asdict
from typing import Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ClipFeatures:
    """
    Признаки видеофрагмента
    Все scores нормализованы в диапазон [0.0, 1.0]
    """
    # Базовые характеристики
    start_time: float
    end_time: float
    duration: float

    # Визуальные признаки
    sharpness_score: float = 0.0        # Резкость (Laplacian variance)
    brightness_score: float = 0.0       # Яркость (средняя по всем кадрам)
    contrast_score: float = 0.0         # Контраст (std яркости)

    # Движение и стабильность
    motion_score: float = 0.0           # Количество движения (optical flow magnitude)
    camera_stability_score: float = 0.0 # Стабильность камеры (inverse of motion variance)

    # Сложность и детали
    visual_complexity_score: float = 0.0  # Насыщенность деталями (edge density)
    scene_change_score: float = 0.0       # Наличие смены сцены внутри клипа

    # Цвет
    color_saturation_score: float = 0.0  # Насыщенность цвета
    color_diversity_score: float = 0.0   # Разнообразие цветов (std hue)

    # Композитные признаки (вычисляются из базовых)
    action_score: float = 0.0           # Динамика: motion + low_stability
    calm_score: float = 0.0             # Спокойствие: high_stability + low_motion
    technical_quality_score: float = 0.0 # Общее техническое качество

    # Будет заполнено позже при diversity analysis
    uniqueness_score: float = 0.0       # Отличие от других клипов
    interest_score: float = 0.0         # Composite "interestingness" — color richness + light quality + complexity
    face_center_x: float = 0.5          # Normalized face/subject horizontal center for smart reframing (0=left, 1=right)

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        """Create from dictionary"""
        return cls(**data)


class VideoFeatureExtractor:
    """
    Извлечение признаков из видеофрагментов.
    Использует ffmpeg fast-seek для извлечения кадров (быстро на сетевых дисках и 4K).
    """

    SHARPNESS_MAX = 1000.0
    MOTION_MAX = 50.0
    EDGE_DENSITY_MAX = 0.3
    # Max width for analysis after resize
    ANALYSIS_WIDTH = 640

    @staticmethod
    def _extract_frame_ffmpeg(video_path: str, timestamp: float, width: int = 320) -> Optional[np.ndarray]:
        """
        Быстрое извлечение одного кадра через ffmpeg -ss (keyframe seek).
        Намного быстрее OpenCV для 4K видео на сетевых дисках.
        """
        try:
            result = subprocess.run(
                [
                    'ffmpeg', '-hwaccel', 'auto',
                    '-ss', f'{max(0.0, timestamp):.3f}',
                    '-i', str(video_path),
                    '-vframes', '1',
                    '-vf', f'scale={width}:-1',
                    '-f', 'image2pipe', '-vcodec', 'mjpeg', '-'
                ],
                capture_output=True,
                timeout=20
            )
            if result.returncode != 0 or not result.stdout:
                return None
            nparr = np.frombuffer(result.stdout, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            return frame
        except Exception as e:
            logger.debug(f"ffmpeg frame extraction failed at {timestamp:.1f}s: {e}")
            return None

    @staticmethod
    def extract_features(
        video_path: str,
        start_time: float,
        end_time: float,
        sample_rate: int = 3,   # kept for API compatibility, not used
        num_samples: int = 3,   # frames to extract via ffmpeg fast-seek
    ) -> Optional[ClipFeatures]:
        """
        Извлечь признаки из видеофрагмента через ffmpeg fast-seek.
        Намного быстрее OpenCV для 4K видео на сетевых дисках.
        Results are cached in SQLite to skip re-analysis on repeated runs.
        """
        try:
            duration = end_time - start_time
            if duration <= 0:
                return None

            # Check global SQLite cache before doing expensive extraction
            try:
                from src.analysis_cache import get_cache
                _cache = get_cache()
                if _cache is not None:
                    cached = _cache.get(video_path, start_time, end_time)
                    if cached is not None:
                        logger.debug(
                            f"Cache hit: {Path(video_path).name} "
                            f"[{start_time:.1f}-{end_time:.1f}]"
                        )
                        return cached
            except Exception:
                _cache = None

            # Sample timestamps: start, middle, end of clip
            timestamps = [
                start_time + duration * i / max(num_samples - 1, 1)
                for i in range(num_samples)
            ]

            frame_features = []
            prev_gray = None

            for ts in timestamps:
                frame = VideoFeatureExtractor._extract_frame_ffmpeg(
                    video_path, ts, width=320
                )
                if frame is None:
                    continue

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                f_features = VideoFeatureExtractor._extract_frame_features(frame, gray, prev_gray)
                frame_features.append(f_features)
                prev_gray = gray.copy()

            if not frame_features:
                logger.warning(f"No features extracted for {Path(video_path).name} [{start_time:.1f}-{end_time:.1f}]")
                return None

            clip_features = VideoFeatureExtractor._aggregate_features(
                frame_features, start_time, end_time, duration
            )
            clip_features = VideoFeatureExtractor.compute_composite_scores(clip_features)

            # Detect face center on middle frame for smart reframing
            _mid_idx = len(timestamps) // 2
            _mid_frame = VideoFeatureExtractor._extract_frame_ffmpeg(
                video_path, timestamps[_mid_idx], width=320
            )
            if _mid_frame is not None:
                clip_features.face_center_x = VideoFeatureExtractor.detect_face_center(_mid_frame)

            logger.debug(
                f"Extracted features for {Path(video_path).name} "
                f"[{start_time:.1f}-{end_time:.1f}s]: "
                f"motion={clip_features.motion_score:.2f} "
                f"stability={clip_features.camera_stability_score:.2f} "
                f"sharpness={clip_features.sharpness_score:.2f} "
                f"interest={clip_features.interest_score:.2f}"
            )

            # Store in cache for future runs
            try:
                if _cache is not None:
                    _cache.set(video_path, start_time, end_time, clip_features)
            except Exception:
                pass

            return clip_features

        except Exception as e:
            logger.error(f"Error extracting features from {video_path}: {e}")
            return None

    @staticmethod
    def _extract_frame_features(
        frame: np.ndarray,
        gray: np.ndarray,
        prev_gray: Optional[np.ndarray]
    ) -> dict:
        """
        Извлечь признаки из одного кадра

        Returns:
            Dictionary with frame features
        """
        features = {}

        # Sharpness (Laplacian variance)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        features['sharpness'] = laplacian.var()

        # Brightness (mean luminance)
        features['brightness'] = gray.mean() / 255.0

        # Contrast (std luminance)
        features['contrast'] = gray.std() / 128.0  # Normalize to ~[0, 1]

        # Visual complexity (edge density)
        edges = cv2.Canny(gray, 50, 150)
        features['edge_density'] = edges.sum() / (edges.size * 255.0)

        # Color saturation
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        features['color_saturation'] = hsv[:, :, 1].mean() / 255.0

        # Color diversity (std of hue)
        features['color_diversity'] = hsv[:, :, 0].std() / 90.0  # Hue is 0-180

        # Motion (optical flow) - only if prev_gray available
        if prev_gray is not None:
            try:
                flow = cv2.calcOpticalFlowFarneback(
                    prev_gray, gray,
                    None,
                    pyr_scale=0.5,
                    levels=3,
                    winsize=15,
                    iterations=3,
                    poly_n=5,
                    poly_sigma=1.2,
                    flags=0
                )
                mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                features['motion'] = mag.mean()
            except Exception as e:
                logger.debug(f"Optical flow failed: {e}")
                features['motion'] = 0.0
        else:
            features['motion'] = 0.0

        return features

    @staticmethod
    def _aggregate_features(
        frame_features: list,
        start_time: float,
        end_time: float,
        duration: float
    ) -> ClipFeatures:
        """
        Агрегировать признаки кадров в признаки клипа

        Используем mean для большинства признаков
        """
        # Extract arrays for each feature
        sharpness_arr = np.array([f['sharpness'] for f in frame_features])
        brightness_arr = np.array([f['brightness'] for f in frame_features])
        contrast_arr = np.array([f['contrast'] for f in frame_features])
        motion_arr = np.array([f['motion'] for f in frame_features])
        edge_density_arr = np.array([f['edge_density'] for f in frame_features])
        color_sat_arr = np.array([f['color_saturation'] for f in frame_features])
        color_div_arr = np.array([f['color_diversity'] for f in frame_features])

        # Normalize scores to [0, 1]
        sharpness_norm = np.clip(
            sharpness_arr.mean() / VideoFeatureExtractor.SHARPNESS_MAX,
            0.0, 1.0
        )

        motion_norm = np.clip(
            motion_arr.mean() / VideoFeatureExtractor.MOTION_MAX,
            0.0, 1.0
        )

        # Camera stability = inverse of motion variance
        motion_variance = motion_arr.var() if len(motion_arr) > 1 else 0.0
        stability_norm = 1.0 - np.clip(motion_variance / (VideoFeatureExtractor.MOTION_MAX / 2), 0.0, 1.0)

        # Visual complexity
        complexity_norm = np.clip(
            edge_density_arr.mean() / VideoFeatureExtractor.EDGE_DENSITY_MAX,
            0.0, 1.0
        )

        # Scene change detection (std of brightness)
        scene_change = np.clip(brightness_arr.std() / 0.3, 0.0, 1.0)

        return ClipFeatures(
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            sharpness_score=float(sharpness_norm),
            brightness_score=float(brightness_arr.mean()),
            contrast_score=float(contrast_arr.mean()),
            motion_score=float(motion_norm),
            camera_stability_score=float(stability_norm),
            visual_complexity_score=float(complexity_norm),
            scene_change_score=float(scene_change),
            color_saturation_score=float(color_sat_arr.mean()),
            color_diversity_score=float(color_div_arr.mean())
        )

    @staticmethod
    def compute_composite_scores(features: ClipFeatures) -> ClipFeatures:
        """
        Вычислить композитные признаки из базовых

        action_score: высокое движение + низкая стабильность
        calm_score: высокая стабильность + низкое движение
        technical_quality_score: резкость + яркость + контраст
        """
        # Action score: motion + instability
        features.action_score = np.clip(
            features.motion_score * 0.7 + (1.0 - features.camera_stability_score) * 0.3,
            0.0, 1.0
        )

        # Calm score: stability + low motion
        features.calm_score = np.clip(
            features.camera_stability_score * 0.7 + (1.0 - features.motion_score) * 0.3,
            0.0, 1.0
        )

        # Technical quality: sharpness + brightness + contrast
        # Penalize very dark or very bright clips
        brightness_quality = 1.0 - abs(features.brightness_score - 0.5) * 2.0  # Peak at 0.5
        features.technical_quality_score = np.clip(
            (
                features.sharpness_score * 1.0 +
                brightness_quality * 0.8 +
                features.contrast_score * 0.6
            ) / 2.4,
            0.0, 1.0
        )

        # Interest score
        _brightness_quality = 1.0 - abs(features.brightness_score - 0.45) * 2.0
        _color_richness = features.color_saturation_score * 0.5 + features.color_diversity_score * 0.5
        _motion_contrib = min(features.motion_score, 0.6) / 0.6
        features.interest_score = float(np.clip(
            _brightness_quality * 0.30 +
            _color_richness * 0.30 +
            features.visual_complexity_score * 0.25 +
            _motion_contrib * 0.15,
            0.0, 1.0,
        ))

        return features

    @staticmethod
    def detect_face_center(frame: np.ndarray) -> float:
        """Return normalized horizontal center of largest detected face, or 0.5 if none."""
        try:
            import cv2
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            cascade = cv2.CascadeClassifier(cascade_path)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
            if len(faces) == 0:
                return 0.5
            largest = max(faces, key=lambda f: f[2] * f[3])
            x, _, w, _ = largest
            return float(np.clip((x + w / 2) / max(frame.shape[1], 1), 0.0, 1.0))
        except Exception:
            return 0.5

    @staticmethod
    def check_opencv_available() -> bool:
        """Check if OpenCV is available"""
        try:
            import cv2
            return True
        except ImportError:
            return False


if __name__ == "__main__":
    # Test feature extractor
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.video_analysis.feature_extractor <video_path> [start] [end]")
        print("\nExample: python -m src.video_analysis.feature_extractor video.mp4 10 15")
        sys.exit(1)

    video_path = sys.argv[1]
    start = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    end = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0

    print(f"Extracting features from {video_path} [{start}-{end}]...")

    features = VideoFeatureExtractor.extract_features(video_path, start, end)

    if features:
        print(f"\n✓ Features extracted successfully:\n")
        print(f"  Duration: {features.duration:.1f}s")
        print(f"  Sharpness: {features.sharpness_score:.2f}")
        print(f"  Brightness: {features.brightness_score:.2f}")
        print(f"  Contrast: {features.contrast_score:.2f}")
        print(f"  Motion: {features.motion_score:.2f}")
        print(f"  Stability: {features.camera_stability_score:.2f}")
        print(f"  Visual Complexity: {features.visual_complexity_score:.2f}")
        print(f"  Color Saturation: {features.color_saturation_score:.2f}")
        print(f"  Action Score: {features.action_score:.2f}")
        print(f"  Calm Score: {features.calm_score:.2f}")
        print(f"  Technical Quality: {features.technical_quality_score:.2f}")
    else:
        print("✗ Failed to extract features")
        sys.exit(1)
