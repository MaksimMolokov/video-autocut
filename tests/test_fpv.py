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


def test_interest_score_penalizes_static_no_subject():
    """Регрессия: статичный технически «чистый» кадр без людей (завис
    дрона) не должен побеждать по интересности человека в динамике, даже
    если у него ХУЖЕ формальное качество (смаз/шум от движения)."""
    from core.fpv import _interest_score
    boring_static = Scene(video_id="v", video_path="/x.mp4", start=0, end=10,
                          aesthetic_score=0.0, quality_score=0.9,
                          people_count=0, motion="static")
    dancer = Scene(video_id="v", video_path="/x.mp4", start=0, end=10,
                  aesthetic_score=0.3, quality_score=0.5,
                  people_count=1, motion="fast")
    cache: dict = {}
    assert _interest_score(dancer, cache) > _interest_score(boring_static, cache)
    assert _interest_score(boring_static, cache) < 0.15  # ниже порога зоны


def test_auto_zones_skip_lane_with_only_boring_static_content():
    """Полоса, где нет ничего кроме статичного зависшего кадра без людей,
    не должна становиться обязательной зоной — вся полоса уходит в
    перемотку. Прямая репродукция жалобы: «пауза без человека в саду —
    почему это не перематывается»."""
    from core.fpv import _auto_zones
    project = Project(name="p", target_duration=60)
    video = SourceVideo(project_id="p", path="/x.mp4")
    scenes = []
    for i in range(6):
        if i == 1:
            s = Scene(video_id="v", video_path="/x.mp4", start=10, end=20,
                     aesthetic_score=0.0, quality_score=0.95,
                     people_count=0, motion="static")
        else:
            s = Scene(video_id="v", video_path="/x.mp4",
                     start=i * 10.0, end=(i + 1) * 10.0,
                     aesthetic_score=0.6, quality_score=0.5,
                     people_count=1, motion="fast")
        scenes.append(s)
    zones = _auto_zones(project, video, scenes, 0.0, 60.0)
    # лана 10-20с (только скучная статика, единственный кандидат в ней —
    # ровно этот кусок) не должна дать зону
    assert not any(z.start == 10.0 for z in zones)
    assert len(zones) == 5  # остальные 5 лан (с людьми) дали зоны


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


# ─────────── длинные зоны → несколько моментов; хард-вырез технических ───────────

def test_expand_long_zone_creates_multiple_moments(synthetic_video):
    """Длинная зона (60с непрерывного танца) должна дать НЕСКОЛЬКО моментов
    с перемоткой между ними, а не один показ + одну гигантскую перемотку
    до следующей зоны — прямая репродукция жалобы пользователя."""
    from core.fpv import _expand_long_zones
    project = Project(name="dance", target_duration=45, fpv_style="smooth")
    video = SourceVideo(project_id="p", path=str(synthetic_video))
    scenes = [
        Scene(video_id="v", video_path=str(synthetic_video),
             start=i * 10.0, end=(i + 1) * 10.0,
             aesthetic_score=0.7, quality_score=0.6,
             people_count=1 if i % 2 == 0 else 2)
        for i in range(6)  # 60с одной длинной зоны
    ]
    long_zone = Zone(project_id="p", video_id="v", start=0.0, end=60.0,
                     title="Танец на первом этаже", required=True, technical=False)
    target_span = 6.0 * 3.0  # style smooth window max=6 → target_span=18
    expanded = _expand_long_zones(project, video, scenes, [long_zone], target_span)
    assert len(expanded) >= 2  # больше одного момента
    starts = [z.start for z in expanded]
    assert starts == sorted(starts)
    for z in expanded:
        assert long_zone.start <= z.start and z.end <= long_zone.end


def test_expand_long_zone_leaves_short_zone_untouched():
    from core.fpv import _expand_long_zones
    project = Project(name="p", target_duration=45)
    video = SourceVideo(project_id="p", path="/x.mp4")
    short_zone = Zone(project_id="p", video_id="v", start=0.0, end=8.0, title="вход")
    expanded = _expand_long_zones(project, video, [], [short_zone], target_span=18.0)
    assert expanded == [short_zone]


def test_split_excluding_technical_middle():
    from core.fpv import _split_excluding_technical
    tech = [Zone(project_id="p", video_id="v", start=70.0, end=79.0,
                technical=True, required=False)]
    assert _split_excluding_technical(65.0, 85.0, tech) == [(65.0, 70.0), (79.0, 85.0)]


