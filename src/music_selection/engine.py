"""
Music Selection Engine

Selects the optimal audio segment for a preset style using sliding-window scoring.
Runs BEFORE video timeline is built, so the video is assembled against
the chosen audio window — not the other way around.

Pipeline:
    1. Analyse full audio track (reuses AudioAnalyzer)
    2. Create sliding-window candidates across the track
    3. Score each candidate against the preset's MusicSelectionProfile
    4. Return the best-scoring MusicSelection

Key guarantee:
    The returned MusicSelection always covers the full target_duration.
    If the track is shorter, loop_required=True is set and FFmpegRenderer
    will loop the audio automatically.
"""

import logging
import math
import numpy as np
from dataclasses import dataclass
from typing import Optional

from src.audio.audio_analyzer import AudioAnalyzer, AudioFeatures
from .profiles import MusicSelectionProfile, get_profile

logger = logging.getLogger(__name__)


@dataclass
class MusicSelection:
    """
    Optimal audio window for a given preset and video duration.

    Compatible with the existing AudioSelection duck-type contract
    (start_time, end_time, duration, reason) so callers need no changes.
    """
    start_time: float
    end_time: float
    duration: float
    score: float
    reason: str
    loop_required: bool = False   # True when audio < target_duration
    fade_in: float = 2.0
    fade_out: float = 2.0


