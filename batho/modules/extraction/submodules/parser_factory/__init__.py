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

Use :mod:`batho.modules.extraction.submodules.parser_factory.registry` to resolve a file
extension to the correct extractor instance at runtime.

Language Detection:
Use :mod:`batho.modules.extraction.submodules.parser_factory.detector` for intelligent
language detection beyond file extensions.
"""

# NEW: Additional programming language extractors
from batho.modules.extraction.submodules.languages.bash import BashExtractor
from batho.modules.extraction.submodules.languages.c import CExtractor
from batho.modules.extraction.submodules.languages.cpp import CppExtractor
from batho.modules.extraction.submodules.languages.css import CSSExtractor
from batho.modules.extraction.submodules.languages.dart import DartExtractor
from .detector import (
    DetectionResult,
    LanguageDetector,
    default_detector,
    detect_language,
    detect_language_with_fallback,
    permissive_detector,
    strict_detector,
)
from batho.modules.extraction.submodules.languages.erlang import ErlangExtractor

# Factory module for creating extractors without subclassing
from .factory import QUERY_REGISTRY, ConfigurableExtractor, create_extractor
from .factory import get_extractor as get_factory_extractor
from .factory import list_supported_languages, register_extractor
from batho.modules.extraction.submodules.languages.go import GoExtractor
from batho.modules.extraction.submodules.languages.hack import HackExtractor
from batho.modules.extraction.submodules.languages.haskell import HaskellExtractor
from batho.modules.extraction.submodules.languages.hcl import HCLExtractor
from batho.modules.extraction.submodules.languages.html import HTMLExtractor
from batho.modules.extraction.submodules.languages.java import JavaExtractor
from batho.modules.extraction.submodules.languages.javascript import JavaScriptExtractor

# NEW: Markup/Config Language Extractors
from batho.modules.extraction.submodules.languages.json import JSONExtractor
from batho.modules.extraction.submodules.languages.julia import JuliaExtractor
from batho.modules.extraction.submodules.languages.kotlin import KotlinExtractor
from batho.modules.extraction.submodules.languages.lua import LuaExtractor
from batho.modules.extraction.submodules.languages.markdown import MarkdownExtractor
from batho.modules.extraction.submodules.languages.ocaml import OCamlExtractor
from batho.modules.extraction.submodules.languages.perl import PerlExtractor
from batho.modules.extraction.submodules.languages.php import PHPExtractor
from batho.modules.extraction.submodules.languages.python import PythonExtractor
from batho.modules.extraction.submodules.languages.r import RExtractor
from .registry import (
    REGISTRY,
    discover_and_register_all,
    get_extensions_for_language,
    get_extractor,
    get_extractor_for_language,
    get_language_for_extension,
    is_language_available,
)
from batho.modules.extraction.submodules.languages.ruby import RubyExtractor
from batho.modules.extraction.submodules.languages.rust import RustExtractor
from batho.modules.extraction.submodules.languages.scala import ScalaExtractor
from batho.modules.extraction.submodules.languages.swift import SwiftExtractor
from batho.modules.extraction.submodules.languages.toml import TOMLExtractor
from batho.modules.extraction.submodules.languages.typescript import TypeScriptExtractor
from batho.modules.extraction.submodules.languages.verilog import VerilogExtractor
from batho.modules.extraction.submodules.languages.yaml import YAMLExtractor
from batho.modules.extraction.submodules.languages.zig import ZigExtractor

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
