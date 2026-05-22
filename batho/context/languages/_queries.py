"""
context/languages/_queries.py — Consolidated tree-sitter queries for all languages.

This module provides a single source of truth for all tree-sitter SCM queries
used by programming language extractors. Markup/config languages (JSON, YAML,
Markdown, HTML, CSS, TOML, HCL) use custom extractors with regex/parsing logic
and are not included here.

Usage:
    from batho.context.languages._queries import TREE_SITTER_QUERIES
    query = TREE_SITTER_QUERIES["python"]
"""

from __future__ import annotations

# Import common query fragments
from ._common import CommonQueries


# =============================================================================
# Python
# =============================================================================

PYTHON_QUERY = r"""
; ── Class definitions ────────────────────────────────────────────────────────
(class_definition
  name: (identifier) @def.class.name
  superclasses: (argument_list)? @def.class.bases
  body: (block
    (expression_statement
      (string) @def.class.docstring)?))

; ── Method definitions (function inside a class body) ────────────────────────────
(class_definition
  body: (block
    (function_definition
      name: (identifier) @def.method.name
      parameters: (parameters) @def.method.params
      return_type: (type)? @def.method.return_type
      body: (block
        (expression_statement
          (string) @def.method.docstring)?))))

; ── Module-level / nested function definitions ────────────────────────────────
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

; ── Entry point: if __name__ == "__main__": ─────────────────────────────────
(if_statement
  condition: (comparison_operator
    (identifier) @def.entry_point.name
    "=="
    (string) @def.entry_point.value)
  (#eq? @def.entry_point.name "__name__")
  (#match? @def.entry_point.value "['\"]__main__['\"]")) @def.entry_point.invocation
"""


# =============================================================================
# JavaScript (with CommonQueries entry points)
# =============================================================================

JAVASCRIPT_QUERY = (
    r"""
; ── Function declarations ───────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (formal_parameters) @def.function.params)

; ── Arrow functions assigned to a const ────────────────────────────────────────
(variable_declarator
  name: (identifier) @def.function.name
  value: (arrow_function
    parameters: (_) @def.function.params))

; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (identifier) @def.class.name)

(class_declaration
  (class_heritage
    (_) @def.class.extends))

; ── Method definitions ───────────────────────────────────────────────────────
(method_definition
  name: (property_identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params)

; ── Imports ───────────────────────────────────────────────────────────────────
(import_statement
  source: (string) @ref.import.module)

(call_expression
  function: (identifier) @_require_fn
  arguments: (arguments
    (string) @ref.import.require)
  (#eq? @_require_fn "require"))

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (member_expression
    property: (property_identifier) @ref.call))
"""
    + CommonQueries.http_server_entry_points()
    + CommonQueries.react_render_entry_points()
)


# =============================================================================
# TypeScript (with CommonQueries entry points)
# =============================================================================

TYPESCRIPT_QUERY = (
    r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (type_identifier) @def.class.name
  (class_heritage
    (implements_clause
      (type_identifier) @def.class.implements))?)

(class_declaration
  (class_heritage
    (extends_clause
      (_) @def.class.extends)))

; ── Interface declarations ────────────────────────────────────────────────────
(interface_declaration
  name: (type_identifier) @def.interface.name)

; ── Method definitions ───────────────────────────────────────────────────────
(method_definition
  (accessibility_modifier)? @def.method.visibility
  name: (property_identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params
  return_type: (type_annotation)? @def.method.return_type)

; ── Function declarations ────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (formal_parameters) @def.function.params
  return_type: (type_annotation)? @def.function.return_type)

; ── Arrow functions assigned to a const ───────────────────────────────────────
(variable_declarator
  name: (identifier) @def.function.name
  value: (arrow_function
    parameters: (_) @def.function.params
    return_type: (type_annotation)? @def.function.return_type))

; ── Imports ───────────────────────────────────────────────────────────────────
(import_statement
  source: (string) @ref.import.module)

