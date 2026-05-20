"""
Advanced music analysis
Extends basic analyzer with structure detection, mood estimation, and peak identification
"""

import logging
import numpy as np
from typing import List, Tuple
from scipy import signal
from scipy.ndimage import maximum_filter

from .models import (
    AudioAnalysis, MusicStructureSection, TrackSection,
    MusicMood, EnergyLevel
)

logger = logging.getLogger(__name__)


class AdvancedMusicAnalyzer:
    """Advanced music analysis for track structure and mood"""

    @staticmethod
    def analyze_structure(analysis: AudioAnalysis) -> AudioAnalysis:
        """
        Detect track structure (intro, verse, chorus, etc.)

        This is a heuristic approach based on:
        - Energy changes
        - Beat patterns
        - Repetition detection

        Returns updated AudioAnalysis with structure_sections filled
        """
        if not analysis.energy_curve or len(analysis.energy_curve) < 10:
            logger.warning("Insufficient data for structure analysis")
            return analysis

        logger.info("[AdvancedAnalyzer] Analyzing track structure...")

        duration = analysis.duration
        sections = []

        # Simple heuristic: detect intro, body, outro based on energy
        intro_duration = min(duration * 0.15, 20.0)  # First 15% or 20s max
        outro_start = max(duration - min(duration * 0.1, 15.0), duration * 0.8)  # Last 10-20%

        # Detect drops (sharp energy increases)
        drop_times = AdvancedMusicAnalyzer._detect_drops(analysis)
        analysis.drop_times = drop_times

        # Detect peaks/climaxes
        peak_times = AdvancedMusicAnalyzer._detect_peaks(analysis)
        analysis.peak_times = peak_times

        current_time = 0.0

        # Intro section
        if intro_duration > 2.0:
            sections.append(MusicStructureSection(
                start_time=0.0,
                end_time=intro_duration,
                section_type=TrackSection.INTRO,
                confidence=0.7
            ))
            current_time = intro_duration

        # Middle sections - identify potential chorus/verse
        # Look for repeating energy patterns
        if duration > 30:
            chorus_times = AdvancedMusicAnalyzer._detect_chorus(analysis, intro_duration, outro_start)

            # Build sections based on detected patterns
            for i, (chorus_start, chorus_end) in enumerate(chorus_times):
                # Add verse before chorus if there's space
                if current_time < chorus_start - 5.0:
                    sections.append(MusicStructureSection(
                        start_time=current_time,
                        end_time=chorus_start,
                        section_type=TrackSection.VERSE,
                        confidence=0.6
                    ))

                # Add chorus
                sections.append(MusicStructureSection(
                    start_time=chorus_start,
                    end_time=chorus_end,
                    section_type=TrackSection.CHORUS,
                    confidence=0.7
                ))

                current_time = chorus_end

        # Outro section
        if outro_start < duration - 2.0:
            # Add verse/body before outro if needed
            if current_time < outro_start - 3.0:
                sections.append(MusicStructureSection(
                    start_time=current_time,
                    end_time=outro_start,
                    section_type=TrackSection.VERSE,
                    confidence=0.5
                ))

            sections.append(MusicStructureSection(
                start_time=outro_start,
                end_time=duration,
                section_type=TrackSection.OUTRO,
                confidence=0.7
            ))

        # Mark drops as special sections
        for drop_time in drop_times:
            # Check if this overlaps with existing sections
            overlaps = False
            for section in sections:
                if section.start_time <= drop_time <= section.end_time:
                    # Already covered
                    overlaps = True
                    break

            if not overlaps:
                # Add drop section
                drop_duration = 8.0  # Assume ~8s drop section
                sections.append(MusicStructureSection(
                    start_time=max(0, drop_time - 2),
                    end_time=min(duration, drop_time + drop_duration),
                    section_type=TrackSection.DROP,
                    confidence=0.8
                ))

        # Sort sections by time
        sections.sort(key=lambda s: s.start_time)

        analysis.structure_sections = sections

        logger.info(f"  Detected {len(sections)} structural sections")
        for section in sections:
            logger.info(f"    {section.section_type.value}: {section.start_time:.1f}s - {section.end_time:.1f}s")

        return analysis

    @staticmethod
    def _detect_drops(analysis: AudioAnalysis) -> List[float]:
        """Detect drop points (sharp energy increases)"""
        if not analysis.energy_curve or len(analysis.energy_curve) < 20:
            return []

        energy = np.array(analysis.energy_curve)

        # Calculate energy derivative (rate of change)
        energy_diff = np.diff(energy)

        # Find sharp increases
        threshold = np.percentile(energy_diff, 90)  # Top 10% increases

        drop_indices = []
        for i in range(len(energy_diff)):
            if energy_diff[i] > threshold:
                # Check if this is a significant drop (not just noise)
                if i > 5 and i < len(energy_diff) - 5:
                    # Verify energy increases substantially
                    before_avg = np.mean(energy[max(0, i-5):i])
                    after_avg = np.mean(energy[i+1:min(len(energy), i+6)])

                    if after_avg > before_avg * 1.3:  # 30% increase
                        drop_indices.append(i)

        # Convert indices to time
        hop_length = 512
        sr = analysis.sample_rate
        frame_duration = hop_length / sr

        drop_times = [idx * frame_duration for idx in drop_indices]

        # Remove drops that are too close together (< 15s apart)
        filtered_drops = []
        for drop_time in drop_times:
            if not filtered_drops or (drop_time - filtered_drops[-1]) > 15.0:
                filtered_drops.append(drop_time)

        return filtered_drops

    @staticmethod
    def _detect_peaks(analysis: AudioAnalysis) -> List[float]:
        """Detect climax/peak points"""
        if not analysis.energy_curve or len(analysis.energy_curve) < 20:
            return []

        energy = np.array(analysis.energy_curve)

        # Smooth energy curve
        window_size = 20
        smoothed = np.convolve(energy, np.ones(window_size)/window_size, mode='same')

        # Find local maxima
        local_max_filter = maximum_filter(smoothed, size=30)
        peaks = (smoothed == local_max_filter) & (smoothed > 0)

        peak_indices = np.where(peaks)[0]

        # Filter to keep only significant peaks (top 30%)
        peak_values = smoothed[peak_indices]
        if len(peak_values) == 0:
            return []

        threshold = np.percentile(peak_values, 70)
        significant_peaks = peak_indices[peak_values >= threshold]

        # Convert to time
        hop_length = 512
        sr = analysis.sample_rate
        frame_duration = hop_length / sr

        peak_times = [idx * frame_duration for idx in significant_peaks]

        # Remove peaks too close together (< 20s apart)
        filtered_peaks = []
        for peak_time in peak_times:
            if not filtered_peaks or (peak_time - filtered_peaks[-1]) > 20.0:
                filtered_peaks.append(peak_time)

        return filtered_peaks

    @staticmethod
    def _detect_chorus(analysis: AudioAnalysis, start_time: float, end_time: float) -> List[Tuple[float, float]]:
        """
        Detect chorus sections (repeating high-energy parts)

        Returns list of (start, end) tuples
        """
        if not analysis.energy_sections:
            return []

        # Find high-energy sections in the middle of the track
        high_energy_sections = [
            (section.start_time, section.end_time)
            for section in analysis.energy_sections
            if section.energy_level == EnergyLevel.HIGH
            and start_time < section.start_time < end_time
            and section.duration > 10.0  # At least 10 seconds
        ]

        # Group nearby sections
        if not high_energy_sections:
            return []

        # Simple heuristic: take 2-3 largest high-energy sections as potential choruses
        high_energy_sections.sort(key=lambda x: x[1] - x[0], reverse=True)

        # Take top 2-3 sections
        chorus_sections = high_energy_sections[:min(3, len(high_energy_sections))]

        # Sort by time
        chorus_sections.sort(key=lambda x: x[0])

        return chorus_sections

    @staticmethod
    def estimate_mood(analysis: AudioAnalysis) -> AudioAnalysis:
        """
        Estimate the mood of the track

        Based on:
        - Tempo (fast = energetic, slow = calm)
        - Average energy
        - Energy variance
        """
        if not analysis.energy_curve:
            analysis.detected_mood = MusicMood.UNKNOWN
            analysis.mood_confidence = 0.0
            return analysis

        logger.info("[AdvancedAnalyzer] Estimating mood...")

        energy_arr = np.array(analysis.energy_curve)
        avg_energy = np.mean(energy_arr)
        energy_std = np.std(energy_arr)
        tempo = analysis.tempo or 120.0

        # Decision tree for mood
        mood = MusicMood.UNKNOWN
        confidence = 0.5

        # High energy + fast tempo = Energetic or Aggressive
        if avg_energy > 0.6 and tempo > 130:
            if energy_std > 0.2:
                mood = MusicMood.AGGRESSIVE
                confidence = 0.7
            else:
                mood = MusicMood.ENERGETIC
                confidence = 0.7

        # Medium-high energy + medium-fast tempo = Happy or Epic
        elif avg_energy > 0.5 and 110 < tempo < 140:
            if energy_std > 0.15:
                mood = MusicMood.EPIC
                confidence = 0.6
            else:
                mood = MusicMood.HAPPY
                confidence = 0.6

        # Low energy + slow tempo = Calm or Romantic
        elif avg_energy < 0.4 and tempo < 100:
            if energy_std < 0.1:
                mood = MusicMood.CALM
                confidence = 0.7
            else:
                mood = MusicMood.ROMANTIC
                confidence = 0.6

        # Medium energy + variable = Atmospheric or Dramatic
        elif 0.4 <= avg_energy <= 0.6:
            if energy_std > 0.2:
                mood = MusicMood.DRAMATIC
                confidence = 0.6
            else:
                mood = MusicMood.ATMOSPHERIC
                confidence = 0.6

        else:
            # Default based on energy
            if avg_energy > 0.5:
                mood = MusicMood.ENERGETIC
            else:
                mood = MusicMood.CALM
            confidence = 0.4

        analysis.detected_mood = mood
        analysis.mood_confidence = confidence

        logger.info(f"  Detected mood: {mood.value} (confidence: {confidence:.2f})")
        logger.info(f"    avg_energy={avg_energy:.2f}, tempo={tempo:.1f}, std={energy_std:.2f}")

        return analysis

    @staticmethod
    def analyze_full(analysis: AudioAnalysis) -> AudioAnalysis:
        """
        Perform all advanced analysis

        Returns updated AudioAnalysis
        """
        analysis = AdvancedMusicAnalyzer.analyze_structure(analysis)
        analysis = AdvancedMusicAnalyzer.estimate_mood(analysis)
        return analysis
