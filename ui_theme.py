"""Тема UI — перенесена из первого проекта (AI Video Producer).

Тёмная палитра #0B0F12, акцент #00FF88, Inter, карточки, wizard-бар,
бейджи, таймлайн-блоки.
"""

CSS = """
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

h1 { font-size: 2rem !important; font-weight: 800 !important; letter-spacing: -.03em !important;
     color: #fff !important; margin-bottom: .3rem !important; }
h2 { font-size: 1.45rem !important; font-weight: 700 !important; color: #fff !important;
     margin-bottom: .4rem !important; }
h3 { font-size: 1rem !important; font-weight: 600 !important; color: #C5CBD3 !important; }
p  { color: #8A9BAE !important; line-height: 1.6 !important; }

/* ── Wizard step bar ── */
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

/* ── Cards ── */
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

/* ── Buttons ── */
.stButton > button {
    background: #00FF88 !important; color: #000000 !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 700 !important; font-size: .88rem !important;
    border: none !important; border-radius: 10px !important;
    padding: .55rem 1.3rem !important;
    transition: filter .15s, transform .12s, box-shadow .15s !important;
    box-shadow: 0 2px 6px rgba(0,255,136,.20) !important;
}
.stButton > button:hover { filter: brightness(1.10) !important; transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(0,255,136,.30) !important; }
.stButton > button:active { transform: translateY(0) !important; filter: brightness(.94) !important; }
.stButton > button:disabled {
    background: #1A2330 !important; color: #4A5A6A !important; cursor: not-allowed !important;
    transform: none !important; box-shadow: none !important; filter: none !important;
    border: 1px solid #232B36 !important; opacity: .7 !important;
}

/* ── Inputs ── */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {
    background: #12171D !important; border: 1px solid #232B36 !important;
    border-radius: 10px !important; color: #E8EDF2 !important;
}
[data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus {
    border-color: #00FF88 !important; box-shadow: 0 0 0 2px rgba(0,255,136,.15) !important;
}

/* ── File uploader ── */
[data-testid="stFileUploaderDropzone"] {
    background: #12171D !important; border: 2px dashed #232B36 !important;
    border-radius: 14px !important; min-height: 140px !important;
    transition: border-color .2s;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color: #00FF88 !important; }

/* ── Progress ── */
.stProgress > div > div > div > div { background: #00FF88 !important; border-radius: 99px !important; }
.stProgress > div > div { background: #1A2228 !important; border-radius: 99px !important; }

/* ── Badges ── */
.badge { display:inline-block; padding:.12rem .55rem; border-radius:99px;
         font-size:.68rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase; }
.b-green  { background:rgba(0,255,136,.15); color:#00FF88; }
.b-teal   { background:rgba(0,212,255,.15); color:#00D4FF; }
.b-red    { background:rgba(255,76,106,.18); color:#FF4C6A; }
.b-yellow { background:rgba(255,210,70,.18); color:#FFD246; }
.b-gray   { background:rgba(138,155,174,.12); color:#8A9BAE; }
.b-purple { background:rgba(123,97,255,.18); color:#7B61FF; }

/* ── Scene thumbs ── */
.scene-thumb { width:100%; aspect-ratio:16/9; border-radius:10px; overflow:hidden;
    background:#1A2228; margin-bottom:.65rem; display:flex; align-items:center; justify-content:center; }
.scene-thumb img { width:100%; height:100%; object-fit:cover; border-radius:10px; }

/* ── AI explainer ── */
.ai-explain {
    background: rgba(0,255,136,.06); border: 1px solid rgba(0,255,136,.18);
    border-radius: 10px; padding: .5rem .75rem; margin: .5rem 0;
    font-size: .78rem; color: #9DE8BE; line-height: 1.5;
}
.ai-explain::before { content:"🤖 "; }

/* ── Stats ── */
.stat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:.6rem; }
.stat-box { background:#12171D; border:1px solid #232B36; border-radius:12px;
    padding:.75rem 1rem; text-align:center; }
.stat-val { font-size:1.8rem; font-weight:800; color:#00FF88; line-height:1.1; }
.stat-lbl { font-size:.7rem; color:#8A9BAE; margin-top:.2rem; font-weight:500;
    text-transform:uppercase; letter-spacing:.05em; }

/* ── Timeline ── */
.tl-wrap { background:#0D1318; border:1px solid #1A2228; border-radius:14px;
    padding:1rem 1.25rem; overflow-x:auto; }
.tl-track-label { font-size:.68rem; font-weight:700; color:#3B4A59;
    text-transform:uppercase; letter-spacing:.07em; margin-bottom:.35rem; }
.tl-audio-row { height:28px; background:#0F2A1A; border-radius:6px;
    display:flex; align-items:center; padding:0 .75rem; margin-bottom:.5rem; }
.tl-audio-wave { flex:1; height:14px; border-radius:4px;
    background:repeating-linear-gradient(90deg,#00FF8822 0,#00FF8855 2px,transparent 2px,transparent 6px); }
.tl-video-row { display:flex; gap:3px; height:64px; align-items:stretch; margin-bottom:.25rem; }
.tl-seg { border-radius:7px; min-width:26px; display:flex; flex-direction:column;
    align-items:center; justify-content:center; overflow:hidden;
    font-size:.6rem; font-weight:700; color:#0B0F12; cursor:default; }
.tl-seg-dur { font-size:.56rem; opacity:.85; margin-top:.1rem; }

/* ── Misc ── */
[data-testid="stAlert"] { background:#12171D !important; border-radius:12px !important;
    border:1px solid #232B36 !important; }
[data-testid="stSelectbox"] > div { background:#12171D !important;
    border:1px solid #232B36 !important; border-radius:10px !important; }
.stTabs [data-baseweb="tab-list"] { background:#12171D !important; border-radius:12px !important;
    padding:3px !important; gap:3px !important; }
.stTabs [data-baseweb="tab"] { background:transparent !important; color:#8A9BAE !important;
    border-radius:9px !important; font-weight:600 !important; font-size:.85rem !important; }
.stTabs [aria-selected="true"] { background:#00FF88 !important; color:#000000 !important; }
[data-testid="stMetric"] { background:#12171D !important; border-radius:12px !important;
    padding:.9rem !important; border:1px solid #232B36 !important; }
[data-testid="stMetricValue"] { color:#00FF88 !important; font-size:1.5rem !important; font-weight:700 !important; }
/* Видео всегда помещается на экран без скролла: ограничиваем высоту
   ~60% вьюпорта; вертикальные 9:16 летербоксятся по центру, не растягиваются */
[data-testid="stVideo"] video {
    border-radius:12px !important; background:#000 !important;
    max-height:60vh !important; object-fit:contain !important;
    width:100% !important;
}
[data-testid="stVideo"] { display:flex; justify-content:center; }
hr { border-color:#1A2228 !important; margin:1.25rem 0 !important; }
[data-testid="stCheckbox"] label { font-size:.85rem !important; color:#C5CBD3 !important; }
::-webkit-scrollbar { width:4px; height:4px; }
::-webkit-scrollbar-track { background:#0D1318; }
::-webkit-scrollbar-thumb { background:#232B36; border-radius:99px; }
[data-testid="stDownloadButton"] > button { background:#00FF88 !important;
    color:#000000 !important; font-weight:700 !important; border-radius:12px !important; }
[data-testid="stExpander"] { background:#12171D !important; border:1px solid #232B36 !important;
    border-radius:12px !important; }
</style>
"""

# Цвета слотов драматургии для таймлайна
SLOT_COLORS = {
    "intro": "#00D4FF",
    "development": "#00FF88",
    "main": "#7B61FF",
    "climax": "#FFD246",
    "ending": "#FF4C6A",
}