def test_split_excluding_technical_covers_whole_gap():
    """Техническая зона занимает весь промежуток целиком — перемотки не
    остаётся вообще: footage не должно появиться в ролике ни на какой
    скорости (репродукция: «я указал не использовать эти кадры — ты всё
    равно их вставил»)."""
    from core.fpv import _split_excluding_technical
    tech = [Zone(project_id="p", video_id="v", start=60.0, end=90.0,
                technical=True, required=False)]
    assert _split_excluding_technical(65.0, 85.0, tech) == []


def test_split_excluding_technical_no_overlap():
    from core.fpv import _split_excluding_technical
    tech = [Zone(project_id="p", video_id="v", start=200.0, end=210.0,
                technical=True, required=False)]
    assert _split_excluding_technical(65.0, 85.0, tech) == [(65.0, 85.0)]


def test_split_excluding_technical_multiple_zones():
    from core.fpv import _split_excluding_technical
    tech = [
        Zone(project_id="p", video_id="v", start=68.0, end=71.0, technical=True),
        Zone(project_id="p", video_id="v", start=80.0, end=83.0, technical=True),
    ]
    assert _split_excluding_technical(65.0, 85.0, tech) == \
        [(65.0, 68.0), (71.0, 80.0), (83.0, 85.0)]


def test_fpv_plan_never_includes_technical_footage_mid_route(storage, synthetic_video, monkeypatch):
    """Прямая репродукция жалобы: пауза между этажами явно помечена
    технической — её footage не должно появляться в ролике ни на какой
    скорости, а длинные зоны танца до/после должны дать несколько
    нормально-скоростных моментов, а не один + гигантскую перемотку."""
    import core.frame_quality as fq_mod
    monkeypatch.setattr(fq_mod, "motion_profile", lambda *a, **k: None)

    project = Project(name="dance2", target_duration=40, fpv_style="smooth")
    storage.save_project(project)
    video = SourceVideo(project_id=project.id, path=str(synthetic_video),
                        duration=140.0, fps=30, width=640, height=360,
                        fpv_showroom=True, valid=True)
    storage.save_video(video)
    scenes = []
    for i in range(14):  # 0-140с
        in_pause = 7 <= i <= 8  # 70-90с — техническая пауза
        s = Scene(project_id=project.id, video_id=video.id,
                 video_path=str(synthetic_video),
                 start=i * 10.0, end=(i + 1) * 10.0,
                 quality_score=0.6, llm_status="done",
                 aesthetic_score=0.1 if in_pause else 0.7,
                 people_count=0 if in_pause else (1 if i % 2 == 0 else 2),
                 motion="static" if in_pause else "slow")
        scenes.append(s)
    storage.save_scenes(scenes)

    floor1 = Zone(project_id=project.id, video_id=video.id, start=0.0, end=70.0,
                 title="Танец на первом этаже", required=True, technical=False)
    pause = Zone(project_id=project.id, video_id=video.id, start=70.0, end=90.0,
                title="Переход на второй этаж", required=False, technical=True)
    floor2 = Zone(project_id=project.id, video_id=video.id, start=90.0, end=140.0,
                 title="Танец на втором этаже", required=True, technical=False)
    for z in (floor1, pause, floor2):
        storage.save_zone(z)

    plan = build_fpv_plan(storage, project, video)

    # техническая пауза не появляется в ролике ни на какой скорости
    for seg in plan.segments:
        overlap = min(seg.src_end, 90.0) - max(seg.src_start, 70.0)
        assert overlap <= 0.01, f"сегмент {seg.src_start}-{seg.src_end} задел паузу"

    # в каждом из этажей — больше одного нормально-скоростного момента,
    # а не один показ + одна гигантская перемотка
    floor1_normal = [s for s in plan.segments if s.speed == 1.0 and s.src_end <= 70.0]
    floor2_normal = [s for s in plan.segments if s.speed == 1.0 and s.src_start >= 90.0]
    assert len(floor1_normal) >= 2
    assert len(floor2_normal) >= 2
    # порядок маршрута не нарушен: всё строго по возрастанию
    starts = [s.src_start for s in plan.segments]
    assert starts == sorted(starts)


# ─────────── скорость в модели ───────────

def test_segment_out_duration():
    from core.models import PlanSegment
    seg = PlanSegment(scene_id="s", order=0, src_start=0, src_end=12,
                      slot="переезд", speed=3.0)
    assert seg.duration == 12.0        # в исходнике
    assert seg.out_duration == 4.0     # в ролике


