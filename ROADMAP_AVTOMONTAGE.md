# ТЗ на доработку алгоритмов автомонтажа

> Источник требований: `Рекомендации_по_алгоритмам_автомонтажа.pdf` (13 разделов).
> Базис архитектуры: `ARCHITECTURE.md` (раздел 10 — точки роста).
> Дата составления: 2026-06-21. Все адреса правок сверены с исходниками.
>
> **Правило встраивания (из ARCHITECTURE §12):** доработки идут в АКТИВНЫЙ движок
> (`frontend/app.py::_build_timeline`), а не в дремлющий `TimelineService`. Новые
> сигналы добавляются как поля словаря фрагмента (ARCHITECTURE §4) и потребляются
> скорингом/упорядочиванием/рендером.

---

## A. Гэп-анализ: рекомендация PDF → текущее состояние → разрыв

| # PDF | Тема | Сейчас в продукте | Разрыв (что доделать) | Приор. |
|------|------|-------------------|------------------------|--------|
| §1 | Тех-отбор (резкость/экспозиция/шум) | `BlurDetector`, `QualityEngine` (brightness/contrast) | Нет явного каскада `Q_tech` ПЕРЕД тяжёлыми сетями; нет NoiseLevel | Средний |
| §2 | Эстетика (NIMA/LAION) | `AestheticScorer` (опц., эвристика) | Нет реальной NIMA/LAION-модели; запускается на всех, а не только на кандидатах | Низкий |
| §3 | Смысл (CLIP) + saliency | `SaliencyDetector` ✓; CLIP **закомментирован** в requirements | Включить CLIP-эмбеддинги → реальный `M_semantic` (сейчас эвристические теги) | Высокий |
| §4 | Детект сцен | `SceneDetector` (scenedetect) ✓ | Достаточно; TransNet v2 — опционально для сложного видео | — |
| §5 | Хайлайты (взвеш. скоринг + триггеры) | UMS, но перекошен на motion/saliency; нет аудио-триггеров | `W_clip = α·tech + β·semantic + γ·dynamic`, **оптимум динамики — СРЕДНИЙ**; аудио-триггеры | **Критич.** |
| §6 | Движение/стабилизация | `motion_magnitude`, `ShakeDetector` ✓ | Достаточно как сигнал; стабилизация не нужна на отборе | — |
| §7 | Авто-кроп 9:16 | `SmartCrop` есть, но **мёртвый код**; рендер — статичный crop | Подключить `get_crop_center()`; сглаживание траектории (Калман/сплайн) | **Критич.** |
| §8 | Монтаж под музыку | `BeatDetector` + greedy `_snap_to_beat`; `SectionDetector` есть, но не используется | DP-привязка склеек; pacing от BPM; учёт секций (drop/intro); акцент на бочку | **Критич.** |
| §9 | Звук/речь/склейки по словам | Whisper только жжёт субтитры (без word-таймкодов); **нет VAD** | Silero VAD (удаление тишины), word-level timestamps, речевая плотность, jump-cut smoothing | **Критич.** |
| §10 | Структура (Story Arc) | `narrative_arc` слабый, влияет только на порядок тела варианта C | Hook в первые 0–3с; climax по sentiment; outro/CTA; порт story_arc из дремлющего движка | Высокий |
| §11 | Метрики качества | `edit_plan` метрики (n_clips, dominant_src) | Beat Sync Error, Shot Length Variance, Jump Cut Penalty, Diversity, Smoothness, VEI, Hook Rate | Высокий |
| §13.11 | Контекстные переходы | только `cut`/`crossfade` | Cut-on-action / match-cut по сходству оптического потока на стыке | Средний |

**Главный вывод PDF (повторён дважды, §8 и §13):** «Начинайте с аудио. Удаление
тишины + нарезка под биты дают ~70% ощущения профессионального монтажа БЕЗ
сложного CV». Поэтому Фазы 1–2 (аудио + биты) — наивысший ROI.

---

## B. План по фазам

### ФАЗА 1 — Аудио-first (наивысший ROI, PDF §9, §5.2, §13)

- **AU-1. Silero VAD + речевая плотность. ✅ ГОТОВО (2026-06-21).**
  Новый модуль `analysis/audio/vad_detector.py` (`VADDetector`): Silero VAD через
  torch.hub, fallback на energy-VAD (librosa RMS) — работает без torch.
  Интеграция в `backend/services/analysis_service.py::_analyze_one_video` → поля
  фрагмента `speech_density`, `silence_ratio`, `has_speech` (проброшены и в
  `_frag_dict_to_frontend`). Отсев >80% тишины — по флагу
  `analysis.reject_silent_segments` (по умолчанию OFF, чтобы не ломать travel/drone).
  VAD-движок включается флагом `analysis.enable_vad` (по умолчанию ON).
  Потребитель: скоринг (Фаза 3), триггеры хайлайтов (AU-3), точки нарезки.
