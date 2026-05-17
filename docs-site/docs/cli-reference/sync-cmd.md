---
sidebar_position: 15
title: "sync"
description: "Sync artifacts to cloud endpoint"
---

# `sync` Command

Sync pending artifacts to a configured cloud endpoint for cross-repo aggregation and backup.

## Usage

```bash
batho sync --root /path/to/repo [options]
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | current directory | Path to repository root |
| `--dry-run` | off | Show what would be synced without uploading |
| `--type` | all | Filter by artifact types (can specify multiple times) |
| `--status` | off | Show sync status and exit |
| `--retry-failed` | off | Retry previously failed uploads |
| `-v`, `--verbose` | off | Show detailed upload progress |

## Examples

```bash
# Preview pending artifacts (no upload)
batho sync --root . --dry-run

# Sync all pending artifacts
export BATHO_CLOUD_SYNC_ENABLED=true
export BATHO_CLOUD_ENDPOINT="https://sync.batho.dev/v1"
export BATHO_CLOUD_API_KEY="batho_live_xxxxx"
batho sync --root .

# Sync only specific artifact types
batho sync --root . --type snapshot --type bsg

# Show sync status summary
batho sync --root . --status

# Retry only failed artifact uploads
batho sync --root . --retry-failed

# Sync with verbose output
batho sync --root . -v
```

## Configuration

Cloud sync requires environment variables to be set:

| Variable | Required | Description |
|----------|----------|-------------|
| `BATHO_CLOUD_SYNC_ENABLED` | Yes | Set to `true` to enable sync |
| `BATHO_CLOUD_ENDPOINT` | Yes | Cloud sync API endpoint URL |
| `BATHO_CLOUD_API_KEY` | Yes | API key for authentication |

## Artifact Types

| Type | Description |
|------|-------------|
| `snapshot` | Time Machine snapshots |
| `patch` | Incremental patch operations |
| `bsg` | BSG structured graph outputs |
| `metrics` | Indexing performance metrics |
| `context` | Generated context files |

## Use Cases

- **Backup**: Automatically sync snapshots to cloud storage
- **Cross-repo analysis**: Aggregate artifacts from multiple repositories
- **CI/CD**: Upload build artifacts for audit trail
- **Disaster recovery**: Maintain off-site backups of critical code intelligence
