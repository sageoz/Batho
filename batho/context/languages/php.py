"""
context/languages/php.py — PHP ASTExtractor subclass.

Capture coverage:
  - class declarations (with optional extends, implements)
  - method definitions (with params, visibility, return type)
  - function declarations (with params)
  - trait definitions
  - interface definitions
  - use statements (imports)
  - function/method calls
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor


class PHPExtractor(ASTExtractor):
    """Tree-sitter based extractor for PHP source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("php", parsing_config)

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
  parameters: (formal_parameters) @def.method.params
  (return_type)? @def.method.return_type)

; ── Function declarations ─────────────────────────────────────────────────────
(function_declaration
  name: (name) @def.function.name
  parameters: (formal_parameters) @def.function.params
  (return_type)? @def.function.return_type)

; ── Use statements (imports) ──────────────────────────────────────────────────
(use_declaration
  (namespace_use_clause (name) @ref.import.module))

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call_expression
  function: (qualified_name) @ref.call)

(function_call_expression
  function: (member_access_expression
    name: (name) @ref.call))

(method_call_expression
  method: (name) @ref.call)

(method_call_expression
  object: (_) @ref.call)
"""
