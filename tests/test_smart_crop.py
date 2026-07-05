"""Smart Crop: математика окна кропа, лица, фолбэк на центр."""
from core.smart_crop import crop_window, find_focus


def test_horizontal_to_vertical_center():
    """16:9 → 9:16 без фокуса: окно по центру, аспект соблюдён."""
    cw, ch, x, y = crop_window(1920, 1080, 1080, 1920)
    assert ch == 1080                       # вся высота
    assert abs(cw / ch - 1080 / 1920) < 0.01
    assert x == (1920 - cw) // 2 and y == 0  # центр


def test_focus_shifts_window():
    """Лицо слева → окно уезжает влево, лицо не срезано."""
    cw, ch, x, _ = crop_window(1920, 1080, 1080, 1920, focus=(0.15, 0.5))
    face_px = 0.15 * 1920
    assert x <= face_px <= x + cw           # лицо внутри окна
    assert x < (1920 - cw) // 2             # окно левее центра


def test_focus_clamped_to_frame():
    """Фокус у самого края — окно не выходит за кадр."""
    cw, ch, x, y = crop_window(1920, 1080, 1080, 1920, focus=(0.99, 0.5))
    assert 0 <= x <= 1920 - cw
    cw, ch, x, y = crop_window(1920, 1080, 1080, 1920, focus=(0.01, 0.5))
    assert x == 0


def test_vertical_to_horizontal():
    """9:16 → 16:9: режется верх/низ, фокус двигает по вертикали."""
    cw, ch, x, y = crop_window(1080, 1920, 1920, 1080, focus=(0.5, 0.2))
    assert cw == 1080
    assert abs(cw / ch - 1920 / 1080) < 0.02
    assert y < (1920 - ch) // 2             # окно выше центра


def test_same_aspect_full_frame():
    cw, ch, x, y = crop_window(1920, 1080, 960, 540)
    assert (cw, ch, x, y) == (1920, 1080, 0, 0)


def test_even_dimensions():
    """Размеры окна чётные (требование yuv420p)."""
    cw, ch, _, _ = crop_window(1919, 1079, 1080, 1920)
    assert cw % 2 == 0 and ch % 2 == 0


def test_crop_rect_norm():
    """Нормированный прямоугольник для превью кадрирования (ТЗ §17.5)."""
    from core.smart_crop import crop_rect_norm
    x0, y0, x1, y1 = crop_rect_norm(1920, 1080, 1080, 1920)  # 16:9 → 9:16
    assert 0 <= x0 < x1 <= 1 and (y0, y1) == (0.0, 1.0)
    # аспект окна соответствует цели
    w, h = (x1 - x0) * 1920, (y1 - y0) * 1080
    assert abs(w / h - 1080 / 1920) < 0.01
    # фокус слева сдвигает окно
    fx0, _, fx1, _ = crop_rect_norm(1920, 1080, 1080, 1920, focus=(0.2, 0.5))
    assert fx0 < x0


def test_find_focus_no_faces(synthetic_video):
    """На синтетике лиц нет → None → рендер падёт в центральный кроп."""
    assert find_focus(str(synthetic_video), 0.5, 2.5) is None


def test_find_focus_missing_file():
    assert find_focus("/nonexistent.mp4", 0, 1) is None


def test_segment_focus_cascade(monkeypatch, synthetic_video):
    """Каскад фокуса: CV → subject от LLM → None (центр)."""
    from core import renderer as r
    from core.models import PlanSegment, Scene

    seg = PlanSegment(scene_id="s", order=0, src_start=0, src_end=2,
                      slot="main", crop="smart")
    scene = Scene(video_id="v", video_path=str(synthetic_video), start=0, end=2)

    # 1) CV нашёл лицо — его позиция приоритетна
    monkeypatch.setattr(r, "find_focus", lambda *a, **k: (0.2, 0.4))
    scene.subject_x, scene.subject_y = 0.8, 0.8
    assert r._segment_focus(scene, seg) == (0.2, 0.4)

    # 2) CV пусто — берём позицию объекта от LLM
    monkeypatch.setattr(r, "find_focus", lambda *a, **k: None)
    assert r._segment_focus(scene, seg) == (0.8, 0.8)

    # 3) CV пусто и LLM говорит «центр» — None (центральный кроп)
    scene.subject_x, scene.subject_y = 0.5, 0.5
    assert r._segment_focus(scene, seg) is None

    # 4) crop=center — детекция вообще не запускается
    seg.crop = "center"
    scene.subject_x = 0.9
    assert r._segment_focus(scene, seg) is None
