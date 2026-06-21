# DEVELOPMENT STATUS — AI Video Producer

**Дата**: 2026-06-09  
**Статус**: В работе — аудит завершён, исправления в процессе

---

## Аудит завершён

### Найденные root causes

#### BUG-SAME-PREVIEW (КРИТИЧЕСКИЙ)
`ClipCandidate` ORM-модель не имеет колонок `start_s`, `end_s`, `duration_s`.  
`FragmentRepo.save_many` пытается сохранить `source_file_id` (не существует в модели) — SQLAlchemy игнорирует его, `scene_id` остаётся NULL.  
При загрузке из кэша `_candidate_to_dict` читает `candidate.scene` → None → `start_s=0`, `end_s=0` для всех.  
Итог: все сцены из кэша показывают timestamp 0 → одинаковый видеофрагмент.  
**Текущее состояние**: DB пустая (0 rows) → кэш никогда не срабатывает → fresh analysis всегда. Но при первом re-run баг проявится.

#### BUG-THUMB-LIVE (ПРОИЗВОДИТЕЛЬНОСТЬ)
`_scene_card` каждый рендер вызывает `_extract_thumb` (открывает cv2.VideoCapture)  
для N сцен = N VideoCapture открытий. При 24+ сценах — очень медленно.  
Pre-generated `_thumb_abs` вычисляется, но НЕ используется в `_scene_card`.

#### BUG-UPLOAD-SCROLL (UX)
Кнопка "🚀 Запустить AI-анализ" внизу страницы — при 10+ файлах уезжает из видимости.

#### BUG-MOCK-DISPLAY
`_simulate_analysis()` вызывается только при `not video_paths` (demo mode).  
При наличии файлов — исключительно реальный анализ. Mock не показывается как реальный ✓

### Что проверено и работает
- `_analyze_one_video()` обходит каждый файл отдельно ✓  
- `SceneDetector` с histogram fallback — реальный CV2 анализ ✓  
- `QualityEngine` — реальные метрики (sharpness, brightness, contrast, motion) ✓  
- `_score_for_style()` — разный scoring по стилям ✓  
- `_variant()` — diversity по источникам (max_per_src) ✓  
- Logging pipeline уже есть ✓  
- Filters в scene screen — работают ✓  

---

## Backlog задач

| ID | Приоритет | Статус | Задача |
|----|-----------|--------|--------|
| TASK-001 | P0 | ✅ done | Аудит backend pipeline |
| TASK-002 | P0 | ✅ done | Fix ClipCandidate model (add start_s/end_s/source_file_id) + migration |
| TASK-003 | P0 | ✅ done | Fix identical thumbnail/preview — используем pre-generated _thumb_abs |
| TASK-004 | P0 | ✅ done | Mock analysis — только в demo mode (нет файлов), не в production |
| TASK-005 | P1 | ✅ done | Базовые признаки сцены (sharpness/brightness/shake/motion) |
| TASK-006 | P1 | ✅ done | Логирование + per-file breakdown в analysis summary |
| TASK-007 | P1 | ✅ done | Concept scoring profiles — 6 профилей с явными boost/penalty |
| TASK-008 | P1 | ✅ done | Edit plan validation + logging unique sources % |
| TASK-009 | P2 | ✅ done | Fix первая страница — sticky action bar + кнопка вверху списка |
| TASK-010 | P2 | ✅ done | Компактный список файлов + expand/collapse |
| TASK-011 | P2 | ✅ done | Scene card — feature indicators, mode badge, timestamps |
| TASK-012 | P2 | ✅ done | Фильтры сцен + grouped view + min score filter + hide bad |
| TASK-013 | P3 | ✅ done | CSS кнопки — цвет чёрный, мягче, все состояния |
| TASK-014 | P3 | ✅ done | Единый стиль карточек (scene card redesign) |
| TASK-015 | P3 | ✅ done | QA сценарии — E2E через streamlit.testing.v1.AppTest: upload → analysis → фрагменты, кэш работает |
| TASK-016 | P3 | ⬜ | Финальный отчёт |

## Подтверждено тестами

- 1 видео → 3 сцены, уникальные start_s, thumbnails сгенерированы ✓
- Кэш: 2й запуск 0.1с vs 14.4с, start_s сохраняются корректно ✓
- 2 видео → 7 сцен из обоих файлов, уникальные источники ✓
- Синтаксис всех 4 файлов OK ✓

