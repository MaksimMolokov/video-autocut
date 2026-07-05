"""Лок фонового воркера анализа: один воркер на проект.

pid-файл в папке проекта. Мёртвый процесс (краш, kill) оставляет lock —
он определяется через os.kill(pid, 0) и считается несущественным (stale).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_LOCK_NAME = "worker.pid"


def _lock_path(project_dir: Path) -> Path:
    return project_dir / "cache" / _LOCK_NAME


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # сигнал 0 — только проверка существования
        return True
    except (ProcessLookupError, PermissionError, ValueError):
        return False


def acquire(project_dir: Path) -> bool:
    """Захват лока текущим процессом. False — воркер уже работает."""
    lp = _lock_path(project_dir)
    if lp.exists():
        try:
            pid = int(lp.read_text().strip())
        except ValueError:
            pid = -1
        if pid > 0 and _pid_alive(pid):
            log.warning("Воркер уже запущен (pid=%s)", pid)
            return False
        log.info("Найден мёртвый lock (pid=%s) — перехватываем", pid)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(str(os.getpid()))
    return True


def release(project_dir: Path):
    _lock_path(project_dir).unlink(missing_ok=True)


def is_running(project_dir: Path) -> bool:
    """Жив ли воркер этого проекта прямо сейчас."""
    lp = _lock_path(project_dir)
    if not lp.exists():
        return False
    try:
        return _pid_alive(int(lp.read_text().strip()))
    except ValueError:
        return False
