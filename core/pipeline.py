"""Пайплайн анализа (ТЗ §7, §24 п.2): исходники → каталог сцен.

Порядок: импорт → теханализ (ffprobe) → детекция сцен (PySceneDetect) →
качество/движение (OpenCV) → превью (ffmpeg) → смысловой анализ (Qwen3-VL 8B).

LLM-этап отделён: если LM Studio недоступен, каталог всё равно создаётся,
сцены остаются llm_status=pending и дозаполняются командой `cli.py llm`.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import config
from core import media_import, previews, scene_detector, video_analyzer
from core.frame_quality import analyze_scene_quality
from core.llm_analyzer import LLMAnalyzer
from core.models import Project, Scene
from core.storage import Storage

log = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]


def analyze_project(storage: Storage, project: Project,
                    progress: ProgressCb = print, run_llm: bool = True) -> list[Scene]:
    """Полный анализ исходников проекта. Возвращает список сцен.

    Каждое сообщение прогресса дублируется в project.analysis_progress —
    фоновый воркер и UI видят один и тот же живой статус через БД.
    """
    user_progress = progress

    def progress(msg: str):  # noqa: ANN001 — обёртка с побочным эффектом
        user_progress(msg)
        project.analysis_progress = msg
        storage.save_project(project)

    project.status = "analyzing"
    storage.save_project(project)
    pdir = storage.project_dir(project.id)

    # 1. Импорт
    files = media_import.collect_video_files(project.source_paths)
    if not files:
        raise ValueError(f"Видеофайлы не найдены в: {project.source_paths}")
    progress(f"Найдено видеофайлов: {len(files)}")

    # Кэш: файлы, уже проанализированные в этом проекте (по отпечатку),
    # не пересчитываются — повторный запуск анализа почти мгновенный
    existing = storage.list_videos(project.id)
    known = {v.file_hash: v for v in existing if v.file_hash}

    all_scenes: list[Scene] = []
    for i, f in enumerate(files, 1):
        fp = media_import.file_fingerprint(f)
        cached = known.get(fp)
        if cached and storage.list_scenes_by_video(cached.id):
            progress(f"[{i}/{len(files)}] {f.name}: уже проанализирован — из кэша")
            continue

        # Файл изменился или анализируется заново — все старые записи этого
        # пути удаляются, иначе сцены задваиваются
        for old in existing:
            if old.path == str(f):
                storage.delete_video(old.id)

        progress(f"[{i}/{len(files)}] {f.name}: технический анализ…")
        # 2. Теханализ
        video = video_analyzer.probe_video(project.id, f)
        video.file_hash = fp
        storage.save_video(video)
        if not video.valid:
            progress(f"  ⚠️ пропущен ({video.error})")
            continue

        # 3. Детекция сцен
        progress(f"  детекция сцен ({video.duration:.1f}s)…")
        ranges = scene_detector.detect_scenes(f, video.duration)
        progress(f"  найдено сцен: {len(ranges)}")

        # 4. Качество + превью
        for start, end in ranges:
            q = analyze_scene_quality(str(f), start, end)
            if q.quality_score < config.QUALITY_REJECT_THRESHOLD:
                continue  # брак: темно/мыло/хаос (ТЗ §7.2 «исключение плохих участков»)
            scene = Scene(
                project_id=project.id, video_id=video.id, video_path=str(f),
                start=start, end=end,
                quality_score=q.quality_score, stability_score=q.stability_score,
                sharpness=q.sharpness, brightness=q.brightness,
                motion=q.motion, motion_type=q.motion_type, jerkiness=q.jerkiness,
            )
            if q.motion_type == "shake":
                scene.tags.append("jerky")  # дёрганая камера — маркер для каталога
            thumb = pdir / "thumbnails" / f"{scene.id}.jpg"
            clip = pdir / "previews" / f"{scene.id}.mp4"
            key_t = q.keyframes[0]
            if previews.make_thumbnail(str(f), key_t, thumb):
                scene.thumbnail_path = str(thumb)
            if previews.make_preview_clip(str(f), start, end, clip):
                scene.preview_path = str(clip)
            # кадры для LLM кэшируем сразу — пригодятся и при отложенном прогоне;
            # длинная сцена (≥12с) получает второй кадр: модель видит развитие
            frame = pdir / "cache" / f"{scene.id}_key.jpg"
            previews.extract_frame(str(f), key_t, frame)
            if scene.duration >= 12 and len(q.keyframes) > 1:
                frame2 = pdir / "cache" / f"{scene.id}_key2.jpg"
                previews.extract_frame(str(f), q.keyframes[-1], frame2)
            all_scenes.append(scene)

        storage.save_scenes(all_scenes)

    total = len(storage.list_scenes(project.id))
    progress(f"Каталог сцен: {total} (новых {len(all_scenes)}, после отсева брака)")

    # 5. Смысловой анализ LLM
    if run_llm:
        run_llm_analysis(storage, project, progress)

    project.status = "analyzed"
    project.analysis_progress = ""
    storage.save_project(project)
    return storage.list_scenes(project.id)


def run_llm_analysis(storage: Storage, project: Project,
                     progress: ProgressCb = print) -> int:
    """Дозаполняет LLM-поля всех pending-сцен проекта. Возвращает число обработанных."""
    llm = LLMAnalyzer()
    if not llm.is_available():
        progress("⚠️ LM Studio недоступен (localhost:1234) или vision-модель не загружена. "
                 "Смысловой анализ отложен: запусти LM Studio с Qwen3-VL 8B и выполни `python3 cli.py llm`.")
        return 0

    pdir = storage.project_dir(project.id)
    pending = storage.list_scenes(project.id, llm_status="pending") \
        + storage.list_scenes(project.id, llm_status="failed")
    progress(f"LLM-анализ ({llm.model}): {len(pending)} сцен…")
    done = 0
    for n, scene in enumerate(pending, 1):
        frame = pdir / "cache" / f"{scene.id}_key.jpg"
        if not frame.exists():
            mid = scene.start + scene.duration / 2
            if not previews.extract_frame(scene.video_path, mid, frame):
                scene.llm_status = "failed"
                storage.save_scene(scene)
                continue
        frames: list = [frame]
        frame2 = pdir / "cache" / f"{scene.id}_key2.jpg"
        if frame2.exists():
            frames.append(frame2)
        if llm.fill_scene(scene, frames):
            done += 1
            progress(f"  [{n}/{len(pending)}] {scene.scene_type or '?'} — "
                     f"{scene.description[:60]}…")
        storage.save_scene(scene)
    progress(f"LLM-анализ завершён: {done}/{len(pending)}")
    return done
