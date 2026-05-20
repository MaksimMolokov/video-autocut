"""
Audio phrase / beat boundary detection for smart audio start/end selection.

Modes supported (AudioIntroRule.mode):
  'from_start'   — return 0.0 (no analysis)
  'soft_fade'    — return avoid_first_sec (simple skip)
  'phrase_start' — find nearest low-energy boundary after avoid_first_sec
  'beat_start'   — find nearest beat after avoid_first_sec
  'drop_start'   — find highest-onset point after avoid_first_sec

AudioOutroRule.mode:
  'soft_fade_end'    — end at start + target_duration
  'phrase_fade_end'  — end at nearest phrase boundary before start + target_duration
  'beat_cut_end'     — end at nearest beat before start + target_duration
  'punch_end'        — end at highest-onset beat near start + target_duration
"""

from __future__ import annotations
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class AudioBoundaryDetector:
    """
    Detects phrase/beat boundaries in an audio file using librosa.
    Falls back gracefully when librosa is unavailable.
    """

    def __init__(self, audio_path: str):
        self.audio_path = audio_path
        self._beats: Optional[List[float]] = None       # beat timestamps (s)
        self._onsets: Optional[List[float]] = None      # onset timestamps (s)
        self._phrase_boundaries: Optional[List[float]] = None  # low-energy boundaries
        self._duration: Optional[float] = None
        self._loaded = False

    # ── Internal analysis ─────────────────────────────────────────────────────

    def _load(self):
        """Run librosa analysis once; silently skip if unavailable."""
        if self._loaded:
            return
        self._loaded = True
        try:
            import librosa  # type: ignore
            import numpy as np

            y, sr = librosa.load(self.audio_path, sr=22050, mono=True)
            self._duration = len(y) / sr

            # Beats
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            self._beats = librosa.frames_to_time(beat_frames, sr=sr).tolist()

            # Onsets
            onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units='time')
            self._onsets = onset_frames.tolist()

            # Phrase boundaries — segments of low RMS energy
            rms = librosa.feature.rms(y=y)[0]
            hop = 512
            rms_times = librosa.frames_to_time(
                range(len(rms)), sr=sr, hop_length=hop
            )
            threshold = float(np.percentile(rms, 20))  # bottom 20%
            boundaries = []
            in_low = False
            for t, r in zip(rms_times, rms):
                if r < threshold and not in_low:
                    boundaries.append(float(t))
                    in_low = True
                elif r >= threshold:
                    in_low = False
            self._phrase_boundaries = boundaries

            logger.info(
                f"[AudioBoundary] Loaded: dur={self._duration:.1f}s "
                f"beats={len(self._beats)} onsets={len(self._onsets)} "
                f"phrase_boundaries={len(self._phrase_boundaries)}"
            )
        except Exception as e:
            logger.warning(f"[AudioBoundary] librosa unavailable or failed: {e}")
            self._beats = []
            self._onsets = []
            self._phrase_boundaries = []
            try:
                import subprocess, json
                r = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries',
                     'format=duration', '-of', 'json', self.audio_path],
                    capture_output=True, text=True, timeout=10
                )
                data = json.loads(r.stdout)
                self._duration = float(data['format']['duration'])
            except Exception:
                self._duration = None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_duration(self) -> Optional[float]:
        self._load()
        return self._duration

    def _nearest_after(self, timestamps: List[float], t_min: float) -> Optional[float]:
        for t in timestamps:
            if t >= t_min:
                return t
        return None

    def _nearest_before(self, timestamps: List[float], t_max: float) -> Optional[float]:
        result = None
        for t in timestamps:
            if t <= t_max:
                result = t
        return result

    def _highest_onset_after(self, t_min: float, window: float = 30.0) -> Optional[float]:
        """Return onset with highest energy in [t_min, t_min+window]."""
        self._load()
        if not self._onsets:
            return None
        candidates = [t for t in self._onsets if t_min <= t <= t_min + window]
        return candidates[0] if candidates else None  # onsets already ordered by time

    # ── Public API ────────────────────────────────────────────────────────────

    def find_best_start(self, rule) -> float:
        """
        Return the best audio start time (seconds) according to audio intro rule.
        """
        self._load()
        avoid = rule.avoid_first_sec
        mode = rule.mode

        if mode == 'from_start':
            return 0.0

        if mode == 'soft_fade':
            return avoid

        if mode == 'phrase_start':
            t = self._nearest_after(self._phrase_boundaries or [], avoid)
            if t is not None:
                logger.info(f"[AudioBoundary] phrase_start → {t:.2f}s")
                return t
            # Fallback: nearest beat
            t = self._nearest_after(self._beats or [], avoid)
            if t is not None:
                return t
            return avoid

        if mode == 'beat_start':
            t = self._nearest_after(self._beats or [], avoid)
            if t is not None:
                logger.info(f"[AudioBoundary] beat_start → {t:.2f}s")
                return t
            return avoid

        if mode == 'drop_start':
            # Drop = first strong onset after avoid_sec
            onsets_after = [t for t in (self._onsets or []) if t >= avoid]
            if onsets_after:
                t = onsets_after[0]
                logger.info(f"[AudioBoundary] drop_start → {t:.2f}s")
                return t
            t = self._nearest_after(self._beats or [], avoid)
            return t if t is not None else avoid

        # Unknown mode — safe fallback
        return avoid

    def find_best_end(self, start: float, target_duration: float, rule) -> float:
        """
        Return the best audio end time (seconds) according to audio outro rule.
        """
        self._load()
        mode = rule.outro_mode if hasattr(rule, 'outro_mode') else rule.mode
        ideal_end = start + target_duration

        if mode in ('soft_fade_end', 'soft_fade'):
            return ideal_end

        if mode == 'phrase_fade_end':
            t = self._nearest_before(self._phrase_boundaries or [], ideal_end)
            if t and ideal_end - t < target_duration * 0.15:
                logger.info(f"[AudioBoundary] phrase_fade_end → {t:.2f}s")
                return t
            # Fallback: beat
            t = self._nearest_before(self._beats or [], ideal_end)
            if t:
                return t
            return ideal_end

        if mode == 'beat_cut_end':
            t = self._nearest_before(self._beats or [], ideal_end)
            if t:
                logger.info(f"[AudioBoundary] beat_cut_end → {t:.2f}s")
                return t
            return ideal_end

        if mode == 'punch_end':
            # Punch = last strong onset within 2s before ideal_end
            window_start = ideal_end - 2.0
            candidates = [t for t in (self._beats or [])
                          if window_start <= t <= ideal_end]
            if candidates:
                t = candidates[-1]
                logger.info(f"[AudioBoundary] punch_end → {t:.2f}s")
                return t
            return ideal_end

        return ideal_end
