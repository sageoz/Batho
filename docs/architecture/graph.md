# Graph Module

The Graph module (`batho/modules/graph/`) builds, updates, diffs, and reconstructs the semantic relationship graph of the codebase.

---

## File Reference Table

| Path | Purpose |
|:---|:---|
| `incremental.py` | Git-aware helpers (repository status, HEAD commits, and current branch tracking). |
| `builder/codegraph.py` | Implementation of `InMemoryGraph`, `IncrementalGraphUpdater`, and `CodeGraphIndexer`. Handles relationships, type resolution, and semantic overrides. |
| `reconstructor/reconstructor.py` | Pure in-memory reconstruction engine that reassembles source files losslessly from entity content hashes and byte ranges. |
| `diff_engine/node_diff.py` | Diffing engine comparing entities between indexing runs to generate `NodeDiff` records. |

---

## Core Components

### 1. Code Graph Indexer (`builder/codegraph.py`)
- **`InMemoryGraph`**: In-memory representation of code entities and relationships. Maintains lazy adjacency and secondary lookup indexes for O(1)/O(k) operations.
- **`CodeGraphIndexer`**: Orchestrator that triggers parallel AST parsing, resolves cross-file import statements, derives `INHERITS`/`IMPLEMENTS` and `OVERRIDES` edges, and invokes overlays/plugins.
- **`IncrementalGraphUpdater`**: Executes transactional mutations (adds/removes) on a graph structure for single files in patch mode.

### 2. File Reconstructor (`reconstructor/reconstructor.py`)
- **`FileReconstructor`**: Concatenates `raw_content`/`raw_bytes` of non-overlapping entities covering the byte ranges `[0, file_size)`. Validates reconstruction success against original SHA-256 hashes.

### 3. Entity Diffing Engine (`diff_engine/node_diff.py`)
- **`diff_file_nodes()`**: Computes added, modified, removed, and renamed entities for a modified file by utilizing fast-path hash matches, field comparisons, and name-similarity matching. Produces `NodeDiff` dataclass objects.

### 4. Git-Aware Tracking (`incremental.py`)
- Interacts with Git subprocesses to stamp commit IDs (`HEAD`) and branch names into file snapshots.

---

## Mermaid Class Diagram

```mermaid
classDiagram
    class InMemoryGraph {
        +entities: dict
        +relationships: list
        +add_entity(entity)
        +add_relationship(rel)
        +get_entity(entity_id) Entity
        +neighbors(entity_id, direction) list
        +entities_by_file(file_path) list
        +entities_by_type(entity_type) list
        +to_dict(view) dict
        +from_dict(data)$ InMemoryGraph
    }

    class IncrementalGraphUpdater {
        +update_entities_for_file(graph, file_path, extractor)
        +remove_entities_for_file(graph, file_path)
        +add_entities_for_file(graph, file_path, extractor)
        +validate_graph_consistency(graph) bool
    }

    class CodeGraphIndexer {
        -_cache: BathoCache
        -_graph: InMemoryGraph
        +build_graph(root, ...) InMemoryGraph
        +index_file(filepath, extractor) tuple
        +reconstruct_file(file_path) ReconstructionResult
        -_derive_hierarchy_relations(graph)
        -_derive_override_edges(graph)
        -_resolve_imports(graph, symbol_index)
    }

    class FileReconstructor {
        +reconstruct_file(file_path, entities, original_hash) ReconstructionResult
        +reconstruct_from_snapshot(snapshot, entity_lookup) ReconstructionResult
        -_select_covering_entities(entities) list
        -_check_coverage(entities, file_size) bool
    }

    class NodeDiff {
        +str entity_id
        +str entity_name
        +str change_kind
        +dict changed_fields
        +to_dict() dict
    }

    CodeGraphIndexer --> InMemoryGraph : builds / updates
    CodeGraphIndexer --> IncrementalGraphUpdater : validates
    CodeGraphIndexer --> FileReconstructor : delegates reconstruction
    IncrementalGraphUpdater --> InMemoryGraph : mutates
    NodeDiff <.. CodeGraphIndexer : generates
```

---

## Mermaid Workflow Diagram

```mermaid
flowchart TD
    BUILD["orchestrator.build / patch"] --> INDEXER["CodeGraphIndexer.build_graph()"]
    INDEXER --> RUNPARALLEL["pipeline.build_graph_parallel()"]
    RUNPARALLEL --> ADDBATCH["InMemoryGraph.add_entities_batch()"]
    
    INDEXER --> SYMBINDEX["SymbolIndex.build()"]
    INDEXER --> RESOLVE["_resolve_imports()\nResolves imports against SymbolIndex"]
    INDEXER --> HIERARCHY["_derive_hierarchy_relations()\nDerives INHERITS & IMPLEMENTS"]
    INDEXER --> OVERRIDES["_derive_override_edges()\nDerives OVERRIDES on method signatures"]
    
    BUILD_PATCH["orchestrator.patch"] --> UPDATER["IncrementalGraphUpdater"]
    UPDATER --> REMOVE["remove_entities_for_file()"]
    UPDATER --> ADD["add_entities_for_file()"]
    ADD --> DIFF["diff_file_nodes() → yields NodeDiffs"]
```

---

## Integration Points

- **Extraction Module**: Supplies the initial lists of parsed `Entity` and `Relationship` objects.
- **Storage Module**: Provides persistence via the database registry and cache.
- **Query Module**: Queries the graph via `SymbolIndex` for importing and override resolution.
