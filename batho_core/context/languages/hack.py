"""
context/languages/hack.py — Hack ASTExtractor subclass.

Capture coverage:
  - class declarations (with extends, implements)
  - function definitions
  - method definitions
  - interface definitions
  - trait definitions
  - type alias definitions
  - use statements (imports)
  - function/method calls

Note: Hack is built on top of PHP, so many patterns are similar but with
additional type annotations and strict typing features.
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class HackExtractor(ASTExtractor):
    """Tree-sitter based extractor for Hack source files."""

    def __init__(self) -> None:
        super().__init__("hack")

    def _query_source(self) -> str:
        return r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (name) @def.class.name
  (extends_clause (name) @def.class.extends)?
  (implements_clause (name) @def.class.implements)?)

; ── Interface declarations ────────────────────────────────────────────────────
(interface_declaration
  name: (name) @def.interface.name)

; ── Trait declarations ────────────────────────────────────────────────────────
(trait_declaration
  name: (name) @def.trait.name)

; ── Method definitions ────────────────────────────────────────────────────────
(method_declaration
  (visibility_modifier)? @def.method.visibility
  (static_modifier)? @def.method.static
  name: (name) @def.method.name
  parameters: (parameters) @def.method.params
  (return_type)? @def.method.return_type)

; ── Function definitions ───────────────────────────────────────────────────────
(function_declaration
  name: (name) @def.function.name
  parameters: (parameters) @def.function.params
  (return_type)? @def.function.return_type)

; ── Type alias definitions ────────────────────────────────────────────────────
(type_alias_declaration
  name: (name) @def.type_alias.name
  (type) @def.type_alias.type)

; ── Use statements (imports) ──────────────────────────────────────────────────
(use_declaration
  (namespace_use_clause (name) @ref.import.module))

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call_expression
  function: (qualified_name) @ref.call)

(function_call_expression
  function: (member_call_expression
    method: (name) @ref.call))

(method_call_expression
  method: (name) @ref.call)

(method_call_expression
  object: (_) @ref.call)
"""
