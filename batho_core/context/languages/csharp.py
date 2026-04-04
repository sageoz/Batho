"""
context/languages/csharp.py — C# ASTExtractor subclass.

Capture coverage:
  - class declarations (with optional base class, interfaces)
  - method definitions (with params, return type, accessibility)
  - property definitions
  - constructor definitions
  - interface declarations
  - struct declarations
  - enum declarations
  - using statements (imports)
  - method/property calls
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class CSharpExtractor(ASTExtractor):
    """Tree-sitter based extractor for C# source files."""

    def __init__(self) -> None:
        super().__init__("csharp")

    def _query_source(self) -> str:
        return r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (identifier) @def.class.name
  base: (base_clause
    (identifier) @def.class.extends)?
  (base_list
    (identifier) @def.class.implements)?)

; ── Struct declarations ────────────────────────────────────────────────────────
(struct_declaration
  name: (identifier) @def.struct.name)

; ── Interface declarations ────────────────────────────────────────────────────
(interface_declaration
  name: (identifier) @def.interface.name)

; ── Enum declarations ──────────────────────────────────────────────────────────
(enum_declaration
  name: (identifier) @def.enum.name)

; ── Method declarations ───────────────────────────────────────────────────────
(method_declaration
  (accessibility_modifier)? @def.method.visibility
  (modifier)? @def.method.static
  type: (_)? @def.method.return_type
  name: (identifier) @def.method.name
  parameters: (parameter_list) @def.method.params)

; ── Constructor declarations ────────────────────────────────────────────────────
(constructor_declaration
  (accessibility_modifier)? @def.method.visibility
  name: (identifier) @def.method.name
  parameters: (parameter_list) @def.method.params)

; ── Property declarations ──────────────────────────────────────────────────────
(property_declaration
  (accessibility_modifier)? @def.property.visibility
  type: (_)? @def.property.type
  name: (identifier) @def.property.name
  (accessor_list)? @def.property.accessors)

; ── Using statements (imports) ────────────────────────────────────────────────
(using_directive
  (qualified_name) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(invocation_expression
  (member_access_expression
    name: (identifier) @ref.call))

(invocation_expression
  (identifier) @ref.call)

(object_creation_expression
  (type (identifier) @ref.call))
"""
