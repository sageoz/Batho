---
sidebar_position: 19
title: "patch-info"
description: "Show detailed patch operation information"
---

# `patch-info` Command

Display detailed information about a specific patch operation, including changes, entities affected, and metadata.

## Usage

```bash
batho patch-info --root /path/to/repo --patch-id PATCH_ID [options]
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |
| `--patch-id` | required | Patch operation ID |
| `--format` | `json` | Output format: `json` or `summary` |

## Finding Patch IDs

```bash
# List all patches to find IDs
batho patches --root . --format timeline
```

## Examples

```bash
# Show detailed patch info in JSON
batho patch-info --root . --patch-id batho_uuid_20260517T120000Z

# Show human-readable summary
batho patch-info --root . --patch-id batho_uuid_20260517T120000Z --format summary

# Use short patch ID (first 12 chars of UUID)
batho patch-info --root . --patch-id uuid_20260517
```

## Output Formats

### JSON Format (default)

```json
{
  "operation_id": "batho_uuid_20260517T120000Z",
  "operation_type": "incremental",
  "base_snapshot_id": "batho_project_abc123_20260501T100000Z.json",
  "timestamp": "2026-05-17T12:00:00Z",
  "status": "applied",
  "files_changed": [
    {
      "path": "src/auth.py",
      "change_type": "modified",
      "entities_added": 5,
      "entities_removed": 2
    }
  ],
  "entities_added": 42,
  "entities_removed": 8,
  "relationships_added": 15,
  "relationships_removed": 3,
  "duration_seconds": 2.3
}
```

### Summary Format

Human-readable summary:

```
Patch: batho_uuid_20260517T120000Z
Type: incremental
Base: batho_project_abc123_20260501T100000Z.json
Time: 2026-05-17T12:00:00Z
Status: applied

Files Changed: 15
  - src/auth.py (modified, +5/-2 entities)
  - src/api.py (modified, +12/-4 entities)
  ...

Entities: +42 added, -8 removed
Relationships: +15 added, -3 removed
Duration: 2.3s
```

## Use Cases

- **Detailed audit**: Understand exactly what changed in a patch
- **Debugging**: Investigate why a patch behaved unexpectedly
- **Documentation**: Include patch details in change logs
- **Analysis**: Correlate patches with external changes (commits, PRs)

## Related Commands

- `patches` - List all patch operations
- `patch-chain` - Show patch chain for a snapshot
- `apply-patch` - Apply a patch from a file
