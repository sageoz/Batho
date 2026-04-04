"""
context/languages/go.py — Go ASTExtractor subclass.

Capture coverage:
  - top-level function declarations (with params and optional return type)
  - method declarations (with receiver, params, optional return type)
  - struct type declarations (mapped to def.struct)
  - interface type declarations (mapped to def.interface)
  - import spec paths (mapped to ref.import.module)
  - call expressions

Go has no classes.  Structs + interfaces are the primary composite types;
methods are functions with a receiver parameter.
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class GoExtractor(ASTExtractor):
    """Tree-sitter based extractor for Go source files."""

    def __init__(self) -> None:
        super().__init__("go")

    def _query_source(self) -> str:
        return r"""
; ── Function declarations ─────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (parameter_list) @def.function.params
  result: (_)? @def.function.return_type)

; ── Method declarations ───────────────────────────────────────────────────────
(method_declaration
  receiver: (parameter_list) @def.method.receiver
  name: (field_identifier) @def.method.name
  parameters: (parameter_list) @def.method.params
  result: (_)? @def.method.return_type)

; ── Struct type declarations ──────────────────────────────────────────────────
(type_declaration
  (type_spec
    name: (type_identifier) @def.struct.name
    type: (struct_type)))

; ── Interface type declarations ───────────────────────────────────────────────
(type_declaration
  (type_spec
    name: (type_identifier) @def.interface.name
    type: (interface_type)))

; ── Imports ───────────────────────────────────────────────────────────────────
(import_spec
  path: (interpreted_string_literal) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (selector_expression
    field: (field_identifier) @ref.call))
"""
