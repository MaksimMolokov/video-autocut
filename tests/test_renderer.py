"""Renderer: preview/final рендер, форматы, замена фрагментов."""
import subprocess

import pytest

from core.models import MontagePlan, PlanSegment, Project, Scene
from core.renderer import render_plan, replace_segment


def _probe_wh(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip().split(",")
    return int(out[0]), int(out[1])


@pytest.fixture()
def project_with_plan(storage, synthetic_video):
    project = Project(name="render-test", aspect="9:16", target_duration=6)
    storage.save_project(project)
    s1 = Scene(project_id=project.id, video_id="v1", video_path=str(synthetic_video),
               start=0.5, end=3.0)
    s2 = Scene(project_id=project.id, video_id="v1", video_path=str(synthetic_video),
               start=3.5, end=6.0)
    s3 = Scene(project_id=project.id, video_id="v1", video_path=str(synthetic_video),
               start=6.5, end=8.5)
    storage.save_scenes([s1, s2, s3])
    plan = MontagePlan(project_id=project.id, segments=[
        PlanSegment(scene_id=s1.id, order=0, src_start=0.5, src_end=3.0, slot="intro"),
        PlanSegment(scene_id=s2.id, order=1, src_start=3.5, src_end=6.0, slot="main"),
    ], alternatives={"main": [s3.id]})
    storage.save_plan(plan)
    return project, plan, s3


def test_preview_render(storage, project_with_plan):
    project, plan, _ = project_with_plan
    out = render_plan(storage, project, plan, final=False, progress=lambda m: None)
    assert out and out.exists()
    w, h = _probe_wh(out)
    assert (w, h) == (540, 960)  # 9:16 half-res preview
    assert storage.get_plan(plan.id).status == "rendered"
    # длительность ролика = сумме сегментов (2.5 + 2.5), точность нарезки
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip())
    assert abs(dur - plan.total_duration) < 0.3


def test_final_render_16_9(storage, project_with_plan):
    project, plan, _ = project_with_plan
    project.aspect = "16:9"
    out = render_plan(storage, project, plan, final=True, progress=lambda m: None)
    assert out and out.exists()
    assert _probe_wh(out) == (1920, 1080)
    got = storage.get_plan(plan.id)
    assert got.status == "final" and got.export_path == str(out)


def test_render_with_music(storage, project_with_plan, synthetic_music):
    project, plan, _ = project_with_plan
    project.music_path = str(synthetic_music)
    out = render_plan(storage, project, plan, final=False, progress=lambda m: None)
    assert out and out.exists()
    # аудиодорожка присутствует
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
    assert "audio" in streams


def test_render_empty_plan(storage, project_with_plan):
    project, plan, _ = project_with_plan
    plan.segments = []
    assert render_plan(storage, project, plan, final=False, progress=lambda m: None) is None


def test_target_fps_matches_sources(storage, project_with_plan):
    """50fps исходники → рендер 25fps (ровный дроп, без стробо-судорог);
    прочие → 30fps."""
    from core.models import SourceVideo
    from core.renderer import _target_fps
    project, plan, _ = project_with_plan
    scene = storage.get_scene(plan.segments[0].scene_id)

    v = SourceVideo(project_id=project.id, path=scene.video_path, fps=50.0)
    v.id = scene.video_id
    storage.save_video(v)
    assert _target_fps(storage, plan) == 25

    v.fps = 59.94
    storage.save_video(v)
    assert _target_fps(storage, plan) == 30

    v.fps = 25.0
    storage.save_video(v)
    assert _target_fps(storage, plan) == 25


def test_crossfade_render_duration(storage, project_with_plan):
    """Crossfade: длительность ролика = сумма сегментов − (N−1)·D."""
    project, plan, _ = project_with_plan
    plan.transition = "crossfade"
    plan.transition_duration = 0.5
    out = render_plan(storage, project, plan, final=False, progress=lambda m: None)
    assert out and out.exists()
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip())
    expected = plan.total_duration - (len(plan.segments) - 1) * 0.5
    assert abs(dur - expected) < 0.35


def test_segment_cache_reused(storage, project_with_plan):
    """Повторный рендер не перекодирует сегменты — берёт из кэша."""
    project, plan, _ = project_with_plan
    render_plan(storage, project, plan, final=False, progress=lambda m: None)
    seg_dir = storage.project_dir(project.id) / "cache" / "segments"
    first = {p.name: p.stat().st_mtime_ns for p in seg_dir.glob("*.mp4")}
    assert first  # кэш создан

    messages = []
    out = render_plan(storage, project, plan, final=False, progress=messages.append)
    assert out and out.exists()
    second = {p.name: p.stat().st_mtime_ns for p in seg_dir.glob("*.mp4")}
    assert set(second) == set(first)                     # те же файлы
    assert sum("из кэша" in m for m in messages) == len(plan.segments)


