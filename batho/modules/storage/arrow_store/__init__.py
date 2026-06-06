"""batho/modules/storage/arrow_store — Apache Arrow IPC + zstd BSG scratch store.

Replaces the four SQLite scratch tables (entity_dict, query_entities,
query_relationships, dangling_references) with persistent Arrow IPC files
stored under .batho/bsg/<run_uuid>/.

Public API:
    BsgScratchStore — main session store class
"""

from .store import BsgScratchStore

__all__ = ["BsgScratchStore"]
