"""
context/languages/rust.py — Rust ASTExtractor subclass.

Capture coverage:
  - struct definitions
  - enum definitions (mapped to def.enum)
  - trait definitions (mapped to def.trait)
  - free function definitions (with visibility, params, return type)
  - impl-block method / associated-function definitions (mapped to def.method)
  - use declarations (imports)
  - call expressions

``impl_item`` blocks themselves are not captured as entities because they
are not uniquely named constructs — their contained functions are captured
as ``def.method``.
"""

from __future__ import annotations

from typing import Any

from batho.modules.extraction.extractor import ASTExtractor


class RustExtractor(ASTExtractor):
    """Tree-sitter based extractor for Rust source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("rust", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Struct definitions ────────────────────────────────────────────────────────
(struct_item
  name: (type_identifier) @def.struct.name)

; ── Enum definitions ──────────────────────────────────────────────────────────
(enum_item
  name: (type_identifier) @def.enum.name)

; ── Trait definitions ─────────────────────────────────────────────────────────
(trait_item
  name: (type_identifier) @def.trait.name)

; ── Free function definitions (source-file scope only) ───────────────────────
; Scoping to source_file prevents double-capture with impl-block methods below.
(source_file
  (function_item
    (visibility_modifier)? @def.function.visibility
    name: (identifier) @def.function.name
    parameters: (parameters) @def.function.params
    return_type: (_)? @def.function.return_type))

; ── Methods inside impl blocks ────────────────────────────────────────────────
(impl_item
  trait: (type_identifier)? @def.method.trait
  body: (declaration_list
    (function_item
      (visibility_modifier)? @def.method.visibility
      name: (identifier) @def.method.name
      parameters: (parameters) @def.method.params
      return_type: (_)? @def.method.return_type)))

; ── Use declarations (imports) ────────────────────────────────────────────────
(use_declaration
  argument: (_) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (field_expression
    field: (field_identifier) @ref.call))
"""
