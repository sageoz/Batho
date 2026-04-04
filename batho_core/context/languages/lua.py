"""
context/languages/lua.py — Lua ASTExtractor subclass.

Capture coverage:
  - function definitions (local and global)
  - method definitions (function calls on tables)
  - table definitions
  - require statements (imports)
  - function calls
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor


class LuaExtractor(ASTExtractor):
    """Tree-sitter based extractor for Lua source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("lua", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Global function definitions ────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (parameters) @def.function.params)

; ── Local function definitions ─────────────────────────────────────────────────
(local_function
  name: (identifier) @def.function.name
  parameters: (parameters) @def.function.params)

; ── Method definitions (function as table field) ───────────────────────────────
(table_definition
  (field
    key: (field_key
      (identifier) @def.method.name)
    value: (function_definition
      parameters: (parameters) @def.method.params)))

; ── Table definitions ─────────────────────────────────────────────────────────
(table_constructor
  (field
    key: (field_key
      (identifier) @def.field.name)))

; ── Require statements (imports) ───────────────────────────────────────────────
(function_call
  (prefix
    (identifier) @_import_fn)
  (arguments
    (string) @ref.import.module)
  (#match? @_import_fn "^(require|dofile|loadfile)$"))

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call
  (prefix: (identifier) @ref.call))

(function_call
  (prefix: (method_call_expression
    (identifier) @ref.call)))

; ── Method calls ───────────────────────────────────────────────────────────────
(method_call
  method: (identifier) @ref.call)
"""
