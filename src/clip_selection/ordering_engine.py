"""
Ordering Engine - упорядочивание выбранных клипов под структуру ролика
"""

import random
import logging
from typing import List

logger = logging.getLogger(__name__)


class OrderingEngine:
    """
    Упорядочивание выбранных клипов согласно типу структуры ролика
    """

    @staticmethod
    def order_clips(
        selected_clips: List,  # List[CandidateClip]
        ordering_type: str
    ) -> List:
        """
        Упорядочить клипы согласно типу структуры

        Args:
            selected_clips: List of selected CandidateClip objects
            ordering_type: Type of ordering

        Returns:
            Ordered list of clips
        """
        if not selected_clips:
            return []

        logger.info(f"Ordering {len(selected_clips)} clips using '{ordering_type}'")

        if ordering_type == 'chronological':
            return OrderingEngine._chronological(selected_clips)
        elif ordering_type == 'best_first':
            return OrderingEngine._best_first(selected_clips)
        elif ordering_type == 'energy_growth':
            return OrderingEngine._energy_growth(selected_clips)
        elif ordering_type == 'smooth_progression':
            return OrderingEngine._smooth_progression(selected_clips)
        elif ordering_type == 'story_arc':
            return OrderingEngine._story_arc(selected_clips)
        elif ordering_type == 'hook_then_fast_variation':
            return OrderingEngine._hook_then_fast(selected_clips)
        elif ordering_type == 'rhythmic_alternation':
            return OrderingEngine._rhythmic_alternation(selected_clips)
        else:
            logger.warning(f"Unknown ordering type '{ordering_type}', using chronological")
            return OrderingEngine._chronological(selected_clips)

    @staticmethod
    def _chronological(clips: List) -> List:
        """Порядок как в исходном видео"""
        return sorted(clips, key=lambda c: (c.source_path, c.start))

    @staticmethod
    def _best_first(clips: List) -> List:
        """Сначала лучшие кадры"""
        return sorted(clips, key=lambda c: c.final_score, reverse=True)

    @staticmethod
    def _energy_growth(clips: List) -> List:
        """
        Нарастание динамики (от спокойных к энергичным)

        Сортируем по action_score
        """
        return sorted(clips, key=lambda c: c.features.action_score)

    @staticmethod
    def _smooth_progression(clips: List) -> List:
        """
        Плавное развитие - минимизировать резкие скачки между соседними клипами

        Алгоритм: greedy nearest neighbor
        """
        if len(clips) <= 1:
            return clips

        # Начинаем с клипа со средней динамикой
        clips_sorted_by_action = sorted(clips, key=lambda c: abs(c.features.action_score - 0.5))
        ordered = [clips_sorted_by_action[0]]
        remaining = [c for c in clips if c != clips_sorted_by_action[0]]

        while remaining:
            last = ordered[-1]

            # Найти ближайший клип по признакам
            nearest = min(remaining, key=lambda c: OrderingEngine._distance(
                last.features, c.features
            ))

            ordered.append(nearest)
            remaining.remove(nearest)

        logger.debug(f"Smooth progression: {len(ordered)} clips ordered")

        return ordered

    @staticmethod
    def _story_arc(clips: List) -> List:
        """
        Структура истории: начало (establishing) → развитие → кульминация → финал

        Логика:
        - Первый клип: средняя динамика, хорошее качество (establishing shot)
        - Середина: разнообразие и динамика
        - Финал: сильный эмоциональный или красивый кадр
        """
        if len(clips) <= 3:
            # Слишком мало клипов, просто сортируем по качеству
            return sorted(clips, key=lambda c: c.final_score, reverse=True)

        # Отсортировать по качеству
        sorted_by_quality = sorted(clips, key=lambda c: c.final_score, reverse=True)

        # Выбрать opening (хорошее качество, средняя динамика)
        opening_candidates = [
            c for c in sorted_by_quality
            if 0.3 < c.features.action_score < 0.7 and c.final_score > 0.5
        ]
        opening = opening_candidates[0] if opening_candidates else sorted_by_quality[0]

        # Выбрать finale (лучший клип или самый спокойный)
        finale_candidates = sorted(
            [c for c in clips if c != opening],
            key=lambda c: c.features.calm_score,
            reverse=True
        )
        finale = finale_candidates[0] if finale_candidates else clips[-1]

        # Остальные в середину
        middle = [c for c in clips if c != opening and c != finale]

        # Сортировать middle по динамике (нарастание к кульминации)
        middle_sorted = sorted(middle, key=lambda c: c.features.action_score)

        result = [opening] + middle_sorted + [finale]

        logger.debug(
            f"Story arc: opening={opening.start:.1f}s, "
            f"middle={len(middle_sorted)}, finale={finale.start:.1f}s"
        )

        return result

    @staticmethod
    def _hook_then_fast(clips: List) -> List:
        """
        Сильный hook в начале, затем быстрая смена разнообразных клипов

        Для Social Media Punchy
        """
        if len(clips) <= 1:
            return clips

        # Найти самый яркий/контрастный/динамичный клип для hook
        hook = max(clips, key=lambda c: (
            c.features.action_score +
            c.features.contrast_score +
            c.features.visual_complexity_score
        ) / 3.0)

        # Остальные - shuffle с учетом качества
        remaining = [c for c in clips if c != hook]

        # Shuffle, но лучшие клипы имеют больше шансов попасть в начало
        weighted_remaining = sorted(
            remaining,
            key=lambda c: c.final_score + random.uniform(-0.3, 0.3),
            reverse=True
        )

        result = [hook] + weighted_remaining

        logger.debug(f"Hook then fast: hook={hook.start:.1f}s with action={hook.features.action_score:.2f}")

        return result

    @staticmethod
    def _rhythmic_alternation(clips: List) -> List:
        """
        Ритмичное чередование спокойных и динамичных кадров

        Для Urban Rhythm
        """
        if len(clips) <= 2:
            return clips

        # Разделить на спокойные и динамичные
        calm_clips = sorted(
            [c for c in clips if c.features.action_score < 0.5],
            key=lambda c: c.final_score,
            reverse=True
        )

        dynamic_clips = sorted(
            [c for c in clips if c.features.action_score >= 0.5],
            key=lambda c: c.final_score,
            reverse=True
        )

        # Чередовать
        result = []
        max_len = max(len(calm_clips), len(dynamic_clips))

        for i in range(max_len):
            if i < len(dynamic_clips):
                result.append(dynamic_clips[i])
            if i < len(calm_clips):
                result.append(calm_clips[i])

        logger.debug(
            f"Rhythmic alternation: {len(calm_clips)} calm + {len(dynamic_clips)} dynamic "
            f"= {len(result)} total"
        )

        return result

    @staticmethod
    def _distance(f1, f2) -> float:
        """
        Вычислить расстояние между двумя наборами признаков

        Простое евклидово расстояние
        """
        diff_motion = abs(f1.motion_score - f2.motion_score)
        diff_brightness = abs(f1.brightness_score - f2.brightness_score)
        diff_action = abs(f1.action_score - f2.action_score)

        distance = (diff_motion**2 + diff_brightness**2 + diff_action**2) ** 0.5
        return distance / (3 ** 0.5)  # Normalize


if __name__ == "__main__":
    print("OrderingEngine - use in integration with CandidateClip")
