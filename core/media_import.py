"""Media Import (ТЗ §4): файлы и папки → список видеофайлов."""
from __future__ import annotations

import hashlib
from pathlib import Path

import config


def file_fingerprint(path: str | Path) -> str:
    """Быстрый отпечаток файла без чтения целиком: размер + mtime +
    md5 первых 64 КБ. Достаточно, чтобы понять «файл не менялся»."""
    p = Path(path)
    st = p.stat()
    h = hashlib.md5()
    h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
    with open(p, "rb") as fh:
        h.update(fh.read(65536))
    return h.hexdigest()


def collect_video_files(paths: list[str | Path]) -> list[Path]:
    """Принимает файлы и/или папки, возвращает отсортированный список видео."""
    result: set[Path] = set()
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            for f in p.rglob("*"):
                if f.suffix.lower() not in config.VIDEO_EXTENSIONS:
                    continue
                # скрытые файлы и файлы внутри скрытых папок (.videoeditor и т.п.)
                rel_parts = f.relative_to(p).parts
                if any(part.startswith(".") for part in rel_parts):
                    continue
                result.add(f.resolve())
        elif p.is_file() and p.suffix.lower() in config.VIDEO_EXTENSIONS:
            result.add(p.resolve())
    return sorted(result)
