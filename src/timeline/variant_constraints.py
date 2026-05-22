"""
variant_constraints.py — Structural diversity engine for multi-preview generation.

Architecture:
  1. CandidatePools   — organises raw clips into role-specific pools
  2. VariantConstraints — per-variant structural rules
  3. VariantMemory    — cross-variant state (used openings, endings, scene sets)
  4. TimelineFingerprint — immutable record of a built timeline
  5. build_variant_constraints() — factory driven by memory + material level
  6. build_candidate_pools()    — partition candidates by role score
  7. analyze_timeline_difference() — comprehensive structural comparison
  8. get_pair_threshold()       — per-pair similarity ceiling
  9. scene_id()                 — stable segment identity key

Root causes this module fixes:
  - All variants share the same sorted candidate pool → identical intro/body/outro
  - IntroOutroScorer always picks the same top-1 clip (no exclusions)
  - _fill_body always sorts by score with no seed → same clips
  - No memory of which opening/ending has already been used
  - compare_timelines() used only Jaccard, missing opening/ending/sequence checks
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ── Pairwise similarity thresholds ───────────────────────────────────────────
PAIR_THRESHOLDS: Dict[Tuple[str, str], float] = {
    ('A', 'B'): 0.75,
    ('A', 'C'): 0.75,
    ('A', 'D'): 0.65,
    ('B', 'C'): 0.75,
    ('B', 'D'): 0.70,
    ('C', 'D'): 0.70,
}

MAX_REGEN_ATTEMPTS = 5

# Material-level buckets (number of usable candidate clips)
MATERIAL_RICH   = 12
MATERIAL_MEDIUM = 6


def get_pair_threshold(va: str, vb: str) -> float:
    """Return the allowed maximum overall_similarity for a pair of variants."""
    key = (min(va, vb), max(va, vb))
    return PAIR_THRESHOLDS.get(key, 0.75)


# ── Stable scene identity ─────────────────────────────────────────────────────

def scene_id(seg_or_cand) -> str:
    """
    Stable 12-char hex ID for a clip, based on source_path + rounded start time.
    Works for both CandidateClip and SelectedSegment objects.
    """
    path  = getattr(seg_or_cand, 'source_path', '')
    start = round(getattr(seg_or_cand, 'start', 0.0), 1)
    end   = round(getattr(seg_or_cand, 'end',   0.0), 1)
    raw   = f"{path}|{start:.1f}|{end:.1f}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ── Candidate pools ───────────────────────────────────────────────────────────

@dataclass
class CandidatePools:
    """Candidates partitioned into role-specific pools."""
    all_candidates:          List = field(default_factory=list)
    opening_candidates:      List = field(default_factory=list)
    ending_candidates:       List = field(default_factory=list)
    high_motion_candidates:  List = field(default_factory=list)
    aesthetic_candidates:    List = field(default_factory=list)
    alternative_candidates:  List = field(default_factory=list)   # good but not in top-N baseline
    backup_candidates:       List = field(default_factory=list)   # barely acceptable

    @property
    def total_usable(self) -> int:
        return len(self.all_candidates)

    @property
    def material_level(self) -> str:
        n = self.total_usable
        if n >= MATERIAL_RICH:
            return 'rich'
        if n >= MATERIAL_MEDIUM:
            return 'medium'
        return 'limited'

    def opening_ids(self) -> Set[str]:
        return {scene_id(c) for c in self.opening_candidates}

    def ending_ids(self) -> Set[str]:
        return {scene_id(c) for c in self.ending_candidates}


def build_candidate_pools(all_candidates: list) -> CandidatePools:
    """
    Partition a raw candidate list into role-specific pools.
    Feature thresholds are chosen to be permissive so small pools still get populated.
    """
    if not all_candidates:
        return CandidatePools()

    sorted_all = sorted(
        all_candidates, key=lambda c: getattr(c, 'final_score', 0.0), reverse=True
    )
    n     = len(sorted_all)
    top_n = max(1, n // 2)

    opening_cands    = []
    ending_cands     = []
    motion_cands     = []
    aesthetic_cands  = []

    for cand in sorted_all:
        feats = getattr(cand, 'features', None)
        if feats is None:
            # No features: still eligible for pools via backup
            continue

        sharpness   = getattr(feats, 'sharpness_score',   0.5)
        brightness  = getattr(feats, 'brightness_score',  0.5)
        motion      = getattr(feats, 'motion_score',       0.5)
        action      = getattr(feats, 'action_score',       0.5)
        stability   = getattr(feats, 'camera_stability_score', 0.5)
        complexity  = getattr(feats, 'visual_complexity_score', 0.5)
        composition = getattr(feats, 'technical_quality_score', 0.5)

        # Opening: quality + visible + not too chaotic
        opening_score = (
            sharpness   * 0.30
            + brightness  * 0.20
            + stability   * 0.20
            + motion      * 0.15
            + composition * 0.15
        )
        if opening_score > 0.35:
            opening_cands.append(cand)

        # Ending: stable + visually clean + low action (natural close)
        ending_score = (
            sharpness          * 0.35
            + brightness       * 0.20
            + stability        * 0.25
            + (1.0 - action)   * 0.10
            + composition      * 0.10
        )
        if ending_score > 0.35:
            ending_cands.append(cand)

        # High motion
        if motion > 0.45 or action > 0.45:
            motion_cands.append(cand)

        # Aesthetic: sharp + stable + not overly active
        if sharpness > 0.45 and stability > 0.40:
            aesthetic_cands.append(cand)

    # Sort role pools by final_score descending
    def _sort(lst):
        return sorted(lst, key=lambda c: getattr(c, 'final_score', 0.0), reverse=True)

    # Alternative = good quality clips NOT in top-half baseline
    alternative_cands = [
        c for c in sorted_all[top_n:]
        if getattr(c, 'final_score', 0.0) > 0.25
    ]

    # Backup = anything above minimum threshold (for very limited material)
    backup_cands = [
        c for c in sorted_all
        if getattr(c, 'final_score', 0.0) > 0.10
    ]

    return CandidatePools(
        all_candidates          = sorted_all,
        opening_candidates      = _sort(opening_cands),
        ending_candidates       = _sort(ending_cands),
        high_motion_candidates  = _sort(motion_cands),
        aesthetic_candidates    = _sort(aesthetic_cands),
        alternative_candidates  = alternative_cands,
        backup_candidates       = backup_cands,
    )


# ── Variant constraints ───────────────────────────────────────────────────────

@dataclass
class VariantConstraints:
    """Structural rules for one variant's timeline build."""
    variant_id:               str
    variant_name:             str
    opening_strategy:         str    # which pool to draw intro from
    ending_strategy:          str    # which pool to draw outro from
    scene_selection_strategy: str    # body selection logic
    segment_duration_policy:  str    # 'normal' | 'shorter' | 'longer' | 'mixed'
    scene_overlap_limit:      Optional[float]   # max Jaccard with any prior variant
    sequence_similarity_limit: Optional[float]
    entry_point_strategy:     str    # 'best_moment' | 'energetic_offset' | 'clean_offset' | 'alt_offset'
    transition_policy:        str
    beat_alignment_policy:    str
    diversity_pressure:       float  # 0.0 = none, 1.0 = maximum
    excluded_opening_ids:     Set[str] = field(default_factory=set)
    excluded_ending_ids:      Set[str] = field(default_factory=set)
    soft_excluded_ids:        Set[str] = field(default_factory=set)   # score penalty
    hard_excluded_ids:        Set[str] = field(default_factory=set)   # must not appear
    seed_offset:              int  = 0
    limited_material_warning: bool = False


