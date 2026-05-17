---
sidebar_position: 4
title: "3. Deterministic Code Graph Engine"
description: "Entity model, graph consistency, and cross-file resolution"
---

# 3. Deterministic Code Graph Engine

## 3.1 Entity Model

The graph is built on two primitives: **Entities** and **Relationships**. This model enables efficient querying and cross-referencing across large codebases.

### Entity Types

| Type | Description | Example |
|------|-------------|---------|
| `FUNCTION` | Standalone function | `def process_data():` |
| `METHOD` | Class/instance method | `def save(self):` |
| `CLASS` | Class definition | `class UserManager:` |
| `STRUCT` | Struct (Rust/Go) | `type Config struct` |
| `INTERFACE` | Interface/protocol | `interface Repository` |
| `TRAIT` | Rust trait | `trait Sendable` |
| `FIELD` | Attribute/field | `name: str` |
| `ENUM` | Enumeration | `enum Status` |
| `TYPE_ALIAS` | Type alias | `type ID = string` |
| `CONSTANT` | Constant declaration | `const MAX = 100` |
| `MODULE` | Module/package | `package main` |
| `NAMESPACE` | Namespace | `namespace App` |
| `ENTRY_POINT` | Program entry point | `main()` |

### Relationship Types

| Type | Direction | Semantics |
|------|-----------|-----------|
| `IMPORTS` | File → Module | File imports a module |
| `CALLS` | Entity → Entity | Function/method invocation |
| `USES` | Entity → Entity | Variable/type usage |
| `INHERITS` | Class → Class | Inheritance |
| `IMPLEMENTS` | Class → Interface | Interface implementation |
| `DEFINES` | File → Entity | Container definition |

## 3.2 Graph Consistency Model

The `InMemoryGraph` ensures deterministic processing through lazy indexing and automatic deduplication:

```mermaid
flowchart LR
    A[Parse File] --> B{Entity Exists?}
    B -->|Yes| C[Update Entity]
    B -->|No| D[Add Entity]
    C --> E[Invalidate Adjacency]
    D --> E
    E --> F[Lazy Rebuild Index]
    F --> G[Validate Cross-refs]
```

**Key Guarantees:**
- Index built on first `neighbors()` call
- Invalidated on every relationship mutation
- Duplicate relationships silently deduplicated via `has_relationship()`

## 3.3 Cross-File Resolution

The `SymbolIndex` performs a two-pass resolution to enable cross-module references:

```mermaid
flowchart TB
    A[Local Pass] --> B[Resolve symbols within each file]
    B --> C[Global Pass]
    C --> D[Match unresolved imports against exports]
    D --> E{Resolved?}
    E -->|Yes| F[Tag with resolved symbol]
    E -->|No| G[Tag with unresolved: prefix]
    G --> H[Track for later resolution]
```

**Resolution Process:**
1. **Local pass**: Resolve symbols within each file's scope
2. **Global pass**: Match unresolved imports against exported symbols across the repository
3. **Tracking**: Unresolved targets are tagged with `unresolved:` prefix and tracked for later resolution

## 3.4 Example: Cross-File Reference

Consider a Python project with two files:

**models.py:**
```python
class User:
    def __init__(self, name: str):
        self.name = name
```

**services.py:**
```python
from models import User

def create_user(name: str) -> User:
    return User(name)
```

**Graph Representation:**
```json
{
  "entities": [
    {"id": "models.py::User", "type": "CLASS", "file": "models.py"},
    {"id": "models.py::User.__init__", "type": "METHOD", "file": "models.py"},
    {"id": "services.py::create_user", "type": "FUNCTION", "file": "services.py"}
  ],
  "relationships": [
    {"from": "services.py", "to": "models", "type": "IMPORTS"},
    {"from": "services.py::create_user", "to": "models.py::User", "type": "USES"}
  ]
}
```