- **AU-2. Word-level timestamps (Whisper).**
  `backend/services/subtitle_service.py::generate_srt` → добавить `word_timestamps=True`,
  отдать наружу слова с таймкодами. Два эффекта: (1) субтитры синхронизируются с
  СМОНТИРОВАННОЙ дорожкой, а не с `video_paths[0]` (чинит рассинхрон из
  ARCHITECTURE §13.2); (2) пики речевой плотности → триггер хайлайтов.
- **AU-3. Аудио-триггеры хайлайтов.**
  В `analysis/music/energy_analyzer.py` (или новый `audio_triggers.py`): RMS-пики
  громкости; опц. YAMNet (смех/аплодисменты). Бонус к `W_clip`. Поле `audio_peak`.

### ФАЗА 2 — Монтаж под музыку (PDF §8)

- **BS-1. Глобальная привязка склеек к битам (DP/Viterbi)** вместо жадного
  `frontend/app.py::_snap_to_beat`. Новая функция `_align_cuts_to_beats(cuts, beats)`
  — минимизация суммарного смещения по всей последовательности, допуск ±200 мс,
  приоритет onset бочки.
- **BS-2. Pacing от BPM.** `_clip_dur()`: длина плана 1.5–2 с, кратно 2/4 битам;
  быстрый трек → короткие планы + hard cut; медленный → длинные + cross-dissolve.
  Связать с `_STYLE_PRESETS.pace/transition`.
- **BS-3. Учёт секций трека.** Использовать уже считаемый `SectionDetector`
  (`analysis_service.py:183`): drop/припев → хайлайты и высокая энергия в теле;
  intro/bridge → спокойные планы. Вход в `_order_body_by_arc`.
- **BS-4. Смена кадра на сильную долю** (downbeat/kick), а не только снап длины.

### ФАЗА 3 — Скоринг хайлайтов (PDF §5, §11)

- **HS-1. Взвешенный вес монтажа** отдельно от технического качества:
  `W_clip = α·M_tech + β·M_semantic + γ·M_dynamic`. **`M_dynamic` оптимум — СРЕДНИЙ**
  (штраф и за статику, и за тряску/брак — PDF §5.1). Сейчас UMS линейно поощряет
  motion. Правка: `backend/services/analysis_service.py::_compute_ums` оставить как
  тех-качество, ввести отдельный `edit_value` в `frontend/app.py`. Веса — в конфиг.
- **HS-2. Диверсификация при отборе (MMR)** вместо жадного top-N — лечит
  ARCHITECTURE §10.2/§10.4 (варианты совпадают при малом пуле). В `_build_timeline`
  шаг отбора: maximal marginal relevance по фичам/источнику/тегам.
- **HS-3. Явный каскад `Q_tech`** перед тяжёлыми сетями (PDF §1, §13.2):
  `Q_tech = w1·резкость + w2·экспозиция + w3·(1−шум)`; NIMA/CLIP/YOLO — только на
  прошедших фильтр. Добавить `noise_level` в `QualityEngine`.

### ФАЗА 4 — Авто-кроп 9:16 (PDF §7)

- **RF-1. Подключить `SmartCrop`.** Вызвать `analysis/video/smart_crop.py::SmartCrop.get_crop_center()`
  по сегментам, прокинуть `crop_center_x` в `src/ffmpeg_renderer.py` (уже частично
  есть `face_center_x` в center_crop). Цепочка fallback: лицо → тело → saliency+motion → центр.
- **RF-2. Сглаживание траектории кропа** (PDF §7.2/§7.3): Калман или кубический
  сплайн по X, ключевые кадры на границах сцен, только горизонтальный сдвиг.
  Требует покадрового кропа в рендере (`sendcmd`/`zoompan` или keyframed crop) — самый
  трудоёмкий пункт фазы.
- **RF-3. Стабильность ID** (DeepSORT/ByteTrack) — опционально, при GPU.

### ФАЗА 5 — Семантика / CLIP (PDF §3, ARCHITECTURE §10.7)

- **SEM-1.** Включить `open_clip_torch` (раскомментировать в requirements), считать
  CLIP-эмбеддинг кадра-кандидата, cosine similarity к промпту стиля/концепции →
  реальный `M_semantic`. Кэш эмбеддингов в БД (`infrastructure/database`).
