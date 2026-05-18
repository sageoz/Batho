# Cross-Repo Search

The Batho MCP hub supports searching across multiple workspaces simultaneously.

## When to Use Cross-Repo Tools

Cross-repo search is ideal for:

- **Multi-repo projects** — Monorepos with shared code
- **Library usage** — Finding where a dependency is used
- **Symbol tracking** — Finding all definitions of a symbol
- **Dependency analysis** — Understanding package relationships

## Available Tools

### cross_search

Search for entities across workspaces.

```python
cross_search(
    query: str,                    # Search query
    workspaces: list[str] | null,  # Filter by workspace IDs
    tags: list[str] | null,        # Filter by workspace tags
    kinds: list[str] | null,       # Entity types (function, class, etc.)
    limit_per_ws: int = 25,        # Results per workspace
    merge_strategy: str = "score_desc"  # How to merge results
)
```

**Example:**
```python
# Find "User" class across all Python workspaces
result = cross_search(
    query="class User",
    tags=["python"],
    kinds=["class"]
)
```

### cross_symbols

Find symbol definitions across workspaces.

```python
cross_symbols(
    name: str,                     # Symbol name
    workspaces: list[str] | null,  # Filter by workspace
    tags: list[str] | null,        # Filter by tag
    kinds: list[str] | null        # Symbol types
)
```

**Example:**
```python
# Find all "process_request" function definitions
symbols = cross_symbols(
    name="process_request",
    kinds=["function"]
)
```

### cross_dependencies

Find package dependencies across workspaces.

```python
cross_dependencies(
    package: str,                  # Package name
    workspaces: list[str] | null,  # Filter by workspace
    tags: list[str] | null         # Filter by tag
)
```

**Example:**
```python
# Find all workspaces using "requests" library
deps = cross_dependencies(package="requests")
```

## Merge Strategies

| Strategy | Description |
|----------|-------------|
| `score_desc` | Sort by relevance score (default) |
| `alphabetical` | Sort by workspace then entity name |
| `recent` | Sort by most recent index timestamp |

## Configuration

Enable cross-repo search in `mcp.yaml`:

```yaml
cross_repo:
  enabled: true
  max_workspaces: 100
  max_index_bytes: 104857600  # 100MB
```

## Performance

Cross-repo search uses an in-memory index for fast queries:

- Index built on first access
- Incremental updates on workspace changes
- LRU eviction when memory limit reached

**Benchmarks (warm):**
- 5 workspaces: p95 < 150ms
- 50 workspaces: p95 < 400ms

## Use Cases

### Finding Shared Code

```python
# Find where "AuthService" is imported
cross_search(
    query="from auth import AuthService",
    kinds=["import"]
)
```

### Tracking API Changes

```python
# Find all "POST /api/users" handlers
cross_search(
    query="@app.post /api/users",
    kinds=["endpoint"]
)
```

### Multi-Language Projects

```python
# Find all TypeScript interfaces
cross_search(
    query="interface",
    kinds=["interface"],
    tags=["typescript"]
)
```
