---
sidebar_position: 3
title: "Bridge Artifacts"
description: "Artifact types and schema reference"
---

# Bridge Artifacts

## Artifact Types

| Type | Schema | Description |
|------|--------|-------------|
| `graph` | `graph.v1` | Entities + relationships |
| `bsg` | `bsg.v1` | Structured symbol graph |
| `bsg_compressed` | `bsg.v1` | Token-budgeted compressed output |
| `bsg_full` | `bsg.v1` | Full textual BSG output |
| `bsg_hierarchical` | `bsg.v1` | Hierarchical directory view |
| `snapshot` | `snapshot.v1` | Time Machine snapshot |
| `patch` | `patch.v1` | Patch operation record |
| `metrics` | `metrics.v1` | Indexing performance metrics |

## graph.json Example

```json
{
  "schema_version": "graph.v1",
  "entities": [
    {"id": "e1", "name": "login", "type": "function", "file": "auth.py", "start_line": 10, "end_line": 25}
  ],
  "relationships": [
    {"source_id": "e1", "target_id": "e2", "type": "IMPORTS"}
  ]
}
```

## bsg.json Example

```json
{
  "schema_version": "bsg.v1",
  "nodes": [
    {
      "id": "e1",
      "type": "FUNCTION",
      "name": "login",
      "file": "src/auth.py",
      "start_line": 10,
      "end_line": 25
    }
  ],
  "edges": [],
  "indexes": {
    "nodes_by_file": {
      "src/auth.py": ["e1"]
    }
  }
}
```
