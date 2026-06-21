"""
ValidationService — validate uploaded files before analysis (TZ section 5).

Checks: format, size, fps, codec, duration, file integrity.
Returns structured validation result with warnings and errors.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional


_SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".mts", ".m2ts",
    ".mxf", ".dng", ".hevc", ".webm", ".m4v",
}
_SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".aiff",
}
_MAX_VIDEO_SIZE_GB = 10.0
_MAX_AUDIO_SIZE_MB = 500.0
_MIN_FPS = 10.0
_MAX_FPS = 240.0
_MIN_DURATION_S = 1.0
_SUPPORTED_CODECS = {
    "h264", "hevc", "h265", "vp9", "av1", "prores",
    "mpeg4", "mpeg2video", "mjpeg", "dnxhd",
}


class ValidationService:
    """Validate video and audio files before they enter the pipeline."""

    def validate_video(self, abs_path: str) -> Dict:
        """
        Returns {
            valid: bool,
            errors: List[str],
            warnings: List[str],
            info: dict (duration_s, fps, width, height, codec, size_mb)
        }
        """
        errors = []
        warnings = []

        path = Path(abs_path)
        if not path.exists():
            return _result(False, [f"Файл не найден: {abs_path}"], [], {})

        # Extension check
        ext = path.suffix.lower()
        if ext not in _SUPPORTED_VIDEO_EXTENSIONS:
            errors.append(f"Неподдерживаемый формат: {ext}. "
                          f"Поддерживаются: {', '.join(sorted(_SUPPORTED_VIDEO_EXTENSIONS))}")

        # Size check
        size_bytes = path.stat().st_size
        size_gb = size_bytes / 1e9
        size_mb = size_bytes / 1e6
        if size_gb > _MAX_VIDEO_SIZE_GB:
            errors.append(f"Файл слишком большой: {size_gb:.1f} ГБ (максимум {_MAX_VIDEO_SIZE_GB} ГБ)")

        # Probe with ffprobe
        info = {}
        try:
            from backend.services.ffmpeg_service import FFmpegService
            ffmpeg = FFmpegService()
            probe = ffmpeg.probe(abs_path)
            info = probe

            # FPS check
            fps = probe.get("fps", 0)
            if fps < _MIN_FPS:
                warnings.append(f"Низкий FPS: {fps:.1f} (рекомендуется ≥ {_MIN_FPS})")
            if fps > _MAX_FPS:
                warnings.append(f"Очень высокий FPS: {fps:.1f} — будет нормализован до 30")

            # Duration check
            duration = probe.get("duration_s", 0)
            if duration < _MIN_DURATION_S:
                errors.append(f"Слишком короткое видео: {duration:.1f}с (минимум {_MIN_DURATION_S}с)")
            if duration > 7200:
                warnings.append(f"Очень длинное видео: {duration/60:.0f} мин — анализ займёт время")

            # Resolution check
            width = probe.get("width", 0)
            height = probe.get("height", 0)
            if width < 480 or height < 480:
                warnings.append(f"Низкое разрешение: {width}×{height} — качество может быть плохим")

            # Codec check
            codec = probe.get("codec", "").lower()
            if codec not in _SUPPORTED_CODECS:
                warnings.append(f"Нестандартный кодек: {codec} — может потребоваться перекодирование")

        except Exception as exc:
            errors.append(f"Не удалось прочитать файл: {exc}")

        info["size_mb"] = round(size_mb, 1)
        valid = len(errors) == 0
        return _result(valid, errors, warnings, info)

    def validate_audio(self, abs_path: str) -> Dict:
        errors = []
        warnings = []

        path = Path(abs_path)
        if not path.exists():
            return _result(False, [f"Файл не найден: {abs_path}"], [], {})

        ext = path.suffix.lower()
        if ext not in _SUPPORTED_AUDIO_EXTENSIONS:
            errors.append(f"Неподдерживаемый формат аудио: {ext}")

        size_mb = path.stat().st_size / 1e6
        if size_mb > _MAX_AUDIO_SIZE_MB:
            warnings.append(f"Большой аудиофайл: {size_mb:.0f} МБ — анализ займёт время")

        info = {"size_mb": round(size_mb, 1)}
        try:
            from backend.services.ffmpeg_service import FFmpegService
            probe = FFmpegService().probe(abs_path)
            info.update(probe)
            dur = probe.get("duration_s", 0)
            if dur < 5:
                errors.append(f"Слишком короткий аудиофайл: {dur:.1f}с")
            if dur > 600:
                warnings.append(f"Длинный трек: {dur/60:.0f} мин — будет использован лучший фрагмент")
        except Exception as exc:
            errors.append(f"Не удалось прочитать аудио: {exc}")

        return _result(len(errors) == 0, errors, warnings, info)

    def validate_project_inputs(
        self,
        video_paths: List[str],
        audio_path: Optional[str] = None,
    ) -> Dict:
        """Validate all project inputs at once. Returns combined result."""
        all_errors = []
        all_warnings = []
        file_results = {}

        for vp in video_paths:
            r = self.validate_video(vp)
            file_results[vp] = r
            all_errors.extend([f"{Path(vp).name}: {e}" for e in r["errors"]])
            all_warnings.extend([f"{Path(vp).name}: {w}" for w in r["warnings"]])

        if audio_path:
            r = self.validate_audio(audio_path)
            file_results[audio_path] = r
            all_errors.extend([f"{Path(audio_path).name}: {e}" for e in r["errors"]])
            all_warnings.extend([f"{Path(audio_path).name}: {w}" for w in r["warnings"]])

        return {
            "valid": len(all_errors) == 0,
            "errors": all_errors,
            "warnings": all_warnings,
            "files": file_results,
        }


def _result(valid: bool, errors: List[str], warnings: List[str], info: dict) -> Dict:
    return {"valid": valid, "errors": errors, "warnings": warnings, "info": info}
