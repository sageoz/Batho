
```bash
# Show all commands
batho --help

# Show command-specific help
batho <command> --help
```

### Command Matrix

| Command | Purpose |
|------|---------|
| `index` | Build/update graph + BSG artifacts for a repo |
| `stats` | Show current index metadata and health summary |
| `snapshots` | List stored snapshots |
| `diff-snapshots` | Diff two snapshots |
| `patch` | Apply incremental updates from scan/diff/files |
| `patches` | List patch operations |
| `patch-info` | Show patch operation details |
| `patch-chain` | Show chain of patches for a snapshot |
| `apply-patch` | Apply patch by diff file or patch id |
| `cherry-pick` | Apply a patch to another snapshot |
| `webhook` | Parse/process a webhook payload |
| `webhook-server` | Start webhook server from `batho.yaml` |
| `hooks` | Git client-side hook management (install/remove/run) |
| `invalidate` | Clear index file cache |
| `cache` | AST cache management (`stats`, `invalidate`, `clear`) |
| `storage` | Persistent artifact registry tools (`backfill`, `verify`, `cleanup`, `stats`, `rebuild-indexes`) |
| `query` | Query persisted entity/relationship indexes |
| `bsg` | Render BSG outputs (`compressed`, `full`, `hierarchical`) |

### Indexing & Snapshots

```bash
# Full index
batho index --root /path/to/repo --verbose

# Force full rebuild (disable incremental path)
batho index --root /path/to/repo --full

# Index and create snapshot
batho index --root /path/to/repo --snapshot --snapshot-label "release-candidate"

# Snapshot inspection
batho snapshots --root /path/to/repo
batho diff-snapshots --root /path/to/repo --snapshot-a SNAP_A --snapshot-b SNAP_B
```

### Patch Lifecycle

```bash
# Auto-detect file changes and patch
batho patch --root /path/to/repo --scan

# Patch from unified diff
batho patch --root /path/to/repo --diff /path/to/changes.diff

# Patch specific files
batho patch --root /path/to/repo src/a.py src/b.py

# Patch history and details
batho patches --root /path/to/repo --format timeline
batho patch-info --root /path/to/repo --patch-id PATCH_ID --format summary
batho patch-chain --root /path/to/repo --snapshot-id SNAP_ID --full

# Advanced patch operations
batho apply-patch --root /path/to/repo --base-snapshot SNAP_ID --diff-file /path/to/changes.diff
batho cherry-pick --root /path/to/repo --patch-id PATCH_ID --target-snapshot SNAP_ID
```

### BSG Rendering & Querying

```bash
# Render BSG formats
batho bsg --root /path/to/repo --mode compressed --budget 12000
batho bsg --root /path/to/repo --mode full
batho bsg --root /path/to/repo --mode hierarchical

# Query persisted graph indexes
batho query --root /path/to/repo --entity-type function --limit 50
batho query --root /path/to/repo --file-path src/api.py
batho query --root /path/to/repo --relationship-type calls --rebuild-index
```

### Cache & Storage Operations

```bash
# Index cache cleanup
batho invalidate --root /path/to/repo

# AST cache management
batho cache stats
batho cache invalidate "**/*.py"
batho cache clear

# Persistent storage management
batho storage backfill --root /path/to/repo
batho storage verify --root /path/to/repo --repair
batho storage cleanup --root /path/to/repo          # dry-run
batho storage cleanup --root /path/to/repo --apply  # execute cleanup
batho storage stats --root /path/to/repo
batho storage rebuild-indexes --root /path/to/repo
```

### Webhook Operations

```bash
# Parse/process one webhook payload
batho webhook --payload '{"event":"push"}' --headers '{"X-GitHub-Event":"push"}'

# Process webhook with repository context
batho webhook --root /path/to/repo --payload '{...}' --headers '{...}'

# Start webhook server from config
batho webhook-server --root /path/to/repo
```

### Git Hooks Management

YAML-driven Git client-side hook automation with enterprise reliability.

```bash
# List configured hooks and templates
batho hooks list --root /path/to/repo

# Check installation status
batho hooks status --hook pre-commit

# Install all enabled hooks (auto-bootstraps .batho/hooks.yaml if missing)
batho hooks install --all

# Install specific hook with force (overwrites unmanaged)
batho hooks install --hook pre-commit --force

# Remove managed hooks
batho hooks remove --all

# Run hook manually (supports custom hooks for CI/CD)
batho hooks run --hook enterprise-nightly --verbose
```

Configuration in `.batho/hooks.yaml`:

```yaml
version: hooks.v1
defaults:
  shell: /bin/sh
  timeout: 60
hooks:
  pre-commit:
    enabled: true
    stages:
      - run: ruff check .
      - run: pytest --co -q
  pre-push:
    enabled: true
    stages:
      - run: pytest -x --tb=short
```

Enable in `batho.yaml`:

```yaml
hooks:
  enabled: true
  include: true
```

### Index Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-workers` | `0` (auto) | Worker threads — 0 uses CPU × 2, capped at 32 |
| `--max-file-size-kb` | `500` | Skip files larger than this |
| `--extensions` | all supported | Restrict indexing to selected extensions |
| `--full` | off | Disable incremental reuse and force full rebuild |
| `--base-snapshot` | auto | Prefer this snapshot for incremental indexing |
| `--output-json` | none | Optional override path for graph JSON output |
| `--metrics-output` | from config | Write metrics JSON to explicit path |
| `--log-json` | off | JSON structured logs (useful in CI) |
| `--verbose` | off | Print progress to stdout |
| `--snapshot` | off | Create snapshot after indexing |
| `--snapshot-label` | none | Attach label to generated snapshot |

### BSG Options

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `compressed` | Rendering mode: compressed, full, hierarchical |
| `--budget` | `12000` | Token budget for compressed mode |

### Patch Options

| Flag | Default | Description |
|------|---------|-------------|
| `--scan` | off | Auto-scan for changes |
| `--dry-run` | off | Preview changes without applying |
| `--base-snapshot` | auto | Use specific snapshot as base |
| `--force-index-patch` | off | Force traditional index-based patching |
| `--diff` | none | Apply patch from unified diff |
| `files...` | none | Patch explicit changed files |

---