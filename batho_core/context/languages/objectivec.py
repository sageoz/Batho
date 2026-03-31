"""
context/languages/objectivec.py — Objective-C ASTExtractor subclass.

Capture coverage:
  - class interfaces (@interface) with inheritance
  - class implementations (@implementation)
  - protocol declarations (@protocol)
  - method declarations (in @interface)
  - method definitions (in @implementation)
  - property declarations (@property)
  - function definitions (C-style)
  - import statements (#import #include)
  - function/method calls
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class ObjectiveCExtractor(ASTExtractor):
    """Tree-sitter based extractor for Objective-C source files."""

    def __init__(self) -> None:
        super().__init__("objc")  # Make sure your registry uses "objc"

    def _query_source(self) -> str:
        return r"""
; ── Class interfaces ─────────────────────────────────────────────────────
(class_interface
  name: (identifier) @def.class.name)

(class_interface
  superclass: (identifier) @def.class.extends)

; ── Class implementations ────────────────────────────────────────────────
(class_implementation
  name: (identifier) @def.class.name)

; ── Protocol declarations ────────────────────────────────────────────────
(protocol_declaration
  name: (identifier) @def.protocol.name)

; ── Property declarations ────────────────────────────────────────────────
(property_declaration
  (identifier) @def.property.name)

(property_declaration
  type: (type_identifier) @def.property.type)

; ── Method declarations (in @interface) ──────────────────────────────────
(method_declaration
  selector: (selector) @def.method.name)

; ── Method definitions (in @implementation) ──────────────────────────────
(method_definition
  selector: (selector) @def.method.name)

; ── Function definitions (C-style) ───────────────────────────────────────
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @def.function.name))

; ── Import statements ────────────────────────────────────────────────────
(preproc_include
  path: (system_lib_string) @ref.import)

(preproc_include
  path: (string_literal) @ref.import)

; ── Calls ───────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (member_expression
    property: (identifier) @ref.call))

(message_expression
  selector: (selector) @ref.call)
"""