# Output Structure

All outputs are stored in `.ctn/`.

---

## Structure

```
.ctn/
├── index.json                   # Index metadata + staleness + persistence model
├── artifact_registry.db         # SQLite artifact registry (durable outputs)
├── file_cache.json              # Index file cache
├── file_hashes.json             # Content-hash tracker for incremental scans
├── metrics.json                 # Optional metrics output
├── interception_stats.json      # Rule interception matrix
├── evolution_ledger.json        # Failure synthesis ledger
├── snapshots/                   # Time Machine snapshots
│   └── batho_<project>_<sha>_<ts>.json
├── patches/                     # Patch operation history
│   ├── index.json
│   └── patch_<operation_id>.json
└── <index_id>/
    ├── graph.json               # Entities + relationships
    ├── bsg.json                 # Structured symbol graph
    ├── bsg_compressed.json      # LLM-ready compressed output
    ├── bsg_full.json            # Full textual BSG output
    ├── bsg_hierarchical.json    # Hierarchical textual BSG output
    └── context/
        ├── overview.md
        ├── architecture.md
        ├── tests.md
        ├── docs.md
        └── config.md
```

---

## Key Files

* graph.json → full graph
* bsg_compressed.json → LLM-ready output
* snapshots → version history
* patches → incremental updates
