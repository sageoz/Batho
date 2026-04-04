"""
context/languages/java.py — Java ASTExtractor subclass.

Capture coverage:
  - class declarations (with visibility, optional superclass, interface list)
  - method declarations (with visibility, return type, params)
  - constructor declarations (mapped to def.method, visibility, params)
  - field declarations (with visibility and type)
  - import declarations
  - method invocations (calls)
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class JavaExtractor(ASTExtractor):
    """Tree-sitter based extractor for Java source files."""

    def __init__(self) -> None:
        super().__init__("java")

    def _query_source(self) -> str:
        return r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  (modifiers)? @def.class.visibility
  name: (identifier) @def.class.name
  superclass: (superclass
    (type_identifier) @def.class.extends)?
  interfaces: (super_interfaces
    (type_list
      (type_identifier) @def.class.implements))?)

; ── Method declarations ───────────────────────────────────────────────────────
(method_declaration
  (modifiers)? @def.method.visibility
  type: (_) @def.method.return_type
  name: (identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params)

; ── Constructor declarations (treated as methods) ────────────────────────────
(constructor_declaration
  (modifiers)? @def.method.visibility
  name: (identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params)

; ── Field declarations ────────────────────────────────────────────────────────
(field_declaration
  (modifiers)? @def.field.visibility
  type: (_) @def.field.type
  declarator: (variable_declarator
    name: (identifier) @def.field.name))

; ── Imports ───────────────────────────────────────────────────────────────────
(import_declaration
  (scoped_identifier) @ref.import.module)

(import_declaration
  "static"
  (scoped_identifier) @ref.import.static)

; ── Calls ─────────────────────────────────────────────────────────────────────
(method_invocation
  name: (identifier) @ref.call)
"""
