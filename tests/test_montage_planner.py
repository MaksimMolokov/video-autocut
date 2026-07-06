"""Montage Planner: слоты, скоринг, анти-повторы, биты, пометки пользователя."""
import pytest

from core.audio_analyzer import MusicAnalysis
from core.models import Project, Scene
from core.montage_planner import _pick_fragment, _score, _snap_to_beats, build_plan
from core.presets import SlotSpec


def _scene(video_id="v1", start=0.0, end=8.0, scene_type="location",
           quality=0.8, aesthetic=0.7, motion="slow", stability=0.9, **kw) -> Scene:
    return Scene(video_id=video_id, video_path=f"/{video_id}.mp4",
                 start=start, end=end, scene_type=scene_type,
                 quality_score=quality, aesthetic_score=aesthetic,
                 motion=motion, stability_score=stability, llm_status="done", **kw)


def _library(n=12, videos=("v1", "v2", "v3")) -> list[Scene]:
    types = ["establishing", "location", "detail", "action", "people", "climax"]
    return [
        _scene(video_id=videos[i % len(videos)], start=i * 10.0, end=i * 10.0 + 8.0,
               scene_type=types[i % len(types)])
        for i in range(n)
    ]


def _project(**kw) -> Project:
    defaults = dict(name="t", preset_id="generic", target_duration=30, sync_to_music=True)
    defaults.update(kw)
    return Project(**defaults)


def test_plan_fills_target_duration():
    plan = build_plan(_project(), _library(), music=None, use_llm=False)
    assert plan.segments
    assert 0.7 * 30 <= plan.total_duration <= 30 + 0.5


def test_plan_dramaturgy_order():
    """Слоты идут по драматургии: intro первым, ending последним (ТЗ §12)."""
    plan = build_plan(_project(), _library(), music=None, use_llm=False)
    slots = [s.slot for s in plan.segments]
    assert slots[0] == "intro"
    assert slots[-1] == "ending"
    assert slots == sorted(slots, key=["intro", "development", "main",
                                       "climax", "ending"].index)


def test_plan_no_duplicate_scenes():
    plan = build_plan(_project(), _library(), music=None, use_llm=False)
    ids = [s.scene_id for s in plan.segments]
    assert len(ids) == len(set(ids))


def test_plan_every_segment_has_reason():
    plan = build_plan(_project(), _library(), music=None, use_llm=False)
    assert all(seg.reason for seg in plan.segments)  # прозрачность (ТЗ §2)


def test_plan_no_consecutive_same_video_when_choice_exists():
    plan = build_plan(_project(), _library(), music=None, use_llm=False)
    scenes_by_id = {s.id: s for s in _library()}
    # восстановить сцены по факту нельзя (id новые), проверяем через план+сцены не выйдет —
    # поэтому строим план на явной библиотеке
    lib = _library()
    plan = build_plan(_project(), lib, music=None, use_llm=False)
    by_id = {s.id: s for s in lib}
    videos = [by_id[seg.scene_id].video_id for seg in plan.segments]
    assert all(a != b for a, b in zip(videos, videos[1:]))


def test_plan_single_video_source_still_works():
    """Все сцены из одного файла — план всё равно собирается (регрессия бага)."""
    lib = _library(videos=("v1",))
    plan = build_plan(_project(), lib, music=None, use_llm=False)
    assert plan.total_duration >= 0.6 * 30


def test_banned_scenes_excluded():
    lib = _library()
    for s in lib:
        s.user_flag = "banned"
    with pytest.raises(ValueError):
        build_plan(_project(), lib, music=None, use_llm=False)


def test_not_usable_tag_excluded():
    lib = _library(n=6, videos=("v1",))
    for s in lib[:5]:
        s.tags.append("not-usable")
    plan = build_plan(_project(), lib, music=None, use_llm=False)
    used = {seg.scene_id for seg in plan.segments}
    assert used <= {lib[5].id}


def test_pinned_scene_wins_slot():
    lib = _library()
    # закрепляем худшую по качеству сцену типа establishing
    pinned = _scene(video_id="v9", start=0, end=8, scene_type="establishing",
                    quality=0.3, aesthetic=0.1)
    pinned.user_flag = "pinned"
    lib.append(pinned)
    plan = build_plan(_project(), lib, music=None, use_llm=False)
    assert plan.segments[0].scene_id == pinned.id  # intro достаётся закреплённой


