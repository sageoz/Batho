"""
context/languages/javascript.py — JavaScript ASTExtractor subclass.

Capture coverage:
  - function declarations (with params)
  - arrow functions assigned to const variables
  - class declarations
  - method definitions (with params)
  - import statements
  - call expressions

JavaScript has no type annotations or visibility modifiers, so those
auxiliary captures are simply absent from this query.
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor
from ._common import CommonQueries


class JavaScriptExtractor(ASTExtractor):
    """Tree-sitter based extractor for JavaScript source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("javascript", parsing_config)

    def _query_source(self) -> str:
        # Use common entry point patterns for JavaScript/TypeScript
        return r"""
; ── Function declarations ─────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (formal_parameters) @def.function.params)

; ── Arrow functions assigned to a const ───────────────────────────────────────
(variable_declarator
  name: (identifier) @def.function.name
  value: (arrow_function
    parameters: (_) @def.function.params))

; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (identifier) @def.class.name)

(class_declaration
  (class_heritage
    (_) @def.class.extends))

; ── Method definitions ────────────────────────────────────────────────────────
(method_definition
  name: (property_identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params)

; ── Imports ───────────────────────────────────────────────────────────────────
(import_statement
  source: (string) @ref.import.module)

(call_expression
  function: (identifier) @_require_fn
  arguments: (arguments
    (string) @ref.import.require)
  (#eq? @_require_fn "require"))

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (member_expression
    property: (property_identifier) @ref.call))
""" + CommonQueries.http_server_entry_points() + CommonQueries.react_render_entry_points()