(call_expression
  function: (identifier) @_require_fn
  arguments: (arguments
    (string) @ref.import.require)
  (#eq? @_require_fn "require"))

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (member_expression
    property: (property_identifier) @ref.call))
"""
    + CommonQueries.http_server_entry_points()
    + CommonQueries.react_render_entry_points()
)


# =============================================================================
# Rust
# =============================================================================

RUST_QUERY = r"""
; ── Struct definitions ────────────────────────────────────────────────────────
(struct_item
  name: (type_identifier) @def.struct.name)

; ── Enum definitions ──────────────────────────────────────────────────────────
(enum_item
  name: (type_identifier) @def.enum.name)

; ── Trait definitions ─────────────────────────────────────────────────────────
(trait_item
  name: (type_identifier) @def.trait.name)

; ── Free function definitions (source-file scope only) ───────────────────────
(source_file
  (function_item
    (visibility_modifier)? @def.function.visibility
    name: (identifier) @def.function.name
    parameters: (parameters) @def.function.params
    return_type: (_)? @def.function.return_type))

; ── Methods inside impl blocks ───────────────────────────────────────────────
(impl_item
  trait: (type_identifier)? @def.method.trait
  body: (declaration_list
    (function_item
      (visibility_modifier)? @def.method.visibility
      name: (identifier) @def.method.name
      parameters: (parameters) @def.method.params
      return_type: (_)? @def.method.return_type)))

; ── Use declarations (imports) ────────────────────────────────────────────────
(use_declaration
  argument: (_) @ref.import.module)

; ── Calls ────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (field_expression
    field: (field_identifier) @ref.call))
"""


# =============================================================================
# Go
# =============================================================================

GO_QUERY = r"""
; ── Function declarations ────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (parameter_list) @def.function.params
  result: (_)? @def.function.return_type)

; ── Method declarations ────────────────────────────────────────────────────
(method_declaration
  receiver: (parameter_list) @def.method.receiver
  name: (field_identifier) @def.method.name
  parameters: (parameter_list) @def.method.params
  result: (_)? @def.method.return_type)

; ── Struct type declarations ─────────────────────────────────────────────────
(type_declaration
  (type_spec
    name: (type_identifier) @def.struct.name
    type: (struct_type)))

; ── Interface type declarations ──────────────────────────────────────────────
(type_declaration
  (type_spec
    name: (type_identifier) @def.interface.name
    type: (interface_type)))

; ── Imports ───────────────────────────────────────────────────────────────────
(import_spec
  path: (interpreted_string_literal) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (selector_expression
    field: (field_identifier) @ref.call))
"""


# =============================================================================
# Java
# =============================================================================

JAVA_QUERY = r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  (modifiers)? @def.class.visibility
  name: (identifier) @def.class.name
  superclass: (superclass
    (type_identifier) @def.class.extends)?
  interfaces: (super_interfaces
    (type_list
      (type_identifier) @def.class.implements))?)

; ── Method declarations ─────────────────────────────────────────────────────
(method_declaration
  (modifiers)? @def.method.visibility
  type: (_) @def.method.return_type
  name: (identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params)

; ── Constructor declarations (treated as methods) ─────────────────────────────
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

; ── Imports ─────────────────────────────────────────────────────────────────
(import_declaration
  (scoped_identifier) @ref.import.module)

(import_declaration
  "static"
  (scoped_identifier) @ref.import.static)

; ── Calls ────────────────────────────────────────────────────────────────────
(method_invocation
  name: (identifier) @ref.call)
"""


# =============================================================================
# Ruby
# =============================================================================

RUBY_QUERY = r"""
; ── Class definitions ────────────────────────────────────────────────────────
(class
  name: (constant) @def.class.name
  superclass: (superclass
    (constant) @def.class.extends)?)

; ── Module definitions ────────────────────────────────────────────────────────
(module
  name: (constant) @def.namespace.name)

; ── Instance method definitions ─────────────────────────────────────────────
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

; ── Method calls ─────────────────────────────────────────────────────────────
(call
  method: (identifier) @ref.call)
"""


