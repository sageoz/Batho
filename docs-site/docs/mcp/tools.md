# MCP Tools Reference

The Batho MCP hub exposes tools for workspace management, artifact retrieval, and cross-repo search.

## Workspace Tools

### workspace_list

List all registered workspaces.

```python
workspace_list() -> list[WorkspaceInfo]
```

**Response:**
```json
{
  "ok": true,
  "data": [
    {
      "id": "my-project",
      "ctn_dir": "/path/to/.ctn",
      "tags": ["python"],
      "resident": true
    }
  ]
}
```

### workspace_health

Get health status of workspaces.

```python
workspace_health(workspace_id: str | null) -> list[WorkspaceHealth]
```

### workspace_stats

Get registry statistics for a workspace.

```python
workspace_stats(workspace_id: str | null) -> RegistryStats
```

## Index Tools

### index_list

List all available index IDs and timestamps.

```python
index_list(workspace_id: str | null) -> IndexList
```

### index_get

Get metadata for a specific index.

```python
index_get(index_id: str, workspace_id: str | null) -> IndexMetadata
```

## Artifact Tools

### artifact_list

List artifact records, optionally filtered by type.

```python
artifact_list(
    artifact_type: str | null = null,
    limit: int | null = null,
    workspace_id: str | null = null
) -> list[ArtifactRecord]
```

### artifact_get

Load and return full JSON content for an artifact type.

```python
artifact_get(
    artifact_type: str,
    index_id: str | null = null,
    workspace_id: str | null = null
) -> ArtifactContent
```

**Example:**
```python
# Get BSG compressed output
result = artifact_get(artifact_type="bsg_json", workspace_id="my-project")
```

### artifact_get_by_path

Load artifact content by its exact logical path.

```python
artifact_get_by_path(
    logical_path: str,
    workspace_id: str | null = null
) -> ArtifactWithRecord
```

### artifact_search

Fuzzy search artifacts by logical path.

```python
artifact_search(
    query: str,
    artifact_type: str | null = null,
    workspace_id: str | null = null
) -> list[ArtifactRecord]
```

## File Tools

### file_read

Read file content with optional BSG entity overlay.

```python
file_read(
    path: str,
    with_entities: bool = false,
    workspace_id: str | null = null
) -> FileContent
```

### file_list

List files in the workspace.

```python
file_list(
    glob: str | null = null,
    limit: int | null = null,
    workspace_id: str | null = null
) -> list[FileInfo]
```

### file_outline

Get structural outline of a file.

```python
file_outline(
    path: str,
    workspace_id: str | null = null
) -> FileOutline
```

## Graph Tools

### graph_get

Get the full code graph.

```python
graph_get(
    index_id: str | null = null,
    workspace_id: str | null = null
) -> CodeGraph
```

### graph_search

Search the code graph.

```python
graph_search(
    query: str,
    kinds: list[str] | null = null,
    limit: int = 25,
    workspace_id: str | null = null
) -> list[GraphEntity]
```

### graph_relationships

Get relationships for an entity.

```python
graph_relationships(
    entity_id: str,
    direction: str = "both",
    workspace_id: str | null = null
) -> list[Relationship]
```

## Cross-Repo Tools

### cross_search

Search across multiple workspaces.

```python
cross_search(
    query: str,
    workspaces: list[str] | null = null,
    tags: list[str] | null = null,
    kinds: list[str] | null = null,
    limit_per_ws: int = 25,
    merge_strategy: str = "score_desc"
) -> CrossSearchResult
```

### cross_symbols

Find symbol definitions across workspaces.

```python
cross_symbols(
    name: str,
    workspaces: list[str] | null = null,
    tags: list[str] | null = null,
    kinds: list[str] | null = null
) -> list[SymbolResult]
```

### cross_dependencies

Find package dependencies across workspaces.

```python
cross_dependencies(
    package: str,
    workspaces: list[str] | null = null,
    tags: list[str] | null = null
) -> list[DependencyResult]
```

## Snippet Tools

### snippet_generate

Generate agent-ready code snippets.

```python
snippet_generate(
    file_path: str,
    focus_entities: list[str] | null = null,
    max_tokens: int = 4000,
    workspace_id: str | null = null
) -> Snippet
```

## Known Artifact Types

- `graph.json` — Full code graph (entities + relationships)
- `bsg_compressed.json` — LLM-ready compressed output
- `bsg_full.json` — Full BSG with signatures
- `bsg_hierarchical.json` — Hierarchical directory view
- `file_cache.json` — File metadata cache
