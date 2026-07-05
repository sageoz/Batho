---
sidebar_position: 5
title: "Tools Reference"
description: "Complete documentation for all 10 Batho MCP tools"
---

# MCP Tools Reference

All Batho MCP tools return dual output:
- **`content`** — Compact markdown for the AI model (token-optimized)
- **`structuredContent`** — Full JSON for programmatic consumers

All graph tools accept `repo` as an optional parameter. If omitted, the first registered repo is used. Use `list_repos` to see available repos.

---

## `list_repos`

List all registered repos with artifact status and entity counts.

### Parameters

None.

### Example

```
list_repos()
```

### Output

**Markdown:**
```markdown
## Registered Repos

- **frontend** — /projects/frontend (✓ ready, 892 entities)
- **backend** — /projects/backend (✓ ready, 650 entities)
```

**JSON:**
```json
{
  "repos": [
    {"name": "frontend", "path": "/projects/frontend", "has_artifact": true, "entity_count": 892},
    {"name": "backend", "path": "/projects/backend", "has_artifact": true, "entity_count": 650}
  ],
  "total": 2
}
```

---

## `add_repo`

Register a repository in the Batho MCP registry. The repo must have a `.batho` artifact (run `batho build` first).

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | — | Repo name (unique identifier in registry) |
| `path` | string | Yes | — | Absolute path to the repository root |

### Example

```
add_repo(name="myapp", path="/projects/myapp")
```

### Output

**Markdown:**
```markdown
## Repo Registered

- **myapp** — /projects/myapp
- Entities: 892
- Artifact: ✓ ready
```

**JSON:**
```json
{"name": "myapp", "path": "/projects/myapp", "entity_count": 892, "has_artifact": true}
```

---

## `remove_repo`

Remove a repository from the Batho MCP registry.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | — | Repo name to remove |

### Example

```
remove_repo(name="myapp")
```

### Output

**Markdown:**
```markdown
## Repo Removed

- **myapp** — removed from registry
```

**JSON:**
```json
{"name": "myapp", "removed": true}
```

---

## `graph_overview`

Get a high-level overview of the codebase: entity counts, relationship breakdown, file list, and community summaries.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `response_format` | string | No | `"summary"` | Output detail level: `summary`, `concise`, `detailed` |
| `max_tokens` | int | No | `25000` | Token budget for markdown output |

### Example

```
graph_overview(repo="myapp", response_format="summary")
```

### Output

**Markdown (`content`):**
```markdown
# Codebase Overview

**Stats:** 1542 entities, 4823 relationships, 312 files
**Run:** abc-123 | commit: a1b2c3d | branch: main

## Entity Breakdown
- function: 892
- class: 124
- method: 387

## Communities
1. **UserService** — 45 entities across 8 files
2. **ApiClient** — 32 entities across 5 files
```

**JSON (`structuredContent`):**
```json
{
  "overview": {
    "stats": {
      "total_entities": 1542,
      "total_relationships": 4823,
      "total_files": 312,
      "entity_breakdown": {"function": 892, "class": 124},
      "relationship_breakdown": {"calls": 2100, "imports": 1800},
      "run_id": "abc-123",
      "git_commit": "a1b2c3d"
    },
    "communities": [...]
  },
  "meta": {
    "artifact_generation": 3,
    "tokens_used": 1840,
    "token_budget": 25000,
    "truncated": false
  }
}
```

---

## `graph_query`

Query the code graph with optional filters. Returns paginated nodes and edges.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `file_path` | string | No | — | Filter entities by file path |
| `entity_types` | list[string] | No | — | Filter by entity type (e.g., `["function", "class"]`) |
| `relation_types` | list[string] | No | — | Filter relationships by type |
| `name_pattern` | string | No | — | Regex pattern to match entity names |
| `response_format` | string | No | `"concise"` | Output format: `concise`, `detailed` |
| `limit` | int | No | `50` | Max entities to return |
| `offset` | int | No | `0` | Pagination offset |
| `max_tokens` | int | No | `25000` | Token budget |

### Example

```
graph_query(repo="myapp", file_path="src/auth/", entity_types=["function"], limit=20)
```

### Output

Returns nodes (entities) and edges (relationships) matching the filters, with pagination metadata in `structuredContent`.

---

## `get_entity`

Get detailed information about a single entity, including its relationships and optionally source code.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `entity_id` | string | Yes | — | Entity ID from previous query results |
| `repo` | string | No | Registry default | Repo name from registry |
| `include_source` | bool | No | `false` | Include source code snippet |
| `response_format` | string | No | `"detailed"` | Output format |

### Example

```
get_entity(entity_id="src/auth.py:AuthManager.validate_token", repo="myapp", include_source=true)
```

### Output

Returns the entity's metadata (name, type, file, line range), all relationships where it appears as source or target, and optionally the source code from `storage_views`.

