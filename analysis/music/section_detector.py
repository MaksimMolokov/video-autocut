"""
SectionDetector — detect musical structure sections (TASK-043).

Identifies: intro, verse, chorus/drop, buildup, bridge, breakdown, outro.
Uses energy + self-similarity matrix + librosa structure analysis.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class SectionDetector:
    """Detect and label structural sections in an audio track."""

    def detect(
        self,
        audio_path: str,
        energy: Optional[Dict] = None,
        beats: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return list of sections:
        [{start_s, end_s, type, label, energy_score, rhythm_score,
          montage_score, status}]
        """
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=22050, mono=True)
            duration = librosa.get_duration(y=y, sr=sr)

            # Chromagram for self-similarity
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            features = np.vstack([chroma, mfcc])

            # Recurrence matrix
            R = librosa.segment.recurrence_matrix(features, width=3, mode="affinity", sym=True)
            df = librosa.segment.timelag_filter(R)
            novelty = librosa.segment.onset_strength(df)
            times, _ = librosa.beat.beat_track(onset_envelope=novelty, sr=sr)
            boundary_frames = librosa.segment.agglomerative(features, k=_estimate_k(duration))
            boundary_times = librosa.frames_to_time(boundary_frames, sr=sr).tolist()

        except Exception as exc:
            logger.warning("[SectionDetector] librosa structure analysis failed: %s — using energy fallback", exc)
            return self._energy_fallback(audio_path, energy, beats)

        boundary_times = [0.0] + [t for t in boundary_times if 0 < t < duration] + [duration]
        boundary_times = sorted(set(boundary_times))

        energy_curve = energy.get("curve", []) if energy else []
        energy_times = energy.get("curve_times", []) if energy else []

        sections = []
        for i in range(len(boundary_times) - 1):
            start = boundary_times[i]
            end = boundary_times[i + 1]
            dur = end - start
            if dur < 1.0:
                continue

            avg_energy = _avg_energy_in_range(energy_curve, energy_times, start, end)
            section_type, label = _classify_section(i, len(boundary_times) - 2, avg_energy, dur)
            montage_score = _compute_montage_score(avg_energy, section_type)
            status = "best" if montage_score > 0.7 else ("recommended" if montage_score > 0.4 else "optional")

            sections.append({
                "start_s": start,
                "end_s": end,
                "type": section_type,
                "label": label,
                "energy_score": avg_energy,
                "rhythm_score": 0.6,  # placeholder — beat_clarity would go here
                "montage_score": montage_score,
                "status": status,
            })

        return sections

    def _energy_fallback(self, audio_path: str, energy: Optional[dict], beats: Optional[dict]) -> List[dict]:
        """Simple section detection using energy sections only."""
        if not energy or not energy.get("sections"):
            return _flat_sections(audio_path)

        sections = []
        energy_sections = energy["sections"]
        n = len(energy_sections)
        for i, es in enumerate(energy_sections):
            avg_e = es["avg_energy"]
            section_type, label = _classify_section(i, n, avg_e, es["end_s"] - es["start_s"])
            montage_score = _compute_montage_score(avg_e, section_type)
            status = "best" if montage_score > 0.7 else "optional"
            sections.append({
                "start_s": es["start_s"],
                "end_s": es["end_s"],
                "type": section_type,
                "label": label,
                "energy_score": avg_e,
                "rhythm_score": 0.5,
                "montage_score": montage_score,
                "status": status,
            })
        return sections


def _classify_section(idx: int, total: int, energy: float, duration: float):
    ratio = idx / max(total - 1, 1)
    if ratio < 0.1:
        return "intro", "intro"
    if ratio > 0.9:
        return "outro", "outro"
    if energy > 0.75:
        return "drop" if duration < 30 else "chorus", "chorus"
    if energy > 0.5:
        return "buildup", "verse"
    if energy < 0.3:
        return "calm", "breakdown"
    return "verse", "verse"


def _compute_montage_score(energy: float, section_type: str) -> float:
    base = energy * 0.7
    bonus = {"drop": 0.3, "chorus": 0.25, "buildup": 0.15, "peak": 0.3}.get(section_type, 0.0)
    return min(1.0, base + bonus)


def _avg_energy_in_range(curve, times, start, end) -> float:
    if not curve or not times:
        return 0.5
    vals = [curve[i] for i, t in enumerate(times) if start <= t < end]
    return float(np.mean(vals)) if vals else 0.5


def _estimate_k(duration: float) -> int:
    return max(4, min(12, int(duration / 30)))


def _flat_sections(audio_path: str) -> List[dict]:
    try:
        import librosa
        duration = librosa.get_duration(filename=audio_path)
    except Exception:
        duration = 180.0
    step = 30.0
    sections = []
    t = 0.0
    while t < duration:
        end = min(t + step, duration)
        sections.append({"start_s": t, "end_s": end, "type": "verse", "label": "verse",
                          "energy_score": 0.5, "rhythm_score": 0.5,
                          "montage_score": 0.4, "status": "optional"})
        t += step
    return sections
