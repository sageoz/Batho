"""
context/languages/haskell.py — Haskell ASTExtractor subclass.

Capture coverage:
  - function definitions
  - type definitions (data, newtype, type)
  - class definitions
  - instance definitions
  - import statements
  - function calls
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor


class HaskellExtractor(ASTExtractor):
    """Tree-sitter based extractor for Haskell source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("haskell", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Function definitions ────────────────────────────────────────────────────────
(function_definition
  (signature
    name: (identifier) @def.function.name
    type: (type) @def.function.return_type)?
  (pattern_list
    (identifier) @def.function.name)
  (exp_binding
    (lambda
      (pattern_list) @def.function.params)))

(function_definition
  (signature
    name: (identifier) @def.function.name
    type: (type) @def.function.return_type)?
  (pattern_list
    (identifier) @def.function.name))

; ── Type definitions ────────────────────────────────────────────────────────────
(type_declaration
  name: (type_identifier) @def.type_alias.name
  (type_variable) @def.type_alias.params)

(data_declaration
  name: (type_identifier) @def.class.name
  (constructor_list)? @def.class.constructors)

(newtype_declaration
  name: (type_identifier) @def.class.name
  (constructor_declaration
    (constructor_name) @def.class.constructor))

; ── Class declarations ─────────────────────────────────────────────────────────
(class_declaration
  name: (class_name) @def.class.name
  (class_body
    (signature
      (identifier) @def.method.name)))

; ── Instance declarations ────────────────────────────────────────────────────────
(instance_declaration
  (class_name) @def.trait.name
  (instance_body
    (signature
      (identifier) @def.method.name)))

; ── Import statements ──────────────────────────────────────────────────────────
(import_statement
  (module_name) @ref.import.module)

(qualified_import
  (module_name) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call_expression
  (function) @ref.call)

(operator_application
  (function) @ref.call)
"""