# ─────────── танцор не перематывается, пустой завис — перематывается ───────────

def test_timing_subject_gaps_gentler_than_empty():
    """Промежутки с людьми ≤×3 (щадяще), пустые гонятся быстрее."""
    sol = solve_timing([10] * 3, 120.0, 40.0, "smooth", subject_len=40.0)
    assert sol.fits
    assert 1.0 <= sol.subject_gap_speed <= 3.0
    assert sol.gap_speed >= sol.subject_gap_speed
    # длительность сходится: зоны + люди + пустое ≈ target
    shown = 3 * min(sol.window, 10)
    subj_gap = max(40.0 - shown, 0.0)
    empty_gap = 120.0 - shown - subj_gap
    total = shown + subj_gap / sol.subject_gap_speed + empty_gap / sol.gap_speed
    assert abs(total - 40.0) <= 2.0


def test_timing_without_people_unchanged():
    """subject_len=0 (пустая локация) — поведение как раньше, одна скорость."""
    sol = solve_timing([20] * 6, 300.0, 60.0, "smooth")
    assert sol.fits and sol.subject_gap_speed == 1.0


def test_timing_warns_because_people_cannot_be_rushed():
    """Люди занимают почти весь маршрут, target мал — честное предупреждение
    (танец не гонится быстрее ×3 ради тайминга)."""
    sol = solve_timing([10] * 3, 120.0, 20.0, "smooth", subject_len=110.0)
    assert not sol.fits
    assert "не перематываются быстрее" in sol.warnings[0]
    assert sol.subject_gap_speed <= 3.0


def test_interest_score_person_beats_prettier_empty_frame():
    """Человек в кадре доминирует: танцор обыгрывает БОЛЕЕ красивый и
    БОЛЕЕ качественный пустой кадр (прямая репродукция жалобы: сюжетом
    становился красивый завис, а танец уезжал в перемотку)."""
    from core.fpv import _interest_score
    pretty_empty = Scene(video_id="v", video_path="/x.mp4", start=0, end=10,
                         aesthetic_score=0.95, quality_score=0.95,
                         people_count=0, motion="slow")
    dancer = Scene(video_id="v", video_path="/x.mp4", start=0, end=10,
                   aesthetic_score=0.3, quality_score=0.4,
                   people_count=1, motion="fast")
    assert _interest_score(dancer) > _interest_score(pretty_empty)


def test_auto_zones_prefer_people_when_route_has_them():
    """Если на маршруте есть люди — «моменты» ставятся только на людей;
    полосы с красивыми, но пустыми кадрами уходят в перемотку."""
    from core.fpv import _auto_zones
    project = Project(name="p", target_duration=60)
    video = SourceVideo(project_id="p", path="/x.mp4")
    scenes = []
    for i in range(6):
        with_person = i in (1, 4)
        scenes.append(Scene(
            video_id="v", video_path="/x.mp4",
            start=i * 10.0, end=(i + 1) * 10.0,
            aesthetic_score=0.4 if with_person else 0.9,  # пустые красивее!
            quality_score=0.5 if with_person else 0.9,
            people_count=1 if with_person else 0, motion="slow"))
    zones = _auto_zones(project, video, scenes, 0.0, 60.0)
    assert zones
    for z in zones:
        assert z.start in (10.0, 40.0), \
            f"зона {z.start}-{z.end} стоит на пустом кадре"


