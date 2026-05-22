"""Duplicate detection via perceptual hash (Level 2)."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

HAMMING_THRESHOLD = 8  # hashes closer than this → duplicates


@dataclass
class DuplicatePair:
    fragment_idx_a: int
    fragment_idx_b: int
    hamming_distance: int
    keep_idx: int   # index of the fragment to keep (higher quality_score)


def compute_phash(frame: np.ndarray) -> Optional[str]:
    """Compute perceptual hash of a frame. Returns hex string or None on error."""
    try:
        import imagehash
        from PIL import Image
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        return str(imagehash.phash(pil))
    except Exception as e:
        logger.debug(f'[DuplicateDetector] phash error: {e}')
        return None


def hamming_distance(h1: str, h2: str) -> int:
    try:
        import imagehash
        return int(imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2))
    except Exception:
        return 999


def are_duplicates(h1: str, h2: str, threshold: int = HAMMING_THRESHOLD) -> bool:
    return hamming_distance(h1, h2) < threshold


class DuplicateDetector:
    """
    Detect near-duplicate fragments using perceptual hash.
    Works on a list of fragment dicts (as produced by _analyze_one_video).
    """

    def __init__(self, threshold: int = HAMMING_THRESHOLD):
        self.threshold = threshold

    def extract_hash(self, video_path: str, start_s: float, end_s: float) -> Optional[str]:
        """Sample middle frame of a scene and compute its phash."""
        mid_s = (start_s + end_s) / 2.0
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_POS_MSEC, mid_s * 1000)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return None
        return compute_phash(frame)

    def find_duplicates(
        self,
        fragments: List[dict],
    ) -> List[DuplicatePair]:
        """
        Compare all pairs. Returns list of duplicate pairs.
        Each pair indicates which fragment to drop (lower quality_score).
        """
        hashes = [f.get('phash') for f in fragments]
        pairs: List[DuplicatePair] = []

        for i in range(len(fragments)):
            if hashes[i] is None:
                continue
            for j in range(i + 1, len(fragments)):
                if hashes[j] is None:
                    continue
                dist = hamming_distance(hashes[i], hashes[j])
                if dist < self.threshold:
                    q_i = fragments[i].get('quality_score', 0.0) or 0.0
                    q_j = fragments[j].get('quality_score', 0.0) or 0.0
                    keep = i if q_i >= q_j else j
                    pairs.append(DuplicatePair(
                        fragment_idx_a=i,
                        fragment_idx_b=j,
                        hamming_distance=dist,
                        keep_idx=keep,
                    ))
        return pairs

    def filter_fragments(
        self,
        fragments: List[dict],
    ) -> Tuple[List[dict], List[DuplicatePair]]:
        """
        Mark duplicates in-place and return (filtered_list, duplicate_pairs).
        The fragment with lower quality_score in each pair is marked is_duplicate=True.
        """
        pairs = self.find_duplicates(fragments)

        drop_indices = set()
        for pair in pairs:
            drop_idx = (
                pair.fragment_idx_b
                if pair.keep_idx == pair.fragment_idx_a
                else pair.fragment_idx_a
            )
            drop_indices.add(drop_idx)

        for i, frag in enumerate(fragments):
            if i in drop_indices:
                frag['is_duplicate'] = True

        if drop_indices:
            logger.info(
                f'[DuplicateDetector] Marked {len(drop_indices)} duplicates '
                f'from {len(pairs)} pairs'
            )

        return fragments, pairs

    def is_temporal_duplicate(
        self,
        f1: dict, f2: dict,
        overlap_threshold: float = 0.7,
    ) -> bool:
        """Check if two fragments from the same source overlap significantly."""
        if f1.get('source_path') != f2.get('source_path'):
            return False
        overlap_start = max(f1['start_s'], f2['start_s'])
        overlap_end = min(f1['end_s'], f2['end_s'])
        if overlap_end <= overlap_start:
            return False
        overlap = overlap_end - overlap_start
        min_dur = min(f1['duration_s'], f2['duration_s'])
        return (overlap / min_dur) > overlap_threshold if min_dur > 0 else False
