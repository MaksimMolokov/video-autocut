"""Auto Video Editor V2 — Streamlit UI.

Дизайн перенесён из первого проекта (AI Video Producer): тёмная тема,
акцент #00FF88, wizard-путь. Пользовательский путь — по ТЗ §3:
Материал → Настройки → Анализ → Сцены → Черновик → Экспорт.

Запуск: streamlit run app.py
Слои: UI здесь, вся логика в core/.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

import config
from core.audio_analyzer import analyze_music_cached
from core.media_import import collect_video_files
from core.models import Project
from core.montage_planner import build_plan
from core.pipeline import run_llm_analysis
from core.presets import PRESETS
from core.renderer import render_plan, replace_segment
from core.storage import Storage
from ui_theme import CSS, SLOT_COLORS

st.set_page_config(page_title="Auto Video Editor V2", page_icon="⚡",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)

STEPS = [
    ("material", "Материал"),
    ("settings", "Настройки"),
    ("analysis", "AI Анализ"),
    ("scenes", "Сцены"),
    ("draft", "Черновик"),
    ("export", "Экспорт"),
]
_STEP_IDS = [s[0] for s in STEPS]


@st.cache_resource
def get_storage() -> Storage:
    return Storage()


storage = get_storage()


# ─────────────────────────── helpers ───────────────────────────

def _go(step: str):
    st.session_state["step"] = step
    st.rerun()


def _project() -> Project | None:
    pid = st.session_state.get("project_id")
    return storage.get_project(pid) if pid else None


def _wizard_bar(current: str):
    idx = _STEP_IDS.index(current)
    st.markdown(
        f'<div class="wiz-label"><span class="wiz-title">'
        f'{STEPS[idx][1]}</span><span class="wiz-counter">'
        f'шаг {idx + 1} / {len(STEPS)}</span></div>',
        unsafe_allow_html=True,
    )
    segs = "".join(
        f'<div class="wiz-seg {"done" if i < idx else "active" if i == idx else "todo"}"></div>'
        for i in range(len(STEPS))
    )
    st.markdown(f'<div class="wiz-bar">{segs}</div>', unsafe_allow_html=True)
    # навигация по пройденным шагам
    cols = st.columns(len(STEPS))
    for i, (sid, title) in enumerate(STEPS):
        if i <= idx and sid != current:
            if cols[i].button(f"← {title}", key=f"nav_{sid}"):
                _go(sid)


def _badge(text: str, kind: str = "green"):
    st.markdown(f'<span class="badge b-{kind}">{text}</span>', unsafe_allow_html=True)


def _uploads_dir(project_id: str) -> Path:
    d = storage.project_dir(project_id) / "uploads"
    d.mkdir(exist_ok=True)
    return d


def _size_str(path: Path) -> str:
    if not path.exists():
        return "?"
    gb = path.stat().st_size / 1e9
    return f"{gb:.2f} ГБ" if gb >= 1 else f"{gb * 1000:.0f} МБ"


def _infer_step(p: Project) -> str:
    """При открытии проекта возвращаемся на нужный шаг пути."""
    scenes_exist = bool(storage.list_scenes(p.id))
    plan_exists = storage.latest_plan(p.id) is not None
    if plan_exists:
        return "draft"
    if scenes_exist:
        return "scenes"
    if p.source_paths:
        return "settings"
    return "material"


# ─────────────────────────── HOME: выбор проекта ───────────────────────────

if "project_id" not in st.session_state:
    st.title("⚡ Auto Video Editor V2")
    st.markdown("<p>Сценарный автомонтаж: каталог сцен → черновик → замены → экспорт</p>",
                unsafe_allow_html=True)

    col_new, col_open = st.columns([1, 1])
    with col_new:
        st.markdown("### Новый проект")
        name = st.text_input("Название", placeholder="Океан · Дрон · Январь",
                             key="new_name", label_visibility="collapsed")
        if st.button("Создать проект", type="primary", use_container_width=True):
            p = Project(name=name.strip() or "Без названия")
            storage.save_project(p)
            st.session_state["project_id"] = p.id
            st.session_state["step"] = "material"
            st.rerun()

    def _dir_size(path: Path) -> float:
        """Размер папки в ГБ (быстро, без прав — 0)."""
        try:
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e9
        except OSError:
            return 0.0

    with col_open:
        st.markdown("### Открыть существующий")
        projects = storage.list_projects()
        if not projects:
            st.caption("Проектов пока нет")
        for p in projects[:20]:
            n_scenes = len(storage.list_scenes(p.id))
            pdir = config.PROJECTS_DIR / p.id
            size_gb = _dir_size(pdir)
            c_open, c_clean, c_del = st.columns([5, 1, 1])
            label = f"{p.name} · {p.status} · сцен: {n_scenes} · {size_gb:.1f} ГБ"
            if c_open.button(label, key=f"open_{p.id}", use_container_width=True):
                st.session_state["project_id"] = p.id
                st.session_state["step"] = _infer_step(p)
                st.rerun()
            if c_clean.button("🧹", key=f"clean_{p.id}",
                              help="Очистить кэш (сегменты рендера и ключевые кадры — восстановимы)"):
                from core import worker_lock as _wl
                if _wl.is_running(pdir):
                    st.warning("Идёт анализ — кэш не тронут")
                else:
                    import shutil
                    cache_dir = pdir / "cache"
                    if cache_dir.exists():
                        shutil.rmtree(cache_dir, ignore_errors=True)
                        cache_dir.mkdir(exist_ok=True)
                    st.rerun()
            confirm_key = f"confirm_del_{p.id}"
            if st.session_state.get(confirm_key):
                if c_del.button("❗️ Точно?", key=f"del2_{p.id}",
                                help="Удалит проект, сцены, превью и рендеры БЕЗ ВОЗВРАТА"):
                    storage.delete_project(p.id)
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            else:
                if c_del.button("🗑", key=f"del1_{p.id}", help="Удалить проект"):
                    st.session_state[confirm_key] = True
                    st.rerun()
    st.stop()

project = _project()
if project is None:
    st.session_state.pop("project_id", None)
    st.rerun()

step = st.session_state.get("step", _infer_step(project))

# Шапка проекта
hc1, hc2 = st.columns([5, 1])
hc1.markdown(f"## ⚡ {project.name}")
if hc2.button("⌂ Проекты"):
    st.session_state.pop("project_id", None)
    st.session_state.pop("step", None)
    st.rerun()

_wizard_bar(step)

# ═══════════════════ ШАГ 1: Материал (ТЗ §3.2–3.3, §4) ═══════════════════
if step == "material":
    st.markdown("## Добавить материал")
    st.markdown("<p>Укажите папку с видео или вставьте пути — всё читается прямо с диска. "
                "Выбор сохраняется в проекте.</p>", unsafe_allow_html=True)

    tab_folder, tab_files, tab_upload = st.tabs(
        ["📁  Папка с видео", "🗂  Отдельные файлы", "⬆  Загрузить с компьютера"])

    # TAB 1: папка
    with tab_folder:
        folder_in = st.text_input(
            "Путь к папке", value=st.session_state.get("_folder_input", ""),
            placeholder="/Users/maksimmolokov/VideoProjects/Отпуск",
            key="folder_box", label_visibility="collapsed")
        st.session_state["_folder_input"] = folder_in
        if folder_in:
            fp = Path(folder_in.strip().strip("'\""))
            if fp.is_dir():
                found = collect_video_files([fp])
                if found:
                    _badge(f"✓ Найдено {len(found)} видео")
                    for vp in found[:12]:
                        st.markdown(
                            f'<div style="display:flex;gap:.5rem;padding:.3rem 0;'
                            f'border-bottom:1px solid #1A2228;font-size:.82rem;">'
                            f'<span style="color:#00FF88;">▶</span>'
                            f'<span style="flex:1;">{vp.name}</span>'
                            f'<span style="color:#8A9BAE;">{_size_str(vp)}</span></div>',
                            unsafe_allow_html=True)
                    if st.button("Добавить все видео из папки", use_container_width=True):
                        project.source_paths = [str(fp)]
                        storage.save_project(project)
                        st.rerun()
                else:
                    st.warning("В папке нет поддерживаемых видео")
            else:
                st.error("Папка не найдена")

    # TAB 2: пути списком
    with tab_files:
        paths_text = st.text_area(
            "Пути к файлам", height=140, label_visibility="collapsed",
            value="\n".join(project.source_paths if project.source_paths else []),
            placeholder="/Volumes/SSD/shoot_001.mp4\n/Users/me/drone.mp4")
        if st.button("Проверить и добавить", use_container_width=True, key="add_paths"):
            lines = [l.strip().strip("'\"") for l in paths_text.splitlines() if l.strip()]
            ok = [l for l in lines
                  if Path(l).exists() and (Path(l).is_dir()
                  or Path(l).suffix.lower() in config.VIDEO_EXTENSIONS)]
            bad = [l for l in lines if l not in ok]
            if ok:
                project.source_paths = ok
                storage.save_project(project)
            if bad:
                st.warning("Не найдено: " + ", ".join(Path(b).name for b in bad))
            st.rerun()

    # TAB 3: загрузка через браузер → сохраняем в папку проекта (персистентно)
    with tab_upload:
        st.caption("Файлы сохраняются в папку проекта — при возврате к редактированию они на месте.")
        vids = st.file_uploader("Видео", type=[e[1:] for e in config.VIDEO_EXTENSIONS],
                                accept_multiple_files=True, key="vu")
        mus = st.file_uploader("Музыка", type=[e[1:] for e in config.AUDIO_EXTENSIONS], key="mu")
        if (vids or mus) and st.button("Сохранить загруженные файлы", key="save_up"):
            updir = _uploads_dir(project.id)
            new_paths = list(project.source_paths)
            for f in vids or []:
                dest = updir / f.name
                dest.write_bytes(f.getbuffer())
                if str(dest) not in new_paths:
                    new_paths.append(str(dest))
            project.source_paths = new_paths
            if mus:
                mdest = updir / mus.name
                mdest.write_bytes(mus.getbuffer())
                project.music_path = str(mdest)
            storage.save_project(project)
            st.rerun()

    # Музыка по пути
    st.markdown("<br>**🎵 Музыка** <span style='color:#3B4A59;font-size:.8rem;'>"
                "(файл или папка — трек можно выбрать)</span>", unsafe_allow_html=True)
    music_in = st.text_input("Путь к музыке",
                             value=st.session_state.get("_music_input", project.music_path),
                             placeholder="/Users/me/Music/track.mp3",
                             key="music_box", label_visibility="collapsed")
    st.session_state["_music_input"] = music_in
    if music_in:
        mp = Path(music_in.strip().strip("'\""))
        if mp.is_file() and mp.suffix.lower() in config.AUDIO_EXTENSIONS:
            _badge(f"🎵 {mp.name} · {_size_str(mp)}", "teal")
            if str(mp) != project.music_path and st.button("Использовать этот трек"):
                project.music_path = str(mp)
                storage.save_project(project)
                st.rerun()
        elif mp.is_dir():
            tracks = sorted(f for f in mp.iterdir()
                            if f.suffix.lower() in config.AUDIO_EXTENSIONS)
            if tracks:
                _badge(f"🎵 Найдено {len(tracks)} треков", "teal")
                chosen = st.selectbox("Трек", [t.name for t in tracks],
                                      label_visibility="collapsed")
                if st.button("Использовать выбранный трек"):
                    project.music_path = str(mp / chosen)
                    storage.save_project(project)
                    st.rerun()
        else:
            st.error("Файл/папка не найдены или формат не поддерживается")

    # Сводка и переход
    st.divider()
    videos_now = collect_video_files(project.source_paths) if project.source_paths else []
    s1, s2, s3 = st.columns(3)
    s1.metric("Видео", len(videos_now))
    s2.metric("Музыка", "✓" if project.music_path else "—")
    s3.metric("Объём", f"{sum(v.stat().st_size for v in videos_now) / 1e9:.1f} ГБ"
              if videos_now else "0")
    if project.music_path:
        _badge(f"🎵 {Path(project.music_path).name}", "teal")
    if st.button("Далее: настройки ролика →", type="primary",
                 disabled=not videos_now, use_container_width=True):
        _go("settings")

# ═══════════════════ ШАГ 2: Настройки (ТЗ §3.4–3.6, §5) ═══════════════════
elif step == "settings":
    st.markdown("## Сценарий и формат")
    c1, c2 = st.columns([3, 2])
    with c1:
        preset_ids = list(PRESETS)
        # дефолт — универсальный пресет, а не первый в списке (fpv слишком агрессивен)
        cur = (preset_ids.index(project.preset_id)
               if project.preset_id in preset_ids
               else preset_ids.index("generic"))
        preset_id = st.selectbox("Пресет сценария", preset_ids, index=cur,
                                 format_func=lambda k: PRESETS[k].title)
        st.markdown(f'<div class="ai-explain">{PRESETS[preset_id].idea}</div>',
                    unsafe_allow_html=True)
        scenario = st.text_area("Свой сценарий (опционально, перекрывает пресет)",
                                value=project.scenario_text, height=110,
                                placeholder="Начать с общего вида океана, показать пляж и волны, "
                                            "кульминация — пролёт над водой на закате…")
    with c2:
        aspect = st.radio("Формат кадра", list(config.ASPECTS),
                          index=list(config.ASPECTS).index(project.aspect),
                          horizontal=True,
                          format_func=lambda a: {"9:16": "📱 9:16", "16:9": "🖥 16:9",
                                                 "1:1": "⬛ 1:1"}[a])
        st.caption("Горизонтальные исходники автоматически вписываются в вертикальный "
                   "формат умным кропом — без искажений.")
        duration = st.select_slider("Длительность, сек", [15, 30, 45, 60],
                                    value=project.target_duration
                                    if project.target_duration in (15, 30, 45, 60) else 30)
        sync = st.checkbox("Синхронизация склеек с битами музыки",
                           value=project.sync_to_music)
        stab = st.checkbox("Стабилизировать дёрганые сцены вместо исключения",
                           value=project.stabilize_shaky,
                           help="По умолчанию дёрганое просто не попадает в монтаж. "
                                "Включайте, когда материала мало и жалко терять сцены — "
                                "ffmpeg выровняет тряску (рендер медленнее).")
        speech = st.checkbox("Анализ речи (Whisper): не резать фразы склейками",
                             value=project.analyze_speech,
                             help="Для видео с голосом (семейные, интервью). "
                                  "Видео без аудио пропускаются автоматически.")

    if st.button("Сохранить и перейти к анализу →", type="primary", use_container_width=True):
        project.preset_id = preset_id
        project.scenario_text = scenario.strip()
        project.aspect = aspect
        project.target_duration = duration
        project.sync_to_music = sync
        project.stabilize_shaky = stab
        project.analyze_speech = speech
        storage.save_project(project)
        _go("analysis")

# ═══════════════════ ШАГ 3: Анализ (ТЗ §3.7, §7–8, §16) ═══════════════════
elif step == "analysis":
    st.markdown("## AI-анализ материала")
    scenes = storage.list_scenes(project.id)
    n_done = sum(1 for s in scenes if s.llm_status == "done")

    if scenes:
        st.markdown('<div class="stat-grid">'
                    f'<div class="stat-box"><div class="stat-val">{len(scenes)}</div>'
                    f'<div class="stat-lbl">сцен найдено</div></div>'
                    f'<div class="stat-box"><div class="stat-val">{n_done}</div>'
                    f'<div class="stat-lbl">описано ИИ</div></div>'
                    '</div>', unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    with_llm = st.checkbox("Смысловой анализ кадров (Qwen3-VL 8B через LM Studio)", True,
                           help="Нужен запущенный LM Studio. Можно дозаполнить позже.")

    # ошибка последнего запуска воркера (статус сброшен, сообщение осталось)
    if project.status != "analyzing" and project.analysis_progress.startswith("Ошибка"):
        st.error(project.analysis_progress)

    # ── Фоновый воркер: UI не блокируется, прогресс читается из БД ──
    from core import worker_lock
    pdir = storage.project_dir(project.id)
    worker_alive = worker_lock.is_running(pdir)

    if project.status == "analyzing" and not worker_alive:
        # воркер умер (краш/kill), а статус остался — честно сообщаем
        st.error("Воркер анализа умер, не завершив работу. Последний статус: "
                 f"«{project.analysis_progress}»")
        log_path = pdir / "cache" / "worker.log"
        if log_path.exists():
            tail = log_path.read_text(errors="ignore").splitlines()[-15:]
            with st.expander("Хвост лога воркера"):
                st.code("\n".join(tail))
        if st.button("Сбросить статус и продолжить"):
            project.status = "new" if not storage.list_scenes(project.id) else "analyzed"
            project.analysis_progress = ""
            storage.save_project(project)
            st.rerun()
    elif project.status == "analyzing":
        st.markdown(
            f'<div class="ai-explain">Анализ идёт в фоне — вкладку можно '
            f'закрывать, прогресс не потеряется.<br><b>'
            f'{project.analysis_progress or "запуск…"}</b></div>',
            unsafe_allow_html=True)
        st.progress(min(len(storage.list_scenes(project.id)) % 100 / 100 + 0.05, 0.95))
        import time
        time.sleep(2)
        st.rerun()

    cA, cB = st.columns(2)
    if cA.button("🔍 Запустить анализ видео", type="primary", use_container_width=True,
                 disabled=worker_alive,
                 help="Анализ уже идёт" if worker_alive else None):
        import subprocess
        import sys as _sys
        cmd = [_sys.executable, "cli.py", "analyze-project", "--project", project.id]
        if not with_llm:
            cmd.append("--no-llm")
        log_path = pdir / "cache" / "worker.log"
        with open(log_path, "ab") as logf:
            subprocess.Popen(cmd, cwd=str(config.BASE_DIR),
                             stdout=logf, stderr=logf, start_new_session=True)
        project.status = "analyzing"
        project.analysis_progress = "запуск воркера…"
        storage.save_project(project)
        import time
        time.sleep(1)  # даём воркеру захватить lock до первого rerun
        st.rerun()

    pending = [s for s in scenes if s.llm_status in ("pending", "failed")]
    if pending and cB.button(f"🧠 Дозаполнить описания ({len(pending)})",
                             use_container_width=True):
        box = st.status("LLM-анализ…", expanded=True)
        run_llm_analysis(storage, project, progress=box.write)
        box.update(label="Готово", state="complete")
        st.rerun()

    # Музыка — ИИ-анализ трека
    if project.music_path and Path(project.music_path).exists():
        st.divider()
        st.markdown("### 🎵 Анализ музыки")
        if st.button("Проанализировать трек"):
            with st.spinner("Темп, биты, энергетика…"):
                m = analyze_music_cached(storage, project.music_path)
                st.session_state["music_info"] = {
                    "bpm": m.bpm, "duration": m.duration,
                    "beats": len(m.beats), "climax": m.climax_time,
                    "calm": m.calm_ranges[:3], "energetic": m.energetic_ranges[:3],
                }
        mi = st.session_state.get("music_info")
        if mi:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("BPM", mi["bpm"])
            m2.metric("Длительность", f"{mi['duration']:.0f}s")
            m3.metric("Битов", mi["beats"])
            m4.metric("Кульминация", f"{mi['climax']:.0f}s")
            st.markdown('<div class="ai-explain">Под сценарий будет выбран правильный '
                        'фрагмент трека: спокойный вход, энергия к кульминации, '
                        'плавные фейды на вступлении и финале.</div>',
                        unsafe_allow_html=True)

    if scenes and st.button("К каталогу сцен →", use_container_width=True):
        _go("scenes")

# ═══════════════════ ШАГ 4: Каталог сцен (ТЗ §10, §15) ═══════════════════
elif step == "scenes":
    scenes = storage.list_scenes(project.id)
    st.markdown(f"## Каталог сцен · {len(scenes)}")
    if not scenes:
        st.info("Сцен нет — вернитесь к шагу анализа")
    else:
        plan_now = storage.latest_plan(project.id)
        used_ids = {seg.scene_id for seg in plan_now.segments} if plan_now else set()

        f1, f2, f3 = st.columns(3)
        f_type = f1.multiselect("Тип сцены",
                                sorted({s.scene_type for s in scenes if s.scene_type}))
        f_minq = f2.slider("Мин. качество", 0.0, 1.0, 0.0, 0.05)
        f_sort = f3.selectbox("Сортировка", ["по порядку", "по качеству", "по эстетике"])

        shown = [s for s in scenes if s.quality_score >= f_minq
                 and (not f_type or s.scene_type in f_type)]
        if f_sort == "по качеству":
            shown.sort(key=lambda s: -s.quality_score)
        elif f_sort == "по эстетике":
            shown.sort(key=lambda s: -s.aesthetic_score)

        for row in range(0, len(shown), 3):
            cols = st.columns(3)
            for col, sc in zip(cols, shown[row:row + 3]):
                flag_cls = {"pinned": "pinned", "banned": "excluded",
                            "bad": "excluded"}.get(sc.user_flag, "")
                sel_cls = "selected" if sc.id in used_ids else ""
                with col:
                    with st.container(border=True):
                        if sc.thumbnail_path and Path(sc.thumbnail_path).exists():
                            st.image(sc.thumbnail_path, use_container_width=True)
                        badges = []
                        if sc.id in used_ids:
                            badges.append('<span class="badge b-green">в черновике</span>')
                        if sc.scene_type:
                            badges.append(f'<span class="badge b-purple">{sc.scene_type}</span>')
                        fl = {"good": ("👍", "green"), "bad": ("👎", "red"),
                              "banned": ("🚫", "red"), "pinned": ("📌", "teal")}.get(sc.user_flag)
                        if fl:
                            badges.append(f'<span class="badge b-{fl[1]}">{fl[0]}</span>')
                        st.markdown(" ".join(badges), unsafe_allow_html=True)
                        st.markdown(
                            f"`{sc.start:.1f}–{sc.end:.1f}s` · {sc.duration:.1f}s · "
                            f"q={sc.quality_score:.2f} · ✨{sc.aesthetic_score:.2f} · "
                            f"{sc.motion}/{sc.motion_type}")
                        if sc.description:
                            st.caption(sc.description[:130])
                        with st.expander("▶️ Превью и действия"):
                            if sc.preview_path and Path(sc.preview_path).exists():
                                st.video(sc.preview_path)
                            st.caption(f"Источник: {Path(sc.video_path).name}")
                            if sc.tags:
                                st.caption("🏷 " + ", ".join(sc.tags[:8]))
                            b = st.columns(4)
                            for btn, (icon, flag) in zip(
                                    b, [("👍", "good"), ("👎", "bad"),
                                        ("🚫", "banned"), ("📌", "pinned")]):
                                if btn.button(icon, key=f"fl_{flag}_{sc.id}"):
                                    sc.user_flag = "" if sc.user_flag == flag else flag
                                    storage.save_scene(sc)
                                    st.rerun()

        st.divider()
        if st.button("Сгенерировать черновик →", type="primary", use_container_width=True):
            _go("draft")

# ═══════════════════ ШАГ 5: Черновик и таймлайн (ТЗ §11–15) ═══════════════════
elif step == "draft":
    st.markdown("## Черновик")
    scenes = storage.list_scenes(project.id)
    ready = [s for s in scenes if s.user_flag != "banned"]
    plan = storage.latest_plan(project.id)

    def _rebuild(variant: int):
        with st.spinner("Монтажный план…"):
            music = None
            if project.music_path and Path(project.music_path).exists():
                music = analyze_music_cached(storage, project.music_path)
            new_plan = build_plan(project, ready, music,
                                  use_llm=use_llm_rank, variant=variant)
            storage.save_plan(new_plan)
        with st.spinner("Рендер preview…"):
            render_plan(storage, project, new_plan, final=False, progress=lambda m: None)
        st.rerun()

    cbtn, cvid = st.columns([1, 2])
    with cbtn:
        use_llm_rank = st.checkbox("LLM-ранжирование сцен", True)
        label = "🎬 Пересобрать черновик" if plan else "🎬 Сгенерировать черновик"
        if st.button(label, type="primary", use_container_width=True, disabled=not ready):
            st.session_state["plan_variant"] = 0
            _rebuild(0)
        if plan and st.button("🎲 Другой вариант", use_container_width=True,
                              disabled=not ready,
                              help="Пересоберёт черновик из других сцен-кандидатов"):
            v = st.session_state.get("plan_variant", 0) + 1
            st.session_state["plan_variant"] = v
            _rebuild(v)
        if plan and project.music_path:
            st.markdown(
                f'<div class="ai-explain">Музыка: фрагмент с {plan.music_offset:.0f}s, '
                f'fade-in {plan.music_fade_in:.1f}s, fade-out {plan.music_fade_out:.1f}s</div>',
                unsafe_allow_html=True)
    with cvid:
        if plan and plan.preview_path and Path(plan.preview_path).exists():
            st.video(plan.preview_path)

    if plan:
        # ── Визуальный таймлайн в стиле первого проекта ──
        st.markdown(f"### Таймлайн · {plan.total_duration:.1f}s")
        total = max(plan.total_duration, 0.1)
        segs_html = ""
        for seg in plan.segments:
            w = max(seg.duration / total * 100, 3)
            color = SLOT_COLORS.get(seg.slot, "#8A9BAE")
            beat = " ♪" if seg.beat_synced else ""
            segs_html += (
                f'<div class="tl-seg" style="width:{w:.1f}%;background:{color};" '
                f'title="{seg.slot} · {seg.duration:.1f}s">'
                f'<span>{seg.slot}{beat}</span>'
                f'<span class="tl-seg-dur">{seg.duration:.1f}s</span></div>')
        audio_row = ('<div class="tl-track-label">Audio</div>'
                     '<div class="tl-audio-row"><div class="tl-audio-wave"></div></div>'
                     ) if project.music_path else ""
        st.markdown(
            f'<div class="tl-wrap">{audio_row}'
            f'<div class="tl-track-label">Video</div>'
            f'<div class="tl-video-row">{segs_html}</div></div>',
            unsafe_allow_html=True)

        # Миниатюры сегментов
        tl_cols = st.columns([max(seg.duration, 0.5) for seg in plan.segments])
        for col, seg in zip(tl_cols, plan.segments):
            sc = storage.get_scene(seg.scene_id)
            with col:
                if sc and sc.thumbnail_path and Path(sc.thumbnail_path).exists():
                    st.image(sc.thumbnail_path, use_container_width=True)
                st.caption(f"#{seg.order + 1} · {seg.reason[:42]}")

        # ── Замена фрагмента (ТЗ §14) ──
        st.divider()
        st.markdown("### Замена фрагмента")
        seg_map = {f"#{s.order + 1} [{s.slot}] {s.duration:.1f}s": s for s in plan.segments}
        sel = st.selectbox("Фрагмент", list(seg_map))
        seg = seg_map[sel]
        cur = storage.get_scene(seg.scene_id)
        cL, cR = st.columns(2)
        with cL:
            st.markdown("**Сейчас:**")
            if cur:
                if cur.preview_path and Path(cur.preview_path).exists():
                    st.video(cur.preview_path)
                st.caption(f"{cur.description[:110]}")
                st.markdown(f'<div class="ai-explain">{seg.reason}</div>',
                            unsafe_allow_html=True)
        with cR:
            st.markdown("**Альтернативы (то же место сценария):**")
            used_now = {s.scene_id for s in plan.segments}
            alt_ids = [i for i in plan.alternatives.get(seg.slot, []) if i not in used_now]
            extras = [s.id for s in ready
                      if s.id not in used_now and s.id not in alt_ids
                      and (s.recommended_slot == seg.slot
                           or (cur and s.scene_type == cur.scene_type))]
            shown_any = False
            for aid in (alt_ids + extras)[:4]:
                alt = storage.get_scene(aid)
                if not alt:
                    continue
                shown_any = True
                with st.container(border=True):
                    i1, i2 = st.columns([1, 2])
                    if alt.thumbnail_path and Path(alt.thumbnail_path).exists():
                        i1.image(alt.thumbnail_path)
                    i2.caption(f"{alt.scene_type} · q={alt.quality_score:.2f} · "
                               f"✨{alt.aesthetic_score:.2f}\n\n{alt.description[:80]}")
                    if i2.button("Заменить", key=f"rep_{seg.id}_{alt.id}"):
                        music_for_sync = None
                        if project.music_path and Path(project.music_path).exists():
                            music_for_sync = analyze_music_cached(storage, project.music_path)
                        replace_segment(storage, plan, seg.id, alt, music=music_for_sync)
                        with st.spinner("Пересборка preview…"):
                            render_plan(storage, project, plan, final=False,
                                        progress=lambda m: None)
                        st.rerun()
            if not shown_any:
                st.caption("Подходящих альтернатив нет — все сцены использованы")

        st.divider()
        if st.button("К экспорту →", type="primary", use_container_width=True):
            _go("export")

# ═══════════════════ ШАГ 6: Экспорт (ТЗ §17–18) ═══════════════════
elif step == "export":
    st.markdown("## Финальный экспорт")
    plan = storage.latest_plan(project.id)
    if not plan:
        st.info("Сначала сгенерируйте черновик")
    else:
        e1, e2, e3 = st.columns(3)
        e1.metric("Длительность", f"{plan.total_duration:.1f}s")
        e2.metric("Формат", project.aspect)
        e3.metric("Фрагментов", len(plan.segments))

        # Предпросмотр кадрирования (ТЗ §17.5): рамка окна кропа на миниатюрах
        with st.expander("🖼 Проверить кадрирование перед экспортом"):
            from PIL import Image, ImageDraw

            from core.smart_crop import crop_rect_norm
            tw, th = config.ASPECTS[project.aspect]
            cols_per_row = 4
            segs = plan.segments
            for row in range(0, len(segs), cols_per_row):
                cols = st.columns(cols_per_row)
                for col, seg in zip(cols, segs[row:row + cols_per_row]):
                    sc = storage.get_scene(seg.scene_id)
                    if not (sc and sc.thumbnail_path and Path(sc.thumbnail_path).exists()):
                        continue
                    img = Image.open(sc.thumbnail_path).convert("RGB")
                    iw, ih = img.size
                    focus = (None if (sc.subject_x, sc.subject_y) == (0.5, 0.5)
                             else (sc.subject_x, sc.subject_y))
                    x0, y0, x1, y1 = crop_rect_norm(iw, ih, tw, th, focus)
                    d = ImageDraw.Draw(img, "RGBA")
                    # затемняем то, что будет отрезано
                    d.rectangle([0, 0, iw, ih], fill=(0, 0, 0, 110))
                    d.rectangle([x0 * iw, y0 * ih, x1 * iw, y1 * ih],
                                fill=(0, 0, 0, 0), outline=(0, 255, 136), width=3)
                    crop_img = Image.open(sc.thumbnail_path).convert("RGB").crop(
                        (int(x0 * iw), int(y0 * ih), int(x1 * iw), int(y1 * ih)))
                    img.paste(crop_img, (int(x0 * iw), int(y0 * ih)))
                    d2 = ImageDraw.Draw(img)
                    d2.rectangle([x0 * iw, y0 * ih, x1 * iw, y1 * ih],
                                 outline=(0, 255, 136), width=3)
                    with col:
                        st.image(img, use_container_width=True,
                                 caption=f"#{seg.order + 1} {seg.slot}"
                                         + (" 🎯" if focus else ""))
        if st.button("📦 Экспортировать mp4", type="primary", use_container_width=True):
            box = st.status("Финальный рендер…", expanded=True)
            out = render_plan(storage, project, plan, final=True, progress=box.write)
            box.update(label="Готово" if out else "Ошибка рендера",
                       state="complete" if out else "error")
            if out:
                st.rerun()
        if plan.export_path and Path(plan.export_path).exists():
            st.success(f"`{plan.export_path}`")
            # плеер по центру, не на всю ширину — видео помещается на экран
            _, vcol, _ = st.columns([1, 2, 1])
            with vcol:
                st.video(plan.export_path)
            # файл отдаётся потоком (open), а не читается целиком в память
            with open(plan.export_path, "rb") as fh:
                st.download_button(
                    "⬇️ Скачать mp4", data=fh,
                    file_name=f"{project.name}_{project.aspect.replace(':', 'x')}.mp4",
                    mime="video/mp4", use_container_width=True)
