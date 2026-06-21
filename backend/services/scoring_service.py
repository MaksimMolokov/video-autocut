"""
ScoringService — multi-level fragment scoring (VI2-012, VI2-016).

Produces full per-fragment score breakdown:
  - technical_score:   sharpness, stability, exposure
  - content_score:     faces, persons, subject presence
  - aesthetic_score:   composition, color, saliency
  - vi_score:          VideoIntelligence aggregate (VI2-016)
  - style_fit_score:   match against selected style preset
  - semantic_score:    scene category relevance
  - motion_fit:        camera motion vs preset rules
  - role_score:        how well fragment fits intro/body/outro
  - reject_score:      probability-of-rejection penalty
  - global_quality_score: final combined score

Plus human-readable selection_reason and rejection_reason.
Scoring weights come from YAML presets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from infrastructure.config.config_manager import cfg


@dataclass
class FragmentScore:
    """Full scoring breakdown for one fragment."""
    fragment_id: int = 0

    technical_score: float = 0.5
    sharpness: float = 0.5
    stability: float = 0.5
    exposure: float = 0.5

    aesthetic_score: float = 0.5
    composition_score: float = 0.5

    vi_score: float = 0.5
    pose_score: float = 0.5
    eye_score: float = 1.0

    semantic_score: float = 0.5
    motion_fit: float = 0.5
    style_fit_score: float = 0.5
    role_score: float = 0.5
    suggested_role: str = "body"

    reject_score: float = 0.0
    reject_reasons: List[str] = field(default_factory=list)

    global_quality_score: float = 0.5
    explanation: str = ""


class ScoringService:
    """Score clip candidates and generate explanations."""

    def score(self, metrics: Dict[str, Any], preset: dict) -> Dict[str, Any]:
        """
        Compute technical, content, aesthetic and overall quality scores.
        Returns dict with all scores + selection_reason + rejection_reason.
        """
        weights = preset.get("scoring_weights", {})

        technical = self._technical_score(metrics, weights)
        content = self._content_score(metrics, weights)
        aesthetic = self._aesthetic_score(metrics, weights)

        # Combined UMS
        quality = 0.45 * technical + 0.25 * content + 0.30 * aesthetic

        reject_reason = self._reject_reason(metrics)
        selection_reason = self._selection_reason(metrics, technical, content, aesthetic) if not reject_reason else None

        return {
            "technical_score": round(technical, 3),
            "content_score": round(content, 3),
            "aesthetic_score": round(aesthetic, 3),
            "quality_score": round(min(1.0, quality), 3),
            "rejection_reason": reject_reason,
            "selection_reason": selection_reason,
        }

    # ── Multi-level VI scoring (VI2-012, VI2-016) ──────────────────────────────

    def score_fragment(
        self,
        frag: dict,
        preset_settings: Optional[dict] = None,
        style_id: str = "",
    ) -> FragmentScore:
        """
        Full multi-level score for one fragment dict. Integrates VI data.
        Replaces (or supplements) the older score() method.
        """
        from backend.services.reject_reason_builder import build_reject_reasons

        ps   = preset_settings or {}
        sel  = ps.get("segment_selection", {})
        clip = ps.get("clip_selection", {})
        weights = ps.get("scoring_weights", {})

        result = FragmentScore(fragment_id=frag.get("id", 0))

        # Technical
        sharpness  = float(frag.get("sharpness", frag.get("blur_score", 0.5)))
        shake      = float(frag.get("camera_shake", 0.0))
        brightness = float(frag.get("brightness", 0.5))
        stability  = max(0.0, 1.0 - shake)
        result.sharpness  = sharpness
        result.stability  = stability
        result.exposure   = brightness
        result.technical_score = _clamp(sharpness * 0.45 + stability * 0.35 + brightness * 0.20)

        # Aesthetic + composition
        result.aesthetic_score   = float(frag.get("aesthetic_score", 0.5))
        result.composition_score = float(frag.get("composition_score", result.aesthetic_score))

        # VI score (from VideoIntelligenceService) — VI2-016
        result.vi_score   = float(frag.get("vi_score", frag.get("quality_score", 0.5)))
        result.pose_score = float(frag.get("pose_quality_score", 0.5))
        result.eye_score  = float(frag.get("eyes_open_score", 1.0))

        # Semantic relevance
        preferred_cats  = set(sel.get("preferred_scene_categories", []))
        fragment_tags   = set(frag.get("scene_tags", []))
        if preferred_cats and fragment_tags:
            overlap = len(fragment_tags & preferred_cats)
            # Нет пересечения — нейтрально (0.5); штрафы — зона reject_reason_builder
            result.semantic_score = _clamp(0.5 + overlap * 0.15)
        else:
            result.semantic_score = 0.5

        # Camera motion fit
        preferred_motion = set(sel.get("preferred_camera_motion", []))
        rejected_motion  = set(sel.get("rejected_camera_motion", []))
        cam_motion = frag.get("camera_motion_type", "static")
        if cam_motion in preferred_motion:
            result.motion_fit = 0.85
        elif cam_motion in rejected_motion:
            result.motion_fit = 0.10
        else:
            result.motion_fit = 0.50

        # Style fit
        style_fits = frag.get("style_fit_scores", {})
        if style_id and style_id in style_fits:
            result.style_fit_score = float(style_fits[style_id])
        else:
            result.style_fit_score = _clamp(result.semantic_score * 0.55 + result.motion_fit * 0.45)

        # Role
        role = frag.get("suggested_role", "body")
        result.suggested_role = role
        result.role_score = _score_role(frag, role, sel.get("role_rules", {}))

        # Reject
        reasons = build_reject_reasons(frag, ps)
        result.reject_reasons = reasons
        result.reject_score   = _clamp(len(reasons) * 0.35)

        # Global quality (VI2-016: vi_score is a first-class component)
        w_tech  = _clamp(weights.get("sharpness", 0.9) * 0.5 + weights.get("stability", 0.5) * 0.5)
        w_aes   = _clamp(weights.get("aesthetic_score", 0.7))
        w_vi    = 1.0
        w_style = _clamp(weights.get("aesthetic_score", 0.7))
        w_sem   = 1.0

        denom = w_tech * 0.25 + w_aes * 0.20 + w_vi * 0.20 + w_style * 0.20 + w_sem * 0.15
        raw_global = (
            result.technical_score  * w_tech  * 0.25 +
            result.aesthetic_score  * w_aes   * 0.20 +
            result.vi_score         * w_vi    * 0.20 +
            result.style_fit_score  * w_style * 0.20 +
            result.semantic_score   * w_sem   * 0.15
        ) / max(denom, 0.01)
        raw_global -= result.reject_score * 0.30
        result.global_quality_score = _clamp(raw_global)

        result.explanation = _build_vi_explanation(result, style_id)
        return result

    def apply_scores(
        self,
        frags: List[dict],
        preset_settings: Optional[dict] = None,
        style_id: str = "",
    ) -> List[dict]:
        """
        Score all frags and write scores back into each dict.
        Enriches dicts with: quality_score, technical_score, aesthetic_score,
        vi_score, style_fit_score, semantic_score, motion_fit, role_score,
        suggested_role, reject_score, _score_explanation.
        Mutates and returns the same list.
        """
        for f in frags:
            s = self.score_fragment(f, preset_settings, style_id)
            f["quality_score"]       = s.global_quality_score
            f["technical_score"]     = s.technical_score
            f["aesthetic_score"]     = s.aesthetic_score
            f["vi_score"]            = s.vi_score
            f["style_fit_score"]     = s.style_fit_score
            f["semantic_score"]      = s.semantic_score
            f["motion_fit"]          = s.motion_fit
            f["role_score"]          = s.role_score
            f["suggested_role"]      = s.suggested_role
            f["reject_score"]        = s.reject_score
            f["_score_explanation"]  = s.explanation
            if s.reject_reasons and not f.get("rejection_reason"):
                f["rejection_reason"] = "; ".join(s.reject_reasons)
        return frags

    def score_for_preset(self, base_scores: Dict, preset: dict) -> float:
        """Compute preset-specific score using preset's scoring_weights."""
        weights = preset.get("scoring_weights", {})
        metrics = base_scores

        score = 0.0
        total_w = 0.0

        mapping = {
            "sharpness": metrics.get("sharpness", 0.5),
            "stability": 1.0 - metrics.get("camera_shake", 0.0),
            "brightness": metrics.get("brightness", 0.5),
            "colorfulness": metrics.get("colorfulness", 0.5),
            "motion": metrics.get("motion_magnitude", 0.5),
            "face_presence": 1.0 if metrics.get("has_face") else 0.0,
            "aesthetic_score": metrics.get("aesthetic_score", 0.5),
        }

        for key, w in weights.items():
            if key in mapping:
                score += mapping[key] * w
                total_w += w

        return round(score / total_w, 3) if total_w > 0 else 0.5

    # ── Score components ───────────────────────────────────────────────────────

    def _technical_score(self, m: dict, w: dict) -> float:
        sharpness = m.get("sharpness", 0.0) * w.get("sharpness", 1.0)
        stability = (1.0 - m.get("camera_shake", 0.0)) * w.get("stability", 1.0)
        brightness_ok = self._brightness_score(m.get("brightness", 0.5)) * 1.0
        contrast = m.get("contrast", 0.5) * 0.8

        total = sharpness + stability + brightness_ok + contrast
        max_possible = w.get("sharpness", 1.0) + w.get("stability", 1.0) + 1.0 + 0.8
        return min(1.0, total / max(max_possible, 0.1))

    def _content_score(self, m: dict, w: dict) -> float:
        score = 0.5  # base — content without people is neutral
        if m.get("has_face"):
            score += 0.3 * w.get("face_presence", 1.0)
            face_size = m.get("face_size_ratio", 0.1)
            score += min(0.2, face_size * 2) * w.get("face_size_bonus", 1.0)
        if m.get("has_person") and not m.get("has_face"):
            score += 0.15 * w.get("face_presence", 1.0)
        return min(1.0, score)

    def _aesthetic_score(self, m: dict, w: dict) -> float:
        aesthetic = m.get("aesthetic_score", 0.5) * w.get("aesthetic_score", 1.0)
        saliency = m.get("saliency_score", 0.5) * 0.7
        colorfulness = m.get("colorfulness", 0.5) * 0.5
        total = aesthetic + saliency + colorfulness
        max_p = w.get("aesthetic_score", 1.0) + 0.7 + 0.5
        return min(1.0, total / max(max_p, 0.1))

    def _brightness_score(self, brightness: float) -> float:
        """Penalize too dark or too bright frames."""
        if brightness < 0.05:
            return 0.0
        if brightness > 0.95:
            return 0.2
        return 1.0 - abs(brightness - 0.50) * 1.5

    # ── Explainability ─────────────────────────────────────────────────────────

    def _reject_reason(self, m: dict) -> Optional[str]:
        thresholds = cfg.quality
        sharpness = m.get("sharpness", 1.0)
        if sharpness < thresholds.get("sharpness_min", 0.04):
            return f"Размытый кадр (резкость {sharpness:.3f} < порога {thresholds.get('sharpness_min', 0.04)})"
        brightness = m.get("brightness", 0.5)
        if brightness < thresholds.get("brightness_min", 0.05):
            return f"Слишком тёмный (яркость {brightness:.2f})"
        if brightness > thresholds.get("brightness_max", 0.95):
            return f"Засветка (яркость {brightness:.2f})"
        shake = m.get("camera_shake", 0.0)
        if shake > 0.9:
            return f"Сильная тряска камеры (shake {shake:.2f})"
        if m.get("is_duplicate"):
            return "Дубль другого фрагмента"
        return None

    def _selection_reason(self, m: dict, tech: float, content: float, aesthetic: float) -> str:
        parts = []

        sharpness = m.get("sharpness", 0.0)
        if sharpness > 0.6:
            parts.append("чёткий кадр")
        elif sharpness > 0.3:
            parts.append("приемлемая резкость")

        shake = m.get("camera_shake", 0.0)
        if shake < 0.2:
            parts.append("стабильная съёмка")

        motion_type = m.get("camera_motion_type", "static")
        if motion_type == "pan":
            parts.append("плавная панорама")
        elif motion_type == "static":
            parts.append("статичная камера")

        if m.get("has_face"):
            count = m.get("face_count", 1)
            parts.append(f"{'лицо' if count == 1 else f'{count} лица'} в кадре")
        elif m.get("has_person"):
            parts.append("человек в кадре")

        scene_type = m.get("scene_type", "")
        if scene_type == "wide":
            parts.append("общий план")
        elif scene_type == "close":
            parts.append("крупный план")

        if aesthetic > 0.7:
            parts.append("высокая эстетика")

        tags = m.get("scene_tags") or []
        if tags:
            parts.append(f"теги: {', '.join(tags[:2])}")

        return "; ".join(parts).capitalize() if parts else "Соответствует критериям качества"


