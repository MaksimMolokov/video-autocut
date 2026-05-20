"""
Streamlit GUI for Auto Video Cutter
MVP interface for semi-automatic video editing
Works with LOCAL files only - no file upload to memory
"""

import streamlit as st
from pathlib import Path
import sys
import os
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import ConfigLoader, Range, OutputConfig
from src.video_analyzer import VideoAnalyzer
from src.range_manager import RangeManager
from src.segment_selector import SegmentSelector
from src.ffmpeg_renderer import FFmpegRenderer
from src.project_manager import ProjectManager, validate_video_path
from src.effects_config import (
    StylePresets, TransitionType, SpeedMode, ColorStyle,
    MusicSyncMode, EffectsConfiguration, TransitionSettings,
    SpeedEffectSettings, ColorSettings, QualityFilterSettings,
    MusicSyncSettings, OverlaySettings
)
from src.effects_engine import EffectsEngine
from src.music_sync_integration import integrate_music_sync_with_selection
from src.presets import PresetRegistry, PresetApplier


# Page config
st.set_page_config(
    page_title="Auto Video Cutter",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Compact CSS
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0.5rem;
        max-width: 1400px;
    }
    h1 { padding-bottom: 0.25rem; font-size: 1.6rem; }
    h2 { padding-top: 0.25rem; padding-bottom: 0.2rem; font-size: 1.3rem; }
    h3 { padding-top: 0.2rem; padding-bottom: 0.15rem; font-size: 1.1rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] { padding: 6px 12px; }
    div[data-testid="stExpander"] { margin-top: 0.25rem; margin-bottom: 0.25rem; }
    div[data-testid="stVerticalBlock"] > div { gap: 0.4rem; }
    .stRadio label { font-size: 0.9rem; }
    .stButton button { padding: 0.25rem 0.75rem; }
    .element-container { margin-bottom: 0.25rem; }
    p { margin-bottom: 0.3rem; }
    hr { margin: 0.5rem 0; }
    .stAlert { padding: 0.4rem 0.8rem; }
