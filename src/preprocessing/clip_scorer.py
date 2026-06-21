"""Aggregate quality_score and style scores from technical metrics."""

from dataclasses import dataclass
from typing import Optional

from .quality_analyzer import TechMetrics


@dataclass
class ContentMetrics:
    has_face: bool = False
    face_area_ratio: float = 0.0
    has_person: bool = False
    has_subject: bool = False
    scene_type: str = 'wide'
    scene_tag: str = ''
    crop_9_16: float = 0.5
    crop_1_1: float = 0.5


@dataclass
class ScoreResult:
    quality_score: float
    cinematic_score: float
    action_score: float
    social_score: float
    premium_score: float
    travel_score: float


# Travel tags that boost travel_score (CLIP semantic tags from Level 4)
_TRAVEL_TAGS = frozenset({'nature', 'ocean', 'mountains'})
# Interior/city tags that reduce travel_score
_NON_TRAVEL_TAGS = frozenset({'interior', 'architecture', 'food'})


class ClipScorer:

    def score(
        self,
        m: TechMetrics,
        c: Optional[ContentMetrics] = None,
        scene_tag: Optional[str] = None,
    ) -> ScoreResult:
        return ScoreResult(
            quality_score=self._quality(m, c),
            cinematic_score=self._cinematic(m),
            action_score=self._action(m),
            social_score=self._social(m, c),
            premium_score=self._premium(m),
            travel_score=self._travel(m, c, scene_tag),
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _quality(m: TechMetrics, c: Optional[ContentMetrics]) -> float:
        brightness_ok = 1.0 if 0.20 < m.brightness < 0.88 else 0.3
        motion_ok     = 1.0 if 0.04 < m.motion < 0.72 else 0.4
        overexpose_ok = 0.3 if m.overexpose else 1.0
        has_subject   = float(c.has_subject) if c else 0.5
        colorfulness  = float(getattr(m, 'colorfulness', 0.0))

        base = (
            0.22 * m.sharpness    +
            0.18 * brightness_ok  +
            0.18 * m.stability    +
            0.13 * overexpose_ok  +
            0.09 * motion_ok      +
            0.10 * has_subject    +
            0.10 * colorfulness
        )
        return round(min(1.0, max(0.0, base)), 3)

    @staticmethod
    def _cinematic(m: TechMetrics) -> float:
        smooth_motion = 1.0 - min(1.0, m.motion * 1.5)
        composition   = float(getattr(m, 'composition_score', 0.0))
        return round(min(1.0, max(0.0,
            0.30 * m.stability    +
            0.25 * m.sharpness    +
            0.18 * smooth_motion  +
            0.12 * m.brightness   +
            0.15 * composition
        )), 3)

    @staticmethod
    def _action(m: TechMetrics) -> float:
        return round(min(1.0, max(0.0,
            0.40 * m.motion +
            0.30 * m.action +
            0.20 * m.sharpness +
            0.10 * (1.0 - m.stability)
        )), 3)

    @staticmethod
    def _social(m: TechMetrics, c: Optional[ContentMetrics]) -> float:
        has_face = float(c.has_face) if c else 0.0
        return round(min(1.0, max(0.0,
            0.25 * m.motion +
            0.25 * has_face +
            0.25 * m.sharpness +
            0.25 * m.brightness
        )), 3)

    @staticmethod
    def _premium(m: TechMetrics) -> float:
        return round(min(1.0, max(0.0,
            0.40 * m.stability +
            0.35 * m.sharpness +
            0.25 * m.brightness
        )), 3)

    @staticmethod
    def _travel(
        m: TechMetrics,
        c: Optional[ContentMetrics],
        scene_tag: Optional[str] = None,
    ) -> float:
        has_face = float(c.has_face) if c else 0.0
        base = (
            0.30 * m.sharpness +
            0.25 * m.brightness +
            0.25 * m.stability +
            0.20 * has_face
        )
        # CLIP semantic boost: nature/ocean/mountains → +0.12; interior/food → –0.10
        if scene_tag in _TRAVEL_TAGS:
            base += 0.12
        elif scene_tag in _NON_TRAVEL_TAGS:
            base -= 0.10
        return round(min(1.0, max(0.0, base)), 3)