# ── Material sufficiency checker (TZ section 15, point 10) ───────────────────

class MaterialChecker:
    """Check if available material is sufficient for the requested duration."""

    def check(
        self,
        candidates: List[Any],
        target_duration_s: float,
        preset: dict,
    ) -> Dict[str, Any]:
        """
        Returns {
            sufficient: bool,
            available_duration_s: float,
            coverage_ratio: float,
            warnings: List[str],
        }
        """
        min_dur = preset.get("clip_selection", {}).get("segment_min_duration", 1.0)
        max_dur = preset.get("clip_selection", {}).get("segment_max_duration", 10.0)
        min_quality = preset.get("clip_selection", {}).get("min_quality_score", 0.40)

        usable = [
            c for c in candidates
            if (getattr(c, "quality_score", 0) or 0) >= min_quality
            and min_dur <= (getattr(c, "duration_s", 0) or 0) <= max_dur
        ]

        available_s = sum(getattr(c, "duration_s", 0) or 0 for c in usable)
        comfortable = cfg.get("coverage.comfortable_ratio", 1.5)
        coverage = available_s / max(target_duration_s, 1.0)

        warnings = []
        if available_s < target_duration_s:
            warnings.append(
                f"⚠️ Материала недостаточно: доступно {available_s:.0f}с, "
                f"нужно {target_duration_s:.0f}с. "
                f"Рендер может повторять фрагменты или получиться короче."
            )
        elif coverage < comfortable:
            warnings.append(
                f"⚠️ Мало разнообразия: {available_s:.0f}с материала при цели {target_duration_s:.0f}с "
                f"(рекомендуется {comfortable}× = {target_duration_s * comfortable:.0f}с). "
                f"Варианты A/B/C/D будут похожи."
            )

        return {
            "sufficient": available_s >= target_duration_s,
            "available_duration_s": available_s,
            "usable_clip_count": len(usable),
            "total_clip_count": len(candidates),
            "coverage_ratio": round(coverage, 2),
            "warnings": warnings,
        }


