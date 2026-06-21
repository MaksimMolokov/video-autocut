"""
Step2SelectionAdapter — bridges Step 2 curation results into the render pipeline.

Converts session_state prep data (prep_rejected_fids, prep_approved_ids) into a
MontagePool that candidate_filter.apply_montage_pool() can use to:
  - Hard-remove forbidden fragments from ALL candidates (including SegmentSelector ones)
  - Boost final_score + set is_must_use for approved/priority fragments
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class MontagePool:
    """Resolved pool produced by Step2SelectionAdapter."""

    # Fragment IDs the user explicitly rejected — must never appear in any variant
    forbidden_fragment_ids: Set[int] = field(default_factory=set)

    # (source_path, start_s, end_s) for forbidden fragments — used to filter
    # SegmentSelector candidates that don't carry a _fragment_id
    forbidden_ranges: List[Tuple[str, float, float]] = field(default_factory=list)

    # Fragment IDs the user approved — receive score boost + is_must_use flag
    priority_fragment_ids: Set[int] = field(default_factory=set)

    # (source_path, start_s, end_s) for manual required/recommended ranges
    priority_ranges: List[Tuple[str, float, float]] = field(default_factory=list)

    # How much to add to final_score for priority clips (capped at 1.0)
    score_boost: float = 0.30

    # False → pass-through mode (legacy / Step 2 skipped)
    is_active: bool = False


class Step2SelectionAdapter:
    """Builds a MontagePool from session_state prep data."""

    @staticmethod
    def build_pool(
        prep_mode: Optional[str],
        prep_rejected_fids: Optional[Set[int]],
        prep_approved_ids: Optional[Set[int]],
        db_dirs: List[str],
    ) -> MontagePool:
        """
        Build a MontagePool from Step 2 session_state values.

        Args:
            prep_mode:           st.session_state.prep_mode ('done'|'running'|None|'skipped')
            prep_rejected_fids:  st.session_state.prep_rejected_fids (set of DB fragment IDs)
            prep_approved_ids:   st.session_state.prep_approved_ids  (set of DB fragment IDs)
            db_dirs:             list of project dirs that may have an analysis DB

        Returns:
            MontagePool with is_active=False when Step 2 is not 'done'.
        """
        if prep_mode != 'done':
            return MontagePool(is_active=False)

        forbidden_fids: Set[int] = set(prep_rejected_fids or set())
        priority_fids: Set[int] = set(prep_approved_ids or set())

        # Resolve time-ranges for forbidden fragment IDs so we can filter
        # SegmentSelector candidates that don't carry _fragment_id
        forbidden_ranges: List[Tuple[str, float, float]] = []
        if forbidden_fids:
            for db_dir in db_dirs:
                try:
                    from src.storage.analysis_db import AnalysisDB
                    db = AnalysisDB(db_dir)
                    rows = db.get_fragments_by_ids(forbidden_fids)
                    for row in rows:
                        forbidden_ranges.append(
                            (str(row['source_path']), float(row['start_s']), float(row['end_s']))
                        )
                    db.close()
                except Exception as exc:
                    logger.debug('[Step2Adapter] Could not look up forbidden ranges in %s: %s', db_dir, exc)

        is_active = bool(forbidden_fids or priority_fids)
        return MontagePool(
            forbidden_fragment_ids=forbidden_fids,
            forbidden_ranges=forbidden_ranges,
            priority_fragment_ids=priority_fids,
            score_boost=0.30,
            is_active=is_active,
        )
