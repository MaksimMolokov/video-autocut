"""AnalysisService — orchestrate video and music analysis (TASK-003)."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from sqlalchemy.orm import Session

from infrastructure.config.config_manager import cfg
from infrastructure.database.models import create_db_engine
from infrastructure.database.repository import FragmentRepo, SourceFileRepo
from infrastructure.storage.path_manager import PathManager

logger = logging.getLogger(__name__)


class AnalysisService:
    """
    Run the full analysis pipeline for a project.

    Accepts either a PathManager or a plain project root string.
    Returns frontend-compatible dicts with "fragments", "duplicates_removed", etc.
    """

    def __init__(self, path_manager_or_root: Union[PathManager, str]) -> None:
        if isinstance(path_manager_or_root, PathManager):
            self.pm = path_manager_or_root
        else:
            self.pm = PathManager(str(path_manager_or_root))
            self.pm.ensure_dirs()
        self._engine = create_db_engine(str(self.pm.db_path))
        # Ensure schema exists (idempotent — no-op if already created)
        from infrastructure.database.models import init_db
        init_db(self._engine)

    def analyze_project(
        self,
        abs_paths: Optional[List[str]] = None,
        force: bool = False,
        progress_callback: Optional[Callable] = None,
        # legacy alias
        progress_cb: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Analyze all videos in abs_paths.

        Returns:
            {
                "fragments":          List[dict],  # frontend-compatible clip dicts
                "duplicates_removed": int,
                "total_analyzed":     int,
                "cached":             int,         # files skipped (cached)
            }

        progress_callback(stage_idx: int, detail: str = "", found: int = 0)
        """
        _cb = progress_callback or progress_cb

        if not abs_paths:
            return {"fragments": [], "duplicates_removed": 0, "total_analyzed": 0, "cached": 0}

        total = len(abs_paths)
        all_frags: List[dict] = []
        n_cached = 0
        duplicates_removed = 0
        failed_files: List[dict] = []

        _t_pipeline_start = time.time()
        logger.info("[AnalysisService] starting pipeline: %d files", total)

        with Session(self._engine) as session:
            source_repo = SourceFileRepo(session)
            frag_repo   = FragmentRepo(session)

            for idx, abs_path in enumerate(abs_paths, 1):
                p = Path(abs_path)
                if not p.exists():
                    logger.warning("[AnalysisService] [%d/%d] not found: %s", idx, total, abs_path)
                    failed_files.append({"name": p.name, "error": "файл не найден на диске"})
                    continue

                try:
                    rel_path = str(self.pm.rel(abs_path))
                except Exception:
                    rel_path = p.name

                if _cb:
                    try:
                        _cb(idx, f"[{idx}/{total}] {p.name}", idx)
                    except Exception:
                        try:
                            _cb(idx, f"Анализ: {p.name}")
                        except Exception:
                            pass

                source = source_repo.get_or_create(rel_path)
                file_hash = _file_hash(abs_path)

                # Cache hit: file already analyzed with same hash
                if not force and source_repo.is_analyzed(rel_path, file_hash):
                    file_frags = frag_repo.get_for_source(source.id)
                    all_frags.extend(_candidate_to_dict(f, abs_path) for f in file_frags)
                    n_cached += 1
                    logger.info("[AnalysisService] [%d/%d] CACHED %s → %d frags (start_s range: %.1f–%.1f)",
                                idx, total, p.name, len(file_frags),
                                file_frags[0].start_s if file_frags else 0,
                                file_frags[-1].end_s if file_frags else 0)
                    continue

                _t_file = time.time()
                try:
                    fragment_dicts = _analyze_one_video(abs_path, rel_path, self.pm)
                    saved = frag_repo.save_many(source.id, fragment_dicts)
                    source_repo.mark_analyzed(
                        source.id,
                        file_hash=file_hash,
                        duration_s=fragment_dicts[0].get("_src_duration_s", 0.0) if fragment_dicts else 0.0,
                    )

                    for i, frag_dict in enumerate(fragment_dicts):
                        fid = saved[i].id if i < len(saved) else (source.id * 1000 + i)
                        all_frags.append(_frag_dict_to_frontend(frag_dict, fid, p.name, abs_path))

                    _elapsed = time.time() - _t_file
                    logger.info("[AnalysisService] [%d/%d] DONE %s → %d frags (%.1fs)",
                                idx, total, p.name, len(saved), _elapsed)
                except Exception as exc:
                    source_repo.mark_error(source.id, str(exc))
                    failed_files.append({"name": p.name, "error": f"{type(exc).__name__}: {exc}"})
                    logger.error("[AnalysisService] [%d/%d] FAILED %s: %s",
                                 idx, total, p.name, exc, exc_info=True)

        # Mark duplicates
        seen_hashes: Dict[str, int] = {}
        for frag in all_frags:
            h = frag.get("_phash")
            if h:
                if h in seen_hashes:
                    frag["is_duplicate"] = True
                    frag["rejection_reason"] = frag.get("rejection_reason") or "Дубль другого фрагмента"
                    duplicates_removed += 1
                else:
                    seen_hashes[h] = frag["id"]

        # Assign sequential IDs (consistent with session_state)
        for i, frag in enumerate(all_frags):
            frag["id"] = i

        _total_elapsed = time.time() - _t_pipeline_start
        logger.info(
            "[AnalysisService] pipeline done: %d files, %d analyzed, %d cached, "
            "%d fragments, %d dupes, %.1fs total",
            total, total - n_cached, n_cached, len(all_frags), duplicates_removed, _total_elapsed,
        )

        return {
            "fragments":          all_frags,
            "duplicates_removed": duplicates_removed,
            "total_analyzed":     total - n_cached,
            "cached":             n_cached,
            "elapsed_s":          _total_elapsed,
            "failed_files":       failed_files,
        }

    def analyze_music(self, abs_path: str) -> List[dict]:
        from analysis.music.bpm_detector import BpmDetector
        from analysis.music.beat_detector import BeatDetector
        from analysis.music.energy_analyzer import EnergyAnalyzer
        from analysis.music.section_detector import SectionDetector
        from infrastructure.database.repository import MusicFragmentRepo

        p = Path(abs_path)
        try:
            rel_path = str(self.pm.rel(abs_path))
        except Exception:
            rel_path = p.name

        bpm_result = BpmDetector().detect(abs_path)
        beats      = BeatDetector().detect(abs_path)
        energy     = EnergyAnalyzer().analyze(abs_path)
        sections   = SectionDetector().detect(abs_path, energy=energy, beats=beats)

        fragments = _build_music_fragments(rel_path, bpm_result, beats, energy, sections)

        with Session(self._engine) as session:
            repo = MusicFragmentRepo(session)
            repo.clear_for_audio(rel_path)
            repo.save_many(fragments)

        return fragments


