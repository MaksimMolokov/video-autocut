"""
ConceptService — infers a high-level VideoConcept from enriched fragment dicts.

Aggregates semantic tags, motion types, and quality scores across all fragments
to determine the project's concept_type, narrative_arc, energy_profile, and
dominant_tags. Result can be persisted to the VideoConcept ORM table.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Concept detection rules — tag sets that strongly suggest a concept
_CONCEPT_RULES: Dict[str, set] = {
    "travel":   {"drone", "aerial", "landscape", "nature", "beach", "mountain",
                 "forest", "urban", "architecture"},
    "wedding":  {"face_closeup", "studio", "indoor", "people"},
    "sport":    {"sport", "action", "crowd"},
    "product":  {"product", "studio", "indoor"},
    "nature":   {"nature", "landscape", "sunset", "sunrise", "forest",
                 "water", "beach", "mountain"},
    "event":    {"crowd", "people", "urban"},
}

_NARRATIVE_ARC_MAP: Dict[str, str] = {
    "wedding":  "three_act",
    "travel":   "journey",
    "sport":    "highlight_reel",
    "event":    "highlight_reel",
    "product":  "montage",
    "nature":   "journey",
    "other":    "montage",
}


@dataclass
class ConceptResult:
    concept_type: str          # travel | wedding | sport | event | product | nature | other
    narrative_arc: str         # three_act | highlight_reel | journey | montage
    dominant_tags: List[str]   # top-5 tags by occurrence
    energy_profile: str        # low | medium | high | dynamic
    description: str           # human-readable summary
    confidence: float          # 0–1


class ConceptService:
    """
    Infer the project concept from enriched fragment dicts.

    Usage:
        result = ConceptService().infer(fragments)
        # → ConceptResult(concept_type="travel", narrative_arc="journey", ...)
    """

    MIN_CLIPS = 3   # minimum clips needed to make a meaningful inference

    def infer(self, fragments: List[Dict[str, Any]]) -> Optional[ConceptResult]:
        """
        Infer concept from a list of enriched fragment dicts.

        Returns None if there are too few fragments for a confident inference.
        """
        if len(fragments) < self.MIN_CLIPS:
            return None

        tag_counter     = Counter()
        motion_counter  = Counter()
        quality_scores  = []
        has_aerial      = False

        for frag in fragments:
            # Semantic tags
            for t in (frag.get("semantic_tags") or frag.get("scene_tags") or []):
                tag_counter[t] += 1

            # Motion types
            mt = frag.get("camera_motion_type") or "unknown"
            motion_counter[mt] += 1

            # Quality
            q = frag.get("quality_score", 0.5)
            quality_scores.append(q)

            # Aerial flag (strong concept signal)
            if mt in ("aerial_forward", "aerial_descent") or \
               "drone" in (frag.get("semantic_tags") or []) or \
               "aerial" in (frag.get("semantic_tags") or []):
                has_aerial = True

        dominant_tags = [t for t, _ in tag_counter.most_common(5)]
        concept_type, confidence = self._classify_concept(tag_counter, has_aerial)

        # ROADMAP Фаза 5, SEM-2: уточнение концепции через CLIP zero-shot.
        # Self-disable без torch/open_clip — эвристика остаётся источником истины.
        try:
            concept_type, confidence = self._refine_with_clip(
                fragments, concept_type, confidence)
        except Exception as clip_exc:  # noqa: BLE001
            logger.debug("[Concept] CLIP refine skipped: %s", clip_exc)

        narrative_arc = _NARRATIVE_ARC_MAP.get(concept_type, "montage")
        energy_profile = self._classify_energy(quality_scores, motion_counter)
        description = self._describe(concept_type, dominant_tags, energy_profile, has_aerial)

        return ConceptResult(
            concept_type   = concept_type,
            narrative_arc  = narrative_arc,
            dominant_tags  = dominant_tags,
            energy_profile = energy_profile,
            description    = description,
            confidence     = confidence,
        )

    def infer_and_save(
        self,
        session,
        project_id: int,
        fragments: List[Dict[str, Any]],
    ) -> Optional[ConceptResult]:
        """Infer concept and upsert into the VideoConcept ORM table."""
        result = self.infer(fragments)
        if result is None:
            return None

        from infrastructure.database.models import VideoConcept

        # Deactivate prior concepts for this project
        session.query(VideoConcept).filter_by(project_id=project_id, is_active=True)\
               .update({"is_active": False})

        session.add(VideoConcept(
            project_id     = project_id,
            concept_type   = result.concept_type,
            narrative_arc  = result.narrative_arc,
            dominant_tags  = result.dominant_tags,
            energy_profile = result.energy_profile,
            description    = result.description,
            confidence     = result.confidence,
            is_active      = True,
            created_at     = time.time(),
            updated_at     = time.time(),
        ))
        session.commit()
        return result

    # ── Internal ──────────────────────────────────────────────────────────────

    # Текстовые описания концепций для CLIP zero-shot (SEM-2).
    _CLIP_CONCEPT_PROMPTS = {
        "travel":  "travel and tourism footage, scenic locations",
        "wedding": "a wedding ceremony with people, romantic",
        "sport":   "sports action, athletes competing, fast movement",
        "event":   "a live event or party with a crowd of people",
        "product": "a product showcase or commercial advertisement",
        "nature":  "nature and wildlife, landscapes, no people",
    }

    def _refine_with_clip(self, fragments, rule_concept: str, rule_conf: float):
        """Скорректировать концепцию zero-shot скором CLIP (SEM-2).

        CLIP-результат блендится с правиловым: если CLIP уверенно указывает на
        другую концепцию — она побеждает; иначе CLIP лишь повышает уверенность.
        """
        from analysis.content.clip_scorer import CLIPScorer
        scorer = CLIPScorer()
        if not scorer.available:
            return rule_concept, rule_conf
        labels = list(self._CLIP_CONCEPT_PROMPTS.keys())
        prompts = [self._CLIP_CONCEPT_PROMPTS[k] for k in labels]
        scores = scorer.zero_shot_fragments(fragments, prompts)
        if not scores:
            return rule_concept, rule_conf
        # scores keyed by prompt → перевести обратно в метки
        by_label = {labels[i]: scores[p] for i, p in enumerate(prompts)}
        clip_concept = max(by_label, key=by_label.get)
        clip_conf = by_label[clip_concept]
        if clip_concept == rule_concept:
            return rule_concept, round(min(1.0, max(rule_conf, clip_conf) + 0.1), 3)
        if clip_conf > 0.5 and clip_conf > rule_conf:
            logger.info("[Concept] CLIP override %s→%s (%.2f vs %.2f)",
                        rule_concept, clip_concept, clip_conf, rule_conf)
            return clip_concept, round(clip_conf, 3)
        return rule_concept, rule_conf

    def _classify_concept(
        self, tag_counter: Counter, has_aerial: bool
    ) -> tuple[str, float]:
        if has_aerial:
            # Aerial footage is very specific — check travel vs nature
            if tag_counter.get("urban", 0) + tag_counter.get("architecture", 0) > 0:
                return "travel", 0.85
            return "nature", 0.80

        best_concept, best_score = "other", 0.0
        total_tags = sum(tag_counter.values()) or 1

        for concept, tag_set in _CONCEPT_RULES.items():
            overlap = sum(tag_counter.get(t, 0) for t in tag_set)
            score   = overlap / total_tags
            if score > best_score:
                best_score   = score
                best_concept = concept

        confidence = min(1.0, best_score * 3.0)   # scale up for readability
        return best_concept, confidence

    def _classify_energy(
        self, quality_scores: List[float], motion_counter: Counter
    ) -> str:
        high_motion = (
            motion_counter.get("shake", 0) +
            motion_counter.get("handheld", 0) +
            motion_counter.get("zoom_in", 0)
        )
        static_motion = motion_counter.get("static", 0) + motion_counter.get("dolly", 0)
        total = sum(motion_counter.values()) or 1

        high_ratio   = high_motion / total
        static_ratio = static_motion / total

        if high_ratio > 0.5:
            return "high"
        if static_ratio > 0.5:
            return "low"
        if high_ratio > 0.25:
            return "dynamic"
        return "medium"

    @staticmethod
    def _describe(concept: str, tags: List[str], energy: str, aerial: bool) -> str:
        tag_str = ", ".join(tags[:3]) if tags else "mixed content"
        aerial_note = " (aerial footage)" if aerial else ""
        energy_map = {
            "high": "динамичный", "low": "спокойный",
            "medium": "умеренный", "dynamic": "переменный",
        }
        energy_label = energy_map.get(energy, energy)
        concept_map = {
            "travel": "Путешествие", "wedding": "Свадьба", "sport": "Спорт",
            "event": "Событие", "product": "Продукт", "nature": "Природа",
            "other": "Смешанный",
        }
        return (
            f"{concept_map.get(concept, concept)}{aerial_note} — "
            f"{energy_label} темп, основные теги: {tag_str}."
        )
