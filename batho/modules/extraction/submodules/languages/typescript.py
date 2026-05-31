"""
context/languages/typescript.py — TypeScript ASTExtractor subclass.

Capture coverage:
  - class declarations (with optional interface implementation list)
  - method definitions (with accessibility modifier, params, return type)
  - function declarations (with params and optional return type annotation)
  - arrow functions assigned to const variables
  - interface declarations (mapped to def.interface)
  - import statements
  - call expressions
"""

from __future__ import annotations

from typing import Any

from batho.modules.extraction.extractor import ASTExtractor
from batho.modules.extraction.submodules.parser_factory._common import CommonQueries


class TypeScriptExtractor(ASTExtractor):
    """Tree-sitter based extractor for TypeScript source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("typescript", parsing_config)

    def _query_source(self) -> str:
        # Use common entry point patterns (shared with JavaScript)
        return (
            r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (type_identifier) @def.class.name
  (class_heritage
    (implements_clause
      (type_identifier) @def.class.implements))?)

(class_declaration
  (class_heritage
    (extends_clause
      (_) @def.class.extends)))

; ── Interface declarations ────────────────────────────────────────────────────
(interface_declaration
  name: (type_identifier) @def.interface.name)

; ── Method definitions ────────────────────────────────────────────────────────
(method_definition
  (accessibility_modifier)? @def.method.visibility
  name: (property_identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params
  return_type: (type_annotation)? @def.method.return_type)

; ── Function declarations ─────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (formal_parameters) @def.function.params
  return_type: (type_annotation)? @def.function.return_type)

; ── Arrow functions assigned to a const ───────────────────────────────────────
(variable_declarator
  name: (identifier) @def.function.name
  value: (arrow_function
    parameters: (_) @def.function.params
    return_type: (type_annotation)? @def.function.return_type))

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

; ── Variable read / write access ──────────────────────────────────────────────
(assignment_expression
  left: (identifier) @ref.write)

(update_expression
  argument: (identifier) @ref.write)

(variable_declarator
  name: (identifier) @ref.write)

(identifier) @ref.read
"""
            + CommonQueries.http_server_entry_points()
            + CommonQueries.react_render_entry_points()
        )
