"""
context/languages/python.py — Python ASTExtractor subclass.

Capture coverage:
  - class definitions (with optional base-class list and docstring)
  - function / method definitions (with params, return type, docstring)
  - import statements (plain and from-import)
  - call expressions

Methods are distinguished from module-level functions at query time:
methods are ``function_definition`` nodes nested directly inside a
``class_definition`` body block.  Top-level and nested standalone
functions use ``@def.function.*``; class-body functions use
``@def.method.*``.
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor


class PythonExtractor(ASTExtractor):
    """Tree-sitter based extractor for Python source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("python", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Class definitions ────────────────────────────────────────────────────────
(class_definition
  name: (identifier) @def.class.name
  superclasses: (argument_list)? @def.class.bases
  body: (block
    (expression_statement
      (string) @def.class.docstring)?))

; ── Method definitions (function inside a class body) ────────────────────────
(class_definition
  body: (block
    (function_definition
      name: (identifier) @def.method.name
      parameters: (parameters) @def.method.params
      return_type: (type)? @def.method.return_type
      body: (block
        (expression_statement
          (string) @def.method.docstring)?))))

; ── Module-level / nested function definitions ───────────────────────────────
(module
  (function_definition
    name: (identifier) @def.function.name
    parameters: (parameters) @def.function.params
    return_type: (type)? @def.function.return_type
    body: (block
      (expression_statement
        (string) @def.function.docstring)?)))

; Decorated module-level functions
(module
  (decorated_definition
    definition: (function_definition
      name: (identifier) @def.function.name
      parameters: (parameters) @def.function.params
      return_type: (type)? @def.function.return_type
      body: (block
        (expression_statement
          (string) @def.function.docstring)?))))

; Nested functions inside other functions
(function_definition
  body: (block
    (function_definition
      name: (identifier) @def.function.name
      parameters: (parameters) @def.function.params
      return_type: (type)? @def.function.return_type)))

; ── Imports ───────────────────────────────────────────────────────────────────
(import_statement
  name: (_) @ref.import.module)

(import_from_statement
  module_name: (_) @ref.import.module)

(import_from_statement
  name: (_) @ref.import.symbol)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call
  function: [
    (identifier) @ref.call
    (attribute
      attribute: (identifier) @ref.call)
  ])

; ── Entry point: if __name__ == "__main__": ───────────────────────────────────
(if_statement
  condition: (comparison_operator
    (identifier) @def.entry_point.name
    "=="
    (string) @def.entry_point.value)
  (#eq? @def.entry_point.name "__name__")
  (#match? @def.entry_point.value "['\"]__main__['\"]")) @def.entry_point.invocation
"""
