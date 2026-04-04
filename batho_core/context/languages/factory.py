"""
backend/context/languages/factory.py — Factory for creating ASTExtractor instances.

This module provides a declarative, configuration-based approach to creating
language extractors, eliminating the ~40 lines of boilerplate per extractor.

Instead of defining a new class for each language:

    class PythonExtractor(ASTExtractor):
        def __init__(self) -> None:
            super().__init__("python")

        def _query_source(self) -> str:
            return PYTHON_QUERY

You can simply use:

    extractor = create_extractor("python", PYTHON_QUERY)

Or use the pre-registered extractors:

    from batho_core.context.languages.factory import get_extractor
    extractor = get_extractor("python")

Estimated savings: ~40 lines per extractor × 30 extractors = 1,200 lines → ~200 lines
"""

from __future__ import annotations

from batho_core.context.extractor import ASTExtractor


class ConfigurableExtractor(ASTExtractor):
    """
    A configurable ASTExtractor that accepts query source at initialization.

    This eliminates the need to subclass ASTExtractor for each language.
    The language name and query source are provided at instantiation time
    rather than through abstract method overrides.

    Args:
        language: Language identifier for tree-sitter (e.g., "python", "rust")
        query_source: Tree-sitter SCM query string for extracting entities
    """

    def __init__(self, language: str, query_source: str) -> None:
        """
        Initialize a configurable extractor.

        Args:
            language: Language identifier for tree-sitter-language-pack
            query_source: Tree-sitter SCM query string
        """
        self._query: str = query_source
        super().__init__(language)

    def _query_source(self) -> str:
        """Return the configured query source."""
        return self._query


def create_extractor(language: str, query_source: str) -> ASTExtractor:
    """
    Factory function to create an ASTExtractor instance.

    This is the primary factory method for creating extractors without
    defining a new subclass for each language.

    Args:
        language: Language identifier (e.g., "python", "javascript", "rust")
        query_source: Tree-sitter SCM query string for the language

    Returns:
        Configured ASTExtractor instance ready to parse files

    Example:
        >>> extractor = create_extractor("python", PYTHON_QUERY)
        >>> entities, relationships = extractor.parse_file("test.py", content)
    """
    return ConfigurableExtractor(language, query_source)


# =============================================================================
# Query Registry
# =============================================================================
# Registry of tree-sitter queries for supported languages.
# These can be imported and used with create_extractor() or kept as strings
# in separate configuration files.
# =============================================================================

# Python query - covers classes, functions, methods, imports, calls
PYTHON_QUERY = r"""
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

; ── Imports ───────────────────────────────────────────────────────────────────
(import_statement
  name: (dotted_name) @ref.import.module)

(import_from_statement
  module_name: (dotted_name) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call
  function: (identifier) @ref.call)

(call
  function: (attribute
    attribute: (identifier) @ref.call))
"""

# JavaScript query - covers functions, arrow functions, classes, methods
JAVASCRIPT_QUERY = r"""
; ── Function declarations ─────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (formal_parameters) @def.function.params)

; ── Arrow functions assigned to a const ───────────────────────────────────────
(variable_declarator
  name: (identifier) @def.function.name
  value: (arrow_function
    parameters: (_) @def.function.params))

; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (identifier) @def.class.name)

; ── Method definitions ────────────────────────────────────────────────────────
(method_definition
  name: (property_identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params)

; ── Imports ───────────────────────────────────────────────────────────────────
(import_statement
  source: (string) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (member_expression
    property: (property_identifier) @ref.call))
"""

# TypeScript query - extends JavaScript with type annotations
TYPESCRIPT_QUERY = r"""
; ── Function declarations with types ──────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (formal_parameters) @def.function.params
  return_type: (type_annotation)? @def.function.return_type)

; ── Arrow functions ───────────────────────────────────────────────────────────
(variable_declarator
  name: (identifier) @def.function.name
  value: (arrow_function
    parameters: (_) @def.function.params
    return_type: (type_annotation)? @def.function.return_type))

; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (type_identifier) @def.class.name
  heritage: (class_heritage
    (extends_clause
      (type_identifier) @def.class.extends)?
    (implements_clause
      (type_identifier) @def.class.implements)*))

; ── Method definitions ────────────────────────────────────────────────────────
(method_definition
  name: (property_identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params
  return_type: (type_annotation)? @def.method.return_type)

; ── Interface declarations ────────────────────────────────────────────────────
(interface_declaration
  name: (type_identifier) @def.interface.name
  extends: (extends_clause
    (type_identifier) @def.interface.extends)*)

; ── Type aliases ──────────────────────────────────────────────────────────────
(type_alias_declaration
  name: (type_identifier) @def.type_alias.name)

; ── Imports ───────────────────────────────────────────────────────────────────
(import_statement
  source: (string) @ref.import.module)

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (member_expression
    property: (property_identifier) @ref.call))
"""

# Rust query - covers structs, enums, traits, functions, impl methods
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

; ── Free function definitions ─────────────────────────────────────────────────
(function_item
  (visibility_modifier)? @def.function.visibility
  name: (identifier) @def.function.name
  parameters: (parameters) @def.function.params
  return_type: (_)? @def.function.return_type)

; ── Methods inside impl blocks ────────────────────────────────────────────────
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
  (scoped_identifier) @ref.import.module)

(use_declaration
  (identifier) @ref.import.module)

; ── Call expressions ──────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (scoped_identifier) @ref.call)

(call_expression
  function: (field_expression
    field: (field_identifier) @ref.call))
"""

# Go query - covers functions, methods, interfaces, structs
GO_QUERY = r"""
; ── Function declarations ─────────────────────────────────────────────────────
(function_declaration
  name: (identifier) @def.function.name
  parameters: (parameter_list) @def.function.params
  result: (type)? @def.function.return_type)

