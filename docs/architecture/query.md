# Query Module

The Query module (`batho/modules/query/`) handles lookups, references, and semantic queries over the workspace code graph.

---

## File Reference Table

| Path | Purpose |
|:---|:---|
| `symbol_index.py` | Maps symbol names and aliases to tuples of entity IDs, enabling fast cross-file import resolution. |
| `engine/query.py` | Implements `QueryService`, a cached query interface over decompressed database artifacts. |

---

## Core Components

### 1. Symbol Index (`symbol_index.py`)
- **`SymbolIndex`**: A frozen lookup table mapping exact and lowercase names to tuples of sorted entity IDs.
- **Proximity Resolution**: Resolves target symbols using `_choose_best()`, scoring candidates based on:
  - Same-file residency (`+1000`)
  - Shared leading directory segments depth (`×10`)
  - Tiebreak preference for shorter fully-qualified names

### 2. Query Service (`engine/query.py`)
- **`QueryService`**: Primary interface utilized by `batho export` commands.
- Loads SQLite graph artifacts lazily on-demand, decompressing file blobs and caching results via an LRU-evicting cache (`OrderedDict`).
- Provides filtering methods: `entities_by_type()`, `entities_by_file()`, and `relationships_by_type()`.

---

## Mermaid Class Diagram

```mermaid
classDiagram
    class SymbolIndex {
        <<frozen dataclass>>
        +dict names
        +dict names_lower
        +dict files_by_id
        +dict names_by_id
        +int size
        +build(graph)$ SymbolIndex
        +resolve_candidates(candidates, source_file, fuzzy_matching) str|None
        -_choose_best(candidate_ids, source_file) str|None
        -_shared_dir_depth(source, target) int
    }

    class QueryService {
        +Path ctn_dir
        +str index_id
        +bool cache_enabled
        -_cache: OrderedDict
        -_entities: list
        -_relationships: list
        +_resolve_index_id() str
        +_ensure_loaded(run_uuid)
        +entities_by_type(entity_type, limit) list
        +entities_by_file(file_path, limit) list
        +relationships_by_type(relationship_type, limit) list
    }

    SymbolIndex ..> InMemoryGraph : built from
    QueryService ..> BathoDatabase : queries
```

---

## Mermaid Call-Flow Flowchart

```mermaid
flowchart TD
    EXPORT["batho export"] --> EXPORT_ORCH["orchestrator.export.run_export()"]
    EXPORT_ORCH --> QUERY_INIT["QueryService.__init__(ctn_dir, index_id)"]
    QUERY_INIT --> GET_ENTS["QueryService.entities_by_type()"]
    GET_ENTS --> RESOLVE["_resolve_index_id() → gets latest run_uuid"]
    RESOLVE --> LOAD["_ensure_loaded(run_uuid)"]
    
    LOAD -->|Cache Miss| READ_DB["BathoDatabase.get_file_artifacts(run_internal_id)"]
    READ_DB --> DECOMPRESS["Decompress zstd blobs and deserialize JSON"]
    DECOMPRESS --> POPULATE["Populate in-memory _entities & _relationships lists"]
    
    LOAD -->|Cache Hit / Populated| FILTER["Filter by type / file and apply limit"]
    FILTER --> CACHE_SET["_cache_set(cache_key, results)"]
    CACHE_SET --> RETURN["Return filtered entity lists to exporter"]
```

---

## Integration Points

- **Graph Module**: Uses `SymbolIndex` internally during `CodeGraphIndexer.build_graph()` to resolve outbound imports and bind override relationships.
- **Storage Module**: `QueryService` queries the SQLite registry (`BathoDatabase`) to read file artifact blobs.