## Файлы изменены

- `infrastructure/database/models.py` — ClipCandidate +14 новых колонок, scene_id nullable
- `infrastructure/database/migrations/versions/8f9a0e92d870_clip_candidate_timing_fields.py` — миграция
- `infrastructure/database/repository.py` — FragmentRepo.save_many, get_for_source, get_filtered
- `backend/services/analysis_service.py` — _candidate_to_dict, _generate_thumbnail, init_db
- `frontend/app.py` — upload UI sticky, scene card, filters, CSS, concept scoring, edit plan

---

## Ключевые файлы

| Файл | Роль |
|------|------|
| `frontend/app.py` | Главный UI (3058 строк) |
| `backend/services/analysis_service.py` | Pipeline анализа |
| `infrastructure/database/models.py` | ORM модели |
| `infrastructure/database/repository.py` | Data access layer |
| `analysis/video/scene_detector.py` | Детектор сцен |
| `analysis/video/quality_engine.py` | Метрики качества |

---

## Продолжить с: TASK-002 → TASK-003 → TASK-009 → TASK-011


## Фикс 2026-06-10: «Анализ не удался» на экране AI-анализа

**Причина:** Streamlit-процесс работал с понедельника со старыми модулями в памяти,
несовместимыми со схемой БД после миграции 8f9a0e92d870. Generic-ошибка скрывала причину.

**Исправлено:**
- `frontend/app.py`: ошибка анализа теперь показывает реальное исключение + путь к логу;
  pre-check существования файлов (temp-загрузки могли быть удалены ОС);
  progress-callback обёрнут в try/except (ошибки UI не роняют анализ);
  предупреждение `analysis_warning` при частичных сбоях;
  файловый лог `.videoeditor/app.log` (все INFO+ из pipeline)
- `backend/services/analysis_service.py`: `failed_files` в результате pipeline
  (имя файла + причина для каждого необработанного), FAILED логируется с traceback
- Streamlit перезапущен на порту 8502 со свежим кодом
- E2E проверено: AppTest upload→analysis → 1 фрагмент, analysis_error=None

## Полный аудит 2026-06-10 (вечер): монтаж работает E2E

**Проверено:** 170 модулей компилируются; 875 тестов проходят (было 75 падений);
все 10 экранов wizard открываются без исключений; все ML-зависимости на месте
(cv2, mediapipe, whisper, librosa, scenedetect); все анализаторы работают на реальном видео.
**E2E монтаж подтверждён:** анализ → 4 варианта таймлайна → превью 480p →
финальный рендер 1920×1080 H.264 + AAC музыка (`~/VideoProjects/qa_dbg/output/`).

### Исправленные баги
1. **КРИТИЧЕСКИЙ — пустой монтаж**: composition-заметки («tilted horizon», «cluttered background»)
   становились жёсткими reject'ами (video_intelligence_service.py), затем все rejected-фрагменты
   авто-помечались excluded (frontend/app.py) → пул пуст → «Нет клипов в таймлайне».
   Фикс: заметки → composition_notes (мягкий сигнал); excluded-дефолты не ставятся для мягких
   причин; при тотальной отбраковке включается лучшая половина; fallback в _build_timeline.
2. **ShotBoundaryDetector слеп к яркости**: гистограмма только H+S — белый и чёрный кадры
   идентичны, склейки по яркости не детектировались. Фикс: H+S+V [15,16,16].
   Добавлен параметр threshold (опциональный).
3. **Экран таймлайна падал** (st.tabs []) при прямом переходе без построенных вариантов —
   теперь авто-build или предупреждение.
4. **timeline_service: relax-фильтр** возвращал отбракованные (shake) фрагменты при pool < 3 —
   теперь ослабление только при пустом пуле и без rejected_motion.
5. **scoring_service: semantic_score** штрафовал (0.4) за отсутствие пересечения тегов —
   теперь нейтрально (0.5).
6. **22 старых пресета восстановлены из git** (easy_mode, f1–f6 и др.) — их удаление ломало
   легаси-GUI (src/gui.py) и тесты. Новый wizard использует свои 8 пресетов независимо.
7. Тесты: мок cv2.VideoCapture использовал неверные константы (0 вместо CAP_PROP_FPS=5);
   speed-factor тесты требовали slow_motion_factor<1.0 у выключенных эффектов.
