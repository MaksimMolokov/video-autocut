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
import random
from dataclasses import dataclass, field
from typing import List, Optional, Set

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
        variant_constraints=None,   # VariantConstraints | None
        seed: int = 42,
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
        from .variant_constraints import scene_id as _scene_id, apply_variant_scoring
        from src.segment_selector import SelectedSegment

        profile = get_profile(preset_id)
        logger.info(
            f"[Timeline] Building: preset={preset_id} "
            f"narrative={profile.narrative} "
            f"target={target_duration:.1f}s "
            f"candidates={len(candidates)} "
            f"seed={seed}"
        )

        # Extract constraint values (None-safe)
        _vc = variant_constraints
        _excl_intro_ids = getattr(_vc, 'excluded_opening_ids', set()) if _vc else set()
        _excl_outro_ids = getattr(_vc, 'excluded_ending_ids',  set()) if _vc else set()
        _dur_policy     = getattr(_vc, 'segment_duration_policy', 'normal') if _vc else 'normal'
        _pressure       = getattr(_vc, 'diversity_pressure',    0.0) if _vc else 0.0
        _soft_excl      = getattr(_vc, 'soft_excluded_ids',     set()) if _vc else set()
        _hard_excl      = getattr(_vc, 'hard_excluded_ids',     set()) if _vc else set()

        # Re-order candidates with variant-specific scoring (without mutating originals)
        if _vc is not None:
            ordered_candidates = apply_variant_scoring(candidates, _vc, seed)
        else:
            ordered_candidates = list(candidates)

        # ── 1. Pick intro ─────────────────────────────────────────────────────
        intro_picks = IntroOutroScorer.pick_best_intro(
            ordered_candidates, profile, n=3,
            excluded_ids=_excl_intro_ids, seed=seed,
        )
        intro_clip = intro_picks[0] if intro_picks else None
        intro_sid  = _scene_id(intro_clip) if intro_clip else ''

        intro_log = "none"
        if intro_clip:
            intro_score = IntroOutroScorer.score_intro(intro_clip, profile)
            intro_log = (
                f"file={intro_clip.source_path.split('/')[-1]} "
                f"start={intro_clip.start:.1f}s "
                f"dur={intro_clip.duration:.1f}s "
                f"intro_score={intro_score:.2f} "
                f"scene_id={intro_sid} "
                f"transition={profile.video_intro.start_transition}"
            )
            logger.info(f"[Timeline] Intro: {intro_log}")

        # ── 2. Pick outro ─────────────────────────────────────────────────────
        # Exclude intro clip (by object identity and scene_id) from outro candidates
        intro_obj_id = id(intro_clip) if intro_clip else None
        outro_excl   = _excl_outro_ids | ({intro_sid} if intro_sid else set())
        outro_cands  = [c for c in ordered_candidates if id(c) != intro_obj_id]
        outro_picks  = IntroOutroScorer.pick_best_outro(
            outro_cands, profile, n=3,
            excluded_ids=outro_excl, seed=seed,
        )
        outro_clip = outro_picks[0] if outro_picks else None
        outro_sid  = _scene_id(outro_clip) if outro_clip else ''

        outro_log = "none"
        if outro_clip:
            outro_score = IntroOutroScorer.score_outro(outro_clip, profile)
            outro_log = (
                f"file={outro_clip.source_path.split('/')[-1]} "
                f"start={outro_clip.start:.1f}s "
                f"dur={outro_clip.duration:.1f}s "
                f"outro_score={outro_score:.2f} "
                f"scene_id={outro_sid} "
                f"transition={profile.video_outro.end_transition}"
            )
            logger.info(f"[Timeline] Outro: {outro_log}")

        # ── 3. Fill body ───────────────────────────────────────────────────────
        reserved_obj_ids = {id(intro_clip), id(outro_clip)} - {None}
        body_candidates  = [c for c in ordered_candidates if id(c) not in reserved_obj_ids]

        intro_dur = intro_clip.duration if intro_clip else 0.0
        outro_dur = outro_clip.duration if outro_clip else 0.0
        body_budget = target_duration - intro_dur - outro_dur

        body_clips = TimelineBuilder._fill_body(
            body_candidates, body_budget, profile.narrative,
            seed=seed,
            duration_policy=_dur_policy,
            soft_excluded_ids=_soft_excl,
            hard_excluded_ids=_hard_excl,
            diversity_pressure=_pressure,
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
            # Carry rich data for the draft-timeline UI
            seg._features = getattr(clip, 'features', None)
            seg._final_score = getattr(clip, 'final_score', 0.0)
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
    def _fill_body(
        candidates: list,
        budget: float,
        narrative: str,
        seed: int = 42,
        duration_policy: str = 'normal',
        soft_excluded_ids: Optional[Set[str]] = None,
        hard_excluded_ids: Optional[Set[str]] = None,
        diversity_pressure: float = 0.0,
    ) -> list:
        """
        Select body clips to fill `budget` seconds, ordered by narrative type.

        seed:               tie-breaking random seed (different per variant)
        duration_policy:    'normal' | 'shorter' | 'longer' | 'mixed'
        soft_excluded_ids:  scene_ids to penalise (already used by previous variants)
        hard_excluded_ids:  scene_ids to exclude entirely (variant D with rich material)
        diversity_pressure: 0.0–1.0; scales soft-exclusion penalty
        """
        from .variant_constraints import scene_id as _sid

        if budget <= 0 or not candidates:
            return []

        soft_excl = soft_excluded_ids or set()
        hard_excl = hard_excluded_ids or set()

        # Build adjusted-score list (candidates already ordered by apply_variant_scoring,
        # but _fill_body may receive a filtered sub-list, so re-apply soft/hard here)
        max_dur = max((getattr(c, 'duration', 3.0) for c in candidates), default=3.0)

        scored = []
        for c in candidates:
            sid = _sid(c)
            if sid in hard_excl:
                continue

            base = getattr(c, 'final_score', 0.5)

            # Soft penalty for clips already in previous variants.
            # Matches the stronger formula used in apply_variant_scoring so that
            # _fill_body's independent re-scoring doesn't undo those exclusions.
            if sid in soft_excl:
                penalty = min(0.72, diversity_pressure * 0.80)
                base = base * (1.0 - penalty)

            # Duration nudge
            dur = getattr(c, 'duration', 3.0)
            dur_bonus = 0.0
            if duration_policy == 'shorter':
                dur_bonus = 0.06 if dur < 3.0 else (-0.05 if dur > 5.5 else 0.0)
            elif duration_policy == 'longer':
                dur_bonus = 0.06 if dur > 4.5 else (-0.05 if dur < 2.0 else 0.0)

            adjusted = min(1.0, max(0.0, base + dur_bonus))
            scored.append((adjusted, c))

        # Sort by adjusted score descending; shuffle within ±0.08 bands by seed.
        # Band widened from ±0.025 so continuous float scores (rarely exact ties)
        # still get variant-specific ordering.
        scored.sort(key=lambda x: x[0], reverse=True)
        rng = random.Random(seed + 7919)   # different constant from intro picker
        reordered: list = []
        i = 0
        while i < len(scored):
            j = i + 1
            while j < len(scored) and abs(scored[j][0] - scored[i][0]) < 0.08:
                j += 1
            group = [c for _, c in scored[i:j]]
            rng.shuffle(group)
            reordered.extend(group)
            i = j

        selected = []
        total = 0.0
        for c in reordered:
            if total + c.duration > budget * 1.15:
                if total >= budget * 0.85:
                    break
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
