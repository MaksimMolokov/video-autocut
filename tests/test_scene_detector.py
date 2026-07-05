"""Scene Detector: детекция склеек, нормализация коротких/длинных сцен."""
import config
from core.scene_detector import _normalize, detect_scenes


def test_detect_on_synthetic(synthetic_video):
    """3 контрастные сцены по 3с должны определиться как >= 2 склейки."""
    ranges = detect_scenes(synthetic_video, 9.0)
    assert len(ranges) >= 2
    # покрытие: сцены внутри файла, начала < концов
    for start, end in ranges:
        assert 0 <= start < end <= 9.5
        assert end - start >= config.MIN_SCENE_LEN_SEC


def test_detect_missing_file_falls_back(tmp_path):
    """Нечитаемый файл → одна сцена на всю длительность (fallback)."""
    ranges = detect_scenes(tmp_path / "nope.mp4", 10.0)
    assert ranges == [(0.0, 10.0)]


def test_detect_zero_duration(tmp_path):
    assert detect_scenes(tmp_path / "nope.mp4", 0.0) == []


def test_normalize_drops_short():
    assert _normalize([(0.0, 0.5)]) == []


def test_normalize_keeps_normal():
    assert _normalize([(0.0, 5.0)]) == [(0.0, 5.0)]


def test_normalize_splits_long():
    long_len = config.MAX_SCENE_LEN_SEC * 2.5
    parts = _normalize([(0.0, long_len)])
    assert len(parts) == 3
    # непрерывность и укладывание в лимит
    assert parts[0][0] == 0.0
    assert abs(parts[-1][1] - long_len) < 0.01
    for s, e in parts:
        assert e - s <= config.MAX_SCENE_LEN_SEC + 0.01
