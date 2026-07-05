"""Умный кроп (ТЗ §17): окно кропа смещается к людям, чтобы их не резать.

Двухуровневая детекция на кадрах сегмента:
1. лица (Haar cascade) — крупные планы, люди лицом к камере;
2. силуэты людей (HOG person detector) — дроновые/дальние планы,
   люди спиной или сверху, где лиц не видно.
Центр внимания — взвешенный по площади. Никого нет → центральный кроп.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

log = logging.getLogger(__name__)

_CASCADE = None
_HOG = None


def _cascade() -> cv2.CascadeClassifier:
    global _CASCADE
    if _CASCADE is None:
        _CASCADE = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _CASCADE


def _hog() -> cv2.HOGDescriptor:
    global _HOG
    if _HOG is None:
        _HOG = cv2.HOGDescriptor()
        _HOG.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return _HOG


def crop_window(src_w: int, src_h: int, target_w: int, target_h: int,
                focus: tuple[float, float] | None = None) -> tuple[int, int, int, int]:
    """Прямоугольник кропа (cw, ch, x, y) в координатах исходника
    под целевой аспект. focus — нормированный центр внимания (0..1, 0..1),
    None = центр кадра."""
    ar_t = target_w / target_h
    ar_s = src_w / src_h
    if ar_s > ar_t:          # источник шире цели — режем бока
        ch = src_h
        cw = min(int(round(src_h * ar_t)), src_w)
    else:                    # источник выше цели — режем верх/низ
        cw = src_w
        ch = min(int(round(src_w / ar_t)), src_h)
    fx, fy = focus if focus else (0.5, 0.5)
    x = int(round(fx * src_w - cw / 2))
    y = int(round(fy * src_h - ch / 2))
    x = max(0, min(x, src_w - cw))
    y = max(0, min(y, src_h - ch))
    # чётные размеры для yuv420p
    return cw - cw % 2, ch - ch % 2, x, y


def crop_rect_norm(src_w: int, src_h: int, target_w: int, target_h: int,
                   focus: tuple[float, float] | None = None
                   ) -> tuple[float, float, float, float]:
    """Нормированный (0..1) прямоугольник окна кропа (x0, y0, x1, y1) —
    для отрисовки рамки предпросмотра кадрирования (ТЗ §17.5)."""
    cw, ch, x, y = crop_window(src_w, src_h, target_w, target_h, focus)
    return (round(x / src_w, 4), round(y / src_h, 4),
            round((x + cw) / src_w, 4), round((y + ch) / src_h, 4))


def find_focus(video_path: str, start: float, end: float,
               n_samples: int = 3) -> tuple[float, float] | None:
    """Взвешенный центр лиц на кадрах сегмента; None, если лиц нет."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    try:
        face_pts: list[tuple[float, float, float]] = []   # (fx, fy, вес)
        body_pts: list[tuple[float, float, float]] = []
        for t in np.linspace(start, end, n_samples + 2)[1:-1]:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            scale = 640 / max(h, w)
            small = cv2.resize(frame, (int(w * scale), int(h * scale)))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            sh, sw = small.shape[:2]

            # Уровень 1: лица (крупные планы)
            faces = _cascade().detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
            for (fx, fy, fw, fh) in faces:
                face_pts.append(((fx + fw / 2) / sw, (fy + fh / 2) / sh, float(fw * fh)))

            # Уровень 2: силуэты людей (дрон, спина, дальний план)
            if len(faces) == 0:
                rects, weights = _hog().detectMultiScale(
                    small, winStride=(8, 8), padding=(8, 8), scale=1.05)
                for (bx, by, bw, bh), conf in zip(rects, np.ravel(weights)):
                    if conf < 0.3:
                        continue
                    body_pts.append(((bx + bw / 2) / sw, (by + bh / 2) / sh,
                                     float(bw * bh) * float(conf)))

        pts = face_pts or body_pts   # лица приоритетнее силуэтов
        if not pts:
            return None
        wsum = sum(p[2] for p in pts)
        return (round(float(sum(p[0] * p[2] for p in pts) / wsum), 4),
                round(float(sum(p[1] * p[2] for p in pts) / wsum), 4))
    except Exception as e:  # детектор не должен ронять рендер
        log.warning("find_focus(%s): %s", video_path, e)
        return None
    finally:
        cap.release()
