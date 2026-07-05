"""Preview / Final Renderer (ТЗ §17–18): сборка ролика по монтажному плану.

Каждый сегмент нарезается ffmpeg-ом в единый промежуточный формат
(разрешение целевого аспекта, кроп по центру безопасной области),
затем конкатенация + наложение музыки.

Preview: 540p-эквивалент, veryfast, crf 28 — быстрая проверка черновика.
Final: полное разрешение, medium, crf 18, aac 192k.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import config
from core.models import MontagePlan, Project, Scene
from core.storage import Storage

log = logging.getLogger(__name__)


def render_plan(storage: Storage, project: Project, plan: MontagePlan,
                final: bool = False, progress=print) -> Path | None:
    """Собирает ролик. Возвращает путь к mp4 или None при ошибке."""
    pdir = storage.project_dir(project.id)
    out_dir = pdir / "render"
    tmp_dir = pdir / "cache" / f"render_{plan.id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    w, h = config.ASPECTS[project.aspect]
    if not final:  # preview — половинное разрешение
        w, h = w // 2, h // 2
    quality = ["-preset", "medium", "-crf", "18"] if final \
        else ["-preset", "veryfast", "-crf", "28"]

    # 1. Нарезка сегментов в единый формат
    parts: list[Path] = []
    for seg in plan.segments:
        scene = storage.get_scene(seg.scene_id)
        if not scene:
            log.warning("Сцена %s не найдена, сегмент пропущен", seg.scene_id)
            continue
        part = tmp_dir / f"{seg.order:03d}.mp4"
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},setsar=1,fps=30")
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{seg.src_start:.3f}", "-i", scene.video_path,
            "-t", f"{seg.duration:.3f}",
            "-vf", vf, "-c:v", "libx264", *quality,
            "-an", "-movflags", "+faststart", str(part),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if res.returncode != 0 or not part.exists():
            log.error("Сегмент %s не отрендерился: %s", seg.order, res.stderr[:300])
            continue
        parts.append(part)
        progress(f"  сегмент {seg.order + 1}/{len(plan.segments)} [{seg.slot}] {seg.duration:.1f}s")

    if not parts:
        return None

    # 2. Конкатенация
    concat_list = tmp_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{p}'\n" for p in parts))
    silent = tmp_dir / "video.mp4"
    res = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(concat_list), "-c", "copy", str(silent)],
        capture_output=True, text=True, timeout=600,
    )
    if res.returncode != 0:
        log.error("Конкатенация не удалась: %s", res.stderr[:300])
        return None

    # 3. Музыка: подобранный фрагмент трека (offset из плана) + фейды,
    #    чтобы вступление и финал не обрывались (ТЗ §16)
    suffix = "final" if final else "preview"
    out = out_dir / f"{plan.id}_{suffix}.mp4"
    if project.music_path and Path(project.music_path).exists():
        total = plan.total_duration
        f_in = max(plan.music_fade_in, 0.01)
        f_out = max(plan.music_fade_out, 0.01)
        fade_start = max(total - f_out, 0)
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(silent),
            "-ss", f"{plan.music_offset:.3f}", "-i", project.music_path,
            "-filter_complex",
            (f"[1:a]atrim=0:{total:.3f},"
             f"afade=t=in:st=0:d={f_in:.3f},"
             f"afade=t=out:st={fade_start:.3f}:d={f_out:.3f}[a]"),
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k" if final else "128k",
            "-shortest", str(out),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if res.returncode != 0:
            log.error("Наложение музыки не удалось: %s", res.stderr[:300])
            silent.rename(out)
    else:
        silent.rename(out)

    if final:
        plan.export_path = str(out)
        plan.status = "final"
    else:
        plan.preview_path = str(out)
        plan.status = "rendered"
    storage.save_plan(plan)
    # Временные сегменты больше не нужны — иначе каждый рендер оставляет
    # сотни МБ в cache/render_* (утечка диска)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    progress(f"Рендер готов: {out}")
    return out


def replace_segment(storage: Storage, plan: MontagePlan, segment_id: str,
                    new_scene: Scene, music=None) -> bool:
    """Замена фрагмента (ТЗ §14): обновляет план и пишет историю.

    Если передан анализ музыки — план заново выравнивается по битам
    (иначе после замены склейки уезжают с музыки).
    """
    for seg in plan.segments:
        if seg.id == segment_id:
            old_scene_id = seg.scene_id
            frag_len = min(seg.duration, new_scene.duration)
            pad = max((new_scene.duration - frag_len) / 2, 0)
            seg.scene_id = new_scene.id
            seg.src_start = round(new_scene.start + pad, 3)
            seg.src_end = round(seg.src_start + frag_len, 3)
            seg.reason = "заменено пользователем"
            seg.beat_synced = False
            if music is not None:
                # идемпотентно: уже выровненные сегменты остаются на битах,
                # заменённый подтягивается к ближайшей точке склейки
                from core.montage_planner import _snap_to_beats
                from core.music_selector import shifted_cut_points
                _snap_to_beats(plan, shifted_cut_points(music, plan.music_offset))
            storage.log_replacement(plan.id, seg.id, old_scene_id, new_scene.id)
            plan.status = "draft"
            storage.save_plan(plan)
            return True
    return False
