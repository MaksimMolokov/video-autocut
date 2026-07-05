"""SQLite-хранилище проектов (ТЗ §19).

Одна БД на всё приложение: projects/app.db.
Файлы проекта (превью, рендеры, кэш) — в projects/<project_id>/.
Dataclass-модели сериализуются в JSON-колонку `data` + индексируемые поля,
чтобы схема не ломалась при эволюции моделей.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, fields
from pathlib import Path

import config
from core.models import MontagePlan, PlanSegment, Project, Scene, SourceVideo

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    path TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    video_id TEXT NOT NULL REFERENCES videos(id),
    llm_status TEXT NOT NULL DEFAULT 'pending',
    user_flag TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replacements (   -- история замен (ТЗ §14, §19)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    old_scene_id TEXT NOT NULL,
    new_scene_id TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec'))
);
CREATE INDEX IF NOT EXISTS idx_scenes_project ON scenes(project_id);
CREATE INDEX IF NOT EXISTS idx_videos_project ON videos(project_id);
CREATE INDEX IF NOT EXISTS idx_plans_project ON plans(project_id);
"""


def _load(cls, row_data: str):
    """JSON → dataclass, игнорируя неизвестные поля (эволюция схемы)."""
    raw = json.loads(row_data)
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in known})


class Storage:
    """Потокобезопасно для Streamlit: одно соединение (check_same_thread=False),
    все операции сериализуются RLock-ом."""

    def __init__(self, db_path: Path | None = None):
        config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (config.PROJECTS_DIR / "app.db")
        # Streamlit выполняет rerun-ы в разных потоках — одно соединение
        # шарится между ними под замком
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)

    def close(self):
        with self._lock:
            self.conn.close()

    def _query(self, sql: str, args: tuple | list = ()) -> list:
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def _write(self, sql: str, args: tuple | list = (), many: bool = False):
        with self._lock:
            if many:
                self.conn.executemany(sql, args)
            else:
                self.conn.execute(sql, args)
            self.conn.commit()

    # --- Папки проекта ---
    def project_dir(self, project_id: str) -> Path:
        d = config.PROJECTS_DIR / project_id
        for sub in ("thumbnails", "previews", "render", "cache"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        return d

    # --- Projects ---
    def save_project(self, p: Project):
        self._write(
            "INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?)",
            (p.id, p.name, p.status, p.created_at, json.dumps(asdict(p), ensure_ascii=False)),
        )

    def get_project(self, project_id: str) -> Project | None:
        rows = self._query("SELECT data FROM projects WHERE id=?", (project_id,))
        return _load(Project, rows[0][0]) if rows else None

    def list_projects(self) -> list[Project]:
        rows = self._query("SELECT data FROM projects ORDER BY created_at DESC")
        return [_load(Project, r[0]) for r in rows]

    # --- Videos ---
    def save_video(self, v: SourceVideo):
        self._write(
            "INSERT OR REPLACE INTO videos VALUES (?,?,?,?)",
            (v.id, v.project_id, v.path, json.dumps(asdict(v), ensure_ascii=False)),
        )

    def list_videos(self, project_id: str) -> list[SourceVideo]:
        rows = self._query("SELECT data FROM videos WHERE project_id=?", (project_id,))
        return [_load(SourceVideo, r[0]) for r in rows]

    # --- Scenes ---
    def save_scene(self, s: Scene):
        self._write(
            "INSERT OR REPLACE INTO scenes VALUES (?,?,?,?,?,?)",
            (s.id, s.project_id, s.video_id, s.llm_status, s.user_flag,
             json.dumps(asdict(s), ensure_ascii=False)),
        )

    def save_scenes(self, scenes: list[Scene]):
        self._write(
            "INSERT OR REPLACE INTO scenes VALUES (?,?,?,?,?,?)",
            [(s.id, s.project_id, s.video_id, s.llm_status, s.user_flag,
              json.dumps(asdict(s), ensure_ascii=False)) for s in scenes],
            many=True,
        )

    def get_scene(self, scene_id: str) -> Scene | None:
        rows = self._query("SELECT data FROM scenes WHERE id=?", (scene_id,))
        return _load(Scene, rows[0][0]) if rows else None

    def list_scenes(self, project_id: str, llm_status: str | None = None) -> list[Scene]:
        q, args = "SELECT data FROM scenes WHERE project_id=?", [project_id]
        if llm_status:
            q += " AND llm_status=?"
            args.append(llm_status)
        rows = self._query(q, args)
        scenes = [_load(Scene, r[0]) for r in rows]
        scenes.sort(key=lambda s: (s.video_path, s.start))
        return scenes

    # --- Plans ---
    def save_plan(self, plan: MontagePlan):
        self._write(
            "INSERT OR REPLACE INTO plans VALUES (?,?,?,?,?)",
            (plan.id, plan.project_id, plan.status, plan.created_at,
             json.dumps(asdict(plan), ensure_ascii=False)),
        )

    def get_plan(self, plan_id: str) -> MontagePlan | None:
        rows = self._query("SELECT data FROM plans WHERE id=?", (plan_id,))
        if not rows:
            return None
        raw = json.loads(rows[0][0])
        segs = [PlanSegment(**s) for s in raw.pop("segments", [])]
        known = {f.name for f in fields(MontagePlan)} - {"segments"}
        plan = MontagePlan(**{k: v for k, v in raw.items() if k in known})
        plan.segments = segs
        return plan

    def latest_plan(self, project_id: str) -> MontagePlan | None:
        rows = self._query(
            "SELECT id FROM plans WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        )
        return self.get_plan(rows[0][0]) if rows else None

    # --- История замен (ТЗ §14) ---
    def log_replacement(self, plan_id: str, segment_id: str, old_scene_id: str, new_scene_id: str):
        self._write(
            "INSERT INTO replacements (plan_id, segment_id, old_scene_id, new_scene_id) VALUES (?,?,?,?)",
            (plan_id, segment_id, old_scene_id, new_scene_id),
        )
