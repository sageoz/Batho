"""
context/languages/objectivec.py — Objective-C ASTExtractor subclass.

Capture coverage:
  - interface declarations (with superclass, protocols)
  - implementation definitions
  - protocol declarations
  - method declarations (instance and class methods)
  - property declarations
  - category definitions
  - class extensions
  - import statements
  - function/method calls
"""

from __future__ import annotations

from typing import Any

from batho.modules.extraction.extractor import ASTExtractor


class ObjectiveCExtractor(ASTExtractor):
    """Tree-sitter based extractor for Objective-C source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("objc", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Class interface declarations ───────────────────────────────────────────────
(class_interface
  !category
  "@interface"
  (identifier) @def.class.name
  (":" (identifier) @def.class.extends)?
  (parameterized_arguments
    (type_name
      (type_identifier) @def.class.implements))?)

; ── Inheritance / protocol relationships ──────────────────────────────────────
(class_interface
  ":" (identifier) @ref.inherit)

(class_interface
  (parameterized_arguments
    (type_name
      (type_identifier) @ref.implement)))

; ── Categories and class extensions ────────────────────────────────────────────
(class_interface
  "@interface"
  (identifier) @def.interface.extends
  "(" category: (identifier) @def.interface.name ")")

(class_interface
  "@interface"
  (identifier) @def.interface.name
  "(" ")")

; ── Protocol declarations ───────────────────────────────────────────────────────
(protocol_declaration
  (identifier) @def.protocol.name
  (protocol_reference_list
    (identifier) @def.protocol.implements)?)

(protocol_declaration
  (protocol_reference_list
    (identifier) @ref.implement))

; ── Method declarations / definitions ─────────────────────────────────────────
(method_declaration
  ["-" "+"] @def.method.receiver
  (method_type) @def.method.return_type
  (identifier) @def.method.name
  (method_parameter)? @def.method.params)

(method_definition
  ["-" "+"] @def.method.receiver
  (method_type) @def.method.return_type
  (identifier) @def.method.name
  (method_parameter)? @def.method.params)

; ── Property declarations ─────────────────────────────────────────────────────
(property_declaration
  (property_attributes_declaration)? @def.field.visibility
  (struct_declaration
    [(type_identifier) (primitive_type)] @def.field.type
    (struct_declarator
      [
        (identifier) @def.field.name
        (pointer_declarator
          (identifier) @def.field.name)
      ])))

; ── Class implementation ────────────────────────────────────────────────────────
(class_implementation (identifier) @def.class.name)

; ── Import statements (#import) ────────────────────────────────────────────────
(preproc_include (system_lib_string) @ref.import.module)
(preproc_include (string_literal) @ref.import.module)

; ── Message sends (selector calls) ─────────────────────────────────────────────
(message_expression
  (identifier)
  (identifier) @ref.call)
"""
