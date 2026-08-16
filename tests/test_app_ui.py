"""UI-автотесты пользовательского пути (Streamlit AppTest, без браузера).

Полный путь по ТЗ §3: Проекты → Материал → Настройки → AI Анализ → Сцены →
Черновик → Экспорт. Проверяются кнопки, навигация, реальный рендер и
отсутствие исключений; default_timeout ловит зависания скрипта.

LM Studio не требуется: анализ идёт с run_llm=False, ранжирование выключается
чекбоксом — как у пользователя без запущенной модели.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import config
from core.storage import Storage

APP = str(Path(__file__).parent.parent / "app.py")
TIMEOUT = 300  # сек на один прогон скрипта: включает реальные ffmpeg-рендеры


@pytest.fixture(scope="module")
def ui_projects_dir(tmp_path_factory):
    """Одна временная папка проектов на весь модуль: get_storage() в app.py
    кэшируется st.cache_resource и должен весь модуль указывать сюда."""
    import streamlit as st
    old = config.PROJECTS_DIR
    config.PROJECTS_DIR = tmp_path_factory.mktemp("ui_projects")
    st.cache_resource.clear()
    yield config.PROJECTS_DIR
    st.cache_resource.clear()
    config.PROJECTS_DIR = old


@pytest.fixture(scope="module")
def ui_storage(ui_projects_dir) -> Storage:
    s = Storage()  # то же app.db, что и у приложения (WAL)
    yield s
    s.close()


@pytest.fixture(scope="module")
def source_dir(ui_projects_dir, tmp_path_factory, synthetic_video) -> Path:
    """Папка-источник ровно с одним видео (media_dir содержит лишние файлы)."""
    d = tmp_path_factory.mktemp("ui_source")
    shutil.copy(synthetic_video, d / "clip.mp4")
    return d


def _run(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, f"необработанное исключение в UI: {at.exception}"
    return at


def _reopen(at: AppTest) -> AppTest:
    """Свежий AppTest после перехода на другой шаг мастера.

    Известный глюк AppTest: виджеты страницы, покинутой через st.rerun(),
    остаются в дереве теста, но их ключи уже вычищены из session_state —
    следующий at.run() падает KeyError. Пересоздаём тест, перенося
    навигационное состояние (так же стартует и реальная сессия браузера)."""
    nt = AppTest.from_file(APP, default_timeout=TIMEOUT)
    for k in ("project_id", "step", "plan_variant"):
        try:
            nt.session_state[k] = at.session_state[k]
        except KeyError:
            pass
    return _run(nt)


def _button(at: AppTest, label_part: str):
    hits = [b for b in at.button if label_part in b.label]
    assert hits, (f"кнопка «{label_part}» не найдена; есть: "
                  f"{[b.label for b in at.button]}")
    return hits[0]


def _checkbox(at: AppTest, label_part: str):
    hits = [c for c in at.checkbox if label_part in c.label]
    assert hits, f"чекбокс «{label_part}» не найден"
    return hits[0]


def test_home_screen_renders(ui_storage):
    """Домашний экран открывается без ошибок и предлагает создать проект."""
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    _run(at)
    assert at.title and "Auto Video Editor" in at.title[0].value
    _button(at, "Создать проект")


def test_full_user_path(ui_storage, source_dir):
    """Сквозной путь: создание проекта → материал → настройки → анализ →
    каталог сцен (пометки) → черновик (сборка + preview) → экспорт (final)."""
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    _run(at)

    # ── Шаг 0: создать проект ──
    at.text_input(key="new_name").set_value("UI сквозной путь")
    _button(at, "Создать проект").click()
    _run(at)
    pid = at.session_state["project_id"]
    assert at.session_state["step"] == "material"
    at = _reopen(at)

    # ── Шаг 1: материал — папка с видео ──
    at.text_input(key="folder_box").set_value(str(source_dir))
    _run(at)  # показывается список найденных видео
    _button(at, "Добавить все видео из папки").click()
    _run(at)
    assert ui_storage.get_project(pid).source_paths == [str(source_dir)]
    _button(at, "Далее: настройки ролика").click()
    _run(at)
    assert at.session_state["step"] == "settings"
    at = _reopen(at)

    # ── Шаг 2: настройки — сохранить и перейти к анализу ──
    _button(at, "Сохранить и перейти к анализу").click()
    _run(at)
    assert at.session_state["step"] == "analysis"
    at = _reopen(at)
    project = ui_storage.get_project(pid)
    assert project.preset_id and project.aspect == "9:16"

    # ── Шаг 3: анализ. Кнопка запускает фоновый воркер-subprocess;
    # в тесте гоняем пайплайн синхронно (тот же код, что и воркер) ──
    _button(at, "Запустить анализ видео")  # кнопка на месте и активна
    from core.pipeline import analyze_project
    scenes = analyze_project(ui_storage, project,
                             progress=lambda m: None, run_llm=False)
    assert scenes, "анализ не нашёл ни одной сцены"
    at = _reopen(at)  # страница перечитала статус: сцены найдены
    _button(at, "К каталогу сцен").click()
    _run(at)
    assert at.session_state["step"] == "scenes"
    at = _reopen(at)

    # ── Шаг 4: каталог — карточки и кнопки-пометки ──
    first = ui_storage.list_scenes(pid)[0]
    at.button(key=f"fl_good_{first.id}").click()
    _run(at)
    assert ui_storage.get_scene(first.id).user_flag == "good"
    # повторный клик снимает пометку
    at.button(key=f"fl_good_{first.id}").click()
    _run(at)
    assert ui_storage.get_scene(first.id).user_flag == ""
    _button(at, "Сгенерировать черновик").click()
    _run(at)
    assert at.session_state["step"] == "draft"
    at = _reopen(at)

    # ── Шаг 5: черновик — сборка плана и реальный preview-рендер ──
    _checkbox(at, "LLM-ранжирование").set_value(False)
    _button(at, "Собрать черновик").click()
    _run(at)
    plan = ui_storage.latest_plan(pid)
    assert plan and plan.segments, "план не собрался"
    assert plan.preview_path and Path(plan.preview_path).exists(), \
        "preview не отрендерился"
    # таймлайн и селектор замены на месте
    assert at.selectbox, "нет селектора «Фрагмент» для замены"

    # замена фрагмента, если планировщик оставил альтернативы
    rep = [b for b in at.button if (b.key or "").startswith("rep_")]
    if rep:
        rep[0].click()
        _run(at)
        n_rep = ui_storage.conn.execute(
            "SELECT COUNT(*) FROM replacements").fetchone()[0]
        assert n_rep == 1, "замена не записана в историю"

    _button(at, "К экспорту").click()
    _run(at)
    assert at.session_state["step"] == "export"
    at = _reopen(at)

    # ── Шаг 6: экспорт — финальный рендер ──
    _button(at, "Экспортировать mp4").click()
    _run(at)
    plan = ui_storage.latest_plan(pid)
    assert plan.export_path and Path(plan.export_path).exists(), \
        "финальный mp4 не создан"
    assert plan.status == "final"

    # ── Возврат на домашний экран ──
    _button(at, "Проекты").click()
    _run(at)
    assert at.title and "Auto Video Editor" in at.title[0].value


def test_wizard_back_navigation(ui_storage, source_dir):
    """Навигация по пройденным шагам мастера работает в обе стороны."""
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    _run(at)
    # открываем проект из сквозного теста (он уже на шаге draft)
    projects = [p for p in ui_storage.list_projects()
                if p.name == "UI сквозной путь"]
    assert projects, "нужен проект из test_full_user_path"
    at.button(key=f"open_{projects[0].id}").click()
    _run(at)
    assert at.session_state["step"] == "draft"  # _infer_step: план существует
    at = _reopen(at)
    at.button(key="nav_material").click()
    _run(at)
    assert at.session_state["step"] == "material"


def test_home_open_clean_delete_buttons(ui_storage):
    """Кнопки домашнего экрана: открыть, очистить кэш, удалить с подтверждением."""
    from core.models import Project
    p = Project(name="Удаляемый UI")
    ui_storage.save_project(p)
    pdir = ui_storage.project_dir(p.id)
    junk = pdir / "cache" / "segments" / "junk.mp4"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_bytes(b"x" * 1024)

    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    _run(at)

    # открыть → шапка проекта → назад
    at.button(key=f"open_{p.id}").click()
    _run(at)
    assert at.session_state["project_id"] == p.id
    _button(at, "Проекты").click()
    _run(at)

    # очистка кэша удаляет содержимое cache/
    at.button(key=f"clean_{p.id}").click()
    _run(at)
    assert not junk.exists()

    # удаление: первый клик — только подтверждение, проект жив
    at.button(key=f"del1_{p.id}").click()
    _run(at)
    assert ui_storage.get_project(p.id) is not None
    at.button(key=f"del2_{p.id}").click()
    _run(at)
    assert ui_storage.get_project(p.id) is None
    assert not pdir.exists()


def test_analysis_page_dead_worker_recovery(ui_storage):
    """Статус «analyzing» без живого воркера: страница не зависает,
    предлагает сброс, кнопка сброса возвращает проект в работу."""
    from core.models import Project
    p = Project(name="Мёртвый воркер", status="analyzing",
                source_paths=["/nonexistent"], analysis_progress="шаг 2…")
    ui_storage.save_project(p)
    ui_storage.project_dir(p.id)

    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["project_id"] = p.id
    at.session_state["step"] = "analysis"
    _run(at)
    assert at.error, "нет сообщения о погибшем воркере"
    _button(at, "Сбросить статус и продолжить").click()
    _run(at)
    got = ui_storage.get_project(p.id)
    assert got.status == "new" and got.analysis_progress == ""
    ui_storage.delete_project(p.id)


def test_fpv_showroom_user_path(ui_storage, source_dir):
    """FPV-путь на шаге «Черновик»: переключение режима, детекция зон
    кнопкой, настройка статичной паузы, сборка showroom с реальным
    preview-рендером."""
    from core.models import Project
    from core.pipeline import analyze_project

    project = Project(name="UI FPV путь", target_duration=15,
                      source_paths=[str(source_dir)], analyze_speech=False)
    ui_storage.save_project(project)
    scenes = analyze_project(ui_storage, project,
                             progress=lambda m: None, run_llm=False)
    assert scenes
    video = ui_storage.list_videos(project.id)[0]
    video.fpv_showroom = True   # как отметил бы чекбокс 🚁 на шаге «Материал»
    ui_storage.save_video(video)

    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["project_id"] = project.id
    at.session_state["step"] = "draft"
    _run(at)

    # переключение в режим FPV
    at.radio(key=f"draft_mode_{project.id}").set_value("fpv")
    _run(at)

    # детекция зон кнопкой
    _button(at, "Найти зоны").click()
    _run(at)
    zones = ui_storage.list_zones(video.id)
    assert zones, "кнопка «Найти зоны» не создала зоны"

    # настройка статичной паузы сохраняется в проект
    pause_inputs = [n for n in at.number_input
                    if "Статичная пауза" in n.label]
    assert pause_inputs, "нет поля настройки статичной паузы"
    pause_inputs[0].set_value(1.0)
    _run(at)
    assert abs(ui_storage.get_project(project.id).fpv_pause_out - 1.0) < 0.01

    # сборка showroom с реальным рендером
    _button(at, "Собрать черновик").click()
    _run(at)
    plan = ui_storage.latest_plan(project.id)
    assert plan and plan.mode == "fpv" and plan.segments
    assert plan.preview_path and Path(plan.preview_path).exists(), \
        "preview showroom не отрендерился"
    # порядок маршрута в плане не нарушен
    starts = [s.src_start for s in plan.segments]
    assert starts == sorted(starts)
