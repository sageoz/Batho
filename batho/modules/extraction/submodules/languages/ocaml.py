"""
context/languages/ocaml.py — OCaml ASTExtractor subclass.

Capture coverage:
  - function definitions
  - module definitions
  - type definitions
  - class definitions
  - open/require statements (imports)
  - function calls
"""

from __future__ import annotations

from typing import Any

from batho.modules.extraction.extractor import ASTExtractor


class OCamlExtractor(ASTExtractor):
    """Tree-sitter based extractor for OCaml source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("ocaml", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Module definitions ───────────────────────────────────────────────────────────
(module_definition
  name: (module_name) @def.module.name
  (module_binding
    (module_expr) @def.module.body))

; ── Module type definitions ─────────────────────────────────────────────────────
(module_type_definition
  name: (module_type_name) @def.module.name)

; ── Function definitions ────────────────────────────────────────────────────────
(function_definition
  name: (value_name) @def.function.name
  (parameter) @def.function.params
  (body) @def.function.body)

; ── Value bindings (let statements) ────────────────────────────────────────────
(value_binding
  (pattern
    (value_name) @def.function.name)
  (parameters) @def.function.params)

; ── Type definitions ────────────────────────────────────────────────────────────
(type_definition
  name: (type_constructor_name) @def.type_alias.name
  (type_parameters)? @def.type_alias.params
  (type_kind
    (variant_declaration
      (variant_name) @def.class.constructors)))

; ── Record type definitions ─────────────────────────────────────────────────────
(type_definition
  name: (type_constructor_name) @def.class.name
  (type_kind
    (record_declaration
      (field_declaration
        (field_name) @def.field.name))))

; ── Class definitions ───────────────────────────────────────────────────────────
(class_definition
  (class_name) @def.class.name
  (class_body
    (method_definition
      (method_name) @def.method.name)))

; ── Open statements (imports) ──────────────────────────────────────────────────
(open_statement
  (module_name) @ref.import.module)

(include_statement
  (module_name) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call
  (value) @ref.call)

(application_expression
  (function
    (value) @ref.call))
"""
