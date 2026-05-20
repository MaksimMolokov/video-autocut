"""
Project manager for handling project structure and temporary files
"""

import shutil
from pathlib import Path
from typing import Optional
import yaml


class ProjectManager:
    """Manages project structure and temporary files"""

    def __init__(self, project_path: str | Path):
        """
        Initialize project manager

        Args:
            project_path: Path to project directory
        """
        self.project_path = Path(project_path)
        self.project_path.mkdir(parents=True, exist_ok=True)

        # Create project structure
        self.input_dir = self.project_path / "input"
        self.music_dir = self.project_path / "music"
        self.temp_dir = self.project_path / "temp"
        self.output_dir = self.project_path / "output"
        self.logs_dir = self.project_path / "logs"

        # Create subdirectories in temp
        self.proxy_dir = self.temp_dir / "proxy"
        self.thumbnails_dir = self.temp_dir / "thumbnails"
        self.fragments_dir = self.temp_dir / "fragments"
        self.analysis_dir = self.temp_dir / "analysis"
        self.render_dir = self.temp_dir / "render"

        self._create_structure()

    def _create_structure(self):
        """Create project directory structure"""
        directories = [
            self.input_dir,
            self.music_dir,
            self.temp_dir,
            self.output_dir,
            self.logs_dir,
            self.proxy_dir,
            self.thumbnails_dir,
            self.fragments_dir,
            self.analysis_dir,
            self.render_dir
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def get_project_config_path(self) -> Path:
        """Get path to project.yaml"""
        return self.project_path / "project.yaml"

    def save_config(self, config: dict):
        """Save project configuration to YAML"""
        config_path = self.get_project_config_path()
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)

    def load_config(self) -> Optional[dict]:
        """Load project configuration from YAML"""
        config_path = self.get_project_config_path()
        if not config_path.exists():
            return None

        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def clear_temp(self, keep_proxy: bool = False):
        """
        Clear temporary files

        Args:
            keep_proxy: If True, keep proxy files
        """
        # Clear fragments
        if self.fragments_dir.exists():
            shutil.rmtree(self.fragments_dir)
            self.fragments_dir.mkdir(exist_ok=True)

        # Clear render temp
        if self.render_dir.exists():
            shutil.rmtree(self.render_dir)
            self.render_dir.mkdir(exist_ok=True)

        # Clear proxy if requested
        if not keep_proxy and self.proxy_dir.exists():
            shutil.rmtree(self.proxy_dir)
            self.proxy_dir.mkdir(exist_ok=True)

    def get_free_space_gb(self) -> float:
        """
        Get free disk space in GB

        Returns:
            Free space in gigabytes
        """
        stat = shutil.disk_usage(self.project_path)
        return stat.free / (1024 ** 3)

    def check_space_available(self, required_gb: float) -> bool:
        """
        Check if enough disk space is available

        Args:
            required_gb: Required space in GB

        Returns:
            True if enough space available
        """
        return self.get_free_space_gb() >= required_gb

    def estimate_required_space_gb(
        self,
        video_sizes_bytes: list[int],
        target_duration: float,
        with_music: bool = False
    ) -> float:
        """
        Estimate required disk space for processing

        Args:
            video_sizes_bytes: List of input video file sizes in bytes
            target_duration: Target output duration in seconds
            with_music: Whether music will be added

        Returns:
            Estimated required space in GB
        """
        # Total input size
        total_input_gb = sum(video_sizes_bytes) / (1024 ** 3)

        # Estimate temp fragments (worst case: 50% of input)
        fragments_gb = total_input_gb * 0.5

        # Estimate output (assume similar bitrate, scaled by duration)
        # Rough estimate: 1GB per 10 minutes of 1080p video
        output_gb = target_duration / 600  # 600 seconds = 10 minutes

        # Add safety margin (2x)
        total_required = (fragments_gb + output_gb) * 2

        return max(1.0, total_required)  # At least 1GB

    def get_project_info(self) -> dict:
        """Get project information"""
        return {
            "project_path": str(self.project_path),
            "input_dir": str(self.input_dir),
            "music_dir": str(self.music_dir),
            "temp_dir": str(self.temp_dir),
            "output_dir": str(self.output_dir),
            "free_space_gb": self.get_free_space_gb(),
            "config_exists": self.get_project_config_path().exists()
        }


def validate_video_path(video_path: str | Path) -> tuple[bool, str]:
    """
    Validate video file path

    Args:
        video_path: Path to video file

    Returns:
        Tuple of (is_valid, error_message)
    """
    path = Path(video_path)

    if not path.exists():
        return False, f"Файл не найден: {video_path}"

    if not path.is_file():
        return False, f"Путь не является файлом: {video_path}"

    # Check extension
    valid_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.mts', '.m2ts', '.webm']
    if path.suffix.lower() not in valid_extensions:
        return False, f"Неподдерживаемый формат: {path.suffix}"

    # Check file size (warn if > 50GB, but don't reject)
    size_gb = path.stat().st_size / (1024 ** 3)
    if size_gb > 50:
        return True, f"⚠️ Большой файл ({size_gb:.1f} GB). Обработка может занять время."

    return True, ""


if __name__ == "__main__":
    # Test project manager
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_project = Path(tmp) / "test_project"

        pm = ProjectManager(test_project)

        print("✓ Project structure created:")
        print(f"  Project: {pm.project_path}")
        print(f"  Input: {pm.input_dir}")
        print(f"  Temp: {pm.temp_dir}")
        print(f"  Output: {pm.output_dir}")

        print(f"\n✓ Free space: {pm.get_free_space_gb():.1f} GB")

        # Test config
        test_config = {
            "project": {"name": "Test Project"},
            "sources": []
        }
        pm.save_config(test_config)
        loaded = pm.load_config()
        print(f"\n✓ Config saved and loaded: {loaded['project']['name']}")

        # Test space estimation
        video_sizes = [5 * 1024**3]  # 5GB
        required = pm.estimate_required_space_gb(video_sizes, 60.0)
        print(f"\n✓ Estimated space for 60s video: {required:.1f} GB")
