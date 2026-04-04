"""
context/languages/scala.scala — Scala ASTExtractor subclass.

Capture coverage:
  - class declarations (with optional extends, with)
  - object declarations (singletons)
  - trait declarations
  - function definitions (with params, return type)
  - method definitions (inside classes/objects/traits)
  - import statements
  - function/method calls
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor


class ScalaExtractor(ASTExtractor):
    """Tree-sitter based extractor for Scala source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("scala", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (identifier) @def.class.name
  (class_parent
    (type) @def.class.extends)?
  (class_template
    (with_clause
      (type) @def.class.implements)?))

; ── Object declarations (singletons) ───────────────────────────────────────────
(object_declaration
  name: (identifier) @def.object.name)

; ── Trait declarations ────────────────────────────────────────────────────────
(trait_declaration
  name: (identifier) @def.trait.name
  (trait_template
    (with_clause
      (type) @def.trait.implements)?))

; ── Function definitions (top-level) ───────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  (parameters) @def.function.params
  (type) @def.function.return_type)

(function_definition
  name: (identifier) @def.function.name
  (parameters) @def.function.params
  (type) @def.function.return_type)

; ── Method definitions (inside classes/objects/traits) ────────────────────────
(class_declaration
  (class_body
    (function_definition
      name: (identifier) @def.method.name
      (parameters) @def.method.params
      (type) @def.method.return_type)))

(object_declaration
  (object_body
    (function_definition
      name: (identifier) @def.method.name
      (parameters) @def.method.params
      (type) @def.method.return_type)))

(trait_declaration
  (trait_body
    (function_definition
      name: (identifier) @def.method.name
      (parameters) @def.method.params
      (type) @def.method.return_type)))

; ── Import statements ──────────────────────────────────────────────────────────
(import_declaration
  (import_expression
    (identifier) @ref.import.module))

(import_declaration
  (import_expression
    (stable_identifier
      (identifier) @ref.import.module)))

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  (identifier) @ref.call)

(call_expression
  (select_expression
    (identifier) @ref.call))
"""
