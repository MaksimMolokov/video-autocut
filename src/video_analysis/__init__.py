"""
Video analysis module for extracting features from video clips
"""

from .feature_extractor import ClipFeatures, VideoFeatureExtractor
from .candidate_builder import CandidateClip, CandidateClipBuilder

__all__ = [
    'ClipFeatures',
    'VideoFeatureExtractor',
    'CandidateClip',
    'CandidateClipBuilder',
]
