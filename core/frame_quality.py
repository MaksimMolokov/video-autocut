"""Frame Quality + Motion (ТЗ §7.3–7.4): оценка качества и движения через OpenCV.

Сцена сэмплируется «бёрстами»: в нескольких точках берём по 3 ПОСЛЕДОВАТЕЛЬНЫХ
кадра. Только соседние кадры показывают реальные рывки камеры:
- скорость потока между соседними кадрами (px/кадр),
- ускорение потока и смену направления → дёрганость (jerk),
- падение резкости на движении → смаз (motion blur),
- экспозицию и интегральный quality_score 0..1.

Дёрганые сцены получают motion_type="shake", низкий stability_score и
штраф к качеству — планировщик их не берёт в монтаж.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

import config

log = logging.getLogger(__name__)

_N_BURSTS = 4          # точек сэмплирования по сцене
_BURST_LEN = 3         # последовательных кадров в точке
_JERK_ACCEL = 14.0     # px/кадр² (кадр ~640px): ускорение выше — рывок
_JERK_SPEED = 45.0     # px/кадр: быстрее — всё смазано даже без рывков


@dataclass
class QualityResult:
    quality_score: float      # 0..1 интегральная
    stability_score: float    # 0..1 (1 = стабильно)
    sharpness: float          # сырая дисперсия Лапласиана
    brightness: float         # средняя яркость 0..255
    motion: str               # static | slow | fast
    motion_type: str          # none | pan | zoom_in | zoom_out | rotate | shake
    keyframes: list[float]    # таймкоды лучших кадров сцены (для LLM/превью)
    jerkiness: float = 0.0    # 0..1 (1 = очень дёрганая)


def analyze_scene_quality(path: str, start: float, end: float) -> QualityResult:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return QualityResult(0, 0, 0, 0, "static", "none", [start + (end - start) / 2])

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        burst_times = np.linspace(start, end, _N_BURSTS + 2)[1:-1]

        bursts: list[list[np.ndarray]] = []   # серии последовательных серых кадров
        sharpness_vals: list[float] = []
        brightness_vals: list[float] = []
        frame_times: list[float] = []

        for t in burst_times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
            series = []
            for _ in range(_BURST_LEN):
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                h, w = frame.shape[:2]
                scale = 640 / max(h, w)
                if scale < 1:
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                series.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            if series:
                bursts.append(series)
                sharpness_vals.append(float(cv2.Laplacian(series[0], cv2.CV_64F).var()))
                brightness_vals.append(float(series[0].mean()))
                frame_times.append(float(t))

        if not bursts:
            return QualityResult(0, 0, 0, 0, "static", "none", [start + (end - start) / 2])

        sharpness = float(np.median(sharpness_vals))
        brightness = float(np.median(brightness_vals))

        motion, motion_type, stability, jerkiness = _motion_metrics(bursts, fps)

        # --- Интегральный quality_score ---
        q_sharp = min(sharpness / 150.0, 1.0)
        if brightness < config.DARK_MEAN_MAX:
            q_expo = max(brightness / config.DARK_MEAN_MAX, 0.1)
        elif brightness > config.BRIGHT_MEAN_MIN:
            q_expo = max((255 - brightness) / (255 - config.BRIGHT_MEAN_MIN), 0.1)
        else:
            q_expo = 1.0
        quality = 0.45 * q_sharp + 0.25 * q_expo + 0.30 * stability
        if motion_type == "shake":
            quality *= 0.5   # дёрганая сцена — жёсткий штраф (смаз, некрасиво)
        elif motion == "fast" and sharpness < config.SHARPNESS_MIN * 2.5:
            quality *= 0.7   # быстрый пролёт с motion blur — смазанная картинка
        quality = round(float(quality), 3)

        order = np.argsort(sharpness_vals)[::-1]
        keyframes = [frame_times[i] for i in order[:2]] or [start + (end - start) / 2]

        return QualityResult(quality, round(stability, 3), round(sharpness, 1),
                             round(brightness, 1), motion, motion_type,
                             sorted(keyframes), round(jerkiness, 3))
    finally:
        cap.release()


def _flow(prev: np.ndarray, curr: np.ndarray) -> np.ndarray | None:
    """Медианный вектор оптического потока между двумя кадрами (px/кадр)."""
    pts = cv2.goodFeaturesToTrack(prev, maxCorners=120, qualityLevel=0.01, minDistance=12)
    if pts is None or len(pts) < 8:
        return None
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, curr, pts, None)
    good = st.ravel() == 1
    if good.sum() < 8:
        return None
    return np.median((nxt[good] - pts[good]).reshape(-1, 2), axis=0)


def _motion_metrics(bursts: list[list[np.ndarray]],
                    fps: float) -> tuple[str, str, float, float]:
    """Скорость/ускорение потока между СОСЕДНИМИ кадрами → движение и дёрганость."""
    speeds: list[float] = []      # px/кадр
    accels: list[float] = []      # px/кадр² — резкие изменения вектора
    flips = 0                     # смены направления внутри бёрста
    pairs = 0
    radials: list[float] = []

    for series in bursts:
        vecs = []
        for a, b in zip(series, series[1:]):
            v = _flow(a, b)
            if v is not None:
                vecs.append(v)
                speeds.append(float(np.linalg.norm(v)))
                # радиальность для zoom-детекции: знак скалярного роста от центра
        for v1, v2 in zip(vecs, vecs[1:]):
            pairs += 1
            accels.append(float(np.linalg.norm(v2 - v1)))
            n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
            if n1 > 1.5 and n2 > 1.5 and float(np.dot(v1, v2)) < 0:
                flips += 1   # камера дёрнулась в обратную сторону
        # zoom: сравниваем поток в верхней/нижней половинах первого кадра пары
        if len(series) >= 2:
            r = _radial_component(series[0], series[1])
            if r is not None:
                radials.append(r)

    if not speeds:
        return "static", "none", 1.0, 0.0

    speed = float(np.median(speeds))          # px/кадр на ~640px
    accel = float(np.median(accels)) if accels else 0.0
    flip_ratio = flips / pairs if pairs else 0.0
    radial = float(np.median(radials)) if radials else 0.0
    speed_pps = speed * fps                   # px/сек для классификации темпа

    if speed_pps < 8:
        motion = "static"
    elif speed_pps < 120:
        motion = "slow"
    else:
        motion = "fast"

    # --- Дёрганость: ускорение + смены направления + запредельная скорость ---
    jerkiness = min(
        0.5 * min(accel / _JERK_ACCEL, 2.0)
        + 0.3 * min(flip_ratio / 0.4, 2.0)
        + 0.2 * min(speed / _JERK_SPEED, 2.0),
        2.0,
    ) / 2.0  # → 0..1

    if motion == "static":
        motion_type = "none"
    elif jerkiness >= 0.5:
        motion_type = "shake"
    elif abs(radial) > speed * 0.5 and speed > 1.0:
        motion_type = "zoom_in" if radial > 0 else "zoom_out"
    else:
        motion_type = "pan"

    stability = float(np.clip(1.0 - jerkiness, 0.0, 1.0))
    return motion, motion_type, stability, float(jerkiness)


def _radial_component(prev: np.ndarray, curr: np.ndarray) -> float | None:
    """Медианная радиальная составляющая потока (>0 = zoom in)."""
    pts = cv2.goodFeaturesToTrack(prev, maxCorners=100, qualityLevel=0.01, minDistance=14)
    if pts is None or len(pts) < 8:
        return None
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, curr, pts, None)
    good = st.ravel() == 1
    if good.sum() < 8:
        return None
    p0 = pts[good].reshape(-1, 2)
    flow = (nxt[good] - pts[good]).reshape(-1, 2)
    center = np.array(prev.shape[::-1], dtype=float) / 2
    rel = p0 - center
    rel_norm = rel / (np.linalg.norm(rel, axis=1, keepdims=True) + 1e-6)
    return float(np.median(np.sum(flow * rel_norm, axis=1)))