def test_fpv_dancer_normal_speed_hover_fast_forwarded(storage, synthetic_video,
                                                      monkeypatch):
    """Сквозная репродукция жалобы: танец 20–60с, вокруг — пустые пролёты
    и зависания. Требования:
    1) нормальная скорость — только на танце;
    2) перемотка ПО танцу щадящая (≤×3) — чередование «показ/мягкая
       перемотка» внутри танца;
    3) пустые участки гонятся быстрее — переход между людьми минимален."""
    import core.frame_quality as fq_mod
    import core.smart_crop as sc_mod
    monkeypatch.setattr(fq_mod, "motion_profile", lambda *a, **k: None)
    monkeypatch.setattr(sc_mod, "find_focus", lambda *a, **k: None)

    project = Project(name="dance-hover", target_duration=40, fpv_style="smooth")
    storage.save_project(project)
    video = SourceVideo(project_id=project.id, path=str(synthetic_video),
                        duration=120.0, fps=30, width=640, height=360,
                        fpv_showroom=True, valid=True)
    storage.save_video(video)
    scenes = []
    for i in range(12):
        dancing = 2 <= i <= 5  # 20–60с — танец
        scenes.append(Scene(
            project_id=project.id, video_id=video.id,
            video_path=str(synthetic_video),
            start=i * 10.0, end=(i + 1) * 10.0,
            # завис/пролёт технически «чище» и «красивее» танца — раньше
            # это делало его сюжетом, а танцора отправляло в перемотку
            quality_score=0.5 if dancing else 0.9,
            aesthetic_score=0.4 if dancing else 0.8,
            people_count=1 if dancing else 0,
            motion="fast" if dancing else "static",
            llm_status="done", description="танец" if dancing else "пусто"))
    storage.save_scenes(scenes)
    storage.save_zone(Zone(project_id=project.id, video_id=video.id,
                           start=0.0, end=120.0, title="маршрут",
                           required=True, technical=False))

    plan = build_fpv_plan(storage, project, video)

    # 1. все нормально-скоростные окна лежат на танце
    normal = [s for s in plan.segments if s.speed == 1.0]
    assert normal, "нет ни одного нормально-скоростного окна"
    for seg in normal:
        assert seg.src_start >= 19.5 and seg.src_end <= 60.5, \
            f"нормальная скорость на пустом кадре {seg.src_start}-{seg.src_end}"

    # 2. перемотка по танцу щадящая
    for seg in plan.segments:
        overlap = min(seg.src_end, 60.0) - max(seg.src_start, 20.0)
        if overlap > 0.5 and seg.speed > 1.0:
            assert seg.speed <= 3.01, \
                f"танец перемотан ×{seg.speed} ({seg.src_start}-{seg.src_end})"

    # 3. пустые участки гонятся быстрее любых «человеческих» перемоток
    empty_gaps = [s for s in plan.segments if s.speed > 1.0
                  and (s.src_end <= 20.5 or s.src_start >= 59.5)]
    assert empty_gaps, "пустые участки должны перематываться"
    dance_gaps = [s for s in plan.segments if s.speed > 1.0
                  and s.src_start >= 19.5 and s.src_end <= 60.5]
    if dance_gaps:
        assert (max(g.speed for g in empty_gaps)
                >= max(g.speed for g in dance_gaps))

    # маршрут по-прежнему строго по порядку и укладывается в тайминг
    starts = [s.src_start for s in plan.segments]
    assert starts == sorted(starts)
    assert abs(plan.total_duration - 40.0) <= 4.0


# ─────────── «замёрзшие» паузы: картинка не меняется → сжатие до 0.5с ───────────

def test_frozen_spans_detection():
    """Подряд идущие статичные сцены без людей группируются в паузу;
    короткая статика и статика с человеком паузой не считаются."""
    from core.fpv import _frozen_spans
    scenes = [
        Scene(video_id="v", video_path="/x.mp4", start=0, end=10,
              motion="slow", people_count=0),                    # движение
        Scene(video_id="v", video_path="/x.mp4", start=10, end=20,
              motion="static", people_count=0),                  # пауза…
        Scene(video_id="v", video_path="/x.mp4", start=20, end=30,
              motion="static", people_count=0),                  # …продолжается
        Scene(video_id="v", video_path="/x.mp4", start=30, end=40,
              motion="static", people_count=1),                  # человек стоит — не пауза
        Scene(video_id="v", video_path="/x.mp4", start=40, end=42,
              motion="static", people_count=0),                  # 2с — короче порога
    ]
    spans = _frozen_spans(scenes, cache={})
    assert spans == [(10.0, 30.0)]


def test_timing_frozen_pause_takes_fixed_time():
    """Замёрзшая пауза занимает фиксированное экранное время, освобождая
    бюджет: без учёта заморозки этот тайминг был бы на грани."""
    # маршрут 120с: зоны 3×10, люди 40с, замёрзшая пауза 40с (одна)
    sol = solve_timing([10] * 3, 120.0, 40.0, "smooth",
                       subject_len=40.0, frozen_len=40.0, frozen_out=0.5)
    assert sol.fits
    shown = 3 * min(sol.window, 10)
    subj_gap = max(40.0 - shown, 0.0)
    empty_gap = 120.0 - shown - subj_gap - 40.0
    total = (shown + 0.5 + subj_gap / sol.subject_gap_speed
             + empty_gap / sol.gap_speed)
    assert abs(total - 40.0) <= 2.0