# ── Conversion helpers ─────────────────────────────────────────────────────────

def _candidate_to_dict(candidate, abs_path: str) -> dict:
    """Convert ClipCandidate ORM object to frontend-compatible dict."""
    # Use directly stored timing fields (migration 8f9a0e92d870 added these)
    start_s = candidate.start_s or 0.0
    end_s   = candidate.end_s   or 0.0

    # Fall back to scene relationship only if direct fields are zero/missing
    if start_s == 0.0 and end_s == 0.0:
        scene = getattr(candidate, "scene", None)
        if scene:
            start_s = scene.start_s or 0.0
            end_s   = scene.end_s   or 0.0

    source_name = (getattr(candidate, "source_filename", None)
                   or Path(abs_path).name)

    return {
        "id":                 candidate.id,
        "source":             source_name,
        "_abs_path":          abs_path,
        "start_s":            start_s,
        "end_s":              end_s,
        "duration_s":         (end_s - start_s),
        "quality_score":      candidate.quality_score or 0.0,
        "technical_score":    candidate.technical_score or 0.0,
        "content_score":      candidate.content_score or 0.0,
        "aesthetic_score":    candidate.aesthetic_score or 0.0,
        "rejection_reason":   candidate.rejection_reason,
        "selection_reason":   candidate.selection_reason or "",
        "has_face":           bool(getattr(candidate, "has_face", False)),
        "has_person":         bool(getattr(candidate, "has_person", False)),
        "camera_motion_type": getattr(candidate, "camera_motion_type", "static") or "static",
        "scene_tags":         getattr(candidate, "scene_tags", []) or [],
        "is_duplicate":       bool(getattr(candidate, "is_duplicate", False)),
        "sharpness":          getattr(candidate, "sharpness", 0.5) or 0.5,
        "brightness":         getattr(candidate, "brightness", 0.5) or 0.5,
        "camera_shake":       getattr(candidate, "camera_shake", 0.0) or 0.0,
        "thumbnail_rel_path": getattr(candidate, "thumbnail_rel_path", None),
        "analysis_mode":      "cached",
    }


