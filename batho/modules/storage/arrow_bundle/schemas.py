"""Arrow IPC schema definitions for the Batho Arrow Bundle.

Seven tables replacing the SQLite database:
  runs              — index_runs
  string_dict       — global string dedup dictionary
  file_tracking     — file_path → hash/mtime/inode/size
  agent_views       — bsg_agent_view entities (sorted by file_id)
  storage_views     — bsg_storage_view entities (sorted by file_id)
  rels_views        — bsg_rel_view relationships (sorted by file_id)
  file_changelog    — flattened NodeDiff rows
  run_artifacts     — telemetry/metrics JSON columns per run
"""

from __future__ import annotations

import pyarrow as pa

BUNDLE_SCHEMA_VERSION = "batho-bundle.v1"

STRING_DICT_SCHEMA: pa.Schema = pa.schema([
    pa.field("id", pa.int64(), nullable=False),
    pa.field("val", pa.large_utf8(), nullable=False),
])

RUNS_SCHEMA: pa.Schema = pa.schema([
    pa.field("run_uuid", pa.utf8(), nullable=False),
    pa.field("schema_version", pa.utf8(), nullable=False),
    pa.field("started_at", pa.utf8(), nullable=False),
    pa.field("completed_at", pa.utf8(), nullable=True),
    pa.field("status", pa.utf8(), nullable=False),
    pa.field("git_commit", pa.utf8(), nullable=True),
    pa.field("git_branch", pa.utf8(), nullable=True),
    pa.field("root_path", pa.utf8(), nullable=False),
    pa.field("entity_count", pa.int32(), nullable=False),
    pa.field("rel_count", pa.int32(), nullable=False),
    pa.field("file_count", pa.int32(), nullable=False),
    pa.field("duration_ms", pa.int32(), nullable=True),
    pa.field("error_message", pa.utf8(), nullable=True),
])

FILE_TRACKING_SCHEMA: pa.Schema = pa.schema([
    pa.field("file_id", pa.int64(), nullable=False),
    pa.field("file_path", pa.large_utf8(), nullable=False),
    pa.field("content_hash", pa.utf8(), nullable=False),
    pa.field("mtime_ns", pa.int64(), nullable=True),
    pa.field("inode", pa.int64(), nullable=True),
    pa.field("size", pa.int64(), nullable=False),
    pa.field("is_indexed", pa.bool_(), nullable=False),
    pa.field("last_run_uuid", pa.utf8(), nullable=True),
    pa.field("updated_at", pa.utf8(), nullable=False),
    pa.field("encoding", pa.utf8(), nullable=True),
])

AGENT_VIEWS_SCHEMA: pa.Schema = pa.schema([
    pa.field("file_id", pa.int64(), nullable=False),
    pa.field("entity_id", pa.large_utf8(), nullable=False),
    pa.field("name", pa.utf8(), nullable=False),
    pa.field("entity_type", pa.utf8(), nullable=False),
    pa.field("start_line", pa.int32(), nullable=False),
    pa.field("end_line", pa.int32(), nullable=True),
    pa.field("signature", pa.large_utf8(), nullable=True),
    pa.field("content_hash", pa.utf8(), nullable=True),
    pa.field("is_exported", pa.bool_(), nullable=False),
    pa.field("fqn", pa.large_utf8(), nullable=True),
])

STORAGE_VIEWS_SCHEMA: pa.Schema = pa.schema([
    pa.field("file_id", pa.int64(), nullable=False),
    pa.field("entity_id", pa.large_utf8(), nullable=False),
    pa.field("raw_content", pa.large_utf8(), nullable=True),
    pa.field("raw_bytes", pa.large_binary(), nullable=True),
    pa.field("leading_ws", pa.utf8(), nullable=True),
    pa.field("trailing_ws", pa.utf8(), nullable=True),
    pa.field("ast_node_type", pa.utf8(), nullable=True),
    pa.field("parent_id", pa.large_utf8(), nullable=True),
    pa.field("start_byte", pa.int64(), nullable=True),
    pa.field("end_byte", pa.int64(), nullable=True),
])

RELS_VIEWS_SCHEMA: pa.Schema = pa.schema([
    pa.field("file_id", pa.int64(), nullable=False),
    pa.field("source_id", pa.large_utf8(), nullable=False),
    pa.field("target_id", pa.large_utf8(), nullable=False),
    pa.field("relation_type", pa.utf8(), nullable=False),
    pa.field("metadata_json", pa.utf8(), nullable=True),
])

FILE_CHANGELOG_SCHEMA: pa.Schema = pa.schema([
    pa.field("run_uuid", pa.utf8(), nullable=False),
    pa.field("base_run_uuid", pa.utf8(), nullable=True),
    pa.field("file_id", pa.int64(), nullable=False),
    pa.field("entity_id", pa.utf8(), nullable=False),
    pa.field("entity_name", pa.utf8(), nullable=False),
    pa.field("entity_type", pa.utf8(), nullable=False),
    pa.field("change_kind", pa.utf8(), nullable=False),
    pa.field("changed_fields", pa.list_(pa.utf8()), nullable=True),
    pa.field("old_hash", pa.utf8(), nullable=True),
    pa.field("new_hash", pa.utf8(), nullable=True),
])

RUN_ARTIFACTS_SCHEMA: pa.Schema = pa.schema([
    pa.field("run_uuid", pa.utf8(), nullable=False),
    pa.field("context_overview_json", pa.large_utf8(), nullable=True),
    pa.field("telemetry_json", pa.large_utf8(), nullable=True),
    pa.field("structural_json", pa.large_utf8(), nullable=True),
    pa.field("security_audit_json", pa.large_utf8(), nullable=True),
    pa.field("artifact_payload_json", pa.large_utf8(), nullable=True),
    pa.field("delta_stats_json", pa.large_utf8(), nullable=True),
    pa.field("created_at", pa.utf8(), nullable=False),
])

COMMUNITIES_SCHEMA: pa.Schema = pa.schema([
    pa.field("community_id", pa.int32(), nullable=False),
    pa.field("name", pa.utf8(), nullable=False),
    pa.field("entity_count", pa.int32(), nullable=False),
    pa.field("file_count", pa.int32(), nullable=False),
    pa.field("top_entities", pa.list_(pa.utf8()), nullable=True),
    pa.field("description", pa.large_utf8(), nullable=True),
    pa.field("file_paths", pa.list_(pa.utf8()), nullable=True),
])

ALL_SCHEMAS: dict[str, pa.Schema] = {
    "runs": RUNS_SCHEMA,
    "file_tracking": FILE_TRACKING_SCHEMA,
    "agent_views": AGENT_VIEWS_SCHEMA,
    "storage_views": STORAGE_VIEWS_SCHEMA,
    "rels_views": RELS_VIEWS_SCHEMA,
    "file_changelog": FILE_CHANGELOG_SCHEMA,
    "run_artifacts": RUN_ARTIFACTS_SCHEMA,
    "communities": COMMUNITIES_SCHEMA,
}
