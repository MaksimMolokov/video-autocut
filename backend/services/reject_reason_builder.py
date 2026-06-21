"""reject_reason_builder — structured reject reasons per preset rules (VI2-013)."""
from __future__ import annotations

from typing import List, Optional


def build_reject_reasons(frag: dict, preset_settings: Optional[dict] = None) -> List[str]:
    """
    Return a list of human-readable reject reasons for frag based on preset rules.
    Empty list means the fragment is acceptable.

    frag keys used:
        sharpness, camera_shake, brightness, is_blurry, is_duplicate,
        camera_motion_type, scene_tags, quality_score,
        eyes_open_score, pose_quality_score, bad_crop,
        end_s, start_s
    """
    ps   = preset_settings or {}
    sel  = ps.get("segment_selection", {})
    clip = ps.get("clip_selection", {})

    reasons: List[str] = []

    sharpness    = float(frag.get("sharpness", frag.get("blur_score", 0.5)))
    shake        = float(frag.get("camera_shake", 0.0))
    brightness   = float(frag.get("brightness", 0.5))
    quality      = float(frag.get("quality_score", 0.5))
    duration     = float(frag.get("end_s", 0) - frag.get("start_s", 0))
    cam_motion   = frag.get("camera_motion_type", "static")

    # ── Basic quality thresholds ──────────────────────────────────────────
    if frag.get("is_blurry") or sharpness < 0.10:
        reasons.append(f"Размытый кадр (резкость {sharpness:.2f})")

    if brightness < 0.05:
        reasons.append(f"Слишком тёмный кадр (яркость {brightness:.2f})")
    elif brightness > 0.95:
        reasons.append(f"Засветка кадра (яркость {brightness:.2f})")

    if shake > 0.85:
        reasons.append(f"Сильная тряска камеры (shake {shake:.2f})")

    if frag.get("is_duplicate"):
        reasons.append("Дубль другого фрагмента")

    # ── Preset min_quality check ──────────────────────────────────────────
    min_q = sel.get("min_scores", {}).get("quality_score",
            clip.get("min_quality_score", 0.0))
    if min_q > 0 and quality < min_q:
        reasons.append(f"Низкое качество ({quality:.2f} < {min_q:.2f})")

    min_brightness = sel.get("min_scores", {}).get("brightness", 0.0)
    if min_brightness > 0 and brightness < min_brightness:
        reasons.append(f"Яркость ниже нормы пресета ({brightness:.2f} < {min_brightness:.2f})")

    min_stability = sel.get("min_scores", {}).get("stability", 0.0)
    stability = max(0.0, 1.0 - shake)
    if min_stability > 0 and stability < min_stability:
        reasons.append(f"Нестабильный кадр ({stability:.2f} < {min_stability:.2f})")

    # ── Duration check ────────────────────────────────────────────────────
    min_dur = clip.get("segment_min_duration", 0.0)
    max_dur = clip.get("segment_max_duration", 999.0)
    if min_dur > 0 and duration < min_dur:
        reasons.append(f"Слишком короткий ({duration:.1f}с < {min_dur:.1f}с)")
    if max_dur < 999 and duration > max_dur:
        reasons.append(f"Слишком длинный ({duration:.1f}с > {max_dur:.1f}с)")

    # ── Camera motion reject list ─────────────────────────────────────────
    rejected_motion = set(sel.get("rejected_camera_motion", []))
    if cam_motion and cam_motion in rejected_motion:
        reasons.append(f"Тип движения камеры запрещён пресетом ({cam_motion})")

    # ── Pose/Body crop issues ─────────────────────────────────────────────
    bad_crop = frag.get("bad_crop", False)
    if bad_crop:
        reasons.append("Плохой кроп тела (голова или ноги обрезаны)")

    pose_q = float(frag.get("pose_quality_score", 1.0))
    if pose_q < 0.25:
        reasons.append(f"Неудобная поза / неудачный ракурс (pose={pose_q:.2f})")

    # ── Eye state check (only for presets that care) ──────────────────────
    min_eyes = sel.get("min_scores", {}).get("eyes_open_score", 0.0)
    eyes_q   = float(frag.get("eyes_open_score", 1.0))
    if min_eyes > 0 and eyes_q < min_eyes:
        reasons.append(f"Закрытые глаза (eye_score={eyes_q:.2f} < {min_eyes:.2f})")

    return reasons


def primary_reject_reason(frag: dict, preset_settings: Optional[dict] = None) -> Optional[str]:
    """Return the most important single reject reason, or None if acceptable."""
    reasons = build_reject_reasons(frag, preset_settings)
    return reasons[0] if reasons else None
