"""
context/languages/r.py — R ASTExtractor subclass.

Capture coverage:
  - function definitions
  - library/require statements (imports)
  - function calls
  - variable assignments
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class RExtractor(ASTExtractor):
    """Tree-sitter based extractor for R source files."""

    def __init__(self) -> None:
        super().__init__("r")

    def _query_source(self) -> str:
        return r"""
; ── Function definitions ────────────────────────────────────────────────────────
(function_definition
  name: (identifier) @def.function.name
  parameters: (parameters) @def.function.params)

; ── Binary operator function definition (<-) ─────────────────────────────────
(binary
  left: (identifier) @def.function.name
  operator: "<-"
  right: (function_definition
    parameters: (parameters) @def.function.params))

; ── Variable assignments ────────────────────────────────────────────────────────
(binary
  left: (identifier) @def.field.name
  operator: "<-"
  right: (_) @def.field.value)

(binary
  left: (identifier) @def.field.name
  operator: "="
  right: (_) @def.field.value)

; ── Library/Require statements (imports) ──────────────────────────────────────
(function_call
  name: (identifier) @ref.import
  (#eq? @ref.import "library"))

(function_call
  name: (identifier) @ref.import
  (#eq? @ref.import "require"))

(function_call
  name: (identifier) @ref.import
  (#eq? @ref.import "requireNamespace"))

(function_call
  name: (identifier) @ref.import
  (#eq? @ref.import "loadNamespace"))

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call
  name: (identifier) @ref.call)

(function_call
  name: (namespace_get
    (identifier) @ref.call))
"""
