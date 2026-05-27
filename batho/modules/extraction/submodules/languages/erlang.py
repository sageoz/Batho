"""
context/languages/erlang.py — Erlang ASTExtractor subclass.

Capture coverage:
  - function definitions
  - module declarations
  - record definitions
  - type definitions
  - import statements
  - function calls
"""

from __future__ import annotations

from typing import Any

from batho.modules.extraction.extractor import ASTExtractor


class ErlangExtractor(ASTExtractor):
    """Tree-sitter based extractor for Erlang source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("erlang", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Module declaration ──────────────────────────────────────────────────────────
(module_attribute
  (atom
    (variable) @def.module.name)
  (#eq? @def.module.name "module"))

; ── Function definitions ────────────────────────────────────────────────────────
(function_clause
  name: (atom) @def.function.name
  (arguments
    (list
      (term) @def.function.params))
  (body
    (clause_body
      (expression) @def.function.body)))

; ── Record definitions ─────────────────────────────────────────────────────────
(record_definition
  name: (atom) @def.class.name
  (record_def_body
    (record_field
      (atom) @def.field.name)))

; ── Type definitions ───────────────────────────────────────────────────────────
(type_definition
  name: (type_identifier) @def.type_alias.name
  (type_arguments)? @def.type_alias.params
  (type) @def.type_alias.type)

; ── Import statements ──────────────────────────────────────────────────────────
(import_attribute
  (module_name) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call
  (atom) @ref.call
  (arguments) @ref.call.args)

(remote_function_call
  module: (atom) @ref.call.module
  function: (atom) @ref.call)

; ── Module-qualified calls ─────────────────────────────────────────────────────
(remote_function_call
  (module
    (atom) @ref.import.module)
  (function
    (atom) @ref.call))
"""
