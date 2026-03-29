"""
Batho Core - Code analysis and indexing library.

This package provides the core functionality for analyzing code repositories,
building dependency graphs, and generating contextual information for LLMs.
"""

__version__ = "0.1.0"

# Re-export main functions from batho.py for easier importing
try:
    from ..batho import build_parser, main
    __all__ = ["build_parser", "main"]
except ImportError:
    # If batho.py is not available, define what we can
    __all__ = []
