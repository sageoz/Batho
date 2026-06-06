"""
context/languages — Language-specific ASTExtractor subclasses.

Each module exposes a single extractor class that implements
``_query_source()`` with the tree-sitter SCM query for its language.
The capture naming convention used throughout is the one defined by the
``ASTExtractor`` base class:

  @def.<type>.name          — identifier node of a definition
  @def.<type>.params        — parameter list node
  @def.<type>.return_type   — return type annotation node
  @def.<type>.visibility    — visibility modifier node
  @def.<type>.docstring     — docstring / comment node
  @def.<type>.bases         — base class list (Python)
  @def.<type>.implements    — interface list (Java / TS)
  @def.<type>.extends       — superclass (Java)
  @def.<type>.trait         — trait name (Rust impl)
  @def.<type>.receiver      — method receiver (Go)
  @def.<type>.type          — field / variable type
  @ref.call                 — function call reference
  @ref.import.module        — import reference

Use :mod:`batho.modules.extraction.submodules.parser_factory.registry` to resolve a file
extension to the correct extractor instance at runtime.

Language Detection:
Use :mod:`batho.modules.extraction.submodules.parser_factory.detector` for intelligent
language detection beyond file extensions.
"""

from .detector import (
    DetectionResult,
    LanguageDetector,
    default_detector,
    detect_language,
    detect_language_with_fallback,
    permissive_detector,
    strict_detector,
)
from .factory import QUERY_REGISTRY, ConfigurableExtractor, create_extractor
from .factory import get_extractor as get_factory_extractor
from .factory import list_supported_languages, register_extractor
from .registry import (
    REGISTRY,
    discover_and_register_all,
    get_extensions_for_language,
    get_extractor,
    get_extractor_for_language,
    get_language_for_extension,
    is_language_available,
)

__all__ = [
    # Registry
    "REGISTRY",
    "discover_and_register_all",
    "get_extractor",
    "get_extractor_for_language",
    "get_extensions_for_language",
    "get_language_for_extension",
    "is_language_available",
    # Detector
    "DetectionResult",
    "LanguageDetector",
    "default_detector",
    "permissive_detector",
    "strict_detector",
    "detect_language",
    "detect_language_with_fallback",
    # Factory
    "ConfigurableExtractor",
    "create_extractor",
    "get_factory_extractor",
    "register_extractor",
    "list_supported_languages",
    "QUERY_REGISTRY",
]
