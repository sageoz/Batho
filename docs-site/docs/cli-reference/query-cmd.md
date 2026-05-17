---
sidebar_position: 10
title: "query"
description: "Query persisted entity and relationship indexes"
---

# `query` Command

Query persisted graph indexes.

## Usage

```bash
# Query by entity type
batho query --root /path/to/repo --entity-type function --limit 50

# Query by file path
batho query --root /path/to/repo --file-path src/api.py

# Query by relationship type (with index rebuild)
batho query --root /path/to/repo --relationship-type calls --rebuild-index
```

## Options

| Flag | Description |
|------|-------------|
| `--entity-type` | Filter by entity type (function, class, method, etc.) |
| `--file-path` | Filter by specific file path |
| `--relationship-type` | Filter by relationship type (imports, calls, uses, defines) |
| `--limit` | Maximum results to return |
| `--rebuild-index` | Rebuild query index before executing |
