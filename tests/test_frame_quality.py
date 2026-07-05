"""Frame Quality: метрики качества, движение, ключевые кадры, устойчивость."""
from core.frame_quality import QualityResult, analyze_scene_quality


def test_quality_on_synthetic(synthetic_video):
    q = analyze_scene_quality(str(synthetic_video), 0.0, 3.0)
    assert isinstance(q, QualityResult)
    assert 0.0 <= q.quality_score <= 1.0
    assert 0.0 <= q.stability_score <= 1.0
    assert q.sharpness > 0            # testsrc2 — резкий паттерн
    assert 0 <= q.brightness <= 255
    assert q.motion in ("static", "slow", "fast")
    assert q.motion_type in ("none", "pan", "zoom_in", "zoom_out", "rotate", "shake")
    # ключевые кадры внутри сцены
    assert q.keyframes
    for t in q.keyframes:
        assert 0.0 <= t <= 3.0


def test_quality_missing_file():
    q = analyze_scene_quality("/nonexistent.mp4", 0.0, 3.0)
    assert q.quality_score == 0
    assert q.keyframes  # всегда есть хотя бы средняя точка


def test_static_smptebars_scene(synthetic_video):
    """smptebars — полностью статичная сцена (3–6 c)."""
    q = analyze_scene_quality(str(synthetic_video), 3.2, 5.8)
    assert q.motion == "static"
    assert q.motion_type == "none"
    assert q.stability_score >= 0.9


def test_shaky_video_detected(shaky_video):
    """Дёрганая камера (случайные рывки кропа) → shake, низкая стабильность,
    жёсткий штраф к качеству."""
    q = analyze_scene_quality(str(shaky_video), 0.2, 3.8)
    assert q.motion_type == "shake"
    assert q.jerkiness >= 0.5
    assert q.stability_score <= 0.5
    assert q.quality_score < 0.55  # штраф ×0.5 применён


def test_smooth_pan_not_shake(smooth_pan_video):
    """Плавная панорама — НЕ дёрганая (тип может быть pan/zoom из-за
    движущихся элементов testsrc2, главное — не shake)."""
    q = analyze_scene_quality(str(smooth_pan_video), 0.2, 3.8)
    assert q.motion_type != "shake"
    assert q.jerkiness < 0.5
    assert q.stability_score >= 0.55