def test_fast_scene_nearly_banned_in_intro_and_ending():
    """Быстрый пролёт не должен открывать/закрывать спокойный ролик."""
    intro_spec = SlotSpec(slot="intro", share=0.15,
                          scene_types=["establishing"], prefer_motion=["slow"])
    fast = _scene(scene_type="establishing", motion="fast")
    slow = _scene(scene_type="establishing", motion="slow", quality=0.5, aesthetic=0.4)
    score_fast, _ = _score(fast, intro_spec)
    score_slow, _ = _score(slow, intro_spec)
    assert score_slow > score_fast  # слабый спокойный кадр лучше быстрого смаза


def test_shaky_scenes_excluded_from_plan():
    """Дёрганые сцены не попадают в монтаж, когда есть стабильные."""
    lib = _library()
    shaky = _scene(video_id="v9", start=0, end=8, scene_type="establishing",
                   quality=0.9, aesthetic=0.9)
    shaky.motion_type = "shake"
    shaky.stability_score = 0.2
    shaky.jerkiness = 0.8
    lib.append(shaky)
    plan = build_plan(_project(), lib, music=None, use_llm=False)
    used = {seg.scene_id for seg in plan.segments}
    assert shaky.id not in used


def test_pinned_shaky_scene_still_allowed():
    """Закреплённая пользователем сцена идёт в монтаж даже дёрганая (ТЗ §15)."""
    lib = _library()
    shaky = _scene(video_id="v9", start=0, end=8, scene_type="establishing")
    shaky.motion_type = "shake"
    shaky.stability_score = 0.2
    shaky.user_flag = "pinned"
    lib.append(shaky)
    plan = build_plan(_project(), lib, music=None, use_llm=False)
    used = {seg.scene_id for seg in plan.segments}
    assert shaky.id in used


def test_stabilize_option_keeps_shaky_scenes():
    """stabilize_shaky=True: дёрганые сцены остаются в пуле планировщика."""
    lib = _library(n=4, videos=("v1", "v2"))
    shaky = _scene(video_id="v9", scene_type="establishing",
                   quality=0.9, aesthetic=0.9, stability=0.2)
    shaky.motion_type = "shake"
    shaky.jerkiness = 0.8
    lib.append(shaky)
    # выкл (default) — исключена
    plan_off = build_plan(_project(), lib, music=None, use_llm=False)
    assert shaky.id not in {s.scene_id for s in plan_off.segments}
    # вкл — участвует и берётся (качество у неё выше всех)
    plan_on = build_plan(_project(stabilize_shaky=True), lib,
                         music=None, use_llm=False)
    assert shaky.id in {s.scene_id for s in plan_on.segments}


def test_speech_segments_adjust_fragment():
    """Фрагмент сцены с речью сдвигается, чтобы не резать фразу."""
    s = _scene(start=0.0, end=20.0)
    s.best_moment = 10.0
    s.speech_segments = [[8.5, 12.5, "важная фраза до конца"]]
    plan = build_plan(_project(), [s] + _library(n=6), music=None, use_llm=False)
    for seg in plan.segments:
        if seg.scene_id == s.id:
            # границы фрагмента не внутри фразы
            for edge in (seg.src_start, seg.src_end):
                assert not (8.5 < edge < 12.5), f"склейка режет фразу: {edge}"


