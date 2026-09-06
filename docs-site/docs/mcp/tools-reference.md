---
sidebar_position: 5
title: "Tools Reference"
description: "Complete documentation for all 19 Batho MCP tools (15 enabled by default)"
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
| `watch` | `boolean` | No | `false` | Enable file watching for automatic re-indexing |
| `debounce_ms` | `integer` | No | `2000` | Debounce interval in milliseconds for file watch events |
| `max_file_size_kb` | `integer` | No | `null` | Maximum file size in KB to index (null for default) |

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

Get a high-level overview of the codebase: entity counts, relationship breakdown, file list, community summaries, and ambiguous edge count.

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
      "ambiguous_edge_count": 0,
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
| `symbol_roles` | list[string] | No | — | Filter relationships by symbol role (OR semantics). Valid: `Definition`, `Import`, `WriteAccess`, `ReadAccess`, `Generated`, `Declaration`, `Dynamic`, `Heuristic` (case-insensitive) |
| `confidence_threshold` | float | No | — | Only return relationships with `confidence >= threshold` (0.0–1.0). See [Confidence Tiers](#confidence-tiers) |
| `relation_direction` | string | No | `"both"` | Filter by edge direction: `outgoing` (entity is source), `incoming` (entity is target), `both` |
| `name_pattern` | string | No | — | Regex pattern to match entity names |
| `response_format` | string | No | `"concise"` | Output format: `concise`, `detailed` |
| `limit` | int | No | `50` | Max entities to return |
| `offset` | int | No | `0` | Pagination offset |
| `max_tokens` | int | No | `25000` | Token budget |

### Example

```
graph_query(repo="myapp", file_path="src/auth/", entity_types=["function"], limit=20)
graph_query(repo="myapp", symbol_roles=["WriteAccess"], confidence_threshold=0.85)
graph_query(repo="myapp", relation_types=["CALLS"], relation_direction="incoming")
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
| `symbol_roles` | list[string] | No | — | Only traverse edges matching the specified roles (OR semantics). Valid: `Definition`, `Import`, `WriteAccess`, `ReadAccess`, `Generated`, `Declaration`, `Dynamic`, `Heuristic` |
| `confidence_threshold` | float | No | — | Only traverse edges with `confidence >= threshold` (0.0–1.0). See [Confidence Tiers](#confidence-tiers) |
| `relation_direction` | string | No | `"outgoing"` | Direction of edges to traverse: `outgoing` (source→target), `incoming` (target→source, reverse BFS), `both` |
| `response_format` | string | No | `"concise"` | Output format |

### Example

```
trace_path(
  source_entity_id="api.routes.login.handle_login",
  target_entity_id="auth.SessionHandler.create",
  repo="myapp",
  max_depth=10
)

# Trace only high-confidence import edges (reverse direction)
trace_path(
  source_entity_id="auth.SessionHandler.create",
  target_entity_id="api.routes.login.handle_login",
  repo="myapp",
  symbol_roles=["Import"],
  confidence_threshold=0.85,
  relation_direction="incoming"
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
| `symbol_roles` | list[string] | No | — | Filter to entities that participate in relationships with the specified roles. Valid: `Definition`, `Import`, `WriteAccess`, `ReadAccess`, `Generated`, `Declaration`, `Dynamic`, `Heuristic` |
| `limit` | int | No | `25` | Max results to return |
| `response_format` | string | No | `"concise"` | Output format |

### Example

```
search_entities(query="validate", repo="myapp", entity_types=["function"], limit=10)
search_entities(query="config", repo="myapp", symbol_roles=["WriteAccess"])
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

## `batho_status`

Show artifact and watcher status for one or all repos. Read-only.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | All repos | Repo name to check (omit for all registered repos) |

### Example

```
batho_status(repo="myapp")
```

### Output

Returns per-repo artifact status (ready/stale/missing), entity/relationship counts, last build run ID, and watcher state (active/inactive, pending changes).

---

## `batho_list_runs`

List patch/build run IDs for a repo. Read-only.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `limit` | int | No | `20` | Max runs to return |

### Example

```
batho_list_runs(repo="myapp", limit=10)
```

### Output

Returns a list of runs with UUID, timestamp, status, git commit, branch, entity/relationship counts, and duration.

---

## `batho_diff`

Query node-level changes across runs, entities, or files. Read-only.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `run_id` | string | No | Latest patch | Specific run UUID to diff |
| `entity_id` | string | No | — | Filter changes to a specific entity |
| `file_path` | string | No | — | Filter changes by file path |
| `since` | string | No | — | Run UUID to diff from (defaults to previous run) |

### Example

```
batho_diff(repo="myapp", file_path="src/auth/manager.py")
```

### Output

Returns added, removed, modified, and renamed nodes with before/after metadata for each change.

---

## `batho_patch`

Run an incremental patch on an existing artifact. **Destructive** — modifies the artifact database.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `max_file_size_kb` | int | No | Config default | Skip files exceeding this size |
| `graph_backend` | string | No | Config default | `auto`, `in-memory`, or `arrow` |

### Example

```
batho_patch(repo="myapp")
```

### Output

Returns patch stats: files changed, entities added/removed/modified, relationships added/removed, duration, and new run UUID.

---

## `batho_fix`

Run integrity verification and repair on an artifact database. **Destructive** — may modify or delete corrupt artifacts.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `deep` | bool | No | `false` | Deep verification (slower, more thorough) |
| `dry_run` | bool | No | `false` | Report issues without repairing |
| `target` | string | No | `"all"` | Repair target: `all`, `blobs`, `graph`, `state` |
| `phase` | int | No | — | Run only a specific repair phase (1-N) |
| `parallel` | bool | No | `false` | Run repair phases in parallel |

### Example

```
batho_fix(repo="myapp", dry_run=true)
```

### Output

Returns verification results, issues found, repairs applied (or proposed if `dry_run`), and a tamper-evident audit log entry.

---

## `batho_build`

Run a full index build for a repository. **Destructive** — deletes and rebuilds the artifact database. **Disabled by default** — enable via [Tool Gating](/docs/mcp#tool-gating).

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `full` | bool | No | `false` | Force full rebuild (deletes existing artifact) |
| `max_workers` | int | No | CPU count | Max parallel workers for parsing |
| `max_file_size_kb` | int | No | Config default | Skip files exceeding this size |
| `graph_backend` | string | No | Config default | `auto`, `in-memory`, or `arrow` |

### Example

```
batho_build(repo="myapp", full=true)
```

### Output

Returns build stats: entity count, relationship count, file count, duration, community count, and new run UUID.

---

## `batho_export`

Export a JSON view or Pack artifact from the code graph. **Destructive** — writes files to disk. **Disabled by default** — enable via [Tool Gating](/docs/mcp#tool-gating).

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `view` | string | No | `"storage"` | Export view: `storage` or `agent` |
| `output` | string | No | Auto-generated | Output file path |
| `index_id` | string | No | Latest | Specific index/run ID to export |
| `filter_pattern` | string | No | — | Glob pattern to filter files |
| `category` | string | No | `"all"` | Export category: `all`, `entities`, `relationships`, `files` |
| `token_budget` | int | No | — | Token budget for LLM-optimized export |
| `json_mode` | bool | No | `true` | Export as JSON (false = Pack binary) |
| `include_relationships` | bool | No | `false` | Include relationship data in export |

### Example

```
batho_export(repo="myapp", view="agent", json_mode=true)
```

### Output

Returns the export file path and summary stats (entities exported, file size).

---

## `batho_load`

Unpack a transport artifact ZIP into `.batho/artifact/`. **Destructive** — overwrites the artifact directory. **Disabled by default** — enable via [Tool Gating](/docs/mcp#tool-gating).

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `artifact_path` | string | Yes | — | Path to the transport artifact ZIP file |
| `repo` | string | No | Registry default | Repo name from registry |
| `force` | bool | No | `false` | Overwrite existing artifact without confirmation |

### Example

```
batho_load(artifact_path="/tmp/myapp_artifact.zip", repo="myapp")
```

### Output

Returns the unpacked artifact path and verification status.

---

## `batho_gc`

Run garbage collection and maintenance on an artifact database. **Destructive** — may delete old run artifacts. **Disabled by default** — enable via [Tool Gating](/docs/mcp#tool-gating).

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | No | Registry default | Repo name from registry |
| `subcommand` | string | No | `"status"` | GC action: `status`, `prune`, `compact`, `reclaim` |
| `run_uuid` | string | No | — | Target a specific run UUID for pruning |
| `older_than` | int | No | — | Prune runs older than N days |

### Example

```
batho_gc(repo="myapp", subcommand="prune", older_than=30)
```

### Output

Returns GC stats: runs pruned, disk space reclaimed, remaining run count, and fragmentation metrics.

---

## Relationship Filtering

`graph_query`, `trace_path`, and `search_entities` support three relationship-level filters that compose with AND semantics. All filters default to `None` (no filtering) for backward compatibility.

### `symbol_roles`

Filters relationships by the `SymbolRole` bitmask stored on each edge. A relationship is included if **any** of the specified roles match (OR semantics within the parameter).

| Role | Bit | Description |
|------|-----|-------------|
| `Definition` | 1 | Relationship defines the target entity |
| `Import` | 2 | Import statement |
| `WriteAccess` | 4 | Write access to the target |
| `ReadAccess` | 8 | Read access to the target |
| `Generated` | 16 | Auto-generated code |
| `Declaration` | 32 | Forward declaration |
| `Dynamic` | 64 | Dynamic dispatch / runtime resolution |
| `Heuristic` | 128 | Inferred by heuristic, not directly extracted |

Role names are **case-insensitive** (`"writeaccess"`, `"WriteAccess"`, `"WRITEACCESS"` are all valid). Invalid role names return an error listing the valid options.

> **Requires** an artifact built with the `roles` column (Batho v1.4.2+). Older artifacts return a clear error directing you to run `batho build --full`.

### `confidence_threshold`

Filters relationships by their resolution confidence score. Only edges with `confidence >= threshold` are returned or traversed.

<a id="confidence-tiers"></a>

#### Confidence Tiers

| Strategy | Confidence | Description |
|----------|-----------|-------------|
| Direct extraction | 1.0 | Captured directly by tree-sitter (no resolution needed) |
| `exact_match` | 0.95 | Direct dotpath lookup |
| `stdlib_method` | 0.90 | Stdlib method / module prefix match |
| `import_map` | 0.85 | Import-map cross-file resolution |
| `parent_chain` | 0.75 | Parent stub chain building |
| `scope_qualified` | 0.70 | Caller-scope qualified path |
| `receiver_type` | 0.65 | Receiver-type inference |
| `ambiguous` | 0.50 | Multiple equally-plausible candidates (kept for manual review) |
| `unresolved` | 0.0 | No match found |

The threshold must be between `0.0` and `1.0` inclusive. Use `0.85` for high-confidence edges only, or `0.0` to include everything.

> **Note**: Confidence values are stored as `float32` in Arrow IPC. Values like `0.85` may be stored as `0.84999996` due to binary representation. Use a slightly lower threshold (e.g., `0.84`) if you need to include edges at exact tier boundaries.

### `relation_direction`

Filters relationships by edge direction relative to the entity:

| Value | Behavior |
|-------|----------|
| `"outgoing"` | Entity is the **source** (`source_id` matches) |
| `"incoming"` | Entity is the **target** (`target_id` matches) — enables "who calls X?" queries without inverse relationship types |
| `"both"` (default for `graph_query`) | No direction filtering |
| `"outgoing"` (default for `trace_path`) | BFS follows source→target edges |
| `"incoming"` (trace_path) | Reverse BFS: follows target→source edges |
| `"both"` (trace_path) | BFS follows edges in either direction |

> **Replaces inverse relationship types**: `relation_direction="incoming"` with `relation_types=["CALLS"]` returns all callers of an entity — equivalent to the legacy `CALLED_BY` type, but without requiring separate edge storage.

### `applied_filters` in Output

All active filters are echoed in `structuredContent.applied_filters`:

```json
{
  "applied_filters": {
    "symbol_roles": ["WriteAccess"],
    "confidence_threshold": 0.85,
    "relation_direction": "incoming",
    "entity_types": ["FUNCTION"],
    "relation_types": ["CALLS"]
  }
}
```

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