def test_segment_cache_lru_trim(storage, project_with_plan, monkeypatch):
    """При превышении лимита старейшие сегменты удаляются."""
    from core import renderer as r
    project, plan, _ = project_with_plan
    render_plan(storage, project, plan, final=False, progress=lambda m: None)
    seg_dir = storage.project_dir(project.id) / "cache" / "segments"
    n_before = len(list(seg_dir.glob("*.mp4")))
    assert n_before >= 2
    monkeypatch.setattr(r, "_SEGMENT_CACHE_MAX_BYTES", 1)  # лимит 1 байт
    r._trim_segment_cache(seg_dir)
    assert len(list(seg_dir.glob("*.mp4"))) == 0


def test_replace_segment(storage, project_with_plan):
    project, plan, alt = project_with_plan
    seg = plan.segments[1]
    old_duration = seg.duration
    assert replace_segment(storage, plan, seg.id, alt)
    assert seg.scene_id == alt.id
    assert abs(seg.duration - min(old_duration, alt.duration)) < 0.01
    assert seg.reason == "заменено пользователем"
    assert plan.status == "draft"
    # история замен записана
    assert storage.conn.execute("SELECT COUNT(*) FROM replacements").fetchone()[0] == 1


def test_replace_segment_unknown_id(storage, project_with_plan):
    _, plan, alt = project_with_plan
    assert not replace_segment(storage, plan, "nonexistent", alt)


def test_replace_segment_resyncs_beats(storage, project_with_plan):
    """После замены с переданной музыкой план заново выровнен по битам."""
    from core.audio_analyzer import MusicAnalysis

    _, plan, alt = project_with_plan
    seg = plan.segments[1]
    # альтернатива длиной 2.0s → конец таймлайна 2.5 + 2.0 = 4.5s;
    # точка склейки 4.6s — в допуске ±0.35
    music = MusicAnalysis(path="x", duration=60.0,
                          cut_points=[2.5, 4.6], beats=[2.5, 4.6])
    assert replace_segment(storage, plan, seg.id, alt, music=music)
    replaced = storage.get_plan(plan.id).segments[1]
    assert replaced.beat_synced
    # конец сегмента подтянут: 2.5 (конец первого) + длительность = 4.6
    assert abs((2.5 + replaced.duration) - 4.6) < 0.01


def test_encoder_args_hw_and_fallback(monkeypatch):
    """HW_ENCODE + доступный VideoToolbox → аппаратный кодек; иначе libx264."""
    import config
    from core import renderer as r

    monkeypatch.setattr(r, "_HW_ENCODER", "h264_videotoolbox")
    monkeypatch.setattr(config, "HW_ENCODE", True)
    args = r._encoder_args(final=False)
    assert "h264_videotoolbox" in args and "yuv420p" in args

    monkeypatch.setattr(config, "HW_ENCODE", False)
    args = r._encoder_args(final=True)
    assert "libx264" in args and "18" in args

    # ffmpeg без videotoolbox → fallback даже при HW_ENCODE=True
    monkeypatch.setattr(config, "HW_ENCODE", True)
    monkeypatch.setattr(r, "_HW_ENCODER", "")
    assert "libx264" in r._encoder_args(final=False)


def test_crossfade_survives_short_segment(storage, project_with_plan):
    """Сегмент короче фейда (сжатая пауза 0.4с) не ломает xfade-цепочку:
    фейд ужимается, рендер успешен, все сегменты в ролике."""
    project, plan, _ = project_with_plan
    from core.models import PlanSegment
    scene = storage.get_scene(plan.segments[0].scene_id)
    plan.segments.append(PlanSegment(
        scene_id=scene.id, order=2, src_start=6.5, src_end=6.9,
        slot="пауза", speed=1.0))
    plan.transition = "crossfade"
    plan.transition_duration = 0.5   # больше, чем сегмент 0.4с
    out = render_plan(storage, project, plan, final=False, progress=lambda m: None)
    assert out and out.exists()
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip())
    # фейд ужат до 0.4*0.45=0.18 → длительность = 5.9 - 2*0.18 ≈ 5.54
    expected = plan.total_duration - 2 * (0.4 * 0.45)
    assert abs(dur - expected) < 0.4
