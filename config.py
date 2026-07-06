"""Конфигурация Auto Video Editor V2."""
from pathlib import Path

# --- Пути ---
BASE_DIR = Path(__file__).parent
PROJECTS_DIR = BASE_DIR / "projects"  # данные всех проектов

# --- LM Studio / LLM (см. SPEC_LOCAL_VIDEO_ANALYSIS.md) ---
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
LM_STUDIO_API_KEY = "lm-studio"  # значение не проверяется, но клиент требует
# Основная модель MVP: Qwen3-VL 8B Instruct (MLX 4bit).
# Идентификатор должен совпадать с тем, что показывает LM Studio в списке моделей.
LLM_MODEL = "qwen/qwen3-vl-8b"
# Резервная vision-модель (уже скачана): gemma-3-12b-it-qat-4bit
LLM_TEMPERATURE = 0.2          # детерминированность разметки
LLM_MAX_TOKENS = 3500  # JSON-карточка сцены с запасом; парсер устойчив к обрыву
LLM_TIMEOUT = 120              # сек на один кадр
FRAME_MAX_SIDE = 1024          # даунскейл кадра перед отправкой в LLM

# --- Детекция сцен ---
MIN_SCENE_LEN_SEC = 1.5        # короче — отбрасываем (ТЗ §7.2)
MAX_SCENE_LEN_SEC = 10.0       # длиннее — режем: куски размера «шота», иначе
                               # метрики усредняют развороты камеры внутри куска
# Отбраковка конкретного фрагмента перед монтажом (скользящее окно)
FRAGMENT_JERK_MAX = 0.45       # дёрганость окна выше — фрагмент не берём
ADAPTIVE_THRESHOLD = 3.0       # PySceneDetect AdaptiveDetector

# --- Качество кадров ---
SHARPNESS_MIN = 40.0           # дисперсия Лапласиана ниже — размытый кадр
DARK_MEAN_MAX = 35.0           # средняя яркость ниже — тёмный кадр
BRIGHT_MEAN_MIN = 225.0        # выше — пересвет
QUALITY_REJECT_THRESHOLD = 0.25  # итоговый скор ниже — сцена исключается
STABILITY_MIN = 0.55             # стабильность ниже — сцена не идёт в монтаж (дёрганая)

# --- Превью ---
THUMB_WIDTH = 480              # ширина миниатюры
PREVIEW_HEIGHT = 360           # высота preview-клипа
PREVIEW_CRF = 30               # быстрый/лёгкий кодек для preview

# --- Видеоформаты ---
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac"}

# --- Форматы экспорта (ТЗ §17) ---
ASPECTS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}