---

## `trace_path`

Find the shortest path between two entities in the code graph using BFS traversal.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_entity_id` | string | Yes | — | Starting entity ID |
| `target_entity_id` | string | Yes | — | Target entity ID |
| `repo` | string | No | Registry default | Repo name from registry |
| `max_depth` | int | No | `5` | Maximum BFS depth (hops) |
| `relation_types` | list[string] | No | — | Only traverse these relationship types |
| `response_format` | string | No | `"concise"` | Output format |

### Example

```
trace_path(
  source_entity_id="api.routes.login.handle_login",
  target_entity_id="auth.SessionHandler.create",
  repo="myapp",
  max_depth=10
)
```

### Output

**Markdown:**
```markdown
## Path Trace
  handle_login
  → [CALLS] AuthManager.validate_token
  → [CALLS] SessionHandler.create

Depth: 3 hops
```

**JSON:**
```json
{
  "path": [
    {"entity_id": "api.routes.login.handle_login", "relation_type": "", "name": "handle_login"},
    {"entity_id": "auth.AuthManager.validate_token", "relation_type": "CALLS", "name": "validate_token"},
    {"entity_id": "auth.SessionHandler.create", "relation_type": "CALLS", "name": "create"}
  ],
  "depth": 2,
  "meta": {"artifact_generation": 3}
}
```

---

## `get_file_graph`

Get all entities and relationships within a single file. Optionally includes cross-file reference stubs.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | — | File path relative to repo root |
| `repo` | string | No | Registry default | Repo name from registry |
| `include_cross_file_refs` | bool | No | `true` | Include entities referenced from other files |
| `response_format` | string | No | `"concise"` | Output format |
| `max_tokens` | int | No | `25000` | Token budget |

### Example

```
get_file_graph(file_path="src/auth/manager.py", repo="myapp", include_cross_file_refs=true)
```

### Output

Returns all entities defined in the file, all relationships within the file, and stub entities for cross-file references (when `include_cross_file_refs` is true).

---

## `search_entities`

Search for entities by name using substring or regex matching.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | — | Search query (substring or regex) |
| `repo` | string | No | Registry default | Repo name from registry |
| `entity_types` | list[string] | No | — | Filter by entity type |
| `limit` | int | No | `25` | Max results to return |
| `response_format` | string | No | `"concise"` | Output format |

### Example

```
search_entities(query="validate", repo="myapp", entity_types=["function"], limit=10)
```

### Output

**Markdown:**
```markdown
## Search Results (8 matches, showing 8)
- validate_token [function] src/auth/manager.py:L45-62
- validate_session [function] src/auth/session.py:L12-28
- validate_input [function] src/api/middleware.py:L8-20
...
```

---

## `get_delta`

Get incremental changes from the latest patch run (or a specific run). Shows added, removed, modified, and renamed nodes.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `run_id` | string | No | Latest patch | Specific run UUID |
| `change_kind` | string | No | All | Filter: `added`, `removed`, `modified`, `renamed` |
| `file_path` | string | No | All | Filter changes by file path |
| `limit` | int | No | `100` | Max changes to return |
| `offset` | int | No | `0` | Pagination offset |
| `response_format` | string | No | `"concise"` | Output format |

### Example

```
get_delta(repo="myapp", change_kind="added", limit=20)
```

### Output

Returns node-level changes (entity name, change kind, file path, line range), delta stats (nodes added/removed/modified/renamed), and run metadata (git commit, branch, duration).

---

## Response Formats

| Format | Token Efficiency | Use Case |
|--------|-----------------|----------|
| `summary` | Most compact | Codebase orientation, architecture overview |
| `concise` | Balanced | General queries, search results, file graphs |
| `detailed` | Most verbose | Deep dives with source code, full metadata |

## Token Budgeting

All tools accept `max_tokens` (default: 25,000). When output exceeds the budget:
1. Markdown is truncated with a `[truncated]` marker
2. `structuredContent.meta.truncated` is set to `true`
3. Pagination hints are included for follow-up queries

Token estimation uses a `len(text) / 4` heuristic (approximately 4 characters per token).

## Error Handling

Errors return a `ToolResult` with:
- **`content`**: `Error: <message>` in plain text (plus an optional `Hint: <hint>` on a new line).
- **`structuredContent`**: A JSON object containing:
  ```json
  {
    "error": true,
    "error_type": "CLIENT_ERROR",
    "message": "Error details",
    "retryable": false,
    "hint": "Actionable hint"
  }
  ```

Common errors:
- `No Batho artifact found at <path>. Run 'batho build' first.`
- `No repos registered. Use add_repo to register a repo.`
- `Repo '<name>' not found in registry. Available repos: [...]`
- `File not indexed: <path>`
- `Entity not found: <entity_id>`
- `No patch runs found. Run 'batho patch' first.`
