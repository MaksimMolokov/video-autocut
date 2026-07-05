"""LLM Analyzer: лояльный JSON-парсер, нормализация полей, заполнение сцены.

Сетевые вызовы замоканы; живой LM Studio не требуется.
"""
import json
from pathlib import Path

from core.llm_analyzer import LLMAnalyzer, _parse_json_lenient
from core.models import Scene


GOOD = {"scene_description": "Кафе", "objects": ["стол"], "people_count": 2,
        "emotions": ["радость"], "composition": "средний план", "lighting": "тёплый",
        "aesthetic_score": 0.8, "scene_type": "food", "recommended_slot": "main",
        "tags": ["food", "cafe"], "usable_for_edit": True}


# --- _parse_json_lenient ---

def test_parse_clean():
    assert _parse_json_lenient(json.dumps(GOOD)) == GOOD


def test_parse_trailing_whitespace_flood():
    """Кейс gemma-3: валидный JSON + километры пробелов до лимита токенов."""
    assert _parse_json_lenient(json.dumps(GOOD) + "\n" * 500 + " " * 500) == GOOD


def test_parse_markdown_fenced():
    content = "```json\n" + json.dumps(GOOD) + "\n```"
    assert _parse_json_lenient(content) == GOOD


def test_parse_with_prose_around():
    content = "Вот анализ:\n" + json.dumps(GOOD) + "\nНадеюсь, помог!"
    assert _parse_json_lenient(content) == GOOD


def test_parse_truncated_mid_key():
    """Обрыв генерации посреди ключа."""
    content = '{"scene_description": "Бар", "objects": ["стойка"], "re'
    data = _parse_json_lenient(content)
    assert data is not None
    assert data["scene_description"] == "Бар"


def test_parse_truncated_mid_array():
    data = _parse_json_lenient('{"tags": ["food", "cafe"')
    assert data is None or "tags" in data  # починили или честно отказались


def test_parse_garbage_returns_none():
    assert _parse_json_lenient("это вообще не json") is None
    assert _parse_json_lenient("") is None


# --- fill_scene ---

def _scene() -> Scene:
    return Scene(video_id="v", video_path="/x.mp4", start=0, end=3)


def test_fill_scene_success(monkeypatch, tmp_path):
    llm = LLMAnalyzer()
    monkeypatch.setattr(llm, "analyze_frame", lambda p: dict(GOOD))
    s = _scene()
    assert llm.fill_scene(s, tmp_path / "f.jpg")
    assert s.llm_status == "done"
    assert s.description == "Кафе" and s.scene_type == "food"
    assert s.people_count == 2 and s.aesthetic_score == 0.8
    assert s.recommended_slot == "main"


def test_fill_scene_normalizes_10_scale(monkeypatch, tmp_path):
    """Модель поставила 8 по 10-балльной шкале → 0.8."""
    data = dict(GOOD, aesthetic_score=8)
    llm = LLMAnalyzer()
    monkeypatch.setattr(llm, "analyze_frame", lambda p: data)
    s = _scene()
    llm.fill_scene(s, tmp_path / "f.jpg")
    assert s.aesthetic_score == 0.8


def test_fill_scene_not_usable_tag(monkeypatch, tmp_path):
    data = dict(GOOD, usable_for_edit=False)
    llm = LLMAnalyzer()
    monkeypatch.setattr(llm, "analyze_frame", lambda p: data)
    s = _scene()
    llm.fill_scene(s, tmp_path / "f.jpg")
    assert "not-usable" in s.tags


def test_fill_scene_failure(monkeypatch, tmp_path):
    llm = LLMAnalyzer()
    monkeypatch.setattr(llm, "analyze_frame", lambda p: None)
    s = _scene()
    assert not llm.fill_scene(s, tmp_path / "f.jpg")
    assert s.llm_status == "failed"


# --- is_available / выбор модели ---

class _FakeModel:
    def __init__(self, id):
        self.id = id


class _FakeModels:
    def __init__(self, ids):
        self._ids = ids

    def list(self):
        class R:
            pass
        r = R()
        r.data = [_FakeModel(i) for i in self._ids]
        return r


def test_is_available_exact_model(monkeypatch):
    llm = LLMAnalyzer(model="qwen/qwen3-vl-8b")
    monkeypatch.setattr(llm.client, "models", _FakeModels(["qwen/qwen3-vl-8b"]))
    assert llm.is_available()
    assert llm.model == "qwen/qwen3-vl-8b"


def test_is_available_fallback_to_vision(monkeypatch):
    llm = LLMAnalyzer(model="qwen/qwen3-vl-8b")
    monkeypatch.setattr(llm.client, "models",
                        _FakeModels(["google/gemma-3-12b", "microsoft/phi-4"]))
    assert llm.is_available()
    assert llm.model == "google/gemma-3-12b"


def test_is_available_no_vision_model(monkeypatch):
    llm = LLMAnalyzer(model="qwen/qwen3-vl-8b")
    monkeypatch.setattr(llm.client, "models", _FakeModels(["microsoft/phi-4"]))
    assert not llm.is_available()


def test_is_available_connection_error(monkeypatch):
    from openai import APIConnectionError
    import httpx

    llm = LLMAnalyzer(base_url="http://localhost:9/v1")

    def boom():
        raise APIConnectionError(request=httpx.Request("GET", "http://localhost:9/v1"))

    class M:
        list = staticmethod(boom)

    monkeypatch.setattr(llm.client, "models", M)
    assert not llm.is_available()
