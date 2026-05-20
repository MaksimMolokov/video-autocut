"""
Intelligent Beauty Strategy - интеллектуальный выбор красивых кадров
"""

from typing import Dict, List, Optional, Tuple
import logging
from ..strategy import ClipSelectionStrategy

logger = logging.getLogger(__name__)


class IntelligentBeautyStrategy(ClipSelectionStrategy):
    """
    Стратегия для Intelligent Beauty Mix

    Цель:
    - Глубокий анализ видео
    - Поиск самых красивых кадров
    - Техническое качество + композиция + плавность движения
    - Разнообразие сцен
    - Opening/Closing shot selection
    - Music-aware matching (если аудио доступно)
    """

    def get_strategy_name(self) -> str:
        return "intelligent_beauty"

    def get_feature_weights(self) -> Dict[str, float]:
        """
        Высокие веса:
        - technical_quality (1.5) - максимальное техническое качество
        - uniqueness (1.5) - максимальное разнообразие
        - sharpness (1.4) - резкость
        - stability (1.3) - стабильность
        - visual_complexity (1.1) - визуальная насыщенность
        - calm (1.0) - спокойствие

        Средние веса для остального
        """
        return {
            'sharpness': 1.4,
            'brightness': 1.0,
            'contrast': 0.9,
            'motion': 0.6,
            'stability': 1.3,
            'visual_complexity': 1.1,
            'uniqueness': 1.5,
            'action': 0.7,
            'calm': 1.0,
            'technical_quality': 1.5
        }

    def get_ordering_type(self) -> str:
        """Beauty story arc - особая структура"""
        return 'beauty_story_arc'

    def filter_candidates(self, candidates: List) -> List:
        """
        Строгая фильтрация по техническому качеству

        Убираем:
        - Слишком размытые (sharpness < 0.3)
        - Слишком темные или яркие
        - Сильно трясущиеся (stability < 0.3)
        - Низкое техническое качество (technical_quality < 0.4)
        """
        filtered = []

        for clip in candidates:
            f = clip.features

            # Строгие требования к техническому качеству
            if f.sharpness_score < 0.3:
                logger.debug(f"Filtered: {clip.source_path}[{clip.start:.1f}s] - too blurry")
                continue

            if f.brightness_score < 0.2 or f.brightness_score > 0.9:
                logger.debug(f"Filtered: {clip.source_path}[{clip.start:.1f}s] - bad brightness")
                continue

            if f.camera_stability_score < 0.3:
                logger.debug(f"Filtered: {clip.source_path}[{clip.start:.1f}s] - too shaky")
                continue

            if f.technical_quality_score < 0.4:
                logger.debug(f"Filtered: {clip.source_path}[{clip.start:.1f}s] - low technical quality")
                continue

            filtered.append(clip)

        logger.info(
            f"Intelligent Beauty filter: {len(filtered)}/{len(candidates)} clips passed "
            f"(filtered out {len(candidates) - len(filtered)})"
        )

        return filtered

    def compute_beauty_score(self, clip) -> float:
        """
        Вычислить beauty score для клипа

        Beauty score включает:
        - Technical beauty (резкость, яркость, контраст, стабильность)
        - Composition (визуальная сложность, насыщенность)
        - Smooth motion (плавность движения)
        - Uniqueness (разнообразие)

        Args:
            clip: CandidateClip object

        Returns:
            Beauty score (0.0 - 1.0)
        """
        f = clip.features

        # 1. Technical Beauty Score
        technical_beauty = self._compute_technical_beauty(f)

        # 2. Composition Score
        composition = self._compute_composition_score(f)

        # 3. Smooth Motion Score
        smooth_motion = self._compute_smooth_motion_score(f)

        # 4. Weighted sum
        beauty_score = (
            technical_beauty * 0.35 +
            composition * 0.30 +
            smooth_motion * 0.20 +
            f.uniqueness_score * 0.15
        )

        return min(1.0, beauty_score)

    def _compute_technical_beauty(self, features) -> float:
        """
        Алгоритм 1: Technical Beauty Score

        Оценивает техническую пригодность:
        - резкость
        - яркость (не слишком темная/яркая)
        - контраст
        - стабильность
        """
        # Sharpness
        sharpness = features.sharpness_score

        # Brightness quality (peak at 0.5)
        brightness_quality = 1.0 - abs(features.brightness_score - 0.5) * 2.0
        brightness_quality = max(0.0, brightness_quality)

        # Contrast
        contrast = features.contrast_score

        # Stability
        stability = features.camera_stability_score

        # Weighted sum
        technical_beauty = (
            sharpness * 1.4 +
            brightness_quality * 1.0 +
            contrast * 0.8 +
            stability * 1.3
        ) / 4.5

        return min(1.0, technical_beauty)

    def _compute_composition_score(self, features) -> float:
        """
        Алгоритм 2: Composition Score

        Оценивает визуальную привлекательность:
        - visual complexity (детали)
        - color saturation (насыщенность цвета)
        - color diversity (разнообразие цветов)
        - contrast (контраст)

        Без тяжелого AI, используем доступные признаки
        """
        # Visual complexity (детали)
        complexity = features.visual_complexity_score

        # Color saturation
        color_saturation = features.color_saturation_score

        # Color diversity
        color_diversity = features.color_diversity_score

        # Contrast
        contrast = features.contrast_score

        # Weighted sum
        composition = (
            complexity * 1.0 +
            color_saturation * 0.8 +
            color_diversity * 0.8 +
            contrast * 1.2
        ) / 3.8

        return min(1.0, composition)

    def _compute_smooth_motion_score(self, features) -> float:
        """
        Алгоритм 3: Smooth Motion Score

        Оценивает красоту движения:
        - стабильность камеры
        - низкий motion (для плавных кадров)
        - спокойствие
        """
        stability = features.camera_stability_score
        low_motion = 1.0 - features.motion_score  # Prefer lower motion
        calm = features.calm_score

        smooth_motion = (
            stability * 1.3 +
            low_motion * 0.8 +
            calm * 1.2
        ) / 3.3

        return min(1.0, smooth_motion)

    def select_opening_shot(self, candidates: List) -> Optional:
        """
        Алгоритм 5: Opening Shot Selection

        Выбрать лучший кадр для открытия

        Критерии:
        - Высокое техническое качество
        - Хорошая композиция
        - Не слишком хаотичный
        - Не темный
        - Понятный и красивый
        """
        if not candidates:
            return None

        opening_scores = []

        for clip in candidates:
            f = clip.features

            # Opening score
            opening_score = (
                self._compute_technical_beauty(f) * 0.8 +
                self._compute_composition_score(f) * 1.2 +
                f.motion_score * 0.4 +  # Some motion is good for opening
                f.uniqueness_score * 0.6
            ) / 3.0

            # Penalize very dark clips
            if f.brightness_score < 0.25:
                opening_score *= 0.5

            # Penalize very chaotic clips
            if f.visual_complexity_score > 0.8:
                opening_score *= 0.8

            opening_scores.append((clip, opening_score))

        # Get best
        opening_scores.sort(key=lambda x: x[1], reverse=True)
        best_opening = opening_scores[0][0]

        logger.info(
            f"Selected opening shot: {best_opening.source_path} "
            f"[{best_opening.start:.1f}s] score={opening_scores[0][1]:.3f}"
        )

        return best_opening

    def select_closing_shot(self, candidates: List) -> Optional:
        """
        Алгоритм 5: Closing Shot Selection

        Выбрать лучший кадр для финала

        Критерии:
        - Спокойный
        - Красивый
        - Стабильный
        - Хорошо подходит для fade out
        - Не обрывается на резком движении
        """
        if not candidates:
            return None

        closing_scores = []

        for clip in candidates:
            f = clip.features

            # Closing score
            closing_score = (
                self._compute_technical_beauty(f) * 1.0 +
                self._compute_composition_score(f) * 1.0 +
                f.calm_score * 1.4 +
                f.camera_stability_score * 1.2
            ) / 4.6

            # Prefer low motion for closing
            if f.motion_score < 0.3:
                closing_score *= 1.2

            closing_scores.append((clip, closing_score))

        # Get best
        closing_scores.sort(key=lambda x: x[1], reverse=True)
        best_closing = closing_scores[0][0]

        logger.info(
            f"Selected closing shot: {best_closing.source_path} "
            f"[{best_closing.start:.1f}s] score={closing_scores[0][1]:.3f}"
        )

        return best_closing

    def get_diversity_threshold(self) -> float:
        """Очень высокое разнообразие"""
        return 0.45

    def get_randomness_level(self) -> float:
        """Controlled randomness"""
        return 0.25