# =============================================================================
# C
# =============================================================================

C_QUERY = r"""
; ── Function definitions ────────────────────────────────────────────────────
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

; ── Struct definitions ───────────────────────────────────────────────────────
(struct_specifier
  name: (type_identifier) @def.struct.name
  body: (field_declaration_list))

; Typedef struct { ... } Foo;
(type_definition
  type: (struct_specifier
    body: (field_declaration_list))
  declarator: (type_identifier) @def.struct.name)

; ── Preprocessor includes ────────────────────────────────────────────────────
(preproc_include
  path: (_) @ref.import.module)

; ── Calls ────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)
"""


# =============================================================================
# C++
# =============================================================================

CPP_QUERY = r"""
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

; ── Top-level function definitions ──────────────────────────────────────────
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

; ── Member / method definitions  (Foo::bar or just bar inside a class body) ─
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

; ── Preprocessor includes ────────────────────────────────────────────────────
(preproc_include
  path: (_) @ref.import.module)

; ── Calls ────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (field_expression
    field: (field_identifier) @ref.call))

(call_expression
  function: (qualified_identifier
    name: (identifier) @ref.call))
"""


# =============================================================================
# C#
# =============================================================================

CSHARP_QUERY = r"""
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


# =============================================================================
# PHP
# =============================================================================

PHP_QUERY = r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (name) @def.class.name
  (extends_clause (name) @def.class.extends)?
  (implements_clause (name) @def.class.implements)?)

; ── Interface declarations ────────────────────────────────────────────────────
(interface_declaration
  name: (name) @def.interface.name)

; ── Trait declarations ────────────────────────────────────────────────────────
(trait_declaration
  name: (name) @def.trait.name)

; ── Method definitions ────────────────────────────────────────────────────────
(method_declaration
  (visibility_modifier)? @def.method.visibility
  (static_modifier)? @def.method.static
  name: (name) @def.method.name
  parameters: (formal_parameters) @def.method.params
  (return_type)? @def.method.return_type)

; ── Function declarations ─────────────────────────────────────────────────────
(function_declaration
  name: (name) @def.function.name
  parameters: (formal_parameters) @def.function.params
  (return_type)? @def.function.return_type)

; ── Use statements (imports) ──────────────────────────────────────────────────
(use_declaration
  (namespace_use_clause (name) @ref.import.module))

; ── Calls ─────────────────────────────────────────────────────────────────────
(function_call_expression
  function: (qualified_name) @ref.call)

(function_call_expression
  function: (member_access_expression
    name: (name) @ref.call))

(method_call_expression
  method: (name) @ref.call)

(method_call_expression
  object: (_) @ref.call)
"""


# =============================================================================
# Kotlin
# =============================================================================

KOTLIN_QUERY = r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (type_identifier) @def.class.name
  (primary_constructor
    (constructor_parameters) @def.class.constructor)?
  (superclass
    (user_type
      (type_identifier) @def.class.extends))?
  (delegation_specifiers
    (user_type
      (type_identifier) @def.class.implements))?)

; ── Interface declarations ────────────────────────────────────────────────────
(interface_declaration
  name: (type_identifier) @def.interface.name)

; ── Object declarations (singletons) ───────────────────────────────────────────
(object_declaration
  name: (type_identifier) @def.object.name)

; ── Method declarations (functions inside classes) ────────────────────────────
(class_declaration
  (class_body
    (function_declaration
      (modifiers)? @def.method.visibility
      (simple_identifier) @def.method.name
      (parameters) @def.method.params
      (type) @def.method.return_type)))

; ── Function declarations (top-level) ─────────────────────────────────────────
(function_declaration
  (modifiers)? @def.function.visibility
  (simple_identifier) @def.function.name
  (parameters) @def.function.params
  (type) @def.function.return_type)

; ── Import statements ──────────────────────────────────────────────────────────
(import_header
  (imported_namespace) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  (simple_identifier) @ref.call)

(call_expression
  (member_access_expression
    (simple_identifier) @ref.call))