class MusicSelectionEngine:
    """
    Selects the best audio window for a preset using sliding-window scoring.

    Scoring formula (weights from MusicSelectionProfile):
        score = energy_fit       * w_energy_fit
              + onset_fit        * w_onset_density
              + growth_score     * w_energy_growth
              + start_quality    * w_start_quality
              + end_quality      * w_end_quality
              + variance_score   * w_variance_penalty
    """

    # Seconds between candidate window start positions
    WINDOW_STEP_SEC = 1.5

    @staticmethod
    def select(
        audio_path: str,
        target_duration: float,
        preset_id: str,
        fade_in: float = 2.0,
        fade_out: float = 2.0,
    ) -> MusicSelection:
        """
        Select the best audio segment for the given preset.

        Args:
            audio_path:      Path to the music file
            target_duration: Desired segment length == video duration
            preset_id:       Preset identifier (determines selection profile)
            fade_in:         Fade-in seconds to embed in the result
            fade_out:        Fade-out seconds to embed in the result

        Returns:
            MusicSelection — always valid; loop_required=True when looping needed
        """
        logger.info(
            f"[MusicEngine] preset={preset_id}, target={target_duration:.1f}s, "
            f"audio={audio_path!r}"
        )

        profile = get_profile(preset_id)
        _fallback = lambda reason: MusicSelection(
            start_time=0.0, end_time=target_duration,
            duration=target_duration, score=0.0,
            reason=reason, loop_required=False,
            fade_in=fade_in, fade_out=fade_out,
        )

        try:
            features = AudioAnalyzer.analyze(audio_path)
        except Exception as exc:
            logger.warning(f"[MusicEngine] Analysis failed: {exc} — from_start fallback")
            return _fallback("analysis_error_from_start")

        if features is None:
            logger.warning("[MusicEngine] No features — from_start fallback")
            return _fallback("no_features_from_start")

        audio_dur = features.duration

        # ── Entire track shorter than target → loop is required ──────────────
        if audio_dur < target_duration * 0.98:
            logger.info(
                f"[MusicEngine] Audio {audio_dur:.1f}s < target {target_duration:.1f}s "
                f"— loop required"
            )
            return MusicSelection(
                start_time=0.0, end_time=audio_dur,
                duration=audio_dur, score=1.0,
                reason="audio_shorter_loop_required",
                loop_required=True,
                fade_in=fade_in, fade_out=fade_out,
            )

        # ── Sliding-window search ─────────────────────────────────────────────
        best = MusicSelectionEngine._best_window(features, target_duration, profile)

        end_time = min(best["start"] + target_duration, audio_dur)
        actual_dur = end_time - best["start"]

        logger.info(
            f"[MusicEngine] Selected {best['start']:.1f}s–{end_time:.1f}s "
            f"score={best['score']:.3f} ({best['reason']})"
        )

        return MusicSelection(
            start_time=best["start"],
            end_time=end_time,
            duration=actual_dur,
            score=best["score"],
            reason=best["reason"],
            loop_required=False,
            fade_in=fade_in,
            fade_out=fade_out,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _best_window(
        features: AudioFeatures,
        target_duration: float,
        profile: MusicSelectionProfile,
    ) -> dict:
        """
        Slide a window of `target_duration` seconds across the track and
        return the position with the highest profile score.
        """
        rms       = features.rms_energy        # shape (N,)
        ts        = features.energy_timestamps  # shape (N,)
        onset     = features.onset_strength     # shape (N,) or None

        if len(ts) < 2:
            return {"start": 0.0, "score": 0.0, "reason": "too_short"}

        dt             = float(ts[1] - ts[0])
        window_samp    = max(2, int(target_duration / dt))
        step_samp      = max(1, int(MusicSelectionEngine.WINDOW_STEP_SEC / dt))
        n              = len(rms)
        global_max_rms = float(np.max(rms)) or 1.0

        best_score  = -1.0
        best_start  = 0.0
        best_reason = "first_window"

        for i in range(0, max(1, n - window_samp), step_samp):
            w_rms   = rms[i: i + window_samp]
            w_onset = onset[i: i + window_samp] if onset is not None else None

            score, reason = MusicSelectionEngine._score_window(
                w_rms, w_onset, global_max_rms, profile, dt
            )

            if score > best_score:
                best_score  = score
                best_start  = float(ts[i])
                best_reason = reason

        return {"start": best_start, "score": best_score, "reason": best_reason}

    @staticmethod
    def _score_window(
        w_rms: np.ndarray,
        w_onset: Optional[np.ndarray],
        global_max: float,
        profile: MusicSelectionProfile,
        dt: float,
    ) -> tuple:
        if len(w_rms) == 0:
            return 0.0, "empty"

        norm     = w_rms / global_max              # [0, 1]
        avg_nrg  = float(np.mean(norm))
        n        = len(norm)

        # 1. Energy fit ────────────────────────────────────────────────────────
        mid  = (profile.target_energy_min + profile.target_energy_max) / 2.0
        half = max(1e-6, (profile.target_energy_max - profile.target_energy_min) / 2.0)
        energy_fit = float(np.clip(1.0 - abs(avg_nrg - mid) / half, 0.0, 1.0))

        # 2. Onset density fit ─────────────────────────────────────────────────
        if w_onset is not None and len(w_onset) > 0:
            thresh        = float(np.percentile(w_onset, 75))
            dens          = float(np.sum(w_onset > thresh)) / len(w_onset)
            clamped_dens  = float(np.clip(dens, profile.min_onset_density,
                                          profile.max_onset_density))
            onset_fit     = 1.0 - abs(dens - clamped_dens) * 2.0
        else:
            dens      = 0.0
            onset_fit = 0.5

        # 3. Energy growth ─────────────────────────────────────────────────────
        if n >= 4:
            third       = max(1, n // 3)
            first_avg   = float(np.mean(norm[:third]))
            last_avg    = float(np.mean(norm[-third:]))
            growth      = last_avg - first_avg   # [-1, +1]
            growth_score = float(np.clip((growth + 1.0) / 2.0, 0.0, 1.0))
        else:
            growth_score = 0.5

        # 4. Start quality ─────────────────────────────────────────────────────
        half_sec_samp = max(1, int(0.5 / dt))
        start_quality = float(np.mean(norm[:half_sec_samp]))

        # 5. End quality ───────────────────────────────────────────────────────
        end_quality = float(np.mean(norm[-half_sec_samp:]))
        if not profile.require_final_accent:
            # Prefer calmer endings (natural fade-out point)
            end_quality = 1.0 - end_quality * 0.4

        # 6. Variance score (low variance = stable = good for most styles) ─────
        variance       = float(np.var(norm))
        variance_score = float(np.clip(1.0 - variance * 3.0, 0.0, 1.0))

        # Composite ────────────────────────────────────────────────────────────
        score = (
            energy_fit    * profile.weight_energy_fit
            + onset_fit   * profile.weight_onset_density
            + growth_score* profile.weight_energy_growth
            + start_quality * profile.weight_start_quality
            + end_quality * profile.weight_end_quality
            + variance_score * profile.weight_variance_penalty
        )

        reason = (
            f"energy={avg_nrg:.2f} "
            f"onset={dens:.2f} "
            f"growth={growth_score:.2f}"
        )
        return float(np.clip(score, 0.0, 1.0)), reason
