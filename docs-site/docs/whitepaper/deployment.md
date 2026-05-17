---
sidebar_position: 12
title: "11. Deployment & Operations"
description: "Installation, configuration, CI/CD integration, and operational commands"
---

# 11. Deployment & Operations

## 11.1 Installation

```bash
# Via uv (recommended)
uv add batho

# Via pip
pip install batho

# From source
uv sync
uv run pytest
```

## 11.2 Configuration

Minimal `batho.yaml`:

```yaml
batho_version: "1.0"

indexer:
  max_file_size_kb: 500
  max_workers: 0  # auto
  metrics_output: ".ctn/local/metrics/metrics.json"

logging:
  level: INFO
  json_format: false

rules:
  enabled: true
  auto_load_all_plugins: true
  builtin_plugins:
    - bsg_core
    - bsg_silent_failure_catcher
    - bsg_dependency_blast_radius

storage:
  retention:
    snapshot_days: 90
    patch_days: 90
    max_snapshots: 500
    max_patches: 5000
```

## 11.3 CI/CD Integration

| Platform | Integration | File |
|----------|-------------|------|
| GitHub Actions | Workflow template | `.github/workflows/batho.yml` |
| GitLab CI | Pipeline template | `.gitlab-ci.yml` |
| Pre-commit | Hook stages | `.pre-commit-config.yaml` |

### GitHub Actions Example

```yaml
# .github/workflows/batho.yml
name: Batho Analysis
on: [push, pull_request]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install batho
      - run: batho index --root . --snapshot
      - run: batho stats --root .
```

## 11.4 Operational Commands

### Health Check

```bash
batho stats --root .
```

### Cache Management

```bash
batho cache stats
batho cache invalidate "*.pyc"
batho cache clear
```

### Storage Maintenance

```bash
batho storage verify --root . --repair
batho storage cleanup --root . --apply
batho storage compact --root . --apply
batho storage backfill --root .
```

### Registry Rebuild

```bash
batho storage rebuild-indexes --root .
```

## 11.5 Monitoring

### Metrics Endpoint

```bash
curl http://localhost:8080/stats
```

### Health Check Script

```bash
#!/bin/bash
batho stats --root . > /dev/null 2>&1
if [ $? -eq 0 ]; then
  echo "healthy"
else
  echo "unhealthy"
fi
```

## 11.6 Backup Strategy

| Component | Backup Frequency | Retention |
|-----------|------------------|-----------|
| Snapshots | Daily | 90 days |
| Cache | Weekly | 30 days |
| Config | On change | Indefinite |