"""


# =============================================================================
# Swift
# =============================================================================

SWIFT_QUERY = r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (type_identifier) @def.class.name
  (superclass_clause
    (type_identifier) @def.class.extends)?
  (protocols
    (type_identifier) @def.class.implements)?)

; ── Struct declarations ────────────────────────────────────────────────────────
(struct_declaration
  name: (type_identifier) @def.struct.name
  (protocols
    (type_identifier) @def.struct.implements)?)

; ── Enum declarations ──────────────────────────────────────────────────────────
(enum_declaration
  name: (type_identifier) @def.enum.name
  (protocols
    (type_identifier) @def.enum.implements)?)

; ── Protocol declarations ─────────────────────────────────────────────────────
(protocol_declaration
  name: (type_identifier) @def.protocol.name)

; ── Function declarations (top-level) ───────────────────────────────────────────
(function_declaration
  name: (simple_identifier) @def.function.name
  (parameter_list) @def.function.params
  (type) @def.function.return_type)

; ── Method declarations (inside classes/structs/enums) ─────────────────────────
(class_declaration
  (class_body
    (function_declaration
      name: (simple_identifier) @def.method.name
      (parameter_list) @def.method.params
      (type) @def.method.return_type)))

(struct_declaration
  (struct_body
    (function_declaration
      name: (simple_identifier) @def.method.name
      (parameter_list) @def.method.params
      (type) @def.method.return_type)))

(enum_declaration
  (enum_body
    (function_declaration
      name: (simple_identifier) @def.method.name
      (parameter_list) @def.method.params
      (type) @def.method.return_type)))

; ── Import statements ──────────────────────────────────────────────────────────
(import_declaration
  (import_path
    (simple_identifier) @ref.import.module))

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  (simple_identifier) @ref.call)

(call_expression
  (member_expression
    (simple_identifier) @ref.call))
"""


# =============================================================================
# Scala
# =============================================================================

SCALA_QUERY = r"""
; ── Class definitions ────────────────────────────────────────────────────────
(class_definition
  name: (identifier) @def.class.name
  (extends_clause
    (type_identifier) @def.class.extends)?
  (with_clause
    (type_identifier) @def.class.implements)?)

; ── Object definitions (singletons) ──────────────────────────────────────────
(object_definition
  name: (identifier) @def.object.name
  (extends_clause
    (type_identifier) @def.object.extends)?)

; ── Trait definitions ─────────────────────────────────────────────────────────
(trait_definition
  name: (identifier) @def.trait.name
  (extends_clause
    (type_identifier) @def.trait.extends)?)

; ── Method definitions ───────────────────────────────────────────────────────
(function_definition
  name: (identifier) @def.method.name
  parameters: (parameters) @def.method.params
  (type_identifier)? @def.method.return_type)

; ── Import statements ───────────────────────────────────────────────────────────
(import_declaration
  (stable_identifier) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  (identifier) @ref.call)
"""


# =============================================================================
# Dart
# =============================================================================

DART_QUERY = r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_definition
  name: (identifier) @def.class.name
  (superclass
    (type_identifier) @def.class.extends)?
  (mixins
    (type_identifier) @def.class.implements)?)

; ── Method declarations ───────────────────────────────────────────────────────
(method_declaration
  (final_or_const)? @def.method.static
  (type_identifier)? @def.method.return_type
  name: (identifier) @def.method.name
  (formal_parameter_list) @def.method.params)

; ── Function declarations ────────────────────────────────────────────────────
(function_signature
  (type_identifier)? @def.function.return_type
  name: (identifier) @def.function.name
  (formal_parameter_list) @def.function.params)

; ── Import statements ───────────────────────────────────────────────────────────
(import_statement
  (configurable_uri) @ref.import.module)

