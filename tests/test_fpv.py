"""FPV Showroom: тайминг-солвер, порядок маршрута, зоны, скорость рендера."""
import pytest

from core.fpv import STYLES, build_fpv_plan, detect_zones, solve_timing
from core.models import Project, Scene, SourceVideo, Zone


# ─────────── solve_timing ───────────

def test_timing_fits_comfortably():
    """6 зон по 20с, маршрут 300с (5 мин), цель 60с — как в примере спеки."""
    sol = solve_timing([20] * 6, 300.0, 60.0, "smooth")
    assert sol.fits and not sol.warnings
    shown = 6 * min(sol.window, 20) / sol.zone_speed
    gaps = (300 - 6 * min(sol.window, 20)) / sol.gap_speed
    assert abs(shown + gaps - 60.0) < 1.0        # укладываемся в цель
    assert 1.0 <= sol.gap_speed <= STYLES["smooth"]["gap_max"]


def test_timing_too_short_warns():
    """10 зон в 15 секунд не влезают — предупреждение с вариантами."""
    sol = solve_timing([20] * 10, 400.0, 15.0, "smooth")
    assert not sol.fits
    assert sol.warnings and "слишком короткий" in sol.warnings[0]


def test_timing_dynamic_fits_where_smooth_fails():
    """Динамичный стиль ускоряет сильнее — влезает там, где плавный нет."""
    args = ([15] * 5, 400.0, 45.0)
    smooth = solve_timing(*args, "smooth")
    dynamic = solve_timing(*args, "dynamic")
    assert dynamic.fits
    assert dynamic.gap_speed > smooth.gap_speed or smooth.fits is False


def test_timing_generous_target_slow_gaps():
    """Целевая длительность щедрая — промежутки почти без ускорения."""
    sol = solve_timing([10] * 2, 60.0, 55.0, "smooth")
    assert sol.fits and sol.gap_speed < 1.5


# ─────────── зоны и план ───────────

@pytest.fixture()
def fpv_setup(storage, synthetic_video):
    """Проект + FPV-видео 120с с 12 сценами и 4 зонами (первая техническая)."""
    project = Project(name="fpv", target_duration=30, fpv_style="smooth",
                      music_path="")
    storage.save_project(project)
    video = SourceVideo(project_id=project.id, path=str(synthetic_video),
                        duration=120.0, fps=30, width=640, height=360,
                        fpv_showroom=True, valid=True)
    storage.save_video(video)
    scenes = []
    for i in range(12):
        s = Scene(project_id=project.id, video_id=video.id,
                  video_path=str(synthetic_video),
                  start=i * 10.0, end=(i + 1) * 10.0,
                  quality_score=0.8, stability_score=0.9,
                  llm_status="done", description=f"место {i}")
        scenes.append(s)
    storage.save_scenes(scenes)
    zones = [
        Zone(project_id=project.id, video_id=video.id, start=0, end=10,
             title="взлёт", technical=True, required=False),
        Zone(project_id=project.id, video_id=video.id, start=10, end=40,
             title="вход"),
        Zone(project_id=project.id, video_id=video.id, start=50, end=80,
             title="зал"),
        Zone(project_id=project.id, video_id=video.id, start=90, end=120,
             title="бар"),
    ]
    for z in zones:
        storage.save_zone(z)
    return project, video, zones


def test_fpv_plan_preserves_route_order(storage, fpv_setup, monkeypatch):
    """Главный инвариант: сегменты строго по возрастанию таймкода исходника."""
    import core.fpv as fpv_mod
    monkeypatch.setattr(fpv_mod, "motion_profile", lambda *a, **k: None,
                        raising=False)
    project, video, _ = fpv_setup
    plan = build_fpv_plan(storage, project, video)
    assert plan.mode == "fpv"
    starts = [seg.src_start for seg in plan.segments]
    assert starts == sorted(starts)
    # сегменты не перекрываются
    for a, b in zip(plan.segments, plan.segments[1:]):
        assert b.src_start >= a.src_end - 0.01


def test_fpv_plan_excludes_technical_start(storage, fpv_setup):
    """Взлёт (0–10с, technical) не попадает в ролик."""
    project, video, _ = fpv_setup
    plan = build_fpv_plan(storage, project, video)
    assert min(seg.src_start for seg in plan.segments) >= 10.0 - 0.01


