---
sidebar_position: 1
title: "REST API"
description: "Artifact Bridge REST API endpoints"
---

# REST API

The Artifact Bridge exposes `.ctn/` artifacts via a REST API server.

## Starting the Server

```bash
batho bridge serve --root /path/to/repo
```

Default: `http://127.0.0.1:8766`

## Endpoints

All endpoints are mounted under `/api/v1/bridge/`.

### Indexes

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/indexes` | GET | List all indexes |
| `/indexes/{index_id}` | GET | Get specific index metadata |
| `/index-meta` | GET | Current index metadata |

### Artifacts

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/artifacts` | GET | List registered artifacts |
| `/artifacts/{artifact_type}` | GET | Retrieve artifacts by type |
| `/artifacts/{artifact_type}/content` | GET | Artifact content by path |

### Files & Stats

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/file-content` | GET | File content with BSG enrichment |
| `/stats` | GET | Registry statistics |

### Patches & Snapshots

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/patches` | GET | List patch operations |
| `/patches/{operation_id}` | GET | Patch operation detail |
| `/snapshots/diff` | GET | Diff two snapshots (base + new) |
