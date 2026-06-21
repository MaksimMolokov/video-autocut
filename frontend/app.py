"""
AI Video Producer — 10-step wizard UI.

Проблемы решены:
  1. Сцены — полные карточки с thumbnail, AI-объяснением, 5 действиями
  2. Анализ — live-статистика: файлы / сцены / дубли / люди / дроны
  3. Preview — 4 чётких состояния: not_generated / generating / ready / failed
  4. Пользователь видит кадр перед решением (thumbnail + inline preview)
  5. Explainable AI — текст "почему выбрана сцена" на каждой карточке
  6. Обязательный Review Scenes перед стилем
  7. Draft Timeline — аудио + видео дорожки, перестановка, удаление
  8. Авто-показ результата после рендера
  9. 10-шаговый Wizard Flow с индикатором "Шаг X из 10"
 10. AI Analysis Summary — итоговый блок работы алгоритмов
"""
from __future__ import annotations

import base64
import logging
import os
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st

logger = logging.getLogger(__name__)

# ── ХАРД-ГАРД: Streamlit file-watcher не должен падать на torch.classes ─────────
# Streamlit обходит __path__ всех модулей; torch.classes кидает RuntimeError
# ("Tried to instantiate class '__path__._path'"), как только в процессе появляется
# torch (Whisper/Silero/CLIP). Из-за этого ломались rerun'ы и переставали работать
# кнопки (нельзя было выбрать/подтвердить/удалить сцену). Оборачиваем извлечение
# путей так, чтобы оно НИКОГДА не бросало. Плюс в config.toml fileWatcherType="none".
try:
    import streamlit.watcher.local_sources_watcher as _lsw

    def _safe_get_module_paths(module, _orig=_lsw.get_module_paths):
        try:
            return _orig(module)
        except Exception:
            return set()

    _lsw.get_module_paths = _safe_get_module_paths
except Exception:
    pass

# ── Bootstrap ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

# File log: все ошибки pipeline попадают в app.log рядом с проектом,
# чтобы их можно было диагностировать без доступа к stderr Streamlit-процесса.
_LOG_PATH = _ROOT / ".videoeditor" / "app.log"
try:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _root_logger = logging.getLogger()
    if not any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", "") == str(_LOG_PATH)
        for h in _root_logger.handlers
    ):
        _fh = logging.FileHandler(_LOG_PATH, encoding="utf-8")
        _fh.setLevel(logging.INFO)
        _fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        _root_logger.addHandler(_fh)
        if _root_logger.level > logging.INFO or _root_logger.level == logging.NOTSET:
            _root_logger.setLevel(logging.INFO)
except Exception:
    pass

