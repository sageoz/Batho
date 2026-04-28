# Batho .ctn/ Reorganization - Migration Notes

## Breaking Changes (v2.0)

This release introduces a **clean break** with no backward compatibility for the `.ctn/` directory structure.

### What Changed

#### 1. **New Directory Structure**

```
<project>/.ctn/
├── local/                          # All local state (organized by purpose)
│   ├── cache/
│   │   ├── ast_cache.db           # AST parsing cache (was file_cache.json)
│   │   └── rules_cache.bin        # BSG rules cache
│   ├── sync/
│   │   └── artifact_registry.db   # Cloud sync metadata
│   ├── metrics/
│   │   ├── metrics.json           # Build metrics
│   │   └── interception_stats.json # Plugin interception stats
│   └── state/
│       └── file_hashes.json       # File change tracking
├── index.json                      # Index metadata (root level)
├── batho_*/                        # Snapshot directories
│   ├── graph.json
│   ├── bsg.json
│   └── context/
└── snapshots/                      # Named snapshots
```

#### 2. **Removed Global Cache**

- **Old:** `~/.batho/ast_cache.db` (global across all projects)
- **New:** `.ctn/local/cache/ast_cache.db` (per-project only)

#### 3. **Renamed Files**

- `file_cache.json` → `ast_cache.db` (fixed misleading extension)
- All `.db` files now in organized subdirectories

#### 4. **Updated Default Paths**

| Config Key | Old Value | New Value |
|------------|-----------|-----------|
| `bsg.cache.path` | `~/.batho/ast_cache.db` | `.ctn/local/cache/ast_cache.db` |
| `bsg.storage.registry_path` | `.ctn/artifact_registry.db` | `.ctn/local/sync/artifact_registry.db` |
| `indexer.metrics_output` | `.ctn/metrics.json` | `.ctn/local/metrics/metrics.json` |

## Migration Steps

### For Users

1. **Delete existing `.ctn/` directories:**
   ```bash
   rm -rf .ctn/
   ```

2. **Delete global cache (no longer used):**
   ```bash
   rm -rf ~/.batho/
   ```

3. **Re-run `batho index` to rebuild with new structure:**
   ```bash
   batho index
   ```

4. **Update any custom scripts** that reference old paths:
   - Replace `file_cache.json` → `local/cache/ast_cache.db`
   - Replace `.ctn/artifact_registry.db` → `.ctn/local/sync/artifact_registry.db`
   - Replace `.ctn/metrics.json` → `.ctn/local/metrics/metrics.json`
   - Replace `.ctn/interception_stats.json` → `.ctn/local/metrics/interception_stats.json`
   - Replace `.ctn/file_hashes.json` → `.ctn/local/state/file_hashes.json`

5. **Remove custom `bsg.cache.path` from `batho.yaml`** (uses default now)

### For CI/CD Pipelines

Update any scripts that:
- Reference old cache paths
- Expect `~/.batho/` directory
- Parse `.ctn/` structure

## Benefits

### 1. **Clearer Organization**
- Cache files in `.ctn/local/cache/`
- Sync metadata in `.ctn/local/sync/`
- Metrics in `.ctn/local/metrics/`
- State in `.ctn/local/state/`

### 2. **Per-Project Isolation**
- No cross-project cache contamination
- Easier cleanup (just delete `.ctn/`)
- Better multi-project workflows

### 3. **Correct File Extensions**
- SQLite databases now use `.db` extension
- No more misleading `.json` for binary files

### 4. **Simpler Configuration**
- No need to configure cache paths
- Consistent defaults across projects

## Rollback

If you need to rollback to the previous version:

1. Checkout previous Batho version:
   ```bash
   pip install batho==<previous-version>
   ```

2. Delete new `.ctn/` structure:
   ```bash
   rm -rf .ctn/
   ```

3. Re-index with old version:
   ```bash
   batho index
   ```

## FAQ

**Q: Can I keep my old `.ctn/` directory?**  
A: No, this is a clean break. You must delete and rebuild.

**Q: Will I lose my cloud sync state?**  
A: Yes. Sync all pending artifacts before upgrading, or accept a clean slate.

**Q: Can I use both old and new versions?**  
A: No. The directory structures are incompatible.

**Q: What about my snapshots?**  
A: Snapshots in `.ctn/batho_*/` and `.ctn/snapshots/` are preserved if you don't delete `.ctn/`. However, the registry will be rebuilt.

**Q: Why remove global cache?**  
A: Per-project caches provide better isolation, easier cleanup, and avoid cross-project issues.

## Support

If you encounter issues during migration:
1. Check this document
2. Review the [plan file](/Users/rishirajsharma/.windsurf/plans/batho-ctn-reorganization-b2efed.md)
3. Open an issue with your specific error

---

**Version:** 2.0.0  
**Date:** 2026-04-28  
**Breaking Change:** Yes
