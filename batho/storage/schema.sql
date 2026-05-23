-- ============================================================
-- Batho Unified Database Schema (v1.0)
-- Production-ready, enterprise-grade. 1 project = 1 .batho DB.
-- ============================================================

-- ============================================================
-- PRAGMAS (applied on every connection open via engine.py)
-- ============================================================
-- PRAGMA journal_mode = WAL;
-- PRAGMA synchronous = FULL;
-- PRAGMA foreign_keys = ON;
-- PRAGMA auto_vacuum = INCREMENTAL;
-- PRAGMA page_size = 8192;

-- ============================================================
-- 1. DATABASE METADATA
-- ============================================================

CREATE TABLE IF NOT EXISTS db_meta (
    key        TEXT PRIMARY KEY NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) WITHOUT ROWID;

-- ============================================================
-- 2. INDEX RUNS (replaces index.json)
-- ============================================================

CREATE TABLE IF NOT EXISTS index_runs (
    run_id         TEXT PRIMARY KEY NOT NULL,
    schema_version TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    completed_at   TEXT,
    status         TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    git_commit     TEXT,
    git_branch     TEXT,
    root_path      TEXT NOT NULL,
    entity_count   INTEGER NOT NULL DEFAULT 0,
    rel_count      INTEGER NOT NULL DEFAULT 0,
    file_count     INTEGER NOT NULL DEFAULT 0,
    duration_ms    INTEGER,
    config_hash    TEXT,
    error_message  TEXT
) WITHOUT ROWID;

-- ============================================================
-- 3. GRAPH ENTITIES (shredded — one row per entity)
-- ============================================================

CREATE TABLE IF NOT EXISTS graph_entities (
    run_id         TEXT    NOT NULL,
    entity_id      TEXT    NOT NULL,
    entity_type    TEXT    NOT NULL,
    name           TEXT    NOT NULL,
    file_path      TEXT    NOT NULL,
    start_line     INTEGER NOT NULL CHECK (start_line >= 0),
    end_line       INTEGER NOT NULL CHECK (end_line >= start_line),
    start_byte     INTEGER NOT NULL DEFAULT 0 CHECK (start_byte >= 0),
    end_byte       INTEGER NOT NULL DEFAULT 0 CHECK (end_byte >= start_byte),
    signature      TEXT,
    parent_id      TEXT,
    content_hash   TEXT    NOT NULL DEFAULT '',
    ast_node_type  TEXT,
    metadata_json  TEXT    NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, entity_id),
    FOREIGN KEY (run_id) REFERENCES index_runs(run_id) ON DELETE CASCADE
) WITHOUT ROWID;

-- ============================================================
-- 4. GRAPH RELATIONSHIPS (shredded — one row per edge)
-- ============================================================

CREATE TABLE IF NOT EXISTS graph_relationships (
    run_id            TEXT NOT NULL,
    relationship_id   TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    source_id         TEXT NOT NULL,
    target_id         TEXT NOT NULL,
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, relationship_id),
    FOREIGN KEY (run_id) REFERENCES index_runs(run_id) ON DELETE CASCADE
) WITHOUT ROWID;

-- ============================================================
-- 5. BSG ENTRIES (one row per file per run)
-- ============================================================

CREATE TABLE IF NOT EXISTS bsg_entries (
    run_id       TEXT    NOT NULL,
    file_path    TEXT    NOT NULL,
    view_type    TEXT    NOT NULL DEFAULT 'agent'
                 CHECK (view_type IN ('agent', 'storage', 'human')),
    bsg_json     TEXT    NOT NULL,
    token_count  INTEGER,
    node_count   INTEGER NOT NULL DEFAULT 0,
    checksum     TEXT    NOT NULL,
    PRIMARY KEY (run_id, file_path, view_type),
    FOREIGN KEY (run_id) REFERENCES index_runs(run_id) ON DELETE CASCADE
) WITHOUT ROWID;

-- ============================================================
-- 6. FILE TRACKING (incremental change detection)
-- ============================================================