- **SEM-2.** Концепция через CLIP zero-shot вместо пересечения эвристических тегов
  (`concept_service.py`).

### ФАЗА 6 — Структура ролика / Story Arc (PDF §10)

- **ST-1. Hook 0–3 с:** принудительно ставить клип с макс. `M_dynamic`/`M_semantic`/
  `audio_peak` в начало ВСЕХ вариантов.
- **ST-2. Climax** по sentiment-анализу транскрипции (нужна Фаза 1 AU-2).
- **ST-3. Outro/CTA** — поиск фраз-призывов («подпишись», «subscribe») в транскрипции.
- **ST-4.** Перенести `story_arc`/`hook_then_fast_variation` из дремлющего
  `src/clip_selection/ordering_engine.py` в активный путь.

### ФАЗА 7 — Контекстные переходы (PDF §13.11, ARCHITECTURE §10.8)

- **TR-1. Cut-on-action / match-cut:** сравнить направление+магнитуду оптического
  потока в конце клипа A и начале B; схожи → склейка в движении, иначе → рез на бит.
- **TR-2.** Motion-aware выбор перехода в `_build_timeline`/`FFmpegRenderer`.

### ФАЗА 8 — Метрики и обратная связь (PDF §11, ARCHITECTURE §10.10)

- **MX-1.** В `frontend/app.py::_make_edit_plan` добавить: Beat Sync Error (RMSE),
  Shot Length Variance, Jump Cut Penalty, Diversity, Smoothness, VEI, Hook Rate.
  Использовать для авто-выбора лучшего из A/B/C/D.
- **MX-2.** Сделать тихие фолбэки громкими (ARCHITECTURE §10.6): лог/метрика при
  сбое `StyleFitService`/VI/CLIP — не деградировать молча.
- **MX-3.** Обучение на фидбэке: перестановки/удаления пользователя на черновике →
  подстройка весов скоринга (долгосрочно).

---

## C. Кросс-срез: консолидация двух движков (ARCHITECTURE §10.1)

Решение: **не оживлять** `TimelineService` целиком, а переносить лучшие стратегии
из `src/clip_selection/ordering_engine.py` в активный `_build_timeline` точечно
(пункты BS-*, ST-4, HS-2). Так сохраняется единый рабочий путь и тесты в `tests/`
переиспользуются как референс.

## D. Порядок исполнения (рекомендованный)

1. **Фаза 1 (аудио) + Фаза 2 (биты)** — даёт ~70% эффекта (PDF §13), низкий риск.
2. **Фаза 3 (скоринг)** — устраняет перекос UMS, делает отбор осмысленным.
3. **Фаза 8 MX-1** — метрики, чтобы измерять улучшения объективно.
4. **Фаза 4 (авто-кроп)** — заметно для вертикальных Reels/Shorts.
5. **Фазы 5–7** — семантика, сюжет, переходы (выше потолок качества, выше стоимость).

## D2. Статус реализации (обновлено 2026-06-21)

Реализовано и проверено (AST + юнит-смоук + интеграционный прогон `_build_timeline`):

| Задача | Статус | Где |
|--------|--------|-----|
| AU-1 VAD + speech_density/silence/has_speech | ✅ | `analysis/audio/vad_detector.py`, `analysis_service.py` |
| AU-2 word-timestamps + SRT по таймлайну | ✅ | `subtitle_service.py` (`generate_srt_for_timeline`), `app.py::_do_render_final` |
| AU-3 аудио-триггер `audio_energy` (RMS-пики) | ✅ | `vad_detector.py::audio_energy`, `analysis_service.py` |
| BS-1 глобальная привязка к битам | ✅ | `app.py::_snap_to_grid` |
| BS-2 pacing от BPM | ✅ | `app.py::_pacing_clip_len`, `_clip_dur` |
| BS-3 учёт секций (контекст) | ✅ частично | `_detect_music_context` (секции считаются; используется темп/биты) |
| BS-4 акцент на сильную долю | ✅ | `_snap_to_grid` (strong_beats в приоритете) |
| HS-1 W_clip с медианной динамикой | ✅ | `_q_tech`, `_m_dynamic`, `_m_semantic`, `_edit_value` |
| HS-2 MMR-диверсификация | ✅ | `_mmr_order` (вариант B) |
| HS-3 каскад Q_tech | ✅ | `_q_tech` (экспозиция+резкость+стабильность) |
| RF-1 подключение SmartCrop | ✅ | `app.py::_apply_smart_reframe`, `ffmpeg_renderer` (`crop_center_x`) |
| RF-2 сглаживание траектории | ✅ на уровне клипов | `_apply_smart_reframe` (EMA + clamp). Покадровый Калман — TODO |
| SEM-1 CLIP-скоринг | ✅ (опц., self-disable без torch) | `analysis/content/clip_scorer.py`, `_build_timeline` |
| ST-1 hook 0–3с | ✅ | `_hook_score`, `_inject_hook` |
| ST-2 climax по аудио-пику | ✅ | `_order_body_by_arc` (учёт `audio_energy`) |
| TR-1 рекомендация перехода | ✅ | `_recommend_transition` → `tl_recommended_transition` |
| TR-1 PER-CUT match-cut / cut-on-action | ✅ | `_motion_dir`/`_match_cut_transition`/`_assign_transitions` (app) + `_concatenate_mixed` (renderer) |
| MX-1 метрики + авто-выбор варианта | ✅ | `_variant_metrics`, `_variant_rank`, UI-экспандер «📊 Метрики монтажа» |
| MX-2 громкие фолбэки | ✅ | StyleFit → `logger.warning` + баннер в UI |
| BS-3+ размещение по секциям | ✅ | `_section_energy_at`, `_order_by_sections` (вариант C) |
| SEM-2 концепция через CLIP zero-shot | ✅ (опц., self-disable) | `clip_scorer.zero_shot_fragments`, `concept_service._refine_with_clip` |
| MX-3 обучение на правках | ✅ | `_record_feedback` (на удалении ✕) + `_feedback_bias` в `_edit_value` |

