"""
Adaptive granularity system for C4 model generation.

Provides intelligent granularity selection, component grouping,
and view filtering based on repository characteristics.
"""

from .analyzer import RepositoryMetrics, RepositoryAnalyzer
from .engine import GranularityLevel, GranularityDecisionEngine
from .grouping import ComponentGroupingManager, GroupingStrategy
from .filtering import ViewFilteringEngine, FilterLevel

__all__ = [
    "RepositoryMetrics",
    "RepositoryAnalyzer", 
    "GranularityLevel",
    "GranularityDecisionEngine",
    "ComponentGroupingManager",
    "GroupingStrategy",
    "ViewFilteringEngine",
    "FilterLevel"
]