(import_statement
  (dotted_identifier_list) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(method_invocation
  (identifier) @ref.call)
"""


# =============================================================================
# Additional Programming Languages
# =============================================================================

BASH_QUERY = r"""
; ── Function definitions ────────────────────────────────────────────────────
(function_definition
  name: (word) @def.function.name)

; ── Command calls (as references) ────────────────────────────────────────────
(command
  name: (word) @ref.call)
"""

LUA_QUERY = r"""
; ── Function definitions ────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (parameters) @def.function.params)

; ── Local function definitions ───────────────────────────────────────────────
(local_function_declaration
  name: (identifier) @def.function.name
  parameters: (parameters) @def.function.params)

; ── Function calls ────────────────────────────────────────────────────────────
(function_call
  (identifier) @ref.call)
"""

R_QUERY = r"""
; ── Function definitions ────────────────────────────────────────────────────
(function_definition
  name: (identifier) @def.function.name
  parameters: (parameters) @def.function.params)

; ── Function calls ────────────────────────────────────────────────────────────
(call
  (identifier) @ref.call)
"""

PERL_QUERY = r"""
; ── Subroutine definitions ───────────────────────────────────────────────────
(subroutine_declaration_statement
  name: (identifier) @def.function.name)

; ── Subroutine calls ───────────────────────────────────────────────────────────
(call_expression
  (identifier) @ref.call)
"""

JULIA_QUERY = r"""
; ── Function definitions ────────────────────────────────────────────────────
(function_definition
  name: (identifier) @def.function.name
  parameters: (parameter_list) @def.function.params)

; ── Short function definitions ───────────────────────────────────────────────
(assignment
  . (call_expression
    (identifier) @def.function.name
    (argument_list) @def.function.params))

; ── Function calls ────────────────────────────────────────────────────────────
(call_expression
  (identifier) @ref.call)
"""

HASKELL_QUERY = r"""
; ── Function bindings ─────────────────────────────────────────────────────────
(function
  name: (variable) @def.function.name
  patterns: (patterns) @def.function.params)

; ── Top-level function declarations ─────────────────────────────────────────
(signature
  name: (variable) @def.function.name
  type: (type) @def.function.return_type)
"""

ERLANG_QUERY = r"""
; ── Function declarations ───────────────────────────────────────────────────
(function_declaration
  name: (atom) @def.function.name
  (function_clause
    (arguments) @def.function.params))

; ── Function calls ────────────────────────────────────────────────────────────
(call
  (atom) @ref.call)
"""

OCAML_QUERY = r"""
; ── Function bindings ─────────────────────────────────────────────────────────
(let_binding
  pattern: (value_name) @def.function.name
  (function_expression
    (parameter) @def.function.params))

; ── Module definitions ────────────────────────────────────────────────────────
(module_definition
  name: (module_name) @def.namespace.name)

; ── Module types ──────────────────────────────────────────────────────────────
(module_type_definition
  name: (module_name) @def.interface.name)
"""

HACK_QUERY = r"""
; ── Function declarations ─────────────────────────────────────────────────────
(function_declaration
  name: (name) @def.function.name
  parameters: (formal_parameters) @def.function.params
  (type_specifier)? @def.function.return_type)

; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (name) @def.class.name
  (extends_clause (name) @def.class.extends)?
  (implements_clause (name) @def.class.implements)?)

; ── Method declarations ───────────────────────────────────────────────────────
(method_declaration
  (visibility_modifier)? @def.method.visibility
  name: (name) @def.method.name
  parameters: (formal_parameters) @def.method.params
  (type_specifier)? @def.method.return_type)
"""

ZIG_QUERY = r"""
; ── Function declarations ────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  (parameters) @def.function.params
  (type)? @def.function.return_type)

; ── Struct declarations ───────────────────────────────────────────────────────
(container_field
  (identifier) @def.field.name
  (type)? @def.field.type)
"""

VERILOG_QUERY = r"""
; ── Module declarations ─────────────────────────────────────────────────────
(module_declaration
  name: (module_identifier) @def.module.name)

; ── Function declarations ────────────────────────────────────────────────────
(function_declaration
  (function_body_declaration
    name: (function_identifier) @def.function.name))

