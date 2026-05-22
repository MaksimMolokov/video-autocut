"""
SQLite-backed cache for ClipFeatures analysis results.
Key: (video filename + file size + start + end)
Invalidation: by file modification time (within 1s tolerance).
"""
import sqlite3
import json
import time
import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DB_NAME = "analysis_cache.db"


class AnalysisCache:
    """
    Persists ClipFeatures to disk so large videos don't re-analyze on every run.
    Thread-safe via SQLite WAL mode.
    """

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / _DB_NAME
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clip_features (
                    cache_key   TEXT PRIMARY KEY,
                    file_mtime  REAL NOT NULL,
                    features_json TEXT NOT NULL,
                    created_at  REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ck ON clip_features(cache_key)"
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _make_key(video_path: str, start: float, end: float) -> str:
        path = Path(video_path)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        raw = f"{path.name}:{size}:{start:.3f}:{end:.3f}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, video_path: str, start: float, end: float):
        """Return cached ClipFeatures or None if miss/stale."""
        from src.video_analysis.feature_extractor import ClipFeatures
        try:
            path = Path(video_path)
            if not path.exists():
                return None
            mtime = path.stat().st_mtime
            key = self._make_key(video_path, start, end)
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT file_mtime, features_json FROM clip_features WHERE cache_key=?",
                    (key,),
                ).fetchone()
            if row and abs(row["file_mtime"] - mtime) < 2.0:
                return ClipFeatures.from_dict(json.loads(row["features_json"]))
        except Exception as e:
            logger.debug(f"AnalysisCache.get: {e}")
        return None

    def set(self, video_path: str, start: float, end: float, features) -> None:
        """Store ClipFeatures in cache."""
        try:
            path = Path(video_path)
            mtime = path.stat().st_mtime if path.exists() else 0.0
            key = self._make_key(video_path, start, end)
            features_json = json.dumps(features.to_dict())
            with self._conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO clip_features
                       (cache_key, file_mtime, features_json, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (key, mtime, features_json, time.time()),
                )
        except Exception as e:
            logger.debug(f"AnalysisCache.set: {e}")

    def clear_old(self, max_age_days: int = 30) -> int:
        """Delete entries older than max_age_days. Returns deleted count."""
        try:
            cutoff = time.time() - max_age_days * 86400
            with self._conn() as conn:
                cur = conn.execute(
                    "DELETE FROM clip_features WHERE created_at < ?", (cutoff,)
                )
                return cur.rowcount
        except Exception as e:
            logger.debug(f"AnalysisCache.clear_old: {e}")
            return 0

    def clear_all(self) -> None:
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM clip_features")
        except Exception as e:
            logger.debug(f"AnalysisCache.clear_all: {e}")

    def stats(self) -> dict:
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(features_json)),0) AS sz "
                    "FROM clip_features"
                ).fetchone()
                return {"entries": row["n"], "size_bytes": row["sz"]}
        except Exception:
            return {"entries": 0, "size_bytes": 0}


# Module-level singleton — lazy-initialized when first used.
_global_cache: Optional[AnalysisCache] = None


_DEFAULT_CACHE_DIR = Path.home() / ".video_editor_analysis_cache"


def get_cache(cache_dir: Optional[str | Path] = None) -> Optional[AnalysisCache]:
    """
    Return (or create) the module-level AnalysisCache.
    If *cache_dir* is None, uses ~/.video_editor_analysis_cache so the
    cache persists across projects and Streamlit restarts.
    """
    global _global_cache
    if _global_cache is not None:
        return _global_cache
    target_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
    try:
        _global_cache = AnalysisCache(target_dir)
        return _global_cache
    except Exception as e:
        logger.warning(f"Could not init AnalysisCache: {e}")
        return None
