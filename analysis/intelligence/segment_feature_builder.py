"""
SegmentFeatureBuilder — enriches fragment dicts with Video Intelligence data.

Runs CameraMotionClassifier + SemanticTagger on each fragment and merges
the results back into the fragment dict. Optionally persists to the
SegmentFeatureProfile ORM table when a SQLAlchemy session is provided.

Designed to be called from AnalysisService._analyze_one_video() after the
baseline quality pass, or as a post-processing step over existing fragment dicts.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SegmentFeatureBuilder:
    """
    Enrich a list of fragment dicts with:
      - camera_motion_type / camera_motion_confidence / camera_motion_speed
      - semantic_tags / primary_semantic_tag / scene_context
      - suggested_role / role_confidence
      - human_frame_quality (eye_state, pose_type, body_crop_quality)

    Falls back gracefully: if OpenCV is unavailable or any frame read fails,
    the original dict values are preserved.

    Usage:
        builder = SegmentFeatureBuilder()
        enriched = builder.enrich(fragments, video_path)
    """

    def __init__(
        self,
        motion_sample_fps: float = 5.0,
        motion_max_frames: int = 20,
        semantic_backend: str = "rule_based",
        semantic_min_confidence: float = 0.55,
        semantic_max_tags: int = 5,
    ):
        self._motion_sample_fps = motion_sample_fps
        self._motion_max_frames = motion_max_frames
        self._semantic_backend  = semantic_backend
        self._sem_min_conf      = semantic_min_confidence
        self._sem_max_tags      = semantic_max_tags

        # Lazy-initialised to avoid import overhead when VI is disabled
        self._motion_clf    = None
        self._semantic_tgr  = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def enrich(
        self,
        fragments: List[Dict[str, Any]],
        video_path: str,
        progress_callback=None,
        session=None,          # SQLAlchemy Session — used to write SegmentFeatureProfile
    ) -> List[Dict[str, Any]]:
        """
        Enrich each fragment dict in-place and return the list.

        Args:
            fragments:         List of fragment dicts from _frag_dict_to_frontend or
                               _analyze_one_video.
            video_path:        Absolute path to the source video file.
            progress_callback: Optional callable(n_done, n_total, msg).
            session:           SQLAlchemy Session for ORM persistence.

        Returns:
            The same list, each dict augmented with VI fields.
        """
        if not fragments:
            return fragments

        motion_clf   = self._get_motion_classifier()
        semantic_tgr = self._get_semantic_tagger()
        n = len(fragments)

        for i, frag in enumerate(fragments):
            try:
                self._enrich_one(frag, video_path, motion_clf, semantic_tgr, session)
            except Exception as exc:
                logger.debug(f"[FeatureBuilder] frag {i} failed: {exc}")

            if progress_callback:
                try:
                    progress_callback(i + 1, n, f"Intelligence: {i+1}/{n}")
                except Exception:
                    pass

        return fragments

    # ── Per-fragment enrichment ───────────────────────────────────────────────

    def _enrich_one(
        self,
        frag: Dict[str, Any],
        video_path: str,
        motion_clf,
        semantic_tgr,
        session,
    ) -> None:
        start_s = float(frag.get("start_s", 0.0))
        end_s   = float(frag.get("end_s", start_s + 3.0))

        # ── Camera motion ──────────────────────────────────────────────────────
        motion_result = None
        if motion_clf is not None:
            try:
                motion_result = motion_clf.classify(video_path, start_s, end_s)
                frag["camera_motion_type"]       = motion_result.motion_type
                frag["camera_motion_confidence"] = motion_result.confidence
                frag["camera_motion_speed"]      = motion_result.speed
            except Exception as exc:
                logger.debug(f"[FeatureBuilder] motion failed: {exc}")

        # ── Semantic tags ──────────────────────────────────────────────────────
        tag_result = None
        if semantic_tgr is not None:
            try:
                qm = {
                    "has_face":        frag.get("has_face", False),
                    "face_size_ratio": frag.get("face_size_ratio", 0.0),
                    "person_count":    frag.get("person_count", 0),
                }
                tag_result = semantic_tgr.tag_segment(
                    video_path, start_s, end_s,
                    motion_type=frag.get("camera_motion_type"),
                    quality_metrics=qm,
                )
                # Merge — keep existing tags if new tagger returns empty
                if tag_result.tags:
                    frag["semantic_tags"]       = tag_result.tags
                    frag["primary_semantic_tag"] = tag_result.primary_tag
                    frag["scene_context"]        = tag_result.scene_context
                    # Also update legacy scene_tags field used by UI
                    existing_tags = list(frag.get("scene_tags") or [])
                    for t in tag_result.tags:
                        if t not in existing_tags:
                            existing_tags.append(t)
                    frag["scene_tags"] = existing_tags
            except Exception as exc:
                logger.debug(f"[FeatureBuilder] semantic failed: {exc}")

        # ── Suggested role ─────────────────────────────────────────────────────
        role, role_conf = _infer_role(frag, motion_result, tag_result)
        frag["suggested_role"]      = role
        frag["role_confidence"]     = role_conf

        # ── ORM persistence (optional) ─────────────────────────────────────────
        if session is not None:
            candidate_id = frag.get("_candidate_id") or frag.get("id")
            if candidate_id is not None:
                try:
                    _upsert_feature_profile(session, candidate_id, frag, motion_result, tag_result)
                except Exception as exc:
                    logger.debug(f"[FeatureBuilder] ORM write failed: {exc}")

    # ── Lazy loader ───────────────────────────────────────────────────────────

    def _get_motion_classifier(self):
        if self._motion_clf is None:
            try:
                from analysis.video.camera_motion_classifier import CameraMotionClassifier
                self._motion_clf = CameraMotionClassifier(
                    sample_fps=self._motion_sample_fps,
                    max_frames=self._motion_max_frames,
                )
            except Exception as exc:
                logger.warning(f"[FeatureBuilder] CameraMotionClassifier unavailable: {exc}")
        return self._motion_clf

    def _get_semantic_tagger(self):
        if self._semantic_tgr is None:
            try:
                from analysis.intelligence.semantic_tagger import SemanticTagger
                self._semantic_tgr = SemanticTagger(
                    backend=self._semantic_backend,
                    min_confidence=self._sem_min_conf,
                    max_tags=self._sem_max_tags,
                )
            except Exception as exc:
                logger.warning(f"[FeatureBuilder] SemanticTagger unavailable: {exc}")
        return self._semantic_tgr


# ── Helpers ────────────────────────────────────────────────────────────────────

def _infer_role(frag, motion_result, tag_result) -> tuple[str, float]:
    """Suggest intro | body | outro | transition for timeline placement."""
    tags = set(frag.get("semantic_tags", []) or frag.get("scene_tags", []))
    motion = frag.get("camera_motion_type", "unknown")
    quality = frag.get("quality_score", 0.5)

    # Aerial / wide landscape → strong intro / outro candidate
    if tags & {"drone", "aerial", "landscape", "sunset", "sunrise"}:
        if motion in ("aerial_forward", "aerial_descent", "tilt_up", "pan_left", "pan_right"):
            return "intro", 0.80
        return "outro", 0.70

    # Face closeup in static shot → body (portrait / interview)
    if frag.get("has_face") and motion == "static":
        return "body", 0.75

    # Very short / low quality → transition filler
    dur = frag.get("end_s", 0) - frag.get("start_s", 0)
    if dur < 1.5 or quality < 0.35:
        return "transition", 0.65

    # High energy action → body
    if motion in ("shake", "handheld") and tags & {"sport", "action", "crowd"}:
        return "body", 0.70

    return "body", 0.50


def _upsert_feature_profile(session, candidate_id: int, frag: dict, motion_result, tag_result):
    """Write or update a SegmentFeatureProfile ORM row."""
    from infrastructure.database.models import SegmentFeatureProfile

    existing = (
        session.query(SegmentFeatureProfile)
        .filter_by(candidate_id=candidate_id)
        .first()
    )
    kwargs = dict(
        camera_motion_type       = frag.get("camera_motion_type"),
        camera_motion_confidence = frag.get("camera_motion_confidence"),
        camera_motion_speed      = frag.get("camera_motion_speed"),
        semantic_tags            = frag.get("semantic_tags"),
        primary_semantic_tag     = frag.get("primary_semantic_tag"),
        scene_context            = frag.get("scene_context"),
        suggested_role           = frag.get("suggested_role"),
        role_confidence          = frag.get("role_confidence"),
        analyzed_at              = time.time(),
    )
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
    else:
        session.add(SegmentFeatureProfile(candidate_id=candidate_id, **kwargs))
    session.commit()
