"""
EnergyAnalyzer — compute energy curve and energy sections (TASK-042).

Energy determines editing density:
  - HIGH energy → short, rapid cuts
  - LOW energy → long, slow clips
"""
from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)

_SECTION_WINDOW_S = 2.0  # seconds per energy section


class EnergyAnalyzer:
    """Analyze energy levels throughout an audio track."""

    def analyze(self, audio_path: str) -> Dict:
        """
        Return {
            curve: List[float],          — sampled RMS energy values (1 per second)
            curve_times: List[float],    — timestamps for each energy value
            sections: List[dict],        — [{start_s, end_s, level, avg_energy}]
            overall_energy: float,       — mean energy across whole track [0, 1]
            peak_times: List[float],     — timestamps of local energy peaks
            drop_times: List[float],     — timestamps of sudden energy drops
        }
        """
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=22050, mono=True)
            frame_length = 2048
            hop_length = 512

            rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
            times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

            # Normalize
            rms_norm = rms / (rms.max() + 1e-9)
            curve = rms_norm.tolist()
            curve_times = times.tolist()

            # Energy sections
            sections = _build_sections(curve, curve_times, window_s=_SECTION_WINDOW_S)

            # Peak / drop detection
            peak_times = _find_peaks(curve, curve_times, mode="peak")
            drop_times = _find_peaks(curve, curve_times, mode="drop")

            overall_energy = float(np.mean(rms_norm))

            return {
                "curve": curve,
                "curve_times": curve_times,
                "sections": sections,
                "overall_energy": overall_energy,
                "peak_times": peak_times,
                "drop_times": drop_times,
            }

        except ImportError:
            logger.error("[EnergyAnalyzer] librosa not installed")
            return _empty()
        except Exception as exc:
            logger.error("[EnergyAnalyzer] failed: %s", exc)
            return _empty()


def _build_sections(curve: List[float], times: List[float], window_s: float) -> List[dict]:
    if not times:
        return []
    duration = times[-1]
    sections = []
    t = 0.0
    while t < duration:
        end = min(t + window_s, duration)
        indices = [i for i, ts in enumerate(times) if t <= ts < end]
        if not indices:
            t += window_s
            continue
        avg = float(np.mean([curve[i] for i in indices]))
        level = "high" if avg > 0.65 else ("medium" if avg > 0.35 else "low")
        sections.append({"start_s": t, "end_s": end, "level": level, "avg_energy": avg})
        t += window_s
    return sections


def _find_peaks(curve: List[float], times: List[float], mode: str = "peak") -> List[float]:
    arr = np.array(curve)
    peaks = []
    threshold = 0.7 if mode == "peak" else 0.3
    for i in range(1, len(arr) - 1):
        if mode == "peak" and arr[i] > threshold and arr[i] > arr[i-1] and arr[i] > arr[i+1]:
            peaks.append(float(times[i]))
        elif mode == "drop" and arr[i] < threshold and arr[i] < arr[i-1] and arr[i] < arr[i+1]:
            peaks.append(float(times[i]))
    return peaks


def _empty() -> dict:
    return {"curve": [], "curve_times": [], "sections": [], "overall_energy": 0.5,
            "peak_times": [], "drop_times": []}
