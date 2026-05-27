# Batho Fleet Intelligence

> [!WARNING]
> **Proposed Design Specification**
> Fleet Intelligence is a proposed feature design and is not currently implemented in the `batho` package. The REST API endpoints, MCP tools, and `batho bridge`/`batho fleet` CLI commands described in this document are not yet operational.

Batho Fleet Intelligence enables multi-repository discovery, symbol routing, and cross-repository impact analysis using a centralized global registry.

## Architecture

Fleet intelligence follows the **Registry + Router** pattern:
- **Registry**: A central `global.batho` SQLite database mapping workspace paths, public symbol declarations, and cross-repository dependencies (edges).
- **Router**: Local `.batho` artifacts maintain full AST node graphs for performance and portability, while `global.batho` routes fleet-wide queries to the correct local database context.

```
                  ┌─────────────────┐
                  │  global.batho   │
                  │  (SQL registry) │
                  └────────┬────────┘
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
      ┌─────────────┐┌─────────────┐┌─────────────┐
      │ repo-a.batho││ repo-b.batho││ repo-c.batho│
      │ (Local AST) ││ (Local AST) ││ (Local AST) │
      └─────────────┘└─────────────┘└─────────────┘
```

---

## Configuration

The central registry location is determined in order of precedence:
1. `BATHO_GLOBAL_DB` environment variable
2. `paths.global_db_path` option in `batho.yaml`
3. Default path: `~/.batho/global.batho`

### Setting up batho.yaml
Configure the global database path in your local configuration:
```yaml
paths:
  global_db_path: "/opt/batho/global.batho"
```

---

## CLI Registration Workflow

Workspaces and build artifacts are registered in `global.batho` using the `bridge` command.

### Manual Workspace Registration
To register the current repository workspace and its latest index build run:
```bash
batho bridge serve --register
```

### CI/CD Directory Scanning & Ingestion
For large multi-repo fleets, use the `--scan-dir` flag to recursively register all built `.batho` artifacts in a central artifact storage directory:
```bash
batho bridge serve --scan-dir /var/lib/batho/artifacts/
```
On startup, Batho will:
1. Scan for `artifact_*.batho` files.
2. Resolve workspace root directories and Git origins.
3. Index all exported public symbols (classes, functions, interfaces, structs, enums).
4. Auto-detect cross-repository edges (e.g. imports, calls, inheritance) between all workspaces.

---

## HTTP REST API Endpoints

### 1. Fleet Overview
`GET /api/v1/fleet/overview`

Returns metadata of all registered workspaces, resolved cross-repo dependency edges, and fleet-wide metrics.
```json
{
  "ok": true,
  "data": {
    "workspaces": [
      {
        "repo_id": 1,
        "repo_name": "auth-service",
        "repo_path": "/workspace/auth-service",
        "origin_url": "git@github.com:org/auth-service.git"
      }
    ],
    "edges": [
      {
        "edge_id": 1,
        "source_repo_id": 2,
        "target_repo_id": 1,
        "dependency_type": "IMPORTS",
        "source_symbol": "login_handler",
        "target_symbol": "TokenVerifier",
        "confidence_score": 1.0
      }
    ],
    "metrics": {
      "total_repositories": 2,
      "total_symbols": 2580,
      "total_files": 412
    }
  }
}
```

### 2. Global Symbol Search
`GET /api/v1/search/global?q=<query>&type=<type>`

Searches the global index for public symbols matching a name query and optional type filter.
```json
{
  "ok": true,
  "data": {
    "results": [
      {
        "symbol_id": 12,
        "symbol_name": "TokenVerifier",
        "symbol_type": "CLASS",
        "repo_name": "auth-service",
        "file_path": "verifier.py",
        "line_number": 15,
        "fqn": "auth.verifier.TokenVerifier"
      }
    ]
  }
}
```

### 3. Cross-Repo Impact Analysis
`GET /api/v1/fleet/impact?repo_id=<repo_id>&symbol_name=<symbol_name>`

Resolves downstream dependencies on a public symbol, mapping which outside repositories will be impacted by changing it.

---

## AI Agent MCP Cross-Repo Tools

When using Batho as a Model Context Protocol (MCP) server, AI agents gain access to fleet intelligence:

### `search_fleet_symbols`
Search for symbol definitions across all repositories in the fleet.
- **Arguments**:
  - `query` (string, required)
  - `symbol_type` (string, optional)

### `get_cross_repo_impact`
Analyze downstream code impact across all repos before refactoring or changing a public API.
- **Arguments**:
  - `repo_name` (string, required)
  - `symbol_name` (string, required)

### `list_fleet_workspaces`
Retrieve workspaces and active dependency graphs across the entire codebase fleet.
