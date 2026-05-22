"""
backend/context/languages/factory.py — Factory for creating ASTExtractor instances.

This module provides a declarative, configuration-based approach to creating
language extractors, eliminating the ~40 lines of boilerplate per extractor.

Instead of defining a new class for each language:

    class PythonExtractor(ASTExtractor):
        def __init__(self) -> None:
            super().__init__("python")

        def _query_source(self) -> str:
            return PYTHON_QUERY

You can simply use:

    extractor = create_extractor("python", PYTHON_QUERY)

Or use the pre-registered extractors:

    from batho.context.languages.factory import get_extractor
    extractor = get_extractor("python")

Estimated savings: ~40 lines per extractor × 30 extractors = 1,200 lines → ~200 lines
"""

from __future__ import annotations

from typing import Any

from batho.context.extractor import ASTExtractor

from ._queries import TREE_SITTER_QUERIES, get_query, list_supported_languages as _list_queries


class ConfigurableExtractor(ASTExtractor):
    """
    A configurable ASTExtractor that accepts query source at initialization.

    This eliminates the need to subclass ASTExtractor for each language.
    The language name and query source are provided at instantiation time
    rather than through abstract method overrides.

    Args:
        language: Language identifier for tree-sitter (e.g., "python", "rust")
        query_source: Tree-sitter SCM query string for extracting entities
    """

    def __init__(
        self,
        language: str,
        query_source: str,
        parsing_config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize a configurable extractor.

        Args:
            language: Language identifier for tree-sitter-language-pack
            query_source: Tree-sitter SCM query string
            parsing_config: Optional parsing config dict
        """
        self._query: str = query_source
        super().__init__(language, parsing_config)

    def _query_source(self) -> str:
        """Return the configured query source."""
        return self._query


def create_extractor(language: str, query_source: str) -> ASTExtractor:
    """
    Factory function to create an ASTExtractor instance.

    This is the primary factory method for creating extractors without
    defining a new subclass for each language.

    Args:
        language: Language identifier (e.g., "python", "javascript", "rust")
        query_source: Tree-sitter SCM query string for the language

    Returns:
        Configured ASTExtractor instance ready to parse files

    Example:
        >>> extractor = create_extractor("python", PYTHON_QUERY)
        >>> entities, relationships = extractor.parse_file("test.py", content)
    """
    return ConfigurableExtractor(language, query_source)


# =============================================================================
# Query Registry (delegated to _queries.py for single source of truth)
# =============================================================================

# Re-export for backward compatibility
PYTHON_QUERY = TREE_SITTER_QUERIES["python"]
JAVASCRIPT_QUERY = TREE_SITTER_QUERIES["javascript"]
TYPESCRIPT_QUERY = TREE_SITTER_QUERIES["typescript"]
RUST_QUERY = TREE_SITTER_QUERIES["rust"]
GO_QUERY = TREE_SITTER_QUERIES["go"]
JAVA_QUERY = TREE_SITTER_QUERIES["java"]
C_QUERY = TREE_SITTER_QUERIES["c"]
CPP_QUERY = TREE_SITTER_QUERIES["cpp"]
CSHARP_QUERY = TREE_SITTER_QUERIES["csharp"]
PHP_QUERY = TREE_SITTER_QUERIES["php"]
KOTLIN_QUERY = TREE_SITTER_QUERIES["kotlin"]
SWIFT_QUERY = TREE_SITTER_QUERIES["swift"]
SCALA_QUERY = TREE_SITTER_QUERIES["scala"]
DART_QUERY = TREE_SITTER_QUERIES["dart"]
BASH_QUERY = TREE_SITTER_QUERIES["bash"]
LUA_QUERY = TREE_SITTER_QUERIES["lua"]
R_QUERY = TREE_SITTER_QUERIES["r"]
PERL_QUERY = TREE_SITTER_QUERIES["perl"]
JULIA_QUERY = TREE_SITTER_QUERIES["julia"]
HASKELL_QUERY = TREE_SITTER_QUERIES["haskell"]
ERLANG_QUERY = TREE_SITTER_QUERIES["erlang"]
OCAML_QUERY = TREE_SITTER_QUERIES["ocaml"]
HACK_QUERY = TREE_SITTER_QUERIES["hack"]
ZIG_QUERY = TREE_SITTER_QUERIES["zig"]
VERILOG_QUERY = TREE_SITTER_QUERIES["verilog"]
OBJECTIVEC_QUERY = TREE_SITTER_QUERIES["objectivec"]
RUBY_QUERY = TREE_SITTER_QUERIES["ruby"]

# Backward compatibility alias
QUERY_REGISTRY: dict[str, str] = TREE_SITTER_QUERIES


# Cache of created extractor instances
_extractor_cache: dict[str, ASTExtractor] = {}


def get_extractor(language: str) -> ASTExtractor | None:
    """
    Get a cached extractor instance for the specified language.

    This function returns a cached instance if available, or creates
    a new one using the query registry. The cache prevents redundant
    extractor instantiation.

    Args:
        language: Language identifier (e.g., "python", "rust")

    Returns:
        ASTExtractor instance or None if language not in registry

    Example:
        >>> extractor = get_extractor("python")
        >>> if extractor:
        ...     entities, rels = extractor.parse_file("test.py", content)
    """
    # Return cached instance if available
    if language in _extractor_cache:
        return _extractor_cache[language]

    # Create new instance if query is registered
    query = TREE_SITTER_QUERIES.get(language)
    if query:
        extractor = create_extractor(language, query)
        _extractor_cache[language] = extractor
        return extractor

    return None


def register_extractor(language: str, query_source: str) -> None:
    """
    Register a new extractor query for a language.

    This allows extending the factory with custom languages without
    modifying the factory module itself.

    Args:
        language: Language identifier
        query_source: Tree-sitter SCM query string

    Example:
        >>> register_extractor("kotlin", KOTLIN_QUERY)
        >>> extractor = get_extractor("kotlin")
    """
    TREE_SITTER_QUERIES[language] = query_source
    # Clear cache if this language was previously cached
    if language in _extractor_cache:
        del _extractor_cache[language]


def list_supported_languages() -> list[str]:
    """
    Return a list of language identifiers with registered queries.

    Returns:
        Sorted list of supported language identifiers
    """
    return _list_queries()


def clear_extractor_cache() -> None:
    """
    Clear the extractor instance cache.

    This is useful for testing or when queries are updated dynamically.
    """
    _extractor_cache.clear()
