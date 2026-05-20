# Auto Video Cutter

Полуавтоматическая сборка видео из заранее отмеченных "хороших" фрагментов исходника.

## Возможности

- Разметка диапазонов: good, bad, must_use
- Автоматический выбор фрагментов под целевую длительность
- Форматы вывода: horizontal (16:9), vertical (9:16), square (1:1)
- Динамические уровни: slow, balanced, fast
- Интеграция фоновой музыки с fade in/out
- Экспорт в MP4 (h264)

## Требования

- Python 3.9+
- FFmpeg 4.0+ (должен быть установлен и доступен в PATH)

## Установка

```bash
pip install -r requirements.txt
```

## Использование

Создайте файл `project.yaml` с описанием проекта:

```yaml
project:
  name: "My Video Project"

sources:
  - path: "source1.mp4"
    ranges:
      - {start: 5.0, end: 15.0, type: "good"}
      - {start: 20.0, end: 35.0, type: "must_use"}

output:
  target_duration: 60
  format: "horizontal"
  dynamic_level: "balanced"

music:
  path: "background.mp3"
  fade_in: 3.0
  fade_out: 3.0
```

Запустите обработку:

```bash
python -m src.cli project.yaml output.mp4
```

## Архитектура

- `config_loader.py` — загрузка и валидация project.yaml
- `video_analyzer.py` — получение метаданных через ffprobe
- `range_manager.py` — управление диапазонами (good/bad/must_use)
- `segment_selector.py` — алгоритм выбора фрагментов
- `ffmpeg_renderer.py` — генерация FFmpeg команд
- `music_processor.py` — обработка фоновой музыки
- `cli.py` — CLI интерфейс

## Типы диапазонов

- **good** (зеленые) — хорошие фрагменты, могут быть выбраны
- **bad** (красные) — плохие фрагменты, исключаются
- **must_use** (синие) — обязательные фрагменты, включаются всегда

## Форматы вывода

- **horizontal**: 1920×1080 (16:9)
- **vertical**: 1080×1920 (9:16)
- **square**: 1080×1080 (1:1)

## Динамические уровни

- **slow**: медленные переходы, длинные фрагменты (3-10 сек)
- **balanced**: умеренный темп (2-6 сек)
- **fast**: быстрая нарезка (1-4 сек)

## Пресеты

- `slow_cinematic`: slow + horizontal
- `balanced_promo`: balanced + square
- `fast_dynamic`: fast + vertical

## Лицензия

Proprietary
