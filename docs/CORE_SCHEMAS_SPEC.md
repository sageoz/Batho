# Batho Core Schemas Specification

This document describes the shared type system defined in `batho/core/schemas.py` — the foundational data models that flow through every layer of the Batho pipeline, from AST extraction to Arrow IPC storage.

---

## 1. Overview

All outputs from the AST engine are **frozen Pydantic v2 models**. No raw dicts escape this layer — every entity, relationship, and file snapshot is represented as a strongly-typed, immutable object.

```
tree-sitter parse
    └── ASTExtractor → Entity + Relationship (frozen Pydantic models)
                            │
                    pipeline.py workers
                            │
                    InMemoryGraph (dict[str, Entity])
                            │
                    BSGMap (compressed views)
                            │
                    Arrow IPC (serialized via to_dict())
```

### File Structure

| File | Purpose |
|------|---------|
| `batho/core/schemas.py` | All shared type definitions (~930 lines) |
| `batho/core/__init__.py` | Public re-exports |

---

## 2. Entity Model

**File:** `batho/core/schemas.py` — `class Entity(BaseModel)`

The primary data unit produced by extraction. Represents a single code entity (function, class, variable, etc.) within a source file.

```python
model_config = {"frozen": True, "extra": "allow", "slots": True}
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `EntityType` | — | Kind of entity (function, class, etc.) |
| `name` | `str` | — | Identifier name of the entity |
| `file` | `str` | — | Absolute path to the source file |
| `start_line` | `int` | — | 1-based starting line number |
| `end_line` | `int` | — | 1-based ending line number |
| `start_byte` | `int` | `0` | Starting byte offset in source file |
| `end_byte` | `int` | `0` | Ending byte offset in source file |
| `signature` | `str \| None` | `None` | Optional signature string (e.g., function parameters) |
| `metadata` | `dict[str, Any]` | `{}` | Language-specific + BSG rule-tagged metadata |
| `parent_id` | `str \| None` | `None` | ID of containing parent entity (e.g., class for a method) |
| `raw_content` | `str \| None` | `None` | Raw source text of this entity (storage view only) |
| `content_hash` | `str` | `""` | SHA256 of raw_content bytes |
| `raw_bytes` | `bytes \| None` | `None` | Raw bytes for non-UTF-8 content |
| `leading_whitespace` | `str` | `""` | Whitespace before entity start (SYNTAX_GLUE) |
| `trailing_whitespace` | `str` | `""` | Whitespace after entity end (SYNTAX_GLUE) |
| `ast_node_type` | `str \| None` | `None` | tree-sitter node type string |
| `children_order` | `list[str]` | `[]` | Ordered list of child entity IDs |
| `enclosing_start_byte` | `int \| None` | `None` | Byte start of the enclosing scope |
| `enclosing_end_byte` | `int \| None` | `None` | Byte end of the enclosing scope |
| `is_documentation` | `bool` | `False` | Whether entity is a docstring/comment entity |
| `id_override` | `str \| None` | `None` | If set, returned as `id` instead of computed value |

### Computed Fields

#### `id` (computed, via `@computed_field`)

Returns a deterministic, position-based unique identifier. If `id_override` is set, that value is returned directly (used to preserve serialized IDs across the cache/storage roundtrip).

```python
# Format: "ent|<type>|<file>|<start_byte>|<end_byte>|<start_line>|<end_line>|<name>"
entity.id  # e.g. "ent|FUNCTION|/repo/api.py|100|250|5|12|create_user"
```

#### `fqn` (property)
Returns the fully qualified name:
- If `signature` is set → returns `signature`
- If type is `CLASS`/`MODULE`/`NAMESPACE` → returns `name`
- Otherwise → `None`

#### `is_contextual_stub` (property)
Returns `True` if `type == UNRESOLVED` and `id` starts with `"unresolved:"`.

### Key Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `to_dict(view="agent")` | `dict[str, Any]` | Serialize to dict. `"agent"` = compact; `"storage"` = full-fidelity with raw_content |
| `from_dict(data)` | `Entity` | Deserialize from dict; preserves serialized `id` via `id_override` |
| `compute_content_hash()` | `str` | SHA256 of `raw_content.encode("utf-8")` |
| `validate_coverage()` | `bool` | Verify `(end_byte - start_byte) == len(raw_content)` |
| `_evolve(**fields)` | `Entity` | Efficient frozen copy with field overrides (uses `model_copy(update=...)`) |

### Serialization Views

`to_dict()` accepts a `view` argument that controls the output shape:

| View | Includes | Use Case |
|------|----------|----------|
| `"agent"` (default) | `id`, `type`, `name`, `file`, lines, bytes, `signature`, `metadata`, `parent_id`, `ast_node_type`, `children_order` | LLM context injection, AST cache |
| `"storage"` | All agent fields + `raw_content`, `content_hash`, `raw_bytes`, `leading_whitespace`, `trailing_whitespace` | Bidirectional reconstruction, diff storage |

> **Note**: `raw_content` is intentionally excluded from the agent view to keep the cache lightweight — it is dynamically regenerated on cache hits via `_enrich_cached_entities()`.

---

## 3. Relationship Model

**File:** `batho/core/schemas.py` — `class Relationship(BaseModel)`

Represents a directed relationship between two entities.

```python
model_config = {"frozen": True, "extra": "allow", "slots": True}
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source_id` | `str` | — | ID of the source entity |
| `target_id` | `str` | — | ID of the target entity |
| `type` | `RelationshipType` | — | Kind of relationship |
| `roles` | `SymbolRole` | `SymbolRole(0)` | SCIP-inspired role bitfield |
| `reference_start_byte` | `int \| None` | `None` | Byte start of the reference site |
| `reference_end_byte` | `int \| None` | `None` | Byte end of the reference site |
| `definition_start_byte` | `int \| None` | `None` | Byte start of the definition |
| `definition_end_byte` | `int \| None` | `None` | Byte end of the definition |
| `metadata` | `dict[str, Any]` | `{}` | Additional context (e.g., `line_number`) |
| `confidence` | `float` | `1.0` | Confidence score (0.7 for heuristic refs) |

### Computed Fields

#### `id` (computed, via `@computed_field`)

```python
# Format: "rel|<source_id>|<rel_type>|<target_id>|<ref_start>|<ref_end>|<def_start>|<def_end>|<line>|<roles>"
```

`line_number` from `metadata` is included to disambiguate multiple calls to the same target from the same source (e.g., `foo()` called twice in a function).

### Key Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `to_dict()` | `dict[str, Any]` | Serialize to dict |
| `from_dict(data)` | `Relationship` | Deserialize; handles lowercase type strings, `SymbolRole` int/str |
| `_evolve(**fields)` | `Relationship` | Efficient frozen copy |

---

## 4. SymbolRole (IntFlag)

SCIP-inspired bitfield for semantic roles of symbol occurrences. Combines with bitwise OR.

| Flag | Value | Description |
|------|-------|-------------|
| `Definition` | `1` | The entity is defined here |
| `Import` | `2` | The entity is imported |
| `WriteAccess` | `4` | Write access to the symbol |
| `ReadAccess` | `8` | Read access to the symbol |
| `Generated` | `16` | Code-generated entity |
| `Declaration` | `32` | Forward declaration |
| `Dynamic` | `64` | Dynamically resolved |
| `Heuristic` | `128` | Inferred/heuristic resolution (confidence 0.7) |

```python
# Example: an imported definition
role = SymbolRole.Definition | SymbolRole.Import  # value = 3

