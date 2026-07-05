"""Preview / Final Renderer (ТЗ §17–18): сборка ролика по монтажному плану.

Каждый сегмент нарезается ffmpeg-ом в единый формат: умный кроп в
координатах исходника (окно смещается к лицам — ТЗ §17 «не обрезать лица»),
затем масштаб, конкатенация и наложение музыки.

Сегменты кэшируются в cache/segments/ по содержимому (сцена + таймкоды +
формат + кроп) — замена одного фрагмента пере-кодирует только его.

Preview: половинное разрешение, veryfast, crf 28. Final: medium, crf 18.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

import config
from core.models import MontagePlan, Project, Scene
from core.smart_crop import crop_window, find_focus
from core.storage import Storage

log = logging.getLogger(__name__)

_SEGMENT_CACHE_MAX_BYTES = 3 * 1024 ** 3  # LRU-лимит кэша сегментов


def _display_dims(storage: Storage, scene: Scene) -> tuple[int, int]:
    """Размер кадра исходника с учётом поворота (для расчёта окна кропа)."""
    video = storage.get_video(scene.video_id)
    if video and video.width and video.height:
        w, h = video.width, video.height
        # orientation уже учитывает метаданные поворота (ffprobe side_data)
        if video.orientation == "vertical" and w > h:
            w, h = h, w
        elif video.orientation == "horizontal" and h > w:
            w, h = h, w
        return w, h
    # запись видео недоступна — быстрый пробник
    import cv2
    cap = cv2.VideoCapture(scene.video_path)
    try:
        return (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920,
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080)
    finally:
        cap.release()


def _segment_focus(scene: Scene, seg) -> tuple[float, float] | None:
    """Центр внимания для кропа, каскад (ТЗ §17 «не обрезать лица»):
    1. CV-детекция лиц/силуэтов на кадрах сегмента,
    2. позиция главного объекта от Qwen3-VL (subject_x/y из анализа сцены),
    3. None → безопасный центральный кроп.
    """
    if seg.crop == "center":
        return None
    focus = find_focus(scene.video_path, seg.src_start, seg.src_end)
    if focus:
        return focus
    if (scene.subject_x, scene.subject_y) != (0.5, 0.5):
        return (scene.subject_x, scene.subject_y)
    return None


def _trim_segment_cache(cache_dir: Path):
    """LRU: старейшие сегменты удаляются при превышении лимита."""
    files = sorted(cache_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    while total > _SEGMENT_CACHE_MAX_BYTES and files:
        oldest = files.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink(missing_ok=True)


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

    seg_cache = pdir / "cache" / "segments"
    seg_cache.mkdir(parents=True, exist_ok=True)

    # 1. Нарезка сегментов: умный кроп + пофрагментный кэш
    parts: list[Path] = []
    part_durs: list[float] = []
    for seg in plan.segments:
        scene = storage.get_scene(seg.scene_id)
        if not scene:
            log.warning("Сцена %s не найдена, сегмент пропущен", seg.scene_id)
            continue

        src_w, src_h = _display_dims(storage, scene)
        focus = _segment_focus(scene, seg)
        cw, ch, x, y = crop_window(src_w, src_h, w, h, focus)

        key = hashlib.md5(
            f"{seg.scene_id}:{seg.src_start:.3f}:{seg.src_end:.3f}:"
            f"{w}x{h}:{'f' if final else 'p'}:{cw}x{ch}+{x}+{y}".encode()
        ).hexdigest()[:16]
        part = seg_cache / f"{key}.mp4"

        if part.exists():
            part.touch()  # обновляем mtime для LRU
            parts.append(part)
            part_durs.append(seg.duration)
            progress(f"  сегмент {seg.order + 1}/{len(plan.segments)} [{seg.slot}] из кэша")
            continue

        vf = f"crop={cw}:{ch}:{x}:{y},scale={w}:{h},setsar=1,fps=30"
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
            progress(f"  ⚠️ сегмент {seg.order + 1} пропущен (ошибка ffmpeg) — ролик будет короче")
            continue
        parts.append(part)
        part_durs.append(seg.duration)
        face_note = " 👤" if focus else ""
        progress(f"  сегмент {seg.order + 1}/{len(plan.segments)} [{seg.slot}] "
                 f"{seg.duration:.1f}s{face_note}")

    if not parts:
        return None

    # 2. Сборка: crossfade-цепочка (xfade) или жёсткая конкатенация
    silent = tmp_dir / "video.mp4"
    fade_d = plan.transition_duration
    use_xfade = plan.transition == "crossfade" and fade_d > 0 and len(parts) > 1
    if use_xfade:
        progress(f"  склейка crossfade {fade_d:.1f}s…")
        inputs: list[str] = []
        for p in parts:
            inputs += ["-i", str(p)]
        filters, prev, offset = [], "[0:v]", 0.0
        for k in range(1, len(parts)):
            offset += part_durs[k - 1] - fade_d
            outlbl = f"[v{k}]"
            filters.append(f"{prev}[{k}:v]xfade=transition=fade:"
                           f"duration={fade_d:.3f}:offset={offset:.3f}{outlbl}")
            prev = outlbl
        res = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", *inputs,
             "-filter_complex", ";".join(filters), "-map", prev,
             "-c:v", "libx264", *quality, "-movflags", "+faststart", str(silent)],
            capture_output=True, text=True, timeout=900,
        )
        rendered_total = sum(part_durs) - (len(parts) - 1) * fade_d
    else:
        concat_list = tmp_dir / "concat.txt"
        concat_list.write_text("".join(f"file '{p}'\n" for p in parts))
        res = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(silent)],
            capture_output=True, text=True, timeout=600,
        )
        rendered_total = sum(part_durs)
    if res.returncode != 0:
        log.error("Сборка не удалась: %s", res.stderr[:300])
        return None

    # 3. Музыка: подобранный фрагмент трека (offset из плана) + фейды,
    #    чтобы вступление и финал не обрывались (ТЗ §16)
    suffix = "final" if final else "preview"
    out = out_dir / f"{plan.id}_{suffix}.mp4"
    if project.music_path and Path(project.music_path).exists():
        total = rendered_total  # фактическая длительность (учтён crossfade)
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
    # concat-времянка не нужна; кэш сегментов живёт с LRU-лимитом
    shutil.rmtree(tmp_dir, ignore_errors=True)
    _trim_segment_cache(seg_cache)
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
                _snap_to_beats(plan, shifted_cut_points(music, plan.music_offset),
                               overlap=plan.transition_duration)
            storage.log_replacement(plan.id, seg.id, old_scene_id, new_scene.id)
            plan.status = "draft"
            storage.save_plan(plan)
            return True
    return False
