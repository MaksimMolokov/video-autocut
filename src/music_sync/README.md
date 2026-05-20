# Music Sync Module

Comprehensive music synchronization system for automatic video editing synchronized to music.

## Overview

This module provides three music synchronization strategies:

1. **Simple Tempo** - Adjusts clip durations to match music tempo without precise beat alignment
2. **Beat Sync** - Aligns video cuts exactly to musical beats/onsets
3. **Dynamic Sync** - Adapts editing pace to music energy dynamics (slow→long clips, fast→short clips)

## Architecture

```
music_sync/
├── __init__.py          # Public API
├── models.py            # Data structures
├── analyzer.py          # Audio analysis using librosa
├── cache.py             # Analysis result caching
├── base.py              # Strategy base class
├── simple_tempo.py      # Simple tempo strategy
├── beat_sync.py         # Beat-aligned strategy
├── dynamic_sync.py      # Energy-adaptive strategy
└── README.md            # This file
```

## Dependencies

- `librosa >= 0.10.0` - Audio analysis
- `numpy >= 1.24.0` - Numerical processing
- `scipy >= 1.10.0` - Signal processing

Install with:
```bash
pip install librosa numpy scipy
```

## Usage

### Basic Usage

```python
from src.music_sync import MusicAnalyzer, create_strategy, MusicSyncSettings

# 1. Analyze music
analyzer = MusicAnalyzer(cache_enabled=True)
audio_analysis = analyzer.analyze("music.mp3")

print(f"Tempo: {audio_analysis.tempo:.1f} BPM")
print(f"Beats: {len(audio_analysis.beat_points)}")
print(f"Energy sections: {len(audio_analysis.energy_sections)}")

# 2. Create sync strategy
settings = MusicSyncSettings(
    mode="beat_sync",
    cut_every_n_beats=4,
    prefer_strong_beats=True
)

strategy = create_strategy(settings)

# 3. Build cut plan
cut_plan = strategy.build_cut_plan(
    audio_analysis=audio_analysis,
    available_segments=video_segments,
    target_duration=60.0,
    dynamic_level="balanced"
)

print(f"Total cuts: {len(cut_plan.cut_points)}")
```

### Integration with Segment Selection

The module is integrated via `music_sync_integration.py`:

```python
from src.music_sync_integration import integrate_music_sync_with_selection
from src.effects_config import MusicSyncSettings, MusicSyncMode

music_settings = MusicSyncSettings(
    enabled=True,
    mode=MusicSyncMode.BEAT_SYNC
)

segments = integrate_music_sync_with_selection(
    music_path="music.mp3",
    sources=video_sources,
    target_duration=60.0,
    dynamic_level="balanced",
    music_settings=music_settings
)
```

## Strategies

### 1. Simple Tempo Sync

**Best for:** General use, basic rhythm matching

**How it works:**
- Detects tempo (BPM)
- Calculates beat duration
- Sets clip durations to multiples of beats (2, 4, or 8 beats)
- Adds random variation (±20%)

**Settings:**
- None (uses global min/max clip duration from dynamic_level)

**Example:**
```python
settings = MusicSyncSettings(mode="simple_tempo")
strategy = create_strategy(settings)
```

### 2. Beat Sync

**Best for:** Rhythmic music, electronic, hip-hop, dance

**How it works:**
- Detects all musical beats using librosa
- Identifies strong beats (downbeats)
- Places video cuts exactly on selected beats
- Respects min/max clip duration constraints

**Settings:**
```python
settings = MusicSyncSettings(
    mode="beat_sync",
    cut_every_n_beats=4,          # Cut every 4 beats (1 bar)
    prefer_strong_beats=True,      # Prefer downbeats
    allow_offbeat_cuts=True,       # Fill gaps if needed
    beat_tolerance=0.1             # ±0.1s alignment tolerance
)
```

**Dynamic level effects:**
- `slow`: cut_every_n_beats × 2 (less frequent cuts)
- `balanced`: cut_every_n_beats (as specified)
- `fast`: cut_every_n_beats ÷ 2 (more frequent cuts)

### 3. Dynamic Sync

**Best for:** Cinematic music with varying energy, soundtracks, orchestral

**How it works:**
- Analyzes energy over time (RMS + spectral flux)
- Divides music into energy sections: LOW, MEDIUM, HIGH
- Uses longer clips in low-energy sections
- Uses shorter clips in high-energy sections
- Optionally aligns to beats within high-energy sections

**Settings:**
```python
settings = MusicSyncSettings(
    mode="dynamic_sync",
    # Energy-based clip durations (min, max) in seconds
    low_energy_clip_duration=(4.0, 7.0),      # Slow, contemplative
    medium_energy_clip_duration=(2.0, 4.0),   # Normal pace
    high_energy_clip_duration=(0.8, 2.5),     # Fast, intense

    # Advanced
    use_beats_inside_sections=True,  # Align to beats in HIGH sections
    energy_window_size=2.0           # Smoothing window (seconds)
)
```

**Energy detection:**
- Uses quantiles (33rd, 66th percentile) to classify sections
- Smooths energy curve with 2-second window
- Merges sections shorter than 1 second

## Caching

Analysis results are automatically cached to `temp/audio_analysis/`:

```python
# Cache is enabled by default
analyzer = MusicAnalyzer(cache_enabled=True)

# First analysis: processes audio (~5-10 seconds)
analysis1 = analyzer.analyze("music.mp3")

# Second analysis: loads from cache (~0.1 seconds)
analysis2 = analyzer.analyze("music.mp3")
```

Cache files are named: `{filename}_{md5hash}.json`

Cache is invalidated when:
- Audio file is modified (newer mtime)
- Cache file is manually deleted

## Data Models

### AudioAnalysis