CREATE TABLE IF NOT EXISTS file_tracking (
    file_path    TEXT    PRIMARY KEY NOT NULL,
    content_hash TEXT    NOT NULL,
    mtime        REAL    NOT NULL,
    size         INTEGER NOT NULL CHECK (size >= 0),
    is_indexed   INTEGER NOT NULL DEFAULT 0 CHECK (is_indexed IN (0, 1)),
    last_run_id  TEXT,
    updated_at   TEXT    NOT NULL
) WITHOUT ROWID;

-- ============================================================
-- 7. AST CACHE (parsed entity/relationship cache by content hash)
-- ============================================================

CREATE TABLE IF NOT EXISTS ast_cache (
    file_hash          TEXT    PRIMARY KEY NOT NULL,
    file_path          TEXT    NOT NULL,
    entities_json      TEXT    NOT NULL,
    relationships_json TEXT,
    mtime              REAL    NOT NULL,
    size               INTEGER NOT NULL CHECK (size >= 0),
    cached_at          TEXT    NOT NULL,
    ttl_days           INTEGER NOT NULL DEFAULT 30 CHECK (ttl_days > 0)
) WITHOUT ROWID;

-- ============================================================
-- 8. FILE SNAPSHOTS (reconstruction metadata)
-- ============================================================

CREATE TABLE IF NOT EXISTS file_snapshots (
    file_path             TEXT    PRIMARY KEY NOT NULL,
    file_hash             TEXT    NOT NULL,
    file_size             INTEGER NOT NULL CHECK (file_size >= 0),
    encoding              TEXT    NOT NULL DEFAULT 'utf-8',
    entity_ids_json       TEXT    NOT NULL DEFAULT '[]',
    gap_sections_json     TEXT    NOT NULL DEFAULT '[]',
    shebang               TEXT,
    encoding_declaration  TEXT,
    file_level_comments   TEXT    NOT NULL DEFAULT '[]',
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL
) WITHOUT ROWID;

-- ============================================================
-- 9. SNAPSHOTS (time machine — base snapshots)
-- ============================================================

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id    TEXT PRIMARY KEY NOT NULL,
    parent_id      TEXT,
    created_at     TEXT NOT NULL,
    label          TEXT NOT NULL DEFAULT '',
    git_commit     TEXT,
    git_branch     TEXT,
    root_path      TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    stats_json     TEXT NOT NULL DEFAULT '{}',
    checksum       TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES snapshots(snapshot_id)
) WITHOUT ROWID;

-- ============================================================
-- 10. SNAPSHOT PATCHES (RFC 6902 JSON Patch diffs)
-- ============================================================

CREATE TABLE IF NOT EXISTS snapshot_patches (
    patch_id        TEXT PRIMARY KEY NOT NULL,
    base_snapshot   TEXT NOT NULL,
    target_snapshot TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    patch_format    TEXT NOT NULL DEFAULT 'rfc6902'
                    CHECK (patch_format IN ('rfc6902', 'custom_diff')),
    operations      TEXT NOT NULL,
    op_count        INTEGER NOT NULL DEFAULT 0,
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    checksum        TEXT NOT NULL,
    FOREIGN KEY (base_snapshot) REFERENCES snapshots(snapshot_id),
    FOREIGN KEY (target_snapshot) REFERENCES snapshots(snapshot_id)
) WITHOUT ROWID;

-- ============================================================
-- 11. PATCH OPERATIONS (time machine — incremental file patches)
-- ============================================================

CREATE TABLE IF NOT EXISTS patch_operations (
    operation_id     TEXT PRIMARY KEY NOT NULL,
    base_snapshot_id TEXT,
    new_snapshot_id  TEXT,
    operation_type   TEXT NOT NULL
                     CHECK (operation_type IN ('incremental_patch', 'diff_patch', 'cherry_pick', 'full_reindex')),
    timestamp        TEXT NOT NULL,
    changes_json     TEXT NOT NULL,
    change_count     INTEGER NOT NULL DEFAULT 0,
    checksum         TEXT NOT NULL,
    metrics_json     TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (base_snapshot_id) REFERENCES snapshots(snapshot_id),
    FOREIGN KEY (new_snapshot_id) REFERENCES snapshots(snapshot_id)
) WITHOUT ROWID;