role.is_definition()  # True
role.is_import()      # True
str(role)             # "Definition, Import"
```

---

## 5. EntityType (Enum)

All 26 entity types that can be extracted from source code:

| EntityType | Description |
|------------|-------------|
| `FUNCTION` | Standalone function |
| `METHOD` | Class method |
| `CLASS` | Class definition |
| `MODULE` | File/module level entity |
| `STRUCT` | Struct definition (Rust, Go, C) |
| `INTERFACE` | Interface (Java, TypeScript) |
| `FIELD` | Class field |
| `ENUM` | Enum definition |
| `TRAIT` | Trait (Rust) |
| `TYPE_ALIAS` | Type alias |
| `CONSTANT` | Named constant |
| `NAMESPACE` | Namespace (C++, C#) |
| `VARIABLE` | Variable declaration |
| `PROPERTY` | Property accessor |
| `ENTRY_POINT` | Entry point (e.g., `main()`) |
| `UNRESOLVED` | *(Deprecated)* Unresolved stub — prefer `EXTERNAL_SYMBOL` |
| `EXTERNAL_SYMBOL` | SCIP external reference node |
| `INFRASTRUCTURE_CONFIG` | IaC entity (set by `apply_semantic_overlay`) |
| `ENVIRONMENT_VARIABLE` | Environment variable (set by `apply_semantic_overlay`) |
| `SETTING` | Key-value pairs (JSON, YAML, TOML) |
| `SECTION` | Named sections/objects |
| `ELEMENT` | HTML/CSS/Markdown structural elements |
| `ATTRIBUTE` | Element attributes |
| `DOCUMENT` | Document-level entity |
| `SYNTAX_GLUE` | Whitespace, comments, non-semantic segments (bidirectional gaps) |
| `GLOBAL_STATEMENT` | Top-level executable statements |
| `IMPORT_BLOCK` | Import-only regions |
| `COMMENT_BLOCK` | Comment-only regions |

> **Type promotion**: `apply_semantic_overlay()` can change entity types at build time:
> - Entities tagged `InfrastructureConfig` → type becomes `INFRASTRUCTURE_CONFIG`
> - Entities tagged `EnvironmentVariable` → type becomes `ENVIRONMENT_VARIABLE`

---

## 6. RelationshipType (Enum)

All 19 relationship types:

| RelationshipType | Description |
|-----------------|-------------|
| `CALLS` | Function/method call |
| `IMPORTS` | Module import |
| `INHERITS` | Class inheritance |
| `IMPLEMENTS` | Interface implementation |
| `USES` | Dependency usage |
| `CONTAINS` | Parent→child containment (e.g., class→method) |
| `REFERENCES` | Symbol reference |
| `DEFINES` | Definition relationship |
| `CALLED_BY` | Inverse of CALLS |
| `IMPORTED_BY` | Inverse of IMPORTS |
| `OVERRIDES` | Method override (derived by post-processing) |
| `STACK_BOUNDARY` | Stack/call boundary |
| `WRAPPED_BY` | Decorator/wrapper |
| `DEPENDS_ON_API` | API contract dependency |
| `REFERENCED_IN` | Bidirectional: referenced inside a gap section |
| `CLEANED_BY` | Resource cleanup pairing |
| `CONTAINED_WITHIN` | Inverse of CONTAINS |
| `HAS_ATTRIBUTE` | HTML/CSS attribute relationship |
| `LINKS_TO` | Markdown link target |
| `IMPORTS_STYLE` | CSS/style import |

---

## 7. BSGViewType (Enum)

Controls rendering mode for `BSGMap`:

| BSGViewType | Description |
|-------------|-------------|
| `STORAGE` | Full-fidelity view with `raw_content` and hashes for reconstruction |
| `AGENT` | Compressed view optimized for LLM context, excludes `SYNTAX_GLUE` entities |

---

## 8. ID Generation

### Entity ID: `build_entity_id()`

```python
def build_entity_id(
    *,
    entity_type: str,
    name: str,
    file: str,
    start_byte: int | None = None,
    end_byte: int | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
```

**Format**: `ent|<type>|<file>|<start_byte>|<end_byte>|<start_line>|<end_line>|<name>`

- Pipe-delimited (`|`)
- `|` characters inside values are percent-encoded as `%7C`
- Position-based (no hash) → deterministic across runs; tracks code movement

```python
# Example
build_entity_id(
    entity_type="FUNCTION",
    name="create_user",
    file="/repo/api.py",
    start_byte=100,
    end_byte=250,
    start_line=5,
    end_line=12,
)
# → "ent|FUNCTION|/repo/api.py|100|250|5|12|create_user"
```

### Relationship ID: `build_relationship_id()`

```python
def build_relationship_id(
    source_id: str,
    target_id: str,
    rel_type: str,
    *,
    reference_start_byte: int | None = None,
    reference_end_byte: int | None = None,
    definition_start_byte: int | None = None,
    definition_end_byte: int | None = None,
    line_number: int | None = None,
    roles: SymbolRole | int | None = None,
) -> str:
```

**Format**: `rel|<source_id>|<rel_type>|<target_id>|<ref_start>|<ref_end>|<def_start>|<def_end>|<line>|<roles_int>`

Including `line_number` disambiguates multiple calls to the same function from the same source entity.

### Hierarchical IDs: `generate_hierarchical_id()`

SCIP-style hierarchical IDs for external dependencies:

```python
generate_hierarchical_id(
    package=PackageMetadata(manager=PackageManager.PIP, name="requests", version="2.31.0"),
    descriptors=[("Session", DescriptorSuffix.TYPE), ("get", DescriptorSuffix.METHOD)],
)
# → "batho pip requests 2.31.0 Session#get()."
```

#### `DescriptorSuffix` Enum

| Suffix | Value | Use |
|--------|-------|-----|
| `NAMESPACE` | `"/"` | Namespace/package separator |
| `TYPE` | `"#"` | Class/struct separator |
| `TERM` | `"."` | Field/variable separator |
| `METHOD` | `"()."` | Method separator |

---

## 9. Package Models

### `PackageManager` (Enum)

| Value | Language |
|-------|----------|
| `PIP` | Python |
| `NPM` | JavaScript |
| `CARGO` | Rust |
| `GO` | Go |
| `GRADLE` / `MAVEN` | Java |
| `UNKNOWN` | — |

### `PackageMetadata` (frozen BaseModel)

| Field | Type | Description |
|-------|------|-------------|
| `manager` | `PackageManager` | Package manager |
| `name` | `str` | Package name |
| `version` | `str` | Version string |
| `source` | `str \| None` | Source URL/path |

---

## 10. File Reconstruction Models

### `FileSnapshot`

Metadata for bidirectional reconstruction of a source file from its entity set.

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | `str` | Relative file path |
| `file_hash` | `str` | SHA256 of original file content |
| `file_size` | `int` | File size in bytes |
| `encoding` | `str` | File encoding |
| `entity_ids` | `list[str]` | Ordered entity IDs covering the file |
| `gap_sections` | `list[dict]` | Byte ranges with raw content for SYNTAX_GLUE |
| `shebang` | `str \| None` | Shebang line if present |
| `encoding_declaration` | `str \| None` | Encoding declaration (e.g., `# -*- coding: utf-8 -*-`) |
| `file_level_comments` | `list[str]` | Top-level comment blocks |

Used by `BSGMap.build()` for files with a dedicated AST extractor. Stored as `opaque_snapshots` for files without an extractor.

---

## 11. Exception Types

All exceptions are raised from within the pipeline for structural error conditions — they are never swallowed silently.

### `CoverageError`
Raised when byte coverage validation fails.

```python
raise CoverageError(
    message="Coverage gap detected",
    file_path="/repo/api.py",
    byte_coverage=0.87,
    overlapping_ranges=[(100, 200), (150, 250)],
    gap_ranges=[(300, 350)],
)
```

| Attribute | Type | Description |
|-----------|------|-------------|
| `file_path` | `str` | Path to file being validated |
| `byte_coverage` | `float` | Ratio of covered bytes (0.0–1.0) |
| `overlapping_ranges` | `list[tuple[int, int]]` | Byte ranges that overlap |
| `gap_ranges` | `list[tuple[int, int]]` | Uncovered byte ranges |

### `ReconstructionError`
Raised when file reconstruction from entities fails.

| Attribute | Type | Description |
|-----------|------|-------------|
| `file_path` | `str` | Path to file being reconstructed |
| `entity_count` | `int` | Number of entities provided |
| `byte_coverage` | `float` | Ratio of covered bytes |

### `IntegrityError`
Raised when reconstructed content hash does not match original.

| Attribute | Type | Description |
|-----------|------|-------------|
| `file_path` | `str` | Path to file being validated |
| `expected_hash` | `str` | Expected SHA256 hash |
| `actual_hash` | `str` | Actual SHA256 of reconstructed content |

### `GraphConsistencyError`
Raised when graph consistency check fails (broken relationship references).

| Attribute | Type | Description |
|-----------|------|-------------|
| `file_path` | `str` | File that caused the inconsistency |

---

## 12. Public API

```python
from batho.core.schemas import (
    # Enums
    EntityType,
    RelationshipType,
    BSGViewType,
    SymbolRole,
    DescriptorSuffix,
    PackageManager,

    # Models
    Entity,
    Relationship,
    FileSnapshot,
    PackageMetadata,

    # ID generation
    build_entity_id,
    build_relationship_id,
    generate_hierarchical_id,
    parse_hierarchical_id,
    build_descriptor,

    # Exceptions
    CoverageError,
    ReconstructionError,
    IntegrityError,
    GraphConsistencyError,

    # Type aliases
    EntityMetadata,
)
```

---

## 13. Design Principles

- **Frozen models** — all models use `frozen=True`; mutation is performed via `_evolve()` which creates a new instance via `model_copy(update=...)`.
- **Slots** — `slots=True` reduces per-instance memory overhead in large builds (100K+ entities).
- **Identity** — entities and relationships use `__hash__` and `__eq__` based on `id`, enabling set/dict operations.
- **Deterministic IDs** — position-based IDs (not content hashes) enable stable tracking across runs; only actual code movement changes the ID.
- **No raw dicts leaking** — all pipeline layers exchange `Entity` and `Relationship` objects; serialization only happens at storage boundaries (`to_dict()`) and deserialization at load boundaries (`from_dict()`).

---

*Generated for Batho v1.1.0*
