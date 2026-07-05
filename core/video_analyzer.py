"""Video Analyzer (ТЗ §7.1): технический анализ файла через ffprobe."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.models import SourceVideo


def probe_video(project_id: str, path: str | Path) -> SourceVideo:
    """Читает метаданные через ffprobe. При ошибке возвращает valid=False."""
    v = SourceVideo(project_id=project_id, path=str(path))
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            v.valid, v.error = False, out.stderr.strip()[:500]
            return v
        info = json.loads(out.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        v.valid, v.error = False, str(e)
        return v

    fmt = info.get("format", {})
    v.duration = float(fmt.get("duration", 0) or 0)
    v.bitrate = int(fmt.get("bit_rate", 0) or 0)

    for st in info.get("streams", []):
        if st.get("codec_type") == "video" and not v.width:
            v.width = int(st.get("width", 0) or 0)
            v.height = int(st.get("height", 0) or 0)
            v.codec = st.get("codec_name", "")
            # fps из дроби вида "30000/1001"
            rate = st.get("avg_frame_rate") or st.get("r_frame_rate") or "0/1"
            try:
                num, den = rate.split("/")
                v.fps = round(float(num) / float(den), 3) if float(den) else 0.0
            except ValueError:
                v.fps = 0.0
            # учёт поворота (вертикальное видео с телефона/дрона)
            rotation = 0
            for sd in st.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rotation = abs(int(sd["rotation"]))
            w, h = (v.height, v.width) if rotation in (90, 270) else (v.width, v.height)
            if w > h:
                v.orientation = "horizontal"
            elif h > w:
                v.orientation = "vertical"
            else:
                v.orientation = "square"
        elif st.get("codec_type") == "audio":
            v.has_audio = True

    if v.duration <= 0 or not v.width:
        v.valid, v.error = False, "нет видеопотока или нулевая длительность"
    return v