def test_all_shaky_fallback_least_jerky():
    """Если ВСЁ дёрганое — план всё равно собирается из наименее дёрганых."""
    lib = _library(n=8, videos=("v1", "v2"))
    for i, s in enumerate(lib):
        s.motion_type = "shake"
        s.stability_score = 0.2
        s.jerkiness = 0.5 + i * 0.05
    plan = build_plan(_project(), lib, music=None, use_llm=False)
    assert plan.segments  # не упали, черновик есть
    used_jerk = [s.jerkiness for s in lib if s.id in {g.scene_id for g in plan.segments}]
    assert max(used_jerk) <= sorted(s.jerkiness for s in lib)[len(lib) // 2]


def test_similar_scenes_same_video_adjacent():
    from core.montage_planner import _similar_scenes
    a = _scene(video_id="v1", start=0, end=8)
    b = _scene(video_id="v1", start=10, end=18)   # соседний кусок пролёта
    c = _scene(video_id="v1", start=100, end=108)  # далеко — другой эпизод
    assert _similar_scenes(a, b, {})
    assert not _similar_scenes(a, c, {})


def test_similar_scenes_by_tags():
    from core.montage_planner import _similar_scenes
    a = _scene(video_id="v1", start=0, end=8, scene_type="action")
    b = _scene(video_id="v2", start=0, end=8, scene_type="action")
    a.tags = ["beach", "people", "running"]; a.objects = ["men", "sand"]
    b.tags = ["beach", "people", "running"]; b.objects = ["men", "sand"]
    assert _similar_scenes(a, b, {})               # нет миниатюр → доверяем тегам
    b.tags = ["city", "night"]; b.objects = ["car"]
    assert not _similar_scenes(a, b, {})


def test_plan_avoids_duplicate_looking_scenes():
    """Две почти одинаковые сцены не попадают в один ролик, пока есть выбор."""
    lib = _library(n=10)
    twin_a = _scene(video_id="v7", start=0, end=8, scene_type="action",
                    quality=0.95, aesthetic=0.95)
    twin_b = _scene(video_id="v8", start=0, end=8, scene_type="action",
                    quality=0.95, aesthetic=0.95)
    for t in (twin_a, twin_b):
        t.tags = ["beach", "running", "people"]
        t.objects = ["two-men", "sand", "waves"]
    lib += [twin_a, twin_b]
    plan = build_plan(_project(), lib, music=None, use_llm=False)
    used = {s.scene_id for s in plan.segments}
    assert not ({twin_a.id, twin_b.id} <= used)   # обе сразу — никогда


def test_best_window_avoids_camera_whip(mixed_motion_video):
    """Ядро фикса «фрагменты на разворотах»: скользящее окно обходит
    резкий разворот камеры в середине куска."""
    from core.montage_planner import _pick_best_window
    s = _scene(video_id="vm", start=0.0, end=8.0)
    s.video_path = str(mixed_motion_video)
    s.best_moment = 4.0  # самый резкий кадр мог попасть и на разворот
    window = _pick_best_window(s, 2.5, prefer_motion=["slow"])
    assert window is not None
    st, en = window
    # окно не накрывает ядро разворота (3.5–4.5с)
    overlap = max(0.0, min(en, 4.5) - max(st, 3.5))
    assert overlap < 0.3, f"окно {st}-{en} легло на разворот"


def test_best_window_rejects_fully_shaky(shaky_video):
    """Вся сцена дёрганая → None, кандидат отклоняется целиком."""
    from core.montage_planner import _pick_best_window
    s = _scene(video_id="vs", start=0.2, end=3.8)
    s.video_path = str(shaky_video)
    assert _pick_best_window(s, 2.0, prefer_motion=[]) is None


def test_pick_fragment_centers_on_best_moment():
    s = _scene(start=10.0, end=20.0)
    s.best_moment = 12.0
    start, end = _pick_fragment(s, 4.0)
    assert start <= 12.0 <= end                   # лучший момент внутри окна
    assert (start, end) == (10.0, 14.0)           # окно прижато к границе


def test_pick_fragment_best_moment_fallback():
    s = _scene(start=10.0, end=20.0)              # best_moment=0 → середина
    start, end = _pick_fragment(s, 4.0)
    assert (start, end) == (13.0, 17.0)


def test_plan_carries_transition_from_preset():
    plan = build_plan(_project(preset_id="slow_cinematic"), _library(),
                      music=None, use_llm=False)
    assert plan.transition == "crossfade" and plan.transition_duration == 0.6
    plan2 = build_plan(_project(preset_id="tiktok_clip"), _library(),
                       music=None, use_llm=False)
    assert plan2.transition == "cut" and plan2.transition_duration == 0.0


def test_snap_to_beats_with_overlap():
    """При crossfade середина перехода (а не жёсткий стык) ложится на бит."""
    from core.models import MontagePlan, PlanSegment
    plan = MontagePlan(project_id="p", segments=[
        PlanSegment(scene_id="a", order=0, src_start=0.0, src_end=4.0, slot="intro"),
        PlanSegment(scene_id="b", order=1, src_start=0.0, src_end=4.0, slot="main"),
    ])
    # overlap 0.4 → видимая склейка на 4.0-0.2=3.8; бит на 4.0 → delta 0.2
    _snap_to_beats(plan, [4.0], overlap=0.4)
    assert plan.segments[0].beat_synced
    assert abs(plan.segments[0].duration - 4.2) < 0.01


def test_variant_changes_plan():
    """variant>0 даёт другую сборку; тот же variant — воспроизводимую."""
    lib = _library(n=15)
    base = build_plan(_project(), lib, music=None, use_llm=False, variant=0)
    v1a = build_plan(_project(), lib, music=None, use_llm=False, variant=1)
    v1b = build_plan(_project(), lib, music=None, use_llm=False, variant=1)

    def order(p):
        return [s.scene_id for s in p.segments]

    assert order(v1a) == order(v1b)          # воспроизводимость
    assert order(v1a) != order(base)         # действительно другой вариант
    # структура валидна: длительность в норме
    assert 0.6 * 30 <= v1a.total_duration <= 30.5


def test_variant_keeps_pinned():
    """Перемешивание вариантов не выбрасывает закреплённые сцены."""
    lib = _library()
    pinned = _scene(video_id="v9", scene_type="establishing")
    pinned.user_flag = "pinned"
    lib.append(pinned)
    for v in (1, 2, 3):
        plan = build_plan(_project(), lib, music=None, use_llm=False, variant=v)
        assert pinned.id in {s.scene_id for s in plan.segments}


def test_llm_rank_chunks():
    from core.montage_planner import _RANK_BATCH, _chunks
    items = list(range(60))
    chunks = _chunks(items, _RANK_BATCH)
    assert [len(c) for c in chunks] == [25, 25, 10]
    assert sum(chunks, []) == items


def test_alternatives_stored():
    plan = build_plan(_project(), _library(), music=None, use_llm=False)
    assert isinstance(plan.alternatives, dict)
    assert set(plan.alternatives) <= {"intro", "development", "main", "climax", "ending"}


def test_scenario_match_score_affects_ranking():
    spec = SlotSpec(slot="main", share=0.3, scene_types=["action"])
    s_low = _scene(scene_type="action")
    s_high = _scene(scene_type="action")
    s_high.scenario_match_score = 0.95
    s_low.scenario_match_score = 0.1
    score_high, _ = _score(s_high, spec)
    score_low, _ = _score(s_low, spec)
    assert score_high > score_low


def test_pick_fragment_centered():
    s = _scene(start=10.0, end=20.0)
    start, end = _pick_fragment(s, 4.0)
    assert abs((start - 10.0) - (20.0 - end)) < 0.01  # симметричные отступы
    assert abs((end - start) - 4.0) < 0.01


def test_pick_fragment_whole_scene():
    s = _scene(start=5.0, end=8.0)
    assert _pick_fragment(s, 5.0) == (5.0, 8.0)


def test_snap_to_beats():
    from core.models import MontagePlan, PlanSegment
    plan = MontagePlan(project_id="p", segments=[
        PlanSegment(scene_id="a", order=0, src_start=0.0, src_end=3.8, slot="intro"),
    ])
    _snap_to_beats(plan, [4.0, 8.0])
    seg = plan.segments[0]
    assert seg.beat_synced
    assert abs(seg.duration - 4.0) < 0.01


def test_snap_to_beats_respects_tolerance():
    from core.models import MontagePlan, PlanSegment
    plan = MontagePlan(project_id="p", segments=[
        PlanSegment(scene_id="a", order=0, src_start=0.0, src_end=3.0, slot="intro"),
    ])
    _snap_to_beats(plan, [5.0])  # слишком далеко (2 сек)
    assert not plan.segments[0].beat_synced
    assert plan.segments[0].duration == 3.0


def test_plan_selects_music_cue():
    """План с музыкой получает offset и фейды (умный подбор фрагмента)."""
    curve = [0.2] * 10 + [0.5] * 20 + [1.0] * 20 + [0.3] * 10  # 60 сек трека
    music = MusicAnalysis(path="x", duration=60.0, bpm=120,
                          beats=[i * 0.5 for i in range(120)],
                          downbeats=[i * 2.0 for i in range(30)],
                          energy_curve=curve,
                          cut_points=[i * 2.0 for i in range(30)])
    plan = build_plan(_project(), _library(), music=music, use_llm=False)
    assert plan.music_offset >= 0.0
    assert plan.music_offset <= 60.0 - plan.total_duration + 0.01
    assert plan.music_fade_in > 0 and plan.music_fade_out > 0
