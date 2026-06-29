---
sidebar_position: 13
title: "12. Deployment & Operations"
description: "Installation, configuration, CI/CD integration, and operational commands"
---

# 12. Deployment & Operations

## 12.1 Deployment Architecture

Batho is designed for flexible deployment across local developer workstations and automated CI/CD pipelines. The following architecture diagram illustrates the production topology:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Dev["Developer Workstation"]
        CODE["Source Code<br/>(Git Working Tree)"]
        BATHO["batho CLI<br/>(Local Analysis)"]
    end

    subgraph CI["CI/CD Pipeline"]
        GH["GitHub Actions / GitLab CI"]
        JOB1["batho build"]
        JOB2["batho export"]
    end

    subgraph Store["Persistent Storage"]
        DB["Artifact Database<br/>(.batho/artifact/)"]
        CACHE["AST Cache<br/>(.batho/cache/)"]
    end

    CODE --> BATHO
    BATHO -->|"Write"| Store
    GH --> JOB1
    JOB1 --> JOB2
    JOB2 -->|"Upload ZIP"| Store

    style Dev fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style CI fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Store fill:#fce4ec,stroke:#c2185b,stroke-width:2px
```

**Figure 18: Deployment Architecture** - Recommended topology showing deployment modes across development, CI/CD, and storage layers.

### Deployment Modes

- **Local CLI**: Runs directly on the developer's machine to build indexes (`batho build`), perform patches (`batho patch`), or run queries. All database state is stored locally inside `.batho/`.
- **CI/CD Pipeline**: Runs as a static code analysis job in CI. It builds a database artifact from scratch or from a cached copy, evaluates rules, and uploads the `.batho` database package for downstream consumers.

---

## 12.2 Installation

Install the `batho` package directly from PyPI.

```bash
# Via uv (recommended for speed)
uv add batho

# Via pip
pip install batho
```

---

## 12.3 Configuration Loading Flow

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

**Figure 19: Configuration Loading Flow** - Flowchart showing the configuration loading and validation process with JSON-Schema validation.

---

## 12.4 CI/CD Integration

Integrate Batho into CI pipelines to automate graph generation and rule verification.

### CI/CD Pipeline Flow

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
sequenceDiagram
    actor Dev as Developer
    participant Git as GitHub/GitLab
    participant CI as CI Runner
    participant Batho as batho CLI
    participant Store as Artifact Storage

    Dev->>Git: Push / Pull Request
    Git->>CI: Trigger pipeline
    CI->>Batho: Install batho
    CI->>Batho: batho build --root .
    Batho->>Batho: Execute rule checks & build graph
    CI->>Batho: batho export --root . --json --view agent --output export.json
    CI->>Batho: batho export --root . --output artifact.batho
    Batho->>Store: Upload export.json & artifact.batho
    CI->>Git: Report build status
```

**Figure 20: CI/CD Pipeline Flow** - Sequence diagram showing Batho integration in CI/CD pipelines for automated analysis.

### GitHub Actions Template

Create `.github/workflows/batho.yml` in your repository:

```yaml
name: Batho Analysis
on: [push, pull_request]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install Batho
        run: pip install batho
      - name: Run Build
        run: batho build --root .
      - name: Export Code Intelligence
        run: batho export --root . --json --view agent --output bsg_agent.json
      - name: Pack Artifact Database
        run: batho export --root . --output artifact.batho
      - name: Archive Code Intelligence
        uses: actions/upload-artifact@v4
        with:
          name: batho-artifacts
          path: |
            bsg_agent.json
            artifact.batho
```

---

## 12.5 Operational Command Taxonomy

Batho's command suite is divided into three functional categories:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Analysis["Analysis & Mutation"]
        BUILD["batho build"]
        PATCH["batho patch"]
    end

    subgraph Governance["Governance & Downstream"]
        EXPORT["batho export"]
        DIFF["batho diff"]
    end

    subgraph Maintenance["Maintenance"]
        FIX["batho fix"]
        GC["batho gc"]
        LOAD["batho load"]
    end

    BUILD --> PATCH
    PATCH --> EXPORT
    EXPORT --> DIFF
    DIFF --> FIX
    FIX --> GC
    GC --> LOAD

    style Analysis fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Governance fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Maintenance fill:#fff3e0,stroke:#f57c00,stroke-width:2px
```

**Figure 21: Command Taxonomy** - Flowchart showing the categories of Batho CLI commands.

### Key Maintenance Tasks

#### Database Health Diagnostics
```bash
batho fix --dry-run
```

#### Sweep Stale Runs
```bash
batho gc runs --older-than 30
```

#### Bundle Vacuum
```bash
batho gc vacuum
```
