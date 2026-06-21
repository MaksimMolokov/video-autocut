"""
BpmDetector — detect tempo (BPM) of an audio track (TASK-040).

Uses librosa beat tracking. Works across genres.
Returns bpm (float) and confidence score.
"""
from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class BpmDetector:
    """Detect BPM of an audio file."""

    def detect(self, audio_path: str) -> Dict:
        """
        Return {bpm: float, confidence: float, method: str}
        """
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=22050, mono=True)
            tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
            bpm = float(tempo)

            # Confidence based on beat consistency
            if len(beats) > 4:
                beat_times = librosa.frames_to_time(beats, sr=sr)
                intervals = beat_times[1:] - beat_times[:-1]
                consistency = 1.0 - float(intervals.std() / (intervals.mean() + 1e-9))
                confidence = max(0.0, min(1.0, consistency))
            else:
                confidence = 0.3

            logger.debug("[BpmDetector] %s → %.1f BPM (confidence=%.2f)", audio_path, bpm, confidence)
            return {"bpm": bpm, "confidence": confidence, "method": "librosa"}

        except ImportError:
            logger.error("[BpmDetector] librosa not installed")
            return {"bpm": 120.0, "confidence": 0.0, "method": "fallback"}
        except Exception as exc:
            logger.error("[BpmDetector] failed: %s", exc)
            return {"bpm": 120.0, "confidence": 0.0, "method": "error"}
