"""
context/languages/registry.py — File-extension to ASTExtractor registry.

``REGISTRY`` is a frozen mapping from lowercase file extension (including
the leading dot) to the corresponding :class:`~batho_core.context.extractor.ASTExtractor`
subclass *class* (not instance).  Instances are created lazily and cached
so each language parser is initialised at most once per process.

Auto-discovery:
The registry uses importlib to automatically discover language modules in the
`batho_core.context.languages` package. New languages can be added by
creating a new module file (e.g., `newlang.py`) with an extractor class.

Usage::

    from .registry import get_extractor

    extractor = get_extractor(".py")   # → PythonExtractor instance
    extractor = get_extractor(".ts")   # → TypeScriptExtractor instance
    extractor = get_extractor(".xyz")  # → None  (unsupported)

Support for new languages:
- Programming: PHP, C#, Kotlin, Swift, Scala, Dart, Haskell, Julia, Erlang,
  OCaml, Lua, R, Perl, Verilog, Zig, Bash, Objective-C, Agda, Hack
- Markup/Config: JSON, YAML, TOML, HTML, CSS, Markdown, HCL
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter_language_pack import get_language

from batho_core.utils.logging import get_logger

if TYPE_CHECKING:
    from ..extractor import ASTExtractor

# ---------------------------------------------------------------------------
# Module logger
# ----------------------------------------------------------------------------

_logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Extension → language name mapping (supports multiple extensions per language)
# ---------------------------------------------------------------------------

# Import lazily inside _CLASS_MAP to avoid circular imports at parse time.
# The registry itself is lightweight until get_extractor() is first called.
_EXT_TO_LANG: dict[str, str] = {
    # Python
    ".py": "python",
    ".pyi": "python",
    # TypeScript
    ".ts": "typescript",
    ".tsx": "typescript",
    # JavaScript
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    # Rust
    ".rs": "rust",
    # Go
    ".go": "go",
    # Java
    ".java": "java",
    # Ruby
    ".rb": "ruby",
    # C
    ".c": "c",
    ".h": "c",
    # C++
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    # -----------------------------------------------------------------------
    # NEW: Additional Programming Languages
    # -----------------------------------------------------------------------
    # PHP
    ".php": "php",
    # C#
    ".cs": "csharp",
    # Kotlin
    ".kt": "kotlin",
    ".kts": "kotlin",
    # Swift
    ".swift": "swift",
    # Scala
    ".scala": "scala",
    ".sc": "scala",
    # Dart
    ".dart": "dart",
    # Haskell
    ".hs": "haskell",
    ".lhs": "haskell",
    # Julia
    ".jl": "julia",
    # Erlang
    ".erl": "erlang",
    ".hrl": "erlang",
    # OCaml
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".fml": "ocaml",
    ".fsi": "ocaml",
    # Lua
    ".lua": "lua",
    # R
    ".r": "r",
    ".R": "r",
    ".rdata": "r",
    ".rds": "r",
    # Perl
    ".pl": "perl",
    ".pm": "perl",
    # Verilog
    ".v": "verilog",
    ".sv": "verilog",
    ".vh": "verilog",
    # Zig
    ".zig": "zig",
    # Bash/Shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "bash",
    ".ksh": "bash",
    ".dash": "bash",
    # Objective-C uses Objective-C extractor
    ".m": "objectivec",
    ".mm": "objectivec",
    # Agda
    ".agda": "agda",
    # Hack
    ".hack": "hack",
    # -----------------------------------------------------------------------
    # NEW: Markup/Config Languages
    # -----------------------------------------------------------------------
    # JSON
    ".json": "json",
    # YAML
    ".yaml": "yaml",
    ".yml": "yaml",
    # TOML
    ".toml": "toml",
    # HTML
    ".html": "html",
    ".htm": "html",
    # CSS
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".less": "css",
    # Markdown
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdown": "markdown",
    ".mkd": "markdown",
    ".mkdn": "markdown",
    # HCL/Terraform
    ".hcl": "hcl",
    ".tf": "hcl",
    ".tfvars": "hcl",
}

# Languages that use tree-sitter but may not be available
# Format: language_name -> tree-sitter-language-pack identifier
# This is derived from _EXT_TO_LANG values - languages we support
_TREE_SITTER_LANGUAGES: dict[str, str] = {
    # Core languages that are guaranteed to be available in tree-sitter-language-pack
    "python": "python",
    "typescript": "typescript",
    "javascript": "javascript",
    "rust": "rust",
    "go": "go",
    "java": "java",
    "ruby": "ruby",
    "c": "c",
    "cpp": "cpp",
    # New programming languages
    "php": "php",
    "csharp": "csharp",
    "kotlin": "kotlin",
    "swift": "swift",
    "scala": "scala",
    "dart": "dart",
    "haskell": "haskell",
    "julia": "julia",
    "erlang": "erlang",
    "ocaml": "ocaml",
    "lua": "lua",
    "r": "r",
    "perl": "perl",
    "verilog": "verilog",
    "zig": "zig",
    "bash": "bash",
    "objectivec": "objc",
    "objective-c": "objc",
    "agda": "agda",
    "hack": "hack",
    # Markup/Config languages
    "json": "json",
    "yaml": "yaml",
    "toml": "toml",
    "html": "html",
    "css": "css",
    "markdown": "markdown",
    "hcl": "hcl",
}

# Languages implemented with native parsers / regex instead of tree-sitter.
_NATIVE_LANGUAGES: frozenset[str] = frozenset(
    {
        "json",
        "yaml",
        "toml",
        "html",
        "css",
        "markdown",
        "hcl",
    }
)

# Cache for language availability checks
_language_available_cache: dict[str, bool] = {}


def is_language_available(language: str) -> bool:
    """
    Check if a language parser is available via tree-sitter-language-pack.

    This function provides graceful degradation - it checks if the language
    parser can be loaded and caches the result for performance.

    Args:
        language: The language identifier (e.g., "python", "php", "json")

    Returns:
        True if the language parser is available, False otherwise.
    """
    language = language.lower()

    # Native-parsed formats do not depend on tree-sitter availability.
    if language in _NATIVE_LANGUAGES:
        _language_available_cache[language] = True
        return True

    # Check cache first
    if language in _language_available_cache:
        return _language_available_cache[language]

    # Get the tree-sitter identifier for this language
    ts_identifier = _TREE_SITTER_LANGUAGES.get(language, language)

    try:
        # Try to get the language parser
        get_language(ts_identifier)
        _language_available_cache[language] = True
        _logger.debug("language_available", lang=language, ts_identifier=ts_identifier)
        return True
    except Exception as e:
        _language_available_cache[language] = False
        _logger.warning(
            "language_not_available",
            lang=language,
            ts_identifier=ts_identifier,
            error=str(e),
        )
        return False


# Human-readable language name → extractor class (populated on first import).
_LANG_TO_CLASS: dict[str, Callable[[], ASTExtractor]] = {}


def _build_class_map() -> None:
    """Lazily import and register all extractor classes."""
    # NEW: Additional programming languages
    from .bash import BashExtractor
    from .c import CExtractor
    from .cpp import CppExtractor
    from .csharp import CSharpExtractor
    from .css import CSSExtractor
    from .dart import DartExtractor
    from .erlang import ErlangExtractor
    from .go import GoExtractor
    from .hack import HackExtractor
    from .haskell import HaskellExtractor
    from .hcl import HCLExtractor
    from .html import HTMLExtractor
    from .java import JavaExtractor
    from .javascript import JavaScriptExtractor

    # NEW: Markup/Config Languages
    from .json import JSONExtractor
    from .julia import JuliaExtractor
    from .kotlin import KotlinExtractor
    from .lua import LuaExtractor
    from .markdown import MarkdownExtractor
    from .ocaml import OCamlExtractor
    from .perl import PerlExtractor
    from .objectivec import ObjectiveCExtractor

    # NEW: High-priority programming languages
    from .php import PHPExtractor
    from .python import PythonExtractor
    from .r import RExtractor
    from .ruby import RubyExtractor
    from .rust import RustExtractor
    from .scala import ScalaExtractor
    from .swift import SwiftExtractor
    from .toml import TOMLExtractor
    from .typescript import TypeScriptExtractor
    from .verilog import VerilogExtractor
    from .yaml import YAMLExtractor
    from .zig import ZigExtractor

    _LANG_TO_CLASS.update(
        {
            "python": PythonExtractor,
            "typescript": TypeScriptExtractor,
            "javascript": JavaScriptExtractor,
            "rust": RustExtractor,
            "go": GoExtractor,
            "java": JavaExtractor,
            "ruby": RubyExtractor,
            "c": CExtractor,
            "cpp": CppExtractor,
            # NEW: High-priority programming languages
            "php": PHPExtractor,
            "csharp": CSharpExtractor,
            "kotlin": KotlinExtractor,
            "swift": SwiftExtractor,
            "scala": ScalaExtractor,
            "dart": DartExtractor,
            # NEW: Additional programming languages
            "objectivec": ObjectiveCExtractor,
            "bash": BashExtractor,
            "lua": LuaExtractor,
            "r": RExtractor,
            "perl": PerlExtractor,
            "julia": JuliaExtractor,
            "haskell": HaskellExtractor,
            "erlang": ErlangExtractor,
            "ocaml": OCamlExtractor,
            "hack": HackExtractor,
            "zig": ZigExtractor,
            "verilog": VerilogExtractor,
            # NEW: Markup/Config Languages
            "json": JSONExtractor,
            "yaml": YAMLExtractor,
            "toml": TOMLExtractor,
            "html": HTMLExtractor,
            "css": CSSExtractor,
            "markdown": MarkdownExtractor,
            "hcl": HCLExtractor,
        }
    )


# Instance cache — each language extractor is a stateless singleton.
_instances: dict[str, ASTExtractor] = {}

# Auto-discovery flag
_auto_discovery_done: bool = False


def _get_extractor_instance(language: str) -> ASTExtractor | None:
    """
    Internal function to get or create a cached extractor instance.

    This consolidates the logic from get_extractor() and get_extractor_for_language()
    to avoid code duplication.

    Args:
        language: Language identifier (e.g., "python", "php", "json")

    Returns:
        A singleton extractor instance, or ``None`` if the language is not
        supported or the parser is not available.
    """
    # Check if language parser is available (graceful degradation)
    if not is_language_available(language):
        _logger.debug(
            "get_extractor_language_not_available",
            lang=language,
        )
        return None

    if language not in _instances:
        # Ensure class map is built
        if not _LANG_TO_CLASS:
            discover_and_register_all()

        cls = _LANG_TO_CLASS.get(language)
        if cls is None:
            _logger.debug(
                "get_extractor_no_class",
                lang=language,
            )
            return None
        _instances[language] = cls()

    return _instances[language]


def _discover_language_modules() -> None:
    """
    Auto-discover language modules using importlib.

    This function scans the languages directory for modules that contain
    extractor classes and registers them automatically. New languages can
    be added by simply dropping a new module file in the languages directory.

    The module should export an extractor class named after the language
    (e.g., PythonExtractor for Python, PHPExtractor for PHP).
    """
    global _auto_discovery_done
    if _auto_discovery_done:
        return

    # Get the languages directory path
    languages_dir = Path(__file__).parent

    # Known module-to-class mappings for auto-discovery
    # Format: module_name -> (class_name, language_name)
    _MODULE_CLASS_MAP: dict[str, tuple[str, str]] = {
        "c": ("CExtractor", "c"),
        "cpp": ("CppExtractor", "cpp"),
        "go": ("GoExtractor", "go"),
        "java": ("JavaExtractor", "java"),
        "javascript": ("JavaScriptExtractor", "javascript"),
        "python": ("PythonExtractor", "python"),
        "ruby": ("RubyExtractor", "ruby"),
        "rust": ("RustExtractor", "rust"),
        "typescript": ("TypeScriptExtractor", "typescript"),
        # High-priority languages
        "php": ("PHPExtractor", "php"),
        "csharp": ("CSharpExtractor", "csharp"),
        "kotlin": ("KotlinExtractor", "kotlin"),
        "swift": ("SwiftExtractor", "swift"),
        "scala": ("ScalaExtractor", "scala"),
        "dart": ("DartExtractor", "dart"),
        # Additional programming languages
        "objectivec": ("ObjectiveCExtractor", "objectivec"),
        "bash": ("BashExtractor", "bash"),
        "lua": ("LuaExtractor", "lua"),
        "r": ("RExtractor", "r"),
        "perl": ("PerlExtractor", "perl"),
        "julia": ("JuliaExtractor", "julia"),
        "haskell": ("HaskellExtractor", "haskell"),
        "erlang": ("ErlangExtractor", "erlang"),
        "ocaml": ("OCamlExtractor", "ocaml"),
        "hack": ("HackExtractor", "hack"),
        "zig": ("ZigExtractor", "zig"),
        "verilog": ("VerilogExtractor", "verilog"),
        # Markup/Config languages
        "json": ("JSONExtractor", "json"),
        "yaml": ("YAMLExtractor", "yaml"),
        "toml": ("TOMLExtractor", "toml"),
        "html": ("HTMLExtractor", "html"),
        "css": ("CSSExtractor", "css"),
        "markdown": ("MarkdownExtractor", "markdown"),
        "hcl": ("HCLExtractor", "hcl"),
    }

    for module_name, (class_name, lang_name) in _MODULE_CLASS_MAP.items():
        try:
            # Try to import the module dynamically
            module = importlib.import_module(
                f"batho_core.context.languages.{module_name}"
            )

            # Get the extractor class from the module
            extractor_class = getattr(module, class_name, None)
            if extractor_class is not None:
                # Register the class if not already registered
                if lang_name not in _LANG_TO_CLASS:
                    _LANG_TO_CLASS[lang_name] = extractor_class
                    _logger.debug(
                        "auto_discovered_language",
                        module=module_name,
                        class_name=class_name,
                        language=lang_name,
                    )
        except ImportError as e:
            # Module not found - this is fine, not all languages may be installed
            _logger.debug(
                "auto_discover_import_error",
                module=module_name,
                error=str(e),
            )
        except Exception as e:
            # Other errors - log but continue
            _logger.warning(
                "auto_discover_error",
                module=module_name,
                error=str(e),
            )

    _auto_discovery_done = True


def discover_and_register_all() -> None:
    """
    Public API for triggering full module discovery.

    This is called automatically by get_extractor() on first use,
    but can also be called manually to ensure all modules are loaded.
    """
    # First, build the manual class map (existing behavior)
    _build_class_map()
    # Then, try auto-discovery for any missing modules
    _discover_language_modules()


def get_extractor(extension: str) -> ASTExtractor | None:
    """
    Return a cached :class:`~batho_core.context.extractor.ASTExtractor` instance
    for the given file *extension*, or ``None`` if the extension is not supported
    or the language parser is not available.

    This function provides graceful degradation - it checks if the language
    parser is available before attempting to instantiate the extractor.

    On first call, this function also triggers auto-discovery of language modules
    to support dynamically added languages.

    Args:
        extension: Lowercase file extension **including** the leading dot,
                   e.g. ``".py"``, ``".ts"``, ``".cpp"``.

    Returns:
        A singleton extractor instance, or ``None`` for unsupported extensions
        or unavailable language parsers.

    Examples::

        >>> get_extractor(".py")
        <PythonExtractor language='python'>
        >>> get_extractor(".xyz")
        None
        >>> get_extractor(".php")  # if tree-sitter-php not installed
        None
    """
    # Trigger auto-discovery on first call
    if not _auto_discovery_done:
        discover_and_register_all()

    ext = extension.lower()
    lang = _EXT_TO_LANG.get(ext)
    if lang is None:
        return None

    return _get_extractor_instance(lang)


def get_extractor_for_language(language: str) -> ASTExtractor | None:
    """
    Return an extractor instance for a given language name.

    Unlike get_extractor() which uses file extension, this function directly
    looks up the language by name. Useful when language is already detected.

    Args:
        language: Language identifier (e.g., "python", "php", "json")

    Returns:
        A singleton extractor instance, or ``None`` if the language is not
        supported or the parser is not available.
    """
    return _get_extractor_instance(language)


def get_language_for_extension(extension: str) -> str | None:
    """
    Get the language name for a file extension.

    Args:
        extension: Lowercase file extension including the leading dot.

    Returns:
        Language name string, or None if extension is not recognized.
    """
    return _EXT_TO_LANG.get(extension.lower())


def get_extensions_for_language(language: str) -> list[str]:
    """
    Get all file extensions associated with a language.

    Args:
        language: Language identifier (e.g., "python", "javascript")

    Returns:
        List of file extensions (including leading dots) for the language.
    """
    return [ext for ext, lang in _EXT_TO_LANG.items() if lang == language]


# ---------------------------------------------------------------------------
# Public convenience alias
# ---------------------------------------------------------------------------

#: Read-only view of the extension → language name mapping.
REGISTRY: dict[str, str] = dict(_EXT_TO_LANG)
