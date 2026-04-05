# Cloud Sync Protocol for CTN Artifacts (v2 Foundation)

This document defines the cloud-sync contract for persistent `.ctn` artifacts. The current implementation in v1 stores all required metadata locally in the SQLite artifact registry so cloud synchronization can be added in v2 without changing existing file paths or CLI behavior.

## Goals

- Preserve strict backward compatibility for `.ctn` files and existing commands.
- Use deterministic artifact identity for dedupe and conflict detection.
- Keep local registry reconstructable from disk at any time.
- Support offline-first workflows and eventual cloud reconciliation.

## Artifact Identity

Each artifact is identified by:

- `artifact_id`: deterministic SHA-256 of `(artifact_type, logical_path, checksum, schema_version)`
- `content_id`: checksum-based immutable content identity
- `logical_path`: portable path relative to `.ctn`
- `physical_path`: absolute local filesystem path

This identity scheme enables stable dedupe across machines and storage backends.

## Registry Fields Relevant to Sync

The `artifacts` table persists:

- `artifact_id`
- `content_id`
- `artifact_type`
- `logical_path`
- `physical_path`
- `checksum`
- `schema_version`
- `run_id`
- `sync_status` (`pending`, `synced`, `conflict`, `local_only`)
- `cloud_content_id` (optional remote object reference)
- `last_sync_at` (UTC ISO timestamp)
- `deleted`

## Sync State Model

- `pending`: local artifact ready to be pushed.
- `synced`: local artifact confirmed on remote.
- `conflict`: checksum or identity mismatch detected.
- `local_only`: cloud sync disabled for this artifact/instance.

## Recommended v2 Sync Order

1. **Discover** pending artifacts from local registry.
2. **Upload content** by `content_id` (skip if remote already has it).
3. **Publish metadata** (`artifact_id`, logical mapping, schema version, timestamps).
4. **Mark synced** locally (`sync_status=synced`, `cloud_content_id`, `last_sync_at`).

## Conflict Detection

A conflict should be raised when any of these differ between local and remote for the same `artifact_id`:

- `checksum`
- `schema_version`
- `content_id`

On conflict:

- set `sync_status=conflict`
- retain local file and metadata
- require explicit reconciliation policy in v2 (prefer-local / prefer-remote / manual)

## Recovery and Rebuild Guarantees

- Registry can be rebuilt from disk using `batho storage backfill`.
- Drift can be detected/repaired using `batho storage verify --repair`.
- Retention cleanup remains policy-driven and dry-run capable.

## Compatibility Commitments

- No changes to existing `.ctn` output locations.
- No required changes to existing CLI consumers.
- Existing JSON/markdown artifacts remain readable in-place.
- Sync metadata augments persistence; it does not alter payload formats.
