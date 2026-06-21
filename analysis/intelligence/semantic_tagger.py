"""
SemanticTagger — assigns semantic tags to a video segment.

Backend: rule_based (default, no GPU) | clip (requires open_clip / torch).
Rule-based uses colour histograms + motion magnitude + basic heuristics.
CLIP backend runs zero-shot classification when available.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Canonical tag taxonomy (matches defaults.yaml video_intelligence.semantic_tagger.tag_taxonomy)
ALL_TAGS: List[str] = [
    "drone", "aerial", "nature", "landscape", "sunset", "sunrise",
    "crowd", "people", "sport", "action", "urban", "architecture",
    "water", "mountain", "forest", "beach", "indoor", "studio",
    "face_closeup", "product",
]

_CONTEXT_GROUPS = {
    "outdoor": {"nature", "landscape", "sunset", "sunrise", "drone", "aerial",
                "water", "mountain", "forest", "beach", "sport", "action", "urban"},
    "indoor":  {"indoor", "studio", "product", "face_closeup"},
}


@dataclass
class TagResult:
    tags: List[str]                          # ordered by confidence (highest first)
    primary_tag: str
    scene_context: str                       # "indoor" | "outdoor" | "studio" | "nature" | "urban"
    confidences: dict = field(default_factory=dict)   # tag → score


class SemanticTagger:
    """
    Assign semantic tags to a clip segment.

    Args:
        backend: "rule_based" or "clip"
        min_confidence: Minimum score to include a tag.
        max_tags: Maximum tags per segment.
    """

    def __init__(
        self,
        backend: str = "rule_based",
        min_confidence: float = 0.60,
        max_tags: int = 5,
        clip_model: str = "ViT-B/32",
    ):
        self.backend        = backend
        self.min_confidence = min_confidence
        self.max_tags       = max_tags
        self.clip_model     = clip_model
        self._clip_model_obj = None

    def tag_segment(
        self,
        video_path: str,
        start_s: float = 0.0,
        end_s: Optional[float] = None,
        motion_type: Optional[str] = None,
        quality_metrics: Optional[dict] = None,
    ) -> TagResult:
        """
        Tag a video segment.

        Args:
            video_path:       Path to source video file.
            start_s/end_s:    Segment time range.
            motion_type:      Pre-computed camera motion type (saves re-computation).
            quality_metrics:  Dict with keys from QualityMetrics fields (optional boost).

        Returns:
            TagResult with ordered tags and scene_context.
        """
        if self.backend == "clip":
            try:
                return self._tag_clip(video_path, start_s, end_s)
            except Exception as exc:
                logger.warning(f"[SemanticTagger] CLIP failed ({exc}), falling back to rule_based")

        return self._tag_rule_based(video_path, start_s, end_s, motion_type, quality_metrics)

    # ── Rule-based backend ────────────────────────────────────────────────────

    def _tag_rule_based(
        self,
        video_path: str,
        start_s: float,
        end_s: Optional[float],
        motion_type: Optional[str],
        quality_metrics: Optional[dict],
    ) -> TagResult:
        scores: dict = {tag: 0.0 for tag in ALL_TAGS}

        try:
            import cv2
            import numpy as np

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise RuntimeError("Cannot open video")

            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            end_s_eff = end_s if end_s else total / fps
            mid_frame = int(((start_s + end_s_eff) / 2) * fps)

            cap.set(cv2.CAP_PROP_POS_FRAMES, min(mid_frame, total - 1))
            ret, frame = cap.read()
            cap.release()

            if ret:
                self._score_from_frame(frame, scores)

        except Exception as exc:
            logger.debug(f"[SemanticTagger] frame analysis failed: {exc}")

        # Motion-based boosts
        if motion_type:
            self._boost_from_motion(motion_type, scores)

        # Quality metrics boosts
        if quality_metrics:
            self._boost_from_quality(quality_metrics, scores)

        return self._build_result(scores)

    def _score_from_frame(self, frame, scores: dict) -> None:
        """Analyse a single representative frame for colour/content clues."""
        import cv2
        import numpy as np

        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # ── Sky / outdoor heuristic ───────────────────────────────────────────
        top_half_hsv = hsv[:h//2, :, :]
        blue_mask    = cv2.inRange(top_half_hsv, (95, 30, 80), (135, 255, 255))
        blue_ratio   = float(np.count_nonzero(blue_mask)) / (w * h // 2)
        if blue_ratio > 0.25:
            scores["nature"]    = max(scores["nature"],    0.65)
            scores["landscape"] = max(scores["landscape"], 0.60)
            scores["outdoor"]   = 0.0  # not a real tag — used for context

        # ── Warm orange/red at top → sunset/sunrise ──────────────────────────
        warm_mask = cv2.inRange(top_half_hsv, (5, 80, 100), (30, 255, 255))
        warm_ratio = float(np.count_nonzero(warm_mask)) / (w * h // 2)
        if warm_ratio > 0.20:
            scores["sunset"]  = max(scores["sunset"],  0.70)
            scores["sunrise"] = max(scores["sunrise"], 0.60)

        # ── High brightness & blue → water/beach ─────────────────────────────
        lower_half_hsv = hsv[h//2:, :, :]
        blue_lower = cv2.inRange(lower_half_hsv, (90, 40, 60), (130, 255, 255))
        if float(np.count_nonzero(blue_lower)) / (w * h // 2) > 0.30:
            scores["water"] = max(scores["water"], 0.65)
            scores["beach"] = max(scores["beach"], 0.50)

        # ── Green dominance → forest / nature ────────────────────────────────
        green_mask = cv2.inRange(hsv, (35, 40, 40), (85, 255, 200))
        green_ratio = float(np.count_nonzero(green_mask)) / (w * h)
        if green_ratio > 0.35:
            scores["forest"]  = max(scores["forest"],  0.65)
            scores["nature"]  = max(scores["nature"],  0.60)
            scores["outdoor"] = 0.0

        # ── Low brightness → indoor ───────────────────────────────────────────
        mean_v = float(np.mean(hsv[:, :, 2]))
        if mean_v < 80:
            scores["indoor"] = max(scores["indoor"], 0.55)

        # ── High saturation uniformity → studio ──────────────────────────────
        std_s = float(np.std(hsv[:, :, 1]))
        if std_s < 25 and mean_v > 100:
            scores["studio"] = max(scores["studio"], 0.55)

    def _boost_from_motion(self, motion_type: str, scores: dict) -> None:
        boosts = {
            "aerial_forward":  {"drone": 0.85, "aerial": 0.85, "landscape": 0.55},
            "aerial_descent":  {"drone": 0.80, "aerial": 0.80},
            "pan_left":        {"landscape": 0.45},
            "pan_right":       {"landscape": 0.45},
            "zoom_in":         {"face_closeup": 0.45, "action": 0.40},
            "shake":           {"action": 0.55, "sport": 0.45},
            "handheld":        {"people": 0.40, "action": 0.35},
            "static":          {"product": 0.40, "studio": 0.35},
        }
        for tag, boost in boosts.get(motion_type, {}).items():
            if tag in scores:
                scores[tag] = max(scores[tag], boost)

    def _boost_from_quality(self, qm: dict, scores: dict) -> None:
        if qm.get("has_face"):
            scores["people"]       = max(scores["people"],       0.60)
            scores["face_closeup"] = max(scores["face_closeup"], 0.55 if qm.get("face_size_ratio", 0) > 0.15 else 0.40)
        if qm.get("person_count", 0) > 3:
            scores["crowd"] = max(scores["crowd"], 0.65)

    def _build_result(self, scores: dict) -> TagResult:
        filtered = {t: s for t, s in scores.items() if s >= self.min_confidence}
        ordered  = sorted(filtered, key=lambda t: filtered[t], reverse=True)[: self.max_tags]

        primary = ordered[0] if ordered else "unknown"

        # Determine scene_context
        tag_set = set(ordered)
        if tag_set & {"drone", "aerial"}:
            context = "aerial"
        elif tag_set & {"studio", "product"}:
            context = "studio"
        elif tag_set & {"indoor"}:
            context = "indoor"
        elif tag_set & _CONTEXT_GROUPS["outdoor"]:
            context = "outdoor"
        else:
            context = "indoor"

        return TagResult(
            tags=ordered,
            primary_tag=primary,
            scene_context=context,
            confidences={t: scores[t] for t in ordered},
        )

    # ── CLIP backend ──────────────────────────────────────────────────────────

    def _tag_clip(
        self,
        video_path: str,
        start_s: float,
        end_s: Optional[float],
    ) -> TagResult:
        import open_clip
        import torch
        import cv2
        import numpy as np
        from PIL import Image

        if self._clip_model_obj is None:
            model, _, preprocess = open_clip.create_model_and_transforms(self.clip_model)
            model.eval()
            tokenizer = open_clip.get_tokenizer(self.clip_model)
            self._clip_model_obj = (model, preprocess, tokenizer)

        model, preprocess, tokenizer = self._clip_model_obj

        # Sample one frame from the middle of the clip
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        end_eff = end_s if end_s else total / fps
        cap.set(cv2.CAP_PROP_POS_FRAMES, int((start_s + end_eff) / 2 * fps))
        ret, frame = cap.read()
        cap.release()
        if not ret:
            raise RuntimeError("Could not read frame")

        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        image_tensor = preprocess(img).unsqueeze(0)

        prompts = [f"a video of {tag.replace('_', ' ')}" for tag in ALL_TAGS]
        text_tokens = tokenizer(prompts)

        with torch.no_grad():
            image_features = model.encode_image(image_tensor)
            text_features  = model.encode_text(text_tokens)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            text_features  /= text_features.norm(dim=-1, keepdim=True)
            sims = (100.0 * image_features @ text_features.T).softmax(dim=-1)[0]

        scores = {ALL_TAGS[i]: float(sims[i]) for i in range(len(ALL_TAGS))}
        return self._build_result(scores)
