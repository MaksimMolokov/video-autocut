"""
VADDetector — детекция речи/тишины (ROADMAP Фаза 1, AU-1; PDF §9.1, §11.2).

Назначение: для каждого исходного видео найти интервалы речи/звука, чтобы затем
посчитать на уровне фрагмента-сцены `speech_density` — долю речи в кадре. Это
сигнал для скоринга хайлайтов (Фаза 3) и точек нарезки.

Каскад (как у остальных тяжёлых анализаторов — деградирует мягко):
  1. Silero VAD (точная модель речь/тишина) — если установлен ``torch`` и модель
     скачивается через torch.hub. Аудио читается через librosa @16 кГц.
  2. Энергетический VAD на librosa (RMS + адаптивный порог) — fallback без torch.
  3. Полная неудача → пустой результат (трактуется как «звука нет»).

Замечание: метод сознательно НЕ выбраковывает «тихие» фрагменты сам по себе —
для travel/drone-роликов тишина это норма (PDF §6). Решение об отсеве принимает
вызывающая сторона по конфигу ``analysis.reject_silent_segments`` (по умолчанию off).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000          # Silero и energy-VAD работают на 16 кГц
_MIN_SPEECH_S = 0.20          # короче — не считаем речью
_MIN_SILENCE_S = 0.20         # паузы короче — склеиваем в один интервал

Interval = Tuple[float, float]


class VADDetector:
    """Детектор интервалов речи/звука для одного видеофайла."""

    def __init__(self) -> None:
        self._silero = None          # (model, get_speech_timestamps) или False, если недоступен

    # ── публичный API ────────────────────────────────────────────────────────
    def detect(self, abs_path: str) -> Dict:
        """
        Вернуть {
            "speech_intervals": List[(start_s, end_s)],   — интервалы речи/звука
            "method": "silero" | "energy" | "none",
            "audio_duration_s": float,
        }
        """
        y, sr = self._load_audio(abs_path)
        if y is None or len(y) == 0:
            return {"speech_intervals": [], "method": "none", "audio_duration_s": 0.0}

        duration = float(len(y) / sr)

        intervals = self._detect_silero(y, sr)
        method = "silero"
        if intervals is None:
            intervals = self._detect_energy(y, sr)
            method = "energy"

        rms_times, rms_vals = self._rms_envelope(y, sr)

        return {
            "speech_intervals": intervals,
            "method": method,
            "audio_duration_s": duration,
            "rms_times": rms_times,    # AU-3: огибающая громкости (PDF §5.2)
            "rms_values": rms_vals,    # нормированы в [0,1]
        }

    @staticmethod
    def _rms_envelope(y, sr) -> Tuple[List[float], List[float]]:
        """Огибающая громкости (RMS, 1 точка ≈ 30 мс), нормированная в [0,1]."""
        try:
            import librosa
            import numpy as np
            hop = 512
            rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
            times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
            peak = float(rms.max()) or 1.0
            return times.tolist(), (rms / peak).tolist()
        except Exception:
            return [], []

    @staticmethod
    def audio_energy(rms_times: List[float], rms_values: List[float],
                     start_s: float, end_s: float) -> float:
        """Громкость фрагмента как триггер хайлайта (PDF §5.2): пик RMS в окне."""
        if not rms_times or not rms_values:
            return 0.0
        peak = 0.0
        for t, v in zip(rms_times, rms_values):
            if start_s <= t <= end_s and v > peak:
                peak = v
        return float(min(max(peak, 0.0), 1.0))

    @staticmethod
    def speech_density(intervals: List[Interval], start_s: float, end_s: float) -> float:
        """Доля длительности [start_s, end_s], покрытая интервалами речи, в [0, 1]."""
        window = max(end_s - start_s, 1e-6)
        covered = 0.0
        for a, b in intervals:
            lo, hi = max(a, start_s), min(b, end_s)
            if hi > lo:
                covered += hi - lo
        return float(min(covered / window, 1.0))

    # ── Silero VAD ─────────────────────────────────────────────────────────--
    def _detect_silero(self, y, sr) -> List[Interval] | None:
        """Вернуть интервалы речи через Silero VAD или None, если модель недоступна.

        ВЫКЛЮЧЕН ПО УМОЛЧАНИЮ: Silero тянет torch + грузит модель из сети
        (torch.hub) при первом анализе — это медленно и может зависать оффлайн,
        плюс импорт torch конфликтует с file-watcher Streamlit. Включается явно:
        ``ENABLE_SILERO_VAD=1``. Иначе используется energy-VAD на librosa (без torch).
        """
        import os
        if os.getenv("ENABLE_SILERO_VAD", "0") != "1":
            return None
        if self._silero is False:
            return None
        try:
            if self._silero is None:
                import torch  # noqa: F401
                model, utils = torch.hub.load(
                    "snakers4/silero-vad", "silero_vad", trust_repo=True
                )
                get_speech_timestamps = utils[0]
                self._silero = (model, get_speech_timestamps, torch)
            model, get_speech_timestamps, torch = self._silero

            wav = torch.from_numpy(y).float()
            ts = get_speech_timestamps(wav, model, sampling_rate=sr)
            return [(t["start"] / sr, t["end"] / sr) for t in ts]
        except Exception as exc:  # ImportError, сеть, версия API — деградируем
            logger.info("[VAD] Silero недоступен (%s) — fallback на energy-VAD", exc)
            self._silero = False
            return None

    # ── Энергетический VAD (librosa) ──────────────────────────────────────────
    def _detect_energy(self, y, sr) -> List[Interval]:
        try:
            import librosa
            import numpy as np

            hop = 512
            rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
            times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)

            # Адаптивный порог: шумовой пол (низкий перцентиль) + запас до медианы.
            noise_floor = float(np.percentile(rms, 20))
            median = float(np.median(rms))
            thr = max(noise_floor + 0.5 * (median - noise_floor), rms.max() * 0.10, 0.01)

            voiced = rms > thr
            return self._frames_to_intervals(voiced, times, hop, sr)
        except Exception as exc:
            logger.info("[VAD] energy-VAD не сработал (%s)", exc)
            return []

    @staticmethod
    def _frames_to_intervals(voiced, times, hop, sr) -> List[Interval]:
        """Слить помеченные кадры в интервалы, склеить короткие паузы, отсеять мелочь."""
        frame_dur = hop / sr
        intervals: List[Interval] = []
        start = None
        for i, on in enumerate(voiced):
            t = float(times[i])
            if on and start is None:
                start = t
            elif not on and start is not None:
                intervals.append((start, t))
                start = None
        if start is not None:
            intervals.append((start, float(times[-1]) + frame_dur))

        # склейка близких интервалов
        merged: List[Interval] = []
        for a, b in intervals:
            if merged and a - merged[-1][1] < _MIN_SILENCE_S:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        # отсев слишком коротких
        return [(a, b) for a, b in merged if b - a >= _MIN_SPEECH_S]

    # ── загрузка аудио ─────────────────────────────────────────────────────────
    @staticmethod
    def _has_audio_stream(abs_path: str) -> bool:
        """Быстрый ffprobe-précheck: есть ли в файле аудиодорожка.

        Читает только заголовки (доли секунды), с жёстким таймаутом. Без этого
        librosa.load декодировал бы весь файл и зависал на больших/облачных видео.
        """
        import subprocess
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "csv=p=0", abs_path],
                capture_output=True, text=True, timeout=15,
            )
            return bool(r.stdout.strip())
        except Exception as exc:
            logger.info("[VAD] ffprobe не смог проверить аудио в %s (%s) — пропуск", abs_path, exc)
            return False

    @staticmethod
    def _load_audio(abs_path: str):
        """Загрузить моно @16 кГц. Вернуть (np.ndarray|None, sr)."""
        # Нет аудиодорожки (или ffprobe не ответил) → не пытаемся декодировать.
        if not VADDetector._has_audio_stream(abs_path):
            return None, _SAMPLE_RATE
        try:
            import librosa
            y, sr = librosa.load(abs_path, sr=_SAMPLE_RATE, mono=True)
            return y, sr
        except Exception as exc:
            logger.info("[VAD] не удалось прочитать аудио из %s (%s)", abs_path, exc)
            return None, _SAMPLE_RATE
