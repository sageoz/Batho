-- ============================================================
-- Batho Unified Database Schema (v2.0)
-- Compressed blob storage with global dictionary encoding.
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA auto_vacuum = INCREMENTAL;
PRAGMA page_size = 8192;

-- 1. METADATA
CREATE TABLE IF NOT EXISTS db_meta (
    key        TEXT PRIMARY KEY NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) WITHOUT ROWID;

-- 2. DICTIONARY ENCODING
-- Deduplicates paths, entity types, AST node types globally.
CREATE TABLE IF NOT EXISTS string_dict (
    id  INTEGER PRIMARY KEY AUTOINCREMENT,
    val TEXT UNIQUE NOT NULL
);

-- 3. INDEX RUNS
CREATE TABLE IF NOT EXISTS index_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid       TEXT UNIQUE NOT NULL,
    schema_version TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    completed_at   TEXT,
    status         TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    git_commit     TEXT,
    git_branch     TEXT,
    root_path_id   INTEGER NOT NULL REFERENCES string_dict(id),
    entity_count   INTEGER NOT NULL DEFAULT 0,
    rel_count      INTEGER NOT NULL DEFAULT 0,
    file_count     INTEGER NOT NULL DEFAULT 0,
    duration_ms    INTEGER,
    error_message  TEXT
);

-- 4. THE GRAPH PAYLOAD (Compressed Blobs)
CREATE TABLE IF NOT EXISTS file_artifacts (
    run_id             INTEGER NOT NULL REFERENCES index_runs(id) ON DELETE CASCADE,
    file_id            INTEGER NOT NULL REFERENCES string_dict(id),
    bsg_agent_view     BLOB,  -- zstd-compressed: lightweight structural nodes
    bsg_storage_view   BLOB,  -- zstd-compressed: delta (raw_content, syntax_glue)
    bsg_rel_view       BLOB,  -- zstd-compressed: relationships array
    content_hash       TEXT NOT NULL,
    PRIMARY KEY (run_id, file_id)
) WITHOUT ROWID;

-- 5. FILE TRACKING (Minimal change detection)
CREATE TABLE IF NOT EXISTS file_tracking (
    file_id      INTEGER PRIMARY KEY REFERENCES string_dict(id),
    content_hash TEXT NOT NULL,
    mtime        REAL NOT NULL,
    mtime_ns     INTEGER,
    inode        INTEGER,
    size         INTEGER NOT NULL CHECK (size >= 0),
    is_indexed   INTEGER NOT NULL DEFAULT 0 CHECK (is_indexed IN (0, 1)),
    last_run_id  TEXT,
    updated_at   TEXT NOT NULL,
    encoding     TEXT DEFAULT 'utf-8'
);

-- 6. RUN ARTIFACTS (Enterprise Metrics & Context)
-- Strict 1:1 mapping with index_runs. Replaces external side-files.
-- All metrics stored as zstd-compressed JSON BLOBs.
CREATE TABLE IF NOT EXISTS run_artifacts (
    run_id               INTEGER PRIMARY KEY REFERENCES index_runs(id) ON DELETE CASCADE,
    context_overview     BLOB,   -- zstd JSON: langs, file categories, entity distribution
    telemetry_metrics    BLOB,   -- zstd JSON: duration phases, cache stats, file/entity counts
    structural_metrics   BLOB,   -- zstd JSON: entity type dist, fan-in/fan-out, LOC
    security_audit       BLOB,   -- zstd JSON: BSG interceptor hits (NULL until wired)
    artifact_payload     BLOB,   -- zstd JSON: pre-minified entity+rel summary for LLM injection
    delta_stats          BLOB,   -- zstd JSON: churn/node diffs (NULL for build runs)
    schema_version       TEXT NOT NULL DEFAULT 'run-artifacts.v1',
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) WITHOUT ROWID;

-- 7. QUERY ENTITIES (SQLite-index-first search)
CREATE TABLE IF NOT EXISTS query_entities (
    entity_id       TEXT NOT NULL,
    run_id          INTEGER NOT NULL REFERENCES index_runs(id) ON DELETE CASCADE,
    entity_name     TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    fqn             TEXT,
    file_path       TEXT NOT NULL,
    line_number     INTEGER NOT NULL,
    signature       TEXT,
    is_exported     INTEGER DEFAULT 0,
    PRIMARY KEY (entity_id, run_id)
) WITHOUT ROWID;

