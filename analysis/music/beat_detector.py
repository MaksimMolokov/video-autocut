"""
BeatDetector — detect beat positions and accents (TASK-041).

Produces a beat map: timestamps + strength for each beat.
This is the primary input for Timeline Builder music sync.
"""
from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)


class BeatDetector:
    """Extract beat grid and accent positions from audio."""

    def detect(self, audio_path: str) -> Dict:
        """
        Return {
            times: List[float],          — beat timestamps in seconds
            strengths: List[float],      — normalized beat strength [0, 1]
            strong_beats: List[float],   — downbeat positions (every 4th beat)
            clarity: float,              — overall beat clarity [0, 1]
            onset_times: List[float],    — all onset events (transient attacks)
        }
        """
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=22050, mono=True)

            # Beat tracking
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

            # Beat strength
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            beat_strength = [float(onset_env[min(f, len(onset_env)-1)]) for f in beat_frames]
            max_strength = max(beat_strength) if beat_strength else 1.0
            beat_strength_norm = [s / max_strength for s in beat_strength]

            # Downbeats (every 4th beat)
            strong_beats = beat_times[::4]

            # Clarity: how consistent are beat intervals
            if len(beat_times) > 4:
                intervals = np.diff(beat_times)
                clarity = float(1.0 - intervals.std() / (intervals.mean() + 1e-9))
                clarity = max(0.0, min(1.0, clarity))
            else:
                clarity = 0.3

            # Onset times
            onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="time")
            onset_times = onset_frames.tolist()

            return {
                "times": beat_times,
                "strengths": beat_strength_norm,
                "strong_beats": list(strong_beats),
                "clarity": clarity,
                "onset_times": onset_times,
            }

        except ImportError:
            logger.error("[BeatDetector] librosa not installed")
            return {"times": [], "strengths": [], "strong_beats": [], "clarity": 0.0, "onset_times": []}
        except Exception as exc:
            logger.error("[BeatDetector] failed: %s", exc)
            return {"times": [], "strengths": [], "strong_beats": [], "clarity": 0.0, "onset_times": []}