</style>
""", unsafe_allow_html=True)


# State persistence functions
STATE_FILE = Path.home() / ".video_editor_draft_state.json"

def strip_quotes(path: str) -> str:
    """Remove surrounding quotes (single or double) from path string"""
    if not path:
        return path

    path = path.strip()

    # Remove surrounding quotes if present
    if (path.startswith("'") and path.endswith("'")) or \
       (path.startswith('"') and path.endswith('"')):
        path = path[1:-1]

    return path


def save_draft_state():
    """Save current draft state to disk for persistence across page reloads"""
    try:
        state_data = {
            'project_name': st.session_state.get('project_name', ''),
            'selected_videos': st.session_state.get('selected_videos', []),
            'selected_audio': st.session_state.get('selected_audio', None),
            'selected_preset_id': st.session_state.get('selected_preset_id', None),
            'target_duration': st.session_state.get('target_duration', None),
        }
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # Silently fail - state persistence is not critical
        pass

def load_draft_state():
    """Load draft state from disk if available"""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        # Silently fail and return empty state
        pass
    return {}

def clear_draft_state():
    """Clear saved draft state (called on successful project creation)"""
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
    except Exception:
        pass


# Load saved draft state (persists across page reloads)
saved_state = load_draft_state()

# Initialize session state
if 'project_created' not in st.session_state:
    st.session_state.project_created = False
if 'project_manager' not in st.session_state:
    st.session_state.project_manager = None
if 'project_name' not in st.session_state:
    st.session_state.project_name = saved_state.get('project_name', "")
if 'video_files' not in st.session_state:
    st.session_state.video_files = []
if 'ranges' not in st.session_state:
    st.session_state.ranges = {}
if 'music_path' not in st.session_state:
    st.session_state.music_path = None
if 'rendering' not in st.session_state:
    st.session_state.rendering = False
if 'output_path' not in st.session_state:
    st.session_state.output_path = None
if 'selected_preset' not in st.session_state:
    st.session_state.selected_preset = "clean_basic"
if 'effects_config' not in st.session_state:
    st.session_state.effects_config = None

# New navigation and preset state
if 'page' not in st.session_state:
    st.session_state.page = 'welcome'  # welcome / launch / manual_settings
if 'selected_videos' not in st.session_state:
    st.session_state.selected_videos = saved_state.get('selected_videos', [])
if 'available_videos' not in st.session_state:
    st.session_state.available_videos = []
if 'selected_audio' not in st.session_state:
    st.session_state.selected_audio = saved_state.get('selected_audio', None)
if 'available_audio' not in st.session_state:
    st.session_state.available_audio = []
if 'selected_preset_id' not in st.session_state:
    st.session_state.selected_preset_id = None
if 'preset_registry' not in st.session_state:
    presets_dir = Path(__file__).parent.parent / "presets"
    st.session_state.preset_registry = PresetRegistry(presets_dir)
if 'edit_mode' not in st.session_state:
    st.session_state.edit_mode = None  # "preset" / "manual" / "preset_with_manual_overrides"
if 'target_duration' not in st.session_state:
    st.session_state.target_duration = saved_state.get('target_duration', None)  # Duration in seconds
if 'generation_status' not in st.session_state:
    st.session_state.generation_status = None  # idle / starting / analyzing / rendering / completed / failed
if 'show_custom_duration' not in st.session_state:
    st.session_state.show_custom_duration = False

# Easy mode settings defaults
if 'easy_min_clip' not in st.session_state:
    st.session_state.easy_min_clip = 2.0
if 'easy_max_clip' not in st.session_state:
    st.session_state.easy_max_clip = 5.0
if 'easy_shuffle' not in st.session_state:
    st.session_state.easy_shuffle = True
if 'easy_avoid_repeat' not in st.session_state:
    st.session_state.easy_avoid_repeat = True
if 'easy_use_fixed_seed' not in st.session_state:
    st.session_state.easy_use_fixed_seed = False
if 'easy_seed_value' not in st.session_state:
    st.session_state.easy_seed_value = 42

# Vertical adaptation mode
if 'vertical_mode' not in st.session_state:
    st.session_state.vertical_mode = 'center_crop'

# Render progress and logging
if 'render_logs' not in st.session_state:
    st.session_state.render_logs = []
if 'render_progress' not in st.session_state:
    st.session_state.render_progress = 0
if 'render_stage' not in st.session_state:
    st.session_state.render_stage = ''

# Pre-processing state
if 'preprocessed_ranges' not in st.session_state:
    st.session_state.preprocessed_ranges = {}   # {video_path: List[Range]}
if 'preprocess_camera_moves' not in st.session_state:
    st.session_state.preprocess_camera_moves = True
if 'preprocess_pauses' not in st.session_state:
    st.session_state.preprocess_pauses = True
if 'preprocess_text' not in st.session_state:
    st.session_state.preprocess_text = False


def add_render_log(message: str, level: str = 'INFO'):
    """Append a timestamped log entry to session state render_logs."""
    import datetime
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    if 'render_logs' not in st.session_state:
        st.session_state.render_logs = []
    st.session_state.render_logs.append({'ts': ts, 'level': level, 'msg': str(message)})


def set_render_progress(pct: int, stage: str = ''):
    """Update render progress percentage and stage label."""
    st.session_state.render_progress = max(0, min(100, pct))
    if stage:
        st.session_state.render_stage = stage


def show_render_log_block():
    """Render a scrollable fixed-height log block from session state."""
    logs = st.session_state.get('render_logs', [])
    level_styles = {
        'INFO': 'color:#9cdcfe',
        'SUCCESS': 'color:#4ec9b0',
        'WARNING': 'color:#dcdcaa',
        'ERROR': 'color:#f48771',
    }
    lines = []
    for entry in logs[-80:]:
        style = level_styles.get(entry.get('level', 'INFO'), 'color:#cdd9e5')
        ts = entry.get('ts', '')
        level = entry.get('level', 'INFO')
        msg = str(entry.get('msg', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        lines.append(
            f'<div style="margin:0;padding:1px 0">'
            f'<span style="color:#6e7681">[{ts}]</span> '
            f'<span style="{style}">[{level}]</span> '
            f'<span style="color:#cdd9e5">&nbsp;{msg}</span>'
            f'</div>'
        )
    content = '\n'.join(lines) if lines else '<div style="color:#6e7681;padding:4px">Логи появятся здесь после запуска генерации</div>'
    html = (
        '<div style="height:220px;overflow-y:auto;background:#0d1117;color:#cdd9e5;'
        'font-family:ui-monospace,SFMono-Regular,monospace;font-size:11px;'
        'padding:10px 12px;border-radius:6px;border:1px solid #30363d;line-height:1.6">'
        + content + '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)
    if logs:
        col1, col2 = st.columns(2)
        with col1:
            if st.button('🗑 Очистить', use_container_width=True, key='clear_logs_btn'):
                st.session_state.render_logs = []
                st.rerun()
        with col2:
            log_text = '\n'.join(
                f"[{e.get('ts','')}] [{e.get('level','INFO')}] {e.get('msg','')}" for e in logs
            )
            st.download_button(
                '💾 Скачать лог', data=log_text, file_name='render_log.txt',
                use_container_width=True, key='dl_logs_btn'
            )


def main():
    """Main application entry point"""

    # Header
    st.title("🎬 Auto Video Cutter")
    st.caption("Автоматический монтаж видео — работа с локальными файлами")

    # Navigation based on page state
    if st.session_state.page == 'welcome':
        show_welcome_screen()
    elif st.session_state.page == 'launch':
        show_launch_page()
    elif st.session_state.page == 'auto_render':
        show_auto_render_screen()
    elif st.session_state.page == 'manual_settings':
        show_editor_screen()  # This has manual settings
    elif st.session_state.project_created:
        # Fallback for old flow compatibility
        show_editor_screen()
    else:
        # Default to welcome
        show_welcome_screen()


def show_preprocess_section(selected_videos: list):
    """
    Optional pre-processing step — shown between video/audio selection and style.
    Detects problematic segments (camera moves, pauses, on-screen text) and
    stores filtered good ranges in st.session_state.preprocessed_ranges.
    """
    from src.preprocessor import VideoPreprocessor, PreprocessOptions

    has_results = bool(st.session_state.preprocessed_ranges)
    expander_label = (
        "🔧 Предобработка ✓ применена"
        if has_results else
        "🔧 Предобработка (для очень проблемных видео)"
    )

    with st.expander(expander_label, expanded=False):
        st.caption(
            "Необязательный шаг. Автоматически находит и исключает проблемные участки: "
            "поднятие/опускание камеры, технические паузы, видео с текстом/уведомлениями."
        )

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            cam = st.checkbox(
                "📷 Подъём/опускание камеры",
                value=st.session_state.preprocess_camera_moves,
                key="pp_camera",
                help="Тёмные кадры + отсутствие движения в начале/конце или внутри клипа",
            )
            st.session_state.preprocess_camera_moves = cam
        with col_b:
            pau = st.checkbox(
                "⏸ Технические паузы",
                value=st.session_state.preprocess_pauses,
                key="pp_pauses",
                help="Длительные статичные кадры без движения (стоячий кадр, замороженная сцена)",
            )
            st.session_state.preprocess_pauses = pau
        with col_c:
            txt = st.checkbox(
                "💬 Текст на экране",
                value=st.session_state.preprocess_text,
                key="pp_text",
                help="SMS-уведомления, интерфейсные оверлеи — высокая плотность краёв + неподвижность",
            )
            st.session_state.preprocess_text = txt

        btn_col, clear_col = st.columns([3, 1])

        with btn_col:
            if st.button(
                "▶ Запустить предобработку",
                key="run_preprocess_btn",
                use_container_width=True,
                type="primary",
                disabled=not selected_videos,
            ):
                if not (cam or pau or txt):
                    st.warning("Выберите хотя бы один тип фильтрации.")
                else:
                    options = PreprocessOptions(
                        detect_camera_moves=cam,
                        detect_pauses=pau,
                        detect_text=txt,
                    )
                    new_pp = {}
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    for i, vpath in enumerate(selected_videos):
                        from src.video_analyzer import VideoAnalyzer
                        try:
                            meta = VideoAnalyzer.analyze(vpath)
                            dur = meta.duration
                        except Exception:
                            dur = 0.0

                        if dur <= 0:
                            continue

                        fname = Path(vpath).name
                        status_text.caption(f"Анализ: {fname}...")

                        def _cb(frac, msg, _bar=progress_bar, _txt=status_text, _f=fname):
                            overall = (i + frac) / len(selected_videos)
                            _bar.progress(min(1.0, overall))
                            _txt.caption(f"{_f}: {msg}")

                        try:
                            result = VideoPreprocessor.analyze(
                                video_path=vpath,
                                video_duration=dur,
                                options=options,
                                progress_callback=_cb,
                            )
                            new_pp[vpath] = result.good_ranges
                        except Exception as e:
                            st.warning(f"Ошибка при анализе {fname}: {e}")

                    st.session_state.preprocessed_ranges = new_pp
                    progress_bar.empty()
                    status_text.empty()
                    st.rerun()

        with clear_col:
            if has_results:
                if st.button(
                    "✕ Сбросить",
                    key="clear_preprocess_btn",
                    use_container_width=True,
                ):
                    st.session_state.preprocessed_ranges = {}
                    st.rerun()

        # Show summary when results exist
        if st.session_state.preprocessed_ranges:
            st.write("")
            for vpath, ranges in st.session_state.preprocessed_ranges.items():
                good_dur = sum(r.end - r.start for r in ranges)
                st.caption(
                    f"✓ **{Path(vpath).name}** — "
                    f"{len(ranges)} диапазон(ов), {good_dur:.1f}s полезного видео"
                )


def show_welcome_screen():
    """Compact two-column welcome screen."""

    st.markdown("#### Новый проект автомонтажа")

    # ── Project name ─────────────────────────────────────────────────────────
    project_name = st.text_input(
        "Название проекта",
        value=st.session_state.get('project_name', ''),
        placeholder="Мой видео проект",
        key="welcome_project_name",
        label_visibility="visible"
    )
    if project_name:
        st.session_state.project_name = project_name
        save_draft_state()

    # ── Two-column main layout ────────────────────────────────────────────────
    left_col, right_col = st.columns([5, 6], gap="large")

    with left_col:
        # ── Video ──────────────────────────────────────────────────────────
        st.write("**📹 Видео**")
        cv1, cv2 = st.columns(2)
        with cv1:
            video_folder_raw = st.text_input(
                "Папка с видео", placeholder="/path/to/videos",
                key="vfolder_input", label_visibility="visible"
            )
        with cv2:
            video_file_raw = st.text_input(
                "Конкретный файл", placeholder="/path/to/video.mp4",
                key="vfile_input", label_visibility="visible"
            )

        if video_folder_raw:
            video_folder = strip_quotes(video_folder_raw)
            if Path(video_folder).exists():
                video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.MP4', '.MOV']
                videos = []
                for ext in video_extensions:
                    videos.extend(list(Path(video_folder).glob(f'*{ext}')))
                if videos:
                    st.session_state.available_videos = [str(v) for v in videos]
                    st.caption(f"✓ Найдено: {len(videos)}")

        if video_file_raw:
            video_file = strip_quotes(video_file_raw)
            if Path(video_file).exists():
                if str(video_file) not in st.session_state.available_videos:
                    st.session_state.available_videos.append(str(video_file))
                st.caption(f"✓ {Path(video_file).name}")

        if st.session_state.available_videos:
            new_sel = st.multiselect(
                "Выберите видео",
                options=st.session_state.available_videos,
                default=[v for v in st.session_state.selected_videos if v in st.session_state.available_videos],
                format_func=lambda x: Path(x).name,
                key="video_multiselect",
                label_visibility="collapsed"
            )
            if new_sel != st.session_state.selected_videos:
                st.session_state.selected_videos = new_sel
                save_draft_state()
        if st.session_state.selected_videos:
            st.caption(f"✓ Выбрано: {len(st.session_state.selected_videos)} файл(ов)")

        # ── Audio ──────────────────────────────────────────────────────────
        st.write("**🎵 Аудио**")
        ca1, ca2 = st.columns(2)
        with ca1:
            audio_folder_raw = st.text_input(
                "Папка с аудио", placeholder="/path/to/music",
                key="afolder_input", label_visibility="visible"
            )
        with ca2:
            audio_file_raw_inline = st.text_input(
                "Аудио файл", placeholder="/path/to/music.mp3",
                key="afile_input", label_visibility="visible"
            )

        if audio_folder_raw:
            audio_folder = strip_quotes(audio_folder_raw)
            if Path(audio_folder).exists():
                audio_extensions = ['.mp3', '.wav', '.m4a', '.aac', '.MP3', '.WAV']
                audios = []
                for ext in audio_extensions:
                    audios.extend(list(Path(audio_folder).glob(f'*{ext}')))
                if audios:
                    st.session_state.available_audio = [str(a) for a in audios]
                    st.caption(f"✓ Найдено: {len(audios)}")

        if audio_file_raw_inline:
            audio_file_inline = strip_quotes(audio_file_raw_inline)
            if Path(audio_file_inline).exists():
                st.session_state.selected_audio = str(audio_file_inline)
                save_draft_state()
                st.caption(f"✓ {Path(audio_file_inline).name}")

        if st.session_state.available_audio:
            sel_audio = st.selectbox(
                "Выберите аудио",
                options=["(не выбрано)"] + st.session_state.available_audio,
                format_func=lambda x: Path(x).name if x != "(не выбрано)" else x,
                label_visibility="collapsed"
            )
            if sel_audio != "(не выбрано)":
                st.session_state.selected_audio = sel_audio
                save_draft_state()

        if st.session_state.selected_audio:
            st.caption(f"✓ {Path(st.session_state.selected_audio).name}")

    with right_col:
        # ── Style selection ─────────────────────────────────────────────────
        st.write("**🎨 Стиль монтажа**")

        registry = st.session_state.preset_registry
        presets = registry.list_presets()
        all_preset_ids = [p['preset_id'] for p in presets]
        preset_labels = {p['preset_id']: f"{p['emoji']} {p['name']}" for p in presets}
        preset_labels['manual'] = "⚙️ Manual"

        current_pid = st.session_state.get('selected_preset_id')
        radio_options = all_preset_ids + ['manual']
        try:
            radio_idx = radio_options.index(current_pid) if current_pid in radio_options else 0
        except ValueError:
            radio_idx = 0

        chosen_pid = st.radio(
            "Стиль",
            options=radio_options,
            index=radio_idx,
            format_func=lambda x: preset_labels.get(x, x),
            key="preset_radio_welcome",
            label_visibility="collapsed"
        )

        if chosen_pid != st.session_state.get('selected_preset_id'):
            if not st.session_state.project_name:
                st.error("❌ Введите название проекта")
            elif not st.session_state.selected_videos:
                st.error("❌ Выберите хотя бы одно видео")
            else:
                st.session_state.selected_preset_id = chosen_pid
                st.session_state.edit_mode = "preset" if chosen_pid != "manual" else "manual"
                if chosen_pid == "manual":
                    st.session_state.page = "manual_settings"
                    st.session_state.project_created = True
                    st.rerun()
                else:
                    save_draft_state()
                    st.rerun()

        if current_pid and current_pid != 'manual':
            preset_obj = registry.get_preset(current_pid)
            if preset_obj:
                desc = preset_obj.description
                if len(desc) > 100:
                    desc = desc[:97] + "…"
                st.caption(desc)

    # ── Pre-processing (optional, shown when videos are selected) ────────────
    if st.session_state.selected_videos:
        show_preprocess_section(st.session_state.selected_videos)

    # ── Bottom row: duration + format + easy settings + generate (only for presets)
    if st.session_state.get('selected_preset_id') and st.session_state.get('selected_preset_id') != "manual":
        b1, b2, b3 = st.columns([3, 2, 3], gap="medium")

        with b1:
            st.write("**⏱ Длительность**")
            dc = st.columns(4)
            for di, (secs, label) in enumerate([(30, "30с"), (60, "1м"), (90, "1.5м"), (180, "3м")]):
                with dc[di]:
                    is_sel = st.session_state.get('target_duration') == secs
                    if st.button(label, key=f"dur_{secs}", use_container_width=True,
                                 type="secondary" if is_sel else "primary"):
                        st.session_state.target_duration = secs
                        save_draft_state()
                        st.rerun()
            cc1, cc2, cc3 = st.columns([2, 2, 2])
            with cc1:
                cm = st.number_input("м", min_value=0, max_value=60, value=0, key="cdm", label_visibility="visible")
            with cc2:
                cs = st.number_input("с", min_value=0, max_value=59, value=0, key="cds", label_visibility="visible")
            with cc3:
                if st.button("Ввести", key="apply_dur", use_container_width=True):
                    total = cm * 60 + cs
                    if total > 0:
                        st.session_state.target_duration = total
                        save_draft_state()
                        st.rerun()
            if st.session_state.get('target_duration'):
                d = st.session_state.target_duration
                dm, ds = int(d) // 60, int(d) % 60
                st.caption(f"✓ {dm}м {ds}с" if dm else f"✓ {d:.0f}с")

        with b2:
            st.write("**📐 Формат**")
            fmt_opts = {
                "horizontal_16_9": "16:9 Horizontal",
                "vertical_9_16": "9:16 Vertical",
                "square_1_1": "1:1 Square",
                "original": "Оригинал",
            }
            sel_fmt = st.radio(
                "Формат",
                options=list(fmt_opts.keys()),
                format_func=lambda x: fmt_opts[x],
                key="output_format_radio",
                label_visibility="collapsed"
            )
            st.session_state.selected_output_format = sel_fmt

            # Vertical mode selector — only shown for 9:16 output
            if sel_fmt == "vertical_9_16":
                st.write("**📱 Вертикальный кадр**")
                _vert_opts = {
                    "center_crop": "✂️ Обрезать по центру",
                    "fit_blur":    "🌫 Вписать + размытый фон",
                    "left_crop":   "◀ Левая часть кадра",
                    "right_crop":  "▶ Правая часть кадра",
                }
                _vert_descs = {
                    "center_crop": "Масштабирует для заполнения, обрезает по центру. Рекомендуется.",
                    "fit_blur":    "Полное изображение целиком + размытый фон. Без обрезки.",
                    "left_crop":   "Сохраняет левую часть горизонтального кадра.",
                    "right_crop":  "Сохраняет правую часть горизонтального кадра.",
                }
                sel_vert = st.radio(
                    "Режим адаптации",
                    options=list(_vert_opts.keys()),
                    format_func=lambda x: _vert_opts[x],
                    key="vertical_mode_radio",
                    label_visibility="collapsed"
                )
                st.session_state.vertical_mode = sel_vert
                st.caption(_vert_descs.get(sel_vert, ""))

        with b3:
            if st.session_state.get('selected_preset_id') == 'easy_mode':
                st.write("**⚡ Easy настройки**")
                st.slider("Мин. клип (с)", 0.5, 10.0, step=0.5, key="easy_min_clip")
                st.slider("Макс. клип (с)", 1.0, 20.0, step=0.5, key="easy_max_clip")
                st.checkbox("Перемешать порядок", key="easy_shuffle")
                st.checkbox("Без повторов видео", key="easy_avoid_repeat")
                st.checkbox("Фиксированный seed", key="easy_use_fixed_seed")
                if st.session_state.get('easy_use_fixed_seed', False):
                    st.number_input("Seed", min_value=0, max_value=999999, step=1,
                                    key="easy_seed_value", label_visibility="collapsed")
            elif st.session_state.get('selected_preset_id') in ('sport_dynamic_cut', 'sport_highlight_impact'):
                st.write("**⚡ Настройки спорта**")
                st.select_slider(
                    "Интенсивность",
                    options=["Лёгкая", "Средняя", "Высокая"],
                    value=st.session_state.get('sport_intensity', 'Средняя'),
                    key="sport_intensity",
                )
                st.select_slider(
                    "Частота склеек",
                    options=["Обычная", "Быстро", "Очень быстро"],
                    value=st.session_state.get('sport_cut_frequency', 'Быстро'),
                    key="sport_cut_frequency",
                )
                st.checkbox("Замедление на кульминации", value=True, key="sport_slow_motion")
                st.checkbox("Разгон скорости", value=True, key="sport_speed_ramp")
                st.checkbox("Синхронизация с битом", value=True, key="sport_beat_sync")
            else:
                # Music sync warning
                if st.session_state.get('selected_preset_id'):
                    preset_chk = st.session_state.preset_registry.get_preset(st.session_state.selected_preset_id)
                    if preset_chk and preset_chk.settings.music_sync.enabled and not st.session_state.selected_audio:
                        st.caption("⚠️ Стиль использует синхронизацию с музыкой — добавьте аудио")

        # ── Validation & Generate button ──────────────────────────────────────
        errors = []
        if not st.session_state.project_name:
            errors.append("Название проекта")
        if not st.session_state.selected_videos:
            errors.append("Видеофайлы")
        if not st.session_state.get('target_duration'):
            errors.append("Длительность")

        can_start = len(errors) == 0

        if errors:
            st.caption("⚠️ Не заполнено: " + ", ".join(errors))

        if st.button(
            "🎬 Сгенерировать видео",
            type="primary",
            use_container_width=True,
            disabled=not can_start,
            key="gen_btn_welcome"
        ):
            st.session_state.page = "auto_render"
            st.session_state.generation_status = "starting"
            st.session_state.render_logs = []
            st.session_state.render_progress = 0
            st.session_state.render_stage = ''
            st.rerun()



def display_preset_card(preset_info: dict):
    """Display single preset card"""
    with st.container():
        st.markdown(f"### {preset_info['emoji']} {preset_info['name']}")
        st.caption(preset_info['description'])

        # Show recommended_for tags
        if preset_info.get('recommended_for'):
            tags = preset_info['recommended_for'][:2]  # Show first 2 tags
            tags_str = ", ".join(tags)
            st.text(f"🎯 {tags_str}")

        # Special info for Easy mode
        if preset_info['preset_id'] == 'easy_mode':
            st.info(
                "⚡ **Easy** — мгновенный монтаж без анализа. "
                "Случайные фрагменты + музыка. Каждый запуск — новый ролик."
            )

        # Special info for Intelligent Beauty Mix
        if preset_info['preset_id'] == 'intelligent_beauty_mix':
            st.warning("⏱️ Может анализироваться дольше обычных шаблонов")
            st.info(
                "🧠✨ **Intelligent Beauty Mix** использует глубокий анализ: "
                "ищет красивые кадры, выбирает opening/closing shots, "
                "максимизирует разнообразие и техническое качество."
            )

        # Select button - now just marks as selected, doesn't navigate
        is_selected = st.session_state.get('selected_preset_id') == preset_info['preset_id']
        button_label = "✓ Выбрано" if is_selected else "Выбрать"
        button_type = "secondary" if is_selected else "primary"

        button_key = f"preset_{preset_info['preset_id']}"
        if st.button(button_label, key=button_key, use_container_width=True, type=button_type):
            # Validate required fields
            if not st.session_state.project_name:
                st.error("❌ Введите название проекта")
                return

            if not st.session_state.selected_videos:
                st.error("❌ Выберите хотя бы один видеофайл")
                return

            # Just save selection, don't navigate
            st.session_state.selected_preset_id = preset_info['preset_id']
            st.session_state.edit_mode = "preset"
            save_draft_state()
            st.rerun()


def display_manual_card():
    """Display Manual settings card"""
    with st.container():
        st.markdown("### ⚙️ Manual / Ручная настройка")
        st.caption("Ручной режим для самостоятельной настройки всех параметров монтажа: длительности фрагментов, переходов, скорости, цвета, синхронизации с музыкой, качества, framing и экспорта.")

        # Placeholder for alignment
        st.text("")

        if st.button("Выбрать", key="preset_manual", use_container_width=True):
            # Validate required fields
            if not st.session_state.project_name:
                st.error("❌ Введите название проекта")
                return

            if not st.session_state.selected_videos:
                st.error("❌ Выберите хотя бы один видеофайл")
                return

            # Go to manual settings
            st.session_state.selected_preset_id = "manual"
            st.session_state.edit_mode = "manual"
            st.session_state.page = "manual_settings"
            st.session_state.project_created = True  # Enable editor screen
            st.rerun()


def create_project(name: str, project_dir: str, preset: str):
    """Create new project with preset"""
    if not name:
        st.error("Введите название проекта")
        return

    # Create project manager
    project_path = Path(project_dir) / name.replace(" ", "_")
    pm = ProjectManager(project_path)

    st.session_state.project_name = name
    st.session_state.project_manager = pm
    st.session_state.project_created = True
    st.session_state.preset = preset

    # Apply preset defaults
    preset_config = ConfigLoader.get_preset(preset)
    st.session_state.output_format = preset_config["format"]
    st.session_state.dynamic_level = preset_config["dynamic_level"]
    st.session_state.target_duration = 60.0

    st.success(f"✓ Проект создан: {project_path}")
    st.rerun()


def show_launch_page():
    """Launch page with project summary and start button"""

    st.header("🚀 Запуск монтажа")
    st.markdown("---")

    # Project Summary
    st.subheader("📋 Резюме проекта")

    col1, col2 = st.columns(2)

    with col1:
        st.write(f"**Название:** {st.session_state.project_name}")
        st.write(f"**Видео:** {len(st.session_state.selected_videos)} файл(ов)")
        with st.expander("Показать список видео"):
            for video in st.session_state.selected_videos:
                st.caption(f"• {Path(video).name}")

    with col2:
        if st.session_state.selected_audio:
            st.write(f"**Аудио:** {Path(st.session_state.selected_audio).name}")
        else:
            st.write("**Аудио:** не выбрано")

    st.markdown("---")

    # Preset Details
    if st.session_state.selected_preset_id and st.session_state.selected_preset_id != "manual":
        st.subheader(f"🎨 Выбранный шаблон")

        preset = st.session_state.preset_registry.get_preset(st.session_state.selected_preset_id)

        if preset:
            st.write(f"{preset.emoji} **{preset.name}**")
            st.caption(preset.description)

            # Settings Summary
            with st.expander("Основные настройки шаблона"):
                s = preset.settings
                st.write(f"• **Dynamic level:** {s.dynamic_level.value}")
                st.write(f"• **Clip duration:** {s.clip_selection.segment_min_duration}-{s.clip_selection.segment_max_duration}s")
                st.write(f"• **Transitions:** {s.transitions.type.value} ({s.transitions.duration}s)")
                st.write(f"• **Speed effects:** {s.speed_effects.mode.value} (intensity: {s.speed_effects.intensity.value})")
                st.write(f"• **Color:** {s.color.style.value} (intensity: {s.color.intensity.value})")
                st.write(f"• **Music sync:** {s.music_sync.mode.value}")
                st.write(f"• **Audio selection:** {s.audio_selection.mode.value}")
                st.write(f"• **Output format:** {s.export.format.value} ({s.export.quality.value} quality)")
                st.write(f"• **Resolution:** {s.export.resolution if s.export.resolution else 'auto'}")

    else:
        st.subheader("⚙️ Ручные настройки")
        st.write("Настройки заданы вручную. Перейдите к ручным настройкам для просмотра.")

    st.markdown("---")

    # Action Buttons
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("« Назад", use_container_width=True):
            st.session_state.page = "welcome"
            st.rerun()

    with col2:
        if st.button("⚙️ Изменить настройки вручную", use_container_width=True):
            # Mark as manual overrides if coming from preset
            if st.session_state.edit_mode == "preset":
                st.session_state.edit_mode = "preset_with_manual_overrides"

            st.session_state.page = "manual_settings"
            st.session_state.project_created = True  # Enable editor
            st.rerun()

    with col3:
        if st.button("🎬 Начать генерацию видео", type="primary", use_container_width=True):
            # Validate project
            errors = []

            if not st.session_state.project_name:
                errors.append("Не указано название проекта")

            if not st.session_state.selected_videos:
                errors.append("Не выбраны видеофайлы")

            # Check music_sync requirement
            if st.session_state.selected_preset_id and st.session_state.selected_preset_id != "manual":
                preset = st.session_state.preset_registry.get_preset(st.session_state.selected_preset_id)
                if preset and preset.settings.music_sync.enabled and not st.session_state.selected_audio:
                    errors.append("Пресет требует синхронизацию с музыкой, но аудио не выбрано")

            if errors:
                for error in errors:
                    st.error(f"❌ {error}")
                return

            # Apply preset if selected
            if st.session_state.selected_preset_id and st.session_state.selected_preset_id != "manual":
                apply_preset_to_session(st.session_state.selected_preset_id)

            # Initialize project
            project_dir = Path.home() / "VideoProjects"
            project_path = project_dir / st.session_state.project_name.replace(" ", "_")
            pm = ProjectManager(project_path)

            st.session_state.project_manager = pm
            st.session_state.project_created = True

            # Convert selected videos to video_files format with metadata
            with st.spinner("Загрузка метаданных видео..."):
                video_files = []
                for video_path in st.session_state.selected_videos:
                    try:
                        metadata = VideoAnalyzer.analyze(video_path)
                        video_info = {
                            'name': Path(video_path).name,
                            'path': video_path,
                            'metadata': metadata
                        }
                        video_files.append(video_info)
                        # Initialize empty ranges for this video
                        if video_path not in st.session_state.ranges:
                            st.session_state.ranges[video_path] = []
                    except Exception as e:
                        st.error(f"Ошибка при анализе {Path(video_path).name}: {e}")
                        return

                st.session_state.video_files = video_files

            st.session_state.music_path = st.session_state.selected_audio

            # Set flag to start rendering immediately
            st.session_state.auto_start_render = True

            # Clear page so main() falls through to project_created check
            st.session_state.page = None

            st.success(f"✓ Проект инициализирован: {project_path}")
            st.success(f"✓ Загружено {len(video_files)} видео")
            st.info("Переход к монтажу...")

            # Go to editor which will auto-start render
            st.rerun()


def get_versioned_output_filename(project_name: str, preset_id: str, duration: int, output_dir: Path) -> str:
    """Generate versioned output filename to avoid overwriting existing files"""
    # Base name format: projectname_presetid_duration
    preset_short = preset_id.replace('_', '')[:10] if preset_id else 'custom'
    base_name = f"{project_name.replace(' ', '_')}_{preset_short}_{duration}s"

    # Check if file exists, add version number if needed
    version = 1
    output_name = f"{base_name}.mp4"
    output_path = output_dir / output_name

    while output_path.exists():
        output_name = f"{base_name}_v{version}.mp4"
        output_path = output_dir / output_name
        version += 1

    return output_name


def show_auto_render_screen():
    """Two-column generation screen: left = summary + actions, right = progress + logs + result."""

    # ── Compact header ────────────────────────────────────────────────────────
    hc1, hc2 = st.columns([1, 9])
    with hc1:
        if st.button("← Назад", key="back_from_render"):
            st.session_state.page = 'welcome'
            st.session_state.generation_status = None
            st.rerun()
    with hc2:
        st.markdown("#### 🎬 Генерация видео")

    status = st.session_state.get('generation_status', 'starting')

    left, right = st.columns([4, 6], gap="large")

    # ── LEFT COLUMN: summary + action buttons ────────────────────────────────
    with left:
        vids = st.session_state.selected_videos
        aud = st.session_state.selected_audio
        dur = st.session_state.get('target_duration', 0)
        dur_m, dur_s = int(dur) // 60, int(dur) % 60
        dur_str = f"{dur_m}м {dur_s}с" if dur_m else f"{dur:.0f}с"

        st.write(f"**{st.session_state.project_name}**")
        st.caption(
            f"📹 {len(vids)} видео  ·  ⏱ {dur_str}  ·  "
            f"🎵 {Path(aud).name if aud else 'нет аудио'}"
        )

        pid = st.session_state.get('selected_preset_id')
        if pid and pid != 'manual':
            preset = st.session_state.preset_registry.get_preset(pid)
            if preset:
                st.write(f"{preset.emoji} **{preset.name}**")
                desc = preset.description[:90] + "…" if len(preset.description) > 90 else preset.description
                st.caption(desc)
                if pid == 'easy_mode':
                    seed_info = str(st.session_state.get('easy_seed_value', 42)) if st.session_state.get('easy_use_fixed_seed') else "случайный"
                    st.caption(
                        f"Клипы {st.session_state.get('easy_min_clip', 2.0):.1f}–"
                        f"{st.session_state.get('easy_max_clip', 5.0):.1f}с  ·  seed: {seed_info}"
                    )
                else:
                    with st.expander("Параметры", expanded=False):
                        s = preset.settings
                        st.caption(f"Dynamic: {s.dynamic_level.value}")
                        st.caption(f"Clips: {s.clip_selection.segment_min_duration}–{s.clip_selection.segment_max_duration}s")
                        st.caption(f"Transitions: {s.transitions.type.value}")
                        st.caption(f"Color: {s.color.style.value}")

        fmt = st.session_state.get('selected_output_format', 'horizontal_16_9')
        fmt_labels = {'horizontal_16_9': '16:9', 'vertical_9_16': '9:16', 'square_1_1': '1:1', 'original': 'Оригинал'}
        st.caption(f"📐 {fmt_labels.get(fmt, fmt)}")

        # Action buttons
        if status in ('completed', 'failed'):
            st.write("")
            if st.button("🎬 Сгенерировать заново", use_container_width=True, type="primary", key="regen_btn"):
                st.session_state.generation_status = 'starting'
                st.session_state.render_logs = []
                st.session_state.render_progress = 0
                st.session_state.render_stage = ''
                st.rerun()
            if st.button("🎨 Изменить стиль", use_container_width=True, key="change_style_btn"):
                st.session_state.page = 'welcome'
                st.session_state.selected_preset_id = None
                # Keep target_duration — user chose style, not duration
                st.session_state.generation_status = None
                st.rerun()
            if st.button("⏱ Изменить длительность", use_container_width=True, key="change_dur_btn"):
                st.session_state.page = 'welcome'
                st.session_state.target_duration = None
                st.session_state.generation_status = None
                st.rerun()
            if st.button("🏠 Новый проект", use_container_width=True, key="new_proj_btn"):
                reset_project()
                st.session_state.page = 'welcome'
                st.session_state.generation_status = None
                st.session_state.selected_videos = []
                st.session_state.selected_audio = None
                st.session_state.available_videos = []
                st.session_state.available_audio = []
                st.rerun()

    # ── RIGHT COLUMN: progress / render / result ──────────────────────────────
    with right:

        if status == 'starting':
            with st.spinner("Инициализация проекта..."):
                # Apply preset
                if pid and pid != 'manual':
                    apply_preset_to_session(pid)

                # Init project manager
                project_dir = Path.home() / "VideoProjects"
                project_path = project_dir / st.session_state.project_name.replace(" ", "_")
                pm = ProjectManager(project_path)
                st.session_state.project_manager = pm
                st.session_state.project_created = True

                # Load video metadata
                video_files = []
                for video_path in st.session_state.selected_videos:
                    try:
                        metadata = VideoAnalyzer.analyze(video_path)
                        video_files.append({
                            'name': Path(video_path).name,
                            'path': video_path,
                            'metadata': metadata
                        })
                        if video_path not in st.session_state.ranges:
                            st.session_state.ranges[video_path] = []
                    except Exception as e:
                        st.error(f"Ошибка анализа {Path(video_path).name}: {e}")
                        add_render_log(f"Ошибка анализа {Path(video_path).name}: {e}", 'ERROR')
                        st.session_state.generation_status = 'failed'
                        return

                st.session_state.video_files = video_files
                st.session_state.music_path = st.session_state.selected_audio

                output_name = get_versioned_output_filename(
                    st.session_state.project_name,
                    st.session_state.selected_preset_id,
                    st.session_state.target_duration,
                    pm.output_dir
                )
                st.session_state.output_name = output_name

            add_render_log(f"Проект: {st.session_state.project_name}")
            add_render_log(f"Загружено видео: {len(video_files)}")
            add_render_log(f"Выходной файл: {output_name}")
            add_render_log(
                f"[Init] Стиль={st.session_state.get('selected_preset_id')}  "
                f"Длительность={st.session_state.get('target_duration')}s"
            )
            st.session_state.generation_status = 'rendering'
            st.rerun()

        elif status == 'rendering':
            progress = st.session_state.get('render_progress', 0)
            stage = st.session_state.get('render_stage', 'Подготовка...')
            prog_bar = st.progress(max(0.01, progress / 100))
            stage_txt = st.empty()
            stage_txt.caption(f"**{progress}%** — {stage}")
            render_video()

        elif status == 'completed':
            st.success("✅ Видео создано успешно!")

            if st.session_state.output_path and Path(st.session_state.output_path).exists():
                output_path = Path(st.session_state.output_path)
                file_size = output_path.stat().st_size / (1024 * 1024)
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.metric("Файл", output_path.name)
                with col_m2:
                    st.metric("Размер", f"{file_size:.1f} MB")
                st.code(str(output_path), language=None)
                if st.button("📂 Открыть папку", use_container_width=True, key="open_folder_btn"):
                    os.system(f'open "{output_path.parent}"')

            st.write("**📋 Лог генерации**")
            show_render_log_block()

        elif status == 'failed':
            st.error("❌ Ошибка генерации")
            st.write("**📋 Лог ошибок**")
            show_render_log_block()


def apply_preset_to_session(preset_id: str):
    """Apply preset settings to session state"""
    import logging
    logger = logging.getLogger(__name__)

    preset = st.session_state.preset_registry.get_preset(preset_id)

    if not preset:
        st.error(f"Пресет {preset_id} не найден")
        return

    s = preset.settings

    # Map new format values to old GUI values
    format_map = {
        'original': 'horizontal',
        'horizontal_16_9': 'horizontal',
        'vertical_9_16': 'vertical',
        'square_1_1': 'square'
    }

    # Apply settings to session_state
    st.session_state.dynamic_level = s.dynamic_level.value

    # IMPORTANT: User format choice ALWAYS overrides preset format
    if 'selected_output_format' in st.session_state:
        user_format = st.session_state.selected_output_format

        # Map user format to old GUI format
        user_format_map = {
            'horizontal_16_9': 'horizontal',
            'vertical_9_16': 'vertical',
            'square_1_1': 'square',
            'original': 'horizontal'
        }

        st.session_state.output_format = user_format_map.get(user_format, 'horizontal')

        logger.info(
            f"User format '{user_format}' overrides preset format "
            f"from '{s.export.format.value}'"
        )
    else:
        # No user selection, use preset format
        st.session_state.output_format = format_map.get(s.export.format.value, 'horizontal')

    # Store preset settings for rendering
    st.session_state.preset_settings = preset

    # Transitions
    if s.transitions.enabled:
        st.session_state.transition_type = s.transitions.type.value
        st.session_state.transition_duration = s.transitions.duration
    else:
        st.session_state.transition_type = 'cut'
        st.session_state.transition_duration = 0.0

    # Speed effects
    if s.speed_effects.enabled:
        st.session_state.speed_mode = s.speed_effects.mode.value
        st.session_state.slow_motion_factor = s.speed_effects.slow_motion_factor
        st.session_state.speed_up_factor = s.speed_effects.speed_up_factor
    else:
        st.session_state.speed_mode = 'none'

    # Color - map preset color styles to effects_config styles
    color_style_map = {
        'cinematic_warm': 'warm',
        'clean_bright': 'basic_enhance',
        'clean_contrast': 'high_contrast',
        'high_contrast': 'high_contrast',
        'punchy': 'high_contrast',
        'natural_bright': 'natural',
        'natural': 'natural',
        'warm': 'warm',
        'none': 'none',
    }
    if s.color.enabled:
        mapped_color = color_style_map.get(s.color.style.value, 'none')
        st.session_state.color_style = mapped_color
    else:
        st.session_state.color_style = 'none'

    # Audio fade
    st.session_state.fade_in = s.audio_selection.fade_in
    st.session_state.fade_out = s.audio_selection.fade_out

    # Music sync
    if s.music_sync.enabled:
        st.session_state.music_sync_mode = s.music_sync.mode.value
    else:
        st.session_state.music_sync_mode = 'none'

    st.success(f"✓ Применён пресет: {preset.name}")


def show_editor_screen():
    """Main editor screen"""

    pm = st.session_state.project_manager

    # Compact progress indicator
    num_videos = len(st.session_state.video_files)
    total_ranges = sum(len(ranges) for ranges in st.session_state.ranges.values())
    has_music = st.session_state.music_path is not None

    status_parts = []
    if num_videos > 0:
        status_parts.append(f"✅ Видео: {num_videos}")
    else:
        status_parts.append("❌ Видео: 0")

    if total_ranges > 0:
        status_parts.append(f"✅ Интервалы: {total_ranges}")
    else:
        status_parts.append("Интервалы: 0")

    if has_music:
        status_parts.append("✅ Музыка")

    if num_videos > 0:
        status_parts.append("✅ Готов")

    st.caption(" | ".join(status_parts))

    # Sidebar - Left panel
    with st.sidebar:
        st.header(f"📁 {st.session_state.project_name}")

        if st.button("🏠 Новый проект"):
            reset_project()
            st.rerun()

        # Show project info
        with st.expander("ℹ️ Информация о проекте"):
            st.write(f"**Папка:** {pm.project_path}")
            st.write(f"**Свободно:** {pm.get_free_space_gb():.1f} GB")

        st.markdown("---")

        # Video files section
        st.subheader("📹 Исходные видео")

        # Add video by path
        video_path_input = st.text_input(
            "Путь к видео",
            placeholder="/путь/к/видео.mp4",
            help="Укажите полный путь к локальному видеофайлу",
            key="video_path_input"
        )

        if st.button("Добавить видео", use_container_width=True, type="primary"):
            if video_path_input:
                add_video_by_path(video_path_input)
            else:
                st.error("Введите путь к видеофайлу")

        st.caption("💡 Вставьте путь к файлу и нажмите 'Добавить видео'")

        st.write("")

        # Add folder
        folder_path_input = st.text_input(
            "Или добавить папку с видео",
            placeholder="/путь/к/папке",
            help="Укажите полный путь к папке с видеофайлами",
            key="folder_path_input"
        )

        if st.button("📁 Добавить папку", use_container_width=True):
            if folder_path_input:
                add_videos_from_folder(folder_path_input)
            else:
                st.error("Введите путь к папке")

        st.caption("📁 Добавит все видео из указанной папки")

        # Show added videos
        if st.session_state.video_files:
            for i, video_info in enumerate(st.session_state.video_files):
                with st.expander(f"📹 {video_info['name']}", expanded=False):
                    if 'metadata' in video_info:
                        meta = video_info['metadata']
                        st.caption(f"{meta.duration:.0f}s | {meta.resolution}")

                        # File size
                        size_mb = Path(video_info['path']).stat().st_size / (1024**2)
                        if size_mb < 1024:
                            st.caption(f"Размер: {size_mb:.0f} MB")
                        else:
                            st.caption(f"Размер: {size_mb/1024:.1f} GB")

                    # Show ranges for this video
                    video_path = video_info['path']
                    if video_path in st.session_state.ranges and st.session_state.ranges[video_path]:
                        ranges = st.session_state.ranges[video_path]
                        good_count = len([r for r in ranges if r.type == "good"])
                        must_count = len([r for r in ranges if r.type == "must_use"])
                        bad_count = len([r for r in ranges if r.type == "bad"])
                        st.caption(f"🟢 {good_count} | 🔵 {must_count} | 🔴 {bad_count}")
                    else:
                        st.caption("Интервалы: нет")

                    if st.button("🗑️ Удалить", key=f"remove_video_{i}"):
                        st.session_state.video_files.pop(i)
                        if video_path in st.session_state.ranges:
                            del st.session_state.ranges[video_path]
                        st.rerun()
        else:
            st.caption("Нет видео")

        st.write("")

        # Music section
        st.subheader("🎵 Музыка")

        music_path_input = st.text_input(
            "Путь к музыке",
            placeholder="/путь/к/музыке.mp3",
            help="Укажите полный путь к локальному аудиофайлу",
            key="music_path_input"
        )

        if st.button("Добавить", use_container_width=True, key="add_music_btn"):
            if music_path_input:
                music_path = Path(music_path_input)
                if music_path.exists():
                    st.session_state.music_path = str(music_path)
                    st.success(f"✓ {music_path.name}")
                    st.rerun()
                else:
                    st.error("Файл не найден")
            else:
                st.error("Введите путь к аудиофайлу")

        if st.session_state.music_path:
            st.success(f"✓ {Path(st.session_state.music_path).name}")

    # Main content area - show guide if no videos
    if not st.session_state.video_files:
        st.info("👈 Добавьте видео в левой панели → Разметка → Настройки → Сборка")

    # Always show tabs - they will have helpful messages if prerequisites aren't met
    st.write("")
    tab1, tab2, tab3 = st.tabs(["📝 Разметка интервалов", "⚙️ Настройки", "🎬 Сборка"])

    with tab1:
        show_range_editor()

    with tab2:
        show_settings_panel()

    with tab3:
        show_render_panel()


def add_video_by_path(video_path: str):
    """Add video file by local path"""
    # Remove quotes if present (single or double)
    video_path = strip_quotes(video_path)

    # Validate path
    is_valid, message = validate_video_path(video_path)

    if not is_valid:
        st.error(message)
        return

    # Show warning if exists
    if message:
        st.warning(message)

    # Check if already added
    for vid in st.session_state.video_files:
        if vid['path'] == video_path:
            st.warning(f"Видео уже добавлено: {Path(video_path).name}")
            return

    # Analyze video
    try:
        with st.spinner("Анализ видео..."):
            metadata = VideoAnalyzer.analyze(video_path)

        video_info = {
            'name': Path(video_path).name,
            'path': video_path,
            'metadata': metadata
        }

        st.session_state.video_files.append(video_info)
        st.session_state.ranges[video_path] = []

        st.success(f"✓ Видео добавлено: {Path(video_path).name}")
        st.rerun()

    except Exception as e:
        st.error(f"Ошибка анализа видео: {e}")


def add_videos_from_folder(folder_path: str):
    """Add all video files from a folder"""
    # Remove quotes if present
    folder_path = strip_quotes(folder_path)

    folder = Path(folder_path)

    # Validate folder
    if not folder.exists():
        st.error(f"Папка не найдена: {folder_path}")
        return

    if not folder.is_dir():
        st.error(f"Это не папка: {folder_path}")
        return

    # Find all video files
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.m4v', '.MP4', '.MOV', '.AVI', '.MKV', '.M4V']
    video_files = []

    for ext in video_extensions:
        video_files.extend(folder.glob(f'*{ext}'))

    if not video_files:
        st.warning(f"В папке не найдено видеофайлов: {folder_path}")
        return

    # Add each video
    added_count = 0
    skipped_count = 0
    error_count = 0

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, video_file in enumerate(video_files):
        video_path = str(video_file)

        # Update progress
        progress = (i + 1) / len(video_files)
        progress_bar.progress(progress)
        status_text.text(f"Обработка {i + 1}/{len(video_files)}: {video_file.name}")

        # Check if already added
        already_added = False
        for vid in st.session_state.video_files:
            if vid['path'] == video_path:
                skipped_count += 1
                already_added = True
                break

        if already_added:
            continue

        # Analyze and add video
        try:
            metadata = VideoAnalyzer.analyze(video_path)

            video_info = {
                'name': video_file.name,
                'path': video_path,
                'metadata': metadata
            }

            st.session_state.video_files.append(video_info)
            st.session_state.ranges[video_path] = []
            added_count += 1

        except Exception as e:
            st.warning(f"Ошибка при добавлении {video_file.name}: {e}")
            error_count += 1

    # Clear progress
    progress_bar.empty()
    status_text.empty()

    # Show summary
    if added_count > 0:
        st.success(f"✓ Добавлено видео: {added_count}")
    if skipped_count > 0:
        st.info(f"ℹ️ Пропущено (уже добавлены): {skipped_count}")
    if error_count > 0:
        st.error(f"✗ Ошибок: {error_count}")

    if added_count > 0:
        st.rerun()


def show_range_editor():
    """Range editor interface"""

    st.header("📝 Разметка интервалов")

    if not st.session_state.video_files:
        st.warning("⚠️ Сначала добавьте видео в левой панели")
        return

    # Compact help
    total_ranges = sum(len(ranges) for ranges in st.session_state.ranges.values())
    if total_ranges == 0:
        st.info("💡 Интервалы необязательны. Без них программа использует всё видео.")
    video_names = [v['name'] for v in st.session_state.video_files]
    selected_video_name = st.selectbox(
        "Видео",
        video_names,
        help="Интервалы добавляются индивидуально для каждого видео"
    )

    # Get selected video
    selected_video = None
    for vid in st.session_state.video_files:
        if vid['name'] == selected_video_name:
            selected_video = vid
            break

    if not selected_video:
        return

    video_path = selected_video['path']
    metadata = selected_video['metadata']

    # Compact video info
    st.caption(f"📁 {metadata.duration:.0f}s | {metadata.resolution} | {metadata.fps:.0f}fps")

    # Add range form
    st.subheader("➕ Добавить интервал")

    col1, col2, col3 = st.columns(3)

    with col1:
        range_start = st.number_input(
            "Начало (сек)",
            min_value=0.0,
            max_value=metadata.duration,
            value=0.0,
            step=0.1,
            key=f"range_start_{video_path}"
        )

    with col2:
        range_end = st.number_input(
            "Конец (сек)",
            min_value=0.0,
            max_value=metadata.duration,
            value=min(10.0, metadata.duration),
            step=0.1,
            key=f"range_end_{video_path}"
        )

    with col3:
        range_type = st.selectbox(
            "Тип интервала",
            ["good", "must_use", "bad"],
            format_func=lambda x: {
                "good": "🟢 Good",
                "must_use": "🔵 Must-use",
                "bad": "🔴 Bad"
            }[x],
            key=f"range_type_{video_path}"
        )

    if st.button("➕ Добавить интервал", use_container_width=True):
        add_range(video_path, range_start, range_end, range_type, metadata.duration)

    # Show existing ranges
    st.write("")
    st.write("**📋 Список интервалов:**")

    if video_path in st.session_state.ranges and st.session_state.ranges[video_path]:
        ranges = st.session_state.ranges[video_path]

        for i, r in enumerate(ranges):
            col1, col2, col3, col4 = st.columns([1, 2, 2, 1])

            with col1:
                icon = {
                    "good": "🟢",
                    "must_use": "🔵",
                    "bad": "🔴"
                }[r.type]
                st.write(icon)

            with col2:
                st.write(f"{r.start:.1f}s - {r.end:.1f}s")

            with col3:
                st.write(f"Длительность: {r.duration:.1f}s")

            with col4:
                if st.button("🗑️", key=f"del_{video_path}_{i}"):
                    st.session_state.ranges[video_path].pop(i)
                    st.rerun()

        # Show stats
        stats = RangeManager.get_stats(ranges, metadata.duration)
        st.caption(f"📊 Доступно: {stats.available_duration:.0f}s ({stats.good_ratio:.0%}) | Good: {stats.num_good} | Must-use: {stats.num_must_use}")
    else:
        st.caption("Нет интервалов")


def add_range(video_path: str, start: float, end: float, range_type: str, video_duration: float):
    """Add range to video"""
    try:
        # Validate
        if start >= end:
            st.error("Начало должно быть меньше конца")
            return

        if end > video_duration:
            st.error(f"Конец интервала ({end}s) превышает длительность видео ({video_duration}s)")
            return

        # Create range
        new_range = Range(start=start, end=end, type=range_type)

        # Add to session state
        if video_path not in st.session_state.ranges:
            st.session_state.ranges[video_path] = []

        st.session_state.ranges[video_path].append(new_range)

        st.success(f"✓ Интервал добавлен: {start:.1f}s - {end:.1f}s")
        st.rerun()

    except Exception as e:
        st.error(f"Ошибка добавления интервала: {e}")


def show_settings_panel():
    """Settings panel"""

    st.header("⚙️ Настройки итогового ролика")

    # ==== PRESET SELECTION ====
    st.subheader("🎨 Выбор стиля")

    presets = StylePresets.list_presets()
    preset_options = list(presets.keys())
    preset_labels = [f"{info['emoji']} {info['name']}" for info in presets.values()]

    current_preset_idx = preset_options.index(st.session_state.selected_preset) if st.session_state.selected_preset in preset_options else 0

    selected_preset_idx = st.selectbox(
        "Готовый стиль монтажа",
        range(len(preset_options)),
        index=current_preset_idx,
        format_func=lambda i: preset_labels[i],
        help="Выберите готовый стиль или настройте вручную ниже"
    )

    selected_preset = preset_options[selected_preset_idx]

    if selected_preset != st.session_state.selected_preset:
        st.session_state.selected_preset = selected_preset
        # Load preset defaults
        preset_config = StylePresets.get_preset(selected_preset)
        st.session_state.dynamic_level = preset_config.get("dynamic_level", "balanced")
        st.rerun()

    # Show preset description
    st.caption(f"{presets[selected_preset]['emoji']} {presets[selected_preset]['description']}")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🎯 Основные настройки")

        target_duration = st.number_input(
            "Целевая длительность (сек)",
            min_value=1.0,
            max_value=600.0,
            value=st.session_state.get('target_duration', 60.0),
            step=1.0
        )
        st.session_state.target_duration = target_duration

        output_format = st.selectbox(
            "Формат вывода",
            ["horizontal", "vertical", "square"],
            index=["horizontal", "vertical", "square"].index(
                st.session_state.get('output_format', 'horizontal')
            ),
            format_func=lambda x: {
                "horizontal": "🖥️ Horizontal (1920×1080)",
                "vertical": "📱 Vertical (1080×1920)",
                "square": "⬛ Square (1080×1080)"
            }[x]
        )
        st.session_state.output_format = output_format

        st.write("")
        st.write("**🎬 Стиль монтажа**")

        dynamic_level = st.selectbox(
            "Динамика",
            ["slow", "balanced", "fast"],
            index=["slow", "balanced", "fast"].index(
                st.session_state.get('dynamic_level', 'balanced')
            ),
            format_func=lambda x: {
                "slow": "🐢 Slow (3-10 сек)",
                "balanced": "⚖️ Balanced (2-6 сек)",
                "fast": "⚡ Fast (1-4 сек)"
            }[x]
        )
        st.session_state.dynamic_level = dynamic_level

        # Alternating videos setting
        num_videos = len(st.session_state.video_files)
        if num_videos > 1:
            st.subheader("🔀 Чередование видео")

            alternate_videos = st.checkbox(
                f"Чередовать кусочки из {num_videos} видео",
                value=st.session_state.get('alternate_videos', True),
                help="Если включено, кусочки из разных видео будут чередоваться (рекомендуется)"
            )
            st.session_state.alternate_videos = alternate_videos

            if alternate_videos:
                st.caption("✓ Чередование включено")
        else:
            st.session_state.alternate_videos = False

    with col2:
        st.write("**🎵 Музыка**")

        use_music = st.checkbox(
            "Добавить фоновую музыку",
            value=st.session_state.music_path is not None
        )

        if use_music and st.session_state.music_path:
            st.success(f"✓ Музыка: {Path(st.session_state.music_path).name}")

            fade_in = st.slider("Fade in (сек)", 0.0, 10.0, 3.0, 0.5)
            st.session_state.fade_in = fade_in

            fade_out = st.slider("Fade out (сек)", 0.0, 10.0, 3.0, 0.5)
            st.session_state.fade_out = fade_out
        elif use_music:
            st.caption("⚠️ Добавьте музыку в левой панели")

        st.write("")
        st.write("**💾 Экспорт**")

        output_name = st.text_input(
            "Имя файла",
            value=f"{st.session_state.project_name}_output.mp4"
        )
        st.session_state.output_name = output_name

    # ==== ADVANCED EFFECTS SETTINGS ====
    st.write("")
    st.write("**🎬 Дополнительные эффекты**")
    st.caption("Опционально")

    with st.expander("🔀 Переходы между фрагментами", expanded=False):
        transitions_enabled = st.checkbox(
            "Включить переходы",
            value=True,
            help="Добавить эффекты перехода между фрагментами"
        )

        if transitions_enabled:
            transition_type = st.selectbox(
                "Тип перехода",
                [t.value for t in TransitionType],
                index=0,
                format_func=lambda x: {
                    "cut": "Cut (чистая склейка)",
                    "crossfade": "Crossfade (наложение)",
                    "fade": "Fade (через затемнение)",
                    "zoom": "Zoom (через приближение)",
                    "swipe": "Swipe (сдвиг)",
                    "blur": "Blur (размытие)",
                    "flash": "Flash (вспышка)"
                }.get(x, x)
            )

            transition_duration = st.slider(
                "Длительность перехода (сек)",
                0.1, 2.0, 0.3, 0.1,
                help="Длительность эффекта перехода"
            )

            st.session_state.transition_type = transition_type
            st.session_state.transition_duration = transition_duration
        else:
            st.session_state.transition_type = "cut"
            st.session_state.transition_duration = 0.0

    with st.expander("⚡ Эффекты скорости", expanded=False):
        speed_enabled = st.checkbox(
            "Включить эффекты скорости",
            value=False,
            help="Замедление, ускорение или speed ramp"
        )

        if speed_enabled:
            speed_mode = st.selectbox(
                "Режим",
                [m.value for m in SpeedMode if m != SpeedMode.NONE],
                format_func=lambda x: {
                    "slow_motion": "Slow Motion (замедление)",
                    "speed_up": "Speed Up (ускорение)",
                    "speed_ramp": "Speed Ramp (плавная смена)",
                    "auto_dynamic": "Auto Dynamic (автоматически)"
                }.get(x, x)
            )

            if speed_mode == "slow_motion":
                slow_factor = st.slider(
                    "Коэффициент замедления",
                    0.5, 0.95, 0.75, 0.05,
                    help="0.5 = половинная скорость, 0.75 = 75% скорости"
                )
                st.session_state.slow_motion_factor = slow_factor

            elif speed_mode == "speed_up":
                speed_factor = st.slider(
                    "Коэффициент ускорения",
                    1.05, 2.0, 1.25, 0.05,
                    help="1.25 = 125% скорости, 1.5 = полторы скорости"
                )
                st.session_state.speed_up_factor = speed_factor

            st.session_state.speed_mode = speed_mode
        else:
            st.session_state.speed_mode = "none"

    with st.expander("🎨 Цветокоррекция", expanded=False):
        color_enabled = st.checkbox(
            "Включить цветокоррекцию",
            value=False,
            help="Улучшение цвета и контраста"
        )

        if color_enabled:
            color_style = st.selectbox(
                "Стиль",
                [c.value for c in ColorStyle if c != ColorStyle.NONE],
                format_func=lambda x: {
                    "basic_enhance": "Basic Enhance (базовое улучшение)",
                    "cinematic": "Cinematic (кинематографичный)",
                    "natural": "Natural (естественные цвета)",
                    "warm": "Warm (тёплые тона)",
                    "high_contrast": "High Contrast (высокий контраст)"
                }.get(x, x)
            )

            col_a, col_b = st.columns(2)
            with col_a:
                brightness = st.slider("Яркость", -0.3, 0.3, 0.0, 0.05)
                saturation = st.slider("Насыщенность", -0.3, 0.3, 0.0, 0.05)
            with col_b:
                contrast = st.slider("Контраст", -0.3, 0.3, 0.0, 0.05)
                temperature = st.slider("Температура", -0.3, 0.3, 0.0, 0.05)

            st.session_state.color_style = color_style
            st.session_state.color_brightness = brightness
            st.session_state.color_contrast = contrast
            st.session_state.color_saturation = saturation
            st.session_state.color_temperature = temperature
        else:
            st.session_state.color_style = "none"

    with st.expander("🎵 Синхронизация с музыкой (расширенная)", expanded=False):
        music_sync_enabled = st.checkbox(
            "Включить синхронизацию",
            value=False,
            help="Интеллектуальный монтаж под музыку с анализом структуры, настроения и энергии"
        )

        if music_sync_enabled:
            # Import presets
            from src.music_sync.presets import (
                MusicSyncPreset, PRESET_CONFIGS,
                get_preset_description, validate_settings
            )

            # Preset selection
            preset_options = [p.value for p in MusicSyncPreset]
            preset_labels = {
                "dynamic": "🚀 Dynamic (динамичный)",
                "nature": "🌿 Nature (природа)",
                "dance": "💃 Dance (танцевальный)",
                "cinematic": "🎬 Cinematic (кинематографичный)",
                "social": "📱 Social (для соцсетей)",
                "calm_story": "📖 Calm Story (спокойный рассказ)",
                "manual": "⚙️ Manual (ручные настройки)"
            }

            selected_preset = st.selectbox(
                "Выберите пресет",
                options=preset_options,
                format_func=lambda x: preset_labels.get(x, x),
                help="Готовые настройки для разных стилей видео. Manual — для полного контроля"
            )

            # Show preset description
            if selected_preset != "manual":
                description = get_preset_description(MusicSyncPreset(selected_preset))
                st.info(f"ℹ️ {description}")

            st.session_state.music_sync_preset = selected_preset

            # Manual mode - show all settings
            if selected_preset == "manual":
                st.markdown("### ⚙️ Ручные настройки")
                st.caption("Полный контроль над всеми параметрами синхронизации")

                # Base mode selection
                base_mode = st.selectbox(
                    "Базовый режим",
                    ["structure_sync", "mood_sync", "smart_beat_sync", "visual_match_sync", "dynamic_sync", "beat_sync", "simple_tempo"],
                    format_func=lambda x: {
                        "structure_sync": "Music Structure Sync (по структуре трека)",
                        "mood_sync": "Mood Adaptive Sync (по настроению)",
                        "smart_beat_sync": "Smart Beat Priority (умные биты)",
                        "visual_match_sync": "Visual-Music Match (видео-музыка)",
                        "dynamic_sync": "Energy Curve Sync (кривая энергии)",
                        "beat_sync": "Beat Sync (точные биты)",
                        "simple_tempo": "Simple Tempo (простой темп)"
                    }.get(x, x),
                    help="Выберите основной алгоритм синхронизации"
                )
                st.session_state.music_sync_mode = base_mode

                # Advanced manual settings in tabs
                tab1, tab2, tab3, tab4 = st.tabs(["🎵 Биты и ритм", "⚡ Энергия", "✂️ Клипы", "🎨 Дополнительно"])

                with tab1:
                    st.markdown("#### Синхронизация по битам")
                    beat_sensitivity = st.select_slider(
                        "Чувствительность к битам",
                        options=["very_low", "low", "medium", "high", "very_high"],
                        value="high",
                        format_func=lambda x: {"very_low": "Очень низкая", "low": "Низкая", "medium": "Средняя", "high": "Высокая", "very_high": "Очень высокая"}.get(x, x),
                        key="beat_sensitivity"
                    )
                    st.checkbox("Только сильные биты", value=True, key="strong_beats_only")
                    st.slider("Толерантность к биту (сек)", 0.05, 0.5, 0.15, 0.05, key="beat_tolerance")
                    st.slider("Резать каждые N битов", 1, 16, 4, key="cut_every_n_beats")

                with tab2:
                    st.markdown("#### Адаптация к энергии")
                    st.slider("Чувствительность к энергии", 0.0, 1.0, 0.7, 0.1, key="energy_sensitivity")
                    st.slider("Акцент на кульминации", 0.0, 1.0, 0.8, 0.1, key="climax_emphasis")
                    st.slider("Акцент на дропах", 0.0, 1.0, 0.7, 0.1, key="drop_emphasis")
                    st.checkbox("Спокойное интро/аутро", value=True, key="calm_intro_outro")

                with tab3:
                    st.markdown("#### Параметры клипов")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.number_input("Мин. длительность (сек)", 0.3, 10.0, 0.8, 0.1, key="min_clip_duration")
                    with col2:
                        st.number_input("Макс. длительность (сек)", 1.0, 20.0, 4.0, 0.5, key="max_clip_duration")

                    st.slider("Общая динамика", 0.0, 1.0, 0.7, 0.1,
                             help="0 = медленно и спокойно, 1 = быстро и динамично", key="overall_dynamics")

                with tab4:
                    st.markdown("#### Дополнительные опции")
                    st.checkbox("Определять структуру трека", value=True, key="detect_structure")
                    st.checkbox("Адаптироваться к настроению", value=True, key="mood_adaptive")
                    st.checkbox("Умный выбор битов", value=True, key="smart_beat_priority")
                    st.checkbox("Сопоставление видео с музыкой", value=False, key="visual_music_match")

            else:
                # Preset mode - store preset name for later use
                st.session_state.music_sync_mode = "preset"

                # Option to view/modify preset settings
                with st.expander("🔍 Просмотр настроек пресета", expanded=False):
                    preset_config = PRESET_CONFIGS.get(MusicSyncPreset(selected_preset))
                    if preset_config:
                        settings = preset_config["settings"]
                        st.caption(f"**Базовый режим:** {preset_config.get('base_mode', 'dynamic_sync')}")
                        st.caption(f"**Длительность клипов:** {settings.min_clip_duration:.1f}s - {settings.max_clip_duration:.1f}s")
                        st.caption(f"**Динамика:** {settings.overall_dynamics:.1f}")
                        st.caption(f"**Чувствительность к битам:** {settings.beat_sensitivity.value}")
                        st.caption(f"**Определение структуры:** {'✓' if settings.detect_music_structure else '✗'}")
        else:
            st.session_state.music_sync_mode = "none"
            st.session_state.music_sync_preset = None


def show_render_panel():
    """Render panel"""

    # Auto-start rendering if flag is set
    if st.session_state.get('auto_start_render', False):
        st.session_state.auto_start_render = False  # Reset flag
        st.info("🎬 Автоматический запуск сборки...")
        render_video()
        return

    st.header("🎬 Сборка видео")

    pm = st.session_state.project_manager

    # Big status message at the top
    num_videos = len(st.session_state.video_files)
    total_ranges = sum(len(ranges) for ranges in st.session_state.ranges.values())

    if num_videos == 0:
        st.warning("⚠️ Добавьте видео в левой панели")
        return

    if total_ranges == 0:
        st.info("ℹ️ Интервалы не указаны — будет использоваться всё видео")

    # Check ranges
    total_available = 0
    video_sizes = []
    total_video_duration = 0

    for video_info in st.session_state.video_files:
        video_path = video_info['path']
        video_sizes.append(Path(video_path).stat().st_size)
        video_duration = video_info['metadata'].duration
        total_video_duration += video_duration

        if video_path in st.session_state.ranges and st.session_state.ranges[video_path]:
            ranges = st.session_state.ranges[video_path]
            stats = RangeManager.get_stats(ranges, video_duration)
            total_available += stats.available_duration
        else:
            # Если интервалов нет, используем всё видео
            total_available += video_duration

    target = st.session_state.target_duration

    # Check disk space
    required_space = pm.estimate_required_space_gb(
        video_sizes,
        target,
        st.session_state.music_path is not None
    )
    free_space = pm.get_free_space_gb()

    st.subheader("📊 Проверка проекта")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Доступно материала", f"{total_available:.1f}s")

    with col2:
        st.metric("Целевая длительность", f"{target:.1f}s")

    with col3:
        if total_available >= target:
            st.metric("Материал", "✓ Достаточно", delta="OK")
        else:
            st.metric("Материал", "✗ Недостаточно", delta=f"-{target - total_available:.1f}s")

    with col4:
        if free_space >= required_space:
            st.metric("Место на диске", f"{free_space:.1f} GB", delta="OK")
        else:
            st.metric("Место на диске", f"{free_space:.1f} GB", delta=f"Нужно {required_space:.1f} GB")

    # Show warnings
    if total_available < target:
        st.error(f"✗ Недостаточно материала: добавьте ещё {target - total_available:.1f}s good интервалов")

    if free_space < required_space:
        st.error(f"✗ Недостаточно места: освободите ~{required_space - free_space:.1f} GB")

    # Render button
    can_render = (total_available >= target * 0.9 and free_space >= required_space)

    st.write("")

    if st.session_state.rendering:
        st.warning("⏳ Идёт сборка видео... Подождите.")
        return

    if not can_render:
        st.error("❌ Устраните проблемы выше")
        return

    # Big prominent button
    st.success("✅ Готово к сборке")

    if st.button("🎬 СОБРАТЬ ВИДЕО", type="primary", use_container_width=True, key="render_button_main"):
        render_video()

    # Show result if available
    if st.session_state.output_path and Path(st.session_state.output_path).exists():
        st.markdown("---")
        st.subheader("✅ Результат")

        output_path = Path(st.session_state.output_path)
        file_size = output_path.stat().st_size / (1024 * 1024)

        st.success(f"📁 Файл: {output_path.name}")
        st.info(f"📊 Размер: {file_size:.1f} MB")
        st.info(f"📂 Путь: {output_path}")

        if st.button("📂 Открыть папку"):
            os.system(f'open "{output_path.parent}"')


def render_video():
    """Render final video — all status messages go to add_render_log()."""
    import logging
    import traceback as _traceback
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    st.session_state.rendering = True
    clear_draft_state()
    pm = st.session_state.project_manager

    add_render_log("=== Начало сборки видео ===")
    add_render_log(
        f"Стиль: {st.session_state.get('selected_preset_id', 'manual')}  |  "
        f"Длительность: {st.session_state.get('target_duration')}s  |  "
        f"Видео: {len(st.session_state.video_files)}  |  "
        f"Музыка: {st.session_state.music_path or 'нет'}"
    )
    _td_check = st.session_state.get('target_duration')
    if not _td_check or _td_check <= 0:
        add_render_log("target_duration не задана или равна нулю — отмена сборки", 'ERROR')
        st.session_state.rendering = False
        st.session_state.generation_status = 'failed'
        return
    set_render_progress(5, "Подготовка источников")

    try:
        with st.spinner("🎬 Генерация видео..."):
            # Apply sport preset overrides before reading session state for effects
            _sport_presets_set = {'sport_dynamic_cut', 'sport_highlight_impact'}
            _cur_preset_id = st.session_state.get('selected_preset_id', 'manual')
            if _cur_preset_id in _sport_presets_set:
                _sp_intensity = st.session_state.get('sport_intensity', 'Средняя')
                _sp_cut       = st.session_state.get('sport_cut_frequency', 'Быстро')
                _sp_slow      = st.session_state.get('sport_slow_motion', True)
                _sp_ramp      = st.session_state.get('sport_speed_ramp', True)
                _sp_sync      = st.session_state.get('sport_beat_sync', True)

                # Transitions
                if _sp_cut == "Очень быстро":
                    st.session_state.transition_type = 'flash'
                    st.session_state.transition_duration = 0.12
                elif _sp_cut == "Быстро":
                    st.session_state.transition_type = 'flash'
                    st.session_state.transition_duration = 0.22
                else:
                    st.session_state.transition_type = 'cut'
                    st.session_state.transition_duration = 0.0

                # Speed
                _slow_f = {'Лёгкая': 0.65, 'Средняя': 0.50, 'Высокая': 0.35}.get(_sp_intensity, 0.50)
                _fast_f = {'Лёгкая': 1.50, 'Средняя': 2.00, 'Высокая': 2.50}.get(_sp_intensity, 2.00)
                st.session_state.slow_motion_factor = _slow_f
                st.session_state.speed_up_factor = _fast_f
                if _sp_ramp:
                    st.session_state.speed_mode = 'speed_ramp'
                elif _sp_slow:
                    st.session_state.speed_mode = 'slow_motion'
                else:
                    st.session_state.speed_mode = 'none'

                # Music sync
                if not _sp_sync:
                    st.session_state.music_sync_mode = 'none'
                else:
                    st.session_state.music_sync_mode = (
                        'beat_sync' if _cur_preset_id == 'sport_dynamic_cut' else 'dynamic_sync'
                    )
                    _beats = {'Обычная': 4, 'Быстро': 2, 'Очень быстро': 1}.get(_sp_cut, 2)
                    st.session_state.cut_every_n_beats = _beats

                add_render_log(
                    f"[Sport] {_cur_preset_id} | {_sp_intensity} | "
                    f"склейки={_sp_cut} | ramp={_sp_ramp} | sync={_sp_sync}"
                )

            # Validate music sync
            music_sync_mode = st.session_state.get('music_sync_mode', 'none')
            if music_sync_mode != 'none' and not st.session_state.music_path:
                add_render_log("Синхронизация с музыкой включена, но музыка не выбрана", 'ERROR')
                st.session_state.rendering = False
                return

            # Build sources list
            # Priority: manual ranges > preprocessed ranges > full video
            sources = []
            _pp_ranges = st.session_state.get('preprocessed_ranges', {})
            for video_info in st.session_state.video_files:
                video_path = video_info['path']
                video_duration = video_info['metadata'].duration
                if video_path in st.session_state.ranges and st.session_state.ranges[video_path]:
                    ranges = st.session_state.ranges[video_path]
                elif video_path in _pp_ranges and _pp_ranges[video_path]:
                    ranges = _pp_ranges[video_path]
                    good_dur = sum(r.end - r.start for r in ranges)
                    add_render_log(
                        f"Предобработка: {video_info['name']} — "
                        f"{len(ranges)} диапазон(ов), {good_dur:.1f}s"
                    )
                else:
                    ranges = [Range(start=0.0, end=video_duration, type="good")]
                    add_render_log(f"Без разметки: {video_info['name']} — используется целиком ({video_duration:.1f}s)")
                sources.append({'path': video_path, 'ranges': ranges, 'duration': video_duration, 'name': video_info['name']})

            set_render_progress(15, "Настройка музыкальной синхронизации")

            # Music sync settings
            music_sync_mode_str = st.session_state.get('music_sync_mode', 'none')
            music_sync_preset = st.session_state.get('music_sync_preset', None)
            try:
                if music_sync_preset and music_sync_preset != "manual":
                    from src.music_sync.presets import MusicSyncPreset, PRESET_CONFIGS
                    preset_enum = MusicSyncPreset(music_sync_preset)
                    preset_config = PRESET_CONFIGS.get(preset_enum)
                    if preset_config:
                        advanced_settings = preset_config["settings"]
                        base_mode = preset_config.get("base_mode", "dynamic_sync")
                        music_sync_settings = MusicSyncSettings(
                            enabled=True, mode=MusicSyncMode(base_mode),
                            cut_every_n_beats=advanced_settings.cut_every_n_beats,
                            prefer_strong_beats=advanced_settings.strong_beats_only,
                            use_beats_inside_sections=advanced_settings.use_beats_in_sections
                        )
                        add_render_log(f"Music sync пресет: {music_sync_preset} / {base_mode}")
                    else:
                        music_sync_settings = MusicSyncSettings(enabled=False, mode=MusicSyncMode.NONE)
                        add_render_log(f"Пресет {music_sync_preset} не найден — sync отключён", 'WARNING')
                elif music_sync_mode_str != 'none':
                    music_sync_settings = MusicSyncSettings(
                        enabled=True, mode=MusicSyncMode(music_sync_mode_str),
                        cut_every_n_beats=st.session_state.get('cut_every_n_beats', 4),
                        prefer_strong_beats=st.session_state.get('strong_beats_only', True),
                        use_beats_inside_sections=st.session_state.get('use_beats_in_sections', True)
                    )
                    add_render_log(f"Music sync (manual): {music_sync_mode_str}")
                else:
                    music_sync_settings = MusicSyncSettings(enabled=False, mode=MusicSyncMode.NONE)
            except Exception as e:
                add_render_log(f"Ошибка настройки music sync: {e} — fallback simple_tempo", 'WARNING')
                music_sync_settings = MusicSyncSettings(
                    enabled=True, mode=MusicSyncMode.SIMPLE_TEMPO,
                    cut_every_n_beats=4, prefer_strong_beats=True, use_beats_inside_sections=True
                )

            alternate = st.session_state.get('alternate_videos', True) if len(sources) > 1 else False
            if alternate and not music_sync_settings.enabled:
                add_render_log(f"Чередование: {len(sources)} видео")

            music_path = st.session_state.music_path if st.session_state.music_path else None

            # Audio selection
            set_render_progress(30, "Выбор аудио-фрагмента")
            audio_selection = None
            if music_path:
                from src.music_selection import MusicSelectionEngine
                _preset_id_for_audio = st.session_state.get('selected_preset_id', 'manual')
                try:
                    audio_selection = MusicSelectionEngine.select(
                        audio_path=music_path,
                        target_duration=st.session_state.target_duration,
                        preset_id=_preset_id_for_audio,
                        fade_in=st.session_state.get('fade_in', 2.0),
                        fade_out=st.session_state.get('fade_out', 2.0),
                    )
                    loop_note = " [loop]" if audio_selection.loop_required else ""
                    add_render_log(
                        f"Аудио: {audio_selection.start_time:.1f}s–{audio_selection.end_time:.1f}s"
                        f"  score={audio_selection.score:.3f}{loop_note}"
                    )
                except Exception as e:
                    add_render_log(f"AudioEngine failed: {e} — from start", 'WARNING')
                    audio_selection = None

            # Clip selection
            set_render_progress(50, "Выбор видеофрагментов")
            preset_id = st.session_state.get('selected_preset_id', 'manual')

            if preset_id == 'easy_mode':
                from src.easy_mode import EasyClipSelector
                add_render_log("Easy mode: случайный подбор фрагментов")
                easy_seed = (st.session_state.get('easy_seed_value', 42)
                             if st.session_state.get('easy_use_fixed_seed', False) else None)
                all_video_paths = [s['path'] for s in sources]
                all_segments = EasyClipSelector.select_random_clips(
                    video_paths=all_video_paths,
                    target_duration=st.session_state.target_duration,
                    min_clip_duration=st.session_state.get('easy_min_clip', 2.0),
                    max_clip_duration=st.session_state.get('easy_max_clip', 5.0),
                    seed=easy_seed,
                    avoid_repeating_same_video=st.session_state.get('easy_avoid_repeat', True),
                    shuffle_clips=st.session_state.get('easy_shuffle', True)
                )
                if not all_segments:
                    add_render_log("Easy: не удалось выбрать фрагменты — видео слишком короткие?", 'ERROR')
                    st.session_state.rendering = False
                    return
            else:
                use_new_system = preset_id != 'manual' and preset_id in [
                    'drone_nature_cinematic', 'drone_landscape_clean', 'fast_action_sport',
                    'urban_city_rhythm', 'social_media_punchy', 'business_promo_clean',
                    'travel_story', 'real_estate_property_tour', 'event_highlights',
                    'calm_minimal_documentary', 'intelligent_beauty_mix',
                    'sport_dynamic_cut', 'sport_highlight_impact',
                ]
                if use_new_system:
                    add_render_log(f"Стратегический выбор клипов: {preset_id}")
                    _target_total = st.session_state.target_duration
                    _budget_per_source = (_target_total / len(sources)) * 1.5

                    # Collect scored CandidateClips from all sources.
                    # TimelineBuilder needs the full scored pool to pick best intro/outro.
                    _all_candidates = []
                    for source in sources:
                        try:
                            _cands = SegmentSelector.select_segments_with_strategy(
                                source_path=source['path'],
                                ranges=source['ranges'],
                                target_duration=_budget_per_source,
                                preset_id=preset_id,
                                project_dir=Path(pm.project_path) if hasattr(pm, 'project_path') else None,
                                use_clip_selection=True,
                                return_candidates=True,
                            )
                            _all_candidates.extend(_cands)
                            add_render_log(
                                f"  {source['name']}: {len(_cands)} кандидатов"
                            )
                        except Exception as e:
                            add_render_log(f"  {source['name']}: ошибка выбора — {e}", 'WARNING')

                    all_segments = []
                    _timeline_audio_start = audio_selection.start_time if audio_selection else 0.0
                    _timeline_fade_in  = st.session_state.get('fade_in', 2.0)
                    _timeline_fade_out = st.session_state.get('fade_out', 2.0)
                    _between_transition = st.session_state.get('transition_type', 'none')
                    _between_transition_dur = st.session_state.get('transition_duration', 0.5)

                    if _all_candidates:
                        try:
                            from src.timeline import TimelineBuilder
                            from src.timeline.intro_outro_rules import get_profile as _get_tl_profile
                            _tl_result = TimelineBuilder.build(
                                candidates=_all_candidates,
                                target_duration=_target_total,
                                preset_id=preset_id,
                                music_path=music_path,
                                music_start_time=_timeline_audio_start,
                            )
                            all_segments = _tl_result.segments
                            add_render_log(f"[Intro] {_tl_result.intro_log}")
                            add_render_log(f"[Outro] {_tl_result.outro_log}")
                            add_render_log(f"[Audio] {_tl_result.audio_log}")
                            add_render_log(f"[Нарратив] {_tl_result.narrative}")

                            # Use audio boundaries from TimelineBuilder when available
                            if music_path and _tl_result.audio_start != _timeline_audio_start:
                                _timeline_audio_start = _tl_result.audio_start
                                add_render_log(
                                    f"Аудио старт скорректирован: {_timeline_audio_start:.2f}s"
                                )

                            # Get profile fade durations
                            _tl_profile = _get_tl_profile(preset_id)
                            _timeline_fade_in  = _tl_profile.audio_intro.fade_in_sec
                            _timeline_fade_out = _tl_profile.audio_outro.fade_out_sec

                        except Exception as _tl_err:
                            add_render_log(
                                f"TimelineBuilder: {_tl_err} — fallback к прямому выбору",
                                'WARNING'
                            )
                            all_segments = []

                    # If TimelineBuilder failed or returned nothing, fall back to
                    # per-source direct selection (original path, no candidate mode).
                    if not all_segments:
                        add_render_log("Запасной путь: прямой выбор по источникам")
                        _fallback_segs = []
                        for source in sources:
                            try:
                                segs = SegmentSelector.select_segments_with_strategy(
                                    source_path=source['path'],
                                    ranges=source['ranges'],
                                    target_duration=_budget_per_source,
                                    preset_id=preset_id,
                                    project_dir=Path(pm.project_path) if hasattr(pm, 'project_path') else None,
                                    use_clip_selection=True,
                                )
                                _src_dur = sum(s.duration for s in segs)
                                _fallback_segs.extend(segs)
                                add_render_log(
                                    f"  {source['name']}: {len(segs)} фрагментов "
                                    f"({_src_dur:.1f}s)"
                                )
                            except Exception as e:
                                add_render_log(f"  {source['name']}: ошибка — {e}", 'WARNING')
                        all_segments = _fallback_segs

                    # Trigger multi-source fallback if still below 90% of target
                    _collected = sum(s.duration for s in all_segments)
                    if _collected < _target_total * 0.90:
                        add_render_log(
                            f"⚠ Собрано {_collected:.1f}s < цель {_target_total:.1f}s "
                            f"— переключаемся на мультисорс-метод",
                            'WARNING'
                        )
                        all_segments = []  # trigger fallback below
                else:
                    add_render_log("Legacy music sync интеграция")
                    all_segments = None

                if not all_segments:
                    all_segments = integrate_music_sync_with_selection(
                        music_path=music_path,
                        sources=sources,
                        target_duration=st.session_state.target_duration,
                        dynamic_level=st.session_state.dynamic_level,
                        music_settings=music_sync_settings,
                        seed=42
                    )

            if not all_segments:
                add_render_log("Нет сегментов для сборки", 'ERROR')
                st.session_state.rendering = False
                st.session_state.generation_status = 'failed'
                return

            # ── Duration sanity check ─────────────────────────────────────────
            _target = st.session_state.target_duration
            _planned_video = sum(s.duration for s in all_segments)
            _level = 'SUCCESS' if _planned_video >= _target * 0.90 else 'WARNING'
            add_render_log(
                f"Выбрано фрагментов: {len(all_segments)}  |  "
                f"суммарная длина: {_planned_video:.1f}s  |  цель: {_target:.1f}s",
                _level
            )
            if _planned_video < _target * 0.50:
                add_render_log(
                    f"❌ Критически мало материала ({_planned_video:.1f}s) — "
                    f"добавьте видео или уменьшите длительность.",
                    'ERROR'
                )
                st.session_state.rendering = False
                st.session_state.generation_status = 'failed'
                return
            if _planned_video < _target * 0.90:
                add_render_log(
                    f"⚠ Собрано {_planned_video:.1f}s < {_target:.1f}s — "
                    f"итоговое видео будет короче выбранной длительности.",
                    'WARNING'
                )
            set_render_progress(65, "Настройка эффектов")

            # Effects
            transitions = TransitionSettings(
                enabled=st.session_state.get('transition_type', 'cut') != 'cut',
                type=TransitionType(st.session_state.get('transition_type', 'cut')),
                duration=st.session_state.get('transition_duration', 0.3)
            )
            speed_mode_str = st.session_state.get('speed_mode', 'none')
            speed_effects = SpeedEffectSettings(
                enabled=speed_mode_str != 'none',
                mode=SpeedMode(speed_mode_str) if speed_mode_str != 'none' else SpeedMode.NONE,
                slow_motion_factor=st.session_state.get('slow_motion_factor', 0.75),
                speed_up_factor=st.session_state.get('speed_up_factor', 1.25)
            )
            color_style_str = st.session_state.get('color_style', 'none')
            color = ColorSettings(
                enabled=color_style_str != 'none',
                style=ColorStyle(color_style_str) if color_style_str != 'none' else ColorStyle.NONE,
                brightness=st.session_state.get('color_brightness', 0.0),
                contrast=st.session_state.get('color_contrast', 0.0),
                saturation=st.session_state.get('color_saturation', 0.0),
                temperature=st.session_state.get('color_temperature', 0.0)
            )
            effects_config = EffectsConfiguration(
                transitions=transitions, speed_effects=speed_effects, color=color,
                quality_filters=QualityFilterSettings(), music_sync=music_sync_settings,
                overlays=OverlaySettings()
            )

            fx_parts = []
            if transitions.enabled and transitions.type != TransitionType.CUT:
                fx_parts.append(f"переходы:{transitions.type.value}")
            if speed_effects.enabled:
                fx_parts.append(f"скорость:{speed_effects.mode.value}")
            if color.enabled:
                fx_parts.append(f"цвет:{color.style.value}")
            if music_sync_settings.enabled:
                fx_parts.append(f"sync:{music_sync_settings.mode.value}")
            add_render_log("Эффекты: " + (", ".join(fx_parts) if fx_parts else "нет"))

            # Output config
            _out_fmt = st.session_state.get('output_format', 'horizontal')
            output_config = OutputConfig(
                target_duration=st.session_state.target_duration,
                format=_out_fmt,
                dynamic_level=st.session_state.dynamic_level
            )
            out_w, out_h = output_config.resolution
            output_path = pm.output_dir / st.session_state.output_name
            # Use TimelineBuilder-computed fade values when available, else preset/selection
            _fade_in  = locals().get('_timeline_fade_in',
                         getattr(audio_selection, 'fade_in',  st.session_state.get('fade_in',  2.0)))
            _fade_out = locals().get('_timeline_fade_out',
                         getattr(audio_selection, 'fade_out', st.session_state.get('fade_out', 2.0)))
            _music_start = locals().get('_timeline_audio_start',
                            getattr(audio_selection, 'start_time', 0.0) if audio_selection else 0.0)

            # Determine vertical mode (only meaningful for portrait output)
            _is_vertical_out = out_h > out_w
            _vertical_mode = (
                st.session_state.get('vertical_mode', 'center_crop')
                if _is_vertical_out else 'center_crop'
            )

            # Log output format details
            _fmt_label = {'horizontal': '16:9', 'vertical': '9:16', 'square': '1:1'}.get(_out_fmt, _out_fmt)
            add_render_log(f"Формат вывода: {_fmt_label}  {out_w}×{out_h}")
            if _is_vertical_out:
                _mode_labels = {
                    'center_crop': 'Center Crop',
                    'fit_blur':    'Fit + Blur Background',
                    'left_crop':   'Left Crop',
                    'right_crop':  'Right Crop',
                }
                add_render_log(f"Режим вертикального кадра: {_mode_labels.get(_vertical_mode, _vertical_mode)}")

            set_render_progress(80, "Сборка FFmpeg")
            add_render_log(f"Запуск FFmpeg: {output_path.name}")

            # between-clip transition: prefer TimelineBuilder/session values
            _bt = locals().get('_between_transition', st.session_state.get('transition_type', 'none'))
            _bt_dur = locals().get('_between_transition_dur',
                                   st.session_state.get('transition_duration', 0.5))

            FFmpegRenderer.render(
                segments=all_segments,
                output_config=output_config,
                output_path=str(output_path),
                music_path=music_path,
                music_fade_in=_fade_in,
                music_fade_out=_fade_out,
                music_start_time=_music_start,
                effects_config=effects_config,
                progress_callback=lambda msg, level='INFO': add_render_log(msg, level),
                vertical_mode=_vertical_mode,
                between_clip_transition=_bt,
                between_clip_transition_dur=_bt_dur,
            )

            st.session_state.output_path = str(output_path)
            set_render_progress(100, "Готово")
            add_render_log(f"Видео сохранено: {output_path}", 'SUCCESS')

            pm.clear_temp(keep_proxy=False)

            if st.session_state.get('generation_status') == 'rendering':
                st.session_state.generation_status = 'completed'

    except Exception as e:
        add_render_log(f"Ошибка сборки: {e}", 'ERROR')
        add_render_log(_traceback.format_exc(), 'ERROR')
        if st.session_state.get('generation_status') == 'rendering':
            st.session_state.generation_status = 'failed'

    finally:
        st.session_state.rendering = False
        st.rerun()


def reset_project():
    """Reset project state"""
    st.session_state.project_created = False
    st.session_state.project_manager = None
    st.session_state.project_name = ""
    st.session_state.video_files = []
    st.session_state.ranges = {}
    st.session_state.music_path = None
    st.session_state.rendering = False
    st.session_state.output_path = None


if __name__ == "__main__":
    main()
