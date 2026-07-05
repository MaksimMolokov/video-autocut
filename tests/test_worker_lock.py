"""Лок фонового воркера: захват, повторный захват, мёртвый pid."""
import os
import subprocess
import sys

from core import worker_lock


def test_acquire_and_release(tmp_path):
    assert worker_lock.acquire(tmp_path)
    assert worker_lock.is_running(tmp_path)     # наш процесс жив
    worker_lock.release(tmp_path)
    assert not worker_lock.is_running(tmp_path)


def test_second_acquire_blocked(tmp_path):
    assert worker_lock.acquire(tmp_path)
    assert not worker_lock.acquire(tmp_path)    # лок держит живой (наш) pid
    worker_lock.release(tmp_path)


def test_stale_lock_taken_over(tmp_path):
    """Мёртвый процесс не блокирует новый воркер."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "worker.pid").write_text(str(dead.pid))
    assert not worker_lock.is_running(tmp_path)
    assert worker_lock.acquire(tmp_path)        # перехватили
    assert int((tmp_path / "cache" / "worker.pid").read_text()) == os.getpid()
    worker_lock.release(tmp_path)


def test_garbage_lock_file(tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "worker.pid").write_text("мусор")
    assert not worker_lock.is_running(tmp_path)
    assert worker_lock.acquire(tmp_path)
    worker_lock.release(tmp_path)
