---
sidebar_position: 7
title: "6. Git Hooks Enterprise"
description: "Git client-side hook automation with YAML configuration"
---

# 6. Git Hooks Enterprise

## 6.1 Architecture

Batho's Git hooks provide automated quality gates and workflow enforcement:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
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

    style A fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style B fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style C fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style D fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style E fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style F fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    style G fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
```

**Figure 9: Git Hooks Architecture** - Flowchart showing how YAML-defined hooks map to Git hook scripts.

## 6.2 Hook Lifecycle

The hook lifecycle provides a consistent workflow for configuration and management:

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

## 6.4 Configuration Example

```yaml
# .batho/hooks.yaml
hooks:
  pre-commit:
    - name: "Check formatting"
      command: "ruff format --check ."
    - name: "Lint"
      command: "ruff check ."
    - name: "Type check"
      command: "mypy ."
  
  pre-push:
    - name: "Run tests"
      command: "pytest"
    - name: "Security scan"
      command: "bandit -r src/"
  
  post-checkout:
    - name: "Re-index"
      command: "batho index --root ."
```

## 6.5 Best Practices

1. **Fast pre-commit**: Keep pre-commit hooks under 2 seconds
2. **Cache dependencies**: Use cached virtual environments
3. **Parallel execution**: Run independent checks in parallel
4. **Fail fast**: Order checks by likelihood of failure