# ── Variant memory ────────────────────────────────────────────────────────────

@dataclass
class VariantMemory:
    """
    Cross-variant state shared between successive variant builds.
    Stored in st.session_state['_variant_memory'] so it persists across reruns.
    """
    used_opening_ids:          List[str]           = field(default_factory=list)
    used_ending_ids:           List[str]           = field(default_factory=list)
    used_scene_ids_by_variant: Dict[str, Set[str]] = field(default_factory=dict)
    fingerprints:              Dict[str, 'TimelineFingerprint'] = field(default_factory=dict)

    def all_used_ids(self) -> Set[str]:
        out: Set[str] = set()
        for ids in self.used_scene_ids_by_variant.values():
            out |= ids
        return out

    def register(
        self,
        variant_id: str,
        fingerprint: 'TimelineFingerprint',
    ) -> None:
        self.fingerprints[variant_id] = fingerprint
        if fingerprint.first_scene_id:
            self.used_opening_ids.append(fingerprint.first_scene_id)
        if fingerprint.last_scene_id:
            self.used_ending_ids.append(fingerprint.last_scene_id)
        self.used_scene_ids_by_variant[variant_id] = set(fingerprint.scene_ids)


# ── Timeline fingerprint ──────────────────────────────────────────────────────

@dataclass
class TimelineFingerprint:
    """Immutable record of a built timeline for comparison, logging, and export."""
    variant_id:           str
    seed:                 int
    scene_ids:            List[str]
    scene_time_ranges:    List[Tuple[str, float, float]]   # (source_path, start, end)
    first_scene_id:       str
    last_scene_id:        str
    segment_durations:    List[float]
    transition_types:     List[str]
    avg_segment_duration: float
    total_duration:       float
    segment_count:        int
    profile_id:           str
    material_level:       str
    warnings:             List[str] = field(default_factory=list)

    @classmethod
    def from_segments(
        cls,
        segments: list,
        variant_id: str,
        seed: int,
        profile_id: str = '',
        material_level: str = 'rich',
        warnings: Optional[List[str]] = None,
    ) -> 'TimelineFingerprint':
        if not segments:
            return cls(
                variant_id=variant_id, seed=seed,
                scene_ids=[], scene_time_ranges=[],
                first_scene_id='', last_scene_id='',
                segment_durations=[], transition_types=[],
                avg_segment_duration=0.0, total_duration=0.0,
                segment_count=0, profile_id=profile_id,
                material_level=material_level,
                warnings=warnings or [],
            )

        sids      = [scene_id(s) for s in segments]
        ranges    = [
            (getattr(s, 'source_path', ''),
             getattr(s, 'start', 0.0),
             getattr(s, 'end',   0.0))
            for s in segments
        ]
        durations = [getattr(s, 'duration', 0.0) for s in segments]
        trs       = [getattr(s, 'start_transition', '') or '' for s in segments]
        total     = sum(durations)
        avg       = total / max(len(durations), 1)

        return cls(
            variant_id=variant_id,
            seed=seed,
            scene_ids=sids,
            scene_time_ranges=ranges,
            first_scene_id=sids[0]  if sids else '',
            last_scene_id=sids[-1]  if sids else '',
            segment_durations=durations,
            transition_types=trs,
            avg_segment_duration=round(avg, 2),
            total_duration=round(total, 2),
            segment_count=len(segments),
            profile_id=profile_id,
            material_level=material_level,
            warnings=warnings or [],
        )

    def to_log_dict(self) -> dict:
        return {
            'variant_id':           self.variant_id,
            'seed':                 self.seed,
            'first_scene_id':       self.first_scene_id,
            'last_scene_id':        self.last_scene_id,
            'segment_count':        self.segment_count,
            'avg_segment_duration': self.avg_segment_duration,
            'total_duration':       self.total_duration,
            'material_level':       self.material_level,
            'warnings':             self.warnings,
        }


