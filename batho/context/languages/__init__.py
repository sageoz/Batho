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
  @ref.import.module               — import reference

Use :mod:`batho.context.languages.registry` to resolve a file
extension to the correct extractor instance at runtime.

Language Detection:
Use :mod:`batho.context.languages.detector` for intelligent
language detection beyond file extensions.
"""

# NEW: Additional programming language extractors
from .bash import BashExtractor
from .c import CExtractor
from .cpp import CppExtractor
from .css import CSSExtractor
from .dart import DartExtractor
from .detector import (
    DetectionResult,
    LanguageDetector,
    default_detector,
    detect_language,
    detect_language_with_fallback,
    permissive_detector,
    strict_detector,
)
from .erlang import ErlangExtractor

# Factory module for creating extractors without subclassing
from .factory import QUERY_REGISTRY, ConfigurableExtractor, create_extractor
from .factory import get_extractor as get_factory_extractor
from .factory import list_supported_languages, register_extractor
from .go import GoExtractor
from .hack import HackExtractor
from .haskell import HaskellExtractor
from .hcl import HCLExtractor
from .html import HTMLExtractor
from .java import JavaExtractor
from .javascript import JavaScriptExtractor

# NEW: Markup/Config Language Extractors
from .json import JSONExtractor
from .julia import JuliaExtractor
from .kotlin import KotlinExtractor
from .lua import LuaExtractor
from .markdown import MarkdownExtractor
from .ocaml import OCamlExtractor
from .perl import PerlExtractor
from .php import PHPExtractor
from .python import PythonExtractor
from .r import RExtractor
from .registry import (
    REGISTRY,
    discover_and_register_all,
    get_extensions_for_language,
    get_extractor,
    get_extractor_for_language,
    get_language_for_extension,
    is_language_available,
)
from .ruby import RubyExtractor
from .rust import RustExtractor
from .scala import ScalaExtractor
from .swift import SwiftExtractor
from .toml import TOMLExtractor
from .typescript import TypeScriptExtractor
from .verilog import VerilogExtractor
from .yaml import YAMLExtractor
from .zig import ZigExtractor

__all__ = [
    # Extractors
    "BashExtractor",
    "CExtractor",
    "CppExtractor",
    "DartExtractor",
    "ErlangExtractor",
    "GoExtractor",
    "HackExtractor",
    "HaskellExtractor",
    "JavaExtractor",
    "JavaScriptExtractor",
    "JuliaExtractor",
    "KotlinExtractor",
    "LuaExtractor",
    "OCamlExtractor",
    "PerlExtractor",
    "PHPExtractor",
    "PythonExtractor",
    "RExtractor",
    "RubyExtractor",
    "RustExtractor",
    "ScalaExtractor",
    "SwiftExtractor",
    "TypeScriptExtractor",
    "VerilogExtractor",
    "ZigExtractor",
    # NEW: Markup/Config Extractors
    "CSSExtractor",
    "HCLExtractor",
    "HTMLExtractor",
    "JSONExtractor",
    "MarkdownExtractor",
    "TOMLExtractor",
    "YAMLExtractor",
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
    # Factory (consolidated extractor creation)
    "ConfigurableExtractor",
    "create_extractor",
    "get_factory_extractor",
    "register_extractor",
    "list_supported_languages",
    "QUERY_REGISTRY",
]
