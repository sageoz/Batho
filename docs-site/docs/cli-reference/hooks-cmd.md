---
sidebar_position: 6
title: "hooks"
description: "Git client-side hook management"
---

# `hooks` Command

YAML-driven Git client-side hook automation with enterprise reliability.

## Usage

```bash
# List configured hooks and templates
batho hooks list --root /path/to/repo

# Check installation status
batho hooks status --hook pre-commit

# Install all enabled hooks (auto-bootstraps .batho/hooks.yaml if missing)
batho hooks install --all

# Install specific hook with force (overwrites unmanaged)
batho hooks install --hook pre-commit --force

# Remove managed hooks
batho hooks remove --all

# Run hook manually (supports custom hooks for CI/CD)
batho hooks run --hook enterprise-nightly --verbose
```

## Configuration in `.batho/hooks.yaml`

```yaml
version: hooks.v1
defaults:
  shell: /bin/sh
  timeout: 60
hooks:
  pre-commit:
    enabled: true
    stages:
      - run: ruff check .
      - run: pytest --co -q
  pre-push:
    enabled: true
    stages:
      - run: pytest -x --tb=short
```

Enable in `batho.yaml`:

```yaml
hooks:
  enabled: true
  include: true
```
