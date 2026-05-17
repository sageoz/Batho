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

## 11.4 Operational Commands

```bash
# Health check
batho stats --root .

# Cache management
batho cache stats
batho cache invalidate "*.pyc"
batho cache clear

# Storage maintenance
batho storage verify --root . --repair
batho storage cleanup --root . --apply
batho storage compact --root . --apply
batho storage backfill --root .

# Registry rebuild
batho storage rebuild-indexes --root .
```