def test_fpv_frozen_pause_compressed_to_setting(storage, synthetic_video,
                                                monkeypatch):
    """Правило пользователя: длинный статичный кусок (дрон завис между
    этажами, картинка не меняется) занимает в ролике не больше
    fpv_pause_out секунд (по умолчанию 0.5с + защита от фейда)."""
    import core.frame_quality as fq_mod
    import core.smart_crop as sc_mod
    monkeypatch.setattr(fq_mod, "motion_profile", lambda *a, **k: None)
    monkeypatch.setattr(sc_mod, "find_focus", lambda *a, **k: None)
    monkeypatch.setattr(fq_mod, "change_profile", lambda *a, **k: None)

    project = Project(name="frozen", target_duration=30, fpv_style="smooth")
    storage.save_project(project)
    video = SourceVideo(project_id=project.id, path=str(synthetic_video),
                        duration=100.0, fps=30, width=640, height=360,
                        fpv_showroom=True, valid=True)
    storage.save_video(video)
    scenes = []
    for i in range(10):
        dancing = i <= 2 or i >= 7        # 0-30 и 70-100 — танец
        hovering = 3 <= i <= 6            # 30-70 — завис, картинка не меняется
        scenes.append(Scene(
            project_id=project.id, video_id=video.id,
            video_path=str(synthetic_video),
            start=i * 10.0, end=(i + 1) * 10.0,
            quality_score=0.9 if hovering else 0.5,
            aesthetic_score=0.7 if hovering else 0.4,
            people_count=1 if dancing else 0,
            motion="static" if hovering else "fast",
            llm_status="done"))
    storage.save_scenes(scenes)
    storage.save_zone(Zone(project_id=project.id, video_id=video.id,
                           start=0.0, end=100.0, title="маршрут",
                           required=True, technical=False))

    plan = build_fpv_plan(storage, project, video)

    # завис 30-70с присутствует в ролике (не вырезан), но суммарно
    # занимает не больше паузы из настройки (+ защита от фейда: 0.6с)
    frozen_segs = [s for s in plan.segments
                   if s.src_start >= 29.0 and s.src_end <= 71.0 and s.speed > 3.5]
    assert frozen_segs, "статичная пауза должна быть сжата суперскоростью"
    frozen_out = sum(s.out_duration for s in frozen_segs)
    assert frozen_out <= 1.0, f"пауза заняла {frozen_out:.2f}с в ролике"
    # маршрут непрерывен: завис не вырезан, а перемотан
    covered = sorted((s.src_start, s.src_end) for s in plan.segments)
    for a, b in zip(covered, covered[1:]):
        assert b[0] >= a[1] - 0.01
    # нормальная скорость — только на танце
    for seg in plan.segments:
        if seg.speed == 1.0:
            assert seg.src_end <= 30.5 or seg.src_start >= 69.5


def test_fpv_pause_setting_respected(storage, synthetic_video, monkeypatch):
    """fpv_pause_out из настроек проекта управляет длительностью паузы."""
    import core.frame_quality as fq_mod
    import core.smart_crop as sc_mod
    monkeypatch.setattr(fq_mod, "motion_profile", lambda *a, **k: None)
    monkeypatch.setattr(sc_mod, "find_focus", lambda *a, **k: None)
    monkeypatch.setattr(fq_mod, "change_profile", lambda *a, **k: None)

    project = Project(name="frozen2", target_duration=30, fpv_style="smooth",
                      fpv_pause_out=2.0)
    storage.save_project(project)
    video = SourceVideo(project_id=project.id, path=str(synthetic_video),
                        duration=100.0, fps=30, width=640, height=360,
                        fpv_showroom=True, valid=True)
    storage.save_video(video)
    scenes = []
    for i in range(10):
        hovering = 3 <= i <= 6
        scenes.append(Scene(
            project_id=project.id, video_id=video.id,
            video_path=str(synthetic_video),
            start=i * 10.0, end=(i + 1) * 10.0,
            quality_score=0.6, aesthetic_score=0.5,
            people_count=0 if hovering else 1,
            motion="static" if hovering else "slow",
            llm_status="done"))
    storage.save_scenes(scenes)
    storage.save_zone(Zone(project_id=project.id, video_id=video.id,
                           start=0.0, end=100.0, title="маршрут",
                           required=True, technical=False))

    plan = build_fpv_plan(storage, project, video)
    frozen_segs = [s for s in plan.segments
                   if "статичная пауза" in s.reason]
    assert frozen_segs
    frozen_out = sum(s.out_duration for s in frozen_segs)
    assert frozen_out <= 2.0 + 0.3
    assert frozen_out >= 1.0  # пауза видна, а не вырезана в ноль


