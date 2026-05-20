"""
Data models for music synchronization
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum


class EnergyLevel(Enum):
    """Energy level classification for music sections"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MusicMood(Enum):
    """Music mood classification"""
    CALM = "calm"  # Спокойное
    ENERGETIC = "energetic"  # Энергичное
    DRAMATIC = "dramatic"  # Драматичное
    HAPPY = "happy"  # Весёлое
    ATMOSPHERIC = "atmospheric"  # Атмосферное
    AGGRESSIVE = "aggressive"  # Агрессивное
    ROMANTIC = "romantic"  # Романтичное
    EPIC = "epic"  # Эпичное
    UNKNOWN = "unknown"  # Неопределённое


class TrackSection(Enum):
    """Music track structure sections"""
    INTRO = "intro"  # Вступление
    VERSE = "verse"  # Куплет
    CHORUS = "chorus"  # Припев
    BRIDGE = "bridge"  # Бридж
    DROP = "drop"  # Дроп (для электронной музыки)
    BREAKDOWN = "breakdown"  # Breakdown
    BUILDUP = "buildup"  # Buildup/подъём
    OUTRO = "outro"  # Финал
    UNKNOWN = "unknown"  # Неопределённый участок


@dataclass
class BeatPoint:
    """A single beat/onset point in the music"""
    time: float  # Time in seconds
    strength: float = 1.0  # Relative strength (0.0 to 1.0)
    is_strong_beat: bool = False  # Whether this is a downbeat/strong beat


@dataclass
class EnergySection:
    """A section of music with consistent energy level"""
    start_time: float
    end_time: float
    energy_level: EnergyLevel
    avg_energy: float  # Average energy value (0.0 to 1.0)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class MusicStructureSection:
    """A structural section of the track (verse, chorus, etc.)"""
    start_time: float
    end_time: float
    section_type: TrackSection
    confidence: float = 1.0  # Confidence level (0.0 to 1.0)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class AudioAnalysis:
    """Complete analysis of an audio file"""
    file_path: str
    duration: float  # Total duration in seconds
    sample_rate: int

    # Tempo analysis
    tempo: Optional[float] = None  # BPM
    beat_times: List[float] = field(default_factory=list)  # Beat timestamps
    beat_points: List[BeatPoint] = field(default_factory=list)

    # Onset detection
    onset_times: List[float] = field(default_factory=list)
    onset_strengths: List[float] = field(default_factory=list)

    # Energy analysis
    energy_curve: List[float] = field(default_factory=list)  # RMS energy over time
    energy_sections: List[EnergySection] = field(default_factory=list)

    # Spectral analysis
    spectral_flux: List[float] = field(default_factory=list)

    # === NEW: Music structure analysis ===
    structure_sections: List[MusicStructureSection] = field(default_factory=list)
    detected_mood: MusicMood = MusicMood.UNKNOWN
    mood_confidence: float = 0.0

    # Peak detection for climax identification
    peak_times: List[float] = field(default_factory=list)  # Times of major peaks/climaxes
    drop_times: List[float] = field(default_factory=list)  # Times of drops

    def get_beat_at_time(self, time: float, tolerance: float = 0.2) -> Optional[BeatPoint]:
        """Find closest beat to given time within tolerance"""
        for beat in self.beat_points:
            if abs(beat.time - time) <= tolerance:
                return beat
        return None

    def get_section_at_time(self, time: float) -> Optional[EnergySection]:
        """Get energy section at given time"""
        for section in self.energy_sections:
            if section.start_time <= time <= section.end_time:
                return section
        return None

    def get_structure_at_time(self, time: float) -> Optional[MusicStructureSection]:
        """Get track structure section at given time"""
        for section in self.structure_sections:
            if section.start_time <= time <= section.end_time:
                return section
        return None

    def is_near_peak(self, time: float, tolerance: float = 2.0) -> bool:
        """Check if time is near a climax/peak"""
        for peak_time in self.peak_times:
            if abs(time - peak_time) <= tolerance:
                return True
        return False

    def is_near_drop(self, time: float, tolerance: float = 1.0) -> bool:
        """Check if time is near a drop"""
        for drop_time in self.drop_times:
            if abs(time - drop_time) <= tolerance:
                return True
        return False


@dataclass
class CutPoint:
    """A point where video should be cut/transitioned"""
    time: float  # Time in the final video
    source_segment_idx: int  # Which source segment to use
    beat_aligned: bool = False  # Whether this cut is aligned to a beat
    energy_level: Optional[EnergyLevel] = None
    structure_section: Optional[TrackSection] = None  # Track structure at this point
    is_climax: bool = False  # Is this near a climax/peak
    is_drop: bool = False  # Is this near a drop


@dataclass
class CutPlan:
    """Complete plan for cutting video to music"""
    target_duration: float
    cut_points: List[CutPoint] = field(default_factory=list)
    segment_durations: List[float] = field(default_factory=list)

    # Applied settings (for reference/debugging)
    applied_preset: Optional[str] = None
    applied_settings: Optional[dict] = None

    # Statistics
    total_cuts: int = 0
    beat_aligned_cuts: int = 0
    avg_segment_duration: float = 0.0
    climax_cuts: int = 0
    drop_cuts: int = 0

    def calculate_stats(self):
        """Calculate statistics about the cut plan"""
        self.total_cuts = len(self.cut_points)
        self.beat_aligned_cuts = sum(1 for cp in self.cut_points if cp.beat_aligned)
        self.climax_cuts = sum(1 for cp in self.cut_points if cp.is_climax)
        self.drop_cuts = sum(1 for cp in self.cut_points if cp.is_drop)
        if self.segment_durations:
            self.avg_segment_duration = sum(self.segment_durations) / len(self.segment_durations)


@dataclass
class MusicSyncSettings:
    """Settings for music synchronization"""
    mode: str = "none"  # none, simple_tempo, beat_sync, dynamic_sync
    fallback_mode: str = "simple_tempo"

    # Beat sync settings
    beat_source: str = "beats"  # beats, onsets, combined
    cut_every_n_beats: int = 4
    min_clip_duration: float = 1.0
    max_clip_duration: float = 4.0
    beat_tolerance: float = 0.15
    prefer_strong_beats: bool = True
    allow_offbeat_cuts: bool = False

    # Dynamic sync settings
    analysis_window_sec: float = 2.0
    energy_metric: str = "combined"  # rms, onset, combined
    section_detection: bool = True
    use_beats_inside_sections: bool = True
    low_energy_clip_duration: Tuple[float, float] = (4.0, 7.0)
    medium_energy_clip_duration: Tuple[float, float] = (2.0, 4.0)
    high_energy_clip_duration: Tuple[float, float] = (0.8, 2.5)
    climax_priority: bool = True


if __name__ == "__main__":
    # Test models
    analysis = AudioAnalysis(
        file_path="test.mp3",
        duration=60.0,
        sample_rate=22050,
        tempo=128.0
    )

    beat = BeatPoint(time=1.5, strength=0.8, is_strong_beat=True)
    section = EnergySection(
        start_time=0.0,
        end_time=15.0,
        energy_level=EnergyLevel.LOW,
        avg_energy=0.3
    )

    print(f"✓ Models created successfully")
    print(f"  Beat at: {beat.time}s")
    print(f"  Section: {section.energy_level.value} ({section.duration}s)")
