"""
Diversity Selector - выбор клипов с учетом разнообразия
"""

import logging
import random
from typing import List, Set, Tuple

logger = logging.getLogger(__name__)


class DiversitySelector:
    """
    Выбор клипов с максимальным разнообразием

    Избегает выбора слишком похожих соседних клипов
    """

    @staticmethod
    def compute_uniqueness_scores(candidates: List) -> List:
        """
        Вычислить uniqueness_score для каждого клипа

        Логика:
        - Сравнить признаки каждого клипа с признаками всех других
        - Клип уникален, если его признаки сильно отличаются от остальных

        Args:
            candidates: List of CandidateClip objects

        Returns:
            candidates with filled uniqueness_score
        """
        if len(candidates) < 2:
            # Если клип один, он уникален
            for clip in candidates:
                clip.uniqueness_score = 1.0
            return candidates

        logger.info(f"Computing uniqueness scores for {len(candidates)} candidates...")

        for i, clip in enumerate(candidates):
            differences = []

            for j, other in enumerate(candidates):
                if i == j:
                    continue

                diff = DiversitySelector._feature_distance(clip.features, other.features)
                differences.append(diff)

            # Uniqueness = средняя разница с другими клипами
            clip.uniqueness_score = sum(differences) / len(differences) if differences else 0.0

        logger.debug(
            f"Uniqueness scores: "
            f"min={min(c.uniqueness_score for c in candidates):.3f}, "
            f"max={max(c.uniqueness_score for c in candidates):.3f}"
        )

        return candidates

    @staticmethod
    def _feature_distance(f1, f2) -> float:
        """
        Вычислить расстояние между двумя наборами признаков

        Использует евклидово расстояние по ключевым признакам

        Args:
            f1, f2: ClipFeatures objects

        Returns:
            Distance value (0.0 - 1.0)
        """
        # Ключевые признаки для сравнения
        diff_motion = abs(f1.motion_score - f2.motion_score)
        diff_brightness = abs(f1.brightness_score - f2.brightness_score)
        diff_complexity = abs(f1.visual_complexity_score - f2.visual_complexity_score)
        diff_stability = abs(f1.camera_stability_score - f2.camera_stability_score)
        diff_action = abs(f1.action_score - f2.action_score)

        # Евклидово расстояние
        distance = (
            diff_motion**2 +
            diff_brightness**2 +
            diff_complexity**2 +
            diff_stability**2 +
            diff_action**2
        ) ** 0.5

        # Нормализация (sqrt(5) = ~2.236 максимальное расстояние)
        return distance / 2.236

    @staticmethod
    def select_with_diversity(
        candidates: List,  # List[CandidateClip]
        target_count: int,
        diversity_threshold: float = 0.3,
        randomness: float = 0.3
    ) -> List:
        """
        Выбрать target_count клипов с максимальным разнообразием

        Алгоритм:
        1. Отсортировать по preset_score
        2. Взять лучший клип
        3. Для каждого следующего клипа:
           - Проверить diversity с уже выбранными
           - Если достаточно отличается - взять
           - Иначе пропустить
        4. Если не хватило, добрать лучшими оставшимися

        Args:
            candidates: List of CandidateClip objects
            target_count: Number of clips to select
            diversity_threshold: Minimum distance between clips
            randomness: Level of randomness (0.0 = deterministic, 1.0 = maximum)

        Returns:
            Selected clips
        """
        if not candidates:
            return []

        if len(candidates) <= target_count:
            return candidates

        logger.info(
            f"Selecting {target_count} clips from {len(candidates)} candidates "
            f"with diversity_threshold={diversity_threshold:.2f}"
        )

        # Сортировка по score (лучшие первые)
        # Добавляем небольшую случайность
        if randomness > 0:
            # Shuffle slightly: лучшие остаются в топе, но порядок варьируется
            sorted_candidates = sorted(
                candidates,
                key=lambda c: c.preset_score + random.uniform(-randomness, randomness),
                reverse=True
            )
        else:
            sorted_candidates = sorted(candidates, key=lambda c: c.preset_score, reverse=True)

        selected = []

        # Берем лучший
        selected.append(sorted_candidates[0])

        # Проходим по остальным
        for candidate in sorted_candidates[1:]:
            if len(selected) >= target_count:
                break

            # Проверить diversity с уже выбранными
            min_distance = min(
                DiversitySelector._feature_distance(candidate.features, s.features)
                for s in selected
            )

            if min_distance >= diversity_threshold:
                # Достаточно отличается
                selected.append(candidate)
            else:
                # Слишком похож, записываем penalty для final_score
                candidate.diversity_penalty = 1.0 - (min_distance / diversity_threshold)

        # Если не хватило, добрать лучшими оставшимися
        if len(selected) < target_count:
            remaining = [c for c in sorted_candidates if c not in selected]
            needed = target_count - len(selected)

            logger.info(
                f"Not enough diverse clips ({len(selected)}/{target_count}), "
                f"adding {needed} best remaining clips"
            )

            selected.extend(remaining[:needed])

        logger.info(f"Selected {len(selected)} clips with diversity")

        return selected

    @staticmethod
    def apply_diversity_penalty(
        candidates: List,  # List[CandidateClip]
        selected: List,  # List[CandidateClip]
        diversity_threshold: float = 0.3
    ) -> List:
        """
        Применить diversity penalty к кандидатам относительно уже выбранных

        Args:
            candidates: List of CandidateClip objects (not yet selected)
            selected: List of already selected CandidateClip objects
            diversity_threshold: Threshold for diversity

        Returns:
            candidates with diversity_penalty filled
        """
        if not selected:
            # Нет выбранных - нет penalty
            for clip in candidates:
                clip.diversity_penalty = 0.0
            return candidates

        for candidate in candidates:
            # Найти минимальную дистанцию до выбранных клипов
            min_distance = min(
                DiversitySelector._feature_distance(candidate.features, s.features)
                for s in selected
            )

            # Penalty = 1.0 если distance = 0, penalty = 0.0 если distance >= threshold
            if min_distance >= diversity_threshold:
                candidate.diversity_penalty = 0.0
            else:
                candidate.diversity_penalty = 1.0 - (min_distance / diversity_threshold)

        return candidates


if __name__ == "__main__":
    print("DiversitySelector utility - use in integration with CandidateClip")