# ── Constraint factory ────────────────────────────────────────────────────────

def build_variant_constraints(
    variant_id: str,
    memory: VariantMemory,
    pools: CandidatePools,
) -> VariantConstraints:
    """
    Build structural constraints for one variant, given cross-variant memory.
    Constraints become progressively stricter for B/C/D.
    """
    level  = pools.material_level
    limited = (level == 'limited')

    used_openings = set(memory.used_opening_ids)
    used_endings  = set(memory.used_ending_ids)
    all_used      = memory.all_used_ids()

    # Determine if we can actually force different opening/ending
    opening_ids       = pools.opening_ids()
    available_opens   = opening_ids - used_openings
    ending_ids_pool   = pools.ending_ids()
    available_ends    = ending_ids_pool - used_endings

    if variant_id == 'A':
        return VariantConstraints(
            variant_id='A',
            variant_name='Сбалансированный вариант',
            opening_strategy='best_overall',
            ending_strategy='best_overall',
            scene_selection_strategy='balanced_top_quality',
            segment_duration_policy='normal',
            scene_overlap_limit=None,
            sequence_similarity_limit=None,
            entry_point_strategy='best_moment',
            transition_policy='default',
            beat_alignment_policy='standard',
            diversity_pressure=0.0,
            seed_offset=101,
            limited_material_warning=limited,
        )

    elif variant_id == 'B':
        # Exclude A's opening/ending if alternatives exist.
        # Soft-exclude ALL previously used clips regardless of material level —
        # previously this was gated on level == 'rich', meaning limited/medium
        # material got zero body-clip diversification and produced identical timelines.
        excl_opens = used_openings if available_opens else set()
        excl_ends  = used_endings  if available_ends  else set()
        soft_excl  = all_used      # always penalise; pressure governs strength
        return VariantConstraints(
            variant_id='B',
            variant_name='Другое вступление, быстрее нарезка',
            opening_strategy='high_motion_not_prev',
            ending_strategy='beat_end_not_prev',
            scene_selection_strategy='motion_and_energy',
            segment_duration_policy='shorter',
            scene_overlap_limit=0.60,
            sequence_similarity_limit=0.70,
            entry_point_strategy='energetic_offset',
            transition_policy='fast_cuts',
            beat_alignment_policy='strong_beats',
            diversity_pressure=0.55,
            excluded_opening_ids=excl_opens,
            excluded_ending_ids=excl_ends,
            soft_excluded_ids=soft_excl,
            seed_offset=202,
            limited_material_warning=limited,
        )

    elif variant_id == 'C':
        excl_opens = used_openings if available_opens else set()
        excl_ends  = used_endings  if available_ends  else set()
        soft_excl  = all_used      # always penalise
        return VariantConstraints(
            variant_id='C',
            variant_name='Плавнее, длиннее кадры, cinematic',
            opening_strategy='aesthetic_stable_not_prev',
            ending_strategy='smooth_visual_end_not_prev',
            scene_selection_strategy='aesthetic_stable',
            segment_duration_policy='longer',
            scene_overlap_limit=0.65,
            sequence_similarity_limit=0.65,
            entry_point_strategy='clean_offset',
            transition_policy='slow_dissolves',
            beat_alignment_policy='soft_beats',
            diversity_pressure=0.70,
            excluded_opening_ids=excl_opens,
            excluded_ending_ids=excl_ends,
            soft_excluded_ids=soft_excl,
            seed_offset=303,
            limited_material_warning=limited,
        )

    else:  # D
        excl_opens = used_openings if available_opens else set()
        excl_ends  = used_endings  if available_ends  else set()
        soft_excl  = all_used      # always penalise
        # Hard-exclude previously used clips when enough alternatives remain.
        # Previously gated on level == 'rich', missing medium-material case.
        n_remaining = len(pools.all_candidates) - len(all_used)
        hard_excl = all_used if (level != 'limited' and n_remaining >= 6) else set()
        return VariantConstraints(
            variant_id='D',
            variant_name='Альтернативные кадры и другая концовка',
            opening_strategy='alternative_not_prev',
            ending_strategy='alternative_not_prev',
            scene_selection_strategy='least_used_high_quality',
            segment_duration_policy='mixed',
            scene_overlap_limit=0.50,
            sequence_similarity_limit=0.55,
            entry_point_strategy='alt_offset',
            transition_policy='mixed',
            beat_alignment_policy='flexible',
            diversity_pressure=0.90,
            excluded_opening_ids=excl_opens,
            excluded_ending_ids=excl_ends,
            soft_excluded_ids=soft_excl,
            hard_excluded_ids=hard_excl,
            seed_offset=404,
            limited_material_warning=limited,
        )


