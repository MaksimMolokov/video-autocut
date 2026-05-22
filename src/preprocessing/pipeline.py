"""Preprocessing pipeline: orchestrates scene detection, quality analysis, scoring."""

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.wmv', '.flv', '.webm'}


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

    cpu_count = max(1, (os.cpu_count() or 2) // 2)
    logger.info(
        f'[Pipeline] Analyzing {len(pending)}/{len(videos)} files '
        f'using {cpu_count} workers'
    )

    previews_dir = str(Path(project_dir) / '.videoeditor' / 'previews')

    with ProcessPoolExecutor(max_workers=cpu_count) as executor:
        futures = {
            executor.submit(_analyze_one_video, str(v), previews_dir): v
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

    good = db.count_fragments(min_quality=0.55)
    total = db.count_fragments(min_quality=0.0)
    logger.info(f'[Pipeline] Done. {good} good / {total} total fragments.')
    return good


def _analyze_one_video(video_path: str, previews_dir: str) -> dict:
    """
    Worker function — runs in a separate process.
    All imports are local to ensure picklability.
    """
    import subprocess
    from src.preprocessing.scene_detector import SceneDetector
    from src.preprocessing.quality_analyzer import QualityAnalyzer
    from src.preprocessing.clip_scorer import ClipScorer
    from src.preprocessing.preview_generator import PreviewGenerator

    detector = SceneDetector()
    analyzer = QualityAnalyzer()
    scorer = ClipScorer()
    previewer = PreviewGenerator(previews_dir)

    # Get video metadata
    duration_s, fps, resolution = _get_video_meta(video_path)

    scenes = detector.split(video_path)
    fragments = []
    frag_counter = abs(hash(video_path)) % 10_000_000  # unique-ish base id for filenames

    for i, scene in enumerate(scenes):
        try:
            metrics = analyzer.analyze(video_path, scene)
            if metrics.is_rejected:
                continue

            scores = scorer.score(metrics)

            frag_id = frag_counter + i
            thumb_path = previewer.generate_thumbnail(
                video_path, scene.start_s, scene.end_s, frag_id
            )

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
                'is_duplicate': False,
                'quality_score': scores.quality_score,
                'cinematic_score': scores.cinematic_score,
                'action_score': scores.action_score,
                'social_score': scores.social_score,
                'premium_score': scores.premium_score,
                'travel_score': scores.travel_score,
                'thumbnail_path': thumb_path or None,
            })
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f'[Pipeline] Scene {i} failed in {video_path}: {e}'
            )
            continue

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
