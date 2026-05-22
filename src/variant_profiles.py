"""
VariantProfile — controls how each A/B/C/D preview variant differs in clip selection.

Each profile steers three independent axes of variation:
  1. Seed            → different random draws from the same candidate pool
  2. Score weights   → re-rank candidates toward motion-heavy or aesthetic clips
  3. Pool strategy   → variant D penalises clips already chosen by A/B/C

compare_timelines()      — Jaccard similarity on (path, start, end) tuples
calculate_timeline_stats() — avg duration, total duration, energy score
get_variant_ui_description() — one-line UI label with optional % diff from A
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional

SIMILARITY_THRESHOLD = 0.85   # above this → variants are too similar
MAX_REGEN_ATTEMPTS   = 3      # diversity re-roll attempts per variant


# ── Profile definition ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VariantProfile:
    letter: str                    # 'A' | 'B' | 'C' | 'D'
    label: str                     # short English tag used in logs
    description: str               # Russian UI label
    seed_offset: int               # added to base seed 42
    clip_duration_multiplier: float  # scales _budget_per_source (shorter → more clips)
    motion_weight_delta: float     # added to each candidate's score × motion_score
    aesthetic_weight_delta: float  # added to each candidate's score × sharpness_score
    beat_sync_strength: str        # 'none' | 'soft' | 'medium' | 'strong'
    transition_profile: str        # 'default' | 'fast_cuts' | 'slow_dissolves' | 'mixed'
    scene_selection_strategy: str  # 'balanced' | 'motion_heavy' | 'aesthetic' | 'alternative'
    diversity_penalty: float       # fraction to subtract from score of clips reused from A/B/C
    energy_label: str              # 'balanced' | 'high' | 'low' | 'varied'


VARIANT_PROFILES: Dict[str, VariantProfile] = {
    'A': VariantProfile(
        letter='A',
        label='Balanced',
        description='Сбалансированный',
        seed_offset=101,
        clip_duration_multiplier=1.0,
        motion_weight_delta=0.0,
        aesthetic_weight_delta=0.0,
        beat_sync_strength='medium',
        transition_profile='default',
        scene_selection_strategy='balanced',
        diversity_penalty=0.0,
        energy_label='balanced',
    ),
    'B': VariantProfile(
        letter='B',
        label='Dynamic',
        description='Динамичный монтаж',
        seed_offset=202,
        clip_duration_multiplier=0.75,
        motion_weight_delta=0.15,
        aesthetic_weight_delta=-0.05,
        beat_sync_strength='strong',
        transition_profile='fast_cuts',
        scene_selection_strategy='motion_heavy',
        diversity_penalty=0.0,
        energy_label='high',
    ),
    'C': VariantProfile(
        letter='C',
        label='Cinematic',
        description='Кинематографичный',
        seed_offset=303,
        clip_duration_multiplier=1.25,
        motion_weight_delta=-0.05,
        aesthetic_weight_delta=0.20,
        beat_sync_strength='soft',
        transition_profile='slow_dissolves',
        scene_selection_strategy='aesthetic',
        diversity_penalty=0.0,
        energy_label='low',
    ),
    'D': VariantProfile(
        letter='D',
        label='Alternative',
        description='Альтернативный подбор',
        seed_offset=404,
        clip_duration_multiplier=1.0,
        motion_weight_delta=0.0,
        aesthetic_weight_delta=0.0,
        beat_sync_strength='medium',
        transition_profile='mixed',
        scene_selection_strategy='alternative',
        diversity_penalty=0.5,
        energy_label='varied',
    ),
}


# ── Similarity ────────────────────────────────────────────────────────────────

def compare_timelines(segments_a: list, segments_b: list) -> float:
    """
    Jaccard similarity of two timelines based on (source_path, start, end) tuples.
    Returns 0.0 (completely different) … 1.0 (identical).
    """
    if not segments_a or not segments_b:
        return 0.0

    def _key(s):
        return (
            getattr(s, 'source_path', ''),
            round(getattr(s, 'start', 0.0), 1),
            round(getattr(s, 'end', 0.0), 1),
        )

    keys_a = {_key(s) for s in segments_a}
    keys_b = {_key(s) for s in segments_b}
    union = len(keys_a | keys_b)
    if union == 0:
        return 1.0
    return len(keys_a & keys_b) / union


def similarity_matrix(variants: Dict[str, list]) -> Dict[str, float]:
    """
    Compute pairwise similarities for a dict of {letter: segments}.
    Returns {'{X}vs{Y}': score, ...}.
    """
    letters = sorted(variants)
    result: Dict[str, float] = {}
    for i, la in enumerate(letters):
        for lb in letters[i + 1:]:
            score = compare_timelines(variants[la], variants[lb])
            result[f"{la}vs{lb}"] = round(score, 4)
    return result


# ── Stats ─────────────────────────────────────────────────────────────────────

def calculate_timeline_stats(segments: list) -> dict:
    """Return descriptive stats for a list of SelectedSegment objects."""
    if not segments:
        return {'n_clips': 0, 'avg_duration': 0.0, 'total_duration': 0.0, 'energy': 0.0}

    durations = [getattr(s, 'duration', 0.0) for s in segments]
    avg_dur   = sum(durations) / len(durations)
    total     = sum(durations)

    features_list = [getattr(s, '_features', None) for s in segments]
    features_list = [f for f in features_list if f is not None]

    if features_list:
        energy = sum(
            getattr(f, 'action_score', 0.0) * 0.6 + getattr(f, 'motion_score', 0.0) * 0.4
            for f in features_list
        ) / len(features_list)
    else:
        energy = 0.5

    return {
        'n_clips':        len(segments),
        'avg_duration':   round(avg_dur, 2),
        'total_duration': round(total, 2),
        'energy':         round(energy, 3),
    }


# ── UI label ──────────────────────────────────────────────────────────────────

def get_variant_ui_description(
    profile: VariantProfile,
    stats: dict,
    ref_stats: Optional[dict] = None,
) -> str:
    """One-line description used in the variant mini-card."""
    avg_dur = stats.get('avg_duration', 0.0)
    energy  = stats.get('energy', 0.5)

    if energy > 0.65:
        energy_str = "🔥 Высокая"
    elif energy < 0.35:
        energy_str = "💧 Низкая"
    else:
        energy_str = "⚖️ Средняя"

    parts = [
        profile.description,
        f"кл. {avg_dur:.1f}с",
        f"энергия {energy_str}",
    ]

    if ref_stats and ref_stats.get('total_duration', 0) > 0:
        ref_total = ref_stats['total_duration']
        my_total  = stats.get('total_duration', 0.0)
        pct = abs(my_total - ref_total) / max(ref_total, 0.01) * 100
        parts.append(f"≠A {pct:.0f}%")

    return "  ·  ".join(parts)


# ── Candidate pool manipulation ───────────────────────────────────────────────

def apply_profile_weights(candidates: list, profile: VariantProfile) -> list:
    """
    Re-score candidates in-place according to the profile's weight deltas.
    Returns the same list (mutated).
    """
    if profile.motion_weight_delta == 0.0 and profile.aesthetic_weight_delta == 0.0:
        return candidates

    mdelta = profile.motion_weight_delta
    adelta = profile.aesthetic_weight_delta

    for cand in candidates:
        feats = getattr(cand, 'features', None)
        if feats is None:
            continue
        motion    = getattr(feats, 'motion_score',    0.0)
        sharpness = getattr(feats, 'sharpness_score', 0.0)
        old_score = getattr(cand, 'final_score', 0.5)
        cand.final_score = old_score + motion * mdelta + sharpness * adelta

    return candidates


def apply_alternative_penalty(
    candidates: list,
    existing_segments: list,
    diversity_penalty: float,
) -> tuple:
    """
    Penalise candidates whose (source_path, start) appears in existing_segments.
    Returns (mutated candidates, penalised_count).
    """
    if diversity_penalty <= 0.0 or not existing_segments:
        return candidates, 0

    used_keys: set = set()
    for seg in existing_segments:
        used_keys.add((
            getattr(seg, 'source_path', ''),
            round(getattr(seg, 'start', 0.0), 1),
        ))

    penalised = 0
    for cand in candidates:
        key = (
            getattr(cand, 'source_path', ''),
            round(getattr(cand, 'start', 0.0), 1),
        )
        if key in used_keys:
            cand.final_score = getattr(cand, 'final_score', 0.5) * (1.0 - diversity_penalty)
            penalised += 1

    return candidates, penalised


def shuffle_candidates_for_regen(candidates: list, regen_attempt: int, base_seed: int) -> list:
    """Deterministically shuffle candidates for a regen attempt."""
    rng = random.Random(base_seed + regen_attempt * 1337)
    shuffled = list(candidates)
    rng.shuffle(shuffled)
    return shuffled