# ── Candidate reranking for body selection ────────────────────────────────────

def apply_variant_scoring(
    candidates: list,
    constraints: VariantConstraints,
    base_seed: int,
) -> list:
    """
    Return a NEW list of candidates re-scored and re-ordered for this variant.
    Does NOT mutate the original objects' final_score.
    """
    import copy

    strategy = constraints.scene_selection_strategy
    dur_policy = constraints.segment_duration_policy
    pressure = constraints.diversity_pressure
    soft_excl = constraints.soft_excluded_ids
    hard_excl = constraints.hard_excluded_ids

    # Build scored tuples: (adjusted_score, candidate)
    scored = []
    for cand in candidates:
        sid = scene_id(cand)

        # Hard exclude
        if sid in hard_excl:
            continue

        base = getattr(cand, 'final_score', 0.5)
        feats = getattr(cand, 'features', None)

        bonus = 0.0
        if feats:
            motion    = getattr(feats, 'motion_score',    0.5)
            sharpness = getattr(feats, 'sharpness_score', 0.5)
            action    = getattr(feats, 'action_score',    0.5)

            if strategy == 'motion_and_energy':
                bonus += motion * 0.20 + action * 0.10
            elif strategy == 'aesthetic_stable':
                bonus += sharpness * 0.20 - motion * 0.05
            elif strategy == 'least_used_high_quality':
                bonus += sharpness * 0.10

        # Soft exclude penalty — strong enough to actually prefer alternatives.
        # Old formula (pressure * 0.45, max 0.35) was too weak: at B's 0.55 pressure
        # that was only 24%, leaving clip scores [0.9→0.684] still above alternatives
        # at [0.4-0.5], so body selection stayed identical across variants.
        if sid in soft_excl:
            penalty = min(0.72, pressure * 0.80)
            base = base * (1.0 - penalty)

        # Duration policy bonus/penalty
        dur = getattr(cand, 'duration', 3.0)
        if dur_policy == 'shorter' and dur < 3.0:
            bonus += 0.08
        elif dur_policy == 'shorter' and dur > 5.0:
            bonus -= 0.06
        elif dur_policy == 'longer' and dur > 4.5:
            bonus += 0.08
        elif dur_policy == 'longer' and dur < 2.0:
            bonus -= 0.06

        adjusted = min(1.0, max(0.0, base + bonus))
        scored.append((adjusted, cand))

    # Sort by adjusted score descending, then shuffle near-ties deterministically.
    # Band widened to ±0.08 so that clips with continuous float scores (rarely
    # exact ties) still get randomised by variant seed, producing different ordering.
    scored.sort(key=lambda x: x[0], reverse=True)

    rng = random.Random(base_seed + constraints.seed_offset)
    result = []
    i = 0
    while i < len(scored):
        j = i + 1
        while j < len(scored) and abs(scored[j][0] - scored[i][0]) < 0.08:
            j += 1
        group = [c for _, c in scored[i:j]]
        rng.shuffle(group)
        result.extend(group)
        i = j

    return result


