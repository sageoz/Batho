"""Arrow IPC schema definitions for the BSG scratch store.

Four tables for scratch storage:
  entity_dict          — integer key ↔ opaque entity ID string
  entities             — query_entities equivalent (columnar)
  relationships        — query_relationships equivalent (columnar)
  dangling             — dangling_references equivalent (columnar)
"""

from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = "bsg-arrow-store.v1"

ENTITY_DICT_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("id", pa.int64(), nullable=False),
        pa.field("val", pa.large_utf8(), nullable=False),
    ]
)

ENTITIES_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("entity_key", pa.int64(), nullable=False),
        pa.field("run_id", pa.int32(), nullable=False),
        pa.field("entity_name", pa.dictionary(pa.int32(), pa.utf8()), nullable=False),
        pa.field("entity_type", pa.dictionary(pa.int16(), pa.utf8()), nullable=False),
        pa.field("fqn", pa.large_utf8(), nullable=True),
        pa.field("file_path", pa.dictionary(pa.int32(), pa.utf8()), nullable=False),
        pa.field("line_number", pa.int32(), nullable=False),
        pa.field("signature", pa.large_utf8(), nullable=True),
        pa.field("is_exported", pa.bool_(), nullable=False),
    ]
)

RELATIONSHIPS_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("source_key", pa.int64(), nullable=False),
        pa.field("target_key", pa.int64(), nullable=False),
        pa.field("relation_type", pa.dictionary(pa.int16(), pa.utf8()), nullable=False),
        pa.field("run_id", pa.int32(), nullable=False),
        pa.field("metadata_json", pa.utf8(), nullable=True),
    ]
)

DANGLING_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("source_key", pa.int64(), nullable=False),
        pa.field(
            "unresolved_target_name",
            pa.dictionary(pa.int32(), pa.utf8()),
            nullable=False,
        ),
        pa.field("relation_type", pa.dictionary(pa.int16(), pa.utf8()), nullable=False),
        pa.field("run_id", pa.int32(), nullable=False),
    ]
)
