"""
candidate_filter — apply a MontagePool to a list of CandidateClip-like objects.

Rules:
  - forbidden_fragment_ids : hard blacklist by _fragment_id attribute
  - forbidden_ranges        : hard blacklist by (source_path, start, end) overlap
                              used for SegmentSelector candidates without _fragment_id
  - priority_fragment_ids   : score boost + is_must_use for approved clips
"""
from __future__ import annotations

import copy
import logging
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)


def apply_montage_pool(candidates: List[Any], pool: Any) -> List[Any]:
    """
    Filter and boost *candidates* according to *pool* (a MontagePool instance).

    Returns a new list; input list is not mutated.
    When pool.is_active is False the original list is returned as-is.
    """
    if not pool.is_active:
        return candidates

    result: List[Any] = []
    forbidden_ids: set = pool.forbidden_fragment_ids
    forbidden_ranges: List[Tuple[str, float, float]] = pool.forbidden_ranges
    priority_ids: set = pool.priority_fragment_ids
    boost: float = pool.score_boost

    n_removed_id = 0
    n_removed_range = 0
    n_boosted = 0

    for c in candidates:
        fid = getattr(c, '_fragment_id', None)

        # ── Hard blacklist by fragment ID ─────────────────────────────────
        if fid is not None and fid in forbidden_ids:
            n_removed_id += 1
            continue

        # ── Hard blacklist by time-range overlap ──────────────────────────
        if forbidden_ranges and _overlaps_any_forbidden(c, forbidden_ranges):
            n_removed_range += 1
            continue

        # ── Priority boost ────────────────────────────────────────────────
        if fid is not None and fid in priority_ids:
            c = _apply_boost(c, boost)
            n_boosted += 1

        # ── Priority boost by time-range (manual segments) ───────────────
        if fid is None and pool.priority_ranges and _overlaps_any_forbidden(c, pool.priority_ranges):
            c = _apply_boost(c, boost)
            n_boosted += 1

        result.append(c)

    if n_removed_id or n_removed_range or n_boosted:
        logger.info(
            '[CandidateFilter] removed=%d(id)+%d(range) boosted=%d  in=%d out=%d',
            n_removed_id, n_removed_range, n_boosted, len(candidates), len(result),
        )

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _overlaps_any_forbidden(candidate: Any, forbidden_ranges: List[Tuple[str, float, float]]) -> bool:
    src   = str(getattr(candidate, 'source_path', '') or '')
    start = float(getattr(candidate, 'start',         0))
    end   = float(getattr(candidate, 'end',           0))
    for r_src, r_start, r_end in forbidden_ranges:
        if r_src != src:
            continue
        # Half-open intervals: overlap when start < r_end AND end > r_start
        if start < r_end and end > r_start:
            return True
    return False


def _apply_boost(candidate: Any, boost: float) -> Any:
    """Return a shallow copy of *candidate* with boosted final_score and is_must_use=True."""
    c = copy.copy(candidate)
    old_score = float(getattr(c, 'final_score', 0.5) or 0.5)
    c.final_score = min(1.0, old_score + boost)
    c.is_must_use = True
    return c
