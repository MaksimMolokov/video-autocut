"""RenderService — render timelines to video files (TASK-003)."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from infrastructure.config.config_manager import cfg
from infrastructure.storage.path_manager import PathManager

logger = logging.getLogger(__name__)

_ProgressCb = Optional[Callable[[int, str], None]]


class RenderService:
    """
    Render a timeline (list of segments + music) to an output .mp4 file.
    Wraps ffmpeg_renderer with project-aware path resolution.
    """

    def __init__(self, path_manager: PathManager) -> None:
        self.pm = path_manager

    def render(
        self,
        segments: List[dict],
        output_rel_path: str,
        preset: dict,
        music_rel_path: Optional[str] = None,
        music_start_s: float = 0.0,
        music_end_s: Optional[float] = None,
        output_format: str = "16_9",
        watermark_text: str = "",
        watermark_position: str = "bottom_right",
        watermark_opacity: float = 0.7,
        progress_cb: _ProgressCb = None,
    ) -> str:
        """Render and return absolute path to output file."""
        from src.ffmpeg_renderer import FFmpegRenderer

        output_abs = str(self.pm.abs(output_rel_path))
        Path(output_abs).parent.mkdir(parents=True, exist_ok=True)

        # Convert relative segment paths to absolute
        abs_segments = []
        for seg in segments:
            abs_seg = dict(seg)
            rel = seg.get("source_rel_path", "")
            abs_seg["source_path"] = str(self.pm.abs(rel)) if rel else seg.get("source_path", "")
            abs_segments.append(abs_seg)

        music_abs = str(self.pm.abs(music_rel_path)) if music_rel_path else None

        settings = preset.get("settings", {})
        transition = settings.get("transitions", {})
        render_cfg = cfg.render

        FFmpegRenderer.render(
            segments=abs_segments,
            output_path=output_abs,
            music_path=music_abs,
            music_start_s=music_start_s,
            music_end_s=music_end_s,
            output_format=output_format,
            transition_type=transition.get("type", "cut"),
            transition_duration=transition.get("duration", 0.3),
            fps=render_cfg.get("fps", 30),
            watermark_text=watermark_text or "",
            watermark_position=watermark_position,
            watermark_opacity=watermark_opacity,
            progress_callback=progress_cb,
        )

        logger.info("[RenderService] done → %s", output_abs)
        return output_abs

    def save_render_job(
        self,
        project_id: Optional[int],
        output_rel_path: str,
        preset_id: str,
        preset_name: str,
        clip_count: int,
        actual_duration_s: float,
        **kwargs,
    ) -> int:
        from sqlalchemy.orm import Session
        from infrastructure.database.models import create_db_engine
        from infrastructure.database.repository import RenderJobRepo

        engine = create_db_engine(str(self.pm.db_path))
        with Session(engine) as session:
            repo = RenderJobRepo(session)
            job = repo.create({
                "project_id": project_id,
                "output_rel_path": output_rel_path,
                "preset_id": preset_id,
                "preset_name": preset_name,
                "clip_count": clip_count,
                "actual_duration_s": actual_duration_s,
                "created_at": time.time(),
                **kwargs,
            })
            return job.id

    def set_rating(self, job_id: int, rating: int) -> None:
        from sqlalchemy.orm import Session
        from infrastructure.database.models import create_db_engine
        from infrastructure.database.repository import RenderJobRepo

        engine = create_db_engine(str(self.pm.db_path))
        with Session(engine) as session:
            RenderJobRepo(session).set_rating(job_id, rating)
