# MVP-версия предобработки

Срок реализации: **2–3 недели**.

---

## Что входит в MVP

### Новые модули

| Файл | Что делает |
|---|---|
| `src/storage/analysis_db.py` | SQLite-обёртка: CRUD, инвалидация кэша, подсчёт фрагментов |
| `src/preprocessing/scene_detector.py` | PySceneDetect ContentDetector, `frame_skip=5`, `threshold=27.0` |
| `src/preprocessing/quality_analyzer.py` | OpenCV: sharpness, brightness, stability, motion, брак-флаги |
| `src/preprocessing/clip_scorer.py` | quality_score + стилевые scores из технических метрик |
| `src/preprocessing/preview_generator.py` | FFmpeg: JPG thumbnail 320×180 из середины сцены |
| `src/preprocessing/pipeline.py` | Оркестрация: параллельный запуск, инкрементальность |
| `src/preprocessing/clip_library.py` | FragmentLibrary: API для GUI и SegmentSelector |

### Изменения в существующих файлах

| Файл | Изменение |
|---|---|
| `src/gui.py` | Добавить кнопку «Анализировать», прогресс-бар, простой список фрагментов |
| `src/segment_selector.py` | Добавить `load_from_fragment_db()` как альтернативный источник кандидатов |

### Что анализируется

- Резкость (Laplacian variance)
- Яркость (mean pixel value)
- Стабильность (optical flow variance)
- Движение (optical flow magnitude)
- Чёрные кадры / пересвет / encoding artifact
- Пустые кадры (edge density)

### Что нет в MVP (откладывается)

- Детекция лиц и людей
- Тип плана (wide/medium/close)
- Пригодность для crop
- Perceptual hash (дубли)
- Видео-превью (только статичный thumbnail)
- CLIP-теги сцен

---

## Что это даёт пользователю

1. **Отсев технического брака автоматически** — тёмные, смазанные, пустые,
   трясущиеся куски больше не попадают в монтаж
2. **Видимость** — пользователь видит, из чего система строит ролик
3. **Кэш** — повторный рендер с другим стилем/музыкой не требует повторного анализа
4. **Заметное улучшение качества** на плохих исходниках (тёмная съёмка, тряска, дубли)

---

## Технические сложности MVP

### PySceneDetect может быть медленным
**Решение:** использовать `frame_skip=5` (анализировать каждый 5-й кадр).
Для 30fps видео — анализ каждого 6-го кадра. Потеря точности минимальна
для целей разбивки на сцены.

### Синхронизация кэша
**Проблема:** пользователь добавил/удалил видео из папки.
**Решение:** при старте анализа всегда сверять список файлов с `source_files`.
Новые файлы → добавить с `status='pending'`. Удалённые файлы → помечать фрагменты
как `unavailable` (не удалять).

### Конфликт версий OpenCV
**Решение:** зафиксировать `opencv-python==4.8.1.78` в `requirements.txt`.
Не использовать `opencv-contrib-python` в MVP — только stdlib OpenCV.

### Параллельность в macOS
`multiprocessing` на macOS требует `if __name__ == '__main__'` guard.
В Streamlit это работает иначе — использовать `ProcessPoolExecutor` вместо
`multiprocessing.Pool`.

---

## Минимальный UI в MVP

```python
# В gui.py, на шаге выбора источников

if st.button("🔍 Анализировать материалы", type="primary"):
    progress_bar  = st.progress(0)
    status_text   = st.empty()

    def on_progress(filename: str, done: int, total: int):
        progress_bar.progress(done / total)
        status_text.text(f"Обработка: {filename}  ({done}/{total})")

    n = analyze_project(project_dir, progress_callback=on_progress)
    st.success(f"Найдено {n} удачных фрагментов")

# Простой список с thumbnails (без ручного одобрения в MVP)
fragments = lib.get_fragments_for_ui(project_dir, min_quality=0.55, limit=50)
cols = st.columns(4)
for i, f in enumerate(fragments):
    with cols[i % 4]:
        st.image(f.thumbnail_path, caption=f"{f.filename} {f.start_s:.1f}–{f.end_s:.1f}s  ★{f.quality_score:.2f}")
```

---

## Критерии готовности MVP

- [ ] analyze_project() завершается без ошибок на тестовой папке с 10+ видео
- [ ] После анализа `quality_score < 0.08` фрагменты не попадают в кандидаты
- [ ] Повторный запуск analyze_project() на той же папке: время < 2 с
- [ ] Thumbnails генерируются для каждого найденного фрагмента
- [ ] Кнопка в GUI запускает анализ и показывает прогресс
- [ ] При рендере с F1/F5 среднее quality_score кандидатов > 0.55
