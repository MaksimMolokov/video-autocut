"""SQLite wrapper for video preprocessing analysis cache."""

import hashlib
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / 'schema.sql'


class AnalysisDB:
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self._db_dir = self.project_dir / '.videoeditor'
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._db_dir / 'analysis.db'
        self._conn: Optional[sqlite3.Connection] = None
        self._create_tables()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute('PRAGMA journal_mode=WAL')
            self._conn.execute('PRAGMA foreign_keys=ON')
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _create_tables(self):
        schema = _SCHEMA_PATH.read_text()
        conn = self._get_conn()
        conn.executescript(schema)
        conn.commit()
        self._migrate_v2()
        self._migrate_v3()

    def _migrate_v2(self):
        """Add v2 extended quality columns to existing fragments tables."""
        conn = self._get_conn()
        existing = {row[1] for row in conn.execute('PRAGMA table_info(fragments)').fetchall()}
        new_cols = [
            ('colorfulness',       'REAL'),
            ('complexity',         'REAL'),
            ('camera_motion_type', 'TEXT'),
        ]
        for col, dtype in new_cols:
            if col not in existing:
                conn.execute(f'ALTER TABLE fragments ADD COLUMN {col} {dtype}')
        conn.commit()

    def _migrate_v3(self):
        """Add v3 composition/coherence/saliency columns to existing fragments tables."""
        conn = self._get_conn()
        existing = {row[1] for row in conn.execute('PRAGMA table_info(fragments)').fetchall()}
        new_cols = [
            ('composition_score',  'REAL'),
            ('temporal_coherence', 'REAL'),
            ('saliency_score',     'REAL'),
        ]
        for col, dtype in new_cols:
            if col not in existing:
                conn.execute(f'ALTER TABLE fragments ADD COLUMN {col} {dtype}')
        conn.commit()

    # ------------------------------------------------------------------
    # File fingerprint
    # ------------------------------------------------------------------

    @staticmethod
    def _file_hash(path: str) -> str:
        try:
            with open(path, 'rb') as f:
                return hashlib.md5(f.read(65536)).hexdigest()
        except OSError:
            return ''

    @staticmethod
    def _file_size(path: str) -> int:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    # ------------------------------------------------------------------
    # Source files
    # ------------------------------------------------------------------

    def save_source_file(self, path: str) -> int:
        """Insert or update a source file record. Returns source_id."""
        conn = self._get_conn()
        file_hash = self._file_hash(path)
        file_size = self._file_size(path)
        filename = Path(path).name
        conn.execute(
            '''INSERT INTO source_files (path, filename, file_hash, file_size, status)
               VALUES (?, ?, ?, ?, 'pending')
               ON CONFLICT(path) DO UPDATE SET
                 filename=excluded.filename,
                 file_hash=excluded.file_hash,
                 file_size=excluded.file_size,
                 status=CASE WHEN file_hash != excluded.file_hash THEN 'pending' ELSE status END
            ''',
            (path, filename, file_hash, file_size),
        )
        conn.commit()
        row = conn.execute('SELECT id FROM source_files WHERE path=?', (path,)).fetchone()
        return row['id']

    def is_analyzed(self, path: str) -> bool:
        """True if file has status='analyzed' and file hash matches on disk."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT file_hash, status FROM source_files WHERE path=?", (path,)
        ).fetchone()
        if row is None or row['status'] != 'analyzed':
            return False
        current_hash = self._file_hash(path)
        return current_hash == row['file_hash']

    def mark_analyzed(self, path: str, duration_s: float = None, fps: float = None,
                      resolution: str = None):
        conn = self._get_conn()
        file_hash = self._file_hash(path)
        file_size = self._file_size(path)
        conn.execute(
            '''UPDATE source_files
               SET status='analyzed', analyzed_at=?, file_hash=?, file_size=?,
                   duration_s=?, fps=?, resolution=?, error_msg=NULL
               WHERE path=?''',
            (datetime.utcnow().isoformat(), file_hash, file_size,
             duration_s, fps, resolution, path),
        )
        conn.commit()

    def mark_error(self, path: str, error_msg: str):
        conn = self._get_conn()
        conn.execute(
            "UPDATE source_files SET status='error', error_msg=? WHERE path=?",
            (error_msg, path),
        )
        conn.commit()

    def get_source_id(self, path: str) -> Optional[int]:
        conn = self._get_conn()
        row = conn.execute('SELECT id FROM source_files WHERE path=?', (path,)).fetchone()
        return row['id'] if row else None

    # ------------------------------------------------------------------
    # Fragments
    # ------------------------------------------------------------------

    def save_fragments(self, source_id: int, fragments: List[Dict[str, Any]]):
        conn = self._get_conn()
        conn.execute('DELETE FROM fragments WHERE source_id=?', (source_id,))
        for f in fragments:
            conn.execute(
                '''INSERT INTO fragments (
                    source_id, start_s, end_s, duration_s,
                    sharpness, brightness, contrast, motion, stability, action, calm,
                    colorfulness, complexity, camera_motion_type,
                    composition_score, temporal_coherence, saliency_score,
                    has_face, has_person, has_subject, scene_type, scene_tag,
                    quality_score, cinematic_score, action_score, social_score, premium_score, travel_score,
                    crop_16_9, crop_9_16, crop_1_1,
                    is_duplicate, user_approved, user_priority, tags,
                    thumbnail_path, preview_path
                ) VALUES (
                    :source_id, :start_s, :end_s, :duration_s,
                    :sharpness, :brightness, :contrast, :motion, :stability, :action, :calm,
                    :colorfulness, :complexity, :camera_motion_type,
                    :composition_score, :temporal_coherence, :saliency_score,
                    :has_face, :has_person, :has_subject, :scene_type, :scene_tag,
                    :quality_score, :cinematic_score, :action_score, :social_score, :premium_score, :travel_score,
                    :crop_16_9, :crop_9_16, :crop_1_1,
                    :is_duplicate, :user_approved, :user_priority, :tags,
                    :thumbnail_path, :preview_path
                )''',
                {
                    'source_id': source_id,
                    'start_s': f.get('start_s', 0.0),
                    'end_s': f.get('end_s', 0.0),
                    'duration_s': f.get('duration_s', 0.0),
                    'sharpness': f.get('sharpness'),
                    'brightness': f.get('brightness'),
                    'contrast': f.get('contrast'),
                    'motion': f.get('motion'),
                    'stability': f.get('stability'),
                    'action': f.get('action'),
                    'calm': f.get('calm'),
                    'colorfulness': f.get('colorfulness'),
                    'complexity': f.get('complexity'),
                    'camera_motion_type': f.get('camera_motion_type'),
                    'composition_score': f.get('composition_score'),
                    'temporal_coherence': f.get('temporal_coherence'),
                    'saliency_score': f.get('saliency_score'),
                    'has_face': f.get('has_face'),
                    'has_person': f.get('has_person'),
                    'has_subject': f.get('has_subject'),
                    'scene_type': f.get('scene_type'),
                    'scene_tag': f.get('scene_tag'),
                    'quality_score': f.get('quality_score'),
                    'cinematic_score': f.get('cinematic_score'),
                    'action_score': f.get('action_score'),
                    'social_score': f.get('social_score'),
                    'premium_score': f.get('premium_score'),
                    'travel_score': f.get('travel_score'),
                    'crop_16_9': f.get('crop_16_9'),
                    'crop_9_16': f.get('crop_9_16'),
                    'crop_1_1': f.get('crop_1_1'),
                    'is_duplicate': int(f.get('is_duplicate', False)),
                    'user_approved': f.get('user_approved'),
                    'user_priority': f.get('user_priority'),
                    'tags': f.get('tags'),
                    'thumbnail_path': f.get('thumbnail_path'),
                    'preview_path': f.get('preview_path'),
                },
            )
        conn.commit()

    def count_fragments(self, min_quality: float = 0.0) -> int:
        conn = self._get_conn()
        row = conn.execute(
            'SELECT COUNT(*) as n FROM fragments WHERE quality_score >= ? AND is_duplicate=0',
            (min_quality,),
        ).fetchone()
        return row['n'] if row else 0

    def get_fragments_for_source(self, source_id: int) -> List[sqlite3.Row]:
        conn = self._get_conn()
        return conn.execute(
            'SELECT * FROM fragments WHERE source_id=? ORDER BY quality_score DESC',
            (source_id,),
        ).fetchall()

    def get_available_scene_tags(self) -> List[str]:
        """Return all distinct non-null scene_tag values present in fragments."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT scene_tag FROM fragments WHERE scene_tag IS NOT NULL ORDER BY scene_tag"
        ).fetchall()
        return [r[0] for r in rows]

    def get_fragments_filtered(
        self,
        source_ids: Optional[List[int]] = None,
        min_quality: float = 0.0,
        min_duration: float = 0.5,
        max_duration: float = 30.0,
        approved_only: bool = False,
        exclude_duplicates: bool = True,
        sort_by: str = 'quality_score',
        limit: int = 200,
        scene_tags: Optional[List[str]] = None,
    ) -> List[sqlite3.Row]:
        conn = self._get_conn()
        cond_parts = [
            'f.duration_s BETWEEN ? AND ?',
            'f.quality_score >= ?',
        ]
        params: List[Any] = [min_duration, max_duration, min_quality]

        if approved_only:
            cond_parts.append('f.user_approved = 1')
        else:
            cond_parts.append('(f.user_approved IS NULL OR f.user_approved = 1)')

        if exclude_duplicates:
            cond_parts.append('f.is_duplicate = 0')

        if source_ids is not None:
            placeholders = ','.join('?' * len(source_ids))
            cond_parts.append(f'f.source_id IN ({placeholders})')
            params.extend(source_ids)

        if scene_tags:
            placeholders = ','.join('?' * len(scene_tags))
            cond_parts.append(f'f.scene_tag IN ({placeholders})')
            params.extend(scene_tags)

        allowed_sorts = {'quality_score', 'cinematic_score', 'action_score',
                         'social_score', 'premium_score', 'travel_score', 'start_s'}
        sort_col = sort_by if sort_by in allowed_sorts else 'quality_score'

        where = ' AND '.join(cond_parts)
        sql = (
            'SELECT f.*, sf.path as source_path, sf.filename as filename '
            'FROM fragments f '
            'JOIN source_files sf ON f.source_id = sf.id '
            f'WHERE {where} ORDER BY f.{sort_col} DESC LIMIT ?'
        )
        params.append(limit)
        return conn.execute(sql, params).fetchall()

    def get_fragments_by_ids(self, fragment_ids) -> list:
        """Return (id, source_path, start_s, end_s) rows for the given fragment IDs."""
        ids = list(fragment_ids)
        if not ids:
            return []
        conn = self._get_conn()
        placeholders = ','.join('?' * len(ids))
        sql = (
            'SELECT f.id, f.start_s, f.end_s, sf.path as source_path '
            'FROM fragments f '
            'JOIN source_files sf ON f.source_id = sf.id '
            f'WHERE f.id IN ({placeholders})'
        )
        return conn.execute(sql, ids).fetchall()

    def update_fragment_approval(self, fragment_id: int, approved: Optional[bool]):
        conn = self._get_conn()
        value = None if approved is None else (1 if approved else 0)
        conn.execute('UPDATE fragments SET user_approved=? WHERE id=?', (value, fragment_id))
        conn.commit()

    def update_fragment_priority(self, fragment_id: int, priority: bool):
        conn = self._get_conn()
        conn.execute('UPDATE fragments SET user_priority=? WHERE id=?',
                     (1 if priority else None, fragment_id))
        conn.commit()

    def update_thumbnail_path(self, fragment_id: int, path: str):
        conn = self._get_conn()
        conn.execute('UPDATE fragments SET thumbnail_path=? WHERE id=?', (path, fragment_id))
        conn.commit()

    # ------------------------------------------------------------------
    # Project-level helpers
    # ------------------------------------------------------------------

    def get_all_source_ids_for_project(self) -> List[int]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id FROM source_files WHERE status='analyzed'"
        ).fetchall()
        return [r['id'] for r in rows]

    def get_analyzed_paths(self) -> List[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT path FROM source_files WHERE status='analyzed'"
        ).fetchall()
        return [r['path'] for r in rows]

    def get_pending_paths(self) -> List[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT path FROM source_files WHERE status IN ('pending','error')"
        ).fetchall()
        return [r['path'] for r in rows]

    def reset_all(self):
        """Delete all analysis data. Previews must be deleted separately."""
        conn = self._get_conn()
        conn.execute('DELETE FROM duplicates')
        conn.execute('DELETE FROM fragments')
        conn.execute('DELETE FROM source_files')
        conn.commit()
        logger.info('[AnalysisDB] All analysis data cleared')

    # ------------------------------------------------------------------
    # Render history (Idea 4)
    # ------------------------------------------------------------------

    def save_render(
        self,
        project_dir: str,
        style_id: str,
        style_name: str = '',
        music_path: Optional[str] = None,
        output_path: Optional[str] = None,
        quality_avg: Optional[float] = None,
        clip_count: Optional[int] = None,
        duration_s: Optional[float] = None,
    ) -> int:
        """Save a completed render to history. Returns the new record id."""
        conn = self._get_conn()
        cur = conn.execute(
            '''INSERT INTO render_history
               (project_dir, style_id, style_name, music_path, created_at,
                output_path, quality_avg, clip_count, duration_s)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                str(project_dir), style_id, style_name, music_path,
                datetime.utcnow().isoformat(),
                output_path, quality_avg, clip_count, duration_s,
            ),
        )
        conn.commit()
        return cur.lastrowid

    def set_render_rating(self, render_id: int, rating: int):
        """Set 1–5 star rating for a render."""
        conn = self._get_conn()
        conn.execute(
            'UPDATE render_history SET user_rating=? WHERE id=?',
            (max(1, min(5, rating)), render_id),
        )
        conn.commit()

    def get_render_history(
        self,
        project_dir: Optional[str] = None,
        limit: int = 50,
    ) -> List[sqlite3.Row]:
        """Return render history ordered newest first."""
        conn = self._get_conn()
        if project_dir:
            return conn.execute(
                '''SELECT * FROM render_history
                   WHERE project_dir=? ORDER BY created_at DESC LIMIT ?''',
                (str(project_dir), limit),
            ).fetchall()
        return conn.execute(
            'SELECT * FROM render_history ORDER BY created_at DESC LIMIT ?',
            (limit,),
        ).fetchall()

    def delete_render_history_entry(self, render_id: int):
        conn = self._get_conn()
        conn.execute('DELETE FROM render_history WHERE id=?', (render_id,))
        conn.commit()

    # ------------------------------------------------------------------
    # Music fragments
    # ------------------------------------------------------------------

    @staticmethod
    def _audio_hash(path: str) -> str:
        try:
            with open(path, 'rb') as f:
                return hashlib.md5(f.read(65536)).hexdigest()
        except OSError:
            return ''

    def is_music_analyzed(self, audio_path: str) -> bool:
        """True if DB has fragments for this audio file with matching content hash."""
        conn = self._get_conn()
        row = conn.execute(
            'SELECT audio_hash FROM music_fragments WHERE audio_file=? LIMIT 1',
            (audio_path,)
        ).fetchone()
        if row is None:
            return False
        return self._audio_hash(audio_path) == row['audio_hash']

    def save_music_fragments(self, audio_path: str, fragments: List[Dict[str, Any]]) -> None:
        conn = self._get_conn()
        audio_hash = self._audio_hash(audio_path)
        conn.execute('DELETE FROM music_fragments WHERE audio_file=?', (audio_path,))
        for f in fragments:
            conn.execute(
                '''INSERT INTO music_fragments
                   (audio_file, audio_hash, start_s, end_s, duration_s,
                    fragment_type, energy_score, rhythm_score, beat_clarity, montage_score,
                    reason, warnings, selected_by_system, selected_by_user, excluded_by_user, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    audio_path, audio_hash,
                    f.get('start_s', 0.0), f.get('end_s', 0.0), f.get('duration_s', 0.0),
                    f.get('fragment_type'), f.get('energy_score'), f.get('rhythm_score'),
                    f.get('beat_clarity'), f.get('montage_score'),
                    f.get('reason'), f.get('warnings'),
                    int(f.get('selected_by_system', 0)), f.get('selected_by_user'),
                    int(f.get('excluded_by_user', 0)), f.get('status', 'recommended'),
                ),
            )
        conn.commit()

    def get_music_fragments(self, audio_path: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            'SELECT * FROM music_fragments WHERE audio_file=? AND excluded_by_user=0 ORDER BY start_s',
            (audio_path,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_music_fragment_user_selection(
        self,
        fragment_id: int,
        selected_by_user: Optional[bool],
        excluded_by_user: bool = False,
    ) -> None:
        conn = self._get_conn()
        val = None if selected_by_user is None else (1 if selected_by_user else 0)
        conn.execute(
            'UPDATE music_fragments SET selected_by_user=?, excluded_by_user=? WHERE id=?',
            (val, int(excluded_by_user), fragment_id),
        )
        conn.commit()

    def get_selected_music_range(self, audio_path: str) -> Optional[tuple]:
        """Return (start_s, end_s) for user-selected music fragment, or None."""
        conn = self._get_conn()
        row = conn.execute(
            'SELECT start_s, end_s FROM music_fragments '
            'WHERE audio_file=? AND selected_by_user=1 LIMIT 1',
            (audio_path,)
        ).fetchone()
        return (row['start_s'], row['end_s']) if row else None

    def reset_music_fragments(self, audio_path: str) -> None:
        conn = self._get_conn()
        conn.execute('DELETE FROM music_fragments WHERE audio_file=?', (audio_path,))
        conn.commit()

    def get_source_files_status(self) -> List[Dict[str, Any]]:
        """Return status for all registered source files (path, status, error_msg, n_frags)."""
        conn = self._get_conn()
        rows = conn.execute(
            '''SELECT sf.path, sf.status, sf.error_msg, sf.duration_s,
                      COUNT(f.id) as n_frags
               FROM source_files sf
               LEFT JOIN fragments f ON f.source_id = sf.id
               GROUP BY sf.id
               ORDER BY sf.path'''
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        conn = self._get_conn()
        total_files = conn.execute('SELECT COUNT(*) FROM source_files').fetchone()[0]
        analyzed = conn.execute(
            "SELECT COUNT(*) FROM source_files WHERE status='analyzed'"
        ).fetchone()[0]
        total_frags = conn.execute('SELECT COUNT(*) FROM fragments').fetchone()[0]
        good_frags = conn.execute(
            'SELECT COUNT(*) FROM fragments WHERE quality_score >= 0.55 AND is_duplicate=0'
        ).fetchone()[0]
        last_analyzed = conn.execute(
            "SELECT MAX(analyzed_at) FROM source_files WHERE status='analyzed'"
        ).fetchone()[0]
        return {
            'total_files': total_files,
            'analyzed_files': analyzed,
            'total_fragments': total_frags,
            'good_fragments': good_frags,
            'last_analyzed': last_analyzed,
        }
