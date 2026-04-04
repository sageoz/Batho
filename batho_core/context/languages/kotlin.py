"""
context/languages/kotlin.py — Kotlin ASTExtractor subclass.

Capture coverage:
  - class declarations (with optional superclass, interfaces)
  - method declarations (with params, return type, visibility)
  - function declarations (with params, return type)
  - object declarations
  - interface declarations
  - import statements
  - function/method calls
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class KotlinExtractor(ASTExtractor):
    """Tree-sitter based extractor for Kotlin source files."""

    def __init__(self) -> None:
        super().__init__("kotlin")

    def _query_source(self) -> str:
        return r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (type_identifier) @def.class.name
  (primary_constructor
    (constructor_parameters) @def.class.constructor)?
  (superclass
    (user_type
      (type_identifier) @def.class.extends))?
  (delegation_specifiers
    (user_type
      (type_identifier) @def.class.implements))?)

; ── Interface declarations ────────────────────────────────────────────────────
(interface_declaration
  name: (type_identifier) @def.interface.name)

; ── Object declarations (singletons) ───────────────────────────────────────────
(object_declaration
  name: (type_identifier) @def.object.name)

; ── Method declarations (functions inside classes) ────────────────────────────
(class_declaration
  (class_body
    (function_declaration
      (modifiers)? @def.method.visibility
      (simple_identifier) @def.method.name
      (parameters) @def.method.params
      (type) @def.method.return_type)))

; ── Function declarations (top-level) ─────────────────────────────────────────
(function_declaration
  (modifiers)? @def.function.visibility
  (simple_identifier) @def.function.name
  (parameters) @def.function.params
  (type) @def.function.return_type)

; ── Import statements ──────────────────────────────────────────────────────────
(import_header
  (imported_namespace) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  (simple_identifier) @ref.call)

(call_expression
  (member_access_expression
    (simple_identifier) @ref.call))
"""
