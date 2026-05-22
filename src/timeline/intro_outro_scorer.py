"""
Scores CandidateClip objects for intro / outro suitability using
the per-style weights defined in IntroOutroProfile.
"""

from __future__ import annotations
import logging
import random
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

# Import inside functions to avoid circular-import issues at module load time.


class IntroOutroScorer:
    """
    Stateless scorer — all methods are static.

    Uses ClipFeatures fields directly; all values are expected [0, 1].
    """

    # Conditions checked in the forbidden list.
    # Each maps a token to a lambda (features) -> bool that returns True when
    # the condition is triggered (clip SHOULD be excluded).
    _FORBIDDEN_CHECKS = {
        'black_frame':    lambda f: f.brightness_score < 0.08,
        'blur':           lambda f: f.sharpness_score < 0.15,
        'shaky':          lambda f: f.camera_stability_score < 0.20,
        'camera_starting': lambda f: False,   # enforced via skip_source_start_sec
        'camera_ending':  lambda f: False,    # enforced via skip_source_end_sec
        'low_brightness': lambda f: f.brightness_score < 0.18,
        'high_motion':    lambda f: f.motion_score > 0.80,
        'low_motion':     lambda f: f.motion_score < 0.12,
        'low_action':     lambda f: f.action_score < 0.15,
        'no_subject':     lambda f: f.visual_complexity_score < 0.10,
        'scene_change':   lambda f: f.scene_change_score > 0.70,
    }

    # ClipFeatures attribute names available for weighting
    _FEATURE_ATTRS = {
        'sharpness_score', 'brightness_score', 'contrast_score',
        'motion_score', 'camera_stability_score', 'visual_complexity_score',
        'scene_change_score', 'color_saturation_score', 'color_diversity_score',
        'action_score', 'calm_score', 'technical_quality_score',
        'uniqueness_score',
    }

    @staticmethod
    def _apply_weights(features, weights: dict) -> float:
        """Dot-product of weight map against ClipFeatures values."""
        score = 0.0
        for attr, w in weights.items():
            val = getattr(features, attr, 0.0)
            score += val * w
        return score

    @staticmethod
    def _is_forbidden(features, forbidden_tokens: List[str]) -> bool:
        for token in forbidden_tokens:
            check = IntroOutroScorer._FORBIDDEN_CHECKS.get(token)
            if check and check(features):
                return True
        return False

    @staticmethod
    def _passes_hard_thresholds(features, rule) -> bool:
        """Check min/max hard thresholds from a VideoIntroRule or VideoOutroRule."""
        if features.sharpness_score < rule.min_sharpness:
            return False
        if features.brightness_score < rule.min_brightness:
            return False
        # VideoIntroRule extras
        if hasattr(rule, 'min_action') and features.action_score < rule.min_action:
            return False
        if hasattr(rule, 'max_calm') and features.calm_score > rule.max_calm:
            return False
        if hasattr(rule, 'min_stability') and features.camera_stability_score < rule.min_stability:
            return False
        return True

    @staticmethod
    def score_intro(candidate, profile) -> Optional[float]:
        """
        Score a CandidateClip for intro suitability.
        Returns None if the candidate is disqualified (forbidden / fails threshold).
        """
        rule = profile.video_intro
        f = candidate.features

        if IntroOutroScorer._is_forbidden(f, rule.forbidden):
            return None
        if not IntroOutroScorer._passes_hard_thresholds(f, rule):
            return None

        raw = IntroOutroScorer._apply_weights(f, rule.weights)
        # Blend with candidate's existing final_score (diversity already applied).
        blended = raw * 0.70 + candidate.final_score * 0.30
        return blended

    @staticmethod
    def score_outro(candidate, profile) -> Optional[float]:
        """
        Score a CandidateClip for outro suitability.
        Returns None if the candidate is disqualified.
        """
        rule = profile.video_outro
        f = candidate.features

        if IntroOutroScorer._is_forbidden(f, rule.forbidden):
            return None
        if not IntroOutroScorer._passes_hard_thresholds(f, rule):
            return None

        raw = IntroOutroScorer._apply_weights(f, rule.weights)
        blended = raw * 0.70 + candidate.final_score * 0.30
        return blended

    @staticmethod
    def pick_best_intro(
        candidates: list,
        profile,
        n: int = 1,
        excluded_ids: Optional[Set[str]] = None,
        seed: int = 42,
    ) -> list:
        """
        Return up to n candidates best suited to be intro segments.

        excluded_ids: set of scene_id strings that must not be chosen
                      (used to force variant B/C/D to use a different opening).
        seed:         used to break score ties deterministically but differently per variant.
        """
        from .intro_outro_rules import VideoIntroRule
        from .variant_constraints import scene_id as _sid
        skip = profile.video_intro.skip_source_start_sec
        excl = excluded_ids or set()

        scored = []
        for c in candidates:
            if c.start <= skip:
                continue
            if _sid(c) in excl:
                continue
            s = IntroOutroScorer.score_intro(c, profile)
            if s is not None:
                scored.append((s, c))

        if not scored and excl:
            # Fallback: relax exclusion (accept same opening rather than no intro)
            for c in candidates:
                if c.start <= skip:
                    continue
                s = IntroOutroScorer.score_intro(c, profile)
                if s is not None:
                    scored.append((s, c))

        # Sort by score descending, break ties with seeded shuffle
        scored.sort(key=lambda x: x[0], reverse=True)
        rng = random.Random(seed)
        # Shuffle groups within a ±0.02 band
        result = []
        i = 0
        while i < len(scored):
            j = i + 1
            while j < len(scored) and abs(scored[j][0] - scored[i][0]) < 0.02:
                j += 1
            group = scored[i:j]
            rng.shuffle(group)
            result.extend(group)
            i = j

        return [c for _, c in result[:n]]

    @staticmethod
    def pick_best_outro(
        candidates: list,
        profile,
        n: int = 1,
        excluded_ids: Optional[Set[str]] = None,
        seed: int = 42,
    ) -> list:
        """
        Return up to n candidates best suited to be outro segments.

        excluded_ids: set of scene_id strings that must not be chosen.
        seed:         tie-breaking seed.
        """
        from .variant_constraints import scene_id as _sid
        skip = profile.video_outro.skip_source_end_sec
        excl = excluded_ids or set()

        scored = []
        for c in candidates:
            if c.start <= skip:
                continue
            if _sid(c) in excl:
                continue
            s = IntroOutroScorer.score_outro(c, profile)
            if s is not None:
                scored.append((s, c))

        if not scored and excl:
            for c in candidates:
                if c.start <= skip:
                    continue
                s = IntroOutroScorer.score_outro(c, profile)
                if s is not None:
                    scored.append((s, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        rng = random.Random(seed + 1)
        result = []
        i = 0
        while i < len(scored):
            j = i + 1
            while j < len(scored) and abs(scored[j][0] - scored[i][0]) < 0.02:
                j += 1
            group = scored[i:j]
            rng.shuffle(group)
            result.extend(group)
            i = j

        return [c for _, c in result[:n]]
