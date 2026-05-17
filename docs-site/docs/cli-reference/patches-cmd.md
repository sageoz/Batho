---
sidebar_position: 18
title: "patches"
description: "List patch operations"
---

# `patches` Command

List all patch operations with optional filtering by type, snapshot, or format.

## Usage

```bash
batho patches --root /path/to/repo [options]
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |
| `--format` | `json` | Output format: `json` or `timeline` |
| `--operation-type` | all | Filter by operation type (e.g., `incremental`, `diff`) |
| `--base-snapshot` | all | Filter by base snapshot ID |

## Examples

```bash
# List all patches in JSON format
batho patches --root .

# List patches in human-readable timeline format
batho patches --root . --format timeline

# Filter by operation type
batho patches --root . --operation-type incremental

# Filter by base snapshot
batho patches --root . --base-snapshot batho_project_abc123_20260501T100000Z.json

# Combine filters
batho patches --root . --format timeline --operation-type diff
```

## Output Formats

### JSON Format (default)

```json
[
  {
    "operation_id": "batho_uuid_20260517T120000Z",
    "operation_type": "incremental",
    "base_snapshot_id": "batho_project_abc123_20260501T100000Z.json",
    "timestamp": "2026-05-17T12:00:00Z",
    "files_changed": 15,
    "entities_added": 42,
    "entities_removed": 8,
    "status": "applied"
  }
]
```

### Timeline Format

Human-readable chronological display:

```
2026-05-17 12:00:00Z - incremental (15 files, +42/-8 entities) - applied
2026-05-16 18:30:00Z - diff (3 files, +12/-2 entities) - applied
2026-05-16 10:15:00Z - incremental (8 files, +25/-5 entities) - applied
```

## Operation Types

| Type | Description |
|------|-------------|
| `incremental` | True incremental patch using snapshot diff |
| `diff` | Patch from unified diff file |
| `scan` | Patch from file hash scan |

## Use Cases

- **History audit**: Review all changes applied to the index
- **Debugging**: Identify when specific changes were introduced
- **Rollback planning**: Find patches that might need reversal
- **CI/CD tracking**: Monitor patch operations in build pipelines

## Related Commands

- `patch-info` - Show detailed information for a specific patch
- `patch-chain` - Show patch chain for a snapshot
- `patch` - Apply a new patch
