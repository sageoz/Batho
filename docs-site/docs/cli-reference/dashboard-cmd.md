---
sidebar_position: 8
title: "dashboard"
description: "Launch the interactive web dashboard"
---

# `dashboard` Command

Interactive code intelligence visualization served directly from your `.ctn/` artifacts.

## Usage

```bash
# Launch the dashboard (auto-opens browser)
batho dashboard --root .

# Custom port / host
batho dashboard --root . --port 3000 --host 0.0.0.0

# Skip auto-open
batho dashboard --root . --no-browser

# Open to a specific route
batho dashboard --root . --open-route '#/hypergraph/files'
```

## Dashboard Pages

| Page | What it shows |
|------|--------------|
| **Overview** | Repo stats, language breakdown, file distribution |
| **Hypergraph** | Three-level drill-down: files → file symbols → node neighborhood |
| **Files** | Hierarchical file browser with entity counts |
| **File Viewer** | Syntax-highlighted source with BSG entity highlighting sidebar |
| **Relationships** | Filtered relationship tables (imports, calls, extends) |
| **Plugins** | Loaded BSG rule plugins and their metadata |
| **Metrics** | Indexing performance, cache hit rates, worker stats |
| **Snapshots** | Time Machine snapshot list with diff capabilities |
| **Search** | Full-text search across entities and files |