def _frag_dict_to_frontend(frag: dict, fid: int, source_name: str, abs_path: str) -> dict:
    """Convert raw analysis dict to frontend-compatible fragment dict."""
    tags = []
    if frag.get("has_face"):
        tags.append("face")
    if frag.get("camera_motion_type") in ("pan", "tilt", "zoom"):
        tags.append("motion")
    if frag.get("aesthetic_score", 0) > 0.7:
        tags.append("cinematic")
    if frag.get("saliency_score", 0) > 0.7:
        tags.append("saliency")

    score = frag.get("quality_score", 0.5)
    has_face = bool(frag.get("has_face") or frag.get("face_count", 0) > 0)

    return {
        "id":               fid,
        "source":           source_name,
        "_abs_path":        abs_path,
        "start_s":          frag.get("start_s", 0.0),
        "end_s":            frag.get("end_s", 0.0),
        "quality_score":    frag.get("quality_score", score),
        "technical_score":  frag.get("technical_score", score),
        "content_score":    frag.get("content_score", score),
        "aesthetic_score":  frag.get("aesthetic_score", score),
        "has_face":         has_face,
        "has_person":       bool(frag.get("has_person") or has_face),
        "camera_motion_type": frag.get("camera_motion_type", "static"),
        "rejection_reason": frag.get("reject_reason") or frag.get("rejection_reason"),
        "selection_reason": _make_reason(frag),
        "scene_tags":       frag.get("scene_tags", tags),
        "is_duplicate":     bool(frag.get("is_duplicate", False)),
        "sharpness":        frag.get("sharpness", frag.get("blur_score", 0.5)),
        "brightness":       frag.get("brightness", 0.5),
        "camera_shake":     frag.get("camera_shake", 0.0),
        "speech_density":   frag.get("speech_density", 0.0),
        "silence_ratio":    frag.get("silence_ratio", 1.0),
        "has_speech":       bool(frag.get("has_speech", False)),
        "audio_energy":     frag.get("audio_energy", 0.0),
        "semantic_tags":    frag.get("semantic_tags", frag.get("scene_tags", [])),
        "clip_score":       frag.get("clip_score"),
        "thumbnail_rel_path": frag.get("thumbnail_rel_path"),
        "_phash":           frag.get("_phash"),
    }


def _make_reason(frag: dict) -> str:
    parts = []
    score = frag.get("quality_score", 0.5)
    if score > 0.8:
        parts.append("высокая резкость и качество")
    elif score > 0.6:
        parts.append("хорошее качество кадра")
    if frag.get("has_face") or frag.get("face_count", 0) > 0:
        parts.append("лицо в кадре")
    tags = frag.get("scene_tags", [])
    if "drone" in tags or "aerial" in tags:
        parts.append("красивый аэро-кадр")
    if "wide" in tags:
        parts.append("широкий план")
    if not parts:
        parts.append("соответствует критериям качества")
    return "; ".join(parts).capitalize() + "."


# ── Analysis pipeline ─────────────────────────────────────────────────────────

