-- ============================================================
-- Batho Global Registry Schema (v1.0)
-- Centralized index tracking workspaces and public symbols.
-- ============================================================

-- 1. WORKSPACES
CREATE TABLE IF NOT EXISTS workspaces (
    repo_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name       TEXT UNIQUE NOT NULL,
    origin_url      TEXT,
    repo_path       TEXT NOT NULL,
    registered_at   TEXT NOT NULL,
    last_synced_at  TEXT,
    is_active       INTEGER DEFAULT 1
);

-- 2. ARTIFACTS
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER NOT NULL REFERENCES workspaces(repo_id) ON DELETE CASCADE,
    artifact_path   TEXT UNIQUE NOT NULL,
    latest_run_id   TEXT,
    last_synced_at  TEXT,
    entity_count    INTEGER DEFAULT 0,
    file_count      INTEGER DEFAULT 0
);

-- 3. GLOBAL SYMBOLS
CREATE TABLE IF NOT EXISTS global_symbols (
    symbol_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_name     TEXT NOT NULL,
    symbol_type     TEXT NOT NULL,
    repo_id         INTEGER NOT NULL REFERENCES workspaces(repo_id) ON DELETE CASCADE,
    run_id          TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    line_number     INTEGER,
    is_exported     INTEGER DEFAULT 0,
    fqn             TEXT
);

-- 4. CROSS REPOSITORY EDGES
CREATE TABLE IF NOT EXISTS cross_repo_edges (
    edge_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_repo_id   INTEGER NOT NULL REFERENCES workspaces(repo_id) ON DELETE CASCADE,
    target_repo_id   INTEGER NOT NULL REFERENCES workspaces(repo_id) ON DELETE CASCADE,
    dependency_type  TEXT NOT NULL,
    source_symbol    TEXT NOT NULL,
    target_symbol    TEXT NOT NULL,
    confidence_score REAL DEFAULT 1.0,
    discovered_at    TEXT NOT NULL,
    UNIQUE(source_repo_id, target_repo_id, dependency_type, source_symbol, target_symbol)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_symbols_name_type ON global_symbols(symbol_name, symbol_type);
CREATE INDEX IF NOT EXISTS idx_symbols_repo ON global_symbols(repo_id);
CREATE INDEX IF NOT EXISTS idx_edges_source ON cross_repo_edges(source_repo_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON cross_repo_edges(target_repo_id);
