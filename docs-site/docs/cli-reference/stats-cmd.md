---
sidebar_position: 13
title: "stats"
description: "Show current index metadata and health summary"
---

# `stats` Command

Display current index metadata, health summary, and repository statistics.

## Usage

```bash
batho stats --root /path/to/repo
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |

## Output

The `stats` command outputs a nested JSON object containing:

- **summary**: Flattened key metrics (loc_total, repo_size_bytes, compression_ratio, cache_hit_rate)
- **current**: Full index entry metadata including stats, metrics, timestamp, and outputs
- **all_indexes**: List of all known index IDs
- **interception_matrix**: BSG rule interception statistics (if available)

## Examples

```bash
# Show stats for current directory
batho stats --root .

# Show stats for specific repository
batho stats --root /path/to/project
```

## Output Format

```json
{
  "summary": {
    "loc_total": 45000,
    "repo_size_bytes": 2048000,
    "compression_ratio": 10.5,
    "cache_hit_rate": 0.94
  },
  "current": {
    "index_id": "batho_project_abc123_20260517T120000Z",
    "timestamp": "2026-05-17T12:00:00Z",
    "entity_count": 1250,
    "relationship_count": 3400,
    "stats": {
      "loc_total": 45000,
      "repo_size_bytes": 2048000
    },
    "metrics": {
      "compression_ratio": 10.5,
      "cache_hit_rate": 0.94
    },
    "outputs": ["graph.json", "bsg_compressed.json"]
  },
  "all_indexes": [
    "batho_project_abc123_20260517T120000Z"
  ],
  "interception_matrix": [
    {
      "name": "bsg_core",
      "interceptions": 42
    }
  ]
}
```

## Use Cases

- **Health checks**: Verify index is up-to-date before operations
- **Monitoring**: Track indexing performance over time
- **Debugging**: Identify why indexing might be slow
- **CI/CD**: Include stats in build reports for trend analysis
