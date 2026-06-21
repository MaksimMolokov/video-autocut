"""
StyleFitService — computes per-segment, per-style fitness scores.

For each ClipCandidate × StylePreset combination, produces a SegmentStyleFit
record that explains *why* a segment fits (or doesn't fit) a given style.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default style energy / motion mapping
# Maps style_id → preferred camera motion types and semantic context
_STYLE_RULES: Dict[str, dict] = {
    "dynamic_reels": {
        "preferred_motion": {"handheld", "pan_left", "pan_right", "shake", "zoom_in"},
        "preferred_tags":   {"action", "sport", "crowd", "people"},
        "energy":           "high",
        "min_quality":      0.40,
    },
    "cinematic": {
        "preferred_motion": {"static", "dolly", "pan_left", "pan_right", "tilt_up"},
        "preferred_tags":   {"landscape", "nature", "sunset", "architecture", "drone"},
        "energy":           "low",
        "min_quality":      0.55,
    },
    "travel_vlog": {
        "preferred_motion": {"pan_left", "pan_right", "tilt_up", "aerial_forward", "handheld"},
        "preferred_tags":   {"nature", "landscape", "urban", "people", "drone", "beach"},
        "energy":           "medium",
        "min_quality":      0.40,
    },
    "wedding": {
        "preferred_motion": {"static", "dolly", "tilt_up", "zoom_in"},
        "preferred_tags":   {"people", "face_closeup", "nature", "indoor", "studio"},
        "energy":           "low",
        "min_quality":      0.55,
    },
    "sport_highlight": {
        "preferred_motion": {"shake", "handheld", "zoom_in", "pan_left", "pan_right"},
        "preferred_tags":   {"sport", "action", "crowd", "people"},
        "energy":           "high",
        "min_quality":      0.35,
    },
    "drone_nature": {
        "preferred_motion": {"aerial_forward", "aerial_descent", "pan_left", "pan_right"},
        "preferred_tags":   {"drone", "aerial", "nature", "landscape", "water", "forest"},
        "energy":           "medium",
        "min_quality":      0.50,
    },
    "f1_style": {
        "preferred_motion": {"shake", "handheld", "zoom_in", "pan_right", "pan_left"},
        "preferred_tags":   {"action", "sport", "people", "crowd"},
        "energy":           "high",
        "min_quality":      0.40,
    },
}


@dataclass
class StyleFitResult:
    fit_score: float
    motion_fit: float
    semantic_fit: float
    role_fit: float
    quality_fit: float
    explanation: str


class StyleFitService:
    """
    Compute how well a segment (described by its SegmentFeatureProfile +
    QualityMetrics) fits a given style preset.

    Can operate in two modes:
      1. dict-based (for use from frontend without ORM)
      2. ORM-based: write results to SegmentStyleFit table
    """

    def __init__(self, score_weights: Optional[dict] = None):
        self.weights = score_weights or {
            "motion":   0.30,
            "semantic": 0.35,
            "role":     0.20,
            "quality":  0.15,
        }

    def compute_fit(
        self,
        style_id: str,
        motion_type: Optional[str],
        semantic_tags: Optional[List[str]],
        suggested_role: Optional[str],
        quality_score: float,
        *,
        target_role: Optional[str] = None,   # role required by style at this position
    ) -> StyleFitResult:
        """
        Compute style fitness from pre-computed features.

        Returns:
            StyleFitResult with component scores and human-readable explanation.
        """
        rules = _STYLE_RULES.get(style_id, {})
        reasons: List[str] = []

        # ── Motion fit ────────────────────────────────────────────────────────
        pref_motion = rules.get("preferred_motion", set())
        if motion_type and pref_motion:
            motion_fit = 1.0 if motion_type in pref_motion else 0.3
            if motion_type in pref_motion:
                reasons.append(f"{motion_type} matches style")
        else:
            motion_fit = 0.5

        # ── Semantic fit ──────────────────────────────────────────────────────
        pref_tags = rules.get("preferred_tags", set())
        if semantic_tags and pref_tags:
            overlap = len(set(semantic_tags) & pref_tags)
            semantic_fit = min(1.0, overlap / max(1, len(pref_tags)) * 2.5)
            if overlap:
                reasons.append(f"tags {set(semantic_tags) & pref_tags} match style")
        else:
            semantic_fit = 0.5

        # ── Role fit ─────────────────────────────────────────────────────────
        if target_role and suggested_role:
            role_fit = 1.0 if suggested_role == target_role else 0.4
            if suggested_role == target_role:
                reasons.append(f"role={suggested_role} matches")
        else:
            role_fit = 0.6

        # ── Quality fit ───────────────────────────────────────────────────────
        min_q = rules.get("min_quality", 0.40)
        if quality_score >= min_q:
            quality_fit = min(1.0, quality_score)
            reasons.append(f"quality {quality_score:.0%} meets threshold")
        else:
            quality_fit = quality_score / max(min_q, 0.01) * 0.5
            reasons.append(f"quality {quality_score:.0%} below {min_q:.0%}")

        # ── Composite ─────────────────────────────────────────────────────────
        w = self.weights
        fit_score = (
            w["motion"]   * motion_fit +
            w["semantic"] * semantic_fit +
            w["role"]     * role_fit +
            w["quality"]  * quality_fit
        )

        explanation = "; ".join(reasons) if reasons else "default scoring"
        return StyleFitResult(
            fit_score   = round(fit_score, 4),
            motion_fit  = round(motion_fit, 4),
            semantic_fit= round(semantic_fit, 4),
            role_fit    = round(role_fit, 4),
            quality_fit = round(quality_fit, 4),
            explanation = explanation,
        )

    def compute_and_save(
        self,
        session,
        candidate_id: int,
        style_id: str,
        motion_type: Optional[str],
        semantic_tags: Optional[List[str]],
        suggested_role: Optional[str],
        quality_score: float,
    ) -> None:
        """Compute style fit and upsert into SegmentStyleFit ORM table."""
        from infrastructure.database.models import SegmentStyleFit

        result = self.compute_fit(
            style_id, motion_type, semantic_tags, suggested_role, quality_score
        )

        existing = (
            session.query(SegmentStyleFit)
            .filter_by(candidate_id=candidate_id, style_preset_id=style_id)
            .first()
        )
        if existing:
            existing.fit_score    = result.fit_score
            existing.motion_fit   = result.motion_fit
            existing.semantic_fit = result.semantic_fit
            existing.role_fit     = result.role_fit
            existing.quality_fit  = result.quality_fit
            existing.explanation  = result.explanation
            existing.computed_at  = time.time()
        else:
            session.add(SegmentStyleFit(
                candidate_id    = candidate_id,
                style_preset_id = style_id,
                fit_score       = result.fit_score,
                motion_fit      = result.motion_fit,
                semantic_fit    = result.semantic_fit,
                role_fit        = result.role_fit,
                quality_fit     = result.quality_fit,
                explanation     = result.explanation,
                computed_at     = time.time(),
            ))
        session.commit()