def test_fpv_plan_zones_normal_speed_gaps_fast(storage, fpv_setup):
    project, video, _ = fpv_setup
    plan = build_fpv_plan(storage, project, video)
    zone_segs = [s for s in plan.segments if s.slot in ("вход", "зал", "бар")]
    gap_segs = [s for s in plan.segments if s.slot in ("переезд", "финал")]
    assert len(zone_segs) == 3                     # все обязательные зоны показаны
    assert all(s.speed <= 1.5 for s in zone_segs)  # зоны без чрезмерного ускорения
    assert gap_segs and all(s.speed > 1.0 for s in gap_segs)


def test_fpv_plan_hits_target_duration(storage, fpv_setup):
    project, video, _ = fpv_setup
    plan = build_fpv_plan(storage, project, video)
    assert abs(plan.total_duration - 30.0) <= 3.5


def test_fpv_plan_warns_when_impossible(storage, fpv_setup):
    project, video, _ = fpv_setup
    project.target_duration = 8   # 3 зоны в 8 секунд — нереально
    storage.save_project(project)
    plan = build_fpv_plan(storage, project, video)
    assert plan.warnings and "слишком короткий" in plan.warnings[0]


def test_fpv_plan_unrequired_zone_becomes_gap(storage, fpv_setup):
    """Снятая отметка: зона не показывается, но маршрут через неё проходит."""
    project, video, zones = fpv_setup
    hall = next(z for z in zones if z.title == "зал")
    hall.required = False
    storage.save_zone(hall)
    plan = build_fpv_plan(storage, project, video)
    assert not any(s.slot == "зал" for s in plan.segments)
    # маршрут непрерывен: зал покрыт перемоткой
    covered = any(s.src_start <= 60 <= s.src_end and s.speed > 1
                  for s in plan.segments)
    assert covered


def test_detect_zones_fallback(storage, fpv_setup, monkeypatch):
    """Без LLM зоны строятся группировкой похожих соседей."""
    from core import fpv as fpv_mod
    monkeypatch.setattr(fpv_mod, "_detect_zones_llm", lambda scenes: None)
    project, video, _ = fpv_setup
    zones = detect_zones(storage, project, video)
    assert zones
    assert all(z.start < z.end for z in zones)
    starts = [z.start for z in zones]
    assert starts == sorted(starts)
    # зоны сохранены в БД
    assert len(storage.list_zones(video.id)) == len(zones)


# ─────────── интересность и автосюжеты (фикс «всё видео перемотано») ───────────

def test_interest_score_orders_by_aesthetic_and_people():
    from core.fpv import _interest_score
    plain = Scene(video_id="v", video_path="/x.mp4", start=0, end=10,
                 aesthetic_score=0.2, quality_score=0.5, people_count=0)
    pretty = Scene(video_id="v", video_path="/x.mp4", start=0, end=10,
                  aesthetic_score=0.9, quality_score=0.8, people_count=1)
    assert _interest_score(pretty) > _interest_score(plain)


def test_auto_zones_spread_across_long_uniform_route(storage, synthetic_video):
    """Главный сценарий бага: цельный однородный дубль (танец, спорт), где
    старая группировка по похожести схлопнула бы всё в ОДИН блок (все куски
    одного видео в пределах 20с считались «похожими» → одна гигантская
    зона → почти весь ролик становится перемоткой). detect_zones должен
    вернуть >=4 зоны, распределённые по всей длине, а не только в начале."""
    from core.fpv import detect_zones
    project = Project(name="dance", target_duration=40, fpv_style="smooth")
    storage.save_project(project)
    video = SourceVideo(project_id=project.id, path=str(synthetic_video),
                        duration=200.0, fps=30, width=640, height=360,
                        fpv_showroom=True, valid=True)
    storage.save_video(video)
    scenes = []
    for i in range(20):  # 20×10с = 200с одного цельного дубля
        s = Scene(project_id=project.id, video_id=video.id,
                 video_path=str(synthetic_video),
                 start=i * 10.0, end=(i + 1) * 10.0,
                 quality_score=0.7, llm_status="done", description=f"кусок {i}",
                 # каждый третий кусок — «яркий момент» (высокая эстетика/люди)
                 aesthetic_score=0.9 if i % 3 == 0 else 0.3,
                 people_count=1 if i % 3 == 0 else 0)
        scenes.append(s)
    storage.save_scenes(scenes)

    zones = detect_zones(storage, project, video)
    assert len(zones) >= 4
    starts = [z.start for z in zones]
    assert starts == sorted(starts)
    # зоны разбросаны по всему маршруту, а не только в первой трети
    assert max(starts) > 200 * 0.5
    assert min(starts) < 200 * 0.3
    # ни одна зона не покрывает больше половины маршрута — иначе снова
    # «всё видео перемотано»
    assert all(z.duration < 100 for z in zones)


