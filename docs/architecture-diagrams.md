---
title: Batho Core Architecture Diagrams (v1)
---

## 1) End-to-end flow
```
Developer CLI
    |  batho-core index/patch
    v
CodeGraphIndexer
    - Walk repo (ignores, size/binary guard)
    - Extract AST entities/relationships
    - Cache mtime+SHA
    v
InMemoryGraph (entities, relationships)
    v
RepoMap
    - Build relative-path map
    - Derive deps (imports/calls/uses)
    - Render JSON + architecture.md (token budget aware)
    v
Outputs (.ctn/<index_id>/)
    - graph.json
    - repomap.json
    - architecture.md
    - index.json (metadata, staleness)
```

## 2) Patch path (target state)
```
PR diff / changed files
    v
CLI patch
    v
File selection (diff + explicit)
    v
CodeGraphIndexer
    - Reindex changed files only
    - Merge into existing graph
    v
Graph delta applied
    v
RepoMap rebuild (budgeted)
    v
Metadata update
    - counts, repo hash, staleness
    - patched file list
```

## 3) Snapshot + diff
```
Current graph + repomap
    v
Time Machine create_snapshot
    - snapshot_id: batho_<uuid>_<ts>
    - write .ctn/snapshots/<id>.json

Two snapshots (A,B)
    v
Time Machine diff_snapshots
    - entity_delta
    - relationship_delta
    - added/removed files
    - common file count
```

## 4) Webhook (future wiring)
```
GitHub webhook (push/PR)
    v
Webhook handler
    - validate signature (TBD)
    - parse payload
    - determine changed files
    v
Trigger patch/index + snapshot
    - reuse patch flow
```

## 5) Data model sketch
```
InMemoryGraph
  - entities: {id -> Entity(file, type, span, name, parent)}
  - relationships: [Relationship(source_id, target_id, type=IMPORTS|CALLS|USES)]

RepoMap JSON
  files: {
    "path/to/file.py": {
       entities: [ {name, type, start_line, end_line, id}... ],
       dependencies: ["other/file.py", "os"]
    }
  }
  dependencies: { "path/to/file.py": ["other/file.py", ...] }
```