; ── Task declarations ─────────────────────────────────────────────────────────
(task_declaration
  (task_body_declaration
    name: (task_identifier) @def.task.name))
"""

OBJECTIVEC_QUERY = r"""
; ── Class interface declarations ───────────────────────────────────────────────
(class_interface
  !category
  "@interface"
  (identifier) @def.class.name
  (":" (identifier) @def.class.extends)?
  (parameterized_arguments
    (type_name
      (type_identifier) @def.class.implements))?)

; ── Inheritance / protocol relationships ──────────────────────────────────────
(class_interface
  ":" (identifier) @ref.inherit)

(class_interface
  (parameterized_arguments
    (type_name
      (type_identifier) @ref.implement)))

; ── Categories and class extensions ────────────────────────────────────────────
(class_interface
  "@interface"
  (identifier) @def.interface.extends
  "(" category: (identifier) @def.interface.name ")")

(class_interface
  "@interface"
  (identifier) @def.interface.name
  "(" ")")

; ── Protocol declarations ───────────────────────────────────────────────────────
(protocol_declaration
  (identifier) @def.protocol.name
  (protocol_reference_list
    (identifier) @def.protocol.implements)?)

(protocol_declaration
  (protocol_reference_list
    (identifier) @ref.implement))

; ── Method declarations / definitions ─────────────────────────────────────────
(method_declaration
  ["-" "+"] @def.method.receiver
  (method_type) @def.method.return_type
  (identifier) @def.method.name
  (method_parameter)? @def.method.params)

(method_definition
  ["-" "+"] @def.method.receiver
  (method_type) @def.method.return_type
  (identifier) @def.method.name
  (method_parameter)? @def.method.params)

; ── Property declarations ─────────────────────────────────────────────────────
(property_declaration
  (property_attributes_declaration)? @def.field.visibility
  (struct_declaration
    [(type_identifier) (primitive_type)] @def.field.type
    (struct_declarator
      [
        (identifier) @def.field.name
        (pointer_declarator
          (identifier) @def.field.name)
      ])))

; ── Class implementation ────────────────────────────────────────────────────────
(class_implementation (identifier) @def.class.name)

; ── Import statements (#import) ────────────────────────────────────────────────
(preproc_include (system_lib_string) @ref.import.module)
(preproc_include (string_literal) @ref.import.module)

; ── Message sends (selector calls) ─────────────────────────────────────────────
(message_expression
  (identifier)
  (identifier) @ref.call)
"""


# =============================================================================
# Query Registry
# =============================================================================

TREE_SITTER_QUERIES: dict[str, str] = {
    # Core programming languages
    "python": PYTHON_QUERY,
    "javascript": JAVASCRIPT_QUERY,
    "typescript": TYPESCRIPT_QUERY,
    "rust": RUST_QUERY,
    "go": GO_QUERY,
    "java": JAVA_QUERY,
    "ruby": RUBY_QUERY,
    "c": C_QUERY,
    "cpp": CPP_QUERY,
    "csharp": CSHARP_QUERY,
    # Additional programming languages
    "php": PHP_QUERY,
    "kotlin": KOTLIN_QUERY,
    "swift": SWIFT_QUERY,
    "scala": SCALA_QUERY,
    "dart": DART_QUERY,
    "bash": BASH_QUERY,
    "lua": LUA_QUERY,
    "r": R_QUERY,
    "perl": PERL_QUERY,
    "julia": JULIA_QUERY,
    "haskell": HASKELL_QUERY,
    "erlang": ERLANG_QUERY,
    "ocaml": OCAML_QUERY,
    "hack": HACK_QUERY,
    "zig": ZIG_QUERY,
    "verilog": VERILOG_QUERY,
    "objectivec": OBJECTIVEC_QUERY,
}


def get_query(language: str) -> str | None:
    """Get the tree-sitter query for a language."""
    return TREE_SITTER_QUERIES.get(language.lower())


def list_supported_languages() -> list[str]:
    """Return a sorted list of supported language identifiers."""
    return sorted(TREE_SITTER_QUERIES.keys())
