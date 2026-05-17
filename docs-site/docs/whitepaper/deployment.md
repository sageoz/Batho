---
sidebar_position: 12
title: "11. Deployment & Operations"
description: "Installation, configuration, CI/CD integration, and operational commands"
---

# 11. Deployment & Operations

## 11.1 Deployment Architecture

Batho is designed for flexible deployment across local development, CI/CD pipelines, and long-running server environments. The following architecture diagram illustrates the recommended production topology:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Dev["Developer Workstation"]
        CODE["Source Code<br/>(Git Working Tree)"]
        BATHO["batho CLI<br/>(Local Analysis)"]
        DASH["Dashboard<br/>(127.0.0.1:8080)"]
    end

    subgraph CI["CI/CD Pipeline"]
        GH["GitHub Actions / GitLab CI"]
        JOB1["batho index --snapshot"]
        JOB2["batho hooks run --hook pre-commit"]
        JOB3["batho stats --json"]
        ART["Artifacts<br/>(snapshots and metrics)"]
    end

    subgraph Server["Server / Long-running"]
        BRIDGE["batho bridge serve<br/>(REST and MCP)"]
        SYNC["Cloud Sync<br/>(Explicit opt-in)"]
        MON["Prometheus / Grafana<br/>(Metrics scrape)"]
    end

    subgraph Store["Persistent Storage"]
        SNAP["Snapshots<br/>(.ctn/snapshots/)"]
        CACHE["AST Cache<br/>(SQLite .db)"]
        AUDIT["Audit Logs<br/>(.ctn/local/audit/)"]
    end

    CODE --> BATHO
    BATHO --> DASH
    BATHO -->|"Write"| Store
    GH --> JOB1
    GH --> JOB2
    GH --> JOB3
    JOB1 --> ART
    JOB2 --> ART
    JOB3 --> ART
    ART -->|"Upload"| Store
    BRIDGE -->|"Read-only"| Store
    BRIDGE -->|"Serve"| MON
    BRIDGE -->|"Sync (opt-in)"| SYNC

    style Dev fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style CI fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Server fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Store fill:#fce4ec,stroke:#c2185b,stroke-width:2px
```

**Figure 21: Deployment Architecture** - Recommended production topology showing deployment modes across development, CI/CD, server, and storage layers.

### Deployment Modes

| Mode | Use Case | Network | Storage |
|------|----------|---------|---------|
| **Local CLI** | Developer analysis, ad-hoc queries | None | Local `.ctn/` |
| **CI/CD Agent** | Automated indexing on PR/push | None | Ephemeral + artifact upload |
| **Server (Bridge)** | Team dashboard, IDE integration | Localhost or TLS | Local `.ctn/` |
| **Cloud Sync** | Cross-repo artifact aggregation | Explicit outbound | Remote registry |

---

## 11.2 Installation

```bash
# Via uv (recommended)
uv add batho

# Via pip
pip install batho

# From source
uv sync
uv run pytest
```

---

## 11.3 Configuration

### Configuration Loading Flow

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart LR
    A["Start"] --> B{"Config File Found?"}
    B -->|batho.yaml| C["Parse YAML"]
    B -->|None| D["Use Defaults"]
    C --> E["JSON-Schema Validation"]
    E -->|Valid| F["Merge with Defaults"]
    E -->|Invalid| G["Fatal Error<br/>(E100)"]
    D --> F
    F --> H["Apply CLI Overrides"]
    H --> I["Runtime Config"]
    I --> J["Initialize Subsystems"]

    style A fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style B fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style C fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style E fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style F fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style I fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style G fill:#ffebee,stroke:#c62828,stroke-width:2px
```

**Figure 22: Configuration Loading Flow** - Flowchart showing the configuration loading and validation process with JSON-Schema validation.

### Minimal `batho.yaml`

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

---

## 11.4 CI/CD Integration

### CI/CD Pipeline Flow

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
sequenceDiagram
    actor Dev as Developer
    participant Git as GitHub/GitLab
    participant CI as CI Runner
    participant Batho as batho CLI
    participant Cache as Artifact Cache
    participant Store as Snapshot Store

    Dev->>Git: Push / Pull Request
    Git->>CI: Trigger pipeline
    CI->>Batho: Install batho
    CI->>Batho: batho index --root . --snapshot
    Batho->>Store: Write snapshot
    Batho->>Cache: Cache AST entities
    CI->>Batho: batho hooks run --hook pre-commit
    Batho->>CI: Quality gate result
    CI->>Batho: batho stats --root . --json
    Batho->>CI: Metrics JSON
    CI->>Git: Report status + metrics
```

**Figure 23: CI/CD Pipeline Flow** - Sequence diagram showing Batho integration in CI/CD pipelines for automated analysis and quality gates.

### Platform Integration Matrix

| Platform | Integration | File | Trigger |
|----------|-------------|------|---------|
| GitHub Actions | Workflow template | `.github/workflows/batho.yml` | `push`, `pull_request` |
| GitLab CI | Pipeline template | `.gitlab-ci.yml` | `merge_request`, `push` |
| Pre-commit | Hook stages | `.pre-commit-config.yaml` | `git commit` |
| Jenkins | Pipeline step | `Jenkinsfile` | Webhook |

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

---

## 11.5 Operational Commands

### Command Taxonomy

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Index["Indexing"]
        IDX["batho index<br/>--root . --snapshot"]
    end

    subgraph Query["Query and Analysis"]
        STATS["batho stats<br/>--root ."]
        DASH_CMD["batho dashboard<br/>--root ."]
        BRIDGE_CMD["batho bridge serve<br/>--root ."]
    end

    subgraph Maintenance["Maintenance"]
        CACHE_CMD["batho cache<br/>stats / invalidate / clear"]
        STORE_CMD["batho storage<br/>verify / cleanup / compact / backfill"]
        REBUILD["batho storage<br/>rebuild-indexes"]
    end

    subgraph Hooks["Governance"]
        HOOK_INSTALL["batho hooks install"]
        HOOK_RUN["batho hooks run<br/>--hook pre-commit"]
    end

    IDX --> STATS
    IDX --> CACHE_CMD
    STATS --> DASH_CMD
    STATS --> BRIDGE_CMD
    CACHE_CMD --> STORE_CMD
    STORE_CMD --> REBUILD
    IDX --> HOOK_RUN
    HOOK_INSTALL --> HOOK_RUN

    style Index fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Query fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Maintenance fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Hooks fill:#fce4ec,stroke:#c2185b,stroke-width:2px
```