# ─────────── детекция пауз по пофреймовой разнице картинки ───────────

def test_frozen_spans_profile_detects_real_freeze(freeze_video):
    """Замер на настоящем видео: 3–8с — повтор одного кадра (картинка
    буквально не меняется) — детектор находит ровно эту паузу."""
    from core.fpv import _frozen_spans_profile
    spans = _frozen_spans_profile(str(freeze_video), 0.0, 11.0)
    assert spans is not None and len(spans) == 1, f"найдено: {spans}"
    lo, hi = spans[0]
    assert abs(lo - 3.0) <= 1.0, f"начало паузы {lo:.2f}, ждали ~3.0"
    assert abs(hi - 8.0) <= 1.0, f"конец паузы {hi:.2f}, ждали ~8.0"


def test_frozen_spans_profile_no_freeze_on_motion(smooth_pan_video):
    """На видео с непрерывным движением пауз нет."""
    from core.fpv import _frozen_spans_profile
    spans = _frozen_spans_profile(str(smooth_pan_video), 0.0, 4.0)
    assert spans == []


def test_fpv_pause_detected_by_profile_not_scene_labels(storage, synthetic_video,
                                                        monkeypatch):
    """Репродукция жалобы «пауза перематывается недостаточно»:
    1) сцены паузы помечены motion='slow' (лёгкий дрейф дрона) — сценный
       детектор её НЕ видит;
    2) CV/LLM ложно «видят человека» в замершем кадре — раньше пауза уходила
       в щадящую перемотку ×3 и занимала секунды.
    Профиль изменений картинки должен пересилить и то и другое."""
    import core.frame_quality as fq_mod
    import core.smart_crop as sc_mod
    import numpy as np
    monkeypatch.setattr(fq_mod, "motion_profile", lambda *a, **k: None)
    monkeypatch.setattr(sc_mod, "find_focus", lambda *a, **k: None)

    def fake_change_profile(path, start, end):
        times = np.arange(start, end, 1 / 8.0) + 1 / 16.0
        diffs = np.where((times >= 30.0) & (times <= 70.0), 0.5, 10.0)
        return times, diffs
    monkeypatch.setattr(fq_mod, "change_profile", fake_change_profile)

    project = Project(name="sneaky-pause", target_duration=30,
                      fpv_style="smooth", fpv_pause_out=0.5)
    storage.save_project(project)
    video = SourceVideo(project_id=project.id, path=str(synthetic_video),
                        duration=100.0, fps=30, width=640, height=360,
                        fpv_showroom=True, valid=True)
    storage.save_video(video)
    scenes = []
    for i in range(10):
        pausing = 3 <= i <= 6  # 30-70с — пауза, но помечена коварно
        scenes.append(Scene(
            project_id=project.id, video_id=video.id,
            video_path=str(synthetic_video),
            start=i * 10.0, end=(i + 1) * 10.0,
            quality_score=0.7, aesthetic_score=0.5,
            people_count=1,                 # «человек» есть ВЕЗДЕ (ложный тоже)
            motion="slow",                  # и никакой сцены-статики
            llm_status="done"))
    storage.save_scenes(scenes)
    storage.save_zone(Zone(project_id=project.id, video_id=video.id,
                           start=0.0, end=100.0, title="маршрут",
                           required=True, technical=False))

    plan = build_fpv_plan(storage, project, video)

    # пауза 30-70с сжата: суммарное экранное время её кусков ≤ ~0.7с
    pause_out = sum(s.out_duration for s in plan.segments
                    if s.src_start >= 29.0 and s.src_end <= 71.0)
    assert pause_out <= 1.0, f"пауза заняла {pause_out:.2f}с в ролике"
    # и ни одного нормально-скоростного окна внутри паузы
    for seg in plan.segments:
        if seg.speed == 1.0:
            assert seg.src_end <= 31.0 or seg.src_start >= 69.0, \
                f"окно {seg.src_start}-{seg.src_end} стоит на паузе"
    # маршрут непрерывен
    covered = sorted((s.src_start, s.src_end) for s in plan.segments)
    for a, b in zip(covered, covered[1:]):
        assert b[0] >= a[1] - 0.01
