"""
context/languages/cpp.py — C++ ASTExtractor subclass.

Capture coverage:
  - class / struct specifier definitions (mapped to def.class)
  - free function definitions (mapped to def.function)
  - member function / method definitions — function_declarator inside a
    class scope (mapped to def.method)
  - namespace definitions (mapped to def.namespace)
  - preprocessor ``#include`` directives (mapped to ref.import.module)
  - call expressions (mapped to ref.call)

C++ has considerably more complex syntax than C; this query captures the
most common patterns.  Template specialisations, operator overloads, and
lambdas are not yet covered but can be added incrementally.
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor


class CppExtractor(ASTExtractor):
    """Tree-sitter based extractor for C++ source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("cpp", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Class / struct definitions ───────────────────────────────────────────────
(class_specifier
  name: (type_identifier) @def.class.name
  body: (field_declaration_list))

(struct_specifier
  name: (type_identifier) @def.struct.name
  body: (field_declaration_list))

; ── Namespace definitions ─────────────────────────────────────────────────────
(namespace_definition
  name: (namespace_identifier) @def.namespace.name)

; ── Top-level function definitions ───────────────────────────────────────────
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @def.function.name
    parameters: (parameter_list) @def.function.params))

; Pointer-returning functions  e.g. int *foo()
(function_definition
  declarator: (pointer_declarator
    declarator: (function_declarator
      declarator: (identifier) @def.function.name
      parameters: (parameter_list) @def.function.params)))

; ── Member / method definitions  (Foo::bar or just bar inside a class body) ──
(function_definition
  declarator: (function_declarator
    declarator: (field_identifier) @def.method.name
    parameters: (parameter_list) @def.method.params))

; Qualified method definitions  e.g. void Foo::bar() { ... }
(function_definition
  declarator: (function_declarator
    declarator: (qualified_identifier
      name: (identifier) @def.method.name)
    parameters: (parameter_list) @def.method.params))

; ── Preprocessor includes ─────────────────────────────────────────────────────
(preproc_include
  path: (_) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (field_expression
    field: (field_identifier) @ref.call))

(call_expression
  function: (qualified_identifier
    name: (identifier) @ref.call))
"""