-- Indexes for fast search
CREATE INDEX IF NOT EXISTS idx_entities_name ON query_entities(entity_name);
CREATE INDEX IF NOT EXISTS idx_entities_name_prefix ON query_entities(entity_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_entities_type ON query_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_fqn ON query_entities(fqn);
CREATE INDEX IF NOT EXISTS idx_entities_run ON query_entities(run_id);

-- 7.2 QUERY RELATIONSHIPS (Relational edges)
CREATE TABLE IF NOT EXISTS query_relationships (
    source_id       TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    relation_type   TEXT NOT NULL,
    run_id          INTEGER NOT NULL REFERENCES index_runs(id) ON DELETE CASCADE,
    metadata_json   TEXT DEFAULT '{}',
    PRIMARY KEY (source_id, target_id, relation_type, run_id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_relationships_source ON query_relationships(source_id, run_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON query_relationships(target_id, run_id);

-- 7.3 DANGLING REFERENCES (Temporary storage for unresolved edges during parsing)
CREATE TABLE IF NOT EXISTS dangling_references (
    source_id               TEXT NOT NULL,
    unresolved_target_name  TEXT NOT NULL,
    relation_type           TEXT NOT NULL,
    run_id                  INTEGER NOT NULL REFERENCES index_runs(id) ON DELETE CASCADE
);


-- Indexes
CREATE INDEX IF NOT EXISTS idx_dangling_run_name
    ON dangling_references(run_id, unresolved_target_name);

CREATE INDEX IF NOT EXISTS idx_runs_latest
    ON index_runs(status, completed_at DESC)
    WHERE status = 'completed';

CREATE INDEX IF NOT EXISTS idx_file_artifacts_run
    ON file_artifacts(run_id);

CREATE INDEX IF NOT EXISTS idx_file_tracking_hash
    ON file_tracking(content_hash);

CREATE INDEX IF NOT EXISTS idx_file_tracking_unindexed
    ON file_tracking(is_indexed)
    WHERE is_indexed = 0;



-- 8. FILE CHANGELOG
CREATE TABLE IF NOT EXISTS file_changelog (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES index_runs(id) ON DELETE CASCADE,
    base_run_id     INTEGER REFERENCES index_runs(id) ON DELETE SET NULL,
    file_id         INTEGER NOT NULL REFERENCES string_dict(id),
    entity_index    TEXT,       -- space-separated entity IDs for FTS5 tokenization
    node_changes    BLOB,       -- zstd-compressed orjson bytes (array of NodeDiff dicts)
    UNIQUE (run_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_file_changelog_file
    ON file_changelog(file_id, run_id);

-- FTS5 external content table: inverted index only, no text duplication on disk
CREATE VIRTUAL TABLE IF NOT EXISTS file_changelog_fts USING fts5(
    entity_index,
    content='file_changelog',
    content_rowid='id'
);

-- Sync triggers: keep FTS index in sync with file_changelog automatically
CREATE TRIGGER IF NOT EXISTS trg_file_changelog_ai
    AFTER INSERT ON file_changelog
BEGIN
    INSERT INTO file_changelog_fts(rowid, entity_index)
    VALUES (new.id, new.entity_index);
END;

CREATE TRIGGER IF NOT EXISTS trg_file_changelog_ad
    AFTER DELETE ON file_changelog
BEGIN
    INSERT INTO file_changelog_fts(file_changelog_fts, rowid, entity_index)
    VALUES ('delete', old.id, old.entity_index);
END;

CREATE TRIGGER IF NOT EXISTS trg_file_changelog_au
    AFTER UPDATE ON file_changelog
BEGIN
    INSERT INTO file_changelog_fts(file_changelog_fts, rowid, entity_index)
    VALUES ('delete', old.id, old.entity_index);
    INSERT INTO file_changelog_fts(rowid, entity_index)
    VALUES (new.id, new.entity_index);
END;
