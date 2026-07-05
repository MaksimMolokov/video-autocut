"""Пайплайн end-to-end (без LLM): исходники → каталог сцен с превью в БД."""
from pathlib import Path

import pytest

from core.models import Project
from core.pipeline import analyze_project, run_llm_analysis


def test_analyze_project_e2e(storage, synthetic_video):
    project = Project(name="e2e", source_paths=[str(synthetic_video)])
    storage.save_project(project)
    scenes = analyze_project(storage, project, progress=lambda m: None, run_llm=False)

    assert len(scenes) >= 2  # 3 склейки в синтетике
    assert storage.get_project(project.id).status == "analyzed"
    assert storage.list_videos(project.id)[0].valid

    for s in scenes:
        assert s.duration >= 1.0
        assert 0 <= s.quality_score <= 1
        assert s.llm_status == "pending"          # LLM не запускали
        assert Path(s.thumbnail_path).exists()    # превью реально созданы (ТЗ §7.6)
        assert Path(s.preview_path).exists()
        # кэш кадра для LLM подготовлен заранее
        pdir = storage.project_dir(project.id)
        assert (pdir / "cache" / f"{s.id}_key.jpg").exists()


def test_analyze_project_no_files(storage, tmp_path):
    project = Project(name="пусто", source_paths=[str(tmp_path)])
    storage.save_project(project)
    with pytest.raises(ValueError):
        analyze_project(storage, project, progress=lambda m: None, run_llm=False)


def test_analyze_project_skips_broken(storage, synthetic_video, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"garbage")
    project = Project(name="mix", source_paths=[str(synthetic_video), str(bad)])
    storage.save_project(project)
    scenes = analyze_project(storage, project, progress=lambda m: None, run_llm=False)
    assert scenes  # хорошее видео обработано
    videos = storage.list_videos(project.id)
    assert sum(1 for v in videos if not v.valid) == 1  # битое помечено


def test_run_llm_analysis_unavailable(storage, synthetic_video, monkeypatch):
    """LM Studio выключен → 0 обработанных, сцены остаются pending."""
    from core import pipeline

    class FakeLLM:
        def is_available(self):
            return False

    monkeypatch.setattr(pipeline, "LLMAnalyzer", FakeLLM)
    project = Project(name="nollm", source_paths=[str(synthetic_video)])
    storage.save_project(project)
    analyze_project(storage, project, progress=lambda m: None, run_llm=False)
    assert run_llm_analysis(storage, project, progress=lambda m: None) == 0
    assert all(s.llm_status == "pending" for s in storage.list_scenes(project.id))


def test_run_llm_analysis_mocked(storage, synthetic_video, monkeypatch):
    """Мок LLM: все сцены получают описания и статус done."""
    from core import pipeline

    class FakeLLM:
        model = "fake-vl"

        def is_available(self):
            return True

        def fill_scene(self, scene, frame):
            scene.description = "тестовая сцена"
            scene.scene_type = "location"
            scene.aesthetic_score = 0.5
            scene.llm_status = "done"
            return True

    monkeypatch.setattr(pipeline, "LLMAnalyzer", FakeLLM)
    project = Project(name="mockllm", source_paths=[str(synthetic_video)])
    storage.save_project(project)
    analyze_project(storage, project, progress=lambda m: None, run_llm=False)
    n = run_llm_analysis(storage, project, progress=lambda m: None)
    scenes = storage.list_scenes(project.id)
    assert n == len(scenes) > 0
    assert all(s.llm_status == "done" and s.description for s in scenes)
