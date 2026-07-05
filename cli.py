"""CLI Auto Video Editor V2 — анализ исходников без UI (Фаза 3).

Примеры:
  python3 cli.py analyze ~/VideoProjects/clip1.mp4 ~/VideoProjects/clip2.mp4 --name "Тест"
  python3 cli.py analyze ~/VideoProjects/folder --name "Ресторан" --no-llm
  python3 cli.py llm --project <id>        # дозаполнить LLM-описания
  python3 cli.py scenes --project <id>     # показать каталог сцен
  python3 cli.py projects                  # список проектов
"""
from __future__ import annotations

import argparse
import logging
import sys

from core.models import Project
from core.pipeline import analyze_project, run_llm_analysis
from core.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _resolve_project(storage: Storage, project_id: str | None) -> Project:
    if project_id:
        p = storage.get_project(project_id)
        if not p:
            sys.exit(f"Проект {project_id} не найден")
        return p
    projects = storage.list_projects()
    if not projects:
        sys.exit("Проектов нет. Сначала: cli.py analyze <файлы/папка> --name <имя>")
    return projects[0]  # последний созданный


def cmd_analyze(args):
    storage = Storage()
    project = Project(name=args.name, source_paths=[str(p) for p in args.paths])
    storage.save_project(project)
    print(f"Проект создан: {project.id} «{project.name}»")
    scenes = analyze_project(storage, project, run_llm=not args.no_llm)
    print(f"\nГотово. Сцен в каталоге: {len(scenes)}")
    print(f"Каталог: python3 cli.py scenes --project {project.id}")


def cmd_analyze_project(args):
    """Фоновый воркер: анализ уже созданного проекта по сохранённым путям.
    Запускается из UI через subprocess — прогресс пишется в БД."""
    storage = Storage()
    project = _resolve_project(storage, args.project)
    if not project.source_paths:
        sys.exit("У проекта нет исходников")
    try:
        analyze_project(storage, project, run_llm=not args.no_llm)
    except Exception as e:  # статус ошибки должен дойти до UI
        project.status = "new"
        project.analysis_progress = f"Ошибка анализа: {e}"
        storage.save_project(project)
        raise


def cmd_llm(args):
    storage = Storage()
    project = _resolve_project(storage, args.project)
    run_llm_analysis(storage, project)


def cmd_scenes(args):
    storage = Storage()
    project = _resolve_project(storage, args.project)
    scenes = storage.list_scenes(project.id)
    print(f"Проект «{project.name}» ({project.id}) — сцен: {len(scenes)}\n")
    for s in scenes:
        line = (f"{s.id}  {s.start:7.1f}–{s.end:7.1f}s ({s.duration:4.1f}s)  "
                f"q={s.quality_score:.2f} a={s.aesthetic_score:.2f} "
                f"{s.motion}/{s.motion_type:<8} {s.scene_type or 'нет LLM':<12}")
        print(line)
        if s.description:
            print(f"    {s.description[:100]}")
            print(f"    теги: {', '.join(s.tags[:8])}")


def cmd_plan(args):
    storage = Storage()
    project = _resolve_project(storage, args.project)
    if args.preset:
        project.preset_id = args.preset
    if args.duration:
        project.target_duration = args.duration
    if args.aspect:
        project.aspect = args.aspect
    if args.music:
        project.music_path = args.music
    storage.save_project(project)

    from core.montage_planner import build_plan
    music = None
    if project.music_path:
        from core.audio_analyzer import analyze_music_cached
        print(f"Анализ музыки: {project.music_path}")
        music = analyze_music_cached(storage, project.music_path)
        print(f"  BPM {music.bpm}, битов {len(music.beats)}, кульминация {music.climax_time}s")

    scenes = storage.list_scenes(project.id)
    plan = build_plan(project, scenes, music, use_llm=not args.no_llm)
    storage.save_plan(plan)
    project.status = "planned"
    storage.save_project(project)

    print(f"\nМонтажный план {plan.id} — {plan.total_duration:.1f}s из {project.target_duration}s:")
    t = 0.0
    for seg in plan.segments:
        sc = storage.get_scene(seg.scene_id)
        beat = "♪" if seg.beat_synced else " "
        print(f"  {t:5.1f}s {beat} [{seg.slot:<11}] {seg.duration:4.1f}s  "
              f"{(sc.scene_type if sc else '?'):<12} {seg.reason[:60]}")
        t += seg.duration
    print(f"\nРендер: python3 cli.py render --project {project.id}")


def cmd_render(args):
    storage = Storage()
    project = _resolve_project(storage, args.project)
    plan = storage.latest_plan(project.id)
    if not plan:
        sys.exit("Монтажного плана нет. Сначала: cli.py plan")
    from core.renderer import render_plan
    out = render_plan(storage, project, plan, final=args.final)
    if not out:
        sys.exit("Рендер не удался")
    project.status = "rendered"
    storage.save_project(project)


def cmd_presets(_args):
    from core.presets import PRESETS
    for p in PRESETS.values():
        print(f"{p.id:<16} {p.title:<32} динамика={p.dynamics}")


def cmd_projects(_args):
    storage = Storage()
    for p in storage.list_projects():
        n = len(storage.list_scenes(p.id))
        print(f"{p.id}  [{p.status:9}] сцен={n:3}  «{p.name}»")


def main():
    ap = argparse.ArgumentParser(description="Auto Video Editor V2")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="анализ видео → каталог сцен")
    a.add_argument("paths", nargs="+", help="видеофайлы и/или папки")
    a.add_argument("--name", default="Без названия")
    a.add_argument("--no-llm", action="store_true", help="без смыслового LLM-анализа")
    a.set_defaults(func=cmd_analyze)

    ap_ = sub.add_parser("analyze-project", help="анализ существующего проекта (фоновый воркер)")
    ap_.add_argument("--project", required=True)
    ap_.add_argument("--no-llm", action="store_true")
    ap_.set_defaults(func=cmd_analyze_project)

    l = sub.add_parser("llm", help="дозаполнить LLM-описания сцен")
    l.add_argument("--project", default=None)
    l.set_defaults(func=cmd_llm)

    s = sub.add_parser("scenes", help="показать каталог сцен")
    s.add_argument("--project", default=None)
    s.set_defaults(func=cmd_scenes)

    p = sub.add_parser("plan", help="собрать монтажный план")
    p.add_argument("--project", default=None)
    p.add_argument("--preset", default=None, help="id пресета (см. presets)")
    p.add_argument("--duration", type=int, default=None, help="длительность, сек")
    p.add_argument("--aspect", choices=["9:16", "16:9", "1:1"], default=None)
    p.add_argument("--music", default=None, help="путь к музыкальному файлу")
    p.add_argument("--no-llm", action="store_true", help="без LLM-ранжирования")
    p.set_defaults(func=cmd_plan)

    r = sub.add_parser("render", help="собрать ролик по плану")
    r.add_argument("--project", default=None)
    r.add_argument("--final", action="store_true", help="финальный экспорт (иначе preview)")
    r.set_defaults(func=cmd_render)

    ps = sub.add_parser("presets", help="список пресетов")
    ps.set_defaults(func=cmd_presets)

    pr = sub.add_parser("projects", help="список проектов")
    pr.set_defaults(func=cmd_projects)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