def select_opening_candidate(
    pools: CandidatePools,
    constraints: VariantConstraints,
    base_seed: int,
) -> Optional[object]:
    """
    Pick the best opening candidate satisfying exclusion constraints.
    Falls back through pools if no suitable candidate found.
    """
    strategy = constraints.opening_strategy
    excluded = constraints.excluded_opening_ids

    def _first_non_excluded(pool: list) -> Optional[object]:
        for cand in pool:
            if scene_id(cand) not in excluded:
                return cand
        return None

    # Strategy determines which pool to prefer
    if 'motion' in strategy or 'energetic' in strategy:
        preferred = pools.high_motion_candidates
    elif 'aesthetic' in strategy or 'cinematic' in strategy:
        preferred = pools.aesthetic_candidates
    elif 'alternative' in strategy:
        preferred = pools.alternative_candidates
    else:
        preferred = pools.opening_candidates

    cand = _first_non_excluded(preferred) or _first_non_excluded(pools.opening_candidates)

    # Entry point variation: if excluded and no alternative found, try offset
    if cand is None:
        cand = _first_non_excluded(pools.all_candidates)

    return cand


def select_ending_candidate(
    pools: CandidatePools,
    constraints: VariantConstraints,
    excluded_intro_id: str,
) -> Optional[object]:
    """Pick the best ending candidate satisfying exclusion constraints."""
    excluded = constraints.excluded_ending_ids | {excluded_intro_id}

    def _first_non_excluded(pool: list) -> Optional[object]:
        for cand in pool:
            if scene_id(cand) not in excluded:
                return cand
        return None

    strategy = constraints.ending_strategy
    if 'smooth' in strategy or 'aesthetic' in strategy or 'cinematic' in strategy:
        preferred = pools.aesthetic_candidates
    elif 'alternative' in strategy:
        preferred = pools.alternative_candidates
    elif 'beat_end' in strategy:
        preferred = pools.ending_candidates
    else:
        preferred = pools.ending_candidates

    cand = _first_non_excluded(preferred) or _first_non_excluded(pools.ending_candidates)
    if cand is None:
        cand = _first_non_excluded(pools.all_candidates)
    return cand


