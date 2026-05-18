# MCP Configuration

Configure the Batho MCP hub via `~/.batho/mcp.yaml` or a project-specific config.

## Configuration File

```yaml
schema_version: "1"

server:
  host: "127.0.0.1"
  port: 8765
  request_timeout_seconds: 30

residency:
  max_resident_workspaces: 32
  idle_timeout_seconds: 300
  eviction_policy: "lru"

concurrency:
  global_inflight_limit: 100
  per_workspace_limit: 20

discovery:
  enabled: true
  ctn_dir_globs:
    - "**/.ctn"
  exclude_patterns:
    - "**/node_modules/**"
    - "**/__pycache__/**"

cross_repo:
  enabled: true
  max_workspaces: 100
  max_index_bytes: 104857600  # 100MB

workspaces:
  - id: "my-project"
    ctn_dir: "/path/to/project/.ctn"
    tags: ["python", "production"]
    read_only: false
```

## Server Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `host` | string | `"127.0.0.1"` | Bind address |
| `port` | integer | `8765` | HTTP server port |
| `request_timeout_seconds` | integer | `30` | Request timeout |

## Residency Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `max_resident_workspaces` | integer | `32` | Max workspaces in memory |
| `idle_timeout_seconds` | integer | `300` | Evict after idle time |
| `eviction_policy` | string | `"lru"` | Eviction strategy |

## Concurrency Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `global_inflight_limit` | integer | `100` | Max concurrent requests |
| `per_workspace_limit` | integer | `20` | Max requests per workspace |

## Discovery Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable auto-discovery |
| `ctn_dir_globs` | list | `[]` | Glob patterns for .ctn dirs |
| `exclude_patterns` | list | `[]` | Patterns to exclude |

## Cross-Repo Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable cross-repo search |
| `max_workspaces` | integer | `100` | Max workspaces in index |
| `max_index_bytes` | integer | `104857600` | Max index size |

## Workspace Options

| Option | Type | Description |
|--------|------|-------------|
| `id` | string | Unique workspace identifier |
| `ctn_dir` | string | Path to `.ctn` directory |
| `tags` | list | Optional tags for filtering |
| `read_only` | boolean | Prevent mutations |

## Environment Variables

- `BATHO_MCP_CONFIG` — Override config file path
- `BATHO_MCP_PORT` — Override server port
- `BATHO_MCP_HOST` — Override server host
