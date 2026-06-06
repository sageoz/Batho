"""
context/languages/_common.py — Shared query patterns and base classes for language extractors.

This module provides:
1. Common tree-sitter query fragments that can be reused across languages
2. A base class for programming language extractors with common patterns
3. Shared utilities for entity extraction

Design principle: DRY - Don't Repeat Yourself.
Language-specific customizations remain in individual extractor files.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Common Query Fragments
# ---------------------------------------------------------------------------


class CommonQueries:
    """
    Reusable tree-sitter query fragments for common language patterns.

    These can be combined with language-specific queries in individual extractors.
    """

    # ─────────────────────────────────────────────────────────────────────────
    # Import/Reference Queries
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def basic_imports(cls) -> str:
        """Basic import statements - override in subclass for language-specific syntax."""
        return ""

    @classmethod
    def basic_calls(cls) -> str:
        """Basic function/method call patterns."""
        return ""

    # ─────────────────────────────────────────────────────────────────────────
    # Entry Point Queries (common patterns)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def http_server_entry_points() -> str:
        """
        Common HTTP server entry point patterns.
        Matches: app.listen(), server.listen(), http.listen()
        """
        return r"""
; ── HTTP server entry points ─────────────────────────────────────────────────
(call_expression
  function: (member_expression
    object: (identifier) @entry.obj
    property: (property_identifier) @entry.prop)
  (#match? @entry.obj "^(app|server|http)$")
  (#eq? @entry.prop "listen")) @def.entry_point
"""

    @staticmethod
    def react_render_entry_points() -> str:
        """
        Common React entry point patterns.
        Matches: ReactDOM.render(), createRoot().render()
        """
        return r"""
; ── React entry points ───────────────────────────────────────────────────────
(call_expression
  function: (member_expression
    object: (identifier) @entry.obj
    property: (property_identifier) @entry.prop)
  (#eq? @entry.obj "ReactDOM")
  (#eq? @entry.prop "render")) @def.entry_point

; ── React 18+ entry point ────────────────────────────────────────────────────
(call_expression
  function: (member_expression
    object: (call_expression
      function: (identifier) @entry.func)
    property: (property_identifier) @entry.prop)
  (#eq? @entry.func "createRoot")
  (#eq? @entry.prop "render")) @def.entry_point
"""

    # ─────────────────────────────────────────────────────────────────────────
    # Common structural queries
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def class_with_extends() -> str:
        """Class declaration with optional extends clause."""
        return r"""
(class_declaration
  name: (identifier) @def.class.name
  (class_heritage
    (extends_clause
      (identifier) @def.class.extends)?))
"""

    @staticmethod
    def class_with_implements() -> str:
        """Class declaration with optional implements clause."""
        return r"""
(class_declaration
  name: (identifier) @def.class.name
  (class_heritage
    (implements_clause
      (identifier) @def.class.implements))?)
"""

    @staticmethod
    def method_with_params_return() -> str:
        """Method definition with parameters and return type."""
        return r"""
(method_definition
  name: (property_identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params
  return_type: (type_annotation)? @def.method.return_type)
"""

    @staticmethod
    def function_with_params_return() -> str:
        """Function definition with parameters and optional return type."""
        return r"""
(function_declaration
  name: (identifier) @def.function.name
  parameters: (formal_parameters) @def.function.params
  return_type: (type_annotation)? @def.function.return_type)
"""


# ---------------------------------------------------------------------------
# Shared Query Patterns by Category
# ---------------------------------------------------------------------------


class ImportPatterns:
    """Common import/reference patterns across languages."""

    @staticmethod
    def string_import() -> str:
        """Import via string literal (common in JS, TS, Go)."""
        return r"""
(import_statement
  source: (string) @ref.import.module)
"""

    @staticmethod
    def dotted_name_import() -> str:
        """Import via dotted name (common in Python, Java)."""
        return r"""
(import_statement
  name: (dotted_name) @ref.import.module)
"""

    @staticmethod
    def qualified_name_import() -> str:
        """Import via qualified name (common in PHP, Hack)."""
        return r"""
(use_declaration
  (namespace_use_clause (name) @ref.import.module))
"""


class CallPatterns:
    """Common function/method call patterns."""

    @staticmethod
    def direct_call() -> str:
        """Direct function call via identifier."""
        return r"""
(call_expression
  function: (identifier) @ref.call)
"""

    @staticmethod
    def method_call() -> str:
        """Method call via member expression."""
        return r"""
(call_expression
  function: (member_expression
    property: (property_identifier) @ref.call))
"""

    @staticmethod
    def qualified_call() -> str:
        """Qualified/method call (e.g., module.function or obj.method)."""
        return r"""
(call_expression
  function: (field_expression
    field: (field_identifier) @ref.call))
"""


# ---------------------------------------------------------------------------
# Query Builder Utilities
# ---------------------------------------------------------------------------


def build_query(segments: list[str]) -> str:
    """
    Build a tree-sitter query from segments.

    Args:
        segments: List of query segments to combine

    Returns:
        Combined query string
    """
    return "\n\n".join(segment.strip() for segment in segments if segment.strip())