# ── Module-level helpers ──────────────────────────────────────────────────────

def _clamp(v: float) -> float:
    return float(max(0.0, min(1.0, v)))


def _score_role(frag: dict, role: str, role_rules: dict) -> float:
    """How well the fragment fits its assigned role given preset role_rules."""
    key = "intro" if role == "intro" else ("ending" if role in ("outro", "ending") else "main_part")
    rule = role_rules.get(key, {})
    preferred_tags = set(rule.get("preferred_tags", []))
    dur_rule       = rule.get("duration_sec", {})
    fragment_tags  = set(frag.get("scene_tags", []))
    dur            = float(frag.get("end_s", 0) - frag.get("start_s", 0))

    score = 0.5
    if preferred_tags and fragment_tags:
        overlap = len(fragment_tags & preferred_tags)
        score = _clamp(0.4 + overlap * 0.15)
    if dur_rule:
        min_d = dur_rule.get("min", 0)
        max_d = dur_rule.get("max", 999)
        if min_d <= dur <= max_d:
            score = min(1.0, score + 0.10)
        else:
            score = max(0.0, score - 0.15)
    return score


def _build_vi_explanation(s: FragmentScore, style_id: str) -> str:
    parts = [
        f"global={s.global_quality_score:.2f}",
        f"tech={s.technical_score:.2f}",
        f"aes={s.aesthetic_score:.2f}",
        f"vi={s.vi_score:.2f}",
    ]
    if style_id:
        parts.append(f"style({style_id})={s.style_fit_score:.2f}")
    parts.append(f"role={s.suggested_role}({s.role_score:.2f})")
    if s.reject_reasons:
        parts.append(f"REJECT: {'; '.join(s.reject_reasons)}")
    return " | ".join(parts)
