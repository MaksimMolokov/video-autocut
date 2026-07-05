"""Модели: сущности, вычисляемые поля, сериализация."""
import json

from core.models import (SCENE_TYPES, STORY_SLOTS, MontagePlan, PlanSegment,
                         Project, Scene, SourceVideo)


def test_project_defaults_and_json():
    p = Project(name="Тест")
    assert p.id and p.status == "new"
    assert p.aspect == "9:16" and p.target_duration == 30
    data = json.loads(p.to_json())
    assert data["name"] == "Тест"


def test_unique_ids():
    ids = {Project(name="x").id for _ in range(50)}
    assert len(ids) == 50


def test_scene_duration():
    s = Scene(video_id="v", video_path="/x.mp4", start=2.0, end=5.5)
    assert s.duration == 3.5
    assert s.llm_status == "pending"


def test_scene_llm_card_fields():
    s = Scene(video_id="v", video_path="/x.mp4", start=0, end=4,
              description="кафе", tags=["food"], scene_type="food",
              quality_score=0.9, aesthetic_score=0.8, motion="slow",
              motion_type="pan", people_count=2)
    card = s.llm_card()
    assert card["id"] == s.id
    assert card["duration"] == 4
    assert card["scene_type"] == "food"
    assert card["people_count"] == 2
    # карточка компактная: без путей и превью
    assert "video_path" not in card and "thumbnail_path" not in card


def test_plan_segment_and_total():
    segs = [
        PlanSegment(scene_id="a", order=0, src_start=1, src_end=4, slot="intro"),
        PlanSegment(scene_id="b", order=1, src_start=0, src_end=2.5, slot="main"),
    ]
    plan = MontagePlan(project_id="p", segments=segs)
    assert segs[0].duration == 3.0
    assert plan.total_duration == 5.5
    assert plan.status == "draft"


def test_scene_types_and_slots_consistency():
    # слоты драматургии и типы сцен из ТЗ §9, §12
    assert "intro" in SCENE_TYPES and "climax" in SCENE_TYPES
    assert STORY_SLOTS == ["intro", "development", "main", "climax", "ending"]


def test_source_video_defaults():
    v = SourceVideo(project_id="p", path="/x.mp4")
    assert v.valid and v.error == ""
