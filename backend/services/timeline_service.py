"""TimelineService — build and manage render timelines (TASK-003)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from infrastructure.config.config_manager import cfg
from infrastructure.storage.path_manager import PathManager

logger = logging.getLogger(__name__)


class TimelineService:
    """
    Build a render timeline from analyzed fragments + preset settings.
    Wraps the existing clip_selection and timeline building logic.
    """

    def __init__(self, path_manager: PathManager) -> None:
        self.pm = path_manager

    def build(
        self,
        preset: dict,
        target_duration_s: float,
        approved_ids: Optional[set] = None,
        rejected_ids: Optional[set] = None,
        manual_required: Optional[List] = None,
        manual_forbidden: Optional[List] = None,
        seed_offset: int = 0,
        music_beats: Optional[List[float]] = None,
        music_energy: Optional[List] = None,
    ) -> Dict[str, Any]:
        """
        Build a timeline. Returns dict with:
          segments: List[dict]  (source_rel_path, start_s, end_s, role, score)
          total_duration_s: float
          clip_count: int
          coverage_ratio: float
        """
        from sqlalchemy.orm import Session
        from infrastructure.database.models import create_db_engine
        from infrastructure.database.repository import FragmentRepo

        engine = create_db_engine(str(self.pm.db_path))
        with Session(engine) as session:
            repo = FragmentRepo(session)
            candidates = repo.get_filtered(
                min_quality=cfg.get("quality.backup_threshold", 0.35),
                max_duration=cfg.get("scene.max_duration", 30.0),
                exclude_rejected=True,
                exclude_duplicates=True,
            )

        if not candidates:
            return {"segments": [], "total_duration_s": 0.0, "clip_count": 0, "coverage_ratio": 0.0}

        # Apply montage pool (manual forbidden/required)
        from src.preprocessing.candidate_filter import apply_montage_pool
        from src.preprocessing.step2_adapter import MontagePool

        pool = MontagePool(
            forbidden_fragment_ids=set(rejected_ids or []),
            priority_fragment_ids=set(approved_ids or []),
            forbidden_ranges=list(manual_forbidden or []),
            priority_ranges=list(manual_required or []),
            score_boost=cfg.get("render.score_boost", 0.30),
            is_active=bool(rejected_ids or approved_ids or manual_forbidden or manual_required),
        )
        candidates = apply_montage_pool(candidates, pool)

        # Delegate to existing timeline builder (legacy bridge)
        segments = _select_segments(
            candidates, preset, target_duration_s, seed_offset,
            music_beats=music_beats, music_energy=music_energy,
        )

        total_dur = sum(s["end_s"] - s["start_s"] for s in segments)
        available_dur = sum(c.duration_s for c in candidates)
        coverage = total_dur / available_dur if available_dur else 0.0

        return {
            "segments": segments,
            "total_duration_s": total_dur,
            "clip_count": len(segments),
            "coverage_ratio": coverage,
        }

    def build_variants(self, preset: dict, target_duration_s: float, **kwargs) -> Dict[str, dict]:
        variants = {}
        for i, letter in enumerate(["A", "B", "C", "D"]):
            variants[letter] = self.build(preset, target_duration_s, seed_offset=i, **kwargs)
        return variants


def _select_segments(candidates, preset, target_duration_s, seed_offset, **kwargs) -> List[dict]:
    """
    Select segments using preset segment_selection rules + style fit scores.

    Variant semantics (seed_offset):
      0 → Best quality
      1 → Best style fit
      2 → Structured (intro → body → outro)
      3 → Random mix
    """
    import random

    settings = preset.get("settings", {}) or preset
    sel_rules = settings.get("segment_selection", {})
    clip_sel  = settings.get("clip_selection", {})

    min_dur = clip_sel.get("segment_min_duration", 1.5)
    max_dur = clip_sel.get("segment_max_duration", 8.0)
    min_quality = sel_rules.get("min_scores", {}).get("quality_score",
                  clip_sel.get("min_quality_score", 0.35))

    preferred_motion  = set(sel_rules.get("preferred_camera_motion", []))
    rejected_motion   = set(sel_rules.get("rejected_camera_motion", []))
    preferred_cats    = set(sel_rules.get("preferred_scene_categories", []))

    preset_id = settings.get("preset_id", "")

    rng = random.Random(42 + seed_offset)

    # ── Filter candidates ────────────────────────────────────────────────────
    def _passes_filters(c) -> bool:
        if min_dur > 0 and c.duration_s < min_dur:
            return False
        if c.duration_s > max_dur:
            return False
        if float(c.quality_score or 0.0) < min_quality:
            return False
        # Motion filter via SegmentFeatureProfile
        if rejected_motion and hasattr(c, "feature_profile") and c.feature_profile:
            if c.feature_profile.camera_motion_type in rejected_motion:
                return False
        return True

    pool = [c for c in candidates if _passes_filters(c)]
    if not pool:
        # Ничего не прошло — ослабляем только порог качества,
        # но явно отбракованные движения (shake и т.п.) не возвращаем
        def _motion_ok(c) -> bool:
            if rejected_motion and hasattr(c, "feature_profile") and c.feature_profile:
                return c.feature_profile.camera_motion_type not in rejected_motion
            return True
        pool = [c for c in candidates if _motion_ok(c)] or list(candidates)

    # ── Score candidates ─────────────────────────────────────────────────────
    def _style_score(c) -> float:
        base = float(c.quality_score or 0.5)
        # Use cached StyleFit score if available
        if hasattr(c, "style_fits") and c.style_fits:
            for sf in c.style_fits:
                if sf.style_preset_id == preset_id:
                    return float(sf.fit_score)
        # Heuristic boost
        boost = 0.0
        if hasattr(c, "feature_profile") and c.feature_profile:
            fp = c.feature_profile
            if preferred_motion and fp.camera_motion_type in preferred_motion:
                boost += 0.12
            if fp.semantic_tags and preferred_cats:
                overlap = len(set(fp.semantic_tags) & preferred_cats)
                boost += min(0.15, overlap * 0.05)
        return min(1.0, base + boost)

    def _get_role(c) -> str:
        if hasattr(c, "feature_profile") and c.feature_profile:
            return c.feature_profile.suggested_role or "body"
        return "body"

    # ── Build ordered list based on variant ──────────────────────────────────
    if seed_offset == 0:   # Best quality
        ordered = sorted(pool, key=lambda c: -float(c.quality_score or 0))
    elif seed_offset == 1: # Best style fit
        ordered = sorted(pool, key=lambda c: -_style_score(c))
    elif seed_offset == 2: # Structured: intro → body → outro
        intros  = sorted([c for c in pool if _get_role(c) == "intro"],
                         key=lambda c: -_style_score(c))[:2]
        outros  = sorted([c for c in pool if _get_role(c) == "outro"],
                         key=lambda c: -_style_score(c))[:2]
        bodies  = sorted([c for c in pool if _get_role(c) not in ("intro","outro")],
                         key=lambda c: -_style_score(c))
        rng.shuffle(bodies)
        ordered = intros + bodies + outros
    else:  # Random mix
        ordered = list(pool)
        rng.shuffle(ordered)

    # ── Fill timeline ────────────────────────────────────────────────────────
    selected, total = [], 0.0
    explanation_lines = []

    for c in ordered:
        dur = min(c.duration_s, max_dur)
        if total + dur > target_duration_s * 1.2:
            explanation_lines.append(
                f"Пропущен {c.id}: хронометраж {total:.0f}с превышает цель"
            )
            break
        role = _get_role(c)
        score = _style_score(c)
        src_rel = c.source_file.rel_path if hasattr(c, "source_file") and c.source_file else ""
        explanation_lines.append(
            f"Добавлен {c.id} ({role}, score={score:.2f}, dur={dur:.1f}s)"
        )
        selected.append({
            "source_rel_path": src_rel,
            "start_s":         c.start_s,
            "end_s":           min(c.start_s + dur, c.end_s),
            "role":            role,
            "score":           round(score, 4),
            "style_score":     round(_style_score(c), 4),
            "fragment_id":     c.id,
            "explanation":     "; ".join(explanation_lines[-1:]),
        })
        total += dur
        if total >= target_duration_s:
            break

    return selected
