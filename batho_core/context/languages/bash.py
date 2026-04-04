"""
context/languages/bash.py — Bash ASTExtractor subclass.

Capture coverage:
  - function definitions (with params)
  - alias definitions
  - variable assignments
  - source/include statements
  - function calls
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class BashExtractor(ASTExtractor):
    """Tree-sitter based extractor for Bash script files."""

    def __init__(self) -> None:
        super().__init__("bash")

    def _query_source(self) -> str:
        return r"""
; ── Function definitions ───────────────────────────────────────────────────────
(function_definition
  name: (word) @def.function.name
  parameters: (parameter_list) @def.function.params)

; ── Alias definitions ────────────────────────────────────────────────────────────
(alias_definition
  name: (word) @def.constant.name
  value: (string) @def.constant.value)

; ── Variable assignments ────────────────────────────────────────────────────────
(variable_assignment
  name: (variable_name) @def.field.name
  value: (_) @def.field.value)

; ── Source/Include statements ─────────────────────────────────────────────────
(command
  (word) @_source_cmd
  (word) @ref.import.path
  (#eq? @_source_cmd "source"))

(command
  (word) @_source_cmd
  (string) @ref.import.path
  (#eq? @_source_cmd "source"))

(command
  (word) @_dot_cmd
  (word) @ref.import.path
  (#eq? @_dot_cmd "."))

(command
  (word) @_dot_cmd
  (string) @ref.import.path
  (#eq? @_dot_cmd "."))

; ── Calls ─────────────────────────────────────────────────────────────────────
(command
  (word) @ref.call)

(command
  (compound_command
    (subshell
      (command
        (word) @ref.call))))
"""
