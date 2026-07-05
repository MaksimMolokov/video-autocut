"""CLI: smoke-тесты команд через subprocess."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _run(*args):
    return subprocess.run([sys.executable, "cli.py", *args],
                          capture_output=True, text=True, cwd=ROOT, timeout=120)


def test_presets_command():
    res = _run("presets")
    assert res.returncode == 0
    assert "restaurant" in res.stdout and "tiktok_clip" in res.stdout


def test_projects_command():
    res = _run("projects")
    assert res.returncode == 0


def test_help():
    res = _run("--help")
    assert res.returncode == 0
    for cmd in ("analyze", "llm", "scenes", "plan", "render", "presets", "projects"):
        assert cmd in res.stdout


def test_analyze_project_command_exists():
    res = _run("analyze-project", "--project", "nonexistent-id")
    assert res.returncode != 0  # проект не найден — честная ошибка, не крэш
    assert "не найден" in (res.stdout + res.stderr)


def test_unknown_command():
    res = _run("explode")
    assert res.returncode != 0


def test_analyze_requires_paths():
    res = _run("analyze")
    assert res.returncode != 0