# ── Timeline difference analysis ──────────────────────────────────────────────

def analyze_timeline_difference(
    fp_a: TimelineFingerprint,
    fp_b: TimelineFingerprint,
) -> dict:
    """
    Comprehensive structural comparison of two timeline fingerprints.

    Returns dict with:
      scene_set_overlap_ratio, scene_sequence_similarity, time_overlap_ratio,
      same_opening, same_ending, avg_segment_duration_delta, segment_count_delta,
      transition_similarity, overall_similarity
    """
    empty = {
        'scene_set_overlap_ratio':   0.0,
        'scene_sequence_similarity': 0.0,
        'time_overlap_ratio':        0.0,
        'same_opening':              False,
        'same_ending':               False,
        'avg_segment_duration_delta': 0.0,
        'segment_count_delta':        0,
        'transition_similarity':      0.0,
        'overall_similarity':         0.0,
    }
    if not fp_a.scene_ids or not fp_b.scene_ids:
        return empty

    # 1. Scene set overlap (Jaccard)
    set_a   = set(fp_a.scene_ids)
    set_b   = set(fp_b.scene_ids)
    union   = len(set_a | set_b)
    inter   = len(set_a & set_b)
    set_ovl = inter / max(union, 1)

    # 2. Sequence similarity (LCS / max-length)
    lcs     = _lcs_length(fp_a.scene_ids, fp_b.scene_ids)
    seq_sim = lcs / max(len(fp_a.scene_ids), len(fp_b.scene_ids), 1)

    # 3. Time-range overlap (exact (path, start, end) tuples)
    ranges_a = {(p, round(s, 1), round(e, 1)) for p, s, e in fp_a.scene_time_ranges}
    ranges_b = {(p, round(s, 1), round(e, 1)) for p, s, e in fp_b.scene_time_ranges}
    r_union  = len(ranges_a | ranges_b)
    r_inter  = len(ranges_a & ranges_b)
    time_ovl = r_inter / max(r_union, 1)

    # 4. Opening / ending match
    same_open = (fp_a.first_scene_id == fp_b.first_scene_id
                 and bool(fp_a.first_scene_id))
    same_end  = (fp_a.last_scene_id  == fp_b.last_scene_id
                 and bool(fp_a.last_scene_id))

    # 5. Duration delta
    dur_delta = abs(fp_a.avg_segment_duration - fp_b.avg_segment_duration)

    # 6. Segment count delta
    cnt_delta = abs(fp_a.segment_count - fp_b.segment_count)

    # 7. Transition token overlap (both-empty → identical, not missing)
    trans_a  = set(t for t in fp_a.transition_types if t)
    trans_b  = set(t for t in fp_b.transition_types if t)
    if not trans_a and not trans_b:
        trans_s = 1.0
    else:
        t_union = len(trans_a | trans_b)
        t_inter = len(trans_a & trans_b)
        trans_s = t_inter / max(t_union, 1)

    # 8. Weighted overall similarity
    overall = (
        set_ovl * 0.40
        + seq_sim * 0.25
        + time_ovl * 0.20
        + (0.05 if same_open else 0.0)
        + (0.05 if same_end  else 0.0)
        + trans_s * 0.05
    )

    return {
        'scene_set_overlap_ratio':    round(set_ovl,  4),
        'scene_sequence_similarity':  round(seq_sim,  4),
        'time_overlap_ratio':         round(time_ovl, 4),
        'same_opening':               same_open,
        'same_ending':                same_end,
        'avg_segment_duration_delta': round(dur_delta, 2),
        'segment_count_delta':        cnt_delta,
        'transition_similarity':      round(trans_s,  4),
        'overall_similarity':         round(overall,  4),
    }


