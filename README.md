# Auto Video Editor V2

Локальный полуавтоматический монтаж: анализ исходников → каталог сцен → монтажный план → черновик → замена фрагментов → экспорт mp4.

Документы: [ТЗ](TZ_AUTO_VIDEO_EDITOR_V2.md) · [План разработки](DEVELOPMENT_PLAN.md) · [Спецификация LLM](SPEC_LOCAL_VIDEO_ANALYSIS.md)

## Стек

- **Анализ видео:** ffprobe, PySceneDetect (сцены), OpenCV (качество/движение), ffmpeg (превью)
- **Смысловой анализ:** **Qwen3-VL 8B Instruct (MLX 4bit)** через LM Studio API `localhost:1234/v1` (fallback: Gemma 3 12B)
- **Музыка:** librosa (BPM, биты, энергетика, точки склеек)
- **Хранение:** SQLite (`projects/app.db`) + папки проектов (превью/рендеры)
- **UI:** Streamlit

## Быстрый старт

```bash
# 1. LM Studio: загрузить модель qwen/qwen3-vl-8b, включить сервер (порт 1234)

# 2. UI
streamlit run app.py

# … или через CLI:
python3 cli.py analyze ~/видео_папка --name "Мой ролик"   # анализ → каталог сцен
python3 cli.py scenes                                     # посмотреть каталог
python3 cli.py presets                                    # список пресетов
python3 cli.py plan --preset restaurant --duration 30 --aspect 9:16 --music track.mp3
python3 cli.py render              # preview
python3 cli.py render --final      # финальный экспорт
python3 cli.py llm                 # дозаполнить LLM-описания (если LM Studio был выключен)
```

## Архитектура

Три сущности (ТЗ §24): **Проект → Сцена → Монтажный план**.

```
cli.py / app.py (UI)
        │
core/pipeline.py ──► media_import → video_analyzer(ffprobe) → scene_detector(PySceneDetect)
        │             → frame_quality(OpenCV) → previews(ffmpeg) → llm_analyzer(Qwen3-VL)
        │
core/montage_planner.py ──► presets (13 шт) + audio_analyzer(librosa) + LLM-ранжирование
        │                    → MontagePlan (слоты: intro/development/main/climax/ending,
        │                       причины выбора, альтернативы, биты)
        │
core/renderer.py ──► preview (быстрый) / final (качественный) mp4, форматы 9:16·16:9·1:1
```

- LLM недоступен → пайплайн работает rule-based, описания дозаполняются позже (`cli.py llm`).
- Каждый сегмент плана хранит **причину выбора**; история замен пишется в БД.
