---
sidebar_position: 8
title: "7. Interactive Dashboard"
description: "Web dashboard architecture, pages, and launch options"
---

# 7. Interactive Dashboard

## 7.1 Dashboard Architecture

The dashboard provides an interactive interface for code intelligence exploration:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e3f2fd', 'primaryTextColor': '#1565c0', 'primaryBorderColor': '#1976d2', 'lineColor': '#42a5f5', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Client["Browser"]
        UI[Vanilla JS UI]
        Viz[D3/Cytoscape Hypergraph]
    end

    subgraph Server["batho dashboard"]
        Static["Static File Server<br/>(.ctn/ artifacts)"]
        Computed["Computed Endpoints<br/>(diffs, search)"]
    end

    subgraph Data["Data Sources"]
        Index[.ctn/index.json]
        Graph[.ctn/<id>/graph.json]
        BSG[.ctn/<id>/bsg.json]
        Snapshots[.ctn/snapshots/]
    end

    UI --> Static
    UI --> Computed
    Static --> Data
    Computed --> Data

    style Client fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Server fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Data fill:#fff3e0,stroke:#f57c00,stroke-width:2px
```

**Figure 10: Dashboard Architecture** - Three-tier architecture showing browser client, server components, and data sources.

## 7.2 Dashboard Pages

| Page | Function | Data Source |
|------|----------|-------------|
| **Overview** | Repo stats, language breakdown | `index.json` |
| **Hypergraph** | 3-level drill-down: files → symbols → neighborhood | `graph.json` |
| **Files** | Hierarchical file browser with entity counts | `graph.json` |
| **File Viewer** | Syntax-highlighted source + entity sidebar | `graph.json` + raw files |
| **Relationships** | Filtered tables (imports, calls, extends) | `graph.json` |
| **Rules** | Loaded BSG rule plugins and metadata | `batho.yaml` + plugin registry |
| **Metrics** | Indexing performance, cache hit rates | `metrics.json` |
| **Snapshots** | Time Machine list with diff capabilities | `snapshots/` |
| **Search** | Full-text entity and file search | Computed endpoint |

## 7.3 Launch Options

```bash
# Default launch
batho dashboard --root .

# Custom port
batho dashboard --root . --port 3000

# External access
batho dashboard --root . --host 0.0.0.0

# Skip browser auto-open
batho dashboard --root . --no-browser
```

## 7.4 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl/Cmd + K` | Global search |
| `Ctrl/Cmd + D` | Toggle dark mode |
| `Ctrl/Cmd + 0` | Reset zoom (graph) |
| `Ctrl/Cmd + +` | Zoom in (graph) |
| `Ctrl/Cmd + -` | Zoom out (graph) |
| `G` | Toggle grid (graph) |
| `F` | Fit to screen (graph) |

## 7.5 Export Options

| Format | Command |
|--------|---------|
| PNG | Right-click graph → Export PNG |
| SVG | Right-click graph → Export SVG |
| JSON | `batho export --format json --root .` |
| CSV | `batho export --format csv --root .` |