; ── Method declarations ───────────────────────────────────────────────────────
(method_declaration
  name: (field_identifier) @def.method.name
  parameters: (parameter_list) @def.method.params
  result: (type)? @def.method.return_type)

; ── Type declarations (structs and interfaces) ────────────────────────────────
(type_declaration
  (type_spec
    name: (type_identifier) @def.class.name
    type: (struct_type)))

(type_declaration
  (type_spec
    name: (type_identifier) @def.interface.name
    type: (interface_type)))

; ── Imports ───────────────────────────────────────────────────────────────────
(import_declaration
  (import_spec
    path: (interpreted_string_literal) @ref.import.module))

; ── Calls ─────────────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (selector_expression
    field: (field_identifier) @ref.call))
"""

# Java query - covers classes, methods, interfaces
JAVA_QUERY = r"""
; ── Class declarations ────────────────────────────────────────────────────────
(class_declaration
  name: (identifier) @def.class.name
  superclass: (superclass
    (type_identifier) @def.class.extends)?
  interfaces: (super_interfaces
    (type_interface
      (type_identifier) @def.class.implements))*)

; ── Method declarations ───────────────────────────────────────────────────────
(method_declaration
  name: (identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params
  return_type: (_) @def.method.return_type)

; ── Constructor declarations ──────────────────────────────────────────────────
(constructor_declaration
  name: (identifier) @def.method.name
  parameters: (formal_parameters) @def.method.params)

; ── Interface declarations ────────────────────────────────────────────────────
(interface_declaration
  name: (identifier) @def.interface.name
  extends: (extends_interfaces
    (type_interface
      (type_identifier) @def.interface.extends))*)

; ── Import declarations ───────────────────────────────────────────────────────
(import_declaration
  (identifier)? @ref.import.module
  (asterisk)? @ref.import.module)

; ── Method invocations ────────────────────────────────────────────────────────
(method_invocation
  name: (identifier) @ref.call)
"""

# C query - covers functions
C_QUERY = r"""
; ── Function definitions ──────────────────────────────────────────────────────
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @def.function.name
    parameters: (parameter_list) @def.function.params))

; ── Type definitions ──────────────────────────────────────────────────────────
(type_definition
  type: (struct_specifier
    name: (type_identifier) @def.struct.name))

(type_definition
  type: (enum_specifier
    name: (type_identifier) @def.enum.name))

; ── Function calls ────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)
"""

# C++ query - extends C with classes and methods
CPP_QUERY = r"""
; ── Function definitions ──────────────────────────────────────────────────────
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @def.function.name
    parameters: (parameter_list) @def.function.params))

; ── Class definitions ─────────────────────────────────────────────────────────
(class_specifier
  name: (type_identifier) @def.class.name
  base_clause: (base_class_clause
    (base_class_specifier
      (type_identifier) @def.class.extends))*)

; ── Method definitions ────────────────────────────────────────────────────────
(function_definition
  declarator: (function_declarator
    declarator: (field_identifier) @def.method.name
    parameters: (parameter_list) @def.method.params))

; ── Struct definitions ────────────────────────────────────────────────────────
(struct_specifier
  name: (type_identifier) @def.struct.name)

; ── Include directives ────────────────────────────────────────────────────────
(preproc_include
  (string_literal) @ref.import.module)

; ── Function calls ────────────────────────────────────────────────────────────
(call_expression
  function: (identifier) @ref.call)

(call_expression
  function: (field_expression
    field: (field_identifier) @ref.call))
"""

# Query registry mapping language names to their queries
QUERY_REGISTRY: dict[str, str] = {
    "python": PYTHON_QUERY,
    "javascript": JAVASCRIPT_QUERY,
    "typescript": TYPESCRIPT_QUERY,
    "rust": RUST_QUERY,
    "go": GO_QUERY,
    "java": JAVA_QUERY,
    "c": C_QUERY,
    "cpp": CPP_QUERY,
}

# Cache of created extractor instances
_extractor_cache: dict[str, ASTExtractor] = {}


def get_extractor(language: str) -> ASTExtractor | None:
    """
    Get a cached extractor instance for the specified language.

    This function returns a cached instance if available, or creates
    a new one using the query registry. The cache prevents redundant
    extractor instantiation.

    Args:
        language: Language identifier (e.g., "python", "rust")

    Returns:
        ASTExtractor instance or None if language not in registry

    Example:
        >>> extractor = get_extractor("python")
        >>> if extractor:
        ...     entities, rels = extractor.parse_file("test.py", content)
    """
    # Return cached instance if available
    if language in _extractor_cache:
        return _extractor_cache[language]

    # Create new instance if query is registered
    query = QUERY_REGISTRY.get(language)
    if query:
        extractor = create_extractor(language, query)
        _extractor_cache[language] = extractor
        return extractor

    return None


def register_extractor(language: str, query_source: str) -> None:
    """
    Register a new extractor query for a language.

    This allows extending the factory with custom languages without
    modifying the factory module itself.

    Args:
        language: Language identifier
        query_source: Tree-sitter SCM query string

    Example:
        >>> register_extractor("kotlin", KOTLIN_QUERY)
        >>> extractor = get_extractor("kotlin")
    """
    QUERY_REGISTRY[language] = query_source
    # Clear cache if this language was previously cached
    if language in _extractor_cache:
        del _extractor_cache[language]


def list_supported_languages() -> list[str]:
    """
    Return a list of language identifiers with registered queries.

    Returns:
        Sorted list of supported language identifiers
    """
    return sorted(QUERY_REGISTRY.keys())


def clear_extractor_cache() -> None:
    """
    Clear the extractor instance cache.

    This is useful for testing or when queries are updated dynamically.
    """
    _extractor_cache.clear()
