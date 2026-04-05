"""
context/languages/dart.dart — Dart ASTExtractor subclass.

Capture coverage:
  - class declarations (with optional extends, with, implements)
  - mixin declarations
  - method definitions (with params, return type)
  - function definitions (with params, return type)
  - constructor definitions
  - import statements
  - function/method calls
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor


class DartExtractor(ASTExtractor):
    """Tree-sitter based extractor for Dart source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("dart", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (type_identifier) @def.class.name
  (extends_clause
    (type_identifier) @def.class.extends)?
  (with_clause
    (type_identifier) @def.class.with)?
  (implements_clause
    (type_identifier) @def.class.implements)?)

; ── Mixin declarations ─────────────────────────────────────────────────────────
(mixin_declaration
  name: (type_identifier) @def.mixin.name
  (implements_clause
    (type_identifier) @def.mixin.implements)?)

; ── Method definitions (inside classes) ────────────────────────────────────────
(class_declaration
  (class_body
    (method_definition
      (type) @def.method.return_type
      (identifier) @def.method.name
      (formal_parameters) @def.method.params)))

; ── Constructor definitions ────────────────────────────────────────────────────
(class_declaration
  (class_body
    (constructor_definition
      (identifier) @def.method.name
      (formal_parameters) @def.method.params)))

; ── Function definitions (top-level) ───────────────────────────────────────────
(function_signature_function
  (type) @def.function.return_type
  (identifier) @def.function.name
  (formal_parameters) @def.function.params)

(function_expression
  (identifier) @def.function.name
  (formal_parameters) @def.function.params)

; ── Import statements ──────────────────────────────────────────────────────────
(import_directive
  (string (string_content) @ref.import.module))

; ── Calls ─────────────────────────────────────────────────────────────────────
(method_invocation
  (identifier) @ref.call)

(method_invocation
  (property_access_expression
    (identifier) @ref.call))

(function_expression_invocation
  (identifier) @ref.call)
"""