def _lcs_length(a: list, b: list) -> int:
    """O(n·m) longest common subsequence length, memory-efficient (2-row DP)."""
    if not a or not b:
        return 0
    n, m = len(a), len(b)
    prev = [0] * (m + 1)
    curr = [0] * (m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            curr[j] = (prev[j - 1] + 1
                       if a[i - 1] == b[j - 1]
                       else max(prev[j], curr[j - 1]))
        prev, curr = curr, [0] * (m + 1)
    return prev[m]


def build_similarity_log(memory: VariantMemory) -> str:
    """Format a similarity-matrix log line from all built fingerprints."""
    fps   = memory.fingerprints
    pairs = []
    letters = sorted(fps)
    for i, la in enumerate(letters):
        for lb in letters[i + 1:]:
            diff = analyze_timeline_difference(fps[la], fps[lb])
            pairs.append(f"{la}vs{lb}={diff['overall_similarity']:.3f}")
    return '  '.join(pairs) if pairs else '(no pairs yet)'


def check_minimum_requirements(
    new_fp: TimelineFingerprint,
    memory: VariantMemory,
    pools: CandidatePools,
) -> List[str]:
    """
    Return list of requirement violation strings (empty = OK).
    Checks: same_opening, same_ending for B/C/D; pair thresholds.
    """
    violations = []
    vid = new_fp.variant_id
    if vid == 'A':
        return violations

    for prev_id, prev_fp in memory.fingerprints.items():
        diff = analyze_timeline_difference(prev_fp, new_fp)
        threshold = get_pair_threshold(prev_id, vid)
        if diff['overall_similarity'] > threshold:
            violations.append(
                f"similarity {vid}vs{prev_id}={diff['overall_similarity']:.3f}"
                f" > threshold {threshold}"
            )
        # Opening check
        if diff['same_opening'] and vid in ('B', 'C', 'D'):
            if len(pools.opening_candidates) > 1:
                violations.append(
                    f"same_opening as {prev_id} ({new_fp.first_scene_id[:8]})"
                )
        # Ending check
        if diff['same_ending'] and vid in ('B', 'C', 'D'):
            if len(pools.ending_candidates) > 1:
                violations.append(
                    f"same_ending as {prev_id} ({new_fp.last_scene_id[:8]})"
                )

    return violations
