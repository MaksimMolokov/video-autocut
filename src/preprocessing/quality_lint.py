"""Quality lint: check material compatibility with chosen style before render."""

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

# Style-specific requirements
_STYLE_REQUIREMENTS = {
    'f2': {
        'name': 'F2 Cinematic Velocity',
        'min_stability': 0.45,
        'min_sharpness': 0.35,
        'max_motion': 0.75,
        'min_good_ratio': 0.20,
    },
    'f3': {
        'name': 'F3 Urban Pulse',
        'min_motion': 0.15,
        'min_good_ratio': 0.15,
    },
    'f4': {
        'name': 'F4 Impact Sport',
        'min_motion': 0.20,
        'min_good_ratio': 0.10,
    },
    'f5': {
        'name': 'F5 Premium Brand',
        'min_stability': 0.55,
        'min_sharpness': 0.45,
        'min_brightness': 0.20,
        'min_good_ratio': 0.25,
    },
    'f6': {
        'name': 'F6 Dream Travel',
        'min_brightness': 0.15,
        'min_good_ratio': 0.15,
    },
}


@dataclass
class LintWarning:
    code: str
    message: str
    suggestion: str
    severity: str  # 'warning' | 'info'


def check_style_compatibility(
    preset_id: str,
    fragments,  # List[FragmentData] or list of rows with quality metrics
    total_fragments: int = 0,
) -> List[LintWarning]:
    """
    Check if analyzed fragments are compatible with the chosen style.
    Returns list of warnings (empty = all good).
    """
    if not fragments:
        return []

    req = _STYLE_REQUIREMENTS.get(preset_id)
    if req is None:
        return []

    warnings: List[LintWarning] = []
    n = len(fragments)
    if n == 0:
        return []

    def _attr(f, name, default=0.0):
        if hasattr(f, name):
            return getattr(f, name) or default
        if hasattr(f, '__getitem__'):
            try:
                return f[name] or default
            except (KeyError, TypeError):
                return default
        return default

    stabilities = [_attr(f, 'stability') for f in fragments]
    sharpnesses = [_attr(f, 'sharpness') for f in fragments]
    motions = [_attr(f, 'motion') for f in fragments]
    brightnesses = [_attr(f, 'brightness') for f in fragments]
    qualities = [_attr(f, 'quality_score') for f in fragments]

    avg_stability = sum(stabilities) / n
    avg_sharpness = sum(sharpnesses) / n
    avg_motion = sum(motions) / n
    avg_brightness = sum(brightnesses) / n
    avg_quality = sum(qualities) / n

    style_name = req.get('name', preset_id.upper())

    # Check stability requirement
    min_stab = req.get('min_stability')
    if min_stab is not None:
        ok_count = sum(1 for s in stabilities if s >= min_stab)
        ok_ratio = ok_count / n
        if ok_ratio < req.get('min_good_ratio', 0.20):
            warnings.append(LintWarning(
                code='LOW_STABILITY',
                message=(
                    f'Только {ok_count}/{n} фрагментов имеют stability ≥ {min_stab:.2f} '
                    f'(нужно для {style_name}). Средняя: {avg_stability:.2f}'
                ),
                suggestion='Попробуйте F4 (Impact Sport) или F3 (Urban Pulse) — они допускают тряску',
                severity='warning',
            ))

    # Check sharpness requirement
    min_sharp = req.get('min_sharpness')
    if min_sharp is not None and avg_sharpness < min_sharp:
        warnings.append(LintWarning(
            code='LOW_SHARPNESS',
            message=(
                f'Средняя резкость {avg_sharpness:.2f} ниже рекомендованной '
                f'{min_sharp:.2f} для {style_name}'
            ),
            suggestion='Часть видео может быть расфокусирована или снята при плохом освещении',
            severity='warning',
        ))

    # Check motion requirement (for action styles)
    min_mot = req.get('min_motion')
    if min_mot is not None:
        ok_count = sum(1 for m in motions if m >= min_mot)
        ok_ratio = ok_count / n
        if ok_ratio < 0.30:
            warnings.append(LintWarning(
                code='LOW_MOTION',
                message=(
                    f'Слишком мало динамичных фрагментов для {style_name}: '
                    f'{ok_count}/{n} с motion ≥ {min_mot:.2f}'
                ),
                suggestion='Стиль рассчитан на видео с движением. Попробуйте F2 (Cinematic) или F5 (Premium)',
                severity='warning',
            ))

    # Check brightness
    min_bright = req.get('min_brightness')
    if min_bright is not None and avg_brightness < min_bright:
        warnings.append(LintWarning(
            code='LOW_BRIGHTNESS',
            message=(
                f'Среднее освещение {avg_brightness:.2f} ниже нормы '
                f'{min_bright:.2f} для {style_name}'
            ),
            suggestion='Много тёмных фрагментов — итоговый ролик может выглядеть мрачно',
            severity='info',
        ))

    # Overall quality warning
    if avg_quality < 0.35:
        warnings.append(LintWarning(
            code='LOW_OVERALL_QUALITY',
            message=(
                f'Средний quality_score материала: {avg_quality:.2f}. '
                f'Рекомендуется > 0.50 для хорошего результата.'
            ),
            suggestion='Снимите видео при лучшем освещении или используйте более стабильную камеру',
            severity='warning',
        ))

    return warnings


def format_lint_warnings(warnings: List[LintWarning]) -> str:
    """Human-readable summary of warnings."""
    if not warnings:
        return ''
    lines = []
    for w in warnings:
        icon = '⚠️' if w.severity == 'warning' else 'ℹ️'
        lines.append(f'{icon} {w.message}')
        lines.append(f'   → {w.suggestion}')
    return '\n'.join(lines)
