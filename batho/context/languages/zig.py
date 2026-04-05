"""
context/languages/zig.py — Zig ASTExtractor subclass.

Capture coverage:
  - function definitions
  - struct definitions
  - enum definitions
  - union definitions
  - const declarations
  - var declarations
  - import/use statements
  - function calls
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor


class ZigExtractor(ASTExtractor):
    """Tree-sitter based extractor for Zig source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("zig", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Function definitions ────────────────────────────────────────────────────────
(function_definition
  name: (identifier) @def.function.name
  parameters: (parameters) @def.function.params
  (return_type)? @def.function.return_type
  (block)? @def.function.body)

; ── Struct definitions ─────────────────────────────────────────────────────────
(struct_declaration
  name: (identifier) @def.struct.name
  (struct_body
    (declaration
      (field_declaration
        (field_identifier) @def.field.name))))

; ── Enum definitions ───────────────────────────────────────────────────────────
(enum_declaration
  name: (identifier) @def.enum.name
  (enum_body
    (enum_field_declaration
      (identifier) @def.field.name)))

; ── Union definitions ─────────────────────────────────────────────────────────
(union_declaration
  name: (identifier) @def.class.name
  (union_body
    (declaration
      (field_declaration
        (field_identifier) @def.field.name))))

; ── Const declarations ──────────────────────────────────────────────────────────
(const_declaration
  name: (identifier) @def.constant.name
  (type_expr)? @def.constant.type
  (value)? @def.constant.value)

; ── Var declarations ───────────────────────────────────────────────────────────
(var_declaration
  name: (identifier) @def.field.name
  (type_expr)? @def.field.type
  (value)? @def.field.value)

; ── Import statements ──────────────────────────────────────────────────────────
(import
  (string) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call_expression
  (identifier) @ref.call)

(function_call_expression
  (member_expression
    (identifier) @ref.call))

; ── Init expressions ───────────────────────────────────────────────────────────
(struct_initialization_expression
  (field_designation
    (field_identifier) @ref.call))
"""
