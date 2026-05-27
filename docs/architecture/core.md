# Core Foundation Layer

The Core layer (`batho/core/`) houses the fundamental, centralized components of Batho, including protocol definitions (contracts) that decouple systems, shared Pydantic models (schemas), and custom exception classes.

---

## Files Covered

| Filename | Purpose |
|:---|:---|
| `exceptions.py` | Centralized exception definitions (e.g. `CoverageError`, `ReconstructionError`, `IntegrityError`, etc.). |
| `schemas.py` | Pydantic models defining data structures for AST extraction results, graph state, snapshots, and reconstruction results. |
| `contracts.py` | Protocol definitions defining interfaces for language parsers and graph builders. |

---

## Centralized Exceptions (`exceptions.py`)

All custom exception classes are centralized here:

| Exception Class | Purpose | Key Attributes |
|:---|:---|:---|
| `CoverageError` | Raised when byte coverage validation fails during AST extraction. | `file_path`, `byte_coverage`, `overlapping_ranges`, `gap_ranges` |
| `ReconstructionError` | Raised when file reconstruction fails. | `file_path`, `entity_count`, `byte_coverage` |
| `IntegrityError` | Raised when the reconstructed file's hash does not match the original. | `file_path`, `expected_hash`, `actual_hash` |
| `GraphConsistencyError` | Raised when graph consistency verification fails. | `file_path` |

---

## Unified Schemas (`schemas.py`)

Unified models represent the semantic entities, relationships, file snapshots, and state definitions.

| Model / Class | Type | Purpose |
|:---|:---|:---|
| `EntityType` | Enum | All extractable code-entity types (e.g. `FUNCTION`, `METHOD`, `CLASS`, `STRUCT`, `INTERFACE`, `FIELD`, `SYNTAX_GLUE`, etc.). |
| `RelationshipType` | Enum | Directed relationship kinds (e.g. `CALLS`, `IMPORTS`, `INHERITS`, `IMPLEMENTS`, `CONTAINS`, etc.). |
| `BSGViewType` | Enum | Control view serialization formats: `STORAGE` (full details) or `AGENT` (LLM context optimized). |
| `Entity` | Frozen Pydantic Model | Represents an AST entity with properties like `id` (hash-derived), `fqn` (fully qualified name), validation, and serialization. |
| `Relationship` | Frozen Pydantic Model | Directed edge between source and target entities. |
| `FileSnapshot` | Frozen Pydantic Model | Metadata needed for file tracking and reconstruction. |
| `ReconstructionResult` | Frozen Pydantic Model | Output summary of a file reconstruction attempt. |
| `ASTExtractionResult` | Pydantic Model | Combined output of AST parsing containing file path, snapshot, entities, and relationships list. |
| `GraphState` | Pydantic Model | The complete in-memory graph state containing loaded entities and relationships. |

---

## Decoupling Contracts (`contracts.py`)

Protocol definitions decouple the modules from each other by declaring structural interface contracts:

| Protocol Class | Key Method | Purpose |
|:---|:---|:---|
| `LanguageParser` | `parse(file_content, file_path) -> ASTExtractionResult` | Interface for language-specific AST extraction parsers. |
| `GraphBuilder` | `build(extraction_result) -> GraphState` | Interface for building/updating the relationship graph. |

---

## Mermaid Class Diagram

The following class diagram shows the primary schemas and exceptions in the Core layer:

```mermaid
classDiagram
    class Entity {
        +EntityType type
        +str name
        +str file
        +int start_byte
        +int end_byte
        +str|None signature
        +dict metadata
        +str|None parent_id
        +str|None raw_content
        +str content_hash
        +bytes|None raw_bytes
        +id() str
        +fqn() str|None
        +compute_content_hash() str
        +validate_coverage() bool
        +to_dict(view) dict
        +from_dict(data) Entity
    }

    class Relationship {
        +str source_id
        +str target_id
        +RelationshipType type
        +dict metadata
        +id() str
        +to_dict() dict
        +from_dict(data) Relationship
    }

    class FileSnapshot {
        +str file_path
        +str file_hash
        +int file_size
        +list entity_ids
        +create_opaque(file_path, content) FileSnapshot
    }

    class LanguageParser {
        <<interface>>
        +parse(file_content, file_path) ASTExtractionResult
    }

    class GraphBuilder {
        <<interface>>
        +build(extraction_result) GraphState
    }

    class ASTExtractionResult {
        +str file_path
        +FileSnapshot snapshot
        +list entities
        +list relationships
    }

    class GraphState {
        +list entities
        +list relationships
    }

    class CoverageError {
        +str file_path
        +float byte_coverage
    }
    class ReconstructionError {
        +str file_path
        +float byte_coverage
    }
    class IntegrityError {
        +str file_path
        +str expected_hash
        +str actual_hash
    }
    class GraphConsistencyError {
        +str file_path
    }

    Entity --> EntityType : type
    Relationship --> RelationshipType : type
    ASTExtractionResult --> FileSnapshot : snapshot
    ASTExtractionResult --> Entity : entities
    ASTExtractionResult --> Relationship : relationships
    GraphState --> Entity : entities
    GraphState --> Relationship : relationships

    CoverageError --|> Exception
    ReconstructionError --|> Exception
    IntegrityError --|> Exception
    GraphConsistencyError --|> Exception
```
