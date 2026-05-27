"""
Batho Core - Code analysis and indexing library.

This package provides the core functionality for analyzing code repositories,
building dependency graphs, and generating contextual information for LLMs.
"""

__version__ = "1.1.0"

from batho.core.config import get_config_cached, reload_config
from batho.modules.compression.bsg_map import BSGMap

# Import and re-export public APIs from submodules
from batho.modules.graph.builder.codegraph import CodeGraphIndexer, InMemoryGraph

from batho.modules.query.engine.query import QueryService
from batho.utils.logging import get_logger

__all__ = [
    # Core indexing
    "CodeGraphIndexer",
    "InMemoryGraph",
    # Query service
    "QueryService",
    # BSG rendering
    "BSGMap",
    # Config
    "get_config_cached",
    "reload_config",
    # Logging
    "get_logger",
]