Complete analysis result:
```python
@dataclass
class AudioAnalysis:
    file_path: str
    duration: float              # Total duration (seconds)
    sample_rate: int             # Sample rate (Hz)
    tempo: Optional[float]       # BPM (if detected)

    # Beat information
    beat_times: List[float]      # Beat timestamps
    beat_points: List[BeatPoint] # Detailed beat info

    # Onset information
    onset_times: List[float]     # Onset timestamps
    onset_strengths: List[float] # Onset strengths

    # Energy information
    energy_curve: List[float]    # RMS energy over time
    energy_sections: List[EnergySection]  # Energy-based sections
```

### BeatPoint

Individual beat information:
```python
@dataclass
class BeatPoint:
    time: float          # Time in seconds
    strength: float      # Beat strength (0-1)
    is_strong_beat: bool # True if downbeat
```

### EnergySection

Energy-based section:
```python
@dataclass
class EnergySection:
    start_time: float
    end_time: float
    energy_level: EnergyLevel  # LOW, MEDIUM, HIGH
    avg_energy: float          # Average energy (0-1)
```

### CutPlan

Output from strategy:
```python
@dataclass
class CutPlan:
    target_duration: float
    cut_points: List[CutPoint]       # Where to cut
    segment_durations: List[float]   # How long each segment
```

## GUI Integration

The music sync is integrated in the Streamlit GUI:

**Location:** Settings → Music Sync

**Options:**
1. Enable music synchronization ☑
2. Select mode: Simple Tempo / Beat Sync / Dynamic Sync
3. Advanced settings (for Beat Sync and Dynamic Sync)

**Beat Sync Advanced:**
- Cut every N beats (1-8)
- Prefer strong beats (checkbox)

**Dynamic Sync Advanced:**
- Use beats in high-energy sections (checkbox)

## Performance

**Analysis Performance:**
- Audio loading: ~1-3 seconds (depends on file size)
- Beat detection: ~2-5 seconds
- Energy analysis: ~1-2 seconds
- **Total:** ~5-10 seconds for first analysis
- **Cached:** ~0.1 seconds for subsequent analyses

**Cut Plan Building:**
- Simple Tempo: <0.1 seconds
- Beat Sync: <0.5 seconds
- Dynamic Sync: <1 second

## Troubleshooting

### Import Error: librosa not found

```bash
pip install librosa
```

### No beats detected

- Ensure audio file has clear rhythm
- Try different beat_source: `"beats"`, `"onsets"`, or `"both"`
- Check audio quality and format
- Try fallback to `simple_tempo`

### Energy analysis failed

- File may be too short (<2 seconds)
- Audio may be silent or corrupted
- Check logs for specific error

### Cuts don't align perfectly with beats

- Adjust `beat_tolerance` setting
- Try `prefer_strong_beats=True`
- Check that beat detection worked (log output)

## Examples

### Example 1: Electronic Music with Beat Sync

```python
settings = MusicSyncSettings(
    mode="beat_sync",
    cut_every_n_beats=2,  # Cut every 2 beats (fast)
    prefer_strong_beats=True
)
```

### Example 2: Cinematic Trailer with Dynamic Sync

```python
settings = MusicSyncSettings(
    mode="dynamic_sync",
    low_energy_clip_duration=(5.0, 8.0),   # Slow buildup
    high_energy_clip_duration=(0.5, 1.5),  # Fast climax
    use_beats_inside_sections=True
)
```

### Example 3: General Video with Simple Tempo

```python
settings = MusicSyncSettings(
    mode="simple_tempo"
)
# Uses tempo to suggest clip durations but doesn't align precisely
```

## Technical Details

### Beat Detection Algorithm

Uses librosa's `beat_track()`:
1. Compute onset strength envelope
2. Estimate tempo via autocorrelation
3. Track beats using dynamic programming
4. Classify strong beats using strength threshold + position

### Energy Detection Algorithm

1. Calculate RMS energy: `librosa.feature.rms()`
2. Smooth with moving average (2-second window)
3. Normalize to 0-1 range
4. Classify using quantiles:
   - LOW: 0-33rd percentile
   - MEDIUM: 33rd-66th percentile
   - HIGH: 66th-100th percentile
5. Merge short sections (<1 second)

### Fallback Mechanism

If music sync fails:
1. Log error with details
2. Attempt fallback_mode if configured
3. If fallback also fails, raise exception
4. GUI falls back to standard segment selection

## API Reference

### MusicAnalyzer

```python
analyzer = MusicAnalyzer(cache_enabled=True, cache_dir="temp/audio_analysis")
analysis = analyzer.analyze(audio_path, analyze_beats=True, analyze_onsets=True, analyze_energy=True)
```

### create_strategy()

```python
from src.music_sync import create_strategy, MusicSyncSettings

settings = MusicSyncSettings(mode="beat_sync")
strategy = create_strategy(settings)
```

### AudioAnalysisCache

```python
cache = AudioAnalysisCache(cache_dir="temp/audio_analysis")

# Manual cache management
cached = cache.get(audio_path)  # Returns AudioAnalysis or None
cache.save(analysis)             # Save analysis
cache.clear_file(audio_path)     # Clear specific file
cache.clear()                    # Clear all cache
```

## Future Enhancements

Potential improvements:
- [ ] Chorus/verse detection for structural sync
- [ ] Climax detection and prioritization
- [ ] Multi-track analysis (stems)
- [ ] Genre-specific optimizations
- [ ] Real-time preview mode
- [ ] Custom energy classification thresholds
- [ ] Beat subdivision (half-beats, triplets)
- [ ] Swing/groove detection

## Credits

Built using:
- [librosa](https://librosa.org/) - Audio analysis
- [NumPy](https://numpy.org/) - Numerical computing
- [SciPy](https://scipy.org/) - Scientific computing
