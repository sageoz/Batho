"""
context/languages/swift.py — Swift ASTExtractor subclass.

Capture coverage:
  - class declarations (with optional superclass, protocols)
  - struct declarations (with protocols)
  - enum declarations
  - protocol declarations
  - function declarations (with params, return type)
  - method declarations (inside types)
  - import statements
  - function/method calls
"""

from __future__ import annotations

from typing import Any

from batho.modules.extraction.extractor import ASTExtractor


class SwiftExtractor(ASTExtractor):
    """Tree-sitter based extractor for Swift source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("swift", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (type_identifier) @def.class.name
  (superclass_clause
    (type_identifier) @def.class.extends)?
  (protocols
    (type_identifier) @def.class.implements)?)

; ── Struct declarations ────────────────────────────────────────────────────────
(struct_declaration
  name: (type_identifier) @def.struct.name
  (protocols
    (type_identifier) @def.struct.implements)?)

; ── Enum declarations ──────────────────────────────────────────────────────────
(enum_declaration
  name: (type_identifier) @def.enum.name
  (protocols
    (type_identifier) @def.enum.implements)?)

; ── Protocol declarations ──────────────────────────────────────────────────────
(protocol_declaration
  name: (type_identifier) @def.protocol.name)

; ── Function declarations (top-level) ───────────────────────────────────────────
(function_declaration
  name: (simple_identifier) @def.function.name
  (parameter_list) @def.function.params
  (type) @def.function.return_type)

; ── Method declarations (inside classes/structs/enums) ─────────────────────────
(class_declaration
  (class_body
    (function_declaration
      name: (simple_identifier) @def.method.name
      (parameter_list) @def.method.params
      (type) @def.method.return_type)))

(struct_declaration
  (struct_body
    (function_declaration
      name: (simple_identifier) @def.method.name
      (parameter_list) @def.method.params
      (type) @def.method.return_type)))

(enum_declaration
  (enum_body
    (function_declaration
      name: (simple_identifier) @def.method.name
      (parameter_list) @def.method.params
      (type) @def.method.return_type)))

; ── Import statements ──────────────────────────────────────────────────────────
(import_declaration
  (import_path
    (simple_identifier) @ref.import.module))

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  (simple_identifier) @ref.call)

(call_expression
  (member_expression
    (simple_identifier) @ref.call))
"""
