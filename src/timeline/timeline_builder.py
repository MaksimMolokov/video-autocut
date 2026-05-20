"""
TimelineBuilder — assembles intro / body / outro from candidate clips.

Pipeline:
  1. Score all candidates for intro / outro suitability (per-style rules).
  2. Pick best intro candidate.
  3. Pick best outro candidate (different from intro; high-scoring for style end).
  4. Fill remaining duration with body candidates.
  5. Order body according to narrative type.
  6. Return TimelineResult with segments tagged by role, plus audio boundaries.

Roles stored in SelectedSegment.role:
  'intro', 'body', 'outro'
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TimelineResult:
    """Output of TimelineBuilder.build()."""
    segments: list              # List[SelectedSegment] ordered: intro, body..., outro
    audio_start: float = 0.0   # Best audio start time (seconds into audio file)
    audio_end:   float = 0.0   # Best audio end time
    intro_log:   str = ''
    outro_log:   str = ''
    audio_log:   str = ''
    narrative:   str = 'simple'


class TimelineBuilder:
    """
    Builds a timeline with structured intro / body / outro from candidate clips.

    Usage:
        result = TimelineBuilder.build(
            candidates=list_of_candidate_clips,
            target_duration=90.0,
            preset_id='travel_story',
            music_path='/path/to/music.mp3',   # optional
            music_start_time=0.0,              # coarse suggestion
        )
    """

    # Minimum duration allocated for intro and outro.
    MIN_INTRO_DUR = 1.0   # seconds
    MIN_OUTRO_DUR = 1.0

    @staticmethod
    def build(
        candidates: list,
        target_duration: float,
        preset_id: str,
        music_path: Optional[str] = None,
        music_start_time: float = 0.0,
    ) -> TimelineResult:
        """
        Build a timeline with per-style intro/outro structure.

        Args:
            candidates:        List of CandidateClip (with .features and .final_score)
            target_duration:   Desired total video duration in seconds
            preset_id:         Style identifier
            music_path:        Path to background audio (optional)
            music_start_time:  Coarse start hint from MusicSelectionEngine

        Returns:
            TimelineResult
        """
        from .intro_outro_rules import get_profile
        from .intro_outro_scorer import IntroOutroScorer
        from .audio_boundary import AudioBoundaryDetector
        from src.segment_selector import SelectedSegment

        profile = get_profile(preset_id)
        logger.info(
            f"[Timeline] Building: preset={preset_id} "
            f"narrative={profile.narrative} "
            f"target={target_duration:.1f}s "
            f"candidates={len(candidates)}"
        )

        # ── 1. Pick intro ─────────────────────────────────────────────────────
        intro_picks = IntroOutroScorer.pick_best_intro(candidates, profile, n=3)
        intro_clip = intro_picks[0] if intro_picks else None

        intro_log = "none"
        if intro_clip:
            intro_score = IntroOutroScorer.score_intro(intro_clip, profile)
            intro_log = (
                f"file={intro_clip.source_path.split('/')[-1]} "
                f"start={intro_clip.start:.1f}s "
                f"dur={intro_clip.duration:.1f}s "
                f"intro_score={intro_score:.2f} "
                f"transition={profile.video_intro.start_transition}"
            )
            logger.info(f"[Timeline] Intro: {intro_log}")

        # ── 2. Pick outro ─────────────────────────────────────────────────────
        # Exclude intro clip from outro candidates
        intro_id = id(intro_clip) if intro_clip else None
        outro_candidates = [c for c in candidates if id(c) != intro_id]
        outro_picks = IntroOutroScorer.pick_best_outro(outro_candidates, profile, n=3)
        outro_clip = outro_picks[0] if outro_picks else None

        outro_log = "none"
        if outro_clip:
            outro_score = IntroOutroScorer.score_outro(outro_clip, profile)
            outro_log = (
                f"file={outro_clip.source_path.split('/')[-1]} "
                f"start={outro_clip.start:.1f}s "
                f"dur={outro_clip.duration:.1f}s "
                f"outro_score={outro_score:.2f} "
                f"transition={profile.video_outro.end_transition}"
            )
            logger.info(f"[Timeline] Outro: {outro_log}")

        # ── 3. Fill body ───────────────────────────────────────────────────────
        reserved_ids = {id(intro_clip), id(outro_clip)} - {None}
        body_candidates = [c for c in candidates if id(c) not in reserved_ids]

        intro_dur = intro_clip.duration if intro_clip else 0.0
        outro_dur = outro_clip.duration if outro_clip else 0.0
        body_budget = target_duration - intro_dur - outro_dur

        body_clips = TimelineBuilder._fill_body(
            body_candidates, body_budget, profile.narrative
        )

        # ── 4. Convert CandidateClip → SelectedSegment with roles ─────────────
        def to_seg(clip, role: str) -> SelectedSegment:
            seg = SelectedSegment(
                source_path=clip.source_path,
                start=clip.start,
                end=clip.end,
                duration=clip.duration,
                is_must_use=clip.is_must_use,
            )
            seg.role = role
            seg.start_transition = ''
            seg.end_transition = ''
            return seg

        segments: list = []

        if intro_clip:
            s = to_seg(intro_clip, 'intro')
            s.start_transition = profile.video_intro.start_transition
            s.start_transition_duration = profile.video_intro.start_transition_duration
            segments.append(s)

        for c in body_clips:
            segments.append(to_seg(c, 'body'))

        if outro_clip:
            s = to_seg(outro_clip, 'outro')
            s.end_transition = profile.video_outro.end_transition
            s.end_transition_duration = profile.video_outro.end_transition_duration
            segments.append(s)

        # ── 5. Audio boundaries ────────────────────────────────────────────────
        audio_start = music_start_time
        audio_end = music_start_time + target_duration
        audio_log = "no music"

        if music_path:
            try:
                detector = AudioBoundaryDetector(music_path)
                audio_start = detector.find_best_start(profile.audio_intro)
                audio_end = detector.find_best_end(
                    audio_start, target_duration, profile.audio_outro
                )
                audio_dur = detector.get_duration() or 0
                audio_log = (
                    f"start={audio_start:.2f}s end={audio_end:.2f}s "
                    f"file_dur={audio_dur:.1f}s "
                    f"intro_mode={profile.audio_intro.mode} "
                    f"outro_mode={profile.audio_outro.mode} "
                    f"fade_in={profile.audio_intro.fade_in_sec}s "
                    f"fade_out={profile.audio_outro.fade_out_sec}s"
                )
                logger.info(f"[Timeline] Audio: {audio_log}")
            except Exception as e:
                logger.warning(f"[Timeline] Audio boundary detection failed: {e}")

        result = TimelineResult(
            segments=segments,
            audio_start=audio_start,
            audio_end=audio_end,
            intro_log=intro_log,
            outro_log=outro_log,
            audio_log=audio_log,
            narrative=profile.narrative,
        )

        total = sum(s.duration for s in segments)
        logger.info(
            f"[Timeline] Result: {len(segments)} segments "
            f"({len(body_clips)} body) total={total:.1f}s "
            f"target={target_duration:.1f}s"
        )
        return result

    @staticmethod
    def _fill_body(candidates: list, budget: float, narrative: str) -> list:
        """
        Select body clips to fill `budget` seconds, ordered by narrative type.
        """
        if budget <= 0 or not candidates:
            return []

        # Sort by final_score descending, pick until budget is filled
        sorted_cands = sorted(candidates, key=lambda c: c.final_score, reverse=True)
        selected = []
        total = 0.0
        for c in sorted_cands:
            if total + c.duration > budget * 1.15:   # 15% overshoot tolerance
                if total >= budget * 0.85:
                    break
                # Try to fit a shorter remaining slice (can't trim CandidateClip
                # without changing source, so just skip)
                continue
            selected.append(c)
            total += c.duration
            if total >= budget:
                break

        # Apply narrative ordering
        selected = TimelineBuilder._order_body(selected, narrative)
        return selected

    @staticmethod
    def _order_body(clips: list, narrative: str) -> list:
        """Order body clips according to the narrative pattern."""
        if not clips:
            return clips

        if narrative == 'simple':
            return clips   # already score-sorted

        if narrative == 'story_arc':
            # calm → medium → climax → resolution
            # Sort by action_score ascending (calm first), put highest at 2/3 point
            by_action = sorted(clips, key=lambda c: c.features.action_score)
            n = len(by_action)
            if n < 4:
                return by_action
            calm = by_action[:n // 3]
            climax = by_action[-(n // 4):]
            mid = by_action[n // 3: -(n // 4)]
            return calm + mid + climax

        if narrative == 'energy_peak':
            # Ramp up by motion/action
            return sorted(clips, key=lambda c: c.features.motion_score)

        if narrative == 'buildup_impact':
            # Rising action, climax at end
            return sorted(clips, key=lambda c: c.features.action_score)

        if narrative == 'beauty_arc':
            # Rising visual quality
            return sorted(clips, key=lambda c: c.features.sharpness_score *
                          c.features.brightness_score)

        return clips
