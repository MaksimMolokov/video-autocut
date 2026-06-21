"""Preprocessing pipeline: orchestrates scene detection, quality analysis, scoring."""

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.wmv', '.flv', '.webm',
                    '.mts', '.m2ts', '.mxf', '.3gp', '.ts', '.vob', '.dv'}


def list_video_files(project_dir: str) -> List[Path]:
    root = Path(project_dir)
    videos = []
    for ext in VIDEO_EXTENSIONS:
        videos.extend(root.glob(f'*{ext}'))
        videos.extend(root.glob(f'*{ext.upper()}'))
    # Exclude files inside .videoeditor
    videos = [v for v in videos if '.videoeditor' not in str(v)]
    return sorted(set(videos))


def analyze_project(
    project_dir: str,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    force_reanalyze: bool = False,
    enable_clip_tagging: bool = False,
) -> int:
    """
    Analyze all video files in project_dir.
    Returns the number of good fragments found.
    """
    from src.storage.analysis_db import AnalysisDB

    db = AnalysisDB(project_dir)

    if force_reanalyze:
        db.reset_all()

    videos = list_video_files(project_dir)
    if not videos:
        logger.info(f'[Pipeline] No video files found in {project_dir}')
        return 0

    # Register new files
    for v in videos:
        db.save_source_file(str(v))

    pending = [v for v in videos if not db.is_analyzed(str(v))]

    if not pending:
        n = db.count_fragments(min_quality=0.0)
        logger.info(f'[Pipeline] All files cached. {n} total fragments.')
        return db.count_fragments(min_quality=0.55)

    # CLIP tagging loads a 600 MB model per worker — use 1 worker when enabled
    cpu_count = max(1, (os.cpu_count() or 2) // 2)
    if enable_clip_tagging:
        cpu_count = 1
    logger.info(
        f'[Pipeline] Analyzing {len(pending)}/{len(videos)} files '
        f'using {cpu_count} workers'
        + (' (CLIP tagging ON)' if enable_clip_tagging else '')
    )

    previews_dir = str(Path(project_dir) / '.videoeditor' / 'previews')

    with ProcessPoolExecutor(max_workers=cpu_count) as executor:
        futures = {
            executor.submit(
                _analyze_one_video, str(v), previews_dir,
                True, True, True, enable_clip_tagging,
            ): v
            for v in pending
        }
        completed = 0
        for future in as_completed(futures):
            video_path = futures[future]
            try:
                result = future.result()
                source_id = db.save_source_file(str(video_path))
                db.save_fragments(source_id, result['fragments'])
                db.mark_analyzed(
                    str(video_path),
                    duration_s=result.get('duration_s'),
                    fps=result.get('fps'),
                    resolution=result.get('resolution'),
                )
                n_frags = len(result['fragments'])
                logger.info(
                    f'[Pipeline] {video_path.name}: {n_frags} fragments'
                )
            except Exception as e:
                logger.error(f'[Pipeline] Failed: {video_path}: {e}')
                db.mark_error(str(video_path), str(e))

            completed += 1
            if progress_callback:
                progress_callback(video_path.name, completed, len(pending))

    total = db.count_fragments(min_quality=0.0)
    good = db.count_fragments(min_quality=0.55)

    # Adaptive threshold: if very few good fragments, lower the bar
    if good < 15 and total > 0:
        relaxed = db.count_fragments(min_quality=0.35)
        if relaxed > good:
            logger.warning(
                f'[Pipeline] Only {good} fragments at q>=0.55, '
                f'{relaxed} available at q>=0.35 (adaptive mode)'
            )

    logger.info(f'[Pipeline] Done. {good} good / {total} total fragments.')
    return good


def _analyze_one_video(
    video_path: str,
    previews_dir: str,
    enable_content_analysis: bool = True,
    enable_dedup: bool = True,
    enable_video_preview: bool = True,
    enable_clip_tagging: bool = False,
) -> dict:
    """
    Worker function — runs in a separate process.
    All imports are local to ensure picklability.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    from src.preprocessing.scene_detector import SceneDetector
    from src.preprocessing.quality_analyzer import QualityAnalyzer
    from src.preprocessing.clip_scorer import ClipScorer
    from src.preprocessing.preview_generator import PreviewGenerator
    from src.preprocessing.duplicate_detector import DuplicateDetector, compute_phash

    # Try to import content analyzer (optional, may be unavailable)
    content_analyzer = None
    if enable_content_analysis:
        try:
            from src.preprocessing.content_analyzer import ContentAnalyzer
            content_analyzer = ContentAnalyzer(n_frames=3)
        except Exception as e:
            _log.warning(f'[Pipeline] ContentAnalyzer unavailable: {e}')

    # CLIP tagger (Level 4, optional)
    clip_tagger = None
    if enable_clip_tagging:
        try:
            from src.preprocessing.clip_tagger import ClipTagger
            clip_tagger = ClipTagger()
        except Exception as e:
            _log.warning(f'[Pipeline] ClipTagger unavailable: {e}')

    detector = SceneDetector()
    analyzer = QualityAnalyzer()
    scorer = ClipScorer()
    previewer = PreviewGenerator(previews_dir)
    dedup = DuplicateDetector() if enable_dedup else None

    # Pre-flight check: verify OpenCV can open the file.
    # If it can't, raise immediately so mark_error() is called instead of
    # mark_analyzed() with 0 fragments (which would cache a broken state forever).
    import cv2 as _cv2
    _test_cap = _cv2.VideoCapture(video_path)
    if not _test_cap.isOpened():
        _test_cap.release()
        raise RuntimeError(
            f"OpenCV не может открыть видеофайл. "
            f"Возможно, кодек не поддерживается. "
            f"Попробуйте конвертировать в H.264 MP4."
        )
    _test_cap.release()

    duration_s, fps, resolution = _get_video_meta(video_path)

    scenes = detector.split(video_path)
    fragments = []
    frag_counter = abs(hash(video_path)) % 10_000_000

    # Track quality-rejected scenes separately for diagnostics
    quality_rejected_count = 0

    for i, scene in enumerate(scenes):
        try:
            metrics = analyzer.analyze(video_path, scene)

            # Hard-skip only truly unreadable / corrupt frames.
            # Quality-filtered frames (blurry, unstable, dark) are kept so that
            # the UMS scorer can rank them — discarding them here caused "no fragments"
            # errors on DJI/drone/action footage where motion blur is normal.
            _unreadable = metrics.reject_reason in ('no_frames', 'black_frame', 'corrupt')
            if _unreadable:
                quality_rejected_count += 1
                continue

            if metrics.is_rejected:
                quality_rejected_count += 1
                _log.debug(
                    f'[Pipeline] Scene {i} quality-filtered ({metrics.reject_reason})'
                    f' — kept with reduced score'
                )

            # Content analysis (Level 2)
            content = None
            if content_analyzer is not None:
                try:
                    content = content_analyzer.analyze(video_path, scene)
                except Exception as e:
                    _log.debug(f'[Pipeline] Content analysis scene {i}: {e}')

            # Semantic tag (Level 4) — runs before scorer so it can influence scores
            scene_tag = None
            if clip_tagger is not None:
                try:
                    scene_tag = clip_tagger.tag_scene(
                        video_path, scene.start_s, scene.end_s
                    )
                except Exception as e:
                    _log.debug(f'[Pipeline] CLIP tag scene {i}: {e}')

            scores = scorer.score(metrics, content, scene_tag=scene_tag)

            frag_id = frag_counter + i
            thumb_path = previewer.generate_thumbnail(
                video_path, scene.start_s, scene.end_s, frag_id
            )
            # Video preview for scenes >= 2s (Level 3)
            preview_path = None
            if enable_video_preview and scene.duration_s >= 2.0:
                try:
                    preview_path = previewer.generate_video_preview(
                        video_path, scene.start_s, scene.end_s, frag_id, max_duration=3.0
                    )
                except Exception as e:
                    _log.debug(f'[Pipeline] Video preview scene {i}: {e}')

            # Compute phash for dedup
            phash = None
            if dedup is not None:
                try:
                    phash = dedup.extract_hash(video_path, scene.start_s, scene.end_s)
                except Exception:
                    pass

            fragments.append({
                'start_s': scene.start_s,
                'end_s': scene.end_s,
                'duration_s': scene.duration_s,
                'sharpness': metrics.sharpness,
                'brightness': metrics.brightness,
                'contrast': metrics.contrast,
                'motion': metrics.motion,
                'stability': metrics.stability,
                'action': metrics.action,
                'calm': metrics.calm,
                'colorfulness': metrics.colorfulness,
                'complexity': metrics.complexity,
                'camera_motion_type': metrics.camera_motion_type,
                'composition_score': metrics.composition_score,
                'temporal_coherence': metrics.temporal_coherence,
                'saliency_score': metrics.saliency_score,
                # Content fields (None if content analyzer unavailable)
                'has_face': int(content.has_face) if content else None,
                'has_person': int(content.has_person) if content else None,
                'has_subject': int(content.has_subject) if content else None,
                'scene_type': content.scene_type if content else None,
                'scene_tag': scene_tag,
                'crop_9_16': content.crop_9_16 if content else None,
                # Scores
                'is_duplicate': False,
                'quality_score': scores.quality_score,
                'cinematic_score': scores.cinematic_score,
                'action_score': scores.action_score,
                'social_score': scores.social_score,
                'premium_score': scores.premium_score,
                'travel_score': scores.travel_score,
                'thumbnail_path': thumb_path or None,
                'preview_path': preview_path or None,
                'phash': phash,
            })
        except Exception as e:
            _log.warning(f'[Pipeline] Scene {i} failed in {video_path}: {e}')
            continue

    # Deduplication pass
    if dedup is not None and len(fragments) > 1:
        fragments, pairs = dedup.filter_fragments(fragments)
        if pairs:
            _log.info(f'[Pipeline] {video_path}: {len(pairs)} duplicate pairs found')

    # Log quality-rejection summary
    if quality_rejected_count > 0:
        _log.info(
            f'[Pipeline] {Path(video_path).name}: '
            f'{quality_rejected_count}/{len(scenes)} scenes had quality issues '
            f'(kept with reduced scores)'
        )

    # Only raise if frames literally could not be decoded (no fragments AND scenes exist
    # AND every scene had an unreadable-frame error, not a quality filter).
    # Previously this raised for ALL quality rejections, which caused mark_error() to
    # silently block re-analysis of perfectly valid footage (DJI, action, drone).
    if not fragments and scenes:
        raise RuntimeError(
            f"Видеофайл содержит {len(scenes)} обнаруженных сцен, "
            f"но все кадры неудалось декодировать. "
            f"Возможные причины: повреждённый файл, неподдерживаемый кодек "
            f"(попробуйте конвертировать в H.264 MP4)."
        )

    # Remove internal phash field before returning (not stored in DB)
    for f in fragments:
        f.pop('phash', None)

    return {
        'fragments': fragments,
        'duration_s': duration_s,
        'fps': fps,
        'resolution': resolution,
    }


def _get_video_meta(video_path: str):
    try:
        import subprocess, json
        result = subprocess.run(
            [
                'ffprobe', '-v', 'error', '-print_format', 'json',
                '-show_streams', '-show_format', video_path,
            ],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        duration_s = float(data.get('format', {}).get('duration', 0))
        fps = None
        resolution = None
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                w = stream.get('width', 0)
                h = stream.get('height', 0)
                resolution = f'{w}x{h}'
                fr_str = stream.get('r_frame_rate', '30/1')
                try:
                    num, den = fr_str.split('/')
                    fps = float(num) / float(den)
                except Exception:
                    fps = 30.0
                break
        return duration_s, fps, resolution
    except Exception:
        return None, None, None
