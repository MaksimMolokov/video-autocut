"""
Clip selection module for choosing video fragments based on preset strategies
"""

from .strategy import ClipSelectionStrategy
from .strategy_registry import StrategyRegistry
from .clip_scorer import ClipScorer
from .diversity_selector import DiversitySelector
from .ordering_engine import OrderingEngine
from .render_history import RenderHistory, RenderRecord

__all__ = [
    'ClipSelectionStrategy',
    'StrategyRegistry',
    'ClipScorer',
    'DiversitySelector',
    'OrderingEngine',
    'RenderHistory',
    'RenderRecord',
]