def _analyze_one_video(abs_path: str, rel_path: str, pm: PathManager) -> List[dict]:
    """Per-video analysis pipeline."""
    from analysis.video.scene_detector import SceneDetector
    from analysis.video.quality_engine import QualityEngine
    from analysis.video.blur_detector import BlurDetector
    from analysis.video.shake_detector import ShakeDetector

    scenes = SceneDetector().detect(abs_path)
    if not scenes:
        return []

    quality_engine = QualityEngine()
    blur_det       = BlurDetector()
    shake_det      = ShakeDetector()

    enable_content    = cfg.get("analysis.enable_content_analysis", True)
    enable_aesthetic  = cfg.get("analysis.enable_aesthetic_scoring", True)
    face_det          = None
    saliency_det      = None
    aesthetic_scorer  = None

    if enable_content:
        try:
            from analysis.content.face_detector import FaceDetector
            face_det = FaceDetector()
        except Exception:
            pass
        try:
            from analysis.content.saliency_detector import SaliencyDetector
            saliency_det = SaliencyDetector()
        except Exception:
            pass
    if enable_aesthetic:
        try:
            from analysis.content.aesthetic_scorer import AestheticScorer
            aesthetic_scorer = AestheticScorer()
        except Exception:
            pass

    # ── Speech / silence / loudness (ROADMAP Фаза 1 AU-1/AU-3; PDF §9.1, §5.2) ─
    speech_intervals: list = []
    rms_times: list = []
    rms_values: list = []
    _speech_density = lambda ivals, a, b: 0.0       # noqa: E731  безопасный дефолт
    _audio_energy   = lambda t, v, a, b: 0.0        # noqa: E731
    # ВЫКЛ по умолчанию: декодирование аудио из видео (librosa→ffmpeg) на больших/
    # облачных файлах висит (stream timeout). Включается analysis.enable_vad=true,
    # и даже тогда VADDetector сам пропускает файлы без аудиодорожки (ffprobe-précheck).
    if cfg.get("analysis.enable_vad", False):
        try:
            from analysis.audio.vad_detector import VADDetector
            _vad_res = VADDetector().detect(abs_path)
            speech_intervals = _vad_res.get("speech_intervals", [])
            rms_times        = _vad_res.get("rms_times", [])
            rms_values       = _vad_res.get("rms_values", [])
            _speech_density  = VADDetector.speech_density
            _audio_energy    = VADDetector.audio_energy
        except Exception as vad_exc:
            logger.debug("[AnalysisService] VAD skipped: %s", vad_exc)
    reject_silent = cfg.get("analysis.reject_silent_segments", False)

    src_duration = scenes[-1]["end_s"] if scenes else 0.0
    fragments = []

    for scene in scenes:
        metrics = quality_engine.analyze(abs_path, scene["start_s"], scene["end_s"])
        blur    = blur_det.score(abs_path, scene["start_s"], scene["end_s"])
        shake   = shake_det.score(abs_path, scene["start_s"], scene["end_s"])

        frag: dict = {
            "start_s":          scene["start_s"],
            "end_s":            scene["end_s"],
            "duration_s":       scene["end_s"] - scene["start_s"],
            **metrics,
            "blur_score":       blur.get("score", 0.5),
            "is_blurry":        blur.get("is_blurry", False),
            "camera_shake":     shake.get("shake_score", 0.0),
            "camera_motion_type": shake.get("motion_type", "static"),
            "reject_reason":    _reject_reason(metrics, blur, shake),
            "_src_duration_s":  src_duration,
        }

        if face_det:
            try:
                face_res = face_det.detect(abs_path, scene["start_s"], scene["end_s"])
                frag.update(face_res)
            except Exception:
                pass

        if saliency_det:
            try:
                frag["saliency_score"] = saliency_det.score(abs_path, scene["start_s"], scene["end_s"])
            except Exception:
                pass

        if aesthetic_scorer:
            try:
                frag["aesthetic_score"] = aesthetic_scorer.score(abs_path, scene["start_s"])
            except Exception:
                pass

        # speech density для этой сцены из общих интервалов речи видео
        density = _speech_density(speech_intervals, scene["start_s"], scene["end_s"])
        frag["speech_density"] = density
        frag["silence_ratio"]  = round(1.0 - density, 4)
        frag["has_speech"]     = density >= 0.15
        frag["audio_energy"]   = round(
            _audio_energy(rms_times, rms_values, scene["start_s"], scene["end_s"]), 4
        )
        # PDF §11.2: фрагменты с >80% тишины можно отсеивать — но только по флагу,
        # т.к. для travel/drone тишина это норма (не ломаем рабочее поведение).
        if reject_silent and not frag.get("reject_reason") and frag["silence_ratio"] > 0.80:
            frag["reject_reason"] = "Почти полная тишина"

        frag["quality_score"] = _compute_ums(frag)

        thumb_rel = _generate_thumbnail(abs_path, scene["start_s"], pm, scene["end_s"])
        frag["thumbnail_rel_path"] = thumb_rel

        fragments.append(frag)

    # ── Video Intelligence enrichment ─────────────────────────────────────────
    vi_enabled = cfg.get("video_intelligence.enabled", True)
    if vi_enabled and fragments:
        try:
            from backend.services.video_intelligence_service import VideoIntelligenceService
            VideoIntelligenceService().enrich(fragments, abs_path)
        except Exception as vi_exc:
            try:
                from analysis.intelligence.segment_feature_builder import SegmentFeatureBuilder
                SegmentFeatureBuilder().enrich(fragments, abs_path)
            except Exception:
                pass
            logger.debug("[AnalysisService] VI enrichment used fallback: %s", vi_exc)

    # ── Re-score with all VI data (VI2-014, VI2-016) ───────────────────────────
    try:
        from backend.services.scoring_service import ScoringService
        ScoringService().apply_scores(fragments)
    except Exception as sc_exc:
        logger.debug("[AnalysisService] ScoringService skipped: %s", sc_exc)
        for frag in fragments:
            frag["quality_score"] = _compute_ums(frag)

    return fragments


