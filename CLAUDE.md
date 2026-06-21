# AI Video Producer — инструкции для Claude Code

## Автономная доработка

При каждом запуске Claude Code в этом проекте: **продолжай работу над техдолгом**.
Не спрашивай разрешений — пользователь дал права администратора.
Работай на русском языке.

## Текущий статус
- Frontend wizard (frontend/app.py): 10 экранов, полностью работает
- Рендер-пайплайн (src/ffmpeg_renderer.py): исправлен, использует реальный FFmpeg
- Превью: правильный формат (vertical/horizontal), 480p
- Финальный рендер: ~/VideoProjects/{name}/output/, с музыкой

## ТЕХДОЛГ — работай в этом порядке

### TD-001: Alembic миграции [БЫСТРО — 10 мин]
```bash
cd "/Users/maksimmolokov/Projects/video editor"
alembic revision --autogenerate -m "initial_schema"
alembic upgrade head
```
Готово когда: `migrations/versions/` содержит .py файл

### TD-002: Кэш анализа [ВАЖНО]
- `backend/services/analysis_service.py`: перед повторным анализом файла проверь file_hash в БД
- `frontend/app.py` `_run_analysis()`: если все файлы уже проанализированы — пропускай, показывай кэш
- Симптом-фикс: "Почему анализ запускается заново каждый раз?"

### TD-003: Beat-sync тайм-лайн [ВАЖНО]
- В `_build_timeline()` (frontend/app.py): если есть audio_path, импортируй BeatDetector
- Снапай `_clip_dur` к ближайшей битовой метке ±0.15с
- Добавь бейдж "🎵 Бит-синхронизация" в тайм-лайн

### TD-004: Реальный прогресс FFmpeg [DONE]
- Парсим "Segment N/M" из колбэка FFmpegRenderer → точный прогресс-бар
- effects_config передаётся в оба вызова FFmpegRenderer.render()

### TD-005: Color Grading UI [DONE]
- Слайдеры brightness/contrast/saturation/warmth+vignette в _screen_style()
- _build_effects_config() строит EffectsConfiguration → передаётся в render()

### TD-006: Drag-and-Drop тайм-лайн [DONE]
- streamlit-sortables в _render_timeline_editor(); кнопки ↑↓ сохранены как фолбэк

### TD-007: Мульти-трек аудио [DONE]
- FFmpegRenderer: _add_multi_track_audio (voiceover 0.9 + music 0.3), _add_voiceover_only
- UI: expander "🎤 Закадровый голос" в _screen_upload(), voiceover_path в session_state
- Оба вызова render() передают voiceover_path=

### TD-008: Субтитры [DONE]
- backend/services/subtitle_service.py: SubtitleService.generate_srt() через openai-whisper
- FFmpegRenderer._burn_subtitles(): ffmpeg -vf subtitles= re-encode pass
- UI: expander "🔤 Субтитры" в _screen_render() с моделью (tiny/base/small/medium) и языком

## После каждого изменения
```bash
python3 -c "import ast; ast.parse(open('frontend/app.py').read()); print('OK')"
```
НЕ пушить в git без явного запроса пользователя.
