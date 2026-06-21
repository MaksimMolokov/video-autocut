"""One-click mode: automatically select best style from material + music analysis."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def auto_select_style(
    project_dir: str,
    music_path: Optional[str] = None,
) -> str:
    """
    Analyse preprocessed fragments and music to pick the best fitting style.
    Returns a preset_id string ('f2', 'f3', ...) or 'f2' as default.
    """
    material_style = _style_from_material(project_dir)
    music_style = _style_from_music(music_path) if music_path else None

    logger.info(
        f'[AutoStyle] material={material_style} music={music_style}'
    )

    # Music recommendation takes priority when confident
    if music_style and music_style != material_style:
        logger.info(f'[AutoStyle] Music overrides material → {music_style}')
        return music_style

    return material_style or 'f2'


def _style_from_material(project_dir: str) -> Optional[str]:
    """Pick style based on aggregated fragment metrics."""
    try:
        from src.storage.analysis_db import AnalysisDB
        from src.preprocessing.clip_library import FragmentLibrary

        db = AnalysisDB(project_dir)
        lib = FragmentLibrary(db)
        frags = lib.get_fragments_for_ui(min_quality=0.0, limit=300)

        if not frags:
            return None

        n = len(frags)
        avg_motion    = sum(f.motion    for f in frags) / n
        avg_stability = sum(f.stability for f in frags) / n
        avg_brightness = sum(f.brightness for f in frags) / n
        face_ratio    = sum(1 for f in frags if f.has_face) / n

        # Score each style
        scores = {
            'f4': avg_motion * 2.0 + (1 - avg_stability) * 1.5,
            'f3': avg_motion * 1.5 + face_ratio * 1.0,
            'f2': avg_stability * 1.5 + (1 - avg_motion) * 0.8,
            'f5': avg_stability * 2.0 + avg_brightness * 0.5,
            'f6': avg_brightness * 1.2 + avg_stability * 0.8,
        }

        best = max(scores, key=lambda k: scores[k])
        logger.info(
            f'[AutoStyle] Material scores: '
            + ', '.join(f'{k}={v:.2f}' for k, v in sorted(scores.items(), key=lambda x: -x[1]))
        )
        return best
    except Exception as e:
        logger.warning(f'[AutoStyle] Material analysis failed: {e}')
        return None


def _style_from_music(music_path: str) -> Optional[str]:
    """Pick style based on music energy/tempo."""
    try:
        from src.preprocessing.music_style_advisor import get_top_suggestions
        suggestions = get_top_suggestions(music_path, n=1)
        if suggestions and suggestions[0].confidence >= 0.45:
            return suggestions[0].style_id
    except Exception as e:
        logger.warning(f'[AutoStyle] Music analysis failed: {e}')
    return None
