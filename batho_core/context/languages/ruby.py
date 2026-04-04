"""
context/languages/ruby.py — Ruby ASTExtractor subclass.

Capture coverage:
  - class definitions (mapped to def.class)
  - module definitions (mapped to def.namespace)
  - method definitions (mapped to def.method)
  - singleton method definitions / class methods (mapped to def.method)
  - require / require_relative calls (mapped to ref.import.module)
  - method call expressions (mapped to ref.call)

Ruby's tree-sitter grammar uses ``class``, ``module``, ``method``, and
``singleton_method`` as the primary node types.
"""

from __future__ import annotations

from typing import Any

from ..extractor import ASTExtractor


class RubyExtractor(ASTExtractor):
    """Tree-sitter based extractor for Ruby source files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("ruby", parsing_config)

    def _query_source(self) -> str:
        return r"""
; ── Class definitions ────────────────────────────────────────────────────────
(class
  name: (constant) @def.class.name
  superclass: (superclass
    (constant) @def.class.extends)?)

; ── Module definitions ────────────────────────────────────────────────────────
(module
  name: (constant) @def.namespace.name)

; ── Instance method definitions ──────────────────────────────────────────────
(method
  name: (identifier) @def.method.name
  parameters: (method_parameters)? @def.method.params)

; ── Singleton / class method definitions ─────────────────────────────────────
(singleton_method
  name: (identifier) @def.method.name
  parameters: (method_parameters)? @def.method.params)

; ── Require / require_relative (imports) ──────────────────────────────────────
(call
  method: (identifier) @_require_method
  arguments: (argument_list
    (string) @ref.import.module)
  (#match? @_require_method "^require(_relative)?$"))

(call
  method: (identifier) @_load_method
  arguments: (argument_list
    (string) @ref.import.load)
  (#eq? @_load_method "load"))

; ── Method calls ──────────────────────────────────────────────────────────────
(call
  method: (identifier) @ref.call)
"""