-- ============================================================
-- 12. CONTEXT OUTPUTS (generated markdown/text context documents)
-- ============================================================

CREATE TABLE IF NOT EXISTS context_outputs (
    run_id       TEXT NOT NULL,
    output_type  TEXT NOT NULL,
    content      TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    produced_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, output_type),
    FOREIGN KEY (run_id) REFERENCES index_runs(run_id) ON DELETE CASCADE
) WITHOUT ROWID;

-- ============================================================
-- 13. ARTIFACT REGISTRY (cloud sync metadata & artifact tracking)
-- ============================================================

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id      TEXT    PRIMARY KEY NOT NULL,
    content_id       TEXT,
    artifact_type    TEXT    NOT NULL,
    logical_path     TEXT    NOT NULL,
    checksum         TEXT,
    size_bytes       INTEGER NOT NULL CHECK (size_bytes >= 0),
    schema_version   TEXT    NOT NULL,
    producer         TEXT    NOT NULL,
    run_id           TEXT,
    sync_status      TEXT    NOT NULL DEFAULT 'local_only'
                     CHECK (sync_status IN ('pending', 'synced', 'failed', 'conflict', 'local_only')),
    cloud_content_id TEXT,
    last_sync_at     TEXT,
    sync_error       TEXT,
    retry_count      INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    retention_class  TEXT    NOT NULL DEFAULT 'default',
    metadata_json    TEXT    NOT NULL DEFAULT '{}',
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    deleted          INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1))
) WITHOUT ROWID;

-- ============================================================
-- 14. INDEXES
-- ============================================================

-- === Graph Entity Indexes ===
CREATE INDEX IF NOT EXISTS idx_entities_by_file
    ON graph_entities(run_id, file_path);

CREATE INDEX IF NOT EXISTS idx_entities_by_type_name
    ON graph_entities(run_id, entity_type, name);

CREATE INDEX IF NOT EXISTS idx_entities_by_parent
    ON graph_entities(run_id, parent_id)
    WHERE parent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entities_by_line
    ON graph_entities(run_id, file_path, start_line, end_line);

-- === Graph Relationship Indexes ===
CREATE INDEX IF NOT EXISTS idx_rels_by_source
    ON graph_relationships(run_id, source_id);

CREATE INDEX IF NOT EXISTS idx_rels_by_target
    ON graph_relationships(run_id, target_id);

CREATE INDEX IF NOT EXISTS idx_rels_by_type
    ON graph_relationships(run_id, relationship_type);

-- === File Tracking Indexes ===
CREATE INDEX IF NOT EXISTS idx_file_tracking_hash
    ON file_tracking(content_hash);

CREATE INDEX IF NOT EXISTS idx_file_tracking_unindexed
    ON file_tracking(is_indexed)
    WHERE is_indexed = 0;

-- === AST Cache Indexes ===
CREATE INDEX IF NOT EXISTS idx_ast_cache_path
    ON ast_cache(file_path);

CREATE INDEX IF NOT EXISTS idx_ast_cache_expiry
    ON ast_cache(cached_at);

-- === BSG Entry Indexes ===
CREATE INDEX IF NOT EXISTS idx_bsg_by_file
    ON bsg_entries(run_id, file_path);

-- === Snapshot Indexes ===
CREATE INDEX IF NOT EXISTS idx_snapshots_created
    ON snapshots(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_snapshots_parent
    ON snapshots(parent_id)
    WHERE parent_id IS NOT NULL;

-- === Artifact Registry Indexes ===
CREATE INDEX IF NOT EXISTS idx_artifacts_sync_pending
    ON artifacts(sync_status, updated_at DESC)
    WHERE deleted = 0 AND sync_status = 'pending';

CREATE INDEX IF NOT EXISTS idx_artifacts_by_type
    ON artifacts(artifact_type, updated_at DESC)
    WHERE deleted = 0;

CREATE INDEX IF NOT EXISTS idx_artifacts_retention
    ON artifacts(retention_class, created_at)
    WHERE deleted = 0;

-- === Index Run Indexes ===
CREATE INDEX IF NOT EXISTS idx_runs_latest
    ON index_runs(status, completed_at DESC)
    WHERE status = 'completed';
