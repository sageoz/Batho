"""
context/languages/c.py — C ASTExtractor subclass.

Capture coverage:
  - function definitions (with declarator name and parameter list)
  - struct specifiers with a tag name (mapped to def.struct)
  - preprocessor ``#include`` directives (mapped to ref.import.module)
  - call expressions (mapped to ref.call)

C has no classes, methods, or visibility modifiers.  All callables are
free functions.  Typedef'd structs have their name captured via the
``type_definition`` → ``type_declarator`` path as a separate pattern.
"""

from __future__ import annotations

from typing import Any

from batho.modules.extraction.extractor import ASTExtractor


class CExtractor(ASTExtractor):
    """Tree-sitter based extractor for C source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("c", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Function definitions ─────────────────────────────────────────────────────
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @def.function.name
    parameters: (parameter_list) @def.function.params))

; Pointer-returning functions  e.g. int *foo(void)
(function_definition
  declarator: (pointer_declarator
    declarator: (function_declarator
      declarator: (identifier) @def.function.name
      parameters: (parameter_list) @def.function.params)))

; ── Struct definitions ────────────────────────────────────────────────────────
(struct_specifier
  name: (type_identifier) @def.struct.name
  body: (field_declaration_list))

; Typedef struct { ... } Foo;
(type_definition
  type: (struct_specifier
    body: (field_declaration_list))
  declarator: (type_identifier) @def.struct.name)

; ── Preprocessor includes ─────────────────────────────────────────────────────
(preproc_include
  path: (_) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)
"""
