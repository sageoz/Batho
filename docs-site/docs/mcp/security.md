# MCP Security

The Batho MCP hub is designed with security as a core principle.

## Loopback-Only Model

The MCP hub binds to **localhost only** by default (`127.0.0.1`). This ensures:

- No remote network exposure
- Only local processes can connect
- Safe for developer machines

To bind to a specific interface:

```yaml
server:
  host: "127.0.0.1"  # or "0.0.0.0" for all interfaces (not recommended)
  port: 8765
```

## Threat Model

### What We Protect Against

| Threat | Mitigation |
|--------|------------|
| Remote code execution | Loopback-only binding |
| Data exfiltration | No external network calls |
| Path traversal | Path validation, no `..` allowed |
| Cross-origin attacks | Origin header validation |
| Cache poisoning | Checksum verification |

### What We Assume

- User has local machine access
- Local processes are trusted
- `.ctn` directories are trusted

## Access Control

### Workspace Isolation

Workspaces are isolated by:
- Separate file handles
- Independent caches
- No shared mutable state

### Read-Only Mode

Mark workspaces as read-only:

```yaml
workspaces:
  - id: "production"
    ctn_dir: "/path/to/.ctn"
    read_only: true
```

When `read_only: true`:
- `patch.create` rejected
- `index.refresh` rejected
- `bsg.regenerate` rejected

## Input Validation

### Path Validation

All file paths are validated:
- No absolute paths (must be relative)
- No `..` traversal
- Restricted to workspace root

### Query Validation

- Artifact type whitelist
- Limit enforcement
- Query length limits

## Audit Logging

All tool calls are logged with:

```json
{
  "tool": "artifact_get",
  "workspace_id": "my-project",
  "args_hash": "a1b2c3d4",
  "latency_ms": 45.2,
  "status": "success"
}
```

Error responses include:
- `error_code` — Machine-readable code
- `error_class` — Exception type
- `detail` — Redacted message

## Best Practices

1. **Never expose to public networks** — Keep `host: 127.0.0.1`
2. **Use read-only workspaces** — For CI/automation
3. **Limit concurrent requests** — Set `concurrency.per_workspace_limit`
4. **Monitor with Prometheus** — Enable telemetry for observability

## Privacy

The hub does not:
- Send data to external servers
- Collect usage analytics (opt-in only)
- Store credentials

Telemetry is local-only and includes:
- Tool call counts
- Latency histograms
- Workspace state

No source code or file contents are transmitted.
