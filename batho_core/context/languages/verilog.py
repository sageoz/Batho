"""
context/languages/verilog.py — Verilog/SystemVerilog ASTExtractor subclass.

Capture coverage:
  - module definitions
  - function definitions
  - task definitions
  - class definitions
  - interface definitions
  - parameter definitions
  - port declarations
  - signal/wire declarations
  - include statements
  - function/task calls
"""

from __future__ import annotations

from ..extractor import ASTExtractor


class VerilogExtractor(ASTExtractor):
    """Tree-sitter based extractor for Verilog/SystemVerilog source files."""

    def __init__(self) -> None:
        super().__init__("verilog")

    def _query_source(self) -> str:
        return r"""
; ── Module definitions ───────────────────────────────────────────────────────────
(module_declaration
  name: (module_identifier) @def.module.name
  (module_body
    (port_declaration
      (identifier) @def.field.name)))

; ── Function definitions ────────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  (function_body)? @def.function.body)

; ── Task definitions ───────────────────────────────────────────────────────────
(task_declaration
  name: (identifier) @def.function.name
  (task_body)? @def.function.body)

; ── Class definitions ───────────────────────────────────────────────────────────
(class_declaration
  name: (identifier) @def.class.name
  (class_body
    (property_declaration
      (list_of_variables
        (variable_identifier) @def.field.name))))

; ── Interface definitions ───────────────────────────────────────────────────────
(interface_declaration
  name: (identifier) @def.interface.name
  (interface_body)? @def.interface.body)

; ── Package definitions ─────────────────────────────────────────────────────────
(package_declaration
  name: (identifier) @def.module.name
  (package_body)? @def.module.body)

; ── Parameter definitions ───────────────────────────────────────────────────────
(parameter_declaration
  (list_of_param_assignments
    (param_assignment
      (identifier) @def.constant.name)))

(local_parameter_declaration
  (list_of_param_assignments
    (param_assignment
      (identifier) @def.constant.name)))

; ── Signal declarations ─────────────────────────────────────────────────────────
(net_declaration
  (list_of_identifiers
    (identifier) @def.field.name))

(variable_declaration
  (list_of_variables
    (variable_identifier) @def.field.name))

; ── Include statements ──────────────────────────────────────────────────────────
(preproc_include
  (string_literal) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call
  (identifier) @ref.call)

(system_task_call
  (identifier) @ref.call)

(method_call
  (identifier) @ref.call)
"""
