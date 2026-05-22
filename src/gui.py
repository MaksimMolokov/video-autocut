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
    /* ── Compact layout: fits main UI in one screen ─────────────────────── */
    .block-container {
        padding-top: 0.5rem !important;
        padding-bottom: 0.25rem !important;
        max-width: 1440px;
    }
    /* Tighten header */
    header[data-testid="stHeader"] { height: 2rem !important; }
    h1 { padding-bottom: 0.1rem !important; font-size: 1.4rem !important; }
    h2 { padding-top: 0.1rem !important; padding-bottom: 0.1rem !important; font-size: 1.2rem !important; }
    h3 { padding-top: 0.1rem !important; padding-bottom: 0.1rem !important; font-size: 1.0rem !important; }
    h4 { font-size: 0.95rem !important; margin: 0.1rem 0 !important; }
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] { padding: 4px 10px; }
    /* Expanders */
    div[data-testid="stExpander"] { margin-top: 0.15rem !important; margin-bottom: 0.15rem !important; }
    div[data-testid="stExpander"] > div[data-testid="stExpanderDetails"] { padding-top: 0.25rem !important; }
    /* Column gaps */
    div[data-testid="stVerticalBlock"] > div { gap: 0.25rem !important; }
    div[data-testid="column"] > div[data-testid="stVerticalBlock"] > div { gap: 0.2rem !important; }
    /* Inputs */
    .stTextInput > div > div { padding: 0.2rem 0.6rem !important; }
    .stSelectbox > div { min-height: 0 !important; }
    /* Radio: compact */
    .stRadio label { font-size: 0.85rem !important; padding: 0.1rem 0 !important; }
    .stRadio > div { gap: 0.1rem !important; }
    /* Buttons */
    .stButton > button { padding: 0.2rem 0.6rem !important; font-size: 0.85rem !important; }
    /* Style-grid button: selected style highlighted */
    button[data-style-selected="true"] { border: 2px solid #0d6efd !important; }
    /* Element spacing */
    .element-container { margin-bottom: 0.15rem !important; }
    p { margin-bottom: 0.2rem !important; }
    hr { margin: 0.3rem 0 !important; }
    .stAlert { padding: 0.3rem 0.7rem !important; font-size: 0.85rem !important; }
    /* Caption */
    .stCaption { font-size: 0.78rem !important; }
    /* Log panel: fixed max height */
    .render-log-panel { max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 0.78rem; }
    /* Compact metric */
    [data-testid="stMetric"] { padding: 0 !important; }
    [data-testid="stMetric"] label { font-size: 0.8rem !important; }
    [data-testid="stMetric"] [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
    /* Progress bar tighter */
    .stProgress { margin: 0.2rem 0 !important; }
    /* Info/success/warning boxes */
    [data-testid="stAlert"] { padding: 0.3rem 0.7rem !important; }
    /* Compact multiselect */
    .stMultiSelect { margin-bottom: 0 !important; }
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

# Draft / variants / preview state
if 'draft_segments' not in st.session_state:
    st.session_state.draft_segments = []       # segments proposed before render
if 'approved_segments' not in st.session_state:
    st.session_state.approved_segments = None  # approved after draft review
if 'draft_deleted' not in st.session_state:
    st.session_state.draft_deleted = set()     # indices deleted by user in draft
if 'draft_pinned' not in st.session_state:
    st.session_state.draft_pinned = set()      # indices pinned as must-use for next variant
if 'draft_blocked' not in st.session_state:
    st.session_state.draft_blocked = set()     # (path, start, end) tuples blocked from selection
if 'variant_seed_offset' not in st.session_state:
    st.session_state.variant_seed_offset = 0   # 0=A 1=B 2=C 3=D
if 'preview_path' not in st.session_state:
    st.session_state.preview_path = None       # path to fast-preview file
if '_draft_mode' not in st.session_state:
    st.session_state._draft_mode = False
if '_fast_preview_mode' not in st.session_state:
    st.session_state._fast_preview_mode = False

# Platform / branding / export state
if 'platform_preset' not in st.session_state:
    st.session_state.platform_preset = None   # None | 'reels' | 'tiktok' | 'shorts' | 'youtube'
if 'watermark_enabled' not in st.session_state:
    st.session_state.watermark_enabled = False
if 'watermark_text' not in st.session_state:
    st.session_state.watermark_text = ''
if 'watermark_position' not in st.session_state:
    st.session_state.watermark_position = 'bottom_right'
if 'watermark_opacity' not in st.session_state:
    st.session_state.watermark_opacity = 0.7
if 'stabilization_enabled' not in st.session_state:
    st.session_state.stabilization_enabled = False
if 'thumbnail_path' not in st.session_state:
    st.session_state.thumbnail_path = None
if 'favorites' not in st.session_state:
    st.session_state.favorites = {}   # {video_path: {'must_use': [(start,end)], 'forbidden': [(start,end)]}}
if 'preprocess_blurry' not in st.session_state:
    st.session_state.preprocess_blurry = False
if 'preprocess_duplicates' not in st.session_state:
    st.session_state.preprocess_duplicates = False

# Draft timeline view state
if 'draft_view_mode' not in st.session_state:
    st.session_state.draft_view_mode = 'table'
if 'draft_filter' not in st.session_state:
    st.session_state.draft_filter = 'all'
if 'draft_sort' not in st.session_state:
    st.session_state.draft_sort = 'order'
if 'draft_preview_idx' not in st.session_state:
    st.session_state.draft_preview_idx = None
if 'draft_thumbs' not in st.session_state:
    st.session_state.draft_thumbs = {}

# Multi-variant preview state
if 'preview_count' not in st.session_state:
    st.session_state.preview_count = 1          # 1 or 4
if 'variants' not in st.session_state:
    st.session_state.variants = {}              # {letter: variant_dict}
if 'active_variant_id' not in st.session_state:
    st.session_state.active_variant_id = None   # letter of selected variant
if 'building_variant_idx' not in st.session_state:
    st.session_state.building_variant_idx = 0
if '_multi_variant_build' not in st.session_state:
    st.session_state._multi_variant_build = False
if 'previews_stale' not in st.session_state:
    st.session_state.previews_stale = False
if 'manual_format' not in st.session_state:
    st.session_state.manual_format = None       # saved manual format when platform locks it
if 'manual_duration' not in st.session_state:
    st.session_state.manual_duration = None     # saved manual duration when platform locks it
if 'editing_variant_id' not in st.session_state:
    st.session_state.editing_variant_id = None  # which variant is being edited in draft view

# Sound notification state
if 'sound_enabled' not in st.session_state:
    st.session_state.sound_enabled = False      # off by default (browser autoplay policy)
if '_sound_played_key' not in st.session_state:
    st.session_state._sound_played_key = None   # prevents replaying on each rerun

# Variant memory: tracks openings/endings used across A/B/C/D builds
if '_variant_memory' not in st.session_state:
    st.session_state._variant_memory = None     # VariantMemory | None; reset each 4-preview job


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


def _play_completion_sound(event_key: str):
    """
    Play a short 880 Hz chime once per event_key via HTML audio data-URI.
    No-op when sound is disabled or already played for this key.
    The event_key should encode the specific task (e.g. 'preview_A', 'final_42').
    """
    if not st.session_state.get('sound_enabled', False):
        return
    if st.session_state.get('_sound_played_key') == event_key:
        return   # already played for this completion event
    st.session_state._sound_played_key = event_key

    import struct, math, base64
    sr, freq, dur_s = 22050, 880, 0.25
    n = int(sr * dur_s)
    frames = []
    for i in range(n):
        t = i / sr
        env = min(1.0, t * 30.0) * math.exp(-t * 12.0)
        s = int(0.28 * env * 32767 * math.sin(2 * math.pi * freq * t))
        frames.append(struct.pack('<h', max(-32768, min(32767, s))))
    pcm = b''.join(frames)
    ds = len(pcm)
    hdr = struct.pack('<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + ds, b'WAVE', b'fmt ', 16,
        1, 1, sr, sr * 2, 2, 16, b'data', ds)
    b64 = base64.b64encode(hdr + pcm).decode()

    import streamlit.components.v1 as _cmp
    _cmp.html(
        f'<audio autoplay style="display:none">'
        f'<source src="data:audio/wav;base64,{b64}" type="audio/wav">'
        f'</audio>',
        height=0,
    )


def _show_compact_style_grid(presets: list, current_pid: str) -> None:
    """
    2-column grid of style buttons. Clicking a button selects the style.
    Shows emoji+name as label, full description in tooltip (help=).
    Active style is visually indicated with a ▶ prefix.
    """
    n_cols = 2
    for i in range(0, len(presets), n_cols):
        row_presets = presets[i:i + n_cols]
        row_cols = st.columns(n_cols)
        for col, p in zip(row_cols, row_presets):
            pid   = p['preset_id']
            is_sel = pid == current_pid
            label  = f"{'▶ ' if is_sel else ''}{p['emoji']} {p['name']}"
            tip    = (p.get('description', '') or '')[:160]
            with col:
                if st.button(
                    label,
                    key=f"style_grid_{pid}",
                    use_container_width=True,
                    help=tip or None,
                    type="primary" if is_sel else "secondary",
                ):
                    if not st.session_state.get('project_name'):
                        st.toast("⚠️ Введите название проекта", icon="⚠️")
                    elif not st.session_state.get('selected_videos'):
                        st.toast("⚠️ Выберите хотя бы одно видео", icon="⚠️")
                    else:
                        st.session_state.selected_preset_id = pid
                        st.session_state.edit_mode = "preset"
                        if pid == "manual":
                            st.session_state.edit_mode = "manual"
                            st.session_state.page = "manual_settings"
                            st.session_state.project_created = True
                        else:
                            save_draft_state()
                        st.rerun()


def _show_compact_progress(variant_label: str = ""):
    """Single-line compact progress bar shown during rendering."""
    progress  = st.session_state.get('render_progress', 0)
    stage     = st.session_state.get('render_stage', 'Подготовка...')
    pct_label = f"**{progress}%**"
    if variant_label:
        pct_label = f"{variant_label} · {pct_label}"
    st.progress(max(0.01, progress / 100))
    st.caption(f"{pct_label} — {stage}")


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
        if st.session_state.get('generation_status') == 'draft_ready':
            show_draft_timeline()
        else:
            show_auto_render_screen()
    elif st.session_state.page == 'manual_settings':
        show_editor_screen()  # This has manual settings
    elif st.session_state.project_created:
        # Fallback for old flow compatibility
        show_editor_screen()
    else:
        # Default to welcome
        show_welcome_screen()


_VARIANT_LABELS = {0: 'A', 1: 'B', 2: 'C', 3: 'D'}


# ──────────────────────────────────────────────────────────────────────────────
# Draft timeline helpers
# ──────────────────────────────────────────────────────────────────────────────

def _dt_selection_reason(seg, idx: int, pinned: set) -> str:
    """Return a short human-readable reason why this fragment was selected."""
    if seg.is_must_use:
        return "Обязательный"
    role = getattr(seg, 'role', 'body')
    if role == 'intro':
        return "Открывающий план"
    if role == 'outro':
        return "Завершающий план"
    if idx in pinned:
        return "Закреплён вами"
    feat = getattr(seg, '_features', None)
    if feat is not None:
        face_cx = getattr(feat, 'face_center_x', 0.5)
        if abs(face_cx - 0.5) > 0.12:
            return "Есть лицо"
        interest = getattr(feat, 'interest_score', 0.0)
        if interest >= 0.70:
            return "Высокий интерес"
        motion = getattr(feat, 'motion_score', 0.0)
        if motion >= 0.55:
            return "Хорошее движение"
        sharp = getattr(feat, 'sharpness_score', 0.0)
        if sharp >= 0.70:
            return "Высокая резкость"
        color = getattr(feat, 'color_saturation_score', 0.0)
        if color >= 0.65:
            return "Насыщенный цвет"
    fscore = getattr(seg, '_final_score', None)
    if fscore is not None and fscore >= 0.65:
        return "Высокий рейтинг"
    return ""


def _dt_quality_score(seg) -> float:
    """Return a 0–1 quality score for display purposes."""
    fscore = getattr(seg, '_final_score', None)
    if fscore is not None:
        return float(fscore)
    feat = getattr(seg, '_features', None)
    if feat is not None:
        return float(getattr(feat, 'technical_quality_score', 0.5))
    return 0.5


def _dt_interest_score(seg) -> float:
    feat = getattr(seg, '_features', None)
    if feat is not None:
        return float(getattr(feat, 'interest_score', 0.0))
    return 0.0


def _dt_status_badge(i: int, deleted: set, pinned: set, must_use: bool) -> str:
    if i in deleted:
        return "🔴 Исключён"
    if must_use:
        return "🔵 Обязательный"
    if i in pinned:
        return "📌 Закреплён"
    return "✅ Выбран"


def _dt_ensure_thumbs(segments: list):
    """
    Generate thumbnails for all segments on first call (cached after that).
    Stores result in st.session_state.draft_thumbs dict.
    """
    from src.thumbnail_service import ThumbnailService

    thumbs = st.session_state.get('draft_thumbs', {})
    missing = [
        (seg.source_path, seg.start, seg.end)
        for seg in segments
        if (seg.source_path, seg.start, seg.end) not in thumbs
    ]
    if not missing:
        return

    with st.spinner(f"Генерация превью для {len(missing)} фрагментов…"):
        new_thumbs = ThumbnailService.get_or_create_batch(missing, max_workers=4)
    thumbs.update(new_thumbs)
    st.session_state.draft_thumbs = thumbs


def _dt_thumb(seg, thumbs: dict) -> str | None:
    return thumbs.get((seg.source_path, seg.start, seg.end))


def _dt_apply_filter(segments, deleted, pinned, filter_key: str, target_dur: float):
    """Return list of (original_index, seg) after applying filter."""
    result = []
    for i, seg in enumerate(segments):
        is_del = i in deleted
        is_pin = i in pinned
        dur = seg.duration
        score = _dt_quality_score(seg)

        if filter_key == 'selected' and is_del:
            continue
        if filter_key == 'excluded' and not is_del:
            continue
        if filter_key == 'pinned' and not is_pin:
            continue
        if filter_key == 'required' and not seg.is_must_use:
            continue
        if filter_key == 'short' and dur >= 3.0:
            continue
        if filter_key == 'long' and dur < 6.0:
            continue
        if filter_key == 'high_score' and score < 0.6:
            continue
        if filter_key == 'low_score' and score >= 0.4:
            continue
        result.append((i, seg))
    return result


def _dt_apply_sort(indexed_segs, sort_key: str):
    """Sort (index, seg) list in-place or return new sorted list."""
    if sort_key == 'order':
        return sorted(indexed_segs, key=lambda x: x[0])
    if sort_key == 'file':
        return sorted(indexed_segs, key=lambda x: Path(x[1].source_path).name)
    if sort_key == 'dur_asc':
        return sorted(indexed_segs, key=lambda x: x[1].duration)
    if sort_key == 'dur_desc':
        return sorted(indexed_segs, key=lambda x: -x[1].duration)
    if sort_key == 'score':
        return sorted(indexed_segs, key=lambda x: -_dt_quality_score(x[1]))
    if sort_key == 'interest':
        return sorted(indexed_segs, key=lambda x: -_dt_interest_score(x[1]))
    if sort_key == 'status':
        def _status_key(item):
            i, seg = item
            if seg.is_must_use:
                return 0
            if i in st.session_state.get('draft_pinned', set()):
                return 1
            if i in st.session_state.get('draft_deleted', set()):
                return 3
            return 2
        return sorted(indexed_segs, key=_status_key)
    return indexed_segs


# ──────────────────────────────────────────────────────────────────────────────
# Fragment preview / carousel
# ──────────────────────────────────────────────────────────────────────────────

def _show_fragment_preview():
    """
    Full-screen carousel preview for a single fragment.
    Activated when st.session_state.draft_preview_idx is not None.
    """
    segments = st.session_state.draft_segments
    deleted  = st.session_state.get('draft_deleted', set())
    pinned   = st.session_state.get('draft_pinned', set())
    thumbs   = st.session_state.get('draft_thumbs', {})

    idx = st.session_state.draft_preview_idx
    if idx is None or not segments:
        st.session_state.draft_preview_idx = None
        st.rerun()
        return

    idx = max(0, min(idx, len(segments) - 1))
    seg = segments[idx]
    thumb_path = _dt_thumb(seg, thumbs)

    # ── Header ────────────────────────────────────────────────────────────────
    close_col, title_col = st.columns([1, 9])
    with close_col:
        if st.button("✕ Закрыть", key="preview_close", use_container_width=True):
            st.session_state.draft_preview_idx = None
            st.rerun()
    with title_col:
        role = getattr(seg, 'role', 'body')
        role_icons = {'intro': '🎬', 'outro': '🏁', 'body': '▶'}
        st.markdown(
            f"#### {role_icons.get(role,'▶')} Фрагмент #{idx+1} из {len(segments)}"
            f"  —  {Path(seg.source_path).name}"
        )

    st.divider()

    # ── Main content: image + info ─────────────────────────────────────────────
    img_col, info_col = st.columns([3, 2], gap="large")

    with img_col:
        if thumb_path and Path(thumb_path).exists():
            st.image(thumb_path, use_container_width=True)
        else:
            st.markdown(
                '<div style="background:#1c1f26;border-radius:8px;height:200px;'
                'display:flex;align-items:center;justify-content:center;'
                'color:#6e7681;font-size:0.9rem">Нет превью</div>',
                unsafe_allow_html=True,
            )

    with info_col:
        # Status badge
        badge = _dt_status_badge(idx, deleted, pinned, seg.is_must_use)
        st.markdown(f"**Статус:** {badge}")

        # Basic info
        st.markdown(f"**Файл:** `{Path(seg.source_path).name}`")
        st.markdown(f"**Таймкод:** `{seg.start:.2f}s — {seg.end:.2f}s`")
        st.markdown(f"**Длительность:** `{seg.duration:.2f}с`")
        st.markdown(f"**Роль:** {role_icons.get(role,'▶')} {role}")

        # Scores
        q = _dt_quality_score(seg)
        n = _dt_interest_score(seg)
        st.markdown(f"**Качество:** {'█' * int(q*10)}{'░' * (10-int(q*10))} `{q:.2f}`")
        if n > 0:
            st.markdown(f"**Интерес:** {'█' * int(n*10)}{'░' * (10-int(n*10))} `{n:.2f}`")

        # Selection reason
        reason = _dt_selection_reason(seg, idx, pinned)
        if reason:
            st.info(f"💡 {reason}")

        # Feature details
        feat = getattr(seg, '_features', None)
        if feat is not None:
            with st.expander("Детали анализа", expanded=False):
                st.caption(f"Резкость: {feat.sharpness_score:.2f}")
                st.caption(f"Яркость: {feat.brightness_score:.2f}")
                st.caption(f"Движение: {feat.motion_score:.2f}")
                st.caption(f"Стабильность: {feat.camera_stability_score:.2f}")
                st.caption(f"Насыщенность: {feat.color_saturation_score:.2f}")

        st.write("")
        # ── Actions ───────────────────────────────────────────────────────────
        is_del = idx in deleted
        is_pin = idx in pinned

        ac1, ac2 = st.columns(2)
        with ac1:
            if is_del:
                if st.button("✅ Вернуть", key="pv_keep", use_container_width=True):
                    st.session_state.draft_deleted = deleted - {idx}
                    st.rerun()
            else:
                if st.button("🔴 Исключить", key="pv_del", use_container_width=True):
                    st.session_state.draft_deleted = deleted | {idx}
                    st.rerun()
        with ac2:
            if is_pin:
                if st.button("📌 Открепить", key="pv_unpin", use_container_width=True):
                    st.session_state.draft_pinned = pinned - {idx}
                    st.rerun()
            else:
                if st.button("📌 Закрепить", key="pv_pin", use_container_width=True,
                             type="primary"):
                    st.session_state.draft_pinned = pinned | {idx}
                    st.rerun()

    st.divider()

    # ── Navigation ────────────────────────────────────────────────────────────
    nav_prev, nav_info, nav_next = st.columns([2, 3, 2])
    with nav_prev:
        if st.button("← Предыдущий", key="pv_prev",
                     use_container_width=True, disabled=idx == 0):
            st.session_state.draft_preview_idx = idx - 1
            st.rerun()
    with nav_info:
        dots = []
        for j in range(len(segments)):
            if j == idx:
                dots.append("●")
            elif j in deleted:
                dots.append("○")
            elif j in pinned:
                dots.append("◆")
            else:
                dots.append("·")
        # Show window of 15 dots centered on current
        half = 7
        start_d = max(0, idx - half)
        end_d = min(len(segments), start_d + 15)
        st.caption(" ".join(dots[start_d:end_d]))
    with nav_next:
        if st.button("Следующий →", key="pv_next",
                     use_container_width=True, disabled=idx == len(segments)-1):
            st.session_state.draft_preview_idx = idx + 1
            st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Main draft timeline
# ──────────────────────────────────────────────────────────────────────────────

def show_draft_timeline():
    """
    Visual draft timeline review — thumbnails, cards/table, filters, sort,
    carousel preview, bulk actions, rebuild preview.
    """
    # ── Preview mode takes full screen ────────────────────────────────────────
    if st.session_state.get('draft_preview_idx') is not None:
        _show_fragment_preview()
        return

    segments = st.session_state.draft_segments
    if not segments:
        st.warning("Нет предложенных клипов. Вернитесь назад и проверьте настройки.")
        return

    # ── Generate thumbnails (cached after first call) ────────────────────────
    _dt_ensure_thumbs(segments)
    thumbs = st.session_state.get('draft_thumbs', {})

    deleted = st.session_state.get('draft_deleted', set())
    pinned  = st.session_state.get('draft_pinned', set())

    # ── Header ────────────────────────────────────────────────────────────────
    hc1, hc2 = st.columns([1, 9])
    with hc1:
        if st.button("← Назад", key="back_from_draft"):
            st.session_state.page = 'welcome'
            st.session_state.generation_status = None
            st.session_state.draft_segments = []
            st.session_state.draft_deleted = set()
            st.session_state.draft_preview_idx = None
            st.rerun()
    with hc2:
        variant_letter = _VARIANT_LABELS.get(st.session_state.variant_seed_offset, 'A')
        st.markdown(f"#### 🎬 Черновой таймлайн  —  Вариант {variant_letter}")

    # ── Summary metrics ───────────────────────────────────────────────────────
    target_dur  = st.session_state.get('target_duration', 0)
    active_segs = [s for i, s in enumerate(segments) if i not in deleted]
    active_dur  = sum(s.duration for s in active_segs)
    pct         = (active_dur / target_dur * 100) if target_dur else 0

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Фрагментов", f"{len(active_segs)} / {len(segments)}")
    with m2:
        st.metric("Длина", f"{active_dur:.1f}с")
    with m3:
        cov_icon = "✅" if pct >= 90 else "⚠️"
        st.metric("Покрытие", f"{cov_icon} {pct:.0f}%")
    with m4:
        n_pinned = len(pinned & set(range(len(segments))))
        st.metric("Закреплено", n_pinned)

    st.divider()

    # ── Toolbar row ───────────────────────────────────────────────────────────
    t1, t2, t3 = st.columns([3, 3, 3])

    with t1:
        # View mode toggle
        vm = st.session_state.get('draft_view_mode', 'table')
        vc1, vc2 = st.columns(2)
        with vc1:
            if st.button(
                "☰ Таблица",
                key="vm_table",
                use_container_width=True,
                type="primary" if vm == 'table' else "secondary",
            ):
                st.session_state.draft_view_mode = 'table'
                st.rerun()
        with vc2:
            if st.button(
                "⊞ Карточки",
                key="vm_grid",
                use_container_width=True,
                type="primary" if vm == 'grid' else "secondary",
            ):
                st.session_state.draft_view_mode = 'grid'
                st.rerun()

    with t2:
        # Filter
        filter_labels = {
            'all':        f"Все ({len(segments)})",
            'selected':   f"Выбраны ({len(active_segs)})",
            'pinned':     f"Закреплены ({n_pinned})",
            'excluded':   f"Исключены ({len(deleted)})",
            'required':   "Обязательные",
            'short':      "Короткие (<3с)",
            'long':       "Длинные (≥6с)",
            'high_score': "Высокий score",
            'low_score':  "Низкий score",
        }
        cur_filter = st.session_state.get('draft_filter', 'all')
        new_filter = st.selectbox(
            "Фильтр",
            options=list(filter_labels.keys()),
            format_func=lambda k: filter_labels[k],
            index=list(filter_labels.keys()).index(cur_filter),
            key="draft_filter_sel",
            label_visibility="collapsed",
        )
        if new_filter != cur_filter:
            st.session_state.draft_filter = new_filter
            st.rerun()

    with t3:
        # Sort
        sort_labels = {
            'order':    "Порядок в ролике",
            'file':     "По файлу",
            'dur_asc':  "Длина: по возрастанию",
            'dur_desc': "Длина: по убыванию",
            'score':    "Score качества",
            'interest': "Score интереса",
            'status':   "По статусу",
        }
        cur_sort = st.session_state.get('draft_sort', 'order')
        new_sort = st.selectbox(
            "Сортировка",
            options=list(sort_labels.keys()),
            format_func=lambda k: sort_labels[k],
            index=list(sort_labels.keys()).index(cur_sort),
            key="draft_sort_sel",
            label_visibility="collapsed",
        )
        if new_sort != cur_sort:
            st.session_state.draft_sort = new_sort
            st.rerun()

    # ── Bulk actions row ──────────────────────────────────────────────────────
    with st.expander("⚡ Массовые действия", expanded=False):
        ba1, ba2, ba3, ba4 = st.columns(4)
        with ba1:
            if st.button("✅ Вернуть все", key="bulk_keep", use_container_width=True):
                st.session_state.draft_deleted = set()
                st.rerun()
        with ba2:
            if st.button("🔴 Исключить все", key="bulk_excl", use_container_width=True):
                st.session_state.draft_deleted = set(range(len(segments)))
                st.rerun()
        with ba3:
            if st.button("📌 Закрепить видимые", key="bulk_pin", use_container_width=True):
                visible_idxs = {i for i, _ in _dt_apply_filter(
                    segments, deleted, pinned,
                    st.session_state.get('draft_filter', 'all'), target_dur
                )}
                st.session_state.draft_pinned = pinned | visible_idxs
                st.rerun()
        with ba4:
            if st.button("🔄 Сбросить изменения", key="bulk_reset", use_container_width=True):
                st.session_state.draft_deleted = set()
                st.session_state.draft_pinned = set()
                st.session_state.draft_blocked = set()
                st.rerun()

    st.write("")

    # ── Apply filter + sort ───────────────────────────────────────────────────
    cur_filter = st.session_state.get('draft_filter', 'all')
    cur_sort   = st.session_state.get('draft_sort', 'order')
    view_mode  = st.session_state.get('draft_view_mode', 'table')
    blocked    = st.session_state.get('draft_blocked', set())

    display_items = _dt_apply_filter(segments, deleted, pinned, cur_filter, target_dur)
    display_items = _dt_apply_sort(display_items, cur_sort)

    if not display_items:
        st.info("Нет фрагментов, соответствующих фильтру.")
    elif view_mode == 'table':
        _dt_render_table(display_items, segments, deleted, pinned, blocked, thumbs, target_dur)
    else:
        _dt_render_grid(display_items, segments, deleted, pinned, blocked, thumbs, target_dur)

    st.divider()

    # ── Bottom action bar ─────────────────────────────────────────────────────
    can_proceed = active_dur >= target_dur * 0.50

    b1, b2, b3, b4, b5 = st.columns(5)

    with b1:
        next_offset = (st.session_state.variant_seed_offset + 1) % 4
        next_letter = _VARIANT_LABELS[next_offset]
        if st.button(
            f"🔀 Вариант {next_letter}",
            use_container_width=True,
            help="Другой вариант фрагментов (другой seed)",
        ):
            _pinned_segs = [s for idx2, s in enumerate(segments) if idx2 in pinned]
            st.session_state.variant_seed_offset = next_offset
            st.session_state.draft_deleted = set()
            st.session_state.draft_segments = []
            st.session_state.draft_pinned = set()
            st.session_state.draft_preview_idx = None
            st.session_state.draft_thumbs = {}
            st.session_state.approved_segments = None
            st.session_state.draft_pinned_carry = _pinned_segs
            st.session_state._draft_mode = True
            st.session_state.generation_status = 'rendering'
            st.rerun()

    with b2:
        if st.button(
            "🔄 Пересобрать preview",
            use_container_width=True,
            disabled=not can_proceed,
            help="Быстрый preview с учётом исключённых и закреплённых фрагментов",
        ):
            final_segs = [s for i2, s in enumerate(segments) if i2 not in deleted]
            st.session_state.approved_segments = final_segs
            st.session_state._fast_preview_mode = True
            st.session_state._draft_mode = False
            st.session_state.generation_status = 'rendering'
            st.rerun()

    with b3:
        if st.button(
            "⚡ Быстрый preview",
            use_container_width=True,
            type="secondary",
            disabled=not can_proceed,
            help="480p рендер для проверки ритма (~10× быстрее финала)",
        ):
            final_segs = [s for i2, s in enumerate(segments) if i2 not in deleted]
            st.session_state.approved_segments = final_segs
            st.session_state._fast_preview_mode = True
            st.session_state._draft_mode = False
            st.session_state.generation_status = 'rendering'
            st.rerun()

    with b4:
        if st.button(
            "🎬 Финальный рендер",
            use_container_width=True,
            type="primary",
            disabled=not can_proceed,
            help="Полное качество",
        ):
            final_segs = [s for i2, s in enumerate(segments) if i2 not in deleted]
            st.session_state.approved_segments = final_segs
            st.session_state._fast_preview_mode = False
            st.session_state._draft_mode = False
            st.session_state.generation_status = 'rendering'
            st.rerun()

    with b5:
        if st.button("↩ Настройки", use_container_width=True):
            st.session_state.page = 'welcome'
            st.session_state.generation_status = None
            st.session_state.draft_segments = []
            st.session_state.draft_deleted = set()
            st.session_state.draft_preview_idx = None
            st.rerun()

    if not can_proceed:
        st.warning(
            f"⚠️ Активных фрагментов слишком мало ({active_dur:.1f}с). "
            f"Нужно ≥ 50% цели ({target_dur * 0.5:.0f}с). "
            f"Попробуйте другой вариант или добавьте видео."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Table view renderer
# ──────────────────────────────────────────────────────────────────────────────

def _dt_render_table(
    display_items, segments, deleted, pinned, blocked, thumbs, target_dur
):
    """Render the fragment list in table mode with thumbnail column."""
    # Column headers
    h0, h1, h2, h3, h4, h5, h6, h7 = st.columns(
        [0.5, 1.2, 2.2, 2.0, 1.0, 1.5, 1.8, 1.5]
    )
    with h0: st.caption("")
    with h1: st.caption("Превью")
    with h2: st.caption("Файл")
    with h3: st.caption("Таймкод / Длина")
    with h4: st.caption("Роль")
    with h5: st.caption("Score")
    with h6: st.caption("Статус / Причина")
    with h7: st.caption("Действия")
    st.divider()

    for orig_idx, seg in display_items:
        is_del  = orig_idx in deleted
        is_pin  = orig_idx in pinned
        role    = getattr(seg, 'role', 'body')
        role_icons = {'intro': '🎬', 'outro': '🏁', 'body': '▶'}
        thumb   = _dt_thumb(seg, thumbs)
        qs      = _dt_quality_score(seg)
        ns      = _dt_interest_score(seg)
        reason  = _dt_selection_reason(seg, orig_idx, pinned)
        badge   = _dt_status_badge(orig_idx, deleted, pinned, seg.is_must_use)
        _kb     = f"tbl_{orig_idx}"

        # Row opacity via CSS hack using container width
        if is_del:
            row_style = "opacity:0.4;"
        elif is_pin:
            row_style = "border-left:3px solid #0d6efd;"
        else:
            row_style = ""

        col0, col1, col2, col3, col4, col5, col6, col7 = st.columns(
            [0.5, 1.2, 2.2, 2.0, 1.0, 1.5, 1.8, 1.5]
        )

        with col0:
            keep = st.checkbox(
                "", value=not is_del,
                key=f"{_kb}_chk",
                label_visibility="collapsed",
            )
            if keep == is_del:  # state changed
                new_del = set(deleted)
                if keep:
                    new_del.discard(orig_idx)
                else:
                    new_del.add(orig_idx)
                st.session_state.draft_deleted = new_del
                st.rerun()

        with col1:
            if thumb and Path(thumb).exists():
                st.image(thumb, use_container_width=True)
                if st.button(
                    "🔍", key=f"{_kb}_expand",
                    help="Открыть крупно",
                ):
                    st.session_state.draft_preview_idx = orig_idx
                    st.rerun()
            else:
                st.caption("Нет\nпревью")

        with col2:
            fname = Path(seg.source_path).name
            # Truncate long filenames
            label = fname if len(fname) <= 22 else fname[:19] + "…"
            st.caption(f"**{label}**")
            st.caption(f"`#{orig_idx+1}`")

        with col3:
            st.caption(f"{seg.start:.1f}s — {seg.end:.1f}s")
            st.caption(f"{seg.duration:.1f}с")

        with col4:
            st.caption(f"{role_icons.get(role,'▶')} {role}")

        with col5:
            q_bar = "█" * int(qs * 5) + "░" * (5 - int(qs * 5))
            st.caption(f"Q {q_bar} {qs:.2f}")
            if ns > 0:
                n_bar = "█" * int(ns * 5) + "░" * (5 - int(ns * 5))
                st.caption(f"I {n_bar} {ns:.2f}")

        with col6:
            st.caption(badge)
            if reason:
                st.caption(f"💡 {reason}")

        with col7:
            a1, a2 = st.columns(2)
            with a1:
                if is_pin:
                    if st.button("📌", key=f"{_kb}_unpin", help="Открепить",
                                 use_container_width=True):
                        st.session_state.draft_pinned = pinned - {orig_idx}
                        st.rerun()
                else:
                    if st.button("☐", key=f"{_kb}_pin", help="Закрепить",
                                 use_container_width=True):
                        st.session_state.draft_pinned = pinned | {orig_idx}
                        st.rerun()
            with a2:
                _rkey = (seg.source_path, round(seg.start, 2), round(seg.end, 2))
                is_blocked = _rkey in blocked
                blk_lbl = "🚫" if is_blocked else "⬜"
                if st.button(blk_lbl, key=f"{_kb}_blk", help="Заблокировать диапазон",
                             use_container_width=True):
                    new_blk = set(blocked)
                    new_del = set(deleted)
                    if is_blocked:
                        new_blk.discard(_rkey)
                    else:
                        new_blk.add(_rkey)
                        new_del.add(orig_idx)
                    st.session_state.draft_blocked = new_blk
                    st.session_state.draft_deleted = new_del
                    st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Grid / card view renderer
# ──────────────────────────────────────────────────────────────────────────────

def _dt_render_grid(
    display_items, segments, deleted, pinned, blocked, thumbs, target_dur
):
    """Render fragment cards in a 3-column grid."""
    N_COLS = 3
    rows = [display_items[i:i+N_COLS] for i in range(0, len(display_items), N_COLS)]

    for row in rows:
        cols = st.columns(N_COLS)
        for col_idx, (orig_idx, seg) in enumerate(row):
            with cols[col_idx]:
                is_del = orig_idx in deleted
                is_pin = orig_idx in pinned
                thumb  = _dt_thumb(seg, thumbs)
                qs     = _dt_quality_score(seg)
                reason = _dt_selection_reason(seg, orig_idx, pinned)
                role   = getattr(seg, 'role', 'body')
                role_icons = {'intro': '🎬', 'outro': '🏁', 'body': '▶'}
                _kb    = f"grd_{orig_idx}"

                # Card border styling via CSS container
                border_color = "#0d6efd" if is_pin else ("#555" if is_del else "#30363d")
                opacity = "0.45" if is_del else "1.0"
                st.markdown(
                    f'<div style="border:2px solid {border_color};border-radius:8px;'
                    f'padding:6px;margin-bottom:4px;opacity:{opacity}">',
                    unsafe_allow_html=True,
                )

                # Thumbnail
                if thumb and Path(thumb).exists():
                    st.image(thumb, use_container_width=True)
                else:
                    st.markdown(
                        '<div style="background:#1c1f26;border-radius:4px;height:100px;'
                        'display:flex;align-items:center;justify-content:center;'
                        'color:#6e7681;font-size:0.75rem">Нет превью</div>',
                        unsafe_allow_html=True,
                    )

                # Info
                fname = Path(seg.source_path).name
                label = fname if len(fname) <= 24 else fname[:21] + "…"
                st.caption(
                    f"**#{orig_idx+1}** {role_icons.get(role,'▶')}  `{label}`"
                )
                st.caption(
                    f"{seg.start:.1f}–{seg.end:.1f}s · **{seg.duration:.1f}с** · "
                    f"Q:{qs:.2f}"
                )
                if reason:
                    st.caption(f"💡 {reason}")

                # Status badge
                badge = _dt_status_badge(orig_idx, deleted, pinned, seg.is_must_use)
                st.caption(badge)

                # Close div
                st.markdown("</div>", unsafe_allow_html=True)

                # Action buttons below the card
                ga, gb, gc = st.columns(3)
                with ga:
                    keep_lbl = "✅ Вернуть" if is_del else "🔴 Искл."
                    if st.button(keep_lbl, key=f"{_kb}_tog",
                                 use_container_width=True):
                        new_del = set(deleted)
                        if is_del:
                            new_del.discard(orig_idx)
                        else:
                            new_del.add(orig_idx)
                        st.session_state.draft_deleted = new_del
                        st.rerun()
                with gb:
                    pin_lbl = "📌" if is_pin else "☐ Pin"
                    if st.button(pin_lbl, key=f"{_kb}_pin",
                                 use_container_width=True):
                        st.session_state.draft_pinned = (
                            pinned - {orig_idx} if is_pin else pinned | {orig_idx}
                        )
                        st.rerun()
                with gc:
                    if st.button("🔍", key=f"{_kb}_open",
                                 help="Открыть крупно",
                                 use_container_width=True):
                        st.session_state.draft_preview_idx = orig_idx
                        st.rerun()


def _get_project_dir_from_videos(selected_videos: list) -> str:
    """Derive project dir from selected video paths (common parent folder)."""
    if not selected_videos:
        return ''
    return str(Path(selected_videos[0]).parent)


def show_quality_analysis_section(selected_videos: list):
    """
    Quality analysis section: scene detection + technical metrics + thumbnail cache.
    Shows cache status when already analyzed, progress bar during analysis,
    and a fragment viewer after completion.
    """
    if not selected_videos:
        return

    project_dir = _get_project_dir_from_videos(selected_videos)
    if not project_dir:
        return

    try:
        from src.storage.analysis_db import AnalysisDB
        from src.preprocessing.pipeline import analyze_project
        db = AnalysisDB(project_dir)
        stats = db.get_stats()
    except Exception:
        return

    has_analysis = stats['analyzed_files'] > 0

    if has_analysis:
        import datetime
        last = stats.get('last_analyzed', '')
        time_ago = ''
        if last:
            try:
                dt = datetime.datetime.fromisoformat(last)
                delta = datetime.datetime.utcnow() - dt
                h = int(delta.total_seconds() // 3600)
                m = int((delta.total_seconds() % 3600) // 60)
                time_ago = f'{h} ч {m} мин назад' if h else f'{m} мин назад'
            except Exception:
                pass
        st.success(
            f"✅ Материалы проанализированы · "
            f"{stats['good_fragments']} удачных фрагментов · "
            f"{stats['analyzed_files']}/{len(selected_videos)} файлов · "
            f"{time_ago}"
        )
        col_view, col_reanalyze, _ = st.columns([2, 2, 3])
        with col_view:
            if st.button('📋 Посмотреть фрагменты', key='qa_view_btn', use_container_width=True):
                st.session_state['show_fragment_viewer'] = True
        with col_reanalyze:
            if st.button('🔄 Обновить анализ', key='qa_reanalyze_btn', use_container_width=True):
                st.session_state['qa_force_reanalyze'] = True
                st.rerun()

        if st.session_state.get('show_fragment_viewer'):
            _show_fragment_viewer(project_dir, db)
    else:
        col_analyze, col_skip, _ = st.columns([2, 2, 3])
        with col_analyze:
            do_analyze = st.button(
                '🔍 Анализировать материалы',
                key='qa_analyze_btn',
                type='primary',
                use_container_width=True,
            )
        with col_skip:
            st.caption('или пропустите — система сработает без анализа')

        if do_analyze or st.session_state.get('qa_force_reanalyze'):
            st.session_state.pop('qa_force_reanalyze', None)
            progress_bar = st.progress(0.0)
            status_text = st.empty()
            frag_count = st.empty()

            def _on_progress(filename: str, done: int, total: int):
                progress_bar.progress(done / total)
                status_text.text(f'Обработка: {filename}  ({done}/{total})')

            try:
                n = analyze_project(
                    project_dir,
                    progress_callback=_on_progress,
                    force_reanalyze=st.session_state.get('qa_force_reanalyze', False),
                )
                progress_bar.empty()
                status_text.empty()
                st.rerun()
            except Exception as e:
                progress_bar.empty()
                status_text.empty()
                st.error(f'Ошибка анализа: {e}')


def _show_fragment_viewer(project_dir: str, db=None):
    """Thumbnail grid of analyzed fragments with approval controls."""
    try:
        from src.storage.analysis_db import AnalysisDB
        from src.preprocessing.clip_library import FragmentLibrary
        if db is None:
            db = AnalysisDB(project_dir)
        lib = FragmentLibrary(db)
    except Exception as e:
        st.warning(f'Не удалось загрузить фрагменты: {e}')
        return

    min_q = st.slider('Минимальное качество', 0.0, 1.0, 0.55, 0.05, key='fv_min_quality')
    sort_opt = st.selectbox(
        'Сортировка', ['quality_score', 'cinematic_score', 'action_score',
                        'premium_score', 'travel_score'],
        key='fv_sort',
    )
    fragments = lib.get_fragments_for_ui(min_quality=min_q, sort_by=sort_opt, limit=60)

    if not fragments:
        st.info('Нет фрагментов с указанным минимальным качеством.')
        return

    st.caption(f'Показано {len(fragments)} фрагментов')
    cols = st.columns(4)
    for i, f in enumerate(fragments):
        with cols[i % 4]:
            if f.thumbnail_path and Path(f.thumbnail_path).exists():
                st.image(f.thumbnail_path)
            else:
                st.markdown('_(превью нет)_')
            st.caption(
                f'★ {f.quality_score:.2f}  |  {f.filename}\n'
                f'{f.start_s:.1f}–{f.end_s:.1f}s  ({f.duration_s:.1f}s)'
            )
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button('✓', key=f'approve_{f.id}', help='Одобрить'):
                    lib.mark_approved(f.id, True)
                    st.rerun()
            with b2:
                if st.button('✗', key=f'disable_{f.id}', help='Отключить'):
                    lib.mark_disabled(f.id)
                    st.rerun()
            with b3:
                is_priority = bool(f.user_priority)
                if st.button('★' if not is_priority else '☆',
                             key=f'priority_{f.id}', help='Приоритет'):
                    lib.mark_priority(f.id, not is_priority)
                    st.rerun()


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

        col_d, col_e, _ = st.columns(3)
        with col_d:
            blr = st.checkbox(
                "🌫 Размытые кадры",
                value=st.session_state.get('preprocess_blurry', False),
                key="pp_blur",
                help="Убирает не в фокусные кадры (низкая резкость по Лапласиану)",
            )
            st.session_state.preprocess_blurry = blr
        with col_e:
            dup = st.checkbox(
                "📋 Дублирующиеся кадры",
                value=st.session_state.get('preprocess_duplicates', False),
                key="pp_dup",
                help="Убирает дублирующиеся последовательности (высокая корреляция гистограмм)",
            )
            st.session_state.preprocess_duplicates = dup

        btn_col, clear_col = st.columns([3, 1])

        with btn_col:
            if st.button(
                "▶ Запустить предобработку",
                key="run_preprocess_btn",
                use_container_width=True,
                type="primary",
                disabled=not selected_videos,
            ):
                if not (cam or pau or txt or blr or dup):
                    st.warning("Выберите хотя бы один тип фильтрации.")
                else:
                    options = PreprocessOptions(
                        detect_camera_moves=cam,
                        detect_pauses=pau,
                        detect_text=txt,
                        detect_blurry=blr,
                        detect_duplicates=dup,
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


# ── Platform presets ──────────────────────────────────────────────────────────
# 'custom' means no locks; all other entries lock format and duration.
_PLATFORM_PRESETS: dict = {
    'custom': {
        'label': 'Custom / Без платформы',
        'icon': '⚙️',
        'locks_format': False,
        'locks_duration': False,
        'format': None,
        'duration_seconds': None,
        'recommended_resolution': None,
        'desc': 'Ручная настройка формата и длительности',
    },
    'reels': {
        'label': 'Instagram Reels',
        'icon': '📱',
        'locks_format': True,
        'locks_duration': True,
        'format': 'vertical_9_16',
        'duration_seconds': 30,
        'recommended_resolution': '1080x1920',
        'desc': 'Вертикальный 9:16 · 30 сек',
    },
    'tiktok': {
        'label': 'TikTok',
        'icon': '🎵',
        'locks_format': True,
        'locks_duration': True,
        'format': 'vertical_9_16',
        'duration_seconds': 30,
        'recommended_resolution': '1080x1920',
        'desc': 'Вертикальный 9:16 · 30 сек',
    },
    'shorts': {
        'label': 'YouTube Shorts',
        'icon': '▶',
        'locks_format': True,
        'locks_duration': True,
        'format': 'vertical_9_16',
        'duration_seconds': 30,
        'recommended_resolution': '1080x1920',
        'desc': 'Вертикальный 9:16 · до 60 сек',
    },
    'youtube': {
        'label': 'YouTube',
        'icon': '🖥',
        'locks_format': True,
        'locks_duration': True,
        'format': 'horizontal_16_9',
        'duration_seconds': 60,
        'recommended_resolution': '1920x1080',
        'desc': 'Горизонтальный 16:9 · 60 сек',
    },
    'stories': {
        'label': 'Stories',
        'icon': '📖',
        'locks_format': True,
        'locks_duration': True,
        'format': 'vertical_9_16',
        'duration_seconds': 15,
        'recommended_resolution': '1080x1920',
        'desc': 'Вертикальный 9:16 · 15 сек',
    },
    'website_hero': {
        'label': 'Website hero video',
        'icon': '🌐',
        'locks_format': True,
        'locks_duration': True,
        'format': 'horizontal_16_9',
        'duration_seconds': 10,
        'recommended_resolution': '1920x1080',
        'desc': 'Горизонтальный 16:9 · 10 сек',
    },
}

_FMT_LABELS = {
    'vertical_9_16': '9:16 Vertical',
    'horizontal_16_9': '16:9 Horizontal',
    'square_1_1': '1:1 Square',
    'original': 'Оригинал',
}


def _normalize_platform_settings():
    """
    Single source of truth: resolve format and duration from platform preset.
    Called before every render to prevent platform/format contradictions.
    Returns (format_str, duration_secs, warnings_list).
    """
    platform = st.session_state.get('platform_preset', 'custom') or 'custom'
    preset = _PLATFORM_PRESETS.get(platform, _PLATFORM_PRESETS['custom'])
    warnings = []

    _fmt_new_to_old = {
        'vertical_9_16': 'vertical',
        'horizontal_16_9': 'horizontal',
        'square_1_1': 'square',
        'original': 'horizontal',
    }

    if preset['locks_format']:
        resolved_fmt = preset['format']
        stored_fmt = st.session_state.get('selected_output_format')
        if stored_fmt and stored_fmt != resolved_fmt:
            warnings.append(
                f"Формат изменён на {resolved_fmt!r} согласно платформе {preset['label']}"
            )
        st.session_state.selected_output_format = resolved_fmt
    else:
        resolved_fmt = st.session_state.get('selected_output_format', 'horizontal_16_9')

    # Sync old-style 'output_format' key used by render_video()
    st.session_state.output_format = _fmt_new_to_old.get(resolved_fmt, 'horizontal')

    if preset['locks_duration']:
        resolved_dur = float(preset['duration_seconds'])
        stored_dur = st.session_state.get('target_duration')
        if stored_dur and abs(stored_dur - resolved_dur) > 0.5:
            warnings.append(
                f"Длительность изменена на {resolved_dur:.0f}с согласно платформе {preset['label']}"
            )
        st.session_state.target_duration = resolved_dur
    else:
        resolved_dur = st.session_state.get('target_duration') or 0.0

    return resolved_fmt, resolved_dur, warnings


def apply_platform_preset(platform_key: str):
    """Switch to a platform preset: lock/unlock format and duration accordingly."""
    if platform_key not in _PLATFORM_PRESETS:
        platform_key = 'custom'

    prev_platform = st.session_state.get('platform_preset', 'custom') or 'custom'
    prev_preset = _PLATFORM_PRESETS.get(prev_platform, _PLATFORM_PRESETS['custom'])

    # Save manual values before locking (so we can restore when switching back to custom)
    if not prev_preset['locks_format']:
        st.session_state.manual_format = st.session_state.get('selected_output_format')
    if not prev_preset['locks_duration']:
        st.session_state.manual_duration = st.session_state.get('target_duration')

    st.session_state.platform_preset = platform_key
    preset = _PLATFORM_PRESETS[platform_key]

    if preset['locks_format']:
        st.session_state.selected_output_format = preset['format']
    else:
        # Restore last manual format if switching back to custom
        saved = st.session_state.get('manual_format')
        if saved:
            st.session_state.selected_output_format = saved

    if preset['locks_duration']:
        st.session_state.target_duration = float(preset['duration_seconds'])
    else:
        saved = st.session_state.get('manual_duration')
        if saved:
            st.session_state.target_duration = saved

    # Mark existing previews as stale if settings changed
    if (preset.get('format') != _PLATFORM_PRESETS[prev_platform].get('format') or
            preset.get('duration_seconds') != _PLATFORM_PRESETS[prev_platform].get('duration_seconds')):
        if st.session_state.get('variants') or st.session_state.get('preview_path'):
            st.session_state.previews_stale = True

    save_draft_state()


def show_platform_section():
    """
    Compact platform selector row.
    When a platform is selected, format and duration are locked and shown read-only.
    """
    cur = st.session_state.get('platform_preset', 'custom') or 'custom'
    preset = _PLATFORM_PRESETS.get(cur, _PLATFORM_PRESETS['custom'])

    platform_options = list(_PLATFORM_PRESETS.keys())
    platform_labels = {k: f"{v['icon']} {v['label']}" for k, v in _PLATFORM_PRESETS.items()}

    try:
        cur_idx = platform_options.index(cur)
    except ValueError:
        cur_idx = 0

    new_platform = st.selectbox(
        "Платформа",
        options=platform_options,
        index=cur_idx,
        format_func=lambda k: platform_labels[k],
        key="platform_selectbox",
        label_visibility="collapsed",
    )

    if new_platform != cur:
        apply_platform_preset(new_platform)
        st.rerun()

    if cur != 'custom':
        st.caption(
            f"🔒 Формат и длительность заданы платформой **{preset['label']}**. "
            "Выберите «Custom», чтобы настроить вручную."
        )


def show_branding_section():
    """
    Watermark / text overlay settings.
    Shown in advanced settings below the welcome form.
    """
    with st.expander("🏷 Брендинг / Watermark", expanded=False):
        st.caption("Добавить текст или логотип поверх готового видео")

        enabled = st.checkbox(
            "Включить watermark",
            value=st.session_state.watermark_enabled,
            key="wm_enabled_chk",
        )
        st.session_state.watermark_enabled = enabled

        if enabled:
            wm_text = st.text_input(
                "Текст (например @аккаунт, название канала)",
                value=st.session_state.watermark_text,
                key="wm_text_input",
                placeholder="@my_channel",
            )
            st.session_state.watermark_text = wm_text

            wm_pos = st.selectbox(
                "Позиция",
                options=['bottom_right', 'bottom_left', 'top_right', 'top_left', 'center'],
                format_func=lambda x: {
                    'bottom_right': '↘ Правый нижний угол',
                    'bottom_left':  '↙ Левый нижний угол',
                    'top_right':    '↗ Правый верхний угол',
                    'top_left':     '↖ Левый верхний угол',
                    'center':       '⊙ По центру',
                }[x],
                index=['bottom_right','bottom_left','top_right','top_left','center'].index(
                    st.session_state.watermark_position
                ),
                key="wm_pos_sel",
            )
            st.session_state.watermark_position = wm_pos

            wm_opac = st.slider(
                "Прозрачность",
                min_value=0.1, max_value=1.0, step=0.05,
                value=st.session_state.watermark_opacity,
                key="wm_opac_slider",
                format="%.0f%%",
            )
            st.session_state.watermark_opacity = wm_opac


def show_welcome_screen():
    """Compact three-column welcome screen — fits on one screen without scrolling."""

    # ── Compact header row ────────────────────────────────────────────────────
    hdr_a, hdr_b = st.columns([4, 2], gap="small")
    with hdr_a:
        project_name = st.text_input(
            "Название проекта",
            value=st.session_state.get('project_name', ''),
            placeholder="Мой видео проект",
            key="welcome_project_name",
            label_visibility="collapsed",
        )
        if project_name:
            st.session_state.project_name = project_name
            save_draft_state()
        if not project_name:
            st.caption("✏️ Введите название проекта")
    with hdr_b:
        # Mini status line
        n_vid = len(st.session_state.get('selected_videos', []))
        has_aud = bool(st.session_state.get('selected_audio'))
        has_pid = bool(st.session_state.get('selected_preset_id'))
        parts = []
        parts.append(f"{'✅' if n_vid else '○'} {n_vid} видео")
        parts.append(f"{'✅' if has_aud else '○'} аудио")
        parts.append(f"{'✅' if has_pid else '○'} стиль")
        st.caption("  ·  ".join(parts))

    # ── Three-column main layout ───────────────────────────────────────────────
    left_col, mid_col, right_col = st.columns([3, 3, 4], gap="medium")

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

    with mid_col:
        # ── Platform ─────────────────────────────────────────────────────────
        st.write("**📲 Платформа**")
        show_platform_section()

        _cur_platform = st.session_state.get('platform_preset', 'custom') or 'custom'
        _plat_cfg     = _PLATFORM_PRESETS.get(_cur_platform, _PLATFORM_PRESETS['custom'])
        _fmt_locked   = _plat_cfg['locks_format']
        _dur_locked   = _plat_cfg['locks_duration']

        # ── Format ───────────────────────────────────────────────────────────
        st.write("**📐 Формат**")
        if _fmt_locked:
            locked_fmt = _plat_cfg['format']
            st.info(f"🔒 {_FMT_LABELS.get(locked_fmt, locked_fmt)}", icon="🔒")
            st.session_state.selected_output_format = locked_fmt
            sel_fmt = locked_fmt
        else:
            fmt_opts = {
                "horizontal_16_9": "16:9 Horizontal",
                "vertical_9_16": "9:16 Vertical",
                "square_1_1": "1:1 Square",
                "original": "Оригинал",
            }
            _cur_fmt = st.session_state.get('selected_output_format', 'horizontal_16_9')
            _fmt_idx = list(fmt_opts.keys()).index(_cur_fmt) if _cur_fmt in fmt_opts else 0
            sel_fmt = st.radio(
                "Формат",
                options=list(fmt_opts.keys()),
                index=_fmt_idx,
                format_func=lambda x: fmt_opts[x],
                key="output_format_radio",
                label_visibility="collapsed",
                horizontal=True,
            )
            st.session_state.selected_output_format = sel_fmt

        # Vertical mode (compact, only for 9:16)
        if st.session_state.get('selected_output_format') == "vertical_9_16":
            _vert_opts = {
                "center_crop": "✂️ По центру",
                "fit_blur":    "🌫 Вписать+фон",
                "left_crop":   "◀ Лево",
                "right_crop":  "▶ Право",
            }
            sel_vert = st.radio(
                "Вертикальный режим",
                options=list(_vert_opts.keys()),
                format_func=lambda x: _vert_opts[x],
                key="vertical_mode_radio",
                label_visibility="collapsed",
                horizontal=True,
            )
            st.session_state.vertical_mode = sel_vert

        # ── Duration ─────────────────────────────────────────────────────────
        st.write("**⏱ Длительность**")
        if _dur_locked:
            locked_dur = _plat_cfg['duration_seconds']
            dm, ds = int(locked_dur) // 60, int(locked_dur) % 60
            dur_str = f"{dm}м {ds}с" if dm else f"{locked_dur:.0f}с"
            st.info(f"🔒 {dur_str}", icon="🔒")
            st.session_state.target_duration = float(locked_dur)
        else:
            dc = st.columns(4)
            for di, (secs, label) in enumerate([(15, "15с"), (30, "30с"), (60, "1м"), (90, "90с")]):
                with dc[di]:
                    is_sel = st.session_state.get('target_duration') == secs
                    if st.button(label, key=f"dur_{secs}", use_container_width=True,
                                 type="secondary" if is_sel else "primary"):
                        st.session_state.target_duration = secs
                        st.session_state.manual_duration = secs
                        save_draft_state()
                        st.rerun()
            cc1, cc2, cc3 = st.columns([2, 2, 2])
            with cc1:
                cm = st.number_input("м", min_value=0, max_value=60, value=0, key="cdm",
                                     label_visibility="visible")
            with cc2:
                cs = st.number_input("с", min_value=0, max_value=59, value=0, key="cds",
                                     label_visibility="visible")
            with cc3:
                if st.button("Ввести", key="apply_dur", use_container_width=True):
                    total = cm * 60 + cs
                    if total > 0:
                        st.session_state.target_duration = total
                        st.session_state.manual_duration = total
                        save_draft_state()
                        st.rerun()
            if st.session_state.get('target_duration'):
                d = st.session_state.target_duration
                dm2, ds2 = int(d) // 60, int(d) % 60
                st.caption(f"✓ {dm2}м {ds2}с" if dm2 else f"✓ {d:.0f}с")

    with right_col:
        # ── Style selector (compact 2-column grid) ───────────────────────────
        st.write("**🎨 Стиль монтажа**")
        registry    = st.session_state.preset_registry
        presets     = registry.list_presets()
        current_pid = st.session_state.get('selected_preset_id')

        _show_compact_style_grid(
            presets + [{'preset_id': 'manual', 'emoji': '⚙️',
                        'name': 'Manual', 'description': 'Ручные настройки'}],
            current_pid or '',
        )

    # ── Optional expanders (quality analysis, preprocessing, branding) ──────
    if st.session_state.selected_videos:
        show_quality_analysis_section(st.session_state.selected_videos)
        show_preprocess_section(st.session_state.selected_videos)
    show_branding_section()

    # ── Bottom generate bar (only when preset is selected) ────────────────────
    _pid = st.session_state.get('selected_preset_id')
    if _pid and _pid != "manual":

        # Style-specific settings (compact expander)
        if _pid == 'easy_mode':
            with st.expander("⚡ Easy настройки", expanded=False):
                ea1, ea2 = st.columns(2)
                with ea1:
                    st.slider("Мин. клип (с)", 0.5, 10.0, step=0.5, key="easy_min_clip")
                    st.slider("Макс. клип (с)", 1.0, 20.0, step=0.5, key="easy_max_clip")
                with ea2:
                    st.checkbox("Перемешать порядок", key="easy_shuffle")
                    st.checkbox("Без повторов видео", key="easy_avoid_repeat")
                    st.checkbox("Фиксированный seed", key="easy_use_fixed_seed")
                    if st.session_state.get('easy_use_fixed_seed', False):
                        st.number_input("Seed", min_value=0, max_value=999999, step=1,
                                        key="easy_seed_value", label_visibility="collapsed")
        elif _pid in ('sport_dynamic_cut', 'sport_highlight_impact'):
            with st.expander("⚡ Настройки спорта", expanded=False):
                sp1, sp2 = st.columns(2)
                with sp1:
                    st.select_slider("Интенсивность",
                        options=["Лёгкая", "Средняя", "Высокая"],
                        value=st.session_state.get('sport_intensity', 'Средняя'),
                        key="sport_intensity")
                    st.select_slider("Частота склеек",
                        options=["Обычная", "Быстро", "Очень быстро"],
                        value=st.session_state.get('sport_cut_frequency', 'Быстро'),
                        key="sport_cut_frequency")
                with sp2:
                    st.checkbox("Замедление", value=True, key="sport_slow_motion")
                    st.checkbox("Разгон", value=True, key="sport_speed_ramp")
                    st.checkbox("Sync с битом", value=True, key="sport_beat_sync")
        else:
            preset_chk = registry.get_preset(_pid)
            if preset_chk and preset_chk.settings.music_sync.enabled and not st.session_state.selected_audio:
                st.caption("⚠️ Стиль использует синхронизацию с музыкой — добавьте аудио")

        # Advanced + sound in one row of expanders
        adv_col, _ = st.columns([3, 1])
        with adv_col:
            with st.expander("⚙️ Дополнительно", expanded=False):
                adv1, adv2, adv3 = st.columns(3)
                with adv1:
                    stab = st.checkbox(
                        "🎯 Стабилизация видео",
                        value=st.session_state.get('stabilization_enabled', False),
                        key="stab_chk_welcome",
                        help="libvidstab — замедляет рендер",
                    )
                    st.session_state.stabilization_enabled = stab
                with adv2:
                    snd = st.checkbox(
                        "🔔 Звук по завершении",
                        value=st.session_state.get('sound_enabled', False),
                        key="sound_enabled_chk",
                        help="Короткий чайм после завершения генерации",
                    )
                    st.session_state.sound_enabled = snd
                with adv3:
                    try:
                        from src.analysis_cache import get_cache
                        _ac = get_cache()
                        if _ac:
                            _cs = _ac.stats()
                            st.caption(f"Кэш: {_cs['entries']} записей")
                            if st.button("Очистить кэш", key="clear_cache_btn"):
                                _ac.clear_all()
                                st.toast("Кэш очищен")
                                st.rerun()
                    except Exception:
                        pass

        # ── Generate button bar ────────────────────────────────────────────────
        gen_a, gen_b, gen_c = st.columns([2, 3, 1], gap="small")

        with gen_a:
            _pcount = st.radio(
                "Preview-варианты",
                options=[1, 4],
                index=0 if st.session_state.get('preview_count', 1) == 1 else 1,
                format_func=lambda x: "1 вариант" if x == 1 else "4 варианта",
                key="preview_count_radio",
                label_visibility="collapsed",
                horizontal=True,
            )
            st.session_state.preview_count = _pcount

        with gen_b:
            errors = []
            if not st.session_state.project_name:
                errors.append("Название проекта")
            if not st.session_state.selected_videos:
                errors.append("Видеофайлы")
            if not st.session_state.get('target_duration'):
                errors.append("Длительность")

            can_start = len(errors) == 0
            if errors:
                st.caption("⚠️ " + ", ".join(errors))

            _pcount_val = st.session_state.get('preview_count', 1)
            _btn_label = (
                "🎬 Сгенерировать 4 preview"
                if _pcount_val == 4
                else "🎬 Сгенерировать preview"
            )
            if st.button(
                _btn_label,
                type="primary",
                use_container_width=True,
                disabled=not can_start,
                key="gen_btn_welcome",
            ):
                _normalize_platform_settings()
                st.session_state.page = "auto_render"
                st.session_state.generation_status = "starting"
                st.session_state.render_logs = []
                st.session_state.render_progress = 0
                st.session_state.render_stage = ''
                st.session_state.variants = {}
                st.session_state.active_variant_id = None
                st.session_state.previews_stale = False
                st.session_state._sound_played_key = None  # reset for new job
                st.rerun()

        with gen_c:
            if st.button("🏠", key="new_proj_btn_welcome", help="Новый проект",
                         use_container_width=True):
                reset_project()
                st.session_state.page = 'welcome'
                st.session_state.generation_status = None
                st.session_state.selected_videos = []
                st.session_state.selected_audio = None
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


# ── Variant characterisation helpers ──────────────────────────────────────────

def _variant_char_label(segments: list, seed_offset: int) -> str:
    """Return a short human-readable label characterising a variant's feel."""
    if not segments:
        return ""
    features_list = [getattr(s, '_features', None) for s in segments]
    features_list = [f for f in features_list if f is not None]

    if features_list:
        avg_action  = sum(getattr(f, 'action_score',  0.0) for f in features_list) / len(features_list)
        avg_motion  = sum(getattr(f, 'motion_score',  0.0) for f in features_list) / len(features_list)
        avg_quality = sum(getattr(f, 'sharpness_score', 0.0) for f in features_list) / len(features_list)

        if avg_action > 0.65:
            return "Более динамичный"
        if avg_motion > 0.60:
            return "Больше движения"
        if avg_quality > 0.70:
            return "Высокое качество кадра"
        if avg_action < 0.30:
            return "Более спокойный"

    # Fallback: cycle through generic labels by seed
    _fallback = [
        "Акцент на общих планах",
        "Больше крупных планов",
        "Лучше попадает в биты",
        "Больше плавных сцен",
    ]
    return _fallback[seed_offset % len(_fallback)]


def _launch_final_from_variant(variant_id: str):
    """Set approved_segments from the given variant and trigger final render."""
    v = st.session_state.variants.get(variant_id, {})
    segs = v.get('segments')
    if segs:
        st.session_state.approved_segments = list(segs)
        st.session_state.active_variant_id = variant_id
    st.session_state._fast_preview_mode = False
    st.session_state._multi_variant_build = False
    st.session_state.generation_status = 'rendering'
    st.session_state.render_logs = []
    st.session_state.render_progress = 0
    st.session_state.render_stage = ''
    st.rerun()


def _open_fragments_for_variant(variant_id: str):
    """Load a variant's segments into the draft timeline for review/editing."""
    v = st.session_state.variants.get(variant_id, {})
    segs = v.get('segments')
    if segs:
        st.session_state.draft_segments = list(segs)
        st.session_state.draft_deleted = set()
        st.session_state.draft_thumbs = {}
        st.session_state.editing_variant_id = variant_id
        st.session_state.generation_status = 'draft_ready'
        st.rerun()


def _show_single_preview_card():
    """Rich card shown when a single variant preview is ready."""
    v_data = st.session_state.variants.get('A', {})
    preview_path = v_data.get('preview_path') or st.session_state.get('preview_path')
    segs = v_data.get('segments', []) or []
    n_clips = v_data.get('n_clips', len(segs))
    total_dur = v_data.get('duration', sum(getattr(s, 'duration', 0) for s in segs))
    char_label = v_data.get('char_label', '')
    seed = 42 + 0 * 997

    # Stale warning
    if st.session_state.get('previews_stale'):
        st.warning(
            "⚠️ Настройки платформы или длительности изменились. "
            "Preview устарел — рекомендуется пересоздать.",
            icon="⚠️"
        )

    st.markdown("### 🎬 Вариант A — Preview готов")
    pc1, pc2 = st.columns([3, 2], gap="large")

    with pc1:
        if preview_path and Path(preview_path).exists():
            st.video(preview_path)
        else:
            st.info("Preview-файл не найден")

    with pc2:
        pid = st.session_state.get('selected_preset_id', '')
        preset_obj = st.session_state.preset_registry.get_preset(pid) if pid else None
        fmt = st.session_state.get('selected_output_format', 'horizontal_16_9')
        dur = st.session_state.get('target_duration', 0)
        dur_m, dur_s = int(dur) // 60, int(dur) % 60
        dur_str = f"{dur_m}м {dur_s}с" if dur_m else f"{dur:.0f}с"

        st.markdown(f"**Стиль:** {preset_obj.name if preset_obj else pid}")
        st.markdown(f"**Формат:** {_FMT_LABELS.get(fmt, fmt)}")
        st.markdown(f"**Длительность:** {dur_str}")
        st.markdown(f"**Фрагментов:** {n_clips}")
        st.markdown(f"**Seed:** {seed}")
        _single_profile_desc = v_data.get('profile_description', '')
        _single_tl_stats = v_data.get('stats', {})
        if _single_profile_desc:
            st.caption(f"✦ {_single_profile_desc}")
        elif char_label:
            st.caption(f"💡 {char_label}")
        if _single_tl_stats.get('avg_duration'):
            st.caption(f"Средняя длина клипа: {_single_tl_stats['avg_duration']:.1f}с")

        # Platform info
        platform = st.session_state.get('platform_preset', 'custom') or 'custom'
        if platform != 'custom':
            plat_cfg = _PLATFORM_PRESETS[platform]
            st.caption(f"📲 {plat_cfg['label']}")

        st.write("")
        _stale = st.session_state.get('previews_stale', False)

        if st.button(
            "🎬 Сгенерировать финальный монтаж",
            type="primary", use_container_width=True, key="final_from_single_btn",
            disabled=_stale,
        ):
            _launch_final_from_variant('A')

        if st.button("🔄 Сделать другой вариант", use_container_width=True, key="regen_single_btn"):
            st.session_state.generation_status = 'starting'
            st.session_state.variants = {}
            st.session_state.approved_segments = None
            st.session_state.variant_seed_offset = (
                st.session_state.get('variant_seed_offset', 0) + 1
            ) % 4
            st.session_state.render_logs = []
            st.session_state.render_progress = 0
            st.rerun()

        if st.button("📋 Открыть фрагменты", use_container_width=True, key="frags_single_btn"):
            _open_fragments_for_variant('A')

        if preview_path and Path(preview_path).exists():
            if st.button("📂 Открыть папку", use_container_width=True, key="open_preview_folder"):
                os.system(f'open "{Path(preview_path).parent}"')


def _show_variants_ready():
    """Grid of 4 variant cards shown when multi-variant preview is ready."""
    variants = st.session_state.get('variants', {})
    _stale = st.session_state.get('previews_stale', False)

    if _stale:
        st.warning(
            "⚠️ Настройки платформы или длительности изменились. "
            "Preview устарели — рекомендуется пересоздать.",
            icon="⚠️"
        )

    st.markdown("### 🎬 Выберите лучший вариант")
    st.caption("Посмотрите каждый вариант и нажмите «Финал» для выбранного.")

    letters = [k for k in ['A', 'B', 'C', 'D'] if k in variants]
    col_pairs = [letters[i:i+2] for i in range(0, len(letters), 2)]

    for pair in col_pairs:
        grid_cols = st.columns(len(pair), gap="medium")
        for col, letter in zip(grid_cols, pair):
            v = variants[letter]
            with col:
                _show_variant_mini_card(letter, v, _stale)


def _show_variant_mini_card(letter: str, v: dict, stale: bool):
    """Compact card for one variant in the 4-variant grid."""
    preview_path     = v.get('preview_path')
    n_clips          = v.get('n_clips', 0)
    total_dur        = v.get('duration', 0.0)
    char_label       = v.get('char_label', '')
    status           = v.get('status', 'pending')
    variant_name     = v.get('variant_name', f'Вариант {letter}')
    profile_description = v.get('profile_description', '')
    tl_stats         = v.get('stats', {})
    struct_diff      = v.get('struct_diff', {})
    card_warnings    = v.get('warnings', [])

    is_active = st.session_state.get('active_variant_id') == letter
    border_color = "#0d6efd" if is_active else "#30363d"
    st.markdown(
        f'<div style="border:2px solid {border_color};border-radius:8px;padding:8px;margin-bottom:4px">',
        unsafe_allow_html=True,
    )

    # Badge + name
    badge_colors = {
        'ready':    '#198754',
        'error':    '#dc3545',
        'pending':  '#6c757d',
        'building': '#ffc107',
    }
    bc = badge_colors.get(status, '#6c757d')
    st.markdown(
        f'<span style="background:{bc};color:white;padding:2px 8px;border-radius:4px;'
        f'font-size:0.8rem">Вариант {letter}</span>'
        f'<span style="font-size:0.78rem;color:#8b949e;margin-left:6px">'
        f'{variant_name}</span>',
        unsafe_allow_html=True,
    )

    # Video player
    if preview_path and Path(preview_path).exists() and status == 'ready':
        st.video(preview_path)
    else:
        st.markdown(
            '<div style="background:#1c1f26;border-radius:4px;height:120px;'
            'display:flex;align-items:center;justify-content:center;'
            'color:#6e7681;font-size:0.8rem">Нет preview</div>',
            unsafe_allow_html=True,
        )

    # Stats row
    dur_m, dur_s = int(total_dur) // 60, int(total_dur) % 60
    dur_str      = f"{dur_m}м {dur_s}с" if dur_m else f"{total_dur:.0f}с"
    avg_dur      = tl_stats.get('avg_duration', 0.0)
    avg_dur_str  = f"  ·  ср.кл. {avg_dur:.1f}с" if avg_dur else ''
    st.caption(f"⏱ {dur_str}  ·  🎞 {n_clips} фр.{avg_dur_str}")

    if profile_description:
        st.caption(f"✦ {profile_description}")
    elif char_label:
        st.caption(f"💡 {char_label}")

    # Structural diff vs A (for B/C/D)
    if struct_diff and letter != 'A':
        diff_parts = []
        ovl = struct_diff.get('scene_set_overlap_ratio', None)
        if ovl is not None:
            diff_parts.append(f"≠A {(1-ovl)*100:.0f}%")
        same_o = struct_diff.get('same_opening', True)
        same_e = struct_diff.get('same_ending', True)
        if not same_o:
            diff_parts.append("др. вступление")
        if not same_e:
            diff_parts.append("др. концовка")
        dur_d = struct_diff.get('avg_segment_duration_delta', 0.0)
        if dur_d > 0.5:
            diff_parts.append(f"кл. Δ{dur_d:.1f}с")
        if diff_parts:
            st.caption("  ·  ".join(diff_parts))

    # Limited material warning
    if card_warnings:
        st.caption(f"⚠ {card_warnings[0]}")

    # Action buttons
    ba, bb, bc2 = st.columns(3)
    with ba:
        if st.button("✅ Финал", key=f"final_{letter}_btn",
                     use_container_width=True, type="primary",
                     disabled=stale or status != 'ready'):
            _launch_final_from_variant(letter)
    with bb:
        if st.button("📋 Фр-ты", key=f"frags_{letter}_btn",
                     use_container_width=True,
                     disabled=status != 'ready'):
            _open_fragments_for_variant(letter)
    with bc2:
        if st.button("🔄 Ещё", key=f"more_{letter}_btn",
                     use_container_width=True,
                     disabled=status != 'ready',
                     help="Сгенерировать похожий вариант с другим seed"):
            # Rebuild just this slot
            v['status'] = 'pending'
            v['seed_offset'] = (seed_offset + 4) % 8  # shift seed
            st.session_state.building_variant_idx = list('ABCD').index(letter)
            st.session_state.variant_seed_offset = v['seed_offset']
            st.session_state._fast_preview_mode = True
            st.session_state._multi_variant_build = True
            st.session_state.generation_status = 'rendering'
            st.session_state.render_logs = []
            st.session_state.render_progress = 0
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


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
        if status in ('completed', 'failed', 'preview_ready', 'variants_ready'):
            st.write("")
            if st.button("🎬 Пересоздать preview", use_container_width=True, type="primary", key="regen_btn"):
                st.session_state.generation_status = 'starting'
                st.session_state.render_logs = []
                st.session_state.render_progress = 0
                st.session_state.render_stage = ''
                st.session_state.draft_segments = []
                st.session_state.approved_segments = None
                st.session_state.draft_deleted = set()
                st.session_state.variant_seed_offset = 0
                st.session_state.variants = {}
                st.session_state.previews_stale = False
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
                # Apply preset, then normalize platform (platform always wins over preset format)
                if pid and pid != 'manual':
                    apply_preset_to_session(pid)
                _normalize_platform_settings()  # enforce platform locks

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

            # Validate and normalize platform settings before building
            _r_fmt, _r_dur, _plat_warns = _normalize_platform_settings()
            for _w in _plat_warns:
                add_render_log(f"[Platform] {_w}", 'WARNING')

            _pcount = st.session_state.get('preview_count', 1)
            add_render_log(
                f"[Init] Стиль={st.session_state.get('selected_preset_id')}  "
                f"Длительность={_r_dur:.0f}s  Формат={_r_fmt}  "
                f"Preview-вариантов={_pcount}"
            )

            # Set up variant slots
            if _pcount == 4:
                st.session_state.variants = {
                    letter: {
                        'label': f'Вариант {letter}',
                        'seed_offset': idx,
                        'status': 'pending',
                        'preview_path': None,
                        'segments': None,
                        'n_clips': 0,
                        'duration': 0.0,
                        'char_label': '',
                    }
                    for idx, letter in enumerate('ABCD')
                }
                st.session_state.building_variant_idx = 0
                st.session_state.variant_seed_offset = 0
                st.session_state._multi_variant_build = True
                # Reset variant memory so A starts fresh
                st.session_state._variant_memory = None
                add_render_log("[Multi] Генерация 4 вариантов начата")
            else:
                st.session_state.variants = {
                    'A': {
                        'label': 'Вариант A',
                        'seed_offset': 0,
                        'status': 'pending',
                        'preview_path': None,
                        'segments': None,
                        'n_clips': 0,
                        'duration': 0.0,
                        'char_label': '',
                    }
                }
                st.session_state.building_variant_idx = 0
                st.session_state.variant_seed_offset = 0
                st.session_state._multi_variant_build = False

            # Go directly to fast-preview (skip mandatory draft review)
            st.session_state._draft_mode = False
            st.session_state._fast_preview_mode = True
            st.session_state.generation_status = 'rendering'
            st.rerun()

        elif status == 'rendering':
            _vidx = st.session_state.get('building_variant_idx', 0)
            _vtotal = st.session_state.get('preview_count', 1)
            _vletter = _VARIANT_LABELS.get(_vidx, 'A')
            if st.session_state.get('_multi_variant_build') and _vtotal > 1:
                _prog_label = f"Генерация Варианта {_vletter}  ({_vidx + 1}/{_vtotal})"
            else:
                _prog_label = "Генерация preview..."

            progress = st.session_state.get('render_progress', 0)
            stage = st.session_state.get('render_stage', 'Подготовка...')
            prog_bar = st.progress(max(0.01, progress / 100))
            stage_txt = st.empty()
            stage_txt.caption(f"**{_prog_label}** · {progress}% — {stage}")
            render_video()

        elif status == 'variants_ready':
            _play_completion_sound('variants_ready')
            _show_variants_ready()
            with st.expander("📋 Лог генерации", expanded=False):
                show_render_log_block()

        elif status == 'preview_ready':
            _play_completion_sound('preview_ready')
            _show_single_preview_card()
            with st.expander("📋 Лог", expanded=False):
                show_render_log_block()

        elif status == 'completed':
            _play_completion_sound('final_completed')
            st.success("✅ Видео создано успешно!")

            if st.session_state.output_path and Path(st.session_state.output_path).exists():
                output_path = Path(st.session_state.output_path)
                file_size = output_path.stat().st_size / (1024 * 1024)

                _thumb = st.session_state.get('thumbnail_path')
                if _thumb and Path(_thumb).exists():
                    _tc1, _tc2 = st.columns([1, 2])
                    with _tc1:
                        st.image(_thumb, caption="Обложка", use_container_width=True)
                    with _tc2:
                        st.metric("Файл", output_path.name)
                        st.metric("Размер", f"{file_size:.1f} MB")
                        st.code(str(output_path), language=None)
                        fin_c1, fin_c2 = st.columns(2)
                        with fin_c1:
                            if st.button("📂 Папка", use_container_width=True, key="open_folder_btn"):
                                os.system(f'open "{output_path.parent}"')
                        with fin_c2:
                            if st.button("▶ Открыть файл", use_container_width=True, key="open_file_btn"):
                                os.system(f'open "{output_path}"')
                else:
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        st.metric("Файл", output_path.name)
                    with col_m2:
                        st.metric("Размер", f"{file_size:.1f} MB")
                    st.code(str(output_path), language=None)
                    fin_c1b, fin_c2b = st.columns(2)
                    with fin_c1b:
                        if st.button("📂 Папка", use_container_width=True, key="open_folder_btn"):
                            os.system(f'open "{output_path.parent}"')
                    with fin_c2b:
                        if st.button("▶ Открыть файл", use_container_width=True, key="open_file_btn"):
                            os.system(f'open "{output_path}"')

            with st.expander("📋 Лог генерации", expanded=False):
                show_render_log_block()

        elif status == 'failed':
            # Show compact error alert + error log entries
            _err_logs = [e for e in st.session_state.get('render_logs', [])
                         if e.get('level') == 'ERROR']
            if _err_logs:
                _err_summary = _err_logs[-1].get('msg', 'Неизвестная ошибка')
                st.error(f"❌ Ошибка: {_err_summary[:200]}")
            else:
                st.error("❌ Ошибка генерации — откройте лог для деталей")
            with st.expander("📋 Лог ошибок", expanded=True):
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

            # ── Approved segments shortcut (from draft review) ────────────────
            _approved = st.session_state.get('approved_segments')
            if _approved:
                all_segments = _approved
                st.session_state.approved_segments = None  # consume
                add_render_log(
                    f"Используются одобренные клипы из черновика: {len(all_segments)} фрагментов"
                )
                # Jump straight to effects + render
                _skip_selection = True
            else:
                _skip_selection = False

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

            # Clip selection (skipped when approved_segments provided from draft)
            set_render_progress(50, "Выбор видеофрагментов")
            preset_id = st.session_state.get('selected_preset_id', 'manual')

            # ── Variant identity and constraint setup ─────────────────────────
            _is_preview_build    = st.session_state.get('_fast_preview_mode', False)
            _vidx_for_profile    = st.session_state.get('building_variant_idx', 0)
            _vletter_for_profile = _VARIANT_LABELS.get(_vidx_for_profile, 'A')

            # Load constraint + fingerprint infrastructure
            try:
                from src.timeline.variant_constraints import (
                    VariantMemory      as _VM,
                    VariantConstraints as _VC,
                    TimelineFingerprint as _TFP,
                    CandidatePools      as _CP,
                    build_candidate_pools      as _build_pools,
                    build_variant_constraints  as _build_vc,
                    analyze_timeline_difference as _atd,
                    check_minimum_requirements  as _check_min,
                    get_pair_threshold          as _pair_thr,
                    build_similarity_log        as _sim_log_fn,
                    scene_id                    as _sid_fn,
                )
                from src.variant_profiles import (
                    VARIANT_PROFILES as _VP,
                    calculate_timeline_stats    as _calc_tl_stats,
                    get_variant_ui_description  as _get_vui_desc,
                )
                _vc_available = True
            except Exception as _vc_import_err:
                _vc_available = False
                add_render_log(f"VariantConstraints unavailable: {_vc_import_err}", 'WARNING')

            # Load or init VariantMemory (persists across reruns for one 4-preview job)
            if _vc_available:
                _vmem = st.session_state.get('_variant_memory')
                if _vmem is None:
                    _vmem = _VM()
                    st.session_state._variant_memory = _vmem

            # Legacy seed fallback
            _vprofile = (_VP.get(_vletter_for_profile) if _vc_available else None)
            _base_seed = (42 + (_vprofile.seed_offset if _vprofile else
                                _vidx_for_profile * 997))

            if _is_preview_build:
                add_render_log(
                    f"[Вариант {_vletter_for_profile}] seed={_base_seed}"
                )
                add_render_log(
                    f"[VARIANT_DEBUG_INPUT] variant={_vletter_for_profile}"
                    f" idx={_vidx_for_profile}"
                    f" seed={_base_seed}"
                    f" memory_fingerprints={list((_vmem.fingerprints if _vc_available and _vmem else {}).keys())}"
                    f" used_openings={len(_vmem.used_opening_ids) if _vc_available and _vmem else 0}"
                    f" used_endings={len(_vmem.used_ending_ids) if _vc_available and _vmem else 0}"
                )

            # Safe defaults — variables below are only assigned inside the else:
            # branch (use_new_system path). When _skip_selection=True (rebuild from
            # draft) that branch is skipped entirely, causing NameError later in the
            # _fast_preview_mode block that builds _v_data.
            _vconstraints      = None
            _pools             = None
            _timeline_warnings = []

            if _skip_selection:
                pass  # all_segments already set above
            elif preset_id == 'easy_mode':
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
                    'f1',
                ]
                if use_new_system:
                    add_render_log(f"Стратегический выбор клипов: {preset_id}")
                    _target_total = st.session_state.target_duration

                    # Budget: neutral — constraints control duration policy, not budget
                    _budget_per_source = (_target_total / len(sources)) * 1.8

                    # ── Collect scored CandidateClips (FRESH per variant, no sharing) ──
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
                                seed=_base_seed,
                            )
                            _all_candidates.extend(_cands)
                            add_render_log(f"  {source['name']}: {len(_cands)} кандидатов")
                        except Exception as _e_src:
                            add_render_log(f"  {source['name']}: ошибка — {_e_src}", 'WARNING')
                    add_render_log(
                        f"[OBJECT_ID_DEBUG] variant={_vletter_for_profile}"
                        f" total_candidates={len(_all_candidates)}"
                        f" list_id={id(_all_candidates)}"
                        f" first_obj_ids={[id(c) for c in _all_candidates[:3]]}"
                        f" scores={[round(getattr(c,'final_score',0),3) for c in _all_candidates[:5]]}"
                    )

                    # ── Merge preprocessing cache candidates (if available) ───
                    try:
                        _video_dirs = list({str(Path(s['path']).parent) for s in sources})
                        for _vdir in _video_dirs:
                            from src.storage.analysis_db import AnalysisDB as _ADB
                            from src.preprocessing.clip_library import FragmentLibrary as _FL
                            _pdb = _ADB(_vdir)
                            _pstats = _pdb.get_stats()
                            if _pstats['analyzed_files'] > 0:
                                _style_key = f'{preset_id}_score' if preset_id else 'quality_score'
                                _lib = _FL(_pdb)
                                _pp_cands = _lib.get_all_candidates_for_project(
                                    style_score_key=_style_key,
                                    min_quality=0.50,
                                    min_duration=float(getattr(st.session_state, 'min_clip_duration', 1.0) or 1.0),
                                    max_duration=float(getattr(st.session_state, 'max_clip_duration', 10.0) or 10.0),
                                    limit=300,
                                )
                                if _pp_cands:
                                    _all_candidates.extend(_pp_cands)
                                    add_render_log(
                                        f'[Preprocessing] +{len(_pp_cands)} кандидатов из кэша '
                                        f'({_vdir}), всего: {len(_all_candidates)}'
                                    )
                    except Exception as _pp_err:
                        add_render_log(f'[Preprocessing] Кэш недоступен: {_pp_err}', 'DEBUG')

                    # ── Build structural variant constraints ──────────────────
                    _vconstraints = None
                    _pools = None
                    if _vc_available and _all_candidates:
                        try:
                            _pools = _build_pools(_all_candidates)
                            _vconstraints = _build_vc(
                                variant_id=_vletter_for_profile,
                                memory=_vmem,
                                pools=_pools,
                            )
                            add_render_log(
                                f"[Вариант {_vletter_for_profile}]"
                                f" opening={_vconstraints.opening_strategy}"
                                f"  ending={_vconstraints.ending_strategy}"
                                f"  dur={_vconstraints.segment_duration_policy}"
                                f"  pressure={_vconstraints.diversity_pressure}"
                                f"  excl_open={len(_vconstraints.excluded_opening_ids)}"
                                f"  excl_end={len(_vconstraints.excluded_ending_ids)}"
                                f"  soft={len(_vconstraints.soft_excluded_ids)}"
                                f"  hard={len(_vconstraints.hard_excluded_ids)}"
                                f"  material={_pools.material_level}"
                                f"  opens={len(_pools.opening_candidates)}"
                                f"  ends={len(_pools.ending_candidates)}"
                            )
                            add_render_log(
                                f"[VARIANT_OPENING_CHECK] variant={_vletter_for_profile}"
                                f" excluded_opening_ids={sorted(_vconstraints.excluded_opening_ids)}"
                                f" available_opens={len(_pools.opening_ids() - _vconstraints.excluded_opening_ids)}"
                                f" total_opening_pool={len(_pools.opening_candidates)}"
                            )
                            add_render_log(
                                f"[VARIANT_ENDING_CHECK] variant={_vletter_for_profile}"
                                f" excluded_ending_ids={sorted(_vconstraints.excluded_ending_ids)}"
                                f" available_ends={len(_pools.ending_ids() - _vconstraints.excluded_ending_ids)}"
                                f" total_ending_pool={len(_pools.ending_candidates)}"
                            )
                            add_render_log(
                                f"[RANDOM_DEBUG] variant={_vletter_for_profile}"
                                f" base_seed={_base_seed}"
                                f" seed_offset={_vconstraints.seed_offset}"
                                f" effective_seed={_base_seed + _vconstraints.seed_offset}"
                            )
                            if _vconstraints.limited_material_warning:
                                add_render_log(
                                    f"[Вариант {_vletter_for_profile}] ⚠ Мало исходного материала,"
                                    f" отличие между вариантами может быть небольшим.",
                                    'WARNING'
                                )
                        except Exception as _vc_err:
                            add_render_log(f"build_variant_constraints failed: {_vc_err}", 'WARNING')

                    all_segments = []
                    _timeline_audio_start = audio_selection.start_time if audio_selection else 0.0
                    _timeline_fade_in     = st.session_state.get('fade_in', 2.0)
                    _timeline_fade_out    = st.session_state.get('fade_out', 2.0)
                    _between_transition   = st.session_state.get('transition_type', 'none')
                    _between_transition_dur = st.session_state.get('transition_duration', 0.5)
                    _timeline_warnings: list = []

                    if _all_candidates:
                        try:
                            from src.timeline import TimelineBuilder
                            from src.timeline.intro_outro_rules import get_profile as _get_tl_profile

                            # ── Build timeline (with variant constraints + seed) ──
                            _tl_result = TimelineBuilder.build(
                                candidates=_all_candidates,
                                target_duration=_target_total,
                                preset_id=preset_id,
                                music_path=music_path,
                                music_start_time=_timeline_audio_start,
                                variant_constraints=_vconstraints,
                                seed=_base_seed,
                            )
                            all_segments = _tl_result.segments
                            add_render_log(f"[Intro] {_tl_result.intro_log}")
                            add_render_log(f"[Outro] {_tl_result.outro_log}")
                            add_render_log(f"[Audio] {_tl_result.audio_log}")
                            add_render_log(f"[Нарратив] {_tl_result.narrative}")

                            # ── F1: prepend split-screen intro + rapid cuts ───
                            if preset_id == 'f1' and _all_candidates:
                                try:
                                    from src.f1_renderer import F1IntroRenderer
                                    from src.segment_selector import SelectedSegment as _SS
                                    # F1 is always vertical 9:16; read from preset/session
                                    _f1_w, _f1_h = (1080, 1920)
                                    _f1_res_raw = st.session_state.get('resolution', '')
                                    if isinstance(_f1_res_raw, str) and 'x' in _f1_res_raw:
                                        try:
                                            _fw, _fh = _f1_res_raw.split('x')
                                            _f1_w, _f1_h = int(_fw), int(_fh)
                                        except Exception:
                                            pass
                                    _f1_intro_path = str(
                                        pm.output_dir / f"_f1_intro_v{_vidx_for_profile}.mp4"
                                    )
                                    _f1_ok = F1IntroRenderer.render_f1_intro(
                                        candidates=_all_candidates,
                                        output_path=_f1_intro_path,
                                        out_w=_f1_w,
                                        out_h=_f1_h,
                                        seed=_base_seed,
                                        progress_callback=lambda m: add_render_log(m),
                                    )
                                    if _f1_ok and Path(_f1_intro_path).exists():
                                        import subprocess as _sp
                                        _probe_r = _sp.run(
                                            ["ffprobe", "-v", "error",
                                             "-show_entries", "format=duration",
                                             "-of", "default=noprint_wrappers=1:nokey=1",
                                             _f1_intro_path],
                                            capture_output=True, text=True, timeout=10,
                                        )
                                        try:
                                            _f1_dur = float(_probe_r.stdout.strip())
                                        except (ValueError, TypeError):
                                            _f1_dur = 3.0
                                        _f1_seg = _SS(
                                            source_path=_f1_intro_path,
                                            start=0.0,
                                            end=_f1_dur,
                                            duration=_f1_dur,
                                            is_must_use=True,
                                        )
                                        _f1_seg.role = 'intro'
                                        _f1_seg.start_transition = 'clean_cut'
                                        _f1_seg.start_transition_duration = 0.0
                                        _f1_seg._features = None
                                        _f1_seg._final_score = 1.0
                                        _f1_seg._is_f1_intro_block = True
                                        all_segments = [_f1_seg] + list(all_segments)
                                        add_render_log(
                                            f"[F1] Интро инжектировано: "
                                            f"{_f1_dur:.1f}s  "
                                            f"({Path(_f1_intro_path).name})",
                                            'SUCCESS',
                                        )
                                    else:
                                        add_render_log(
                                            "[F1] Интро не сгенерировано — продолжаем без него",
                                            'WARNING',
                                        )
                                except Exception as _f1_err:
                                    add_render_log(
                                        f"[F1] Ошибка генерации интро: {_f1_err}", 'WARNING'
                                    )

                            if music_path and _tl_result.audio_start != _timeline_audio_start:
                                _timeline_audio_start = _tl_result.audio_start
                                add_render_log(
                                    f"Аудио старт скорректирован: {_timeline_audio_start:.2f}s"
                                )

                            _tl_profile = _get_tl_profile(preset_id)
                            _timeline_fade_in  = _tl_profile.audio_intro.fade_in_sec
                            _timeline_fade_out = _tl_profile.audio_outro.fade_out_sec

                            # ── Diversity check + forced regen (max 5 attempts) ──
                            if _vc_available and _is_preview_build and all_segments and _pools:
                                _cur_fp = _TFP.from_segments(
                                    all_segments, _vletter_for_profile, _base_seed,
                                    material_level=_pools.material_level,
                                )
                                add_render_log(
                                    f"[VARIANT_TIMELINE_FINGERPRINT] variant={_vletter_for_profile}"
                                    f" first={_cur_fp.first_scene_id}"
                                    f" last={_cur_fp.last_scene_id}"
                                    f" n_scenes={_cur_fp.segment_count}"
                                    f" scene_ids={_cur_fp.scene_ids}"
                                    f" avg_dur={_cur_fp.avg_segment_duration:.2f}s"
                                )
                                _seg_summary = [
                                    getattr(s, 'source_path', '').split('/')[-1]
                                    + '@' + str(round(getattr(s, 'start', 0), 1))
                                    for s in all_segments
                                ]
                                add_render_log(
                                    f"[VARIANT_TIMELINE] variant={_vletter_for_profile}"
                                    f" segments={_seg_summary}"
                                )
                                _violations = _check_min(_cur_fp, _vmem, _pools)

                                for _regen_i in range(1, 6):
                                    if not _violations:
                                        break
                                    add_render_log(
                                        f"[Diversity] Попытка {_regen_i}: "
                                        + '; '.join(_violations[:3]),
                                        'WARNING',
                                    )
                                    # Escalate exclusions
                                    _cur_open_id = _cur_fp.first_scene_id
                                    _cur_end_id  = _cur_fp.last_scene_id
                                    if _vconstraints:
                                        _vconstraints.excluded_opening_ids.add(_cur_open_id)
                                        _vconstraints.excluded_ending_ids.add(_cur_end_id)
                                        _vconstraints.soft_excluded_ids.update(
                                            set(_cur_fp.scene_ids)
                                        )
                                    _regen_seed = _base_seed + _regen_i * 1337
                                    try:
                                        _tl_regen = TimelineBuilder.build(
                                            candidates=_all_candidates,
                                            target_duration=_target_total,
                                            preset_id=preset_id,
                                            music_path=music_path,
                                            music_start_time=_timeline_audio_start,
                                            variant_constraints=_vconstraints,
                                            seed=_regen_seed,
                                        )
                                        _regen_fp = _TFP.from_segments(
                                            _tl_regen.segments, _vletter_for_profile,
                                            _regen_seed, material_level=_pools.material_level,
                                        )
                                        _regen_violations = _check_min(_regen_fp, _vmem, _pools)
                                        add_render_log(
                                            f"[Diversity] Попытка {_regen_i+1}: "
                                            f"violations={len(_regen_violations)}"
                                        )
                                        if len(_regen_violations) < len(_violations):
                                            all_segments = _tl_regen.segments
                                            _cur_fp = _regen_fp
                                            _violations = _regen_violations
                                    except Exception as _re:
                                        add_render_log(
                                            f"[Diversity] Ошибка пересборки: {_re}", 'WARNING'
                                        )
                                        break

                                if _violations:
                                    _timeline_warnings.append(
                                        "Исходный материал ограничен — "
                                        "варианты могут быть похожи."
                                    )
                                    add_render_log(
                                        f"[Diversity] После {min(_regen_i,5)} попыток:"
                                        f" {'; '.join(_violations[:2])}",
                                        'WARNING'
                                    )

                                # Register this variant in memory
                                _final_fp = _TFP.from_segments(
                                    all_segments, _vletter_for_profile, _base_seed,
                                    material_level=_pools.material_level,
                                    warnings=_timeline_warnings,
                                )
                                _vmem.register(_vletter_for_profile, _final_fp)
                                st.session_state._variant_memory = _vmem

                                # Log full similarity matrix once D is done
                                if _vletter_for_profile == 'D' or len(_vmem.fingerprints) == 4:
                                    add_render_log(
                                        f"[Similarity matrix] {_sim_log_fn(_vmem)}"
                                    )

                            # ── F1: rebuild body with phase-based clip durations ──
                            if preset_id == 'f1' and all_segments:
                                try:
                                    from src.f1_timeline import (
                                        build_f1_phased_body,
                                        F1_PHASE_CONFIG,
                                    )
                                    _f1_intro_segs = [
                                        s for s in all_segments
                                        if getattr(s, '_is_f1_intro_block', False)
                                    ]
                                    _tl_intro_segs = [
                                        s for s in all_segments
                                        if not getattr(s, '_is_f1_intro_block', False)
                                        and getattr(s, 'role', 'body') == 'intro'
                                    ]
                                    _tl_outro_segs = [
                                        s for s in all_segments
                                        if getattr(s, 'role', 'body') == 'outro'
                                    ]
                                    _fixed_dur = sum(
                                        s.duration for s in
                                        _f1_intro_segs + _tl_intro_segs + _tl_outro_segs
                                    )
                                    _body_budget = max(0.0, _target_total - _fixed_dur)
                                    _f1_beat_iv = 0.5  # default 120 BPM
                                    if music_path:
                                        try:
                                            from src.music_sync import MusicAnalyzer
                                            _ma = MusicAnalyzer(cache_enabled=True)
                                            _ma_result = _ma.analyze(
                                                str(music_path),
                                                analyze_beats=True,
                                                analyze_onsets=False,
                                                analyze_energy=False,
                                            )
                                            if _ma_result.tempo:
                                                _f1_beat_iv = 60.0 / _ma_result.tempo
                                                add_render_log(
                                                    f"[F1 Phase] BPM={_ma_result.tempo:.1f}"
                                                    f"  beat={_f1_beat_iv:.3f}s"
                                                )
                                        except Exception as _ma_err:
                                            add_render_log(
                                                f"[F1 Phase] MusicAnalyzer failed: {_ma_err}"
                                                f" — default beat_interval={_f1_beat_iv}s",
                                                'WARNING',
                                            )
                                    _phased_body = build_f1_phased_body(
                                        candidates=_all_candidates,
                                        target_duration=_body_budget,
                                        beat_interval=_f1_beat_iv,
                                        phase_config=F1_PHASE_CONFIG,
                                        seed=_base_seed + 77,
                                        cb=lambda m: add_render_log(m),
                                    )
                                    all_segments = (
                                        _f1_intro_segs
                                        + _tl_intro_segs
                                        + _phased_body
                                        + _tl_outro_segs
                                    )
                                    add_render_log(
                                        f"[F1 Phase] Тело перестроено: "
                                        f"{len(_phased_body)} сегм., "
                                        f"budget={_body_budget:.1f}s",
                                        'SUCCESS',
                                    )
                                except Exception as _f1p_err:
                                    add_render_log(
                                        f"[F1 Phase] Ошибка: {_f1p_err} — тело не изменено",
                                        'WARNING',
                                    )

                        except Exception as _tl_err:
                            add_render_log(
                                f"TimelineBuilder: {_tl_err} — fallback к прямому выбору",
                                'WARNING'
                            )
                            all_segments = []
                            _timeline_warnings = []

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
            # ── Draft mode: pause here and let user review the clip list ─────
            if st.session_state.get('_draft_mode'):
                st.session_state._draft_mode = False
                st.session_state.draft_segments = list(all_segments)
                st.session_state.draft_deleted = set()
                st.session_state.generation_status = 'draft_ready'
                st.session_state.rendering = False
                add_render_log(
                    f"Черновой таймлайн готов: {len(all_segments)} фрагментов — "
                    f"ожидаем одобрения"
                )
                st.rerun()
                return

            # ── Fast preview mode: render 480p quickly ────────────────────────
            if st.session_state.get('_fast_preview_mode'):
                st.session_state._fast_preview_mode = False

                _vidx   = st.session_state.get('building_variant_idx', 0)
                _vletter = _VARIANT_LABELS.get(_vidx, 'A')
                _is_multi = st.session_state.get('_multi_variant_build', False)
                _pcount  = st.session_state.get('preview_count', 1)

                # Per-variant output file name: preview_<name>_<letter>.mp4
                _preview_stem = Path(st.session_state.output_name).stem
                _preview_name = f"preview_{_preview_stem}_{_vletter}.mp4"
                _preview_path = pm.output_dir / _preview_name

                _out_fmt_preview  = st.session_state.get('output_format', 'horizontal')
                _vert_mode_preview = st.session_state.get('vertical_mode', 'center_crop')
                add_render_log(f"⚡ Preview рендер Вариант {_vletter} (480p)...")
                set_render_progress(70, f"Preview Вариант {_vletter}")

                _preview_ok = False
                try:
                    FFmpegRenderer.render_fast_preview(
                        segments=all_segments,
                        output_path=str(_preview_path),
                        output_format=_out_fmt_preview,
                        music_path=music_path,
                        music_start_time=(audio_selection.start_time
                                          if audio_selection else 0.0),
                        vertical_mode=_vert_mode_preview,
                        progress_callback=lambda msg, level='INFO': add_render_log(msg, level),
                    )
                    _preview_ok = True
                    add_render_log(f"Preview {_vletter} сохранён: {_preview_path.name}", 'SUCCESS')
                except Exception as _prev_err:
                    add_render_log(
                        f"Preview {_vletter} ошибка: {_prev_err}", 'WARNING'
                    )

                # Save this variant's data
                _char = _variant_char_label(all_segments, _vidx)
                _tl_stats = {}
                _profile_desc = ''
                _v_warnings: list = list(_timeline_warnings)
                try:
                    _tl_stats = _calc_tl_stats(all_segments)
                    _ref_stats = None
                    if _vidx > 0:
                        _ref_stats = st.session_state.get('variants', {}).get('A', {}).get('stats')
                    if _vprofile:
                        _profile_desc = _get_vui_desc(_vprofile, _tl_stats, _ref_stats)
                except Exception:
                    pass

                # Structural differences vs A (for UI display)
                _struct_diff = {}
                if _vc_available and _vidx > 0:
                    try:
                        _fp_a = _vmem.fingerprints.get('A')
                        _fp_me = _vmem.fingerprints.get(_vletter)
                        if _fp_a and _fp_me:
                            _struct_diff = _atd(_fp_a, _fp_me)
                    except Exception:
                        pass

                _v_data = {
                    'label': f'Вариант {_vletter}',
                    'seed_offset': _vidx,
                    'status': 'ready' if _preview_ok else 'error',
                    'preview_path': str(_preview_path) if _preview_ok else None,
                    'segments': list(all_segments),
                    'n_clips': len(all_segments),
                    'duration': sum(getattr(s, 'duration', 0.0) for s in all_segments),
                    'char_label': _char,
                    'stats': _tl_stats,
                    'profile_description': _profile_desc,
                    'variant_name': (_vconstraints.variant_name
                                     if _vconstraints else f'Вариант {_vletter}'),
                    'warnings': _v_warnings,
                    'struct_diff': _struct_diff,
                }
                if 'variants' not in st.session_state or not st.session_state.variants:
                    st.session_state.variants = {}
                st.session_state.variants[_vletter] = _v_data

                # Always save to legacy preview_path for single-variant compat
                if _preview_ok:
                    st.session_state.preview_path = str(_preview_path)

                # Multi-variant: proceed to next variant or finish
                if _is_multi and _pcount > 1:
                    _next_idx = _vidx + 1
                    if _next_idx < _pcount:
                        # Prepare next variant build
                        _next_letter = _VARIANT_LABELS.get(_next_idx, 'A')
                        add_render_log(
                            f"[Multi] Переход к Варианту {_next_letter} "
                            f"({_next_idx + 1}/{_pcount})"
                        )
                        st.session_state.building_variant_idx = _next_idx
                        st.session_state.variant_seed_offset  = _next_idx
                        st.session_state.approved_segments    = None  # build fresh
                        st.session_state._fast_preview_mode   = True
                        st.session_state._multi_variant_build = True
                        st.session_state.generation_status    = 'rendering'
                    else:
                        # All variants done
                        add_render_log("[Multi] Все варианты сгенерированы", 'SUCCESS')
                        st.session_state._multi_variant_build = False
                        st.session_state.building_variant_idx = 0
                        st.session_state.generation_status    = 'variants_ready'
                else:
                    # Single variant done
                    st.session_state.approved_segments = list(all_segments)
                    st.session_state._multi_variant_build = False
                    st.session_state.generation_status = 'preview_ready'

                st.session_state.rendering = False
                set_render_progress(100, "Готово")
                st.rerun()
                return

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
            add_render_log(f"Видео сохранено: {output_path}", 'SUCCESS')

            # ── Auto stabilization (optional post-process) ─────────────────
            if st.session_state.get('stabilization_enabled', False):
                set_render_progress(85, "Стабилизация видео...")
                add_render_log("Стабилизация: запуск (libvidstab)...")
                _stable_path = output_path.parent / (output_path.stem + "_stable" + output_path.suffix)
                try:
                    _stab_ok = FFmpegRenderer.stabilize_video(
                        input_path=str(output_path),
                        output_path=str(_stable_path),
                        progress_callback=lambda msg, level='INFO': add_render_log(msg, level),
                    )
                    if _stab_ok and _stable_path.exists():
                        import shutil
                        shutil.move(str(_stable_path), str(output_path))
                        add_render_log("Стабилизация применена", 'SUCCESS')
                    else:
                        add_render_log("Стабилизация не выполнена — продолжаем без неё", 'WARNING')
                except Exception as _stab_err:
                    add_render_log(f"Стабилизация: ошибка — {_stab_err}", 'WARNING')

            # ── Watermark (optional post-process) ─────────────────────────
            _wm_text = st.session_state.get('watermark_text', '').strip()
            if st.session_state.get('watermark_enabled', False) and _wm_text:
                set_render_progress(90, "Наложение watermark...")
                add_render_log(f"Watermark: '{_wm_text}'...")
                _wm_path = output_path.parent / (output_path.stem + "_wm" + output_path.suffix)
                try:
                    _wm_ok = FFmpegRenderer.apply_watermark(
                        video_path=str(output_path),
                        output_path=str(_wm_path),
                        text=_wm_text,
                        position=st.session_state.get('watermark_position', 'bottom_right'),
                        opacity=st.session_state.get('watermark_opacity', 0.7),
                    )
                    if _wm_ok and _wm_path.exists():
                        import shutil
                        shutil.move(str(_wm_path), str(output_path))
                        add_render_log("Watermark наложен", 'SUCCESS')
                    else:
                        add_render_log("Watermark не применён", 'WARNING')
                except Exception as _wm_err:
                    add_render_log(f"Watermark: ошибка — {_wm_err}", 'WARNING')

            # ── Auto thumbnail extraction ────────────────────────────────
            set_render_progress(95, "Извлечение обложки...")
            _thumb_path = output_path.parent / (output_path.stem + "_thumb.jpg")
            try:
                _thumb_ok = FFmpegRenderer.extract_thumbnail(
                    video_path=str(output_path),
                    output_path=str(_thumb_path),
                )
                if _thumb_ok:
                    st.session_state.thumbnail_path = str(_thumb_path)
                    add_render_log(f"Обложка: {_thumb_path.name}", 'SUCCESS')
            except Exception as _thumb_err:
                add_render_log(f"Обложка: ошибка — {_thumb_err}", 'WARNING')

            set_render_progress(100, "Готово")
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
