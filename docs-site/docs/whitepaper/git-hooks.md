---
sidebar_position: 7
title: "6. Git Hooks Enterprise"
description: "Git client-side hook automation with YAML configuration"
---

# 6. Git Hooks Enterprise

## 6.1 Architecture

```mermaid
flowchart LR
    A[.batho/hooks.yaml] --> B{Hook Type}
    B -->|pre-commit| C[Lint / Format / Type-check]
    B -->|pre-push| D[Test / Security Scan]
    B -->|post-checkout| E[Re-index if needed]
    B -->|custom| F[User-defined pipeline]
    C --> G[.git/hooks/]
    D --> G
    E --> G
    F --> G
```

## 6.2 Hook Lifecycle

| Stage | Command | Action |
|-------|---------|--------|
| Define | Edit `.batho/hooks.yaml` | Configure stages and commands |
| Plan | `batho hooks list` | Show supported + configured hooks |
| Install | `batho hooks install --all` | Generate scripts in `.git/hooks/` |
| Execute | Git trigger or `batho hooks run --hook NAME` | Run stage pipeline |
| Remove | `batho hooks remove --all` | Clean managed scripts |

## 6.3 Supported Git Hooks

All standard Git client-side hooks are supported:

| Hook | Typical Use Case |
|------|----------------|
| `applypatch-msg` | Patch message validation |
| `pre-commit` | Lint, format, type-check |
| `prepare-commit-msg` | Auto-generate commit messages |
| `commit-msg` | Commit message policy enforcement |
| `post-commit` | Notifications, metrics |
| `pre-rebase` | Prevent dangerous rebases |
| `post-checkout` | Environment reset, re-index |
| `post-merge` | Dependency updates |
| `pre-push` | Test suite, security scans |
| `pre-receive` | Server-side validation stub |
| `update` | Branch-specific policies |
| `post-update` | Deploy triggers |
