"""
context/languages/julia.py — Julia ASTExtractor subclass.

Capture coverage:
  - function definitions
  - macro definitions
  - struct/abstract type definitions
  - module definitions
  - import/using statements
  - function calls
"""

from __future__ import annotations

from typing import Any

from batho.modules.extraction.extractor import ASTExtractor


class JuliaExtractor(ASTExtractor):
    """Tree-sitter based extractor for Julia source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("julia", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Function definitions ────────────────────────────────────────────────────────
(function_definition
  name: (identifier) @def.function.name
  (signature
    (parameters) @def.function.params)?
  (return_type)? @def.function.return_type)

; ── Method definitions (multiple dispatch) ─────────────────────────────────────
(function_definition
  name: (identifier) @def.method.name
  (signature
    (parameters) @def.method.params)?
  (return_type)? @def.method.return_type)

; ── Macro definitions ──────────────────────────────────────────────────────────
(macro_definition
  name: (identifier) @def.function.name
  (macro_argument_list)? @def.function.params)

; ── Struct definitions ─────────────────────────────────────────────────────────
(struct_definition
  name: (identifier) @def.class.name
  (field_declaration_list)? @def.class.fields)

; ── Abstract type definitions ──────────────────────────────────────────────────
(abstract_type_definition
  name: (identifier) @def.class.name)

; ── Primitive type definitions ─────────────────────────────────────────────────
(primitive_type_definition
  name: (identifier) @def.type_alias.name)

; ── Module definitions ─────────────────────────────────────────────────────────
(module_definition
  name: (identifier) @def.module.name)

; ── Import statements ──────────────────────────────────────────────────────────
(import_statement
  (identifier) @ref.import.module)

(using_statement
  (identifier) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call
  (identifier) @ref.call)

(function_call
  (field_expression
    field: (identifier) @ref.call))

; ── Method calls ───────────────────────────────────────────────────────────────
(do_clause
  (call
    (identifier) @ref.call))
"""
