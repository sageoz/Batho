"""
context/languages/python.py — Python extractor (minimal shim).

The actual query is defined in _queries.py for single-source-of-truth.
PythonExtractor is now a thin subclass of ConfigurableExtractor.
"""

from __future__ import annotations

from typing import Any

from .factory import ConfigurableExtractor
from ._queries import PYTHON_QUERY


class PythonExtractor(ConfigurableExtractor):
    """Tree-sitter based extractor for Python source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("python", PYTHON_QUERY, parsing_config)
