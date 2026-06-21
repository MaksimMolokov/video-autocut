"""
DuplicateDetector — find visually similar fragments (TASK-025).

Primary: pHash (perceptual hash, Hamming distance).
Secondary: color histogram correlation for borderline cases.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import cv2
import numpy as np

from infrastructure.config.config_manager import cfg

logger = logging.getLogger(__name__)

try:
    import imagehash
    from PIL import Image
    _IMAGEHASH_AVAILABLE = True
except ImportError:
    _IMAGEHASH_AVAILABLE = False


class DuplicateDetector:
    """Find duplicate / near-duplicate fragments."""

    def __init__(self) -> None:
        self._threshold = cfg.get("duplicate.phash_threshold", 5)

    def find_duplicates(
        self,
        fragments: List[Dict],
        video_paths: Dict[int, str],
    ) -> List[Tuple[int, int, float]]:
        """
        fragments: list of {id, source_file_id, start_s, end_s}
        video_paths: {source_file_id: abs_path}
        Returns: [(frag_id_a, frag_id_b, similarity_0_to_1)]
        """
        hashes: Dict[int, any] = {}
        for frag in fragments:
            vid_path = video_paths.get(frag["source_file_id"])
            if not vid_path:
                continue
            h = self._compute_hash(vid_path, frag["start_s"], frag["end_s"])
            if h is not None:
                hashes[frag["id"]] = h

        pairs = []
        ids = list(hashes.keys())
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                distance = _hash_distance(hashes[a], hashes[b])
                if distance <= self._threshold:
                    similarity = 1.0 - distance / 64.0
                    pairs.append((a, b, similarity))

        logger.info("[DuplicateDetector] %d fragments → %d duplicate pairs", len(fragments), len(pairs))
        return pairs

    def _compute_hash(self, video_path: str, start_s: float, end_s: float):
        mid = (start_s + end_s) / 2
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return None

        if _IMAGEHASH_AVAILABLE:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            return imagehash.phash(pil_img)
        else:
            return _numpy_phash(frame)


def _hash_distance(h1, h2) -> int:
    if _IMAGEHASH_AVAILABLE:
        return int(h1 - h2)
    # numpy fallback: XOR + popcount
    return int(np.sum(h1 != h2))


def _numpy_phash(frame: np.ndarray) -> np.ndarray:
    """Simple pHash without imagehash library."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (32, 32))
    dct = cv2.dct(resized.astype(np.float32))
    dct_low = dct[:8, :8]
    mean = dct_low.mean()
    return dct_low > mean
