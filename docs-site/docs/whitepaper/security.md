---
sidebar_position: 10
title: "9. Security & Governance"
description: "Zero-code-execution guarantee, BSG interceptors, and audit logging"
---

# 9. Security & Governance

## 9.1 Zero-Code-Execution Guarantee

Batho operates entirely via static analysis, ensuring safe operation on untrusted codebases:

| Input | Processing | Guarantee |
|-------|------------|-----------|
| Source files | tree-sitter parse only | No execution |
| Config files | YAML/JSON parse | Schema validated |
| Hook scripts | Shell command delegation | User-defined, auditable |

### Security Boundaries

- **Parsing**: No code execution, only syntax tree construction
- **Caching**: SQLite database with parameterized queries
- **Networking**: Explicit opt-in, no outbound connections by default
- **Storage**: Local filesystem only, no cloud access

## 9.2 BSG Interceptor Plugins

Security-focused plugins that run during graph construction:

| Plugin | Detects | Action |
|--------|---------|--------|
| `bsg_hardcoded_secret_catcher` | API keys, tokens in literals | Tag entity + log warning |
| `bsg_auth_boundary_shield` | Missing auth on API routes | Tag risk boundary |
| `bsg_silent_failure_catcher` | Bare except, swallowed errors | Tag reliability risk |
| `bsg_dependency_blast_radius` | High fan-out modules | Tag architectural risk |

### Plugin Output Example

```json
{
  "entity_id": "DatabaseConfig.password",
  "tags": ["security", "secret-exposure"],
  "severity": "high",
  "message": "Hardcoded secret detected"
}
```

## 9.3 Audit Logging

All patch operations are audited with comprehensive logging:

| Event | Fields |
|-------|--------|
| `patch_operation_start` | base_snapshot_id, change_count |
| `patch_progress` | processed, total, progress_pct |
| `incremental_patch_complete` | new_snapshot_id, elapsed_seconds |
| `audit_complete` | operation_id, success, metadata |

### Audit Log Location

```
.ctn/local/audit/
├── operations.log
├── security_events.log
└── integrity.log
```

## 9.4 Compliance Features

| Feature | Description |
|---------|-------------|
| **Immutable Snapshots** | Snapshots cannot be modified after creation |
| **Chain of Custody** | Patch chain tracks all modifications |
| **Integrity Verification** | SHA-256 checksums on all artifacts |
| **Access Logging** | All API/dashboard access is logged |
| **Retention Policies** | Configurable artifact retention periods |