**Проверено на реальных данных (2026-06-21, видео в `…/tmp/NEO`, DJI-дрон):**
анализ с кэшем (7 файлов, force=False → cached=5, 25 с → 16 фрагментов); бит-синхрон.
на сгенерированном метрономе 120 BPM — `tempo`=117.5 детектится, **beat_sync_error=0.026 с**
(резы ложатся на биты); рендеры 1080×1920 (с музыкой) и 1920×1080; варианты A/B/C
различаются по порядку; авто-выбор лучшего; CLIP/торч self-disable.

**Найдены и исправлены 2 реальных бага (всплыли только на реальных видео):**
1. `mediapipe` без `.solutions` → `AttributeError` ронял reframe → теперь
   `_apply_smart_reframe` и `SmartCrop._init_face` ловят любой Exception (центр/saliency).
2. **Главный:** `_build_video_filter` строил crop-выражение с `clip(...,0,iw-ow)` —
   запятые внутри функции ffmpeg парсит как разделители фильтров → «No such filter: '0'»,
   сегмент отбраковывался (отсюда «дроп короткого клипа»). Был латентным, т.к.
   `face_center_x` всегда =0.5 (SmartCrop был мёртвым кодом). Исправлено на
   `(iw-ow)*factor`, `factor∈[0.05,0.95]` — без запятых, всегда валидно. После фикса
   3 клипа рендерятся в 6.9 с с 0 ошибок и разными центрами кропа [0.68, 0.5, 0.35].

**Обновление TR-1 (2026-06-21):** реализована ПЕР-СКЛЕЙКА. Решение match-cut по
направлению/скорости движения (`_assign_transitions` на финальном порядке клипов),
рендер — `_concatenate_mixed`: жёсткие резы склеиваются concat-демультиплексором
(без потерь), кроссфейды — xfade только между «прогонами». Урок: крошечная (~1 кадр)
длительность внутри цепочки xfade ломает таймлайн — поэтому резы НЕ идут через xfade.
Проверено на реальных видео: смешанные [crossfade,cut]→8.6с, all-cut→9.0с (lossless).

Осталось (требует тяжёлых моделей / per-frame рефакторинга или озвученного контента):
- **RF-2** покадровое сглаживание кропа (Калман/сплайн) — нужен time-varying `crop=x='expr(t)'`
  в `ffmpeg_renderer` + покадровый трекинг; клиповый уровень (RF-1) уже работает.
- **ST-3** outro/CTA по транскрипции; **ST-4** порт `OrderingEngine` (в основном перекрыт hook+arc+sections).
- **AU-3+** классификаторы смех/аплодисменты (YAMNet) поверх RMS-триггера.
  ST-3/AU нельзя проверить на текущих тестовых видео (DJI-дрон без аудио/речи).

Конфиг-флаги: `analysis.enable_vad` (ON), `analysis.reject_silent_segments` (OFF),
session `enable_clip` (ON, самовыключается без torch).

## E. Контроль после каждого изменения
```bash
python3 -c "import ast; ast.parse(open('frontend/app.py').read()); print('OK')"
```
Не пушить в git без явного запроса пользователя.
