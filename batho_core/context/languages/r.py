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
(binary_operator
  (identifier) @def.function.name
  ["<-" "="]
  (function_definition
    (parameters) @def.function.params))

; ── Variable assignments ────────────────────────────────────────────────────────
(binary_operator
  (identifier) @def.field.name
  ["<-" "="]
  (_) @def.field.value
  (#not-match? @def.field.value "^function\\b"))

; ── Library/Require statements (imports) ──────────────────────────────────────
(call
  (identifier) @_import_fn
  (arguments
    (argument
      [
        (identifier)
        (string)
        (namespace_operator
          (identifier)
          (identifier))
      ] @ref.import.module))
  (#match? @_import_fn "^(library|require|requireNamespace|loadNamespace)$"))

; ── Calls ─────────────────────────────────────────────────────────────────────
(call
  (identifier) @ref.call)

(call
  (namespace_operator
    (identifier)
    (identifier) @ref.call)
  (arguments))
"""