def _reject_reason(metrics: dict, blur: dict, shake: dict) -> Optional[str]:
    if blur.get("is_blurry"):
        return "Размытый кадр"
    cfg_q = cfg.quality
    if metrics.get("brightness", 1.0) < cfg_q.get("brightness_min", 0.05):
        return "Слишком тёмный кадр"
    if shake.get("shake_score", 0.0) > 0.9:
        return "Сильная тряска камеры"
    return None


def _compute_ums(frag: dict) -> float:
    """
    Unified Media Score. Weights are read from config; VI scores are included
    when available (aesthetic_score, composition_score, vi_score).
    """
    w = cfg.get("quality.weights") or {}

    sharpness    = frag.get("sharpness",          0.5) * w.get("sharpness",  0.35)
    stability    = max(0.0, 1.0 - frag.get("camera_shake", 0.0)) * w.get("stability", 0.25)
    brightness   = frag.get("brightness",         0.5) * w.get("brightness", 0.20)
    contrast     = frag.get("contrast",           0.5) * w.get("contrast",   0.20)
    motion       = frag.get("motion_magnitude",   0.3) * w.get("motion",     0.40)
    saliency     = frag.get("saliency_score",     0.5) * w.get("saliency",   0.50)

    # VI2-014: incorporate aesthetic, composition, and vi_score when available
    aesthetic    = frag.get("aesthetic_score",    -1.0)
    composition  = frag.get("composition_score",  -1.0)
    vi_score     = frag.get("vi_score",           -1.0)

    total_weight = sum(w.values()) or 1.0
    total        = sharpness + stability + brightness + contrast + motion + saliency

    if aesthetic >= 0.0:
        total        += aesthetic    * w.get("aesthetic_score", 0.60)
        total_weight += w.get("aesthetic_score", 0.60)

    if composition >= 0.0:
        total        += composition  * w.get("composition", 0.40)
        total_weight += w.get("composition", 0.40)

    if vi_score >= 0.0:
        total        += vi_score     * w.get("vi_score", 0.50)
        total_weight += w.get("vi_score", 0.50)

    return min(1.0, max(0.0, total / total_weight))


def _generate_thumbnail(abs_path: str, start_s: float, pm: PathManager,
                        end_s: float = 0.0) -> Optional[str]:
    """Extract a frame at the scene midpoint and save as JPEG."""
    try:
        import cv2, hashlib
        t = (start_s + end_s) / 2 if end_s > start_s else start_s
        # Unique name: stem + scene hash so different scenes never collide
        h = hashlib.md5(f"{abs_path}:{start_s:.3f}:{end_s:.3f}".encode()).hexdigest()[:10]
        name = f"{Path(abs_path).stem}_{h}.jpg"
        out = pm.previews_dir / name
        out.parent.mkdir(parents=True, exist_ok=True)
        # Re-use if already exists (idempotent)
        if out.exists() and out.stat().st_size > 200:
            return str(pm.rel(out))
        cap = cv2.VideoCapture(abs_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        cv2.imwrite(str(out), frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return str(pm.rel(out)) if out.exists() else None
    except Exception:
        return None


def _build_music_fragments(rel_path, bpm_result, beats, energy, sections) -> List[dict]:
    import hashlib
    p = Path(rel_path)
    h = ""
    if p.exists():
        with open(rel_path, "rb") as f:
            h = hashlib.md5(f.read(65536)).hexdigest()
    frags = []
    for sec in sections:
        frags.append({
            "audio_rel_path":  rel_path,
            "audio_hash":      h,
            "start_s":         sec.get("start_s", 0.0),
            "end_s":           sec.get("end_s", 0.0),
            "duration_s":      sec.get("end_s", 0.0) - sec.get("start_s", 0.0),
            "fragment_type":   sec.get("type", "unknown"),
            "section_label":   sec.get("label"),
            "bpm":             bpm_result.get("bpm"),
            "beat_times":      beats.get("times", []),
            "beat_clarity":    beats.get("clarity", 0.0),
            "energy_score":    sec.get("energy_score", 0.0),
            "rhythm_score":    sec.get("rhythm_score", 0.0),
            "montage_score":   sec.get("montage_score", 0.0),
            "status":          sec.get("status", "optional"),
        })
    return frags


def _file_hash(abs_path: str) -> str:
    import hashlib
    h = hashlib.md5()
    with open(abs_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
