"""
Clip Scorer - вычисление score для candidate clips на основе стратегии
"""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class ClipScorer:
    """
    Вычисление score для candidate clips

    Использует веса признаков из стратегии для scoring
    """

    @staticmethod
    def score_clips(
        candidates: List,  # List[CandidateClip]
        strategy  # ClipSelectionStrategy
    ) -> List:
        """
        Вычислить preset_score для каждого candidate clip

        Formula:
        preset_score = sum(feature_value * weight) / sum(weights)

        Args:
            candidates: List of CandidateClip objects
            strategy: ClipSelectionStrategy instance

        Returns:
            candidates with filled preset_score
        """
        weights = strategy.get_feature_weights()

        # Total weight for normalization
        total_weight = sum(weights.values())

        scored_count = 0

        for clip in candidates:
            f = clip.features

            # Calculate weighted sum
            score = (
                f.sharpness_score * weights.get('sharpness', 1.0) +
                f.brightness_score * weights.get('brightness', 0.8) +
                f.contrast_score * weights.get('contrast', 0.7) +
                f.motion_score * weights.get('motion', 0.5) +
                f.camera_stability_score * weights.get('stability', 1.0) +
                f.visual_complexity_score * weights.get('visual_complexity', 0.8) +
                f.uniqueness_score * weights.get('uniqueness', 1.0) +
                f.action_score * weights.get('action', 0.5) +
                f.calm_score * weights.get('calm', 0.5) +
                f.technical_quality_score * weights.get('technical_quality', 1.0)
            )

            # Normalize to [0, 1]
            clip.preset_score = score / total_weight if total_weight > 0 else 0.0
            scored_count += 1

        logger.info(
            f"Scored {scored_count} clips using strategy '{strategy.get_strategy_name()}'"
        )

        return candidates

    @staticmethod
    def get_top_clips(
        candidates: List,  # List[CandidateClip]
        count: int,
        by_score: str = 'final_score'
    ) -> List:
        """
        Получить top N клипов по score

        Args:
            candidates: List of CandidateClip objects
            count: Number of clips to return
            by_score: Which score to use ('preset_score', 'final_score', etc.)

        Returns:
            Top N candidates sorted by score (descending)
        """
        if by_score == 'preset_score':
            sorted_clips = sorted(candidates, key=lambda c: c.preset_score, reverse=True)
        elif by_score == 'final_score':
            sorted_clips = sorted(candidates, key=lambda c: c.final_score, reverse=True)
        elif by_score == 'uniqueness_score':
            sorted_clips = sorted(candidates, key=lambda c: c.uniqueness_score, reverse=True)
        else:
            sorted_clips = candidates

        return sorted_clips[:count]

    @staticmethod
    def compute_final_scores(
        candidates: List  # List[CandidateClip]
    ) -> List:
        """
        Вычислить final_score для каждого клипа

        Final score учитывает:
        - preset_score
        - uniqueness_score
        - diversity_penalty
        - previous_usage_penalty

        Formula:
        final_score = preset_score * (1.0 - diversity_penalty) * (1.0 - previous_usage_penalty)

        Args:
            candidates: List of CandidateClip objects

        Returns:
            candidates with filled final_score
        """
        for clip in candidates:
            # Base score
            base_score = clip.preset_score

            # Apply penalties
            diversity_factor = 1.0 - clip.diversity_penalty
            previous_usage_factor = 1.0 - clip.previous_usage_penalty

            clip.final_score = base_score * diversity_factor * previous_usage_factor

        return candidates

    @staticmethod
    def log_score_distribution(
        candidates: List,  # List[CandidateClip]
        score_field: str = 'final_score'
    ):
        """
        Логировать распределение scores

        Args:
            candidates: List of CandidateClip objects
            score_field: Which score field to analyze
        """
        if not candidates:
            logger.warning("No candidates to analyze")
            return

        scores = []
        for clip in candidates:
            if score_field == 'preset_score':
                scores.append(clip.preset_score)
            elif score_field == 'final_score':
                scores.append(clip.final_score)
            elif score_field == 'uniqueness_score':
                scores.append(clip.uniqueness_score)

        if not scores:
            return

        min_score = min(scores)
        max_score = max(scores)
        avg_score = sum(scores) / len(scores)

        logger.info(
            f"Score distribution ({score_field}): "
            f"min={min_score:.3f}, max={max_score:.3f}, avg={avg_score:.3f}"
        )


if __name__ == "__main__":
    # Test clip scorer
    print("ClipScorer utility - use in integration with CandidateClip and Strategy")
