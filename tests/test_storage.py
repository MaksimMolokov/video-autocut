"""SQLite-хранилище: CRUD всех сущностей, история замен, эволюция схемы."""
import json

from core.models import MontagePlan, PlanSegment, Project, Scene, SourceVideo


def test_project_roundtrip(storage):
    p = Project(name="Ролик", source_paths=["/a.mp4"], music_path="/m.mp3",
                preset_id="restaurant", aspect="16:9", target_duration=45)
    storage.save_project(p)
    got = storage.get_project(p.id)
    assert got.name == "Ролик" and got.aspect == "16:9"
    assert got.source_paths == ["/a.mp4"] and got.target_duration == 45


def test_get_missing_returns_none(storage):
    assert storage.get_project("nope") is None
    assert storage.get_scene("nope") is None
    assert storage.get_plan("nope") is None
    assert storage.latest_plan("nope") is None


def test_list_projects_ordering(storage):
    p1 = Project(name="старый", created_at=100.0)
    p2 = Project(name="новый", created_at=200.0)
    storage.save_project(p1)
    storage.save_project(p2)
    assert [p.name for p in storage.list_projects()] == ["новый", "старый"]


def test_video_roundtrip(storage):
    v = SourceVideo(project_id="p1", path="/x.mp4", duration=10.5, fps=29.97,
                    width=1920, height=1080, orientation="horizontal", has_audio=True)
    storage.save_video(v)
    got = storage.list_videos("p1")[0]
    assert got.fps == 29.97 and got.has_audio


def test_scenes_roundtrip_and_filter(storage):
    s1 = Scene(project_id="p1", video_id="v1", video_path="/x.mp4",
               start=0, end=3, llm_status="done", tags=["food"])
    s2 = Scene(project_id="p1", video_id="v1", video_path="/x.mp4",
               start=3, end=6, llm_status="pending")
    storage.save_scenes([s1, s2])
    assert len(storage.list_scenes("p1")) == 2
    pending = storage.list_scenes("p1", llm_status="pending")
    assert [s.id for s in pending] == [s2.id]
    # сортировка по видео и старту
    assert storage.list_scenes("p1")[0].start == 0


def test_scene_update_overwrites(storage):
    s = Scene(project_id="p1", video_id="v1", video_path="/x.mp4", start=0, end=3)
    storage.save_scene(s)
    s.user_flag = "pinned"
    s.description = "закат"
    storage.save_scene(s)
    got = storage.get_scene(s.id)
    assert got.user_flag == "pinned" and got.description == "закат"
    assert len(storage.list_scenes("p1")) == 1


def test_plan_roundtrip_with_segments(storage):
    plan = MontagePlan(project_id="p1", segments=[
        PlanSegment(scene_id="s1", order=0, src_start=0, src_end=3, slot="intro",
                    reason="тест", beat_synced=True),
    ], alternatives={"intro": ["s2", "s3"]})
    storage.save_plan(plan)
    got = storage.get_plan(plan.id)
    assert got.total_duration == 3.0
    assert got.segments[0].beat_synced and got.segments[0].reason == "тест"
    assert got.alternatives["intro"] == ["s2", "s3"]


def test_latest_plan(storage):
    old = MontagePlan(project_id="p1", created_at=100.0)
    new = MontagePlan(project_id="p1", created_at=200.0)
    storage.save_plan(old)
    storage.save_plan(new)
    assert storage.latest_plan("p1").id == new.id


def test_replacement_history(storage):
    storage.log_replacement("plan1", "seg1", "old_scene", "new_scene")
    row = storage.conn.execute("SELECT * FROM replacements").fetchone()
    assert row[1:5] == ("plan1", "seg1", "old_scene", "new_scene")


def test_schema_evolution_ignores_unknown_fields(storage):
    """Записи со старыми/лишними полями не ломают загрузку."""
    p = Project(name="x")
    raw = json.loads(p.to_json())
    raw["legacy_field"] = 123
    storage.conn.execute(
        "INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?)",
        (p.id, p.name, p.status, p.created_at, json.dumps(raw)),
    )
    got = storage.get_project(p.id)
    assert got.name == "x" and not hasattr(got, "legacy_field")


def test_delete_project_removes_everything(storage):
    """Удаление проекта чистит все таблицы и файлы на диске."""
    p = Project(name="жертва")
    storage.save_project(p)
    storage.save_video(SourceVideo(project_id=p.id, path="/x.mp4"))
    sc = Scene(project_id=p.id, video_id="v1", video_path="/x.mp4", start=0, end=3)
    storage.save_scene(sc)
    plan = MontagePlan(project_id=p.id)
    storage.save_plan(plan)
    storage.log_replacement(plan.id, "seg1", "old", "new")
    pdir = storage.project_dir(p.id)
    (pdir / "render" / "draft.mp4").write_bytes(b"data")

    other = Project(name="сосед")
    storage.save_project(other)

    storage.delete_project(p.id)
    assert storage.get_project(p.id) is None
    assert storage.list_scenes(p.id) == []
    assert storage.list_videos(p.id) == []
    assert storage.latest_plan(p.id) is None
    assert storage.conn.execute("SELECT COUNT(*) FROM replacements").fetchone()[0] == 0
    assert not pdir.exists()
    assert storage.get_project(other.id) is not None  # сосед не пострадал


def test_threaded_access_like_streamlit(storage):
    """Регрессия: Streamlit дергает одно соединение из разных потоков.
    sqlite3.ProgrammingError 'objects created in a thread…' не должно быть."""
    import threading

    storage.save_project(Project(name="из главного потока"))
    errors: list[Exception] = []

    def worker(i: int):
        try:
            p = Project(name=f"из потока {i}")
            storage.save_project(p)
            assert storage.get_project(p.id) is not None
            storage.list_projects()
            storage.save_scene(Scene(project_id=p.id, video_id="v",
                                     video_path="/x.mp4", start=0, end=3))
            storage.list_scenes(p.id)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(storage.list_projects()) == 9  # 1 + 8 потоков


def test_project_dir_creates_subfolders(storage):
    d = storage.project_dir("proj1")
    for sub in ("thumbnails", "previews", "render", "cache"):
        assert (d / sub).is_dir()