def test_auto_zones_skips_duplicate_adjacent_scene():
    from core.fpv import _auto_zones
    project = Project(name="p", target_duration=40)
    scenes = [Scene(video_id="v", video_path="/x.mp4",
                    start=i * 10.0, end=(i + 1) * 10.0,
                    aesthetic_score=0.5, quality_score=0.5)
             for i in range(6)]
    zones = _auto_zones(project, SourceVideo(project_id="p", path="/x.mp4"),
                        scenes, 0.0, 60.0)
    ids = [z.title for z in zones]
    # соседние полосы не должны выбрать один и тот же кусок дважды подряд
    scene_ids_selected = []
    for z in zones:
        for s in scenes:
            if s.start == z.start and s.end == z.end:
                scene_ids_selected.append(s.id)
    assert len(scene_ids_selected) == len(set(dict.fromkeys(scene_ids_selected)))
    for a, b in zip(scene_ids_selected, scene_ids_selected[1:]):
        assert a != b


def test_best_window_prefers_interesting_scene(storage, synthetic_video, monkeypatch):
    """При одинаково плавном движении окно внутри зоны выбирает участок с
    более интересным содержанием (человек в кадре), а не первый попавшийся."""
    import core.frame_quality as fq_mod
    monkeypatch.setattr(fq_mod, "motion_profile", lambda *a, **k: None)
    project = Project(name="pick", target_duration=20, fpv_style="smooth")
    storage.save_project(project)
    video = SourceVideo(project_id=project.id, path=str(synthetic_video),
                        duration=30.0, fps=30, width=640, height=360,
                        fpv_showroom=True, valid=True)
    storage.save_video(video)
    storage.save_scenes([
        Scene(project_id=project.id, video_id=video.id, video_path=str(synthetic_video),
             start=0, end=10, quality_score=0.7, aesthetic_score=0.1, llm_status="done"),
        Scene(project_id=project.id, video_id=video.id, video_path=str(synthetic_video),
             start=10, end=20, quality_score=0.7, aesthetic_score=0.95,
             people_count=2, llm_status="done"),
        Scene(project_id=project.id, video_id=video.id, video_path=str(synthetic_video),
             start=20, end=30, quality_score=0.7, aesthetic_score=0.1, llm_status="done"),
    ])
    storage.save_zone(Zone(project_id=project.id, video_id=video.id, start=0, end=30,
                           title="весь маршрут", required=True, technical=False))

    plan = build_fpv_plan(storage, project, video)
    zone_seg = next(s for s in plan.segments if s.speed == 1.0)
    # окно должно попасть на интересный средний кусок (10-20с), не на края
    assert 9.0 <= zone_seg.src_start <= 14.5


def test_route_tail_never_silently_dropped(storage, fpv_setup):
    """Регрессия: если последняя показанная зона совпадает с концом
    активного маршрута, хвост после её окна должен появиться перемоткой,
    а не пропасть — иначе локация показана не до конца."""
    project, video, _ = fpv_setup
    plan = build_fpv_plan(storage, project, video)
    last_end = max(seg.src_end for seg in plan.segments)
    zones = storage.list_zones(video.id)
    route_end = max(z.end for z in zones if not z.technical)
    assert last_end >= route_end - 0.5


# ─────────── скорость в модели ───────────

def test_segment_out_duration():
    from core.models import PlanSegment
    seg = PlanSegment(scene_id="s", order=0, src_start=0, src_end=12,
                      slot="переезд", speed=3.0)
    assert seg.duration == 12.0        # в исходнике
    assert seg.out_duration == 4.0     # в ролике
