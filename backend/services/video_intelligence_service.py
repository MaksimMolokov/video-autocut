"""
VideoIntelligenceService — orchestrates the full Video Intelligence pipeline.

Runs all analysers on each fragment dict and returns enriched dicts with:
  camera_motion, semantic_tags, style_fit_scores, composition, pose/eye quality,
  suggested_role, reject_reasons, overall_vi_score.

Designed to be called after the baseline AnalysisService pass.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from infrastructure.config.config_manager import cfg

logger = logging.getLogger(__name__)


class VideoIntelligenceService:
    """
    Full Video Intelligence enrichment pass.

    Usage:
        vis = VideoIntelligenceService()
        enriched = vis.enrich(fragments, video_path, style_id="cinematic_nature")
    """

    def enrich(
        self,
        fragments: List[Dict[str, Any]],
        video_path: str,
        style_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        session=None,
    ) -> List[Dict[str, Any]]:
        if not fragments:
            return fragments

        vi_cfg = cfg.get("video_intelligence", {})
        n = len(fragments)

        _motion_enabled    = vi_cfg.get("motion", {}).get("enabled", True)
        _semantic_enabled  = vi_cfg.get("semantic", {}).get("enabled", True)
        _aesthetic_enabled = vi_cfg.get("aesthetic", {}).get("enabled", True)
        _composition_enabled = vi_cfg.get("composition", {}).get("enabled", True)
        _human_enabled     = vi_cfg.get("human", {}).get("enabled", True)
        _style_fit_enabled = vi_cfg.get("style_fit", {}).get("enabled", True)

        # Lazy-load services
        motion_clf    = _load_motion_classifier(vi_cfg) if _motion_enabled    else None
        semantic_tgr  = _load_semantic_tagger(vi_cfg)   if _semantic_enabled  else None
        aesthetic_sc  = _load_aesthetic_scorer()         if _aesthetic_enabled else None
        composition_az= _load_composition_analyzer()    if _composition_enabled else None
        pose_az       = _load_pose_analyzer(vi_cfg)     if _human_enabled     else None
        eye_az        = _load_eye_analyzer(vi_cfg)      if _human_enabled     else None
        style_svc     = _load_style_fit_service()       if _style_fit_enabled else None

        for idx, frag in enumerate(fragments):
            try:
                self._enrich_one(
                    frag, video_path,
                    motion_clf, semantic_tgr, aesthetic_sc,
                    composition_az, pose_az, eye_az,
                    style_svc, style_id, session, vi_cfg,
                )
            except Exception as exc:
                logger.debug(f"[VI] frag {idx} failed: {exc}")

            if progress_callback:
                try:
                    progress_callback(idx + 1, n, f"VI Analysis: {idx+1}/{n}")
                except Exception:
                    pass

        return fragments

    # ── Per-fragment ──────────────────────────────────────────────────────────

    def _enrich_one(
        self, frag, video_path,
        motion_clf, semantic_tgr, aesthetic_sc,
        composition_az, pose_az, eye_az,
        style_svc, style_id, session, vi_cfg,
    ):
        start_s = float(frag.get("start_s", 0.0))
        end_s   = float(frag.get("end_s",   start_s + 3.0))

        # ── Camera motion ──────────────────────────────────────────────────────
        if motion_clf and not frag.get("camera_motion_type"):
            try:
                m = motion_clf.classify(video_path, start_s, end_s)
                frag["camera_motion_type"]       = m.motion_type
                frag["camera_motion_confidence"] = m.confidence
                frag["camera_motion_speed"]      = m.speed
            except Exception as exc:
                logger.debug(f"[VI] motion: {exc}")

        # ── Semantic tags ──────────────────────────────────────────────────────
        if semantic_tgr and not frag.get("semantic_tags"):
            try:
                qm = {
                    "has_face":        frag.get("has_face", False),
                    "face_size_ratio": frag.get("face_size_ratio", 0.0),
                    "person_count":    frag.get("person_count", 0),
                }
                tag_res = semantic_tgr.tag_segment(
                    video_path, start_s, end_s,
                    motion_type=frag.get("camera_motion_type"),
                    quality_metrics=qm,
                )
                if tag_res.tags:
                    frag["semantic_tags"]        = tag_res.tags
                    frag["primary_semantic_tag"] = tag_res.primary_tag
                    frag["scene_context"]        = tag_res.scene_context
                    existing = list(frag.get("scene_tags") or [])
                    frag["scene_tags"] = list(dict.fromkeys(existing + tag_res.tags))
            except Exception as exc:
                logger.debug(f"[VI] semantic: {exc}")

        # ── Aesthetic ─────────────────────────────────────────────────────────
        if aesthetic_sc:
            try:
                frag["aesthetic_score"] = aesthetic_sc.score(video_path, start_s)
            except Exception:
                pass

        # ── Composition ───────────────────────────────────────────────────────
        if composition_az:
            try:
                comp = composition_az.analyze(video_path, start_s, end_s)
                frag["composition_score"]        = comp.composition_score
                frag["rule_of_thirds_score"]     = comp.rule_of_thirds_score
                frag["horizon_level_score"]      = comp.horizon_level_score
                frag["symmetry_score"]           = comp.symmetry_score
                frag["visual_depth_score"]       = comp.visual_depth_score
                frag["background_clutter_score"] = comp.background_clutter_score
                # Композиционные замечания (tilted horizon и т.п.) — мягкий сигнал:
                # они уже снижают composition_score. Жёсткий reject опустошал
                # пул монтажа на любительском материале.
                if comp.notes:
                    frag["composition_notes"] = list(comp.notes)
            except Exception as exc:
                logger.debug(f"[VI] composition: {exc}")

        # ── Pose + eye state (only when faces present) ─────────────────────────
        if frag.get("has_face") or frag.get("has_person"):
            if pose_az:
                try:
                    pr = pose_az.analyze(video_path, start_s, end_s)
                    frag["pose_quality_score"]      = pr.pose_quality_score
                    frag["body_crop_quality_score"] = pr.body_crop_quality_score
                    frag["main_person_area_ratio"]  = pr.main_person_area_ratio
                    frag["head_visible"]            = pr.head_visible
                    for r in pr.reject_reasons:
                        _append_reject(frag, r)
                except Exception as exc:
                    logger.debug(f"[VI] pose: {exc}")

            if eye_az:
                try:
                    er = eye_az.analyze(video_path, start_s, end_s)
                    frag["eyes_open_score"] = er.eyes_open_score
                    frag["eyes_detected"]   = er.eyes_detected
                    min_eyes = vi_cfg.get("human", {}).get("min_eyes_open_score", 0.55)
                    if er.eyes_detected and er.eyes_open_score < min_eyes:
                        _append_reject(frag, "eyes_closed")
                except Exception as exc:
                    logger.debug(f"[VI] eyes: {exc}")

        # ── Role inference (from SegmentFeatureBuilder logic) ──────────────────
        if not frag.get("suggested_role"):
            frag["suggested_role"], frag["role_confidence"] = _infer_role(frag)

        # ── Style fit ─────────────────────────────────────────────────────────
        if style_svc and style_id:
            try:
                sf = style_svc.compute_fit(
                    style_id       = style_id,
                    motion_type    = frag.get("camera_motion_type"),
                    semantic_tags  = frag.get("semantic_tags") or frag.get("scene_tags"),
                    suggested_role = frag.get("suggested_role"),
                    quality_score  = frag.get("quality_score", 0.5),
                )
                if not isinstance(frag.get("style_fit_scores"), dict):
                    frag["style_fit_scores"] = {}
                frag["style_fit_scores"][style_id] = sf.fit_score
                frag["_style_explanation"] = sf.explanation
            except Exception as exc:
                logger.debug(f"[VI] style_fit: {exc}")

        # ── Overall VI score ───────────────────────────────────────────────────
        frag["vi_score"] = _compute_vi_score(frag)

        # ── ORM persistence ────────────────────────────────────────────────────
        if session is not None:
            try:
                _persist_feature_profile(session, frag)
            except Exception:
                pass


# ── Helpers ────────────────────────────────────────────────────────────────────

def _append_reject(frag: dict, reason: str) -> None:
    existing = frag.get("reject_reasons") or []
    if reason not in existing:
        existing.append(reason)
    frag["reject_reasons"] = existing
    # Also fill rejection_reason for legacy compatibility
    if not frag.get("rejection_reason") and existing:
        frag["rejection_reason"] = existing[0]


def _infer_role(frag: dict) -> tuple[str, float]:
    tags   = set(frag.get("semantic_tags", []) or frag.get("scene_tags", []))
    motion = frag.get("camera_motion_type", "unknown")
    quality= frag.get("quality_score", 0.5)
    dur    = frag.get("end_s", 0) - frag.get("start_s", 0)

    if tags & {"drone", "aerial", "landscape", "sunset", "sunrise"}:
        if motion in ("aerial_forward", "aerial_descent", "tilt_up", "pan_left", "pan_right"):
            return "intro", 0.80
        return "outro", 0.70
    if frag.get("has_face") and motion == "static":
        return "body", 0.75
    if dur < 1.5 or quality < 0.35:
        return "transition", 0.65
    if motion in ("shake", "handheld") and tags & {"sport", "action", "crowd"}:
        return "body", 0.70
    return "body", 0.50


def _compute_vi_score(frag: dict) -> float:
    q   = frag.get("quality_score", 0.5)
    aes = frag.get("aesthetic_score", 0.5)
    comp= frag.get("composition_score", 0.5)
    n_r = len(frag.get("reject_reasons") or [])
    penalty = min(0.4, n_r * 0.15)
    return round(float(max(0.0, min(1.0, 0.4*q + 0.3*aes + 0.3*comp - penalty))), 4)


def _persist_feature_profile(session, frag: dict) -> None:
    from infrastructure.database.models import SegmentFeatureProfile
    import time
    candidate_id = frag.get("_candidate_id") or frag.get("id")
    if candidate_id is None:
        return
    existing = session.query(SegmentFeatureProfile).filter_by(candidate_id=candidate_id).first()
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


# ── Lazy loaders ───────────────────────────────────────────────────────────────

def _load_motion_classifier(vi_cfg):
    try:
        from analysis.video.camera_motion_classifier import CameraMotionClassifier
        mc = vi_cfg.get("motion", {})
        return CameraMotionClassifier(
            sample_fps=mc.get("sample_fps", 5.0),
            max_frames=mc.get("max_frames", 20),
        )
    except Exception as exc:
        logger.warning(f"[VI] CameraMotionClassifier unavailable: {exc}")
        return None


def _load_semantic_tagger(vi_cfg):
    try:
        from analysis.intelligence.semantic_tagger import SemanticTagger
        sc = vi_cfg.get("semantic", {})
        return SemanticTagger(
            backend=sc.get("provider", "rule_based"),
            min_confidence=sc.get("min_confidence", 0.55),
        )
    except Exception as exc:
        logger.warning(f"[VI] SemanticTagger unavailable: {exc}")
        return None


def _load_aesthetic_scorer():
    try:
        from analysis.content.aesthetic_scorer import AestheticScorer
        return AestheticScorer()
    except Exception:
        return None


def _load_composition_analyzer():
    try:
        from analysis.content.composition_analyzer import CompositionAnalyzer
        return CompositionAnalyzer()
    except Exception:
        return None


def _load_pose_analyzer(vi_cfg):
    try:
        from analysis.content.pose_analyzer import PoseAnalyzer
        return PoseAnalyzer()
    except Exception:
        return None


def _load_eye_analyzer(vi_cfg):
    try:
        from analysis.content.eye_state_analyzer import EyeStateAnalyzer
        return EyeStateAnalyzer()
    except Exception:
        return None


def _load_style_fit_service():
    try:
        from analysis.intelligence.style_fit_service import StyleFitService
        return StyleFitService()
    except Exception:
        return None
