"""FragmentLibrary: bridge between analysis DB and the montage pipeline."""

import logging
from dataclasses import dataclass
from typing import List, Optional

from src.storage.analysis_db import AnalysisDB

logger = logging.getLogger(__name__)


@dataclass
class FragmentData:
    """Human-readable fragment for GUI display."""
    id: int
    source_path: str
    filename: str
    start_s: float
    end_s: float
    duration_s: float
    quality_score: float
    cinematic_score: float
    action_score: float
    social_score: float
    premium_score: float
    travel_score: float
    sharpness: float
    brightness: float
    stability: float
    motion: float
    thumbnail_path: Optional[str]
    user_approved: Optional[int]
    user_priority: Optional[int]
    # Level 2 content fields (None if not yet analyzed)
    has_face: Optional[int] = None
    has_person: Optional[int] = None
    has_subject: Optional[int] = None
    scene_type: Optional[str] = None
    # Level 3
    preview_path: Optional[str] = None
    # Level 4
    scene_tag: Optional[str] = None


class FragmentLibrary:
    def __init__(self, db: AnalysisDB):
        self.db = db

    # ------------------------------------------------------------------
    # Status checks
    # ------------------------------------------------------------------

    def has_analyzed(self, video_path: str) -> bool:
        return self.db.is_analyzed(video_path)

    def has_any_analyzed(self) -> bool:
        return len(self.db.get_analyzed_paths()) > 0

    # ------------------------------------------------------------------
    # Candidates for the render pipeline
    # ------------------------------------------------------------------

    def get_candidates(
        self,
        source_path: Optional[str] = None,
        style_score_key: str = 'quality_score',
        min_quality: float = 0.50,
        min_duration: float = 1.0,
        max_duration: float = 10.0,
        approved_only: bool = False,
        limit: int = 200,
        allowed_fragment_ids: Optional[set] = None,
    ) -> List:
        """
        Return CandidateClip-compatible objects from the DB.
        Falls back to quality_score if style_score_key not found.
        """
        source_ids = None
        if source_path is not None:
            sid = self.db.get_source_id(source_path)
            if sid is None:
                return []
            source_ids = [sid]

        allowed_sorts = {
            'quality_score', 'cinematic_score', 'action_score',
            'social_score', 'premium_score', 'travel_score',
        }
        sort_by = style_score_key if style_score_key in allowed_sorts else 'quality_score'

        def _fetch(q_threshold: float):
            return self.db.get_fragments_filtered(
                source_ids=source_ids,
                min_quality=q_threshold,
                min_duration=min_duration,
                max_duration=max_duration,
                approved_only=False,
                exclude_duplicates=True,
                sort_by=sort_by,
                limit=limit,
            )

        rows = _fetch(min_quality)

        # Adaptive threshold: relax if too few results
        if len(rows) < 15:
            for relaxed_q in [min_quality * 0.7, min_quality * 0.5, 0.0]:
                relaxed_rows = _fetch(relaxed_q)
                if len(relaxed_rows) >= 15 or relaxed_q == 0.0:
                    if len(relaxed_rows) > len(rows):
                        logger.warning(
                            f'[FragmentLibrary] Adaptive: only {len(rows)} fragments '
                            f'at q>={min_quality:.2f}, using {len(relaxed_rows)} '
                            f'at q>={relaxed_q:.2f}'
                        )
                        rows = relaxed_rows
                    break

        # Filter out manually disabled
        if approved_only:
            rows = [r for r in rows if r['user_approved'] == 1]
        else:
            rows = [r for r in rows if r['user_approved'] != 0 or r['user_approved'] is None]

        # Preprocessing whitelist filter
        if allowed_fragment_ids is not None:
            rows = [r for r in rows if r['id'] in allowed_fragment_ids]

        return [self._row_to_candidate(r, r['source_path']) for r in rows]

    def get_all_candidates_for_project(
        self,
        style_score_key: str = 'quality_score',
        min_quality: float = 0.50,
        min_duration: float = 1.0,
        max_duration: float = 10.0,
        limit: int = 400,
        allowed_fragment_ids: Optional[set] = None,
    ) -> List:
        return self.get_candidates(
            source_path=None,
            style_score_key=style_score_key,
            min_quality=min_quality,
            min_duration=min_duration,
            max_duration=max_duration,
            limit=limit,
            allowed_fragment_ids=allowed_fragment_ids,
        )

    # ------------------------------------------------------------------
    # GUI helpers
    # ------------------------------------------------------------------

    def get_fragments_for_ui(
        self,
        min_quality: float = 0.50,
        sort_by: str = 'quality_score',
        limit: int = 200,
        scene_tags: Optional[List[str]] = None,
    ) -> List[FragmentData]:
        rows = self.db.get_fragments_filtered(
            min_quality=min_quality,
            sort_by=sort_by,
            limit=limit,
            scene_tags=scene_tags if scene_tags else None,
        )

        # Get source paths
        analyzed = self.db.get_analyzed_paths()
        source_id_to_path = {}
        for path in analyzed:
            sid = self.db.get_source_id(path)
            if sid is not None:
                source_id_to_path[sid] = path

        result = []
        for row in rows:
            source_path = source_id_to_path.get(row['source_id'], '')
            result.append(FragmentData(
                id=row['id'],
                source_path=source_path,
                filename=source_path.split('/')[-1] if source_path else '',
                start_s=row['start_s'],
                end_s=row['end_s'],
                duration_s=row['duration_s'],
                quality_score=row['quality_score'] or 0.0,
                cinematic_score=row['cinematic_score'] or 0.0,
                action_score=row['action_score'] or 0.0,
                social_score=row['social_score'] or 0.0,
                premium_score=row['premium_score'] or 0.0,
                travel_score=row['travel_score'] or 0.0,
                sharpness=row['sharpness'] or 0.0,
                brightness=row['brightness'] or 0.0,
                stability=row['stability'] or 0.0,
                motion=row['motion'] or 0.0,
                thumbnail_path=row['thumbnail_path'],
                user_approved=row['user_approved'],
                user_priority=row['user_priority'],
                has_face=row['has_face'],
                has_person=row['has_person'],
                has_subject=row['has_subject'],
                scene_type=row['scene_type'],
                preview_path=row['preview_path'],
                scene_tag=row['scene_tag'] if 'scene_tag' in row.keys() else None,
            ))
        return result

    # ------------------------------------------------------------------
    # User controls
    # ------------------------------------------------------------------

    def mark_approved(self, fragment_id: int, approved: bool):
        self.db.update_fragment_approval(fragment_id, approved)

    def mark_disabled(self, fragment_id: int):
        self.db.update_fragment_approval(fragment_id, False)

    def reset_approval(self, fragment_id: int):
        self.db.update_fragment_approval(fragment_id, None)

    def mark_priority(self, fragment_id: int, priority: bool):
        self.db.update_fragment_priority(fragment_id, priority)

    # ------------------------------------------------------------------
    # Conversion: DB row → CandidateClip
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_candidate(row, source_path: str = ''):
        """Convert a DB row to a CandidateClip compatible with the existing pipeline."""
        try:
            from src.video_analysis.candidate_builder import CandidateClip
            from src.video_analysis.feature_extractor import ClipFeatures
        except ImportError:
            return _FallbackCandidate(row, source_path)

        features = ClipFeatures(
            start_time=row['start_s'],
            end_time=row['end_s'],
            duration=row['duration_s'],
            sharpness_score=row['sharpness'] or 0.5,
            brightness_score=row['brightness'] or 0.5,
            contrast_score=row['contrast'] or 0.5,
            motion_score=row['motion'] or 0.5,
            camera_stability_score=row['stability'] or 0.5,
            action_score=row['action'] or 0.5,
            calm_score=row['calm'] or 0.5,
            technical_quality_score=row['quality_score'] or 0.5,
        )
        candidate = CandidateClip(
            source_path=source_path,
            start=row['start_s'],
            end=row['end_s'],
            duration=row['duration_s'],
            features=features,
            is_must_use=bool(row['user_priority']),
            final_score=row['quality_score'] or 0.5,
        )
        # Fragment ID for preprocessing filter (used in render_video)
        candidate._fragment_id = row['id']  # type: ignore[attr-defined]
        # Attach scene_type for diversity logic in TimelineBuilder (Level 3)
        scene_type = row['scene_type']
        if scene_type:
            candidate.features.scene_type = scene_type  # type: ignore[attr-defined]
        return candidate


class _FallbackCandidate:
    """Minimal duck-type replacement when CandidateClip isn't importable."""
    def __init__(self, row, source_path: str = ''):
        self.source_path = source_path
        self.start = row['start_s']
        self.end = row['end_s']
        self.duration = row['duration_s']
        self.is_must_use = bool(row['user_priority'])
        self.final_score = row['quality_score'] or 0.5

        class F:
            pass

        f = F()
        f.sharpness_score = row['sharpness'] or 0.5
        f.brightness_score = row['brightness'] or 0.5
        f.contrast_score = row['contrast'] or 0.5
        f.motion_score = row['motion'] or 0.5
        f.camera_stability_score = row['stability'] or 0.5
        f.action_score = row['action'] or 0.5
        f.calm_score = row['calm'] or 0.5
        f.technical_quality_score = row['quality_score'] or 0.5
        self.features = f