st.set_page_config(
    page_title="AI Video Producer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════════
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"],
.main, .block-container {
    background-color: #0B0F12 !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
    color: #E8EDF2 !important;
}
[data-testid="stSidebar"]    { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; height: 2.5rem !important; }

.block-container {
    padding: 1.5rem 2rem 4rem !important;
    max-width: 1200px !important;
    margin: 0 auto !important;
}

/* ── Typography ───────────────────────────────────────────────────────────── */
h1 { font-size: 2rem !important; font-weight: 800 !important; letter-spacing: -.03em !important;
     color: #fff !important; margin-bottom: .3rem !important; }
h2 { font-size: 1.45rem !important; font-weight: 700 !important; color: #fff !important;
     margin-bottom: .4rem !important; }
h3 { font-size: 1rem !important; font-weight: 600 !important; color: #C5CBD3 !important; }
p  { color: #8A9BAE !important; line-height: 1.6 !important; }

/* ── Wizard step bar ──────────────────────────────────────────────────────── */
.wiz-bar { display: flex; gap: 0; margin-bottom: 1.8rem; border-radius: 8px;
           overflow: hidden; height: 5px; background: #1A2228; }
.wiz-seg { flex: 1; height: 5px; }
.wiz-seg.done   { background: #00FF88; }
.wiz-seg.active { background: #00FF88; }
.wiz-seg.todo   { background: #1A2228; }

.wiz-label { display: flex; justify-content: space-between; margin-bottom: .4rem; }
.wiz-title { font-size: .78rem; font-weight: 700; letter-spacing: .06em;
             text-transform: uppercase; color: #00FF88; }
.wiz-counter { font-size: .78rem; color: #3B4A59; font-weight: 600; }

/* ── Cards ────────────────────────────────────────────────────────────────── */
.vp-card {
    background: #181F27; border: 1px solid #232B36; border-radius: 16px;
    padding: 1.1rem; transition: transform .18s, border-color .18s, box-shadow .18s;
    position: relative; overflow: hidden;
}
.vp-card:hover { transform: scale(1.008); border-color: #2E3D4E;
                 box-shadow: 0 4px 24px rgba(0,0,0,.35); }
.vp-card.selected { border-color: #00FF88; box-shadow: 0 0 20px rgba(0,255,136,.18); background: #17231A; }
.vp-card.pinned   { border-color: #00D4FF; box-shadow: 0 0 16px rgba(0,212,255,.15); }
.vp-card.excluded { opacity: .4; border-color: #FF4C6A; }
.vp-card.forbidden { opacity: .3; border-color: #FF4C6A; background: #1E1217; }

/* ── Primary button ───────────────────────────────────────────────────────── */
.stButton > button {
    background: #00FF88 !important;
    color: #000000 !important; font-family: 'Inter', sans-serif !important;
    font-weight: 700 !important; font-size: .88rem !important;
    border: none !important; border-radius: 10px !important;
    padding: .55rem 1.3rem !important;
    transition: filter .15s, transform .12s, box-shadow .15s !important;
    box-shadow: 0 2px 6px rgba(0,255,136,.20) !important;
    letter-spacing: .01em !important;
}
.stButton > button:hover {
    filter: brightness(1.10) !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(0,255,136,.30) !important;
}
.stButton > button:active {
    transform: translateY(0) !important;
    filter: brightness(.94) !important;
    box-shadow: 0 1px 4px rgba(0,255,136,.15) !important;
}
.stButton > button:disabled {
    background: #1A2330 !important;
    color: #4A5A6A !important;
    cursor: not-allowed !important;
    transform: none !important;
    box-shadow: none !important;
    filter: none !important;
    border: 1px solid #232B36 !important;
    opacity: 0.7 !important;
}

/* ── Inputs ───────────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: #12171D !important; border: 1px solid #232B36 !important;
    border-radius: 10px !important; color: #E8EDF2 !important;
}
[data-testid="stTextInput"] input:focus {
    border-color: #00FF88 !important; box-shadow: 0 0 0 2px rgba(0,255,136,.15) !important;
}

/* ── File uploader ────────────────────────────────────────────────────────── */
[data-testid="stFileUploaderDropzone"] {
    background: #12171D !important; border: 2px dashed #232B36 !important;
    border-radius: 14px !important; min-height: 140px !important;
    transition: border-color .2s;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color: #00FF88 !important; }

/* ── Progress bar ─────────────────────────────────────────────────────────── */
.stProgress > div > div > div > div {
    background: #00FF88 !important; border-radius: 99px !important;
}
.stProgress > div > div { background: #1A2228 !important; border-radius: 99px !important; }

/* ── Badge / pills ────────────────────────────────────────────────────────── */
.badge { display:inline-block; padding:.12rem .55rem; border-radius:99px;
         font-size:.68rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase; }
.b-green  { background:rgba(0,255,136,.15); color:#00FF88; }
.b-teal   { background:rgba(0,212,255,.15); color:#00D4FF; }
.b-red    { background:rgba(255,76,106,.18); color:#FF4C6A; }
.b-yellow { background:rgba(255,210,70,.18); color:#FFD246; }
.b-gray   { background:rgba(138,155,174,.12); color:#8A9BAE; }
.b-purple { background:rgba(123,97,255,.18); color:#7B61FF; }

/* ── Scene thumbnail ──────────────────────────────────────────────────────── */
.scene-thumb {
    width:100%; aspect-ratio:16/9; border-radius:10px; overflow:hidden;
    background:#1A2228; margin-bottom:.65rem; position:relative;
    display:flex; align-items:center; justify-content:center;
}
.scene-thumb img { width:100%; height:100%; object-fit:cover; border-radius:10px; }
.scene-thumb .thumb-placeholder { font-size:2rem; color:#2E3D4E; }
.scene-thumb .thumb-overlay {
    position:absolute; inset:0; background:rgba(0,0,0,0);
    transition:background .2s; border-radius:10px;
    display:flex; align-items:center; justify-content:center;
}
.scene-thumb:hover .thumb-overlay { background:rgba(0,0,0,.45); }

/* ── Explainer box ────────────────────────────────────────────────────────── */
.ai-explain {
    background: rgba(0,255,136,.06); border: 1px solid rgba(0,255,136,.18);
    border-radius: 10px; padding: .5rem .75rem; margin: .5rem 0;
    font-size: .78rem; color: #9DE8BE; line-height: 1.5;
}
.ai-explain::before { content:"🤖 "; }

/* ── Stats grid ───────────────────────────────────────────────────────────── */
.stat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:.6rem; }
.stat-box {
    background:#12171D; border:1px solid #232B36; border-radius:12px;
    padding:.75rem 1rem; text-align:center;
}
.stat-val { font-size:1.8rem; font-weight:800; color:#00FF88; line-height:1.1; }
.stat-lbl { font-size:.7rem; color:#8A9BAE; margin-top:.2rem; font-weight:500;
            text-transform:uppercase; letter-spacing:.05em; }

/* ── Timeline ─────────────────────────────────────────────────────────────── */
.tl-wrap {
    background:#0D1318; border:1px solid #1A2228; border-radius:14px;
    padding:1rem 1.25rem; overflow-x:auto;
}
.tl-track-label { font-size:.68rem; font-weight:700; color:#3B4A59;
                  text-transform:uppercase; letter-spacing:.07em; margin-bottom:.35rem; }
.tl-audio-row { height:28px; background:#0F2A1A; border-radius:6px;
                display:flex; align-items:center; padding:0 .75rem;
                margin-bottom:.5rem; }
.tl-audio-wave { flex:1; height:14px; border-radius:4px;
                 background:repeating-linear-gradient(90deg,#00FF8822 0,#00FF8855 2px,
                 transparent 2px,transparent 6px); }
.tl-video-row { display:flex; gap:3px; height:52px; align-items:stretch; margin-bottom:.25rem; }
.tl-seg {
    border-radius:7px; min-width:22px; display:flex; flex-direction:column;
    align-items:center; justify-content:center; overflow:hidden;
    font-size:.58rem; font-weight:700; color:#0B0F12; position:relative; cursor:pointer;
    transition:filter .15s;
}
.tl-seg:hover { filter:brightness(1.18); }
.tl-seg-dur { font-size:.55rem; opacity:.8; margin-top:.1rem; }
.tl-transition { width:10px; display:flex; align-items:center; justify-content:center;
                 color:#3B4A59; font-size:.6rem; flex-shrink:0; }

/* ── Preview state ────────────────────────────────────────────────────────── */
.preview-state {
    background:#12171D; border:2px dashed #232B36; border-radius:16px;
    padding:3rem; text-align:center;
}
.preview-state.failed { border-color:#FF4C6A44; background:#180E0E; }
.preview-state.generating { border-color:#00D4FF44; background:#0D1A20; }
.preview-icon { font-size:2.8rem; margin-bottom:.6rem; }
.preview-msg  { color:#8A9BAE; font-size:.9rem; margin-bottom:1rem; }

/* ── Alerts ───────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    background:#12171D !important; border-radius:12px !important;
    border:1px solid #232B36 !important;
}

/* ── Selectbox ────────────────────────────────────────────────────────────── */
[data-testid="stSelectbox"] > div { background:#12171D !important;
    border:1px solid #232B36 !important; border-radius:10px !important; }

/* ── Tabs ─────────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background:#12171D !important; border-radius:12px !important; padding:3px !important; gap:3px !important; }
.stTabs [data-baseweb="tab"] {
    background:transparent !important; color:#8A9BAE !important;
    border-radius:9px !important; font-weight:600 !important; font-size:.85rem !important; }
.stTabs [aria-selected="true"] {
    background:#00FF88 !important; color:#000000 !important; }

/* ── Metric ───────────────────────────────────────────────────────────────── */
[data-testid="stMetric"] { background:#12171D !important; border-radius:12px !important;
    padding:.9rem !important; border:1px solid #232B36 !important; }
[data-testid="stMetric"] label { color:#8A9BAE !important; font-size:.75rem !important; }
[data-testid="stMetricValue"] { color:#00FF88 !important; font-size:1.5rem !important; font-weight:700 !important; }

/* ── Video player ─────────────────────────────────────────────────────────── */
[data-testid="stVideo"] video { border-radius:12px !important; background:#000 !important; }

/* ── Divider ──────────────────────────────────────────────────────────────── */
hr { border-color:#1A2228 !important; margin:1.25rem 0 !important; }

/* ── Checkbox ─────────────────────────────────────────────────────────────── */
[data-testid="stCheckbox"] label { font-size:.85rem !important; color:#C5CBD3 !important; }

/* ── Scrollbar ────────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width:4px; height:4px; }
::-webkit-scrollbar-track { background:#0D1318; }
::-webkit-scrollbar-thumb { background:#232B36; border-radius:99px; }

/* ── Download button ──────────────────────────────────────────────────────── */
[data-testid="stDownloadButton"] > button {
    background:#00FF88 !important;
    color:#000000 !important; font-weight:700 !important; border-radius:12px !important;
}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
STEPS = [
    ("upload",    "Загрузка"),
    ("analysis",  "AI Анализ"),
    ("scenes",    "Просмотр сцен"),
    ("concept",   "Концепция"),
    ("style",     "Стиль"),
    ("format",    "Формат"),
    ("timeline",  "Черновик"),
    ("preview",   "Превью"),
    ("render",    "Рендер"),
    ("result",    "Результат"),
]
# step index (0-based) → screen key
SCREEN_ORDER = [s[0] for s in STEPS]

_STYLE_PRESETS = [
    {"id": "cinematic_nature", "label": "Cinematic Nature",  "icon": "🏔",  "accent": "#00D4FF",
     "desc": "Медленные плавные переходы. Эпичные пейзажи, природа, дроны.",
     "tags": ["slow", "epic", "landscape"], "transition": "crossfade", "pace": "медленный"},
    {"id": "dynamic_travel",   "label": "Dynamic Travel",    "icon": "✈️",  "accent": "#00FF88",
     "desc": "Ритмичный монтаж, разнообразие ракурсов. Путешествия.",
     "tags": ["balanced", "travel"], "transition": "cut", "pace": "средний"},
    {"id": "drone_smooth",     "label": "Drone Smooth",      "icon": "🚁",  "accent": "#00D4FF",
     "desc": "Плавные аэро-переходы, длинные широкие планы. Полёт.",
     "tags": ["aerial", "smooth", "wide"], "transition": "crossfade", "pace": "медленный"},
    {"id": "fast_reels",       "label": "Fast Reels",        "icon": "⚡",  "accent": "#FF4C6A",
     "desc": "Быстрые cuts в ритм. TikTok / Reels энергетика.",
     "tags": ["fast", "beat-sync"], "transition": "cut", "pace": "быстрый"},
    {"id": "family_memories",  "label": "Family Memories",   "icon": "💛",  "accent": "#FFD246",
     "desc": "Тёплый монтаж. Лица, эмоции, моменты.",
     "tags": ["warm", "faces"], "transition": "crossfade", "pace": "медленный"},
    {"id": "luxury_promo",     "label": "Luxury Promo",      "icon": "💎",  "accent": "#C7A85A",
     "desc": "Премиум эстетика. Резкий чистый монтаж для брендов.",
     "tags": ["premium", "sharp"], "transition": "cut", "pace": "средний"},
    {"id": "real_estate",      "label": "Real Estate",       "icon": "🏠",  "accent": "#8BC4E8",
     "desc": "Плавный профессиональный монтаж. Квартиры, дома, офисы.",
     "tags": ["stable", "interior", "architecture"], "transition": "crossfade", "pace": "медленный"},
    {"id": "fpv_action",       "label": "FPV Action",        "icon": "🚀",  "accent": "#FF6B2B",
     "desc": "Экстремальный FPV-монтаж. Гонки, экшн-спорт, дроны.",
     "tags": ["extreme", "fpv", "fast"], "transition": "cut", "pace": "быстрый"},
]

_FORMAT_OPTIONS = [
    {"id": "youtube_shorts",    "label": "YouTube Shorts",   "icon": "▶",  "ratio": "9:16",   "w": 1080, "h": 1920},
    {"id": "instagram_reels",   "label": "Instagram Reels",  "icon": "📸", "ratio": "9:16",   "w": 1080, "h": 1920},
    {"id": "tiktok",            "label": "TikTok",           "icon": "🎵", "ratio": "9:16",   "w": 1080, "h": 1920},
    {"id": "youtube_horizontal","label": "YouTube",          "icon": "📺", "ratio": "16:9",   "w": 1920, "h": 1080},
    {"id": "fullhd_horizontal", "label": "FullHD 1080p",     "icon": "🖥", "ratio": "16:9",   "w": 1920, "h": 1080},
    {"id": "uhd_4k",            "label": "4K",               "icon": "🔷", "ratio": "16:9",   "w": 3840, "h": 2160},
    {"id": "square",            "label": "Square",           "icon": "⬜", "ratio": "1:1",    "w": 1080, "h": 1080},
    {"id": "wide_cinematic",    "label": "Cinematic 2.35:1", "icon": "🎞", "ratio": "2.35:1", "w": 2560, "h": 1080},
]

_SEG_COLORS = [
    "#00FF88","#00D4FF","#7B61FF","#FF7C4C",
    "#FFD246","#00E5CC","#A8FF78","#FF4C8A",
]

_ANALYSIS_STAGES = [
    "Чтение файлов",
    "Обнаружение сцен",
    "Анализ резкости и экспозиции",
    "Определение движения камеры",
    "Обнаружение лиц и людей",
    "Оценка эстетики и композиции",
    "Поиск дублей",
    "Анализ музыки",
    "Итоговая оценка фрагментов",
]

# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════

# Запоминаем введённые пути (видео/аудио/голос/проект, выбранные стиль/формат/длину)
# между перезапусками приложения — до момента финального рендера. Чтобы при
# тестировании не вводить ссылки на видео и аудио каждый раз заново.
_SESSION_FILE = Path.home() / ".video_editor_session.json"
_SESSION_KEYS = ("project_name", "video_paths", "audio_path", "voiceover_path",
                 "selected_style", "selected_format", "target_duration")


def _save_session_inputs() -> None:
    """Сохранить текущие введённые пути/настройки на диск.

    Держим до явного «Новый проект» («✕ Очистить» / «✦ Создать новое видео»),
    а не сбрасываем после рендера — чтобы при тестировании рендерить один и тот
    же набор много раз без повторного ввода путей.
    """
    try:
        import json
        data = {k: st.session_state.get(k) for k in _SESSION_KEYS}
        _SESSION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as exc:
        logger.debug("[session] save failed: %s", exc)


def _load_session_inputs() -> dict:
    try:
        import json
        if _SESSION_FILE.exists():
            return json.loads(_SESSION_FILE.read_text())
    except Exception as exc:
        logger.debug("[session] load failed: %s", exc)
    return {}


def _clear_session_inputs() -> None:
    """Удалить сохранённые входные данные (после финального рендера)."""
    try:
        _SESSION_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _init() -> None:
    defaults: Dict = {
        "screen":           "upload",
        "project_name":     "",
        "video_paths":      [],
        "audio_path":       None,
        "voiceover_path":   None,
        "subtitles_enabled": False,
        "subtitle_model":   "small",
        "subtitle_lang":    None,
        # analysis
        "analysis_done":    False,
        "analysis_stats":   {},   # live counters
        "scene_fragments":  [],
        # scenes review
        "scene_actions":    {},   # fid -> "included"|"excluded"|"pinned"|"forbidden"
        # style / format / duration
        "selected_style":   None,
        "selected_format":  None,
        "target_duration":  30,
        # timeline
        "tl_variant":       "A",
        "tl_variants":      {},   # A/B/C/D → list of segment dicts
        # preview
        "preview_state":    "not_generated",  # not_generated|generating|ready|failed
        "preview_path":     None,
        "preview_error":    "",
        "preview_pct":      0,
        # render
        "render_state":     "not_started",    # not_started|rendering|done|failed
        "render_path":      None,
        "render_pct":       0,
        "render_error":     "",
        "render_rating":    0,
        # concept
        "video_concept":    None,
        "style_fit_done":   False,
        # project
        "project_root":     None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Один раз за сессию восстановить введённые пути из прошлого запуска,
    # если файлы всё ещё существуют на диске (см. _save_session_inputs).
    if not st.session_state.get("_session_restored"):
        st.session_state["_session_restored"] = True
        saved = _load_session_inputs()
        if saved:
            vids = [p for p in (saved.get("video_paths") or []) if Path(p).is_file()]
            if vids:
                st.session_state.video_paths = vids
            ap = saved.get("audio_path")
            if ap and Path(ap).is_file():
                st.session_state.audio_path = ap
            vo = saved.get("voiceover_path")
            if vo and Path(vo).is_file():
                st.session_state.voiceover_path = vo
            if saved.get("project_name"):
                st.session_state.project_name = saved["project_name"]
            for k in ("selected_style", "selected_format", "target_duration"):
                if saved.get(k) is not None:
                    st.session_state[k] = saved[k]
            if vids:
                logger.info("[session] восстановлено %d видео + audio=%s из прошлой сессии",
                            len(vids), bool(ap))

_init()

# ══════════════════════════════════════════════════════════════════════════════
# NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════
def _go(screen: str) -> None:
    st.session_state.screen = screen
    st.rerun()

def _back() -> None:
    idx = SCREEN_ORDER.index(st.session_state.screen)
    if idx > 0:
        _go(SCREEN_ORDER[idx - 1])

# ══════════════════════════════════════════════════════════════════════════════
# WIZARD STEP INDICATOR
# ══════════════════════════════════════════════════════════════════════════════
def _wizard_bar() -> None:
    cur = st.session_state.screen
    cur_idx = SCREEN_ORDER.index(cur) if cur in SCREEN_ORDER else 0
    n = len(STEPS)
    step_num = cur_idx + 1
    step_lbl = STEPS[cur_idx][1]

    segs_html = ""
    for i in range(n):
        cls = "done" if i < cur_idx else ("active" if i == cur_idx else "todo")
        segs_html += f'<div class="wiz-seg {cls}"></div>'

    st.markdown(f"""
<div class="wiz-label">
  <span class="wiz-title">Шаг {step_num} · {step_lbl}</span>
  <span class="wiz-counter">{step_num} / {n}</span>
</div>
<div class="wiz-bar">{segs_html}</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# THUMBNAIL HELPER
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def _extract_thumb(video_path: str, t: float = 1.0) -> Optional[str]:
    """Extract frame at t seconds, return base64 PNG string (or None)."""
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        import cv2
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return base64.b64encode(buf.tobytes()).decode()
    except Exception:
        return None

def _thumb_html(b64: Optional[str], placeholder_icon: str = "🎬") -> str:
    if b64:
        return f'<img src="data:image/jpeg;base64,{b64}" />'
    return f'<div class="thumb-placeholder">{placeholder_icon}</div>'

_VIDEO_EXTS = {".mp4",".mov",".avi",".mkv",".mts",".m2ts",".mxf",".webm",".m4v",".hevc",".dng"}
_AUDIO_EXTS = {".mp3",".wav",".aac",".flac",".ogg",".m4a",".aiff"}


def _scan_folder(folder: str) -> Tuple[List[str], List[str]]:
    """Return (video_paths, audio_paths) found directly in folder."""
    p = Path(folder)
    if not p.is_dir():
        return [], []
    videos, audio = [], []
    for f in sorted(p.iterdir()):
        if f.is_file():
            ext = f.suffix.lower()
            if ext in _VIDEO_EXTS:
                videos.append(str(f))
            elif ext in _AUDIO_EXTS:
                audio.append(str(f))
    return videos, audio


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 1 · UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
def _screen_upload() -> None:
    _wizard_bar()

    st.markdown("## Добавить материал")
    st.markdown('<p>Укажите папку с видео или вставьте пути к файлам. Загрузка по сети не нужна — всё читается прямо с диска.</p>', unsafe_allow_html=True)

    # Project name
    proj = st.text_input(
        "Название проекта",
        value=st.session_state.project_name,
        placeholder="Поездка в Грузию · Свадьба · Дрон-съёмка Байкала",
    )
    st.session_state.project_name = proj.strip()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabs: folder | files | upload ────────────────────────────────────────
    tab_folder, tab_files, tab_upload = st.tabs([
        "📁  Папка с видео",
        "🗂  Отдельные файлы",
        "⬆  Загрузить с компьютера",
    ])

    collected_videos: List[str] = list(st.session_state.get("video_paths") or [])
    collected_audio:  Optional[str] = st.session_state.get("audio_path")

    # ── TAB 1: folder path ────────────────────────────────────────────────────
    with tab_folder:
        st.markdown("Вставьте путь к папке с видео. Все видеофайлы из неё будут добавлены.")
        folder_in = st.text_input(
            "Путь к папке",
            value=st.session_state.get("_folder_input", ""),
            placeholder="/Users/maksimmolokov/Videos/Отпуск 2025",
            key="folder_input_box",
            label_visibility="collapsed",
        )
        st.session_state["_folder_input"] = folder_in

        if folder_in:
            folder_in = folder_in.strip().strip("'\"")
            fp = Path(folder_in)
            if fp.is_dir():
                found_v, found_a = _scan_folder(folder_in)
                if found_v:
                    st.markdown(f'<span class="badge b-green">✓ Найдено {len(found_v)} видео</span>', unsafe_allow_html=True)
                    for vp in found_v:
                        sz = Path(vp).stat().st_size / 1e9
                        sz_str = f"{sz:.2f} ГБ" if sz >= 1 else f"{sz*1000:.0f} МБ"
                        st.markdown(f"""
<div style="display:flex;align-items:center;gap:.5rem;padding:.3rem 0;
            border-bottom:1px solid #1A2228;font-size:.82rem;">
  <span style="color:#00FF88;font-size:.7rem;">▶</span>
  <span style="color:#E8EDF2;flex:1;">{Path(vp).name}</span>
  <span style="color:#8A9BAE;">{sz_str}</span>
</div>""", unsafe_allow_html=True)
                    if st.button("Добавить все видео из папки", key="add_folder", use_container_width=True):
                        st.session_state.video_paths = found_v
                        if found_a and not collected_audio:
                            st.session_state.audio_path = found_a[0]
                        st.rerun()
                else:
                    st.warning("В папке не найдено поддерживаемых видеофайлов.")
            elif folder_in:
                st.error(f"Папка не найдена: {folder_in}")

        # Music folder
        st.markdown("<br>**Папка или файл с музыкой** <span style='color:#3B4A59;font-size:.8rem;'>(опционально)</span>", unsafe_allow_html=True)
        music_in = st.text_input(
            "Путь к аудио",
            value=st.session_state.get("_music_input", ""),
            placeholder="/Users/maksimmolokov/Music/track.mp3",
            key="music_input_box",
            label_visibility="collapsed",
        )
        st.session_state["_music_input"] = music_in
        if music_in:
            music_in = music_in.strip().strip("'\"")
            mp = Path(music_in)
            if mp.is_file() and mp.suffix.lower() in _AUDIO_EXTS:
                sz = mp.stat().st_size / 1e6
                st.markdown(f'<span class="badge b-teal">🎵 {mp.name} · {sz:.1f} МБ</span>', unsafe_allow_html=True)
                if st.button("Использовать этот трек", key="add_music_path"):
                    st.session_state.audio_path = music_in
                    st.rerun()
            elif mp.is_dir():
                _, found_a = _scan_folder(music_in)
                if found_a:
                    st.markdown(f'<span class="badge b-teal">🎵 Найдено {len(found_a)} аудио</span>', unsafe_allow_html=True)
                    chosen = st.selectbox("Выберите трек", [Path(a).name for a in found_a], label_visibility="collapsed")
                    if st.button("Использовать", key="add_music_dir"):
                        idx = [Path(a).name for a in found_a].index(chosen)
                        st.session_state.audio_path = found_a[idx]
                        st.rerun()
            elif music_in:
                st.error("Файл не найден или формат не поддерживается.")

    # ── TAB 2: individual file paths ──────────────────────────────────────────
    with tab_files:
        st.markdown("Вставьте пути к файлам — по одному на строку.")
        paths_text = st.text_area(
            "Пути к файлам",
            value="\n".join(st.session_state.get("_paths_text_lines") or []),
            placeholder="/Volumes/SSD/shoot_001.mp4\n/Volumes/SSD/shoot_002.mov\n/Users/me/drone.mp4",
            height=160,
            label_visibility="collapsed",
            key="paths_textarea",
        )
        if st.button("Проверить и добавить", key="add_paths_btn", use_container_width=True):
            lines = [l.strip().strip("'\"") for l in paths_text.splitlines() if l.strip()]
            ok, bad = [], []
            for l in lines:
                p = Path(l)
                if p.is_file() and p.suffix.lower() in _VIDEO_EXTS:
                    ok.append(str(p))
                elif p.is_file() and p.suffix.lower() in _AUDIO_EXTS:
                    if not st.session_state.get("audio_path"):
                        st.session_state.audio_path = str(p)
                else:
                    bad.append(l)
            if ok:
                st.session_state.video_paths = list(dict.fromkeys(
                    (st.session_state.get("video_paths") or []) + ok
                ))
                st.session_state["_paths_text_lines"] = lines
            if bad:
                st.warning(f"Не найдено или не поддерживается: {', '.join(Path(b).name for b in bad)}")
            st.rerun()

    # ── TAB 3: browser upload (small files) ──────────────────────────────────
    with tab_upload:
        st.markdown("Для файлов до ~500 МБ. Для больших файлов используйте вкладку «Папка с видео».")
        video_files = st.file_uploader(
            "Видео",
            type=["mp4","mov","avi","mkv","mts","m2ts","mxf","webm","m4v"],
            accept_multiple_files=True, key="vu", label_visibility="collapsed",
        )
        music_file = st.file_uploader(
            "Музыка",
            type=["mp3","wav","aac","flac","ogg","m4a","aiff"],
            key="mu", label_visibility="collapsed",
        )
        if video_files and st.button("Сохранить загруженные файлы", key="save_uploads"):
            tmp = Path(tempfile.mkdtemp(prefix="avp_"))
            new_paths = []
            for f in video_files:
                p = tmp / f.name
                p.write_bytes(f.getbuffer())
                new_paths.append(str(p))
            st.session_state.video_paths = new_paths
            if music_file:
                mp = tmp / music_file.name
                mp.write_bytes(music_file.getbuffer())
                st.session_state.audio_path = str(mp)
            st.rerun()

    # ── Voiceover slot ────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("🎤 Закадровый голос (voiceover) — опционально"):
        st.markdown('<p style="font-size:.8rem;color:#8A9BAE;margin-bottom:.4rem;">'
                    'Отдельная аудиодорожка поверх видео. Будет смикширована с музыкой '
                    '(голос 90% — фоновая музыка 30%).</p>', unsafe_allow_html=True)
        vo_in = st.text_input(
            "Путь к voiceover",
            value=st.session_state.get("_vo_input", ""),
            placeholder="/Users/me/voice_comment.wav",
            key="vo_input_box",
            label_visibility="collapsed",
        )
        st.session_state["_vo_input"] = vo_in
        if vo_in:
            vo_in_clean = vo_in.strip().strip("'\"")
            vop = Path(vo_in_clean)
            if vop.is_file() and vop.suffix.lower() in _AUDIO_EXTS:
                sz = vop.stat().st_size / 1e6
                st.markdown(
                    f'<span class="badge b-teal">🎤 {vop.name} · {sz:.1f} МБ</span>',
                    unsafe_allow_html=True,
                )
                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    if st.button("Использовать как voiceover", key="add_vo"):
                        st.session_state.voiceover_path = vo_in_clean
                        st.rerun()
                with col_v2:
                    if st.session_state.get("voiceover_path"):
                        if st.button("✕ Убрать voiceover", key="rm_vo"):
                            st.session_state.voiceover_path = None
                            st.rerun()
            elif vo_in:
                st.error("Файл не найден или формат не поддерживается.")
        elif st.session_state.get("voiceover_path"):
            vop_set = Path(st.session_state.voiceover_path)
            sz = vop_set.stat().st_size / 1e6 if vop_set.exists() else 0
            st.markdown(
                f'<span class="badge b-teal">🎤 {vop_set.name} · {sz:.1f} МБ</span>',
                unsafe_allow_html=True,
            )
            if st.button("✕ Убрать voiceover", key="rm_vo_active"):
                st.session_state.voiceover_path = None
                st.rerun()

    # ── Current selection summary ─────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    final_videos = st.session_state.get("video_paths") or []
    final_audio  = st.session_state.get("audio_path")

    can_go = bool(final_videos) and bool(st.session_state.project_name)

    def _launch_analysis():
        st.session_state.analysis_done = False
        st.session_state.analysis_stats = {}
        st.session_state.scene_fragments = []
        st.session_state.scene_actions = {}
        st.session_state.pop("analysis_error", None)
        st.session_state.pop("analysis_warning", None)
        _go("analysis")

    if final_videos:
        total_gb = sum(Path(p).stat().st_size for p in final_videos if Path(p).exists()) / 1e9
        total_mb = total_gb * 1024
        n = len(final_videos)
        n_word = "файл" if n == 1 else ("файла" if 2 <= n <= 4 else "файлов")
        sz_display = f"{total_gb:.2f} ГБ" if total_gb >= 1 else f"{total_mb:.0f} МБ"

        # ── Sticky action bar — always visible above file list ────────────────
        st.markdown(f"""
<div style="background:#111820;border:1px solid #1E2D3D;border-radius:12px;
            padding:.75rem 1rem;margin-bottom:.75rem;display:flex;
            align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.5rem;">
  <div style="font-weight:700;color:#E8EDF2;">
    Добавлено видео &nbsp;
    <span class="badge b-green">{n} {n_word} · {sz_display}</span>
    {"&nbsp;<span class='badge b-teal'>🎵 " + Path(final_audio).name + "</span>" if final_audio and Path(final_audio).exists() else ""}
  </div>
  <div style="font-size:.75rem;color:#4A5A6A;">
    {"✓ Проект: " + st.session_state.project_name if st.session_state.project_name else "⚠ Укажите название проекта"}
  </div>
</div>""", unsafe_allow_html=True)

        # ── Launch button right after the header (always visible) ────────────
        col_launch, col_clear = st.columns([3, 1])
        with col_launch:
            if st.button("🚀  Запустить AI-анализ", disabled=not can_go,
                         use_container_width=True, key="launch_top"):
                _launch_analysis()
        with col_clear:
            if st.button("✕ Очистить", use_container_width=True, key="clear_top"):
                st.session_state.video_paths    = []
                st.session_state.audio_path     = None
                st.session_state.voiceover_path = None
                _clear_session_inputs()   # «Новый проект» — забыть сохранённые пути
                st.rerun()

        if not can_go and not st.session_state.project_name:
            st.markdown('<p style="font-size:.78rem;color:#FF9A3C;margin-top:.2rem;">'
                        '⚠ Укажите название проекта выше</p>', unsafe_allow_html=True)

        st.markdown("<hr style='border-color:#1A2228;margin:.6rem 0;'>", unsafe_allow_html=True)

        # ── File list in scrollable container ─────────────────────────────────
        show_limit = 8
        show_all = st.session_state.get("_upload_show_all", False)
        visible_paths = final_videos if show_all else final_videos[:show_limit]
        to_delete: Optional[int] = None

        for i, vp in enumerate(visible_paths):
            p = Path(vp)
            exists = p.exists()
            sz = p.stat().st_size / 1e9 if exists else 0
            sz_str = f"{sz:.2f} ГБ" if sz >= 1 else f"{sz*1000:.0f} МБ"
            col_name, col_sz, col_del = st.columns([7, 2, 1])
            with col_name:
                color = "#E8EDF2" if exists else "#FF4C6A"
                icon = "✓" if exists else "❌"
                st.markdown(
                    f'<div style="color:{color};font-family:monospace;font-size:.77rem;'
                    f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
                    f'line-height:2.1;"><span style="color:#3B4A59;margin-right:.3rem;">'
                    f'{icon}</span>{p.name}</div>',
                    unsafe_allow_html=True,
                )
            with col_sz:
                st.markdown(
                    f'<div style="color:#8A9BAE;font-size:.77rem;text-align:right;line-height:2.1;">'
                    f'{"❌" if not exists else sz_str}</div>',
                    unsafe_allow_html=True,
                )
            with col_del:
                if st.button("✕", key=f"del_vid_{i}", help="Убрать из списка"):
                    to_delete = i

        if to_delete is not None:
            st.session_state.video_paths = [p for j, p in enumerate(final_videos) if j != to_delete]
            st.session_state.pop("_upload_show_all", None)
            st.rerun()

        if len(final_videos) > show_limit:
            rem = len(final_videos) - show_limit
            lbl = "▲ Свернуть" if show_all else f"▼ Ещё {rem} файлов"
            if st.button(lbl, key="toggle_show_all"):
                st.session_state["_upload_show_all"] = not show_all
                st.rerun()

        final_vo = st.session_state.get("voiceover_path")
        if final_vo and Path(final_vo).exists():
            sz = Path(final_vo).stat().st_size / 1e6
            st.markdown(f'<span class="badge b-teal">🎤 {Path(final_vo).name} · {sz:.1f} МБ</span>',
                        unsafe_allow_html=True)

    else:
        # No files yet
        st.markdown('<p style="font-size:.82rem;color:#3B4A59;">'
                    'Укажите название проекта и добавьте хотя бы одно видео</p>',
                    unsafe_allow_html=True)

    # ── Bottom CTA (fallback / duplicate for long lists) ─────────────────────
    if final_videos:
        st.markdown("<br>", unsafe_allow_html=True)
        col = st.columns([1, 2, 1])[1]
        with col:
            if st.button("🚀  Запустить AI-анализ", disabled=not can_go,
                         use_container_width=True, key="launch_bottom"):
                _launch_analysis()

    # Запомнить введённые пути до финального рендера (видео/аудио/голос/проект).
    _save_session_inputs()

    # ── kept for compat: handle legacy uploader flow ──────────────────────────
    if False:
        tmp = Path(tempfile.mkdtemp(prefix="avp_"))


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 2 · AI ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
def _screen_analysis() -> None:
    _wizard_bar()
    st.markdown("## AI анализирует материал")

    if st.session_state.analysis_done:
        if st.session_state.get("analysis_error"):
            st.error(st.session_state.analysis_error)
            col = st.columns([1, 2, 1])[1]
            with col:
                if st.button("← Вернуться к загрузке", use_container_width=True):
                    st.session_state.analysis_done = False
                    st.session_state.pop("analysis_error", None)
                    st.session_state.pop("analysis_warning", None)
                    _go("upload")
            return
        if st.session_state.get("analysis_warning"):
            st.warning(st.session_state.analysis_warning)
        _render_analysis_summary()
        col = st.columns([1,2,1])[1]
        with col:
            if st.button("Просмотреть сцены →", use_container_width=True):
                _go("scenes")
        return

    # Live-статистика
    stats_ph  = st.empty()
    stage_ph  = st.empty()
    prog_ph   = st.progress(0)
    detail_ph = st.empty()

    _run_analysis(stats_ph, stage_ph, prog_ph, detail_ph)


def _render_analysis_summary() -> None:
    """Блок итогов анализа."""
    stats = st.session_state.get("analysis_stats", {})
    frags = st.session_state.get("scene_fragments", [])
    n_total  = len(frags)
    n_good   = sum(1 for f in frags if f.get("rejection_reason") is None)
    n_bad    = n_total - n_good
    n_dupes  = stats.get("duplicates", 0)
    n_faces  = sum(1 for f in frags if f.get("has_face"))
    n_drone  = sum(1 for f in frags if "drone" in (f.get("scene_tags") or []) or "aerial" in (f.get("scene_tags") or []))
    avg_q    = sum(f.get("quality_score", 0) for f in frags) / max(1, n_total)

    st.markdown("""
<div style="margin-bottom:1.2rem;">
  <span style="font-size:.7rem;font-weight:700;letter-spacing:.08em;
               text-transform:uppercase;color:#00FF88;">AI Analysis Summary</span>
</div>""", unsafe_allow_html=True)

    st.markdown(f"""
<div class="stat-grid">
  <div class="stat-box"><div class="stat-val">{n_total}</div><div class="stat-lbl">Сцен найдено</div></div>
  <div class="stat-box" style="border-color:#00FF8833;">
    <div class="stat-val" style="color:#00FF88;">{n_good}</div><div class="stat-lbl">Хороших сцен</div></div>
  <div class="stat-box" style="border-color:#FF4C6A33;">
    <div class="stat-val" style="color:#FF4C6A;">{n_bad}</div><div class="stat-lbl">Отклонено</div></div>
  <div class="stat-box" style="border-color:#FFD24633;">
    <div class="stat-val" style="color:#FFD246;">{n_dupes}</div><div class="stat-lbl">Дублей</div></div>
  <div class="stat-box">
    <div class="stat-val" style="color:#00D4FF;">{n_faces}</div><div class="stat-lbl">С людьми</div></div>
  <div class="stat-box">
    <div class="stat-val" style="color:#7B61FF;">{n_drone}</div><div class="stat-lbl">Drone shots</div></div>
  <div class="stat-box">
    <div class="stat-val">{avg_q:.0%}</div><div class="stat-lbl">Сред. качество</div></div>
  <div class="stat-box" style="border-color:#00FF8833;">
    <div class="stat-val">{stats.get('elapsed_s', 0):.1f}с</div><div class="stat-lbl">Время анализа</div></div>
</div>
""", unsafe_allow_html=True)

    # Per-source breakdown
    _sources = sorted({Path(f.get("source", "")).name for f in frags if f.get("source")})
    if len(_sources) > 1:
        rows_html = ""
        for src in _sources:
            src_frags = [f for f in frags if Path(f.get("source", "")).name == src]
            s_good = sum(1 for f in src_frags if not f.get("rejection_reason"))
            s_avg  = sum(f.get("quality_score", 0) for f in src_frags) / max(1, len(src_frags))
            s_mode = src_frags[0].get("analysis_mode", "real") if src_frags else "?"
            mode_c = {"real": "#00C870", "cached": "#00B8D9", "demo": "#FF9A3C"}.get(s_mode, "#8A9BAE")
            rows_html += (
                f'<tr><td style="color:#C5CBD3;padding:.15rem .4rem;">{src}</td>'
                f'<td style="color:#E8EDF2;text-align:center;">{len(src_frags)}</td>'
                f'<td style="color:#00FF88;text-align:center;">{s_good}</td>'
                f'<td style="color:#8A9BAE;text-align:center;">{s_avg:.0%}</td>'
                f'<td style="color:{mode_c};text-align:center;font-size:.65rem;">{s_mode.upper()}</td>'
                f'</tr>'
            )
        st.markdown(f"""
<div style="margin-top:.8rem;">
  <div style="font-size:.7rem;font-weight:700;color:#4A5A6A;text-transform:uppercase;
              letter-spacing:.06em;margin-bottom:.3rem;">По видеофайлам</div>
  <table style="width:100%;border-collapse:collapse;font-size:.75rem;">
    <thead><tr style="color:#4A5A6A;font-size:.68rem;">
      <th style="text-align:left;padding:.1rem .4rem;">Файл</th>
      <th>Сцен</th><th>Хорошие</th><th>Качество</th><th>Режим</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>""", unsafe_allow_html=True)


def _run_analysis(stats_ph, stage_ph, prog_ph, detail_ph) -> None:
    t0 = time.time()
    video_paths = st.session_state.get("video_paths", [])
    used_real_backend = False
    backend_error: str = ""

    # Файлы могли исчезнуть (например, temp-загрузки очищены ОС) — проверяем заранее
    missing = [p for p in video_paths if not Path(p).is_file()]
    if missing and len(missing) == len(video_paths):
        names = ", ".join(Path(p).name for p in missing[:5])
        st.session_state.scene_fragments = []
        st.session_state.analysis_error = (
            f"Исходные файлы не найдены на диске: {names}. "
            "Загруженные через браузер файлы хранятся во временной папке и могли быть "
            "удалены системой — вернитесь на шаг 1 и добавьте файлы заново "
            "(надёжнее через вкладку «Папка с видео»)."
        )
        st.session_state.analysis_done = True
        st.rerun()
        return
    if missing:
        logger.warning("[_run_analysis] %d файлов не найдено, анализируем остальные: %s",
                       len(missing), [Path(p).name for p in missing])
        video_paths = [p for p in video_paths if Path(p).is_file()]

    try:
        from backend.services.analysis_service import AnalysisService
        root = st.session_state.get("project_root") or str(
            Path.home() / "VideoProjects" / (st.session_state.project_name or "project")
        )
        st.session_state.project_root = root
        svc = AnalysisService(root)

        live: Dict = {"found": 0, "good": 0, "dupes": 0, "faces": 0, "drone": 0, "current": ""}

        def _cb(stage: int, detail: str = "", found: int = 0) -> None:
            # Ошибки отрисовки прогресса не должны ронять сам анализ
            try:
                n_stages = max(len(video_paths), 1)
                ratio    = min(0.95, stage / n_stages)
                prog_ph.progress(ratio)
                lbl = _ANALYSIS_STAGES[min(stage - 1, len(_ANALYSIS_STAGES) - 1)] if stage > 0 else _ANALYSIS_STAGES[0]
                stage_ph.markdown(
                    f'<p style="color:#E8EDF2;font-size:.88rem;">'
                    f'<span style="color:#00FF88;">●</span> {lbl}</p>',
                    unsafe_allow_html=True,
                )
                if detail:
                    detail_ph.markdown(
                        f'<p style="color:#8A9BAE;font-size:.75rem;">{detail}</p>',
                        unsafe_allow_html=True,
                    )
                _render_live_stats(stats_ph, live)
            except Exception as cb_exc:
                logger.debug("[_run_analysis] progress UI error (ignored): %s", cb_exc)

        result = svc.analyze_project(
            abs_paths=video_paths,
            progress_callback=_cb,
        )
        frags = result.get("fragments", [])
        failed = result.get("failed_files") or []
        if failed and not frags:
            detail = "; ".join(f"{f['name']} — {f['error']}" for f in failed[:5])
            backend_error = f"все файлы не обработались ({detail})"
        elif failed:
            st.session_state.analysis_warning = (
                f"Не обработано файлов: {len(failed)} — "
                + "; ".join(f"{f['name']} ({f['error']})" for f in failed[:5])
            )
        if frags:
            used_real_backend = True
            # Update live stats from real results
            live["found"] = len(frags)
            live["faces"] = sum(1 for f in frags if f.get("has_face"))
            live["dupes"] = result.get("duplicates_removed", 0)
            _render_live_stats(stats_ph, live)

        st.session_state.scene_fragments = frags
        st.session_state.analysis_stats = {
            "duplicates": result.get("duplicates_removed", 0),
            "cached":     result.get("cached", 0),
            "elapsed_s":  result.get("elapsed_s") or (time.time() - t0),
            "total_analyzed": result.get("total_analyzed", len(frags)),
        }

    except Exception as exc:
        backend_error = f"{type(exc).__name__}: {exc}"
        logger.warning("[_run_analysis] backend error: %s", exc, exc_info=True)

    if not used_real_backend:
        if video_paths:
            # Real files loaded but analysis pipeline failed — never substitute fake data
            st.session_state.scene_fragments = []
            if backend_error:
                st.session_state.analysis_error = (
                    f"Анализ не удался: {backend_error}\n\n"
                    f"Подробности в логе: {_LOG_PATH}"
                )
            else:
                # Пайплайн отработал без исключений, но не нашёл ни одного фрагмента
                st.session_state.analysis_error = (
                    "Анализ завершился, но не нашёл ни одного пригодного фрагмента. "
                    "Проверьте, что видео не повреждены и содержат различимые сцены. "
                    f"Подробности в логе: {_LOG_PATH}"
                )
            st.session_state.analysis_done = True
            prog_ph.progress(1.0)
            stage_ph.markdown(
                '<p style="color:#FF4C6A;font-weight:700;">✗ Ошибка анализа</p>',
                unsafe_allow_html=True,
            )
            st.rerun()
            return
        else:
            # No real files → demo mode only
            frags = _simulate_analysis(stats_ph, stage_ph, prog_ph, detail_ph, t0)
            for f in frags:
                f["analysis_mode"] = "demo"
            st.session_state.scene_fragments = frags

    # Mark real fragments with analysis_mode if not already set
    if used_real_backend:
        for f in st.session_state.scene_fragments:
            if "analysis_mode" not in f:
                f["analysis_mode"] = "real"

    # Ensure _abs_path is set on every fragment
    # CRITICAL: never default to video_paths[0] — that makes all scenes show the same clip
    name_to_abs: Dict[str, str] = {Path(p).name: p for p in video_paths}
    for f in st.session_state.scene_fragments:
        if not f.get("_abs_path"):
            src_name = Path(f.get("source", "")).name
            f["_abs_path"] = name_to_abs.get(src_name, "")

    # Thumbnail abs paths
    root = st.session_state.get("project_root", "")
    for f in st.session_state.scene_fragments:
        if f.get("thumbnail_rel_path") and root:
            abs_thumb = str(Path(root) / f["thumbnail_rel_path"])
            if Path(abs_thumb).exists():
                f["_thumb_abs"] = abs_thumb

    # Build scene actions defaults
    _SOFT = ("tilted horizon", "cluttered background")
    actions = {}
    for f in st.session_state.scene_fragments:
        rej = f.get("rejection_reason")
        if rej and not any(s in rej for s in _SOFT):
            actions[f["id"]] = "excluded"
        else:
            actions[f["id"]] = "included"
    # Если отбраковано вообще всё — включаем лучшую половину по качеству,
    # иначе монтаж невозможен (пользователь может скорректировать на экране сцен)
    if actions and all(a == "excluded" for a in actions.values()):
        frs = st.session_state.scene_fragments
        keep = sorted(frs, key=lambda x: -x.get("quality_score", 0))
        for f in keep[:max(3, len(keep) // 2)]:
            actions[f["id"]] = "included"
        logger.warning("[analysis] все фрагменты отбракованы — включена лучшая половина (%d)",
                       sum(1 for a in actions.values() if a == "included"))
    st.session_state.scene_actions = actions

    st.session_state.analysis_done = True
    prog_ph.progress(1.0)
    stage_ph.markdown(
        '<p style="color:#00FF88;font-weight:700;">✓ Анализ завершён</p>',
        unsafe_allow_html=True,
    )
    st.rerun()


def _render_live_stats(ph, live: Dict) -> None:
    ph.markdown(f"""
<div style="display:flex;gap:.6rem;flex-wrap:wrap;margin-bottom:.75rem;">
  <div class="stat-box" style="min-width:100px;padding:.5rem .75rem;">
    <div class="stat-val" style="font-size:1.2rem;">{live['found']}</div>
    <div class="stat-lbl">Сцен найдено</div>
  </div>
  <div class="stat-box" style="min-width:100px;padding:.5rem .75rem;">
    <div class="stat-val" style="font-size:1.2rem;color:#FFD246;">{live['dupes']}</div>
    <div class="stat-lbl">Дублей удалено</div>
  </div>
  <div class="stat-box" style="min-width:100px;padding:.5rem .75rem;">
    <div class="stat-val" style="font-size:1.2rem;color:#00D4FF;">{live['faces']}</div>
    <div class="stat-lbl">С людьми</div>
  </div>
  <div class="stat-box" style="min-width:100px;padding:.5rem .75rem;">
    <div class="stat-val" style="font-size:1.2rem;color:#7B61FF;">{live['drone']}</div>
    <div class="stat-lbl">Drone shots</div>
  </div>
</div>
""", unsafe_allow_html=True)


def _simulate_analysis(stats_ph, stage_ph, prog_ph, detail_ph, t0: float) -> List[Dict]:
    """Fallback simulation with live counter."""
    rng = random.Random(42)
    frags = []
    n_stages = len(_ANALYSIS_STAGES)
    live: Dict = {"found":0,"good":0,"dupes":0,"faces":0,"drone":0,"current":""}

    for si, lbl in enumerate(_ANALYSIS_STAGES):
        prog_ph.progress((si + .5) / n_stages)
        stage_ph.markdown(
            f'<p style="color:#E8EDF2;font-size:.88rem;">'
            f'<span style="color:#00FF88;">●</span> {lbl}</p>',
            unsafe_allow_html=True,
        )

        # Simulate finding fragments during analysis
        if si == 1:  # scene detection
            for i in range(rng.randint(14, 28)):
                score = round(rng.uniform(.3, .98), 2)
                has_face = rng.random() > .45
                tags = rng.sample(["nature","wide","sky","motion","interior","close","drone","aerial"], k=rng.randint(1,3))
                frags.append({
                    "id": i,
                    "source": f"video_{(i%3)+1}.mp4",
                    "start_s": round(i*4.5, 1),
                    "end_s":   round(i*4.5 + rng.uniform(2, 9), 1),
                    "quality_score":    score,
                    "technical_score":  round(min(1, score + rng.uniform(-.1,.1)), 2),
                    "content_score":    round(rng.uniform(.3, .95), 2),
                    "aesthetic_score":  round(rng.uniform(.3, .95), 2),
                    "has_face":   has_face,
                    "has_person": has_face or rng.random() > .5,
                    "camera_motion_type": rng.choice(["static","pan","tilt","zoom"]),
                    "rejection_reason": None if score >= .42 else rng.choice([
                        "Размытый кадр (резкость ниже порога)",
                        "Слишком тёмный кадр",
                        "Сильная тряска камеры",
                    ]),
                    "selection_reason": _make_reason(score, has_face, tags),
                    "scene_tags": tags,
                    "is_duplicate": False,
                    "sharpness": round(rng.uniform(.3,.99), 2),
                    "brightness": round(rng.uniform(.2,.85), 2),
                    "camera_shake": round(rng.uniform(0,.4), 2),
                })
            live["found"] = len(frags)
        elif si == 4:
            live["faces"] = sum(1 for f in frags if f.get("has_face"))
            live["drone"] = sum(1 for f in frags if "drone" in (f.get("scene_tags") or []) or "aerial" in (f.get("scene_tags") or []))
        elif si == 6:
            live["dupes"] = rng.randint(1, 4)
            for f in frags:
                if rng.random() < .07:
                    f["is_duplicate"] = True
                    f["rejection_reason"] = "Дубль другого фрагмента"

        detail_ph.markdown(f'<p style="color:#8A9BAE;font-size:.75rem;">{lbl}...</p>', unsafe_allow_html=True)
        _render_live_stats(stats_ph, live)
        time.sleep(.55)

    elapsed = round(time.time() - t0, 1)
    st.session_state.analysis_stats = {"duplicates": live["dupes"], "elapsed_s": elapsed}
    return frags


def _make_reason(score: float, has_face: bool, tags: List[str]) -> str:
    parts = []
    if score > .8:  parts.append("высокая резкость")
    elif score > .6: parts.append("хорошая чёткость")
    if has_face:    parts.append("лицо в кадре")
    if "drone" in tags or "aerial" in tags: parts.append("красивый аэро-кадр")
    if "wide" in tags:  parts.append("широкий план")
    if "close" in tags: parts.append("крупный план")
    if "nature" in tags: parts.append("природный фон")
    if "motion" in tags: parts.append("плавное движение")
    if not parts:   parts.append("соответствует критериям качества")
    return "; ".join(parts).capitalize() + "."


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 3 · REVIEW SCENES (AI Footage Review)
# ══════════════════════════════════════════════════════════════════════════════
_ACTION_LABELS = {
    "included":  ("✓ Включена",      "b-green"),
    "excluded":  ("✕ Исключена",     "b-red"),
    "pinned":    ("📌 Закреплена",   "b-teal"),
    "forbidden": ("🚫 Запрещена",    "b-red"),
}

def _screen_scenes() -> None:
    _wizard_bar()

    frags   = st.session_state.get("scene_fragments", [])
    actions = st.session_state.get("scene_actions", {})

    n_excluded  = sum(1 for f in frags if actions.get(f["id"]) in ("excluded","forbidden"))
    n_pinned    = sum(1 for f in frags if actions.get(f["id"]) == "pinned")
    n_included  = len(frags) - n_excluded - n_pinned

    # ── Header ─────────────────────────────────────────────────────────────
    _demo_mode = any(f.get("analysis_mode") == "demo" for f in frags)
    ch, cacts = st.columns([3, 2])
    with ch:
        st.markdown("## Просмотр сцен")
        st.markdown(
            f'<p>AI нашёл <b style="color:#E8EDF2;">{len(frags)}</b> сцен · '
            f'<span class="badge b-green">{n_included} включено</span> '
            f'<span class="badge b-teal">{n_pinned} закреплено</span> '
            f'<span class="badge b-red">{n_excluded} исключено</span></p>',
            unsafe_allow_html=True,
        )
        if _demo_mode:
            st.warning("⚠️ Демо-режим: отображаются смоделированные сцены. Загрузите реальные файлы для анализа.")
    with cacts:
        if st.button("AI Summary", use_container_width=True, key="summary_btn"):
            st.session_state._show_summary = not st.session_state.get("_show_summary", False)

    # ── AI Summary inline ───────────────────────────────────────────────────
    if st.session_state.get("_show_summary"):
        _render_analysis_summary()
        st.markdown("<hr>", unsafe_allow_html=True)

    # ── Filters ─────────────────────────────────────────────────────────────
    _all_sem_tags = sorted({
        t for f in frags
        for t in (f.get("semantic_tags") or f.get("scene_tags") or [])
    })
    _tag_filter_opts = ["— все теги —"] + _all_sem_tags

    # Source video filter options
    _all_sources = sorted({Path(f.get("source", "")).name for f in frags if f.get("source")})
    _src_filter_opts = ["— все видео —"] + _all_sources

    fc1, fc2, fc3, fc4, fc5 = st.columns([2, 2, 1, 2, 2])
    with fc1:
        sort_by = st.selectbox("Сортировка", ["Рейтинг ↓", "По времени ↑", "Закреплённые сначала"], label_visibility="collapsed")
    with fc2:
        filter_state = st.selectbox("Фильтр", ["Все", "Включённые", "Исключённые", "С лицами", "Аэро"], label_visibility="collapsed")
    with fc3:
        col_count = st.selectbox("Кол", ["3", "2", "4"], label_visibility="collapsed")
    with fc4:
        tag_filter = st.selectbox("Тег", _tag_filter_opts, label_visibility="collapsed", key="scene_tag_filter")
    with fc5:
        if st.button("✓ Принять все хорошие", use_container_width=True):
            for f in frags:
                if f.get("rejection_reason") is None:
                    actions[f["id"]] = "included"
                else:
                    actions[f["id"]] = "excluded"
            st.session_state.scene_actions = actions
            st.rerun()

    # Second filter row: source video filter + quality min + grouped view
    fr2a, fr2b, fr2c, fr2d = st.columns([3, 2, 2, 2])
    with fr2a:
        if len(_all_sources) > 1:
            src_filter_val = st.selectbox(
                "Видеофайл",
                _src_filter_opts,
                label_visibility="collapsed",
                key="scene_src_filter",
            )
        else:
            src_filter_val = "— все видео —"
    with fr2b:
        min_score_opt = st.selectbox(
            "Мин. качество",
            ["Любое", "30%+", "50%+", "70%+", "85%+"],
            label_visibility="collapsed",
            key="scene_min_score",
        )
    with fr2c:
        show_grouped = st.checkbox("По видео", value=False, key="scene_grouped")
    with fr2d:
        hide_bad = st.checkbox("Скрыть плохие", value=False, key="scene_hide_bad")

    # Stats per source (shown when multiple sources)
    if len(_all_sources) > 1:
        stats_parts = []
        for src in _all_sources:
            cnt = sum(1 for f in frags if Path(f.get("source", "")).name == src)
            stats_parts.append(f'<span style="color:#8A9BAE;">{src}</span>'
                                f'<span style="color:#3B4A59;"> {cnt}</span>')
        st.markdown(
            '<div style="font-size:.72rem;color:#4A5A6A;margin-bottom:.3rem;">'
            'Сцен по файлам: ' + ' &nbsp;·&nbsp; '.join(stats_parts) + '</div>',
            unsafe_allow_html=True,
        )

    # ── Sort & filter ───────────────────────────────────────────────────────
    display = list(frags)
    if sort_by == "Рейтинг ↓":
        display.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    elif sort_by == "По времени ↑":
        display.sort(key=lambda x: (x.get("source", ""), x.get("start_s", 0)))
    else:
        display.sort(key=lambda x: (actions.get(x["id"]) != "pinned", -x.get("quality_score", 0)))

    if filter_state == "Включённые":
        display = [f for f in display if actions.get(f["id"]) not in ("excluded", "forbidden")]
    elif filter_state == "Исключённые":
        display = [f for f in display if actions.get(f["id"]) in ("excluded", "forbidden")]
    elif filter_state == "С лицами":
        display = [f for f in display if f.get("has_face")]
    elif filter_state == "Аэро":
        display = [f for f in display if
                   f.get("camera_motion_type") in ("aerial_forward", "aerial_descent") or
                   "drone" in (f.get("semantic_tags") or f.get("scene_tags") or []) or
                   "aerial" in (f.get("semantic_tags") or f.get("scene_tags") or [])]

    # Tag filter
    tag_filter = st.session_state.get("scene_tag_filter", "— все теги —")
    if tag_filter and tag_filter != "— все теги —":
        display = [f for f in display if tag_filter in (
            f.get("semantic_tags") or f.get("scene_tags") or []
        )]

    # Source video filter
    src_filter = st.session_state.get("scene_src_filter", "— все видео —")
    if src_filter and src_filter != "— все видео —":
        display = [f for f in display if Path(f.get("source", "")).name == src_filter]

    # Minimum quality filter
    _min_score_map = {"30%+": 0.30, "50%+": 0.50, "70%+": 0.70, "85%+": 0.85}
    _min_q = _min_score_map.get(st.session_state.get("scene_min_score", "Любое"), 0.0)
    if _min_q > 0:
        display = [f for f in display if f.get("quality_score", 0) >= _min_q]

    # Hide bad (rejected) scenes
    if st.session_state.get("scene_hide_bad"):
        display = [f for f in display if not f.get("rejection_reason")]

    ncols = int(col_count)
    st.markdown("<hr>", unsafe_allow_html=True)

    # ── Scene cards — grouped or flat ────────────────────────────────────────
    if st.session_state.get("scene_grouped") and len(_all_sources) > 1:
        # Group display by source video
        from collections import defaultdict as _dd
        grouped: dict = _dd(list)
        for f in display:
            grouped[Path(f.get("source", "?")).name].append(f)
        for src_name, src_frags in grouped.items():
            good = sum(1 for f in src_frags if not f.get("rejection_reason"))
            st.markdown(
                f'<div style="color:#C5CBD3;font-weight:700;font-size:.85rem;'
                f'margin:.6rem 0 .3rem;border-left:3px solid #00C870;padding-left:.5rem;">'
                f'{src_name} <span style="color:#4A5A6A;font-weight:400;">'
                f'· {len(src_frags)} сцен, {good} хороших</span></div>',
                unsafe_allow_html=True,
            )
            for row_start in range(0, len(src_frags), ncols):
                cols = st.columns(ncols)
                for ci, frag in enumerate(src_frags[row_start: row_start + ncols]):
                    with cols[ci]:
                        _scene_card(frag, actions)
    else:
        for row_start in range(0, len(display), ncols):
            cols = st.columns(ncols)
            for ci, frag in enumerate(display[row_start: row_start + ncols]):
                with cols[ci]:
                    _scene_card(frag, actions)

    if not display:
        st.markdown("""
<div style="text-align:center;padding:3rem;color:#3B4A59;">
  <div style="font-size:2rem;">🔍</div>
  <div>Нет сцен, соответствующих фильтру</div>
</div>""", unsafe_allow_html=True)

    # ── CTA ─────────────────────────────────────────────────────────────────
    st.markdown("<br><hr>", unsafe_allow_html=True)
    usable = n_included + n_pinned
    c_info, c_cta = st.columns([2,1])
    with c_info:
        if usable < 3:
            st.warning(f"⚠️ Слишком мало материала ({usable} сцен). Рекомендуется минимум 3.")
        else:
            st.markdown(f'<p style="color:#8A9BAE;">Готово {usable} сцен для монтажа. Выберите стиль.</p>', unsafe_allow_html=True)
    with c_cta:
        if st.button("Концепция ролика →", use_container_width=True):
            st.session_state.video_concept = None  # force re-compute
            _go("concept")


_MOTION_LABELS: Dict[str, str] = {
    "static":          "■ стат",
    "pan_left":        "← пан",
    "pan_right":       "→ пан",
    "tilt_up":         "↑ тилт",
    "tilt_down":       "↓ тилт",
    "zoom_in":         "🔍+ зум",
    "zoom_out":        "🔍− зум",
    "dolly":           "▶ долли",
    "orbit":           "↺ орбит",
    "handheld":        "〰 ручная",
    "aerial_forward":  "🚁 аэро",
    "aerial_descent":  "🚁↓ аэро",
    "shake":           "⚡ тряска",
    "roll":            "↻ крен",
    "unknown":         "? движение",
    # legacy
    "pan":  "← → пан",
    "tilt": "↕ тилт",
    "zoom": "🔍 зум",
}

_ROLE_LABELS: Dict[str, str] = {
    "intro":      "🎬 Вступление",
    "body":       "■ Основа",
    "outro":      "🏁 Завершение",
    "transition": "↔ Связка",
}

_CONTEXT_ICONS: Dict[str, str] = {
    "outdoor": "🌿",
    "indoor":  "🏠",
    "studio":  "🎥",
    "aerial":  "🚁",
}


def _analysis_mode_badge(mode: str) -> str:
    if mode == "demo":
        return ('<span style="background:rgba(255,140,0,.2);color:#FF9A3C;border-radius:4px;'
                'padding:.03rem .28rem;font-size:.6rem;margin-left:.3rem;font-weight:700;">DEMO</span>')
    if mode == "partial":
        return ('<span style="background:rgba(255,210,70,.18);color:#FFD246;border-radius:4px;'
                'padding:.03rem .28rem;font-size:.6rem;margin-left:.3rem;font-weight:700;">ЧАСТИЧНЫЙ</span>')
    return ""


def _scene_card(frag: Dict, actions: Dict) -> None:
    fid      = frag["id"]
    action   = actions.get(fid, "included")
    score    = frag.get("quality_score", 0)
    dur      = frag.get("end_s", 0) - frag.get("start_s", 0)
    source   = frag.get("source", "?")
    motion   = frag.get("camera_motion_type", "static")
    has_face = frag.get("has_face", False)
    reason   = frag.get("selection_reason") or frag.get("rejection_reason") or ""
    tech     = frag.get("technical_score", 0)
    aesth    = frag.get("aesthetic_score", 0)
    cont     = frag.get("content_score", 0)

    # Prefer enriched semantic_tags, fall back to scene_tags
    sem_tags  = frag.get("semantic_tags") or frag.get("scene_tags") or []
    role      = frag.get("suggested_role")
    context   = frag.get("scene_context")

    card_cls = {
        "included":  "",
        "pinned":    "pinned",
        "excluded":  "excluded",
        "forbidden": "forbidden",
    }.get(action, "")

    # Score badge
    if score >= .75:
        sb = f'<span class="badge b-green">{score:.0%}</span>'
    elif score >= .5:
        sb = f'<span class="badge b-teal">{score:.0%}</span>'
    else:
        sb = f'<span class="badge b-red">{score:.0%}</span>'

    action_lbl, action_cls = _ACTION_LABELS.get(action, ("Включена", "b-gray"))
    motion_lbl  = _MOTION_LABELS.get(motion, motion or "?")
    face_icon   = "👤 " if has_face else ""
    ctx_icon    = _CONTEXT_ICONS.get(context, "") + " " if context else ""

    # Semantic tag chips — show up to 4
    tag_html = "".join(
        f'<span style="background:#1A2228;color:#8A9BAE;border-radius:6px;'
        f'padding:.08rem .4rem;font-size:.65rem;">{t}</span>'
        for t in sem_tags[:4]
    )

    # Role hint (only when enriched)
    role_html = ""
    if role and role != "body":
        role_lbl = _ROLE_LABELS.get(role, role)
        role_html = f'<span style="color:#FFD246;font-size:.65rem;">{role_lbl}</span>'

    # Thumbnail — prefer pre-generated file, fall back to live extraction
    thumb_b64: Optional[str] = None
    _thumb_abs = frag.get("_thumb_abs")
    if _thumb_abs and Path(_thumb_abs).exists():
        try:
            import base64 as _b64
            with open(_thumb_abs, "rb") as _tf:
                thumb_b64 = _b64.b64encode(_tf.read()).decode()
        except Exception:
            thumb_b64 = None
    if not thumb_b64 and frag.get("_abs_path"):
        # Live extraction: only if abs_path valid and times are non-zero
        _t_mid = (frag.get("start_s", 0) + frag.get("end_s", 0)) / 2
        if _t_mid > 0 or frag.get("end_s", 0) > 0:
            thumb_b64 = _extract_thumb(frag["_abs_path"], _t_mid if _t_mid > 0 else 1.0)

    reject_block = ""
    if frag.get("rejection_reason"):
        reject_block = (f'<div style="color:#FF4C6A;font-size:.72rem;margin-top:.3rem;">'
                        f'✕ {frag["rejection_reason"]}</div>')

    # Scene feature indicators
    sharpness  = frag.get("sharpness", 0.0)
    brightness = frag.get("brightness", 0.0)
    shake      = frag.get("camera_shake", 0.0)
    has_person = frag.get("has_person", False)

    def _quality_dot(val: float, invert: bool = False) -> str:
        v = (1 - val) if invert else val
        c = "#00FF88" if v >= 0.7 else ("#FFD246" if v >= 0.4 else "#FF4C6A")
        return f'<span style="color:{c};">●</span>'

    feature_html = (
        f'{_quality_dot(sharpness)} резк&nbsp;'
        f'{_quality_dot(brightness)} свет&nbsp;'
        f'{_quality_dot(shake, invert=True)} стаб&nbsp;'
        f'{"👤" if has_face else ""}'
        f'{"🧍" if has_person and not has_face else ""}'
    )

    # Analysis mode indicator
    mode = frag.get("analysis_mode", "real")
    mode_badge = _analysis_mode_badge(mode)
    if mode == "real":
        mode_badge = ('<span style="background:rgba(0,255,136,.12);color:#00C870;border-radius:4px;'
                      'padding:.03rem .28rem;font-size:.6rem;margin-left:.3rem;font-weight:700;">REAL</span>')
    elif mode == "cached":
        mode_badge = ('<span style="background:rgba(0,180,217,.12);color:#00B8D9;border-radius:4px;'
                      'padding:.03rem .28rem;font-size:.6rem;margin-left:.3rem;font-weight:700;">CACHE</span>')

    st.markdown(f"""
<div class="vp-card {card_cls}" style="margin-bottom:.7rem;">
  <div class="scene-thumb">
    {_thumb_html(thumb_b64, face_icon + "🎬")}
    <div class="thumb-overlay"></div>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.35rem;">
    {sb}
    <span class="badge {action_cls}" style="font-size:.62rem;">{action_lbl}</span>
  </div>
  <div style="font-size:.75rem;color:#8A9BAE;margin-bottom:.15rem;line-height:1.5;">
    <span style="color:#C5CBD3;font-weight:600;" title="{source}">{Path(source).name}</span>
    {mode_badge}
  </div>
  <div style="font-size:.72rem;color:#4A5A6A;margin-bottom:.2rem;">
    <span style="color:#8A9BAE;">{frag.get('start_s', 0):.1f}s</span>
    <span style="color:#3B4A59;"> → </span>
    <span style="color:#8A9BAE;">{frag.get('end_s', 0):.1f}s</span>
    <span style="color:#5A6A7A;margin-left:.3rem;">· {dur:.1f}с</span>
    <span style="background:#12171D;color:#8A9BAE;border-radius:4px;padding:.03rem .28rem;
          font-size:.63rem;margin-left:.3rem;">{motion_lbl}</span>
    {role_html}
  </div>
  <div style="font-size:.68rem;color:#4A5A6A;margin-bottom:.2rem;">{feature_html}</div>
  <div class="ai-explain">{reason[:110]}{"…" if len(reason)>110 else ""}</div>
  {reject_block}
  <div style="display:flex;gap:.25rem;flex-wrap:wrap;margin-top:.4rem;">{tag_html}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.25rem;margin-top:.5rem;">
    <div style="font-size:.65rem;color:#8A9BAE;text-align:center;">
      <div style="color:#00FF88;font-weight:700;">{tech:.0%}</div>Техника
    </div>
    <div style="font-size:.65rem;color:#8A9BAE;text-align:center;">
      <div style="color:#00D4FF;font-weight:700;">{cont:.0%}</div>Контент
    </div>
    <div style="font-size:.65rem;color:#8A9BAE;text-align:center;">
      <div style="color:#7B61FF;font-weight:700;">{aesth:.0%}</div>Эстетика
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    # Action buttons
    b1, b2, b3 = st.columns(3)
    b4, b5, b6 = st.columns(3)

    with b1:
        if st.button("▶ Preview", key=f"prev_{fid}", use_container_width=True):
            st.session_state[f"_preview_{fid}"] = not st.session_state.get(f"_preview_{fid}", False)

    with b2:
        lbl = "📌 Убрать" if action == "pinned" else "📌 Pin"
        if st.button(lbl, key=f"pin_{fid}", use_container_width=True):
            actions[fid] = "included" if action == "pinned" else "pinned"
            st.session_state.scene_actions = actions
            st.rerun()

    with b3:
        lbl = "✓ Вернуть" if action == "excluded" else "✕ Убрать"
        if st.button(lbl, key=f"excl_{fid}", use_container_width=True):
            actions[fid] = "included" if action == "excluded" else "excluded"
            st.session_state.scene_actions = actions
            st.rerun()

    with b4:
        lbl = "✓ Включить" if action in ("excluded","forbidden") else "✓ Included"
        if action not in ("excluded","forbidden"):
            lbl = "✓ Вкл."
        if st.button(lbl, key=f"inc_{fid}", use_container_width=True):
            actions[fid] = "included"
            st.session_state.scene_actions = actions
            st.rerun()

    with b5:
        lbl = "🚫 Снять" if action == "forbidden" else "🚫 Запрет"
        if st.button(lbl, key=f"forb_{fid}", use_container_width=True):
            actions[fid] = "included" if action == "forbidden" else "forbidden"
            st.session_state.scene_actions = actions
            st.rerun()

    with b6:
        expl_lbl = "✕ Детали" if st.session_state.get(f"_explain_{fid}") else "🔍 Детали"
        if st.button(expl_lbl, key=f"expl_{fid}", use_container_width=True):
            st.session_state[f"_explain_{fid}"] = not st.session_state.get(f"_explain_{fid}", False)

    # Style fit explanation panel
    if st.session_state.get(f"_explain_{fid}"):
        style_id = st.session_state.get("selected_style", "")
        style_fit = frag.get("style_fit_scores", {})
        fit_val  = style_fit.get(style_id) if isinstance(style_fit, dict) else None
        expl     = frag.get("_style_explanation", "")

        lines = []
        lines.append(f"**Качество:** {frag.get('quality_score', 0):.0%}")
        lines.append(f"**Резкость:** {frag.get('sharpness', 0):.0%}")
        lines.append(f"**Яркость:** {frag.get('brightness', 0):.0%}")
        lines.append(f"**Тряска:** {frag.get('camera_shake', 0):.0%}")
        if fit_val is not None and style_id:
            style_lbl = next((p["label"] for p in _STYLE_PRESETS if p["id"] == style_id), style_id)
            lines.append(f"**Стиль «{style_lbl}»:** {fit_val:.0%}")
        if expl:
            lines.append(f"*{expl}*")
        if frag.get("rejection_reason"):
            lines.append(f"⚠ **Проблема:** {frag['rejection_reason']}")
        st.markdown(
            '<div style="background:#0D1318;border:1px solid #1A2228;border-radius:10px;'
            'padding:.6rem .85rem;font-size:.78rem;color:#8A9BAE;margin:.35rem 0;">'
            + "<br>".join(lines) + "</div>",
            unsafe_allow_html=True,
        )

    # Inline preview — extract exact scene clip so user sees only that segment
    if st.session_state.get(f"_preview_{fid}"):
        abs_path = frag.get("_abs_path")
        start_s  = float(frag.get("start_s", 0))
        end_s    = float(frag.get("end_s", 0))
        if abs_path and Path(abs_path).exists():
            with st.spinner("Нарезаем клип…"):
                clip_path = _extract_scene_clip(abs_path, start_s, end_s)
            if clip_path and Path(clip_path).exists():
                st.video(clip_path)
            else:
                # Fallback: show source from start_s (will play past end_s but at least starts right)
                st.video(abs_path, start_time=int(start_s))
                st.caption(f"⚠ Клип не удалось вырезать · {start_s:.1f}s–{end_s:.1f}s")
        else:
            st.info("Файл недоступен для предпросмотра. Откройте через файловый менеджер.")


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 4 · CONCEPT
# ══════════════════════════════════════════════════════════════════════════════
_CONCEPT_TYPE_RU = {
    "travel":  "Путешествие", "wedding": "Свадьба", "sport": "Спорт",
    "event":   "Мероприятие", "product": "Продукт", "nature": "Природа",
    "other":   "Смешанный контент",
}
_CONCEPT_ARC_RU = {
    "three_act":     "Три акта (завязка → кульминация → развязка)",
    "journey":       "Путешествие (начало → путь → финал)",
    "highlight_reel":"Хайлайты (лучшие моменты)",
    "montage":       "Монтаж (атмосферная нарезка)",
}
_ENERGY_RU = {
    "high": "Высокая", "low": "Спокойная",
    "medium": "Умеренная", "dynamic": "Переменная",
}
_CONCEPT_STYLE_HINT = {
    "travel":  "dynamic_travel",
    "nature":  "cinematic_nature",
    "wedding": "family_memories",
    "sport":   "fast_reels",
    "event":   "fast_reels",
    "product": "luxury_promo",
    "other":   "dynamic_travel",
}


def _concept_field(concept, key: str, default: str = "") -> str:
    """Read a field from the stored video concept regardless of its shape.

    `st.session_state["video_concept"]` may be a ConceptResult dataclass, a
    plain dict, None, or the sentinel False (analysis failed). Accessing it as
    either an object or a dict directly is fragile — always go through this.
    """
    if not concept:                       # None or False sentinel
        return default
    if isinstance(concept, dict):
        return concept.get(key, default) or default
    return getattr(concept, key, default) or default


def _screen_concept() -> None:
    _wizard_bar()
    st.button("← Назад", key="back_concept", on_click=_back)
    st.markdown("## Концепция ролика")
    st.markdown('<p>AI проанализировал ваш материал и предлагает структуру будущего ролика.</p>',
                unsafe_allow_html=True)

    frags = st.session_state.get("scene_fragments", [])

    # Compute concept once
    if st.session_state.get("video_concept") is None:
        with st.spinner("Определяем концепцию…"):
            try:
                from analysis.intelligence.concept_service import ConceptService
                result = ConceptService().infer(frags)
                st.session_state.video_concept = result
            except Exception as exc:
                logger.warning(f"[Concept] {exc}")
                st.session_state.video_concept = False  # sentinel: failed

    concept = st.session_state.get("video_concept")

    if concept and concept is not False:
        c_type  = _CONCEPT_TYPE_RU.get(concept.concept_type, concept.concept_type)
        c_arc   = _CONCEPT_ARC_RU.get(concept.narrative_arc,  concept.narrative_arc)
        c_energy= _ENERGY_RU.get(concept.energy_profile, concept.energy_profile)
        c_conf  = concept.confidence
        c_tags  = concept.dominant_tags or []

        # ── Concept card ───────────────────────────────────────────────────────
        tag_pills = "".join(
            f'<span class="badge b-teal" style="margin:.1rem .15rem 0 0;">{t}</span>'
            for t in c_tags
        )
        conf_color = "#00FF88" if c_conf > 0.65 else ("#FFD246" if c_conf > 0.40 else "#FF4C6A")
        st.markdown(f"""
<div class="vp-card" style="margin-bottom:1.2rem;">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;flex-wrap:wrap;">
    <div>
      <div style="font-size:1.5rem;font-weight:800;color:#E8EDF2;">{c_type}</div>
      <div style="font-size:.85rem;color:#8A9BAE;margin:.2rem 0 .5rem;">{concept.description}</div>
      <div style="font-size:.8rem;color:#8A9BAE;">
        Структура: <b style="color:#E8EDF2;">{c_arc}</b><br>
        Энергетика: <b style="color:#E8EDF2;">{c_energy}</b>
      </div>
    </div>
    <div style="text-align:right;flex-shrink:0;">
      <div style="font-size:2rem;font-weight:800;color:{conf_color};">{c_conf:.0%}</div>
      <div style="font-size:.7rem;color:#8A9BAE;">уверенность</div>
    </div>
  </div>
  <div style="margin-top:.6rem;">{tag_pills}</div>
</div>
""", unsafe_allow_html=True)

        # ── Material found ─────────────────────────────────────────────────────
        st.markdown("### Найденный материал")
        all_tags: Dict[str, int] = {}
        motion_counts: Dict[str, int] = {}
        n_faces = n_aerial = n_good = 0
        for f in frags:
            for t in (f.get("semantic_tags") or f.get("scene_tags") or []):
                all_tags[t] = all_tags.get(t, 0) + 1
            m = f.get("camera_motion_type", "unknown")
            motion_counts[m] = motion_counts.get(m, 0) + 1
            if f.get("has_face"):
                n_faces += 1
            if m in ("aerial_forward", "aerial_descent") or \
               "drone" in (f.get("semantic_tags") or []):
                n_aerial += 1
            if not f.get("rejection_reason"):
                n_good += 1

        top_tags  = sorted(all_tags.items(), key=lambda x: -x[1])[:8]
        top_motions = sorted(motion_counts.items(), key=lambda x: -x[1])[:5]

        col_mat1, col_mat2, col_mat3 = st.columns(3)
        with col_mat1:
            st.markdown(f"""
<div class="vp-card">
  <div class="stat-val">{len(frags)}</div>
  <div class="stat-lbl">Всего сцен</div>
  <div style="font-size:.72rem;color:#8A9BAE;margin-top:.3rem;">{n_good} без проблем</div>
</div>""", unsafe_allow_html=True)
        with col_mat2:
            st.markdown(f"""
<div class="vp-card">
  <div class="stat-val">{n_faces}</div>
  <div class="stat-lbl">Сцен с людьми</div>
  <div style="font-size:.72rem;color:#8A9BAE;margin-top:.3rem;">{n_aerial} аэро</div>
</div>""", unsafe_allow_html=True)
        with col_mat3:
            top_motion_lbl = _MOTION_LABELS.get(top_motions[0][0], top_motions[0][0]) if top_motions else "—"
            st.markdown(f"""
<div class="vp-card">
  <div class="stat-val" style="font-size:1.1rem;">{top_motion_lbl}</div>
  <div class="stat-lbl">Главное движение</div>
  <div style="font-size:.72rem;color:#8A9BAE;margin-top:.3rem;">{top_motions[0][1] if top_motions else 0} кл.</div>
</div>""", unsafe_allow_html=True)

        if top_tags:
            st.markdown(
                "**Основные темы:** " +
                " ".join(f'<span class="badge b-gray">{t} ×{c}</span>' for t, c in top_tags),
                unsafe_allow_html=True,
            )

        # ── Recommended structure ──────────────────────────────────────────────
        st.markdown("### Рекомендуемая структура")
        target = st.session_state.get("target_duration", 30)

        # Build structure based on narrative_arc and concept_type
        arc = concept.narrative_arc
        if arc == "three_act":
            structure = [
                ("🎬 Вступление",  int(target * 0.15), "Вводный кадр, задаёт атмосферу"),
                ("■ Основная часть", int(target * 0.65), "Основной материал, лучшие моменты"),
                ("💡 Кульминация",  int(target * 0.10), "Самый сильный момент"),
                ("🏁 Финал",        int(target * 0.10), "Завершающий кадр"),
            ]
        elif arc == "journey":
            structure = [
                ("🚀 Старт",    int(target * 0.20), "Начало путешествия / общий план"),
                ("🗺 Путь",     int(target * 0.60), "Основные моменты"),
                ("🏁 Финал",   int(target * 0.20), "Итог / красивый завершающий кадр"),
            ]
        elif arc == "highlight_reel":
            structure = [
                ("⚡ Хук",      int(target * 0.10), "Захватывающий первый кадр"),
                ("⚡ Хайлайты", int(target * 0.80), "Динамичная нарезка лучших моментов"),
                ("⚡ Финал",    int(target * 0.10), "Завершение в такт музыке"),
            ]
        else:  # montage
            structure = [
                ("🎬 Открытие",    int(target * 0.15), "Вступительный кадр"),
                ("■ Монтаж",       int(target * 0.75), "Атмосферная нарезка"),
                ("🏁 Завершение",  int(target * 0.10), "Финальный кадр"),
            ]

        for role_lbl, dur_s, desc in structure:
            st.markdown(f"""
<div style="display:flex;align-items:center;gap:.75rem;padding:.5rem .75rem;
     background:#12171D;border:1px solid #1A2228;border-radius:10px;margin-bottom:.4rem;">
  <span style="font-weight:700;color:#E8EDF2;min-width:160px;">{role_lbl}</span>
  <span style="color:#00FF88;font-weight:700;min-width:50px;">{dur_s}с</span>
  <span style="color:#8A9BAE;font-size:.82rem;">{desc}</span>
</div>""", unsafe_allow_html=True)

        # ── Style recommendation ───────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        hint_style_id = _CONCEPT_STYLE_HINT.get(concept.concept_type, "dynamic_travel")
        hint_style = next((p for p in _STYLE_PRESETS if p["id"] == hint_style_id), None)
        if hint_style:
            st.markdown(f"""
<div class="vp-card" style="border-color:#00FF8844;">
  <div style="font-size:.75rem;font-weight:700;color:#00FF88;text-transform:uppercase;
       letter-spacing:.06em;margin-bottom:.3rem;">Рекомендуемый стиль монтажа</div>
  <div style="display:flex;align-items:center;gap:.75rem;">
    <span style="font-size:1.8rem;">{hint_style["icon"]}</span>
    <div>
      <div style="font-weight:700;color:#E8EDF2;">{hint_style["label"]}</div>
      <div style="font-size:.8rem;color:#8A9BAE;">{hint_style["desc"]}</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if st.button(f"Применить «{hint_style['label']}»", use_container_width=True):
                    st.session_state.selected_style = hint_style_id
                    _go("style")
    else:
        st.info(
            "Концепцию не удалось определить — слишком мало материала или "
            "семантика не распознана. Нажмите «Выбрать стиль» для ручного выбора."
        )

    st.markdown("<br>", unsafe_allow_html=True)
    col = st.columns([1, 2, 1])[1]
    with col:
        if st.button("Выбрать стиль вручную →", use_container_width=True):
            _go("style")


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 5 · STYLE SELECTION
# ══════════════════════════════════════════════════════════════════════════════
def _screen_style() -> None:
    _wizard_bar()
    st.button("← Назад", key="back_style", on_click=_back)

    st.markdown("## Выберите стиль")
    st.markdown('<p>Стиль определяет темп, переходы и общее настроение ролика.</p>', unsafe_allow_html=True)

    selected = st.session_state.get("selected_style")
    cols = st.columns(3)
    for i, p in enumerate(_STYLE_PRESETS):
        with cols[i % 3]:
            is_sel = selected == p["id"]
            border = p["accent"] if is_sel else "#232B36"
            bg     = "#15201A" if is_sel else "#181F27"
            sel_badge = f'<span class="badge b-green">✓ Выбран</span>' if is_sel else ""
            tag_html  = "".join(f'<span style="background:#232B36;color:#8A9BAE;border-radius:6px;padding:.08rem .4rem;font-size:.68rem;">{t}</span>' for t in p["tags"])

            st.markdown(f"""
<div class="vp-card" style="border-color:{border};background:{bg};margin-bottom:.6rem;
    {'box-shadow:0 0 20px '+p['accent']+'22;' if is_sel else ''}">
  <div style="font-size:2rem;margin-bottom:.35rem;">{p['icon']}</div>
  <div style="font-weight:700;color:#E8EDF2;margin-bottom:.15rem;">{p['label']}</div>
  <div style="font-size:.78rem;color:#8A9BAE;margin-bottom:.4rem;min-height:2.5em;">{p['desc']}</div>
  <div style="display:flex;gap:.3rem;flex-wrap:wrap;margin-bottom:.4rem;">{tag_html}</div>
  <div style="font-size:.7rem;color:#3B4A59;">Переход: <b style="color:#8A9BAE;">{p['transition']}</b>
    &nbsp;·&nbsp; Темп: <b style="color:#8A9BAE;">{p['pace']}</b></div>
  <div style="margin-top:.4rem;">{sel_badge}</div>
</div>
""", unsafe_allow_html=True)
            if st.button("Выбрать" if not is_sel else "✓ Выбран", key=f"sty_{p['id']}", use_container_width=True):
                st.session_state.selected_style = p["id"]
                st.rerun()

    # ── Color Grading ────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("🎨 Цветокоррекция (опционально)", expanded=False):
        cg = st.session_state.get("color_grading", {})
        st.markdown('<p style="font-size:.8rem;color:#8A9BAE;margin-bottom:.5rem;">Настройки применяются поверх стиля к финальному рендеру</p>', unsafe_allow_html=True)
        cc1, cc2 = st.columns(2)
        with cc1:
            cg["brightness"] = st.slider("Яркость",        -0.30, 0.30, float(cg.get("brightness", 0.0)),  0.01, key="cg_bright",   format="%+.2f")
            cg["contrast"]   = st.slider("Контраст",       -0.30, 0.30, float(cg.get("contrast",   0.0)),  0.01, key="cg_contrast", format="%+.2f")
        with cc2:
            cg["saturation"] = st.slider("Насыщенность",   -0.50, 0.50, float(cg.get("saturation", 0.0)),  0.01, key="cg_sat",      format="%+.2f")
            cg["warmth"]     = st.slider("Тепло/Холод",    -0.30, 0.30, float(cg.get("warmth",     0.0)),  0.01, key="cg_warmth",   format="%+.2f")
        cg["vignette"]       = st.checkbox("Виньетка", value=bool(cg.get("vignette", False)), key="cg_vignette")
        if st.button("Сбросить", key="cg_reset"):
            st.session_state.color_grading = {"brightness": 0.0, "contrast": 0.0, "saturation": 0.0, "warmth": 0.0, "vignette": False}
            st.rerun()
        st.session_state.color_grading = cg

    can_go = bool(st.session_state.get("selected_style"))
    col = st.columns([1,2,1])[1]
    with col:
        if st.button("Выбрать формат →", disabled=not can_go, use_container_width=True):
            _go("format")


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 5 · FORMAT & DURATION
# ══════════════════════════════════════════════════════════════════════════════
def _screen_format() -> None:
    _wizard_bar()
    st.button("← Назад", key="back_fmt", on_click=_back)

    st.markdown("## Формат и длина")
    st.markdown('<p>Выберите платформу — разрешение и соотношение сторон подберётся автоматически.</p>', unsafe_allow_html=True)

    sel_fmt = st.session_state.get("selected_format")
    target  = st.session_state.get("target_duration", 30)

    st.markdown("### Платформа")
    cols = st.columns(4)
    for i, fmt in enumerate(_FORMAT_OPTIONS):
        with cols[i % 4]:
            is_sel = sel_fmt == fmt["id"]
            border = "#00FF88" if is_sel else "#232B36"
            bg     = "#15201A" if is_sel else "#181F27"
            st.markdown(f"""
<div class="vp-card" style="border-color:{border};background:{bg};text-align:center;
    padding:.75rem;margin-bottom:.5rem;
    {'box-shadow:0 0 14px rgba(0,255,136,.15);' if is_sel else ''}">
  <div style="font-size:1.5rem;">{fmt['icon']}</div>
  <div style="font-weight:700;font-size:.82rem;color:#E8EDF2;margin:.15rem 0;">{fmt['label']}</div>
  <div style="font-size:.68rem;color:#8A9BAE;">{fmt['ratio']} · {fmt['w']}×{fmt['h']}</div>
</div>
""", unsafe_allow_html=True)
            if st.button("✓" if is_sel else "Выбрать", key=f"fmt_{fmt['id']}", use_container_width=True):
                st.session_state.selected_format = fmt["id"]
                st.rerun()

    st.markdown("<br>### Длина ролика")
    dur_opts = [15, 30, 60, 90]
    dc = st.columns(len(dur_opts) + 1)
    for i, d in enumerate(dur_opts):
        with dc[i]:
            is_sel = target == d
            border = "#00D4FF" if is_sel else "#232B36"
            bg     = "#0D1A20" if is_sel else "#12171D"
            st.markdown(f"""
<div style="background:{bg};border:1px solid {border};border-radius:10px;
            text-align:center;padding:.6rem;margin-bottom:.3rem;
            {'box-shadow:0 0 10px rgba(0,212,255,.12);' if is_sel else ''}">
  <div style="font-weight:700;color:#E8EDF2;">{d} сек</div>
</div>
""", unsafe_allow_html=True)
            if st.button(str(d), key=f"dur_{d}", use_container_width=True):
                st.session_state.target_duration = d
                st.rerun()

    with dc[-1]:
        custom = st.number_input("Custom", min_value=5, max_value=600, value=int(target), step=5, label_visibility="collapsed")
        if st.button("Задать", key="dur_custom", use_container_width=True):
            st.session_state.target_duration = custom
            st.rerun()

    # Summary row
    fmt_label = next((f["label"] for f in _FORMAT_OPTIONS if f["id"] == sel_fmt), "—")
    style_label = next((p["label"] for p in _STYLE_PRESETS if p["id"] == st.session_state.get("selected_style")), "—")
    st.markdown(f"""
<div style="margin:1rem 0;padding:.75rem 1.1rem;background:#12171D;border:1px solid #1A2228;
            border-radius:12px;display:flex;gap:1.5rem;align-items:center;flex-wrap:wrap;">
  <span style="color:#8A9BAE;font-size:.82rem;">Итог:</span>
  <b style="color:#E8EDF2;">{style_label}</b>
  <span style="color:#1A2228;">·</span>
  <b style="color:#E8EDF2;">{fmt_label}</b>
  <span style="color:#1A2228;">·</span>
  <b style="color:#00D4FF;">{target} сек</b>
</div>
""", unsafe_allow_html=True)

    can_go = bool(sel_fmt)
    col = st.columns([1,2,1])[1]
    with col:
        if st.button("✦  Построить черновик монтажа", disabled=not can_go, use_container_width=True):
            _build_timeline()
            _go("timeline")


@st.cache_data(show_spinner=False)
def _detect_beats(audio_path: str) -> List[float]:
    """Return sorted beat timestamps from audio file. Cached per path."""
    try:
        from analysis.music.beat_detector import BeatDetector
        result = BeatDetector().detect(audio_path)
        times = result.get("times") or result.get("beat_times") or []
        return sorted(float(t) for t in times)
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def _extract_scene_clip(abs_path: str, start_s: float, end_s: float) -> Optional[str]:
    """Extract [start_s, end_s] to a temp MP4 for inline preview. Returns path or None."""
    dur = end_s - start_s
    if dur < 0.1:
        return None
    try:
        import subprocess
        import hashlib
        h = hashlib.md5(f"{abs_path}:{start_s:.3f}:{end_s:.3f}".encode()).hexdigest()[:12]
        tmp_dir = Path(tempfile.gettempdir()) / "avp_clips"
        tmp_dir.mkdir(exist_ok=True)
        out = str(tmp_dir / f"scene_{h}.mp4")
        if Path(out).exists() and Path(out).stat().st_size > 500:
            return out
        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(start_s),
            "-i", abs_path,
            "-t", str(min(dur + 0.1, 30.0)),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            out,
        ], check=True, capture_output=True, timeout=30)
        return out if Path(out).exists() and Path(out).stat().st_size > 500 else None
    except Exception:
        return None


def _snap_to_beat(dur: float, position_s: float, beats: List[float], tol: float = 0.15) -> float:
    """Adjust dur so the cut lands on the nearest beat within tol seconds."""
    if not beats:
        return dur
    cut_time = position_s + dur
    closest = min(beats, key=lambda b: abs(b - cut_time))
    if abs(closest - cut_time) <= tol:
        return max(0.5, dur + (closest - cut_time))
    return dur


def _score_for_style(seg: dict, style_id: str) -> float:
    """
    Return a composite relevance score for this segment under the given style/concept.
    Different styles produce DIFFERENT rankings — same scene can score 0.3 in one
    style and 0.9 in another.
    """
    base = seg.get("quality_score", 0.5)

    # StyleFitService pre-computed score takes priority
    style_fit = seg.get("style_fit_scores", {})
    if isinstance(style_fit, dict) and style_id in style_fit:
        return float(style_fit[style_id])

    motion     = seg.get("camera_motion_type", "static")
    tags       = set(seg.get("semantic_tags") or seg.get("scene_tags") or [])
    has_face   = bool(seg.get("has_face"))
    has_person = bool(seg.get("has_person"))
    sharpness  = seg.get("sharpness", 0.5)
    brightness = seg.get("brightness", 0.5)
    shake      = seg.get("camera_shake", 0.0)
    motion_mag = seg.get("motion_magnitude", 0.3)

    boost = 0.0

    # ── Style-specific scoring profiles ──────────────────────────────────────

    if style_id in ("dynamic_reels", "sport_highlight", "f1_style"):
        # DYNAMIC: short fast clips, active motion required
        if motion in ("pan_left", "pan_right", "dolly", "zoom_in", "zoom_out", "shake", "handheld"):
            boost += 0.20
        if motion_mag > 0.4:
            boost += 0.12
        if tags & {"action", "sport", "crowd", "race", "jump"}:
            boost += 0.15
        if motion == "static" and motion_mag < 0.2:
            boost -= 0.20   # static shots penalised heavily
        if shake > 0.5:
            boost += 0.08   # shaky cam is OK for action
        if sharpness < 0.4:
            boost -= 0.10   # motion blur OK, complete blur not

    elif style_id in ("cinematic", "wedding", "promo"):
        # CINEMATIC: slow stable shots, faces, clean frames
        if motion in ("static", "dolly", "pan_left", "pan_right", "tilt_up", "tilt_down"):
            boost += 0.18
        if tags & {"face_closeup", "landscape", "sunset", "indoor", "detail"}:
            boost += 0.12
        if has_face:
            boost += 0.15
        if motion in ("shake", "handheld") and shake > 0.4:
            boost -= 0.25   # shaky very bad for cinematic
        if sharpness < 0.5:
            boost -= 0.12
        if brightness < 0.2:
            boost -= 0.10   # dark frames bad for promo

    elif style_id in ("travel_vlog", "travel"):
        # TRAVEL: mix of panoramas, locations, movement
        if motion in ("aerial_forward", "aerial_descent", "pan_left", "pan_right", "dolly"):
            boost += 0.18
        if tags & {"drone", "aerial", "landscape", "nature", "beach", "mountain", "city", "road"}:
            boost += 0.18
        if motion_mag > 0.2:
            boost += 0.08
        if shake > 0.6:
            boost -= 0.15
        if tags & {"indoor"} and not has_face:
            boost -= 0.08   # boring indoors less relevant for travel

    elif style_id in ("drone_nature", "nature"):
        # NATURE/DRONE: stable smooth shots, landscapes, minimal people
        if motion in ("aerial_forward", "aerial_descent", "dolly", "pan_left", "pan_right"):
            boost += 0.22
        if tags & {"drone", "aerial", "landscape", "nature", "sky", "water", "forest", "mountain"}:
            boost += 0.20
        if shake > 0.3:
            boost -= 0.25   # stability critical for drone/nature
        if has_person and not tags & {"nature", "outdoor"}:
            boost -= 0.08   # people less relevant unless outdoor context
        if brightness < 0.15:
            boost -= 0.15   # dark nature shots less useful

    elif style_id in ("people", "event", "instagram_reels"):
        # PEOPLE: faces, emotions, clear shots with people
        if has_face:
            boost += 0.25
        if has_person:
            boost += 0.15
        if sharpness < 0.4 and has_face:
            boost -= 0.20   # blurry face shots are unusable
        if motion in ("static", "dolly"):
            boost += 0.08
        if motion == "static" and has_face:
            boost += 0.10   # stable face shot is best for people content
        if shake > 0.5:
            boost -= 0.15
        if not has_person and not has_face:
            boost -= 0.15   # no people = low priority for this concept

    else:
        # Generic fallback
        if motion in ("pan_left", "pan_right", "dolly"):
            boost += 0.08
        if tags & {"landscape", "nature", "city"}:
            boost += 0.05
        if shake > 0.7:
            boost -= 0.12

    # ── Concept-based fine-tuning (stacks on top of style) ───────────────────
    try:
        concept = st.session_state.get("video_concept")
        energy  = _concept_field(concept, "energy_profile")
        c_type  = _concept_field(concept, "concept_type")

        if energy == "high":
            if motion in ("pan_left", "pan_right", "dolly", "zoom_in", "shake", "handheld"):
                boost += 0.08
            elif motion == "static" and motion_mag < 0.15:
                boost -= 0.06
        elif energy == "low":
            if motion in ("static", "dolly"):
                boost += 0.08
            elif motion in ("shake", "handheld") and shake > 0.4:
                boost -= 0.10

        if c_type == "travel":
            if tags & {"aerial", "drone", "landscape", "nature", "beach", "mountain", "city"}:
                boost += 0.10
        elif c_type in ("wedding", "event"):
            if has_face or has_person:
                boost += 0.10
        elif c_type == "sport":
            if motion in ("pan_left", "pan_right", "zoom_in", "handheld", "shake"):
                boost += 0.10
        elif c_type == "nature":
            if tags & {"nature", "outdoor", "landscape", "sky", "water"}:
                boost += 0.10
        elif c_type == "drone":
            if motion in ("aerial_forward", "aerial_descent") or "drone" in tags:
                boost += 0.12
    except Exception:
        pass

    return min(1.0, max(0.0, base + boost))


def _seg_dynamics(seg: dict) -> float:
    """Numeric 0..1 'how dynamic is this clip', with graceful fallbacks.

    Scene fragments don't always carry the same signals, so we try the richest
    one available before degrading: explicit motion → energy_score → a coarse
    estimate from the camera motion category.
    """
    for key in ("motion_magnitude", "energy_score"):
        v = seg.get(key)
        if isinstance(v, (int, float)):
            return max(0.0, min(1.0, float(v)))
    motion = (seg.get("camera_motion_type") or "static").lower()
    _MOTION_DYN = {
        "static": 0.1, "tilt_up": 0.4, "tilt_down": 0.4,
        "pan_left": 0.5, "pan_right": 0.5, "zoom_in": 0.55, "zoom_out": 0.55,
        "dolly": 0.6, "handheld": 0.7, "shake": 0.8,
        "aerial": 0.75, "aerial_descent": 0.8,
    }
    for frag, dyn in _MOTION_DYN.items():
        if frag in motion:
            return dyn
    return 0.5


# ══════════════════════════════════════════════════════════════════════════════
# ROADMAP Фазы 2/3/6/7/8 — музыкальный контекст, скоринг, метрики, переходы
# ══════════════════════════════════════════════════════════════════════════════

def _detect_music_context(audio_path: str) -> dict:
    """Биты, сильные доли (downbeats), темп (BPM) и секции трека за проход.

    Фаза 2 (BS-1/BS-3/BS-4): источник истины о музыке для пейсинга и привязки
    склеек. Деградирует мягко — при любой ошибке возвращает пустые поля.
    """
    ctx = {"beats": [], "strong_beats": [], "tempo": 0.0, "sections": []}
    if not audio_path or not Path(audio_path).exists():
        return ctx
    try:
        from analysis.music.beat_detector import BeatDetector
        res = BeatDetector().detect(audio_path)
        beats = sorted(float(t) for t in (res.get("times") or []))
        ctx["beats"] = beats
        ctx["strong_beats"] = sorted(float(t) for t in (res.get("strong_beats") or []))
        if len(beats) >= 2:
            import statistics
            period = statistics.median(beats[i + 1] - beats[i] for i in range(len(beats) - 1))
            ctx["tempo"] = round(60.0 / period, 1) if period > 0 else 0.0
    except Exception as exc:
        logger.debug("[music_ctx] beats failed: %s", exc)
    try:
        from analysis.music.energy_analyzer import EnergyAnalyzer
        from analysis.music.section_detector import SectionDetector
        energy = EnergyAnalyzer().analyze(audio_path)
        ctx["sections"] = SectionDetector().detect(
            audio_path, energy=energy, beats={"times": ctx["beats"]}
        )
    except Exception as exc:
        logger.debug("[music_ctx] sections failed: %s", exc)
    return ctx


def _pacing_clip_len(tempo: float, pace_hint: str = "") -> float:
    """Целевая длина плана из BPM (PDF §8.3): быстрый трек → короче планы."""
    if tempo and tempo > 0:
        beat = 60.0 / tempo
        n_beats = 2 if tempo >= 115 else 4          # смена кадра кратно 2/4 битам
        desired = n_beats * beat
    else:
        desired = 3.0
    if pace_hint == "fast":
        desired = min(desired, 2.2)
    elif pace_hint == "slow":
        desired = max(desired, 3.5)
    return max(1.2, min(desired, 9.0))


def _snap_to_grid(position_s: float, desired: float, beats: List[float],
                  strong_beats: Optional[List[float]] = None, tol: float = 0.25) -> float:
    """Глобально-согласованная привязка КОНЦА клипа к битовой сетке (BS-1/BS-4).

    Конец клипа сажается на ближайший бит к position+desired; сильные доли
    (downbeats) предпочитаются, если попадают рядом с целью. Монотонность
    гарантируется поиском битов строго правее текущей позиции — нет дрейфа.
    """
    if not beats:
        return max(1.2, desired)
    target = position_s + desired
    grid = [b for b in beats if b > position_s + 0.4]
    if not grid:
        return max(1.2, desired)
    cand = grid
    if strong_beats:
        strong_near = [b for b in strong_beats
                       if b > position_s + 0.4 and abs(b - target) <= tol * 2]
        if strong_near:
            cand = strong_near
    best = min(cand, key=lambda b: abs(b - target))
    return max(1.2, best - position_s)


def _section_energy_at(sections: List[dict], t_s: float) -> float:
    """Энергия секции трека в момент output-времени t_s (BS-3+)."""
    for s in sections:
        if float(s.get("start_s", 0)) <= t_s < float(s.get("end_s", 1e9)):
            return float(s.get("energy_score", 0.5))
    return 0.5


def _order_by_sections(clips: List[dict], sections: List[dict], avg_len: float = 3.0) -> List[dict]:
    """Разложить клипы по секциям трека (BS-3+, PDF §8): спокойные — в intro/bridge,
    динамичные — в drop/припев. Жадно сопоставляем динамику клипа энергии секции
    в текущей точке output-времени.
    """
    if not sections or len(clips) < 3:
        return list(clips)
    remaining = list(clips)
    out: List[dict] = []
    pos = 0.0
    step = max(1.2, avg_len)
    while remaining:
        target_e = _section_energy_at(sections, pos)
        best = min(remaining, key=lambda s: abs(_seg_dynamics(s) - target_e))
        out.append(best)
        remaining.remove(best)
        pos += step
    return out


def _q_tech(seg: dict) -> float:
    """Техническое качество кадра (PDF §1, §13.2): резкость+экспозиция+стабильность."""
    sharp = float(seg.get("sharpness", seg.get("blur_score", 0.5)) or 0.5)
    bright = float(seg.get("brightness", 0.5) or 0.5)
    exposure = 1.0 - min(1.0, abs(bright - 0.5) * 2.0)      # штраф за пере/недосвет
    stability = 1.0 - float(seg.get("camera_shake", 0.0) or 0.0)
    blur_pen = 0.30 if seg.get("is_blurry") else 0.0
    q = 0.45 * sharp + 0.30 * exposure + 0.25 * stability - blur_pen
    return max(0.0, min(1.0, q))


def _m_dynamic(seg: dict) -> float:
    """Динамика с оптимумом В СЕРЕДИНЕ (PDF §5.1): и статика, и тряска — плохо."""
    return max(0.0, 1.0 - abs(_seg_dynamics(seg) - 0.5) * 2.0)


def _m_semantic(seg: dict) -> float:
    """Смысловая ценность: CLIP-скор если есть, иначе теги + лицо + речь."""
    clip = seg.get("clip_score")
    if isinstance(clip, (int, float)):
        base = float(clip)
    else:
        tags = set(seg.get("semantic_tags") or seg.get("scene_tags") or [])
        base = min(1.0, 0.15 * len(tags))
    if seg.get("has_face"):
        base = min(1.0, base + 0.15)
    base = min(1.0, base + 0.25 * float(seg.get("speech_density", 0.0) or 0.0))
    return max(0.0, min(1.0, base))


def _feedback_bias(seg: dict) -> float:
    """Сдвиг ценности по обучению на правках пользователя (ROADMAP Фаза 8, MX-3).

    Если пользователь регулярно удалял клипы с такими тегами/движением/лицом,
    похожие кандидаты получают небольшой штраф. Источник — `edit_feedback` в
    session_state (накапливается при удалении клипа в редакторе черновика).
    """
    try:
        fb = st.session_state.get("edit_feedback")
    except Exception:
        fb = None
    if not fb or fb.get("n_deleted", 0) < 2:
        return 0.0
    n = float(fb["n_deleted"])
    tags = set(seg.get("semantic_tags") or seg.get("scene_tags") or [])
    tag_pen = sum(fb.get("deleted_tags", {}).get(t, 0) for t in tags) / n
    mot_pen = fb.get("deleted_motion", {}).get(seg.get("camera_motion_type", ""), 0) / n
    face_pen = (fb.get("deleted_face", 0) / n) if seg.get("has_face") else 0.0
    pen = 0.10 * min(1.0, tag_pen) + 0.08 * min(1.0, mot_pen) + 0.04 * min(1.0, face_pen)
    return -min(0.15, pen)


def _record_feedback(seg: dict) -> None:
    """Зафиксировать удаление клипа пользователем для обучения (MX-3)."""
    fb = st.session_state.setdefault("edit_feedback", {
        "deleted_tags": {}, "deleted_motion": {}, "deleted_face": 0, "n_deleted": 0})
    for t in (seg.get("semantic_tags") or seg.get("scene_tags") or []):
        fb["deleted_tags"][t] = fb["deleted_tags"].get(t, 0) + 1
    mot = seg.get("camera_motion_type")
    if mot:
        fb["deleted_motion"][mot] = fb["deleted_motion"].get(mot, 0) + 1
    if seg.get("has_face"):
        fb["deleted_face"] += 1
    fb["n_deleted"] += 1


def _edit_value(seg: dict, style_id: str = "") -> float:
    """Монтажная ценность W_clip = α·tech + β·semantic + γ·dynamic + бонусы (PDF §5.1).

    Отличается от quality_score (UMS): динамика оптимальна СРЕДНЯЯ, добавлены
    смысл, аудио-триггер и речевая плотность. Блендится с фитом под стиль,
    корректируется обучением на правках (MX-3).
    """
    a, b, g = 0.40, 0.35, 0.25
    w = a * _q_tech(seg) + b * _m_semantic(seg) + g * _m_dynamic(seg)
    w += 0.10 * float(seg.get("audio_energy", 0.0) or 0.0)        # аудио-триггер (AU-3)
    style = _score_for_style(seg, style_id) if style_id else seg.get("quality_score", 0.5)
    val = 0.6 * w + 0.4 * style + _feedback_bias(seg)             # MX-3
    return max(0.0, min(1.0, val))


def _hook_score(seg: dict) -> float:
    """Аттрактивность для первых 0–3 с (PDF §10): здесь нужна МАКС динамика/смысл/звук."""
    return (0.35 * _seg_dynamics(seg) + 0.30 * _m_semantic(seg)
            + 0.20 * float(seg.get("audio_energy", 0.0) or 0.0)
            + 0.15 * float(seg.get("speech_density", 0.0) or 0.0))


def _clip_sim(a: dict, b: dict) -> float:
    """Похожесть двух клипов для диверсификации/метрик [0..1]."""
    s = 0.0
    if Path(a.get("source", "")).name == Path(b.get("source", "")).name:
        s += 0.5
    ta = set(a.get("semantic_tags") or a.get("scene_tags") or [])
    tb = set(b.get("semantic_tags") or b.get("scene_tags") or [])
    if ta or tb:
        s += 0.4 * len(ta & tb) / max(1, len(ta | tb))
    if (a.get("camera_motion_type") or "x") == (b.get("camera_motion_type") or "y"):
        s += 0.1
    return min(1.0, s)


def _mmr_order(pool: List[dict], score_key: str, lam: float = 0.7) -> List[dict]:
    """Maximal Marginal Relevance — баланс ценности и разнообразия (HS-2, PDF §11.3).

    Лечит вырождение вариантов при малом пуле: рядом не встают похожие клипы.
    """
    remaining = list(pool)
    out: List[dict] = []
    while remaining:
        if not out:
            best = max(remaining, key=lambda s: s.get(score_key, 0))
        else:
            best = max(remaining, key=lambda s: (
                lam * s.get(score_key, 0)
                - (1 - lam) * max(_clip_sim(s, o) for o in out)
            ))
        out.append(best)
        remaining.remove(best)
    return out


def _inject_hook(ordered: List[dict], actions: dict) -> List[dict]:
    """Поставить самый «цепляющий» клип в начало (ST-1, PDF §10: hook 0–3 с).

    Пиннутые пользователем не трогаем — их порядок свят.
    """
    if len(ordered) < 2 or actions.get(ordered[0].get("id")) == "pinned":
        return ordered
    movable = [s for s in ordered if actions.get(s.get("id")) != "pinned"]
    if not movable:
        return ordered
    hook = max(movable, key=_hook_score)
    if hook is ordered[0]:
        return ordered
    rest = [s for s in ordered if s is not hook]
    return [hook] + rest


def _recommend_transition(tempo: float, avg_dyn: float) -> str:
    """Переход по темпу/динамике (PDF §8.3, §13.11): быстро→рез, медленно→cross."""
    if tempo and tempo >= 115:
        return "cut"
    if avg_dyn >= 0.55:
        return "cut"
    return "crossfade"


# Направление движения камеры для match-cut (TR-1).
_MOTION_DIR = {
    "pan_left": "left", "pan_right": "right",
    "tilt_up": "up", "tilt_down": "down",
    "zoom_in": "in", "zoom_out": "out",
    "aerial_forward": "forward", "aerial_descent": "down", "aerial": "forward",
    "dolly": "forward",
}
# Противоположные направления — стык «в лоб» (резать жёстко нельзя).
_OPPOSITE_DIR = {"left": "right", "right": "left", "up": "down", "down": "up",
                 "in": "out", "out": "in"}


def _motion_dir(seg: dict) -> str:
    mt = (seg.get("camera_motion_type") or "static").lower()
    for k, v in _MOTION_DIR.items():
        if k in mt:
            return v
    return "none"


def _match_cut_transition(a: dict, b: dict, style_default: str) -> str:
    """Переход между клипами A→B (ROADMAP Фаза 7, TR-1; PDF §13.11).

    Поток в конце A и начале B схож по направлению и скорости → cut-on-action
    (бесшовный жёсткий рез, 'cut'). Направления противоположны → 'crossfade'
    (сгладить рывок). Иначе — переход по умолчанию стиля.
    """
    da, db = _motion_dir(a), _motion_dir(b)
    dyn_a, dyn_b = _seg_dynamics(a), _seg_dynamics(b)
    if da != "none" and da == db and abs(dyn_a - dyn_b) < 0.30:
        return "cut"                                  # match cut / cut on action
    if da != "none" and db != "none" and _OPPOSITE_DIR.get(da) == db:
        return "crossfade"                            # противоход — сгладить
    return style_default


def _assign_transitions(selected: list, style_default: str) -> None:
    """Проставить ``transition_to_next`` каждому клипу (кроме последнего)."""
    for i in range(len(selected) - 1):
        a = getattr(selected[i], "_frag", None) or {}
        b = getattr(selected[i + 1], "_frag", None) or {}
        selected[i].transition_to_next = _match_cut_transition(a, b, style_default)


def _apply_smart_reframe(selected: list, is_vertical: bool) -> None:
    """Auto-reframe 9:16 (ROADMAP Фаза 4, RF-1/RF-2; PDF §7).

    Для вертикального вывода определяет центр кропа каждого клипа (лицо→тело→
    saliency→центр через SmartCrop) и сглаживает траекторию между клипами:
    EMA + ограничение скачка по X, чтобы рамка не «дёргалась» (PDF §7.2).
    Ставит атрибут ``crop_center_x`` на каждый SelectedSegment.

    Покадровое сглаживание (Калман/сплайн) — следующий шаг RF-2, требует
    покадрового кропа в рендере; здесь центр постоянен в пределах клипа.
    """
    if not is_vertical or not selected:
        return
    try:
        from analysis.video.smart_crop import SmartCrop
        sc = SmartCrop()
    except Exception as exc:
        # Любой сбой (нет mediapipe, сломанный API и т.п.) — кроп остаётся по центру.
        logger.info("[reframe] SmartCrop недоступен (%s) — кроп по центру", exc)
        return
    prev_x = 0.5
    alpha = 0.6          # вес нового измерения (EMA)
    max_jump = 0.18      # макс. сдвиг центра между соседними клипами
    for seg in selected:
        try:
            res = sc.get_crop_center(seg.source_path, seg.start, seg.end)
            raw = float(res.get("center_x", 0.5))
            conf = float(res.get("confidence", 0.0))
        except Exception:
            raw, conf = 0.5, 0.0
        # низкая уверенность → тянем к центру
        measured = raw if conf >= 0.3 else 0.5 + (raw - 0.5) * conf
        smoothed = alpha * measured + (1 - alpha) * prev_x
        smoothed = max(prev_x - max_jump, min(prev_x + max_jump, smoothed))
        smoothed = max(0.05, min(0.95, smoothed))
        seg.crop_center_x = smoothed
        prev_x = smoothed


# ── Метрики монтажа (Фаза 8, MX-1; PDF §11.3) ─────────────────────────────────

def _metric_beat_sync_error(segs: List[dict], beats: List[float]) -> float:
    """RMSE между точками склейки и ближайшими битами; меньше = ритмичнее."""
    if not beats or not segs:
        return 0.0
    import math
    pos, errs = 0.0, []
    for s in segs:
        pos += float(s.get("_clip_dur", 0))
        nb = min(beats, key=lambda b: abs(b - pos))
        errs.append((nb - pos) ** 2)
    return round(math.sqrt(sum(errs) / len(errs)), 3)


def _metric_shot_len_var(segs: List[dict]) -> float:
    ds = [float(s.get("_clip_dur", 0)) for s in segs]
    if len(ds) < 2:
        return 0.0
    import statistics
    return round(statistics.pvariance(ds), 3)


def _metric_jump_cut_penalty(segs: List[dict]) -> float:
    """Штраф за склейки соседних кусков одного источника с малой разницей кадров."""
    pen = 0
    for a, b in zip(segs, segs[1:]):
        if Path(a.get("source", "")).name == Path(b.get("source", "")).name:
            if abs(float(b.get("start_s", 0)) - float(a.get("end_s", 0))) < 0.5:
                pen += 1
    return round(pen / max(1, len(segs) - 1), 3)


def _metric_diversity(segs: List[dict]) -> float:
    """1 − средняя похожесть соседних клипов (креативность)."""
    if len(segs) < 2:
        return 1.0
    sims = [_clip_sim(a, b) for a, b in zip(segs, segs[1:])]
    return round(1.0 - sum(sims) / len(sims), 3)


def _variant_metrics(segs: List[dict], beats: List[float], style_id: str) -> dict:
    """Сводка метрик варианта + холистический VEI и hook_rate."""
    if not segs:
        return {"vei": 0.0, "hook_rate": 0.0, "beat_sync_error": 0.0,
                "shot_len_var": 0.0, "jump_cut_penalty": 0.0, "diversity": 0.0}
    slv = _metric_shot_len_var(segs)
    smoothness = 1.0 / (1.0 + slv)
    engagement = sum(_edit_value(s, style_id) for s in segs) / len(segs)
    return {
        "beat_sync_error":  _metric_beat_sync_error(segs, beats),
        "shot_len_var":     slv,
        "jump_cut_penalty": _metric_jump_cut_penalty(segs),
        "diversity":        _metric_diversity(segs),
        "hook_rate":        round(_hook_score(segs[0]), 3),
        "vei":              round(engagement * smoothness, 3),
    }


def _variant_rank(m: dict) -> float:
    """Композитный балл для авто-выбора лучшего варианта (выше = лучше)."""
    return (1.5 * m.get("vei", 0) + 1.0 * m.get("hook_rate", 0)
            + 0.7 * m.get("diversity", 0)
            - 0.6 * m.get("beat_sync_error", 0)
            - 0.5 * m.get("jump_cut_penalty", 0))


def _order_body_by_arc(body: List[Dict], narrative_arc: str) -> List[Dict]:
    """Deterministically order body clips to match the project's narrative arc.

    Replaces the old random shuffle: the same material + same arc always yields
    the same coherent sequence instead of a random one.
    """
    if len(body) <= 2:
        return list(body)
    arc = (narrative_arc or "").lower()
    q = lambda s: s.get("_style_score", s.get("quality_score", 0))

    if arc in ("journey", "three_act", "story_arc"):
        # Calm establishing → rising dynamics → climax (ST-2: учёт громкого/
        # эмоционального пика через audio_energy, PDF §10) → resolution.
        opening = min(body, key=lambda s: abs(_seg_dynamics(s) - 0.45))
        rest    = [s for s in body if s is not opening]
        climax  = lambda s: q(s) + 0.5 * float(s.get("audio_energy", 0.0) or 0.0)
        finale  = max(rest, key=climax)
        middle  = [s for s in rest if s is not finale]
        middle.sort(key=_seg_dynamics)               # ramp up to the climax
        return [opening] + middle + [finale]

    if arc == "highlight_reel":
        # Best moments first, energy kept high throughout.
        return sorted(body, key=lambda s: (q(s) + _seg_dynamics(s)), reverse=True)

    # montage / default: rhythmic alternation calm↔dynamic, best of each first.
    calm    = sorted([s for s in body if _seg_dynamics(s) < 0.5],  key=q, reverse=True)
    dynamic = sorted([s for s in body if _seg_dynamics(s) >= 0.5], key=q, reverse=True)
    out: List[Dict] = []
    for i in range(max(len(calm), len(dynamic))):
        if i < len(dynamic): out.append(dynamic[i])
        if i < len(calm):    out.append(calm[i])
    return out


def _build_timeline() -> None:
    frags      = st.session_state.get("scene_fragments", [])
    actions    = st.session_state.get("scene_actions", {})
    target     = st.session_state.get("target_duration", 30)
    audio_path = st.session_state.get("audio_path")
    style_id   = st.session_state.get("selected_style", "")

    mctx = _detect_music_context(audio_path) if audio_path else {
        "beats": [], "strong_beats": [], "tempo": 0.0, "sections": []}
    beats: List[float]        = mctx["beats"]
    strong_beats: List[float] = mctx["strong_beats"]
    tempo: float              = mctx["tempo"]
    sections: List[dict]      = mctx.get("sections", [])
    beat_sync_active = bool(beats)
    # Подсказка темпа из пресета стиля (fast_reels/fpv_action → быстрый)
    _style_preset = next((p for p in _STYLE_PRESETS if p.get("id") == style_id), {})
    _pace_ru = str(_style_preset.get("pace", "")).lower()
    pace_hint = "fast" if "быстр" in _pace_ru else "slow" if "медлен" in _pace_ru else ""
    if not pace_hint and tempo and tempo >= 115:
        pace_hint = "fast"
    style_transition = str(_style_preset.get("transition", "")).lower()

    # Косметические замечания композиции — не повод выкидывать фрагмент из пула
    _SOFT_REJECTS = ("tilted horizon", "cluttered background")

    def _in_pool(f: dict) -> bool:
        act = actions.get(f["id"])
        if act == "pinned":
            return True
        if act in ("excluded", "forbidden"):
            return False
        if act == "included":
            return True
        # Default: include only good-quality fragments (no rejection reason)
        rej = f.get("rejection_reason")
        if rej and any(s in rej for s in _SOFT_REJECTS):
            return True
        return rej is None

    pool = [f for f in frags if _in_pool(f)]
    if not pool and frags:
        # Все фрагменты отбракованы — монтаж из лучших по качеству лучше, чем ничего.
        # Явно исключённые пользователем не возвращаем.
        usable = [f for f in frags if actions.get(f["id"]) not in ("excluded", "forbidden")]
        pool = sorted(usable, key=lambda x: -x.get("quality_score", 0))
        logger.warning("[_build_timeline] пул пуст после фильтров — fallback на %d лучших фрагментов", len(pool))

    # Enrich pool with accurate StyleFitService scores for current style
    if style_id and pool:
        try:
            from analysis.intelligence.style_fit_service import StyleFitService
            _sfs = StyleFitService()
            for f in pool:
                result = _sfs.compute_fit(
                    style_id=style_id,
                    motion_type=f.get("camera_motion_type"),
                    semantic_tags=f.get("semantic_tags") or f.get("scene_tags"),
                    suggested_role=f.get("suggested_role"),
                    quality_score=f.get("quality_score", 0.5),
                )
                if not isinstance(f.get("style_fit_scores"), dict):
                    f["style_fit_scores"] = {}
                f["style_fit_scores"][style_id] = result.fit_score
                f["_style_explanation"] = result.explanation
        except Exception as sfs_exc:
            # MX-2: не глушим тихо — деградация на эвристику должна быть видна.
            logger.warning("[Timeline] StyleFitService failed (%s) — fallback на "
                           "эвристику _score_for_style", sfs_exc)
            st.session_state["tl_stylefit_degraded"] = True

    # Фаза 5 (SEM-1): семантический скоринг CLIP под промпт стиля/концепции.
    # Самовыключается, если open_clip/torch не установлены (clip_score не появится).
    if st.session_state.get("enable_clip", True) and pool:
        try:
            from analysis.content.clip_scorer import CLIPScorer, prompt_for
            _scorer = CLIPScorer()
            if _scorer.available:
                _prompt = prompt_for(
                    style_id,
                    _concept_field(st.session_state.get("video_concept"), "concept_type"),
                )
                _n = _scorer.score_fragments(pool, _prompt)
                logger.info("[Timeline] CLIP scored %d/%d fragments", _n, len(pool))
        except Exception as clip_exc:
            logger.debug("[Timeline] CLIP scoring skipped: %s", clip_exc)

    # Score each fragment for the current style (uses style_fit_scores if available)
    for f in pool:
        f["_style_score"] = _score_for_style(f, style_id)
        f["_edit_value"]  = _edit_value(f, style_id)   # Фаза 3: монтажная ценность

    # Sort: pinned first, then by style_score descending
    pool.sort(key=lambda x: (actions.get(x["id"]) != "pinned", -x.get("_style_score", 0)))

    # Identify intro/outro candidates by suggested_role
    intro_pool  = [f for f in pool if f.get("suggested_role") == "intro"]
    outro_pool  = [f for f in pool if f.get("suggested_role") == "outro"]
    body_pool   = [f for f in pool if f.get("suggested_role") not in ("intro", "outro")]

    # Diversity: per-source-file clip limit to avoid repeating the same video
    _unique_sources = {Path(s.get("source", "unknown")).name for s in pool}
    _n_sources      = max(1, len(_unique_sources))
    _est_clips      = max(3, int(target / 4))           # ~4 s average clip
    _max_per_src    = max(2, (_est_clips // _n_sources) + 1) if _n_sources > 1 else 9999

    def _clip_dur(seg: dict, total_s: float) -> float:
        # Фаза 2 (BS-2): целевая длина из BPM, ограниченная длиной самой сцены.
        scene_len = max(0.0, seg.get("end_s", 0) - seg.get("start_s", 0))
        desired = min(_pacing_clip_len(tempo, pace_hint), scene_len if scene_len else 9.0)
        desired = max(1.2, min(desired, 9.0))
        if beat_sync_active:
            # BS-1/BS-4: глобальная привязка реза к битовой сетке (downbeats в приоритете)
            d = _snap_to_grid(total_s, desired, beats, strong_beats)
            return min(d, scene_len) if scene_len else d
        return desired if not scene_len else min(desired, scene_len)

    def _variant(offset: int = 0, prefer_quality: bool = False,
                 prefer_dynamic: bool = False, prefer_intro_outro: bool = False) -> List[Dict]:
        rng = random.Random(offset)

        pinned = [s for s in pool if actions.get(s["id"]) == "pinned"]
        rest   = [s for s in pool if actions.get(s["id"]) != "pinned"]

        if prefer_quality:
            rest_sorted = sorted(rest, key=lambda x: -x.get("quality_score", 0))
        elif prefer_dynamic:
            # Фаза 3 (HS-1/HS-2): порядок по монтажной ценности _edit_value через
            # MMR — баланс ценности и разнообразия, не вырождается в вариант A.
            rest_sorted = _mmr_order(rest, "_edit_value", lam=0.72)
        elif prefer_intro_outro:
            intro_c = [s for s in intro_pool if s not in pinned]
            outro_c = [s for s in outro_pool if s not in pinned]
            body_c  = [s for s in body_pool  if s not in pinned]
            # Order the body to follow the project's narrative arc instead of
            # shuffling it randomly — this is the actual "сюжет" of variant C.
            arc = _concept_field(st.session_state.get("video_concept"), "narrative_arc")
            if sections:
                # BS-3+: при наличии секций трека раскладываем тело по энергии
                # музыки (drop → динамика, intro/bridge → спокойствие).
                body_c = _order_by_sections(body_c, sections,
                                            avg_len=_pacing_clip_len(tempo, pace_hint))
            else:
                body_c = _order_body_by_arc(body_c, arc)
            rest_sorted = (
                sorted(intro_c, key=lambda x: -x.get("_style_score", 0))[:1]
                + body_c
                + sorted(outro_c, key=lambda x: -x.get("_style_score", 0))[:1]
            )
        else:
            rng.shuffle(rest)
            rest_sorted = rest

        ordered = pinned + rest_sorted
        # ST-1 (PDF §10): самый «цепляющий» клип — в первые 0–3 с (кроме случайного D)
        if not prefer_quality or prefer_intro_outro:
            ordered = _inject_hook(ordered, actions)
        result, total = [], 0.0
        src_counts: Dict[str, int] = {}
        deferred: List[dict] = []  # clips skipped due to per-source limit

        for seg in ordered:
            src = Path(seg.get("source", "unknown")).name
            is_pinned = actions.get(seg["id"]) == "pinned"

            # Enforce per-source limit (pinned always pass through)
            if not is_pinned and _n_sources > 1 and src_counts.get(src, 0) >= _max_per_src:
                deferred.append(seg)
                continue

            d = _clip_dur(seg, total)
            if total + d > target * 1.25:
                break
            result.append({**seg, "_clip_dur": round(d, 2), "_beat_sync": beat_sync_active})
            src_counts[src] = src_counts.get(src, 0) + 1
            total += d
            if total >= target:
                break

        # If we're well under target after diversity filtering, fill with deferred clips
        if total < target * 0.65 and deferred:
            for seg in deferred:
                if total >= target:
                    break
                d = _clip_dur(seg, total)
                if total + d > target * 1.35:
                    break
                result.append({**seg, "_clip_dur": round(d, 2), "_beat_sync": beat_sync_active})
                total += d

        return result

    variants = {
        "A": _variant(0,  prefer_quality=True),           # Best quality
        "B": _variant(3,  prefer_dynamic=True),           # Best style fit
        "C": _variant(7,  prefer_intro_outro=True),       # Structured (intro→body→outro)
        "D": _variant(13),                                # Random mix
    }

    # Build explicit edit_plan for each variant (for render validation + debugging)
    import uuid as _uuid
    def _make_edit_plan(segs: list, variant_id: str) -> dict:
        plan_segs = []
        for seg in segs:
            abs_p = seg.get("_abs_path", "")
            src   = seg.get("source", "")
            s_s   = float(seg.get("start_s", 0))
            e_s   = float(seg.get("end_s", 0))
            d     = float(seg.get("_clip_dur", e_s - s_s))
            plan_segs.append({
                "scene_id":        seg.get("id"),
                "source_filename": Path(src).name if src else Path(abs_p).name,
                "abs_path":        abs_p,
                "start_s":         s_s,
                "end_s":           e_s,
                "target_duration": d,
                "style_score":     round(seg.get("_style_score", 0), 3),
                "quality_score":   round(seg.get("quality_score", 0), 3),
                "reason":          seg.get("_style_explanation") or seg.get("selection_reason") or "",
            })
        total_dur = sum(s["target_duration"] for s in plan_segs)
        # Validate: warn if many clips from same source (likely a bug)
        from collections import Counter as _Counter
        src_cnt = _Counter(s["source_filename"] for s in plan_segs)
        dominant_pct = max(src_cnt.values()) / max(1, len(plan_segs))
        metrics = _variant_metrics(segs, beats, style_id)   # Фаза 8 (MX-1)
        return {
            "edit_plan_id":      str(_uuid.uuid4())[:8],
            "variant":           variant_id,
            "style":             style_id,
            "concept":           _concept_field(st.session_state.get("video_concept"), "concept_type"),
            "n_clips":           len(plan_segs),
            "n_unique_sources":  len(src_cnt),
            "total_duration_s":  round(total_dur, 2),
            "dominant_source_pct": round(dominant_pct, 2),
            "metrics":           metrics,
            "selected_scenes":   plan_segs,
        }

    variant_metrics: Dict[str, dict] = {}
    for vid, segs in variants.items():
        if segs:
            # Validate uniqueness: if >80% clips from one source, warn
            plan = _make_edit_plan(segs, vid)
            variants[vid] = segs  # keep segment list as-is
            variant_metrics[vid] = plan["metrics"]
            m = plan["metrics"]
            logger.info(
                "[Timeline] variant=%s clips=%d sources=%d dom_pct=%.0f%% total=%.1fs "
                "VEI=%.2f hook=%.2f bse=%.2f div=%.2f",
                vid, plan["n_clips"], plan["n_unique_sources"],
                plan["dominant_source_pct"] * 100, plan["total_duration_s"],
                m["vei"], m["hook_rate"], m["beat_sync_error"], m["diversity"],
            )

    # Фаза 8 (MX-1): авто-выбор лучшего варианта по композитному рангу метрик.
    best_variant = "A"
    if variant_metrics:
        best_variant = max(variant_metrics, key=lambda v: _variant_rank(variant_metrics[v]))
        logger.info("[Timeline] recommended variant=%s (rank=%.3f)",
                    best_variant, _variant_rank(variant_metrics[best_variant]))

    # Фаза 7 (TR-1): рекомендованный переход по темпу/средней динамике пула
    _avg_dyn = (sum(_seg_dynamics(f) for f in pool) / len(pool)) if pool else 0.5
    st.session_state.tl_recommended_transition = _recommend_transition(tempo, _avg_dyn)
    st.session_state.tl_tempo            = tempo
    st.session_state.tl_metrics          = variant_metrics
    st.session_state.tl_best_variant     = best_variant

    st.session_state.tl_variants  = variants
    st.session_state.tl_variant      = best_variant
    st.session_state.tl_beat_sync    = beat_sync_active
    _save_session_inputs()   # запомнить стиль/формат/длительность вместе с путями
    st.session_state.preview_state   = "not_generated"
    st.session_state.render_state       = "not_started"


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 6 · DRAFT TIMELINE
# ══════════════════════════════════════════════════════════════════════════════
def _screen_timeline() -> None:
    _wizard_bar()
    st.button("← Назад", key="back_tl", on_click=_back)

    beat_sync = st.session_state.get("tl_beat_sync", False)
    beat_badge = ' <span class="badge b-green">🎵 Бит-синхронизация</span>' if beat_sync else ""
    st.markdown(f"## Черновой монтаж{beat_badge}", unsafe_allow_html=True)
    st.markdown('<p>Проверьте последовательность сцен, перестройте при необходимости. Затем сгенерируйте превью.</p>', unsafe_allow_html=True)

    _VARIANT_DESC = {
        "A": "A · Лучшее качество",
        "B": "B · Под стиль",
        "C": "C · Сюжет по концепции (вступ→развитие→финал)",
        "D": "D · Случайный микс",
    }
    # Фаза 8 (MX-1): пометить рекомендованный по метрикам вариант звездой.
    _best = st.session_state.get("tl_best_variant")
    if _best in _VARIANT_DESC:
        _VARIANT_DESC[_best] = "⭐ " + _VARIANT_DESC[_best]
    if st.session_state.get("tl_stylefit_degraded"):
        st.warning("⚠️ Скоринг под стиль (StyleFitService) недоступен — "
                   "использована эвристика. Качество подбора может быть ниже.")
    variants = st.session_state.get("tl_variants", {})
    active   = st.session_state.get("tl_variant", "A")

    if not variants:
        # Таймлайн ещё не построен (прямой переход на экран) — строим сейчас
        if st.session_state.get("scene_fragments"):
            _build_timeline()
            variants = st.session_state.get("tl_variants", {})
        if not variants:
            st.warning("Черновой монтаж ещё не построен — нет проанализированных сцен. "
                       "Вернитесь к шагу анализа.")
            if st.button("← К анализу", key="tl_to_analysis"):
                _go("analysis")
            return

    tab_labels = [_VARIANT_DESC.get(k, k) for k in variants.keys()]
    tabs = st.tabs(tab_labels)
    for tab, key in zip(tabs, variants.keys()):
        with tab:
            if active != key:
                st.session_state.tl_variant = key
            _render_timeline_editor(key, variants)

    st.markdown("<br><hr>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🔄  Новые варианты", use_container_width=True):
            _build_timeline()
            st.rerun()
    with c3:
        if st.button("▶  Сгенерировать превью", use_container_width=True):
            st.session_state.preview_state = "not_generated"
            _go("preview")


def _render_timeline_editor(key: str, variants: Dict) -> None:
    segs  = variants.get(key, [])
    total = sum(s.get("_clip_dur", 0) for s in segs)
    target = st.session_state.get("target_duration", 30)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Длина", f"{total:.0f} / {target} с")
    m2.metric("Клипов", str(len(segs)))
    m3.metric("С лицами", str(sum(1 for s in segs if s.get("has_face"))))
    avg_q = sum(s.get("quality_score",0) for s in segs) / max(1, len(segs))
    m4.metric("Ср. рейтинг", f"{avg_q:.0%}")

    # Фаза 8 (MX-1): метрики качества монтажа этого варианта.
    _vm = (st.session_state.get("tl_metrics") or {}).get(key)
    if _vm:
        with st.expander("📊 Метрики монтажа", expanded=False):
            q1, q2, q3 = st.columns(3)
            q1.metric("VEI (холистич.)", f"{_vm.get('vei',0):.2f}")
            q2.metric("Hook (вступление)", f"{_vm.get('hook_rate',0):.2f}")
            q3.metric("Разнообразие", f"{_vm.get('diversity',0):.2f}")
            q4, q5, q6 = st.columns(3)
            q4.metric("Бит-синхрон. ошибка", f"{_vm.get('beat_sync_error',0):.2f}с")
            q5.metric("Разброс длин", f"{_vm.get('shot_len_var',0):.2f}")
            q6.metric("Jump-cut штраф", f"{_vm.get('jump_cut_penalty',0):.2f}")
            st.caption("VEI = вовлечённость × плавность · меньше бит-ошибки/штрафа = "
                       "ритмичнее · ⭐ помечен вариант с лучшим композитным рангом.")

    # ── Audio track ─────────────────────────────────────────────────────────
    has_audio = bool(st.session_state.get("audio_path"))
    audio_label = Path(st.session_state.get("audio_path","")).name if has_audio else "Без музыки"
    audio_color = "#0F2A1A" if has_audio else "#1A1A1A"

    # ── Video segments bar ───────────────────────────────────────────────────
    seg_bars = ""
    style_id = st.session_state.get("selected_style","")
    style_preset = next((p for p in _STYLE_PRESETS if p["id"] == style_id), {})
    trans_label  = style_preset.get("transition","cut")

    for si, seg in enumerate(segs):
        dur  = seg.get("_clip_dur", 1)
        pct  = max(2.0, dur / max(total, 1) * 100)
        col  = _SEG_COLORS[si % len(_SEG_COLORS)]
        fi   = "👤" if seg.get("has_face") else ""
        seg_bars += (
            f'<div class="tl-seg" style="width:{pct}%;background:{col};" '
            f'title="{seg.get("source","?")} · {dur:.1f}s">'
            f'{fi}<div class="tl-seg-dur">{dur:.1f}s</div></div>'
        )
        if si < len(segs) - 1:
            seg_bars += f'<div class="tl-transition" title="Переход: {trans_label}">╳</div>'

    audio_wave_pct = min(100, total / max(target,1) * 100)
    st.markdown(f"""
<div class="tl-wrap">
  <div class="tl-track-label">🎵 Аудио · {audio_label}</div>
  <div class="tl-audio-row" style="background:{audio_color};">
    <div class="tl-audio-wave" style="width:{audio_wave_pct}%;"></div>
    <span style="font-size:.68rem;color:#00FF8888;margin-left:.5rem;">{total:.0f}с</span>
  </div>
  <div class="tl-track-label">🎬 Видео · {len(segs)} клипов</div>
  <div class="tl-video-row">{seg_bars}</div>
  <div style="display:flex;justify-content:space-between;margin-top:.3rem;">
    <span style="font-size:.65rem;color:#3B4A59;">0:00</span>
    <span style="font-size:.65rem;color:#3B4A59;">{int(total//60)}:{int(total%60):02d}</span>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Drag-and-drop + editable segment list ───────────────────────────────
    with st.expander(f"🎬 Изменить порядок клипов ({len(segs)}) — перетащите мышью или кнопками ↑↓", expanded=True):
        # Build labelled items for sortables (index encoded in key for lookup)
        _sort_labels = [
            f"#{si+1} · {seg.get('source','?')} · {seg.get('_clip_dur',3):.1f}s"
            f"{' 👤' if seg.get('has_face') else ''} · {seg.get('quality_score',0):.0%}"
            for si, seg in enumerate(segs)
        ]
        try:
            from streamlit_sortables import sort_items as _sort_items
            _sorted = _sort_items(_sort_labels, direction="vertical", key=f"sortable_{key}")
            # If order changed, reorder segs to match
            if _sorted != _sort_labels:
                _idx_map = {lbl: i for i, lbl in enumerate(_sort_labels)}
                new_order = [_idx_map[lbl] for lbl in _sorted if lbl in _idx_map]
                if len(new_order) == len(segs) and new_order != list(range(len(segs))):
                    segs = [segs[i] for i in new_order]
                    variants[key] = segs
                    st.session_state.tl_variants = variants
                    # Rerun so the bar, list and duration widgets re-bind to the
                    # new order — otherwise they desync until the next click.
                    st.rerun()
        except Exception:
            # Любой сбой компонента drag-and-drop не должен ломать редактор —
            # остаются кнопки ↑↓ и удаление.
            st.caption("Перетаскивание недоступно — используйте кнопки ↑↓")

        # Per-clip duration editor + remove
        for si, seg in enumerate(segs):
            c_n, c_src, c_dur, c_q, c_up, c_dn, c_rm = st.columns([.4, 2.2, 1, 1, .4, .4, .4])
            c_n.markdown(
                f'<span style="color:{_SEG_COLORS[si%len(_SEG_COLORS)]};font-weight:700;font-size:.85rem;">#{si+1}</span>',
                unsafe_allow_html=True,
            )
            c_src.markdown(
                f'<span style="font-size:.8rem;color:#E8EDF2;">{seg.get("source","?")}'
                f'{" 👤" if seg.get("has_face") else ""}</span>',
                unsafe_allow_html=True,
            )
            new_dur = c_dur.number_input(
                "", min_value=1.0, max_value=15.0,
                value=float(seg.get("_clip_dur", 3)),
                step=0.5, key=f"dur_{key}_{si}",
                label_visibility="collapsed",
            )
            if abs(new_dur - seg.get("_clip_dur", 3)) > 0.1:
                segs[si]["_clip_dur"] = new_dur
                variants[key] = segs
                st.session_state.tl_variants = variants
                st.rerun()
            c_q.markdown(
                f'<span style="font-size:.78rem;color:#00FF88;">{seg.get("quality_score",0):.0%}</span>',
                unsafe_allow_html=True,
            )
            if c_up.button("↑", key=f"up_{key}_{si}") and si > 0:
                segs[si], segs[si-1] = segs[si-1], segs[si]
                variants[key] = segs
                st.session_state.tl_variants = variants
                st.rerun()
            if c_dn.button("↓", key=f"dn_{key}_{si}") and si < len(segs)-1:
                segs[si], segs[si+1] = segs[si+1], segs[si]
                variants[key] = segs
                st.session_state.tl_variants = variants
                st.rerun()
            if c_rm.button("✕", key=f"rm_{key}_{si}"):
                _record_feedback(segs[si])      # MX-3: учимся на удалении
                segs.pop(si)
                variants[key] = segs
                st.session_state.tl_variants = variants
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 7 · PREVIEW (4 explicit states)
# ══════════════════════════════════════════════════════════════════════════════
def _screen_preview() -> None:
    _wizard_bar()
    st.button("← Изменить монтаж", key="back_preview", on_click=_back)

    st.markdown("## Предпросмотр")

    state = st.session_state.get("preview_state", "not_generated")

    # ── STATE: not_generated ─────────────────────────────────────────────────
    if state == "not_generated":
        active = st.session_state.get("tl_variant","A")
        segs   = st.session_state.get("tl_variants",{}).get(active,[])
        total  = sum(s.get("_clip_dur",0) for s in segs)

        st.markdown(f"""
<div class="preview-state">
  <div class="preview-icon">🎬</div>
  <div class="preview-msg">
    Превью ещё не сгенерировано.<br>
    Будет создана быстрая 480p-версия вашего монтажа.<br>
    <span style="color:#3B4A59;font-size:.8rem;">~{max(5, int(total*0.4))} секунд</span>
  </div>
</div>
""", unsafe_allow_html=True)
        col = st.columns([1,2,1])[1]
        with col:
            if st.button("▶  Сгенерировать превью", use_container_width=True):
                st.session_state.preview_state = "generating"
                st.session_state.preview_pct   = 0
                st.rerun()

    # ── STATE: generating ────────────────────────────────────────────────────
    elif state == "generating":
        ph_title = st.empty()
        ph_prog  = st.progress(0)
        ph_eta   = st.empty()

        ph_title.markdown("""
<div class="preview-state generating" style="padding:2rem;">
  <div class="preview-icon">⚙️</div>
  <div class="preview-msg">Генерируется превью 480p…</div>
</div>
""", unsafe_allow_html=True)

        result_path, err = _do_render_preview(ph_prog, ph_eta)
        if err:
            st.session_state.preview_state = "failed"
            st.session_state.preview_error = err
        else:
            st.session_state.preview_state = "ready"
            st.session_state.preview_path  = result_path
        st.rerun()

    # ── STATE: ready ─────────────────────────────────────────────────────────
    elif state == "ready":
        preview_path = st.session_state.get("preview_path")
        col_v, col_info = st.columns([3,2])
        with col_v:
            if preview_path and Path(preview_path).exists():
                st.video(preview_path)
                # Distinguish between a real rendered preview and a source fallback
                active_segs = st.session_state.get("tl_variants",{}).get(
                    st.session_state.get("tl_variant","A"), []
                )
                is_fallback = any(
                    preview_path == seg.get("_abs_path") or
                    preview_path in st.session_state.get("video_paths", [])
                    for seg in active_segs
                ) or preview_path in st.session_state.get("video_paths", [])

                if is_fallback:
                    st.markdown(
                        '<span class="badge b-yellow">▶ Исходный файл · финальный рендер создаст смонтированную версию</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<span class="badge b-green">✓ Превью готово · 480p</span>',
                        unsafe_allow_html=True,
                    )
            else:
                # No file at all — offer to retry
                st.markdown("""
<div class="preview-state" style="padding:2rem;">
  <div class="preview-icon">🎬</div>
  <div class="preview-msg">Файл превью не найден на диске.</div>
</div>
""", unsafe_allow_html=True)
                if st.button("↩ Сгенерировать ещё раз", use_container_width=True):
                    st.session_state.preview_state = "generating"
                    st.rerun()

        with col_info:
            _preview_info_panel()

        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄  Попробовать другой вариант", use_container_width=True):
                _go("timeline")
        with c2:
            if st.button("✦  Финальный рендер", use_container_width=True):
                st.session_state.render_state = "not_started"
                _go("render")

    # ── STATE: failed ────────────────────────────────────────────────────────
    elif state == "failed":
        err = st.session_state.get("preview_error","Неизвестная ошибка")
        st.markdown(f"""
<div class="preview-state failed">
  <div class="preview-icon">⚠️</div>
  <div class="preview-msg" style="color:#FF4C6A;">Ошибка генерации превью</div>
  <div style="font-size:.78rem;color:#8A9BAE;margin-bottom:1rem;max-width:480px;margin-inline:auto;">{err}</div>
</div>
""", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("↩ Повторить", use_container_width=True):
                st.session_state.preview_state = "generating"
                st.rerun()
        with c2:
            if st.button("← Изменить монтаж", use_container_width=True):
                _go("timeline")


def _build_effects_config():
    """Build EffectsConfiguration from session_state color grading + style."""
    try:
        from src.effects_config import (
            EffectsConfiguration, ColorSettings, ColorStyle,
            TransitionSettings, TransitionType, SpeedEffectSettings,
            MusicSyncSettings, QualityFilterSettings, OverlaySettings,
        )
        cg = st.session_state.get("color_grading", {})
        style_id = st.session_state.get("selected_style", "")
        style    = next((p for p in _STYLE_PRESETS if p["id"] == style_id), {})
        trans_str = style.get("transition", "cut")
        try:
            trans_type = TransitionType(trans_str if trans_str != "crossfade" else "fade")
        except ValueError:
            trans_type = TransitionType.CUT

        color_enabled = any(abs(cg.get(k, 0)) > 0.005 for k in ("brightness","contrast","saturation","warmth")) or cg.get("vignette", False)
        return EffectsConfiguration(
            transitions=TransitionSettings(enabled=True, type=trans_type, duration=0.3),
            speed_effects=SpeedEffectSettings(enabled=False),
            color=ColorSettings(
                enabled=color_enabled,
                style=ColorStyle.BASIC_ENHANCE if color_enabled else ColorStyle.NONE,
                brightness=float(cg.get("brightness", 0.0)),
                contrast=float(cg.get("contrast",   0.0)),
                saturation=float(cg.get("saturation", 0.0)),
                temperature=float(cg.get("warmth",  0.0)),
                vignette=bool(cg.get("vignette", False)),
            ),
            quality_filters=QualityFilterSettings(enabled=False),
            music_sync=MusicSyncSettings(enabled=False),
            overlays=OverlaySettings(),
        )
    except Exception:
        return None


def _resolve_segments(segs: List[Dict], video_paths: List[str]) -> List[Dict]:
    """
    Assign _abs_path to each segment and clamp start_s / end_s to actual video duration.
    Falls back to video_paths[0] when segment source doesn't match any uploaded file.
    """
    name_to_path: Dict[str, str] = {Path(vp).name: vp for vp in video_paths}
    # Cache probed durations to avoid repeated ffprobe calls
    _dur_cache: Dict[str, float] = {}

    def _video_dur(path: str) -> float:
        if path not in _dur_cache:
            try:
                import subprocess, json
                r = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_format", path],
                    capture_output=True, text=True, timeout=10,
                )
                _dur_cache[path] = float(json.loads(r.stdout).get("format", {}).get("duration", 3600))
            except Exception:
                _dur_cache[path] = 3600.0
        return _dur_cache[path]

    resolved = []
    for seg in segs:
        s = dict(seg)
        src_name = Path(s.get("source", "")).name
        abs_p = name_to_path.get(src_name) or s.get("_abs_path") or (video_paths[0] if video_paths else "")
        s["_abs_path"] = abs_p
        if abs_p and Path(abs_p).exists():
            vid_dur = _video_dur(abs_p)
            clip_dur = float(s.get("_clip_dur", 3.0))
            start = min(float(s.get("start_s", 0.0)), max(0.0, vid_dur - clip_dur - 0.1))
            start = max(0.0, start)
            end   = min(start + clip_dur, vid_dur - 0.05)
            clip_dur = max(0.5, end - start)
            s["start_s"]   = round(start, 3)
            s["end_s"]     = round(end,   3)
            s["_clip_dur"] = round(clip_dur, 3)
        resolved.append(s)
    return resolved


def _fmt_output_config(fmt_id: str, target_duration: float, prev_w: int = 0, prev_h: int = 0):
    """Return an OutputConfig with correct format type and optionally overridden resolution."""
    from src.config_loader import OutputConfig

    vert_ids   = {"youtube_shorts", "instagram_reels", "tiktok"}
    square_ids = {"square"}
    fmt_type   = "vertical" if fmt_id in vert_ids else ("square" if fmt_id in square_ids else "horizontal")

    cfg = OutputConfig(target_duration=target_duration, format=fmt_type, dynamic_level="balanced")

    if prev_w and prev_h:
        _w, _h = prev_w, prev_h
        class _PreviewCfg(OutputConfig):
            @property
            def resolution(self):
                return (_w, _h)
        cfg = _PreviewCfg(target_duration=target_duration, format=fmt_type, dynamic_level="balanced")
    else:
        # Use exact pixel dimensions from _FORMAT_OPTIONS for non-standard formats
        fmt_info = next((f for f in _FORMAT_OPTIONS if f["id"] == fmt_id), None)
        if fmt_info:
            _w, _h = fmt_info["w"], fmt_info["h"]
            std = {"horizontal": (1920, 1080), "vertical": (1080, 1920), "square": (1080, 1080)}
            if (fmt_info["w"], fmt_info["h"]) != std.get(fmt_type):
                class _CustomCfg(OutputConfig):
                    @property
                    def resolution(self):
                        return (_w, _h)
                cfg = _CustomCfg(target_duration=target_duration, format=fmt_type, dynamic_level="balanced")

    return cfg


def _do_render_preview(ph_prog, ph_eta) -> Tuple[Optional[str], str]:
    """
    Render a real preview using FFmpegRenderer.
    Uses correct aspect ratio at reduced resolution (480p equiv).
    Falls back to showing the first source file if FFmpeg fails.
    """
    active = st.session_state.get("tl_variant", "A")
    segs   = st.session_state.get("tl_variants", {}).get(active, [])
    video_paths = st.session_state.get("video_paths", [])

    if not segs:
        return None, "Нет клипов в таймлайне"
    if not video_paths:
        return None, "Нет видеофайлов"

    segs = _resolve_segments(segs, video_paths)

    fmt_id   = st.session_state.get("selected_format", "fullhd_horizontal")
    fmt_info = next((f for f in _FORMAT_OPTIONS if f["id"] == fmt_id), _FORMAT_OPTIONS[3])
    target   = float(st.session_state.get("target_duration", 30))

    # Preview resolution: 480px on shortest side, correct aspect ratio
    fw, fh  = fmt_info["w"], fmt_info["h"]
    scale   = 480.0 / min(fw, fh)
    prev_w  = int(fw * scale / 2) * 2   # ensure even
    prev_h  = int(fh * scale / 2) * 2

    # Output path in project previews folder
    proj_name = (st.session_state.get("project_name") or "project").replace(" ", "_")
    out_dir   = Path.home() / "VideoProjects" / proj_name / "previews"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path  = str(out_dir / f"preview_{fmt_id}.mp4")

    ph_prog.progress(0.05)
    ph_eta.markdown(
        f'<p style="color:#8A9BAE;font-size:.78rem;">'
        f'Рендер превью {prev_w}×{prev_h}…</p>',
        unsafe_allow_html=True,
    )

    err_msg = ""
    try:
        from src.segment_selector import SelectedSegment
        from src.ffmpeg_renderer import FFmpegRenderer

        out_cfg = _fmt_output_config(fmt_id, target, prev_w, prev_h)

        # Build SelectedSegment list (only segments with valid source files)
        selected: List = []
        for seg in segs:
            abs_p = seg.get("_abs_path", "")
            if not abs_p or not Path(abs_p).exists():
                continue
            start    = float(seg.get("start_s", 0.0))
            clip_dur = float(seg.get("_clip_dur", 3.0))
            end      = start + clip_dur
            selected.append(SelectedSegment(
                source_path=abs_p,
                start=start,
                end=end,
                duration=clip_dur,
                is_must_use=False,
            ))

        if not selected:
            raise RuntimeError("Ни один клип не найден на диске")

        style_id       = st.session_state.get("selected_style", "")
        style          = next((p for p in _STYLE_PRESETS if p["id"] == style_id), {})
        transition     = style.get("transition", "none")
        music_path     = st.session_state.get("audio_path")
        voiceover_path = st.session_state.get("voiceover_path")
        if music_path and not Path(music_path).exists():
            music_path = None
        if voiceover_path and not Path(voiceover_path).exists():
            voiceover_path = None

        import re as _re
        n_segs = len(selected)

        def _cb(*args) -> None:
            msg = args[0] if args else ""
            m = _re.search(r'[Ss]egment\s+(\d+)/(\d+)', str(msg))
            if m:
                n, total_n = int(m.group(1)), int(m.group(2))
                pct = min(0.95, 0.1 + 0.80 * (n / max(total_n, 1)))
            else:
                pct = 0.92
            ph_prog.progress(pct)
            ph_eta.markdown(
                f'<p style="color:#8A9BAE;font-size:.78rem;">{msg or "Рендер…"}</p>',
                unsafe_allow_html=True,
            )

        ph_prog.progress(0.1)
        FFmpegRenderer.render(
            segments=selected,
            output_config=out_cfg,
            output_path=out_path,
            music_path=music_path,
            music_fade_in=1.5,
            music_fade_out=2.0,
            voiceover_path=voiceover_path,
            effects_config=_build_effects_config(),
            progress_callback=_cb,
            between_clip_transition=transition if transition != "crossfade" else "fade",
            between_clip_transition_dur=0.3,
        )

        ph_prog.progress(1.0)
        ph_eta.markdown('<p style="color:#00FF88;font-size:.78rem;">✓ Готово</p>', unsafe_allow_html=True)

        if Path(out_path).exists() and Path(out_path).stat().st_size > 1000:
            return out_path, ""
        raise RuntimeError("Файл превью не создан или пустой")

    except Exception as exc:
        err_msg = str(exc)

    # ── Fallback: show first source video ─────────────────────────────────────
    ph_prog.progress(1.0)
    for vp in video_paths:
        if Path(vp).exists():
            ph_eta.markdown(
                '<p style="color:#FFD246;font-size:.78rem;">'
                '⚠ Показываем исходный файл — рендер не удался</p>',
                unsafe_allow_html=True,
            )
            return vp, ""

    return None, err_msg


def _preview_info_panel() -> None:
    active = st.session_state.get("tl_variant","A")
    segs   = st.session_state.get("tl_variants",{}).get(active,[])
    total  = sum(s.get("_clip_dur",0) for s in segs)
    fmt_id = st.session_state.get("selected_format","—")
    sty_id = st.session_state.get("selected_style","—")
    fmt_l  = next((f["label"] for f in _FORMAT_OPTIONS if f["id"]==fmt_id), fmt_id)
    sty_l  = next((p["label"] for p in _STYLE_PRESETS  if p["id"]==sty_id), sty_id)

    st.markdown(f"""
<div class="vp-card">
  <div style="font-weight:700;color:#E8EDF2;margin-bottom:.75rem;">Параметры монтажа</div>
  <div style="font-size:.83rem;color:#8A9BAE;line-height:2.1;">
    🎨 <b style="color:#E8EDF2;">Стиль:</b> {sty_l}<br>
    📐 <b style="color:#E8EDF2;">Формат:</b> {fmt_l}<br>
    ⏱ <b style="color:#E8EDF2;">Длина:</b> {total:.0f} сек<br>
    🎞 <b style="color:#E8EDF2;">Клипов:</b> {len(segs)}<br>
    🔤 <b style="color:#E8EDF2;">Вариант:</b> {active}<br>
    🎵 <b style="color:#E8EDF2;">Музыка:</b> {"Есть" if st.session_state.get("audio_path") else "Нет"}<br>
    🎤 <b style="color:#E8EDF2;">Voiceover:</b> {"Есть" if st.session_state.get("voiceover_path") else "Нет"}
  </div>
</div>
""", unsafe_allow_html=True)


def _preview_state_missing() -> None:
    st.markdown("""
<div class="preview-state" style="padding:2rem;">
  <div class="preview-icon">🎬</div>
  <div class="preview-msg">
    Превью-файл ещё создаётся или недоступен.<br>
    <span style="color:#3B4A59;font-size:.78rem;">Обновите страницу или повторите генерацию</span>
  </div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 8 · RENDER
# ══════════════════════════════════════════════════════════════════════════════
def _screen_render() -> None:
    _wizard_bar()

    st.markdown("## Финальный рендер")
    state = st.session_state.get("render_state","not_started")

    if state == "not_started":
        active = st.session_state.get("tl_variant","A")
        segs   = st.session_state.get("tl_variants",{}).get(active,[])
        total  = sum(s.get("_clip_dur",0) for s in segs)
        fmt_id = st.session_state.get("selected_format","fullhd_horizontal")
        fmt_info = next((f for f in _FORMAT_OPTIONS if f["id"]==fmt_id), _FORMAT_OPTIONS[3])

        st.markdown(f"""
<div class="vp-card" style="margin-bottom:1rem;">
  <div style="font-weight:700;color:#E8EDF2;margin-bottom:.75rem;">Итоговые параметры</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.5rem;">
    <div class="stat-box"><div class="stat-val" style="font-size:1.2rem;">{fmt_info['w']}×{fmt_info['h']}</div><div class="stat-lbl">Разрешение</div></div>
    <div class="stat-box"><div class="stat-val" style="font-size:1.2rem;">{total:.0f}с</div><div class="stat-lbl">Длина</div></div>
    <div class="stat-box"><div class="stat-val" style="font-size:1.2rem;">{len(segs)}</div><div class="stat-lbl">Клипов</div></div>
  </div>
</div>
""", unsafe_allow_html=True)

        # ── Subtitles toggle ─────────────────────────────────────────────────
        with st.expander("🔤 Субтитры (Whisper AI)", expanded=False):
            subs_enabled = st.checkbox(
                "Добавить субтитры автоматически",
                value=bool(st.session_state.get("subtitles_enabled", False)),
                key="subs_toggle",
            )
            st.session_state.subtitles_enabled = subs_enabled
            if subs_enabled:
                model_opts = ["tiny", "base", "small", "medium"]
                model_idx  = model_opts.index(st.session_state.get("subtitle_model", "small"))
                chosen_model = st.selectbox(
                    "Модель Whisper",
                    model_opts,
                    index=model_idx,
                    key="subs_model",
                    help="small — хороший баланс скорости и качества; medium — точнее, дольше",
                )
                st.session_state.subtitle_model = chosen_model
                lang_in = st.text_input(
                    "Язык (ru / en / … — пусто = авто)",
                    value=st.session_state.get("subtitle_lang", ""),
                    key="subs_lang",
                    label_visibility="visible",
                )
                st.session_state.subtitle_lang = lang_in.strip() or None
                st.caption("Субтитры будут распознаны из аудиодорожки первого видео "
                           "и прожжены в финальный файл.")

        col = st.columns([1,2,1])[1]
        with col:
            if st.button("🚀  Запустить финальный рендер", use_container_width=True):
                st.session_state.render_state = "rendering"
                st.session_state.render_pct   = 0
                st.rerun()
        st.button("← Изменить превью", key="back_render", on_click=_back)

    elif state == "rendering":
        ph_msg  = st.empty()
        ph_prog = st.progress(0)
        ph_eta  = st.empty()

        ph_msg.markdown("""
<div class="preview-state generating" style="padding:1.5rem;">
  <div class="preview-icon">🎬</div>
  <div class="preview-msg">Создаётся финальное видео…<br>
    <span style="font-size:.78rem;color:#3B4A59;">Не закрывайте браузер</span>
  </div>
</div>
""", unsafe_allow_html=True)

        path, err = _do_render_final(ph_prog, ph_eta)
        if err:
            st.session_state.render_state = "failed"
            st.session_state.render_error = err
        else:
            st.session_state.render_state = "done"
            st.session_state.render_path  = path
            # Пути НЕ сбрасываем после рендера — только по «Новый проект».
            # Register in project history
            _register_project()
        st.rerun()

    elif state == "done":
        st.success("✓ Рендер завершён!")
        col = st.columns([1,2,1])[1]
        with col:
            if st.button("Смотреть результат →", use_container_width=True):
                _go("result")

    elif state == "failed":
        err = st.session_state.get("render_error","Неизвестная ошибка")
        st.markdown(f"""
<div class="preview-state failed">
  <div class="preview-icon">⚠️</div>
  <div class="preview-msg" style="color:#FF4C6A;">Ошибка рендера</div>
  <div style="font-size:.78rem;color:#8A9BAE;margin-bottom:1rem;">{err}</div>
</div>
""", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("↩ Повторить рендер", use_container_width=True):
                st.session_state.render_state = "rendering"
                st.rerun()
        with c2:
            if st.button("← Назад к монтажу", use_container_width=True):
                _go("timeline")


def _do_render_final(ph_prog, ph_eta) -> Tuple[Optional[str], str]:
    """
    Render final full-resolution video using FFmpegRenderer directly.
    Correct format dimensions, music sync, and output to ~/VideoProjects/{name}/output/.
    """
    active      = st.session_state.get("tl_variant", "A")
    segs        = st.session_state.get("tl_variants", {}).get(active, [])
    video_paths = st.session_state.get("video_paths", [])
    fmt_id      = st.session_state.get("selected_format", "fullhd_horizontal")
    target      = float(st.session_state.get("target_duration", 30))
    proj_name   = (st.session_state.get("project_name") or "project").replace(" ", "_")
    style_id    = st.session_state.get("selected_style", "")

    if not segs:
        return None, "Нет клипов в таймлайне"
    if not video_paths:
        return None, "Нет видеофайлов"

    segs = _resolve_segments(segs, video_paths)

    # Output path
    out_dir = Path.home() / "VideoProjects" / proj_name / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    suf = f"{style_id}_{fmt_id}_{int(target)}s"
    out_path = str(out_dir / f"{proj_name}_{suf}.mp4")

    ph_prog.progress(0.03)
    ph_eta.markdown(
        f'<p style="color:#8A9BAE;font-size:.78rem;">Подготовка {len(segs)} клипов…</p>',
        unsafe_allow_html=True,
    )

    try:
        from src.segment_selector import SelectedSegment
        from src.ffmpeg_renderer import FFmpegRenderer

        out_cfg = _fmt_output_config(fmt_id, target)

        selected: List = []
        for seg in segs:
            abs_p = seg.get("_abs_path", "")
            if not abs_p or not Path(abs_p).exists():
                continue
            start    = float(seg.get("start_s", 0.0))
            clip_dur = float(seg.get("_clip_dur", 3.0))
            end      = start + clip_dur
            _ss = SelectedSegment(
                source_path=abs_p,
                start=start,
                end=end,
                duration=clip_dur,
                is_must_use=False,
            )
            _ss._frag = seg                      # для TR-1 (match-cut решения)
            selected.append(_ss)

        if not selected:
            return None, "Ни один клип не найден на диске"

        # Фаза 4 (RF-1/RF-2): авто-реframe для вертикальных форматов 9:16.
        _fmt_opt = next((f for f in _FORMAT_OPTIONS if f["id"] == fmt_id), {})
        _is_vertical = _fmt_opt.get("h", 0) > _fmt_opt.get("w", 0)
        if _is_vertical:
            _apply_smart_reframe(selected, _is_vertical)

        style          = next((p for p in _STYLE_PRESETS if p["id"] == style_id), {})
        transition     = style.get("transition", "none")
        # Фаза 7 (TR-1): per-cut match-cut / cut-on-action поверх стиля.
        _assign_transitions(selected, "crossfade" if transition == "crossfade" else "cut")
        music_path     = st.session_state.get("audio_path")
        voiceover_path = st.session_state.get("voiceover_path")
        if music_path and not Path(music_path).exists():
            music_path = None
        if voiceover_path and not Path(voiceover_path).exists():
            voiceover_path = None

        # ── Subtitles: run Whisper transcription before render ─────────────
        subtitle_path: Optional[str] = None
        if st.session_state.get("subtitles_enabled") and video_paths:
            try:
                from backend.services.subtitle_service import SubtitleService
                ph_eta.markdown(
                    '<p style="color:#8A9BAE;font-size:.78rem;">🔤 Транскрипция Whisper…</p>',
                    unsafe_allow_html=True,
                )
                srt_dir = Path.home() / "VideoProjects" / proj_name / "subtitles"
                srt_dir.mkdir(parents=True, exist_ok=True)
                srt_path = str(srt_dir / f"{proj_name}.srt")
                _svc = SubtitleService()
                _model = st.session_state.get("subtitle_model", "small")
                _lang  = st.session_state.get("subtitle_lang") or None
                # AU-2: субтитры по СМОНТИРОВАННОЙ дорожке (а не video_paths[0]) —
                # совпадают с реальным порядком/длиной клипов (ARCHITECTURE §13.2).
                _tl_clips = [
                    {"source_path": s.source_path, "start_s": s.start, "duration": s.duration}
                    for s in selected
                ]
                try:
                    _svc.generate_srt_for_timeline(
                        clips=_tl_clips, output_srt=srt_path,
                        model_name=_model, language=_lang,
                    )
                except Exception as tl_exc:
                    logger.warning("[Subtitles] timeline SRT failed (%s) — fallback", tl_exc)
                    _svc.generate_srt(
                        source_path=video_paths[0], output_srt=srt_path,
                        model_name=_model, language=_lang,
                    )
                subtitle_path = srt_path
            except Exception as srt_exc:
                logger.warning(f"[Subtitles] Transcription failed: {srt_exc}")

        import re as _re2

        def _cb(*args) -> None:
            msg = args[0] if args else ""
            m = _re2.search(r'[Ss]egment\s+(\d+)/(\d+)', str(msg))
            if m:
                n, total_n = int(m.group(1)), int(m.group(2))
                pct = min(0.94, 0.05 + 0.85 * (n / max(total_n, 1)))
            else:
                pct = 0.95
            ph_prog.progress(pct)
            eta = max(0, target * (1 - pct) * 0.8)
            ph_eta.markdown(
                f'<p style="color:#8A9BAE;font-size:.78rem;">{msg or "Рендер…"} · ≈{eta:.0f}с</p>',
                unsafe_allow_html=True,
            )

        ph_prog.progress(0.05)
        FFmpegRenderer.render(
            segments=selected,
            output_config=out_cfg,
            output_path=out_path,
            music_path=music_path,
            music_fade_in=3.0,
            music_fade_out=3.0,
            voiceover_path=voiceover_path,
            subtitle_path=subtitle_path,
            effects_config=_build_effects_config(),
            progress_callback=_cb,
            between_clip_transition=transition if transition != "crossfade" else "fade",
            between_clip_transition_dur=0.5,
        )

        ph_prog.progress(1.0)
        ph_eta.markdown('<p style="color:#00FF88;font-size:.78rem;">✓ Готово</p>', unsafe_allow_html=True)

        if Path(out_path).exists() and Path(out_path).stat().st_size > 1000:
            st.session_state.render_path = out_path
            return out_path, ""
        return None, "Файл не создан — проверьте логи FFmpeg"

    except Exception as exc:
        return None, str(exc)


def _register_project() -> None:
    try:
        from backend.services.project_history_service import ProjectHistoryService
        root = st.session_state.get("project_root","")
        name = st.session_state.get("project_name","")
        if root and name:
            ProjectHistoryService().register(root, name)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 9 · RESULT
# ══════════════════════════════════════════════════════════════════════════════
def _screen_result() -> None:
    _wizard_bar()

    name     = st.session_state.get("project_name","Проект")
    fin_path = st.session_state.get("render_path")

    # ── Hero ─────────────────────────────────────────────────────────────────
    st.markdown(f"""
<div style="text-align:center;padding:1.5rem 0 1rem;">
  <div style="font-size:2.8rem;margin-bottom:.4rem;">🎉</div>
  <h1 style="font-size:2rem !important;background:linear-gradient(135deg,#00FF88,#00D4FF);
      -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
    Ролик готов!
  </h1>
  <p style="color:#8A9BAE;">{name}</p>
</div>
""", unsafe_allow_html=True)

    # Determine output folder
    proj_name = st.session_state.get("project_name", "project")
    output_dir = Path.home() / "VideoProjects" / proj_name / "output"

    col_v, col_r = st.columns([3,2])

    with col_v:
        if fin_path and Path(fin_path).exists():
            st.video(fin_path)
            sz = Path(fin_path).stat().st_size / 1e6
            st.markdown(f'<span class="badge b-green">✓ Готово · {sz:.1f} МБ</span>', unsafe_allow_html=True)
        else:
            # Show any video from the output folder
            found_video = None
            if output_dir.exists():
                mp4s = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
                # skip preview_ files
                finals = [p for p in mp4s if not p.name.startswith("preview_")]
                found_video = finals[0] if finals else (mp4s[0] if mp4s else None)

            if found_video:
                st.video(str(found_video))
                sz = found_video.stat().st_size / 1e6
                st.markdown(f'<span class="badge b-green">✓ {found_video.name} · {sz:.1f} МБ</span>', unsafe_allow_html=True)
            else:
                preview = st.session_state.get("preview_path")
                if preview and Path(preview).exists():
                    st.video(preview)
                    st.markdown('<span class="badge b-yellow">Превью-версия (480p)</span>', unsafe_allow_html=True)
                else:
                    st.info("Видеофайл ещё рендерится или не найден.")

    with col_r:
        # ── Output path block ─────────────────────────────────────────────────
        st.markdown(f"""
<div style="background:#0D1318;border:1px solid #1A2228;border-radius:12px;
            padding:.75rem 1rem;margin-bottom:.75rem;">
  <div style="font-size:.68rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
              color:#3B4A59;margin-bottom:.35rem;">Папка с результатами</div>
  <div style="font-size:.78rem;color:#00FF88;word-break:break-all;font-family:monospace;">
    ~/VideoProjects/{proj_name}/output/
  </div>
</div>
""", unsafe_allow_html=True)
        if st.button("📂  Открыть в Finder", use_container_width=True):
            import subprocess
            target = output_dir if output_dir.exists() else Path.home() / "VideoProjects"
            subprocess.Popen(["open", str(target)])

    with col_r:
        # Download
        if fin_path and Path(fin_path).exists():
            with open(fin_path, "rb") as f:
                st.download_button(
                    "⬇  Скачать видео",
                    data=f.read(),
                    file_name=f"{name.replace(' ','_')}.mp4",
                    mime="video/mp4",
                    use_container_width=True,
                )
            st.markdown("<br>", unsafe_allow_html=True)

        # Rating
        st.markdown("**Оцените результат:**")
        rating = st.session_state.get("render_rating", 0)
        stars  = "".join(
            f'<span style="font-size:1.5rem;color:{"#FFD246" if i<=rating else "#3B4A59"};">{"★" if i<=rating else "☆"}</span>'
            for i in range(1,6)
        )
        st.markdown(f'<div style="display:flex;gap:.3rem;margin-bottom:.5rem;">{stars}</div>', unsafe_allow_html=True)
        rc = st.columns(5)
        for i, c in enumerate(rc):
            with c:
                if st.button(str(i+1), key=f"star_{i+1}", use_container_width=True):
                    st.session_state.render_rating = i+1
                    st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)

        # Actions
        if st.button("🔄  Другой вариант", use_container_width=True):
            st.session_state.preview_state = "not_generated"
            _go("timeline")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✎  Вернуться к сценам", use_container_width=True):
            _go("scenes")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✦  Создать новое видео", use_container_width=True):
            # «Новый проект» — забыть сохранённые пути ДО _init (иначе восстановит).
            _clear_session_inputs()
            for k in list(st.session_state.keys()):
                if k != "screen":
                    del st.session_state[k]
            _init()
            _go("upload")

    # ── Share placeholder ─────────────────────────────────────────────────────
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("""
<div style="background:#12171D;border:1px solid #1A2228;border-radius:14px;padding:1rem 1.25rem;
            display:flex;gap:1rem;align-items:center;flex-wrap:wrap;">
  <span style="color:#8A9BAE;font-size:.82rem;">Поделиться:</span>
  <span style="background:#232B36;color:#E8EDF2;border-radius:8px;padding:.3rem .8rem;font-size:.8rem;cursor:pointer;">YouTube</span>
  <span style="background:#232B36;color:#E8EDF2;border-radius:8px;padding:.3rem .8rem;font-size:.8rem;cursor:pointer;">Instagram</span>
  <span style="background:#232B36;color:#E8EDF2;border-radius:8px;padding:.3rem .8rem;font-size:.8rem;cursor:pointer;">TikTok</span>
  <span style="color:#3B4A59;font-size:.75rem;">Скоро: публикация в один клик</span>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════
_MAP = {
    "upload":   _screen_upload,
    "analysis": _screen_analysis,
    "scenes":   _screen_scenes,
    "concept":  _screen_concept,
    "style":    _screen_style,
    "format":   _screen_format,
    "timeline": _screen_timeline,
    "preview":  _screen_preview,
    "render":   _screen_render,
    "result":   _screen_result,
}


def main() -> None:
    _MAP.get(st.session_state.get("screen","upload"), _screen_upload)()


if __name__ == "__main__":
    main()
