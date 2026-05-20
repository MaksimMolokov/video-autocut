"""
Configuration loader for project.yaml files
"""

import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class Range:
    """Video range definition"""
    start: float
    end: float
    type: str  # "good", "bad", "must_use"

    def __post_init__(self):
        if self.type not in ("good", "bad", "must_use"):
            raise ValueError(f"Invalid range type: {self.type}")
        if self.start >= self.end:
            raise ValueError(f"Invalid range: start ({self.start}) >= end ({self.end})")

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Source:
    """Video source file definition"""
    path: str
    ranges: List[Range]


@dataclass
class OutputConfig:
    """Output configuration"""
    target_duration: float
    format: str  # "horizontal", "vertical", "square"
    dynamic_level: str  # "slow", "balanced", "fast"

    def __post_init__(self):
        if self.format not in ("horizontal", "vertical", "square"):
            raise ValueError(f"Invalid format: {self.format}")
        if self.dynamic_level not in ("slow", "balanced", "fast"):
            raise ValueError(f"Invalid dynamic level: {self.dynamic_level}")

    @property
    def resolution(self) -> tuple[int, int]:
        """Get resolution for the format"""
        resolutions = {
            "horizontal": (1920, 1080),
            "vertical": (1080, 1920),
            "square": (1080, 1080)
        }
        return resolutions[self.format]


@dataclass
class MusicConfig:
    """Music configuration"""
    path: str
    fade_in: float = 3.0
    fade_out: float = 3.0


@dataclass
class ProjectConfig:
    """Complete project configuration"""
    name: str
    sources: List[Source]
    output: OutputConfig
    music: Optional[MusicConfig] = None


class ConfigLoader:
    """Loads and validates project.yaml configuration"""

    @staticmethod
    def load(config_path: str | Path) -> ProjectConfig:
        """
        Load configuration from YAML file

        Args:
            config_path: Path to project.yaml file

        Returns:
            ProjectConfig object

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If configuration is invalid
        """
        config_path = Path(config_path)

        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        return ConfigLoader._parse_config(data)

    @staticmethod
    def _parse_config(data: Dict[str, Any]) -> ProjectConfig:
        """Parse raw YAML data into ProjectConfig"""

        # Parse project name
        project_data = data.get('project', {})
        name = project_data.get('name', 'Untitled Project')

        # Parse sources
        sources_data = data.get('sources', [])
        if not sources_data:
            raise ValueError("No sources defined in configuration")

        sources = []
        for source_data in sources_data:
            path = source_data.get('path')
            if not path:
                raise ValueError("Source path is required")

            ranges_data = source_data.get('ranges', [])
            ranges = []
            for range_data in ranges_data:
                ranges.append(Range(
                    start=float(range_data['start']),
                    end=float(range_data['end']),
                    type=range_data['type']
                ))

            sources.append(Source(path=path, ranges=ranges))

        # Parse output config
        output_data = data.get('output', {})
        if not output_data:
            raise ValueError("Output configuration is required")

        output = OutputConfig(
            target_duration=float(output_data['target_duration']),
            format=output_data.get('format', 'horizontal'),
            dynamic_level=output_data.get('dynamic_level', 'balanced')
        )

        # Parse music config (optional)
        music = None
        music_data = data.get('music')
        if music_data:
            music = MusicConfig(
                path=music_data['path'],
                fade_in=float(music_data.get('fade_in', 3.0)),
                fade_out=float(music_data.get('fade_out', 3.0))
            )

        return ProjectConfig(
            name=name,
            sources=sources,
            output=output,
            music=music
        )

    @staticmethod
    def get_preset(preset_name: str) -> Dict[str, str]:
        """
        Get predefined preset configuration

        Args:
            preset_name: One of "slow_cinematic", "balanced_promo", "fast_dynamic"

        Returns:
            Dict with format and dynamic_level keys
        """
        presets = {
            "slow_cinematic": {
                "format": "horizontal",
                "dynamic_level": "slow"
            },
            "balanced_promo": {
                "format": "square",
                "dynamic_level": "balanced"
            },
            "fast_dynamic": {
                "format": "vertical",
                "dynamic_level": "fast"
            }
        }

        if preset_name not in presets:
            raise ValueError(f"Unknown preset: {preset_name}")

        return presets[preset_name]


if __name__ == "__main__":
    # Test loading example config
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.config_loader <path/to/project.yaml>")
        sys.exit(1)

    try:
        config = ConfigLoader.load(sys.argv[1])
        print(f"✓ Configuration loaded successfully")
        print(f"  Project: {config.name}")
        print(f"  Sources: {len(config.sources)}")
        print(f"  Target duration: {config.output.target_duration}s")
        print(f"  Format: {config.output.format} ({config.output.resolution[0]}×{config.output.resolution[1]})")
        print(f"  Dynamic level: {config.output.dynamic_level}")
        if config.music:
            print(f"  Music: {config.music.path}")
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)
