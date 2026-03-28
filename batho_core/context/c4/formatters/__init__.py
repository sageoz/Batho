"""
Multi-format output system for C4 models.

Provides various output formats including PlantUML, Mermaid, D2, and interactive HTML.
"""

from .base import BaseFormatter, FormatCapabilities, ViewType
from .registry import FormatRegistry, get_format_registry

# Import built-in formatters
from .plantuml import PlantUMLFormatter
from .mermaid import MermaidFormatter
from .interactive import InteractiveHTMLFormatter
from .d2 import D2Formatter

__all__ = [
    "BaseFormatter",
    "FormatCapabilities", 
    "ViewType",
    "FormatRegistry",
    "get_format_registry",
    "PlantUMLFormatter",
    "MermaidFormatter",
    "InteractiveHTMLFormatter",
    "D2Formatter"
]
