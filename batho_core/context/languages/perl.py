"""
context/languages/perl.py — Perl ASTExtractor subclass.

Capture coverage:
  - function/method definitions (sub declarations)
  - package declarations
  - use statements (imports)
  - function calls
  - variable declarations
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class PerlExtractor(ASTExtractor):
    """Tree-sitter based extractor for Perl source files."""

    def __init__(self) -> None:
        super().__init__("perl")

    def _query_source(self) -> str:
        return r"""
; ── Package declarations ────────────────────────────────────────────────────────
(package_declaration
  name: (package_name) @def.module.name)

; ── Subroutine definitions (functions) ─────────────────────────────────────────
(subroutine_declaration
  name: (identifier) @def.function.name
  (prototype)? @def.function.params)

; ── Method definitions (blessed subroutines) ───────────────────────────────────
(subroutine_declaration
  name: (identifier) @def.method.name
  (prototype)? @def.method.params)

; ── Use statements (imports) ─────────────────────────────────────────────────
(use_statement
  module: (module_name) @ref.import.module)

(no_statement
  module: (module_name) @ref.import.module)

(use_statements
  (use_statement
    module: (module_name) @ref.import.module))

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call
  function: (identifier) @ref.call)

(method_call
  method: (identifier) @ref.call)

(function_call
  function: (method_call
    method: (identifier) @ref.call))

; ── Variable declarations ─────────────────────────────────────────────────────
(scalar_variable_declaration
  (scalar_variable
    name: (identifier) @def.field.name))

(array_variable_declaration
  (array_variable
    name: (identifier) @def.field.name))

(hash_variable_declaration
  (hash_variable
    name: (identifier) @def.field.name))
"""
