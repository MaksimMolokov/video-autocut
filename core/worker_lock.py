"""Лок фонового воркера анализа: один воркер на проект.

pid-файл в папке проекта. Мёртвый процесс (краш, kill) оставляет lock —
он определяется через _pid_alive() и считается несущественным (stale).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_LOCK_NAME = "worker.pid"


def _lock_path(project_dir: Path) -> Path:
    return project_dir / "cache" / _LOCK_NAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) на Windows не бросает исключение для мёртвого pid
        # (сигнал 0 там не значит «проверка существования»). OpenProcess()
        # тоже недостаточен: хендл на PID открывается, даже если процесс уже
        # завершился, пока PID не переиспользован ОС — нужен реальный
        # exit-код через GetExitCodeProcess (STILL_ACTIVE = процесс жив).
        import ctypes

        STILL_ACTIVE = 259
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
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