**Figure 24: Command Taxonomy** - Flowchart showing the hierarchical organization of Batho CLI commands across functional categories.

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

---

## 11.6 Monitoring & Observability

### Monitoring Stack

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart LR
    subgraph Batho["Batho Server"]
        BRIDGE["bridge serve<br/>(/stats endpoint)"]
        METRICS["Metrics Emitter<br/>(JSON / Prometheus)"]
    end

    subgraph Observability["Observability Stack"]
        PROM["Prometheus<br/>(Scrape /stats)"]
        GRAF["Grafana<br/>(Dashboards)"]
        ALERT["Alertmanager<br/>(Threshold alerts)"]
    end

    subgraph Alerts["Alert Channels"]
        SLACK["Slack"]
        PAGER["PagerDuty"]
        EMAIL["Email"]
    end

    BRIDGE --> METRICS
    METRICS -->|"HTTP GET /stats"| PROM
    PROM --> GRAF
    PROM --> ALERT
    ALERT --> SLACK
    ALERT --> PAGER
    ALERT --> EMAIL

    style Batho fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Observability fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Alerts fill:#fff3e0,stroke:#f57c00,stroke-width:2px
```

**Figure 25: Monitoring Stack** - Flowchart showing the metrics collection pipeline from Batho server to observability tools and alert channels.

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

### Key Operational Metrics

| Metric | Type | Threshold | Action |
|--------|------|-----------|--------|
| `index_duration_seconds` | Histogram | > 300s | Alert: slow indexing |
| `cache_hit_rate` | Gauge | < 90% | Alert: cache warming needed |
| `snapshot_count` | Gauge | > 450 | Alert: cleanup required |
| `error_rate` | Counter | > 1% | Alert: investigate logs |
| `api_request_latency` | Histogram | > 500ms | Alert: scale bridge |

---

## 11.7 Backup & Disaster Recovery

### Backup Flow

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Source["Batho Data"]
        SNAP["Snapshots<br/>(.ctn/snapshots/)"]
        CACHE["AST Cache<br/>(.ctn/local/cache/)"]
        CFG["batho.yaml<br/>(Config)"]
    end

    subgraph Backup["Backup Process"]
        SCHED["Cron / Scheduler<br/>(Daily 02:00 UTC)"]
        TAR["Tar + Gzip<br/>Archive"]
        HASH["Compute SHA-256<br/>Checksum"]
    end

    subgraph Dest["Storage Targets"]
        LOCAL["Local Backup<br/>(/backup/batho/)"]
        S3["S3-Compatible<br/>(Object Storage)"]
        GIT["Git LFS<br/>(Config-only)"]
    end

    SNAP --> TAR
    CACHE --> TAR
    CFG --> GIT
    SCHED --> TAR
    TAR --> HASH
    HASH --> LOCAL
    HASH --> S3

    style Source fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Backup fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Dest fill:#fff3e0,stroke:#f57c00,stroke-width:2px
```

**Figure 26: Backup Flow** - Flowchart showing the automated backup process for snapshots, cache, and configuration to multiple storage targets.

### Backup Strategy

| Component | Backup Frequency | Retention | Method |
|-----------|------------------|-----------|--------|
| Snapshots | Daily | 90 days | `tar czf` + upload |
| Cache | Weekly | 30 days | `sqlite3 .backup` |
| Config | On change | Indefinite | Git commit |
| Audit Logs | Daily | 1 year | `logrotate` + compress |

### Recovery Procedures

```bash
# Restore from backup archive
tar xzf batho-backup-2026-05-17.tar.gz -C /path/to/restore
batho storage verify --root . --repair

# Rebuild indexes after restore
batho storage rebuild-indexes --root .
batho storage backfill --root .
```

---

## 11.8 Scaling Guidelines

### Resource Requirements by Repository Size

| Repository Size | RAM | Disk | Workers | Index Time |
|---------------|-----|------|---------|------------|
| < 10K files | 512 MB | 100 MB | 2 | < 30s |
| 10K–50K files | 2 GB | 500 MB | 4 | < 3 min |
| 50K–100K files | 4 GB | 1 GB | 8 | < 10 min |
| 100K–200K files | 8 GB | 2 GB | 16 | < 30 min |

### Horizontal Scaling for Monorepos

For repositories approaching the 200K file limit, use repository sharding:

```yaml
# batho.yaml — monorepo shard config
indexer:
  max_workers: 16
  include:
    - "services/auth/**"
    - "services/billing/**"
  exclude:
    - "vendor/**"
    - "node_modules/**"
    - "*.min.js"

storage:
  retention:
    snapshot_days: 30   # Shorter for large repos
    max_snapshots: 100
```
