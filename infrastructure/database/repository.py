"""
Repository — data access layer (TASK-010).

All DB queries go through Repository classes. Services never touch SQL directly.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from infrastructure.database.models import (
    Duplicate, ClipCandidate, ManualSelection, MusicSection,
    Project, RenderJob, Scene, SchemaVersion, SourceVideo,
)

# Aliases to match usage throughout this file
Fragment      = ClipCandidate
ManualSegment = ManualSelection
MusicFragment = MusicSection
SourceFile    = SourceVideo


# ── Schema version (TASK-012) ──────────────────────────────────────────────────

class SchemaVersionRepo:
    def __init__(self, session: Session) -> None:
        self.db = session

    def get_current(self) -> int:
        row = self.db.query(SchemaVersion).order_by(SchemaVersion.id.desc()).first()
        return row.version if row else 0

    def set_version(self, version: int, description: str = "") -> None:
        self.db.add(SchemaVersion(version=version, applied_at=time.time(), description=description))
        self.db.commit()


# ── Source files ───────────────────────────────────────────────────────────────

class SourceFileRepo:
    def __init__(self, session: Session) -> None:
        self.db = session

    def get_or_create(self, rel_path: str, project_id: Optional[int] = None) -> SourceFile:
        q = self.db.query(SourceFile).filter_by(rel_path=rel_path)
        if project_id is not None:
            q = q.filter_by(project_id=project_id)
        row = q.first()
        if row is None:
            from pathlib import Path
            row = SourceFile(
                rel_path=rel_path,
                filename=Path(rel_path).name,
                project_id=project_id,
                status="pending",
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row

    def is_analyzed(self, rel_path: str, file_hash: str) -> bool:
        row = self.db.query(SourceFile).filter_by(rel_path=rel_path, file_hash=file_hash, status="analyzed").first()
        return row is not None

    def mark_analyzed(self, source_id: int, **kwargs: Any) -> None:
        row = self.db.get(SourceFile, source_id)
        if row:
            for k, v in kwargs.items():
                setattr(row, k, v)
            row.status = "analyzed"
            row.analyzed_at = time.time()
            self.db.commit()

    def mark_error(self, source_id: int, error_msg: str) -> None:
        row = self.db.get(SourceFile, source_id)
        if row:
            row.status = "error"
            row.error_msg = error_msg
            self.db.commit()

    def list_all(self, project_id: Optional[int] = None) -> List[SourceFile]:
        q = self.db.query(SourceFile)
        if project_id is not None:
            q = q.filter_by(project_id=project_id)
        return q.all()


# ── Fragments ──────────────────────────────────────────────────────────────────

class FragmentRepo:
    def __init__(self, session: Session) -> None:
        self.db = session

    # Field names that map from analysis dict keys to Fragment columns
    _FIELD_ALIASES = {
        "blur_score": "sharpness",           # blur_score → sharpness
        "reject_reason": "reject_reason",    # keep both reject_reason aliases
    }
    # Fields to skip (internal/transient, not persisted)
    _SKIP_FIELDS = {"_src_duration_s", "_phash", "_abs_path"}

    def save_many(self, source_id: int, fragments: List[Dict[str, Any]]) -> List[Fragment]:
        # Delete existing for this source to allow re-analysis
        self.db.query(Fragment).filter(Fragment.source_file_id == source_id).delete()
        self.db.commit()
        rows = []
        for f in fragments:
            # Build kwargs: only columns that exist on Fragment
            kwargs: Dict[str, Any] = {"source_file_id": source_id}
            for k, v in f.items():
                if k in self._SKIP_FIELDS:
                    continue
                target_key = self._FIELD_ALIASES.get(k, k)
                if hasattr(Fragment, target_key):
                    kwargs[target_key] = v
            row = Fragment(**kwargs)
            self.db.add(row)
            rows.append(row)
        self.db.commit()
        for r in rows:
            self.db.refresh(r)
        return rows

    def get_for_source(self, source_id: int) -> List[Fragment]:
        """Return all fragments for a specific source file, ordered by start_s."""
        return (
            self.db.query(Fragment)
            .filter(Fragment.source_file_id == source_id)
            .order_by(Fragment.start_s)
            .all()
        )

    def get_filtered(
        self,
        min_quality: float = 0.0,
        min_duration: float = 0.0,
        max_duration: float = 9999.0,
        exclude_duplicates: bool = True,
        exclude_rejected: bool = True,
        limit: int = 5000,
        project_id: Optional[int] = None,
    ) -> List[Fragment]:
        q = self.db.query(Fragment)
        if project_id is not None:
            q = q.join(SourceFile).filter(SourceFile.project_id == project_id)
        if min_quality > 0:
            q = q.filter(Fragment.quality_score >= min_quality)
        if min_duration > 0:
            q = q.filter(Fragment.duration_s >= min_duration)
        if max_duration < 9999.0:
            q = q.filter(Fragment.duration_s <= max_duration)
        if exclude_duplicates:
            q = q.filter(Fragment.is_duplicate != True)
        if exclude_rejected:
            q = q.filter(Fragment.reject_reason == None)
        return q.order_by(Fragment.quality_score.desc()).limit(limit).all()

    def get_by_ids(self, ids: Set[int]) -> List[Fragment]:
        if not ids:
            return []
        return self.db.query(Fragment).filter(Fragment.id.in_(ids)).all()

    def set_user_approved(self, fragment_id: int, approved: int) -> None:
        row = self.db.get(Fragment, fragment_id)
        if row:
            row.user_approved = approved
            self.db.commit()

    def set_duplicate(self, fragment_id: int, is_dup: bool) -> None:
        row = self.db.get(Fragment, fragment_id)
        if row:
            row.is_duplicate = is_dup
            self.db.commit()


# ── Duplicates ────────────────────────────────────────────────────────────────

class DuplicateRepo:
    def __init__(self, session: Session) -> None:
        self.db = session

    def save_many(self, pairs: List[Tuple[int, int, float]], method: str = "phash") -> None:
        for fid, did, sim in pairs:
            self.db.add(Duplicate(fragment_id=fid, duplicate_id=did, similarity=sim, method=method))
        self.db.commit()


# ── Music fragments ────────────────────────────────────────────────────────────

class MusicFragmentRepo:
    def __init__(self, session: Session) -> None:
        self.db = session

    def save_many(self, fragments: List[Dict[str, Any]]) -> None:
        for f in fragments:
            row = MusicFragment(**{k: v for k, v in f.items() if hasattr(MusicFragment, k)})
            self.db.add(row)
        self.db.commit()

    def get_for_audio(self, audio_rel_path: str, audio_hash: str) -> List[MusicFragment]:
        return self.db.query(MusicFragment).filter_by(
            audio_rel_path=audio_rel_path, audio_hash=audio_hash
        ).all()

    def clear_for_audio(self, audio_rel_path: str) -> None:
        self.db.query(MusicFragment).filter_by(audio_rel_path=audio_rel_path).delete()
        self.db.commit()


# ── Manual segments ────────────────────────────────────────────────────────────

class ManualSegmentRepo:
    def __init__(self, session: Session) -> None:
        self.db = session

    def add(self, segment: Dict[str, Any], project_id: Optional[int] = None) -> ManualSegment:
        row = ManualSegment(project_id=project_id, **{
            k: v for k, v in segment.items() if hasattr(ManualSegment, k)
        })
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_for_source(self, source_rel_path: str) -> List[ManualSegment]:
        return self.db.query(ManualSegment).filter_by(
            source_rel_path=source_rel_path, status="active"
        ).order_by(ManualSegment.start_s).all()

    def delete(self, segment_id: int) -> None:
        row = self.db.get(ManualSegment, segment_id)
        if row:
            row.status = "deleted"
            self.db.commit()

    def get_forbidden(self) -> List[Tuple[str, float, float]]:
        rows = self.db.query(ManualSegment).filter_by(
            include_policy="forbidden", status="active"
        ).all()
        return [(r.source_rel_path, r.start_s, r.end_s) for r in rows]

    def get_required(self) -> List[Tuple[str, float, float]]:
        rows = self.db.query(ManualSegment).filter(
            ManualSegment.include_policy.in_(["required", "recommended"]),
            ManualSegment.status == "active",
        ).all()
        return [(r.source_rel_path, r.start_s, r.end_s) for r in rows]


# ── Render jobs ────────────────────────────────────────────────────────────────

class RenderJobRepo:
    def __init__(self, session: Session) -> None:
        self.db = session

    def create(self, job_data: Dict[str, Any]) -> RenderJob:
        row = RenderJob(**{k: v for k, v in job_data.items() if hasattr(RenderJob, k)})
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def set_rating(self, job_id: int, rating: int) -> None:
        row = self.db.get(RenderJob, job_id)
        if row:
            row.user_rating = rating
            self.db.commit()

    def list_recent(self, project_id: Optional[int] = None, limit: int = 20) -> List[RenderJob]:
        q = self.db.query(RenderJob)
        if project_id is not None:
            q = q.filter_by(project_id=project_id)
        return q.order_by(RenderJob.created_at.desc()).limit(limit).all()
