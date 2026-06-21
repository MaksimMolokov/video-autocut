"""
SubtitleService — Whisper transcription → SRT file.

ROADMAP Фаза 1, AU-2: word-level timestamps + сборка SRT под СМОНТИРОВАННУЮ
дорожку (а не по video_paths[0]) — чинит рассинхрон субтитров из ARCHITECTURE §13.2.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Кэш транскрипций по (path, model, lang) — Whisper дорог, один файл = один прогон.
_TRANSCRIBE_CACHE: dict = {}


class SubtitleService:
    """Transcribes audio/video with Whisper and writes an SRT file."""

    def generate_srt(
        self,
        source_path: str,
        output_srt: Optional[str] = None,
        model_name: str = "small",
        language: Optional[str] = None,
    ) -> str:
        """
        Run Whisper transcription on source_path and write an SRT file.

        Args:
            source_path: Path to video or audio file.
            output_srt:  Destination .srt path. If None, written next to source.
            model_name:  Whisper model ('tiny', 'base', 'small', 'medium').
            language:    BCP-47 language code ('ru', 'en', ...) or None for auto.

        Returns:
            Absolute path to the generated .srt file.
        """
        if output_srt is None:
            p = Path(source_path)
            output_srt = str(p.with_suffix(".srt"))

        result = self._transcribe(source_path, model_name, language)
        self._write_srt(result["segments"], output_srt)
        logger.info(f"[Subtitles] SRT written → {output_srt}")
        return output_srt

    def generate_srt_for_timeline(
        self,
        clips: List[dict],
        output_srt: str,
        model_name: str = "small",
        language: Optional[str] = None,
        max_words_per_cue: int = 7,
    ) -> str:
        """Собрать SRT для смонтированной дорожки из word-level таймкодов (AU-2).

        Args:
            clips: список в ПОРЯДКЕ монтажа, каждый — dict с ключами
                   ``source_path`` (или ``abs_path``), ``start_s`` (старт в исходнике),
                   ``duration`` (длительность куска в монтаже).
            output_srt: путь к .srt.
        Слова из каждого исходного куска переносятся в таймлайн монтажа со сдвигом
        ``montage_pos − src_start`` → субтитры совпадают с реальной дорожкой.
        """
        montage_pos = 0.0
        cues: List[dict] = []  # {start, end, text}
        bucket: List[dict] = []

        def _flush():
            if bucket:
                cues.append({
                    "start": bucket[0]["start"],
                    "end":   bucket[-1]["end"],
                    "text":  " ".join(w["word"].strip() for w in bucket).strip(),
                })
                bucket.clear()

        for clip in clips:
            src = clip.get("source_path") or clip.get("abs_path")
            src_start = float(clip.get("start_s", 0.0))
            dur = float(clip.get("duration") or clip.get("_clip_dur") or 0.0)
            src_end = src_start + dur
            if not src or dur <= 0:
                montage_pos += dur
                continue
            try:
                words = self._transcribe(src, model_name, language, want_words=True)["words"]
            except Exception as exc:
                logger.debug("[Subtitles] timeline transcribe skipped for %s: %s", src, exc)
                words = []
            for w in words:
                if w["end"] <= src_start or w["start"] >= src_end:
                    continue
                shift = montage_pos - src_start
                wt = {"word": w["word"],
                      "start": max(montage_pos, w["start"] + shift),
                      "end":   min(montage_pos + dur, w["end"] + shift)}
                bucket.append(wt)
                # разрез реплики по числу слов или по паузе >0.6с
                if len(bucket) >= max_words_per_cue or (
                    len(bucket) >= 2 and bucket[-1]["start"] - bucket[-2]["end"] > 0.6
                ):
                    _flush()
            _flush()  # граница клипа = граница реплики
            montage_pos += dur

        self._write_srt(cues, output_srt)
        logger.info("[Subtitles] timeline SRT written → %s (%d cues)", output_srt, len(cues))
        return output_srt

    # ── transcription core (cached) ────────────────────────────────────────────

    def _transcribe(self, source_path: str, model_name: str,
                    language: Optional[str], want_words: bool = False) -> dict:
        """Транскрибировать с кэшем. Возвращает {'segments': [...], 'words': [...]}."""
        key = (os.path.abspath(source_path), model_name, language or "auto")
        if key in _TRANSCRIBE_CACHE:
            return _TRANSCRIBE_CACHE[key]

        import whisper
        logger.info("[Subtitles] Transcribing %s model=%s words=%s",
                    source_path, model_name, want_words)
        model = whisper.load_model(model_name)
        kwargs: dict = {"verbose": False, "word_timestamps": True}
        if language:
            kwargs["language"] = language
        result = model.transcribe(source_path, **kwargs)

        words: List[dict] = []
        for seg in result.get("segments", []):
            for w in seg.get("words", []) or []:
                words.append({"word": w.get("word", ""),
                              "start": float(w.get("start", seg["start"])),
                              "end":   float(w.get("end", seg["end"]))})
        out = {"segments": result.get("segments", []), "words": words}
        _TRANSCRIBE_CACHE[key] = out
        return out

    # ── internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _write_srt(segments: list, path: str) -> None:
        """Convert Whisper segments list to standard SRT format."""
        with open(path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                start = SubtitleService._fmt_time(seg["start"])
                end   = SubtitleService._fmt_time(seg["end"])
                text  = seg["text"].strip()
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        h  = int(seconds // 3600)
        m  = int((seconds % 3600) // 60)
        s  = int(seconds % 60)
        ms = int(round((seconds - int(seconds)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
