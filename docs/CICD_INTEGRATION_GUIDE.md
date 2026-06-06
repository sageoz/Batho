# Batho CI/CD Integration Guide

This guide covers integrating Batho into your CI/CD pipeline for continuous code intelligence — building, incrementally updating, and consuming the code graph in automated workflows.

---

## 1. Overview: The Batho CI/CD Model

Batho is designed for CI/CD-native operation. The key insight is that indexing is separated from consumption:

```
┌─────────────────────────────────────────────────────┐
│  Developer Push → CI/CD Pipeline                    │
│                                                     │
│  1. Download cached artifact (.batho ZIP)           │
│  2. batho load artifact.batho    ← restore index    │
│  3. batho patch --root .         ← update index     │
│  4. batho export --view agent    ← consume index    │
│  5. Upload new artifact (.batho ZIP)                │
└─────────────────────────────────────────────────────┘
```

This avoids a full rebuild on every commit — only changed files are re-parsed.

### Cold Start vs Warm Path

| Scenario | Command | When |
|----------|---------|------|
| First run / no cache | `batho build --root .` | First time, cache miss |
| Cached run | `batho load` + `batho patch` | Every subsequent commit |
| Full rebuild | `batho build --root . --full` | Schema upgrade, major refactor |

---

## 2. GitHub Actions Integration

Reference workflow: [`cicd/github-batho.yaml`](../cicd/github-batho.yaml)

### Complete Workflow

```yaml
name: Batho Code Intelligence

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  batho-index:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install Batho
        run: pip install batho

      # Attempt to restore previous artifact (warm path)
      - name: Restore Batho artifact cache
        id: cache-restore
        uses: actions/cache/restore@v4
        with:
          path: artifact_*.batho
          key: batho-${{ runner.os }}-${{ hashFiles('**/*.py', '**/*.ts', '**/*.go', '**/*.rs') }}
          restore-keys: |
            batho-${{ runner.os }}-

      # Cold start: build from scratch if no cache
      - name: Build index (cold start)
        if: steps.cache-restore.outputs.cache-hit != 'true'
        run: batho build --root .

      # Warm path: load + patch
      - name: Load existing artifact
        if: steps.cache-restore.outputs.cache-hit == 'true'
        run: |
          # Find the artifact file
          ARTIFACT=$(ls artifact_*.batho 2>/dev/null | head -1)
          if [ -n "$ARTIFACT" ]; then
            batho load "$ARTIFACT" --root .
            batho patch --root .
          else
            batho build --root .
          fi

      # Pack the updated artifact for caching
      - name: Pack artifact
        run: batho export --pack --root .

      # Save updated artifact
      - name: Save Batho artifact cache
        uses: actions/cache/save@v4
        with:
          path: artifact_*.batho
          key: batho-${{ runner.os }}-${{ hashFiles('**/*.py', '**/*.ts', '**/*.go', '**/*.rs') }}

      # Export for consumption
      - name: Export agent view for LLM tools
        run: batho export --view agent --output batho_agent_context.json --root .

      # Optional: Integrity check as CI gate
      - name: Verify index integrity
        run: batho fix --dry-run --root .

      - name: Upload context artifact
        uses: actions/upload-artifact@v4
        with:
          name: batho-agent-context
          path: batho_agent_context.json
          retention-days: 7
```

### Cache Key Strategy

The cache key uses a hash of all source files to ensure the cache is invalidated when any code changes:

```yaml
key: batho-${{ runner.os }}-${{ hashFiles('**/*.py', '**/*.ts', '**/*.go') }}
```

**Alternative**: Use a simpler time-based key if the full file hash is too expensive:
```yaml
key: batho-${{ runner.os }}-${{ github.sha }}
restore-keys: |
  batho-${{ runner.os }}-
```

---

## 3. GitLab CI Integration

Reference workflow: [`cicd/gitlab-batho.yaml`](../cicd/gitlab-batho.yaml)

### Complete Pipeline

```yaml
stages:
  - batho

variables:
  BATHO_ARTIFACT: "artifact_${CI_PROJECT_NAME}.batho"
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

batho-index:
  stage: batho
  image: python:3.11
  cache:
    key: batho-${CI_COMMIT_REF_SLUG}
    paths:
      - .cache/pip
      - artifact_*.batho
    policy: pull-push
  before_script:
    - pip install batho --quiet
  script:
    # Try warm path first
    - |
      if [ -f "$BATHO_ARTIFACT" ]; then
        echo "Loading existing artifact..."
        batho load "$BATHO_ARTIFACT" --root .
        batho patch --root .
      else
        echo "Cold start: building from scratch..."
        batho build --root .
      fi
    # Pack for next run
    - batho export --pack --root .
    # Export for consumers
    - batho export --view agent --output batho_agent_context.json --root .
    # Integrity gate
    - batho fix --dry-run --root .
  artifacts:
    paths:
      - batho_agent_context.json
    expire_in: 7 days
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

---

## 4. The Pack / Load Cycle

The core of the CI/CD workflow is the pack/load cycle:

```
Build Phase                    Next Run
────────────                   ─────────
batho build --root .
    └─ produces:
        .batho/artifact/*.ipc
        .batho/bsg/current/*.ipc

batho export --pack
    └─ BathoBundleManager.export_artifact()
    └─ produces: artifact_<dir>.batho (ZIP)
        manifest.json
        bsg/runs.ipc.zst
        bsg/agents/<file_id>.ipc.zst
        bsg/rels/<file_id>.ipc.zst
        ...

[Upload artifact_<dir>.batho to artifact store]

                               [Download artifact_<dir>.batho]

                               batho load artifact_<dir>.batho
                                   └─ validates manifest.json schema_version
                                   └─ decompresses .ipc.zst → .ipc
                                   └─ restores .batho/artifact/ + .batho/bsg/current/

                               batho patch --root .
                                   └─ detects changed files via SHA256 comparison
                                   └─ re-parses only changed files
                                   └─ updates .batho/artifact/ + .batho/bsg/current/

                               batho export --pack
                                   └─ produces updated artifact_<dir>.batho
```

### Transport ZIP Format

```
artifact_<dirname>.batho  (ZIP file)
  manifest.json           — {"schema_version": "batho-bundle.v1", "tables": [...]}
  bsg/runs.ipc.zst        — zstd-compressed Arrow IPC stream
  bsg/file_tracking.ipc.zst
  bsg/file_changelog.ipc.zst
  bsg/run_artifacts.ipc.zst
  bsg/agents/<file_id>.ipc.zst  — one per indexed file
  bsg/rels/<file_id>.ipc.zst    — one per indexed file
```

---

## 5. Environment Variable Configuration for CI

Configure Batho behavior via environment variables without a `batho.yaml`:

```bash
# Performance
export BATHO_INDEX_WORKERS=8           # Parallel workers for build
export BATHO_MAX_FILE_SIZE_KB=500      # Skip large generated files

# Logging
export BATHO_LOG_LEVEL=INFO            # Show progress in CI logs
export BATHO_LOG_JSON=true             # Structured JSON logs for log aggregators

# Storage (override default .batho/artifact path)
export BATHO_ARTIFACT_DIR=/tmp/batho-artifact

# Rules
export BATHO_RULES_ENABLED=true        # Keep security scanning on in CI
export BATHO_RULES_DISABLED_RULES=bsg_token_optimization  # Disable specific rules

# Bidirectional
export BATHO_BSG_BIDIRECTIONAL_ENABLED=true
export BATHO_BSG_BIDIRECTIONAL_INCLUDE_GAPS=true
```

For a complete list, see [config.md — Environment Variable Index](config.md#environment-variable-index).

---

## 6. Using `batho fix` as a CI Gate

Run `batho fix --dry-run` after indexing to catch integrity issues before they reach production:

```bash
# Fail CI if database integrity issues are found
batho fix --dry-run --target all --format json --root . | tee fix_report.json

# Check for any issues in the JSON output
if jq -e '.issues | length > 0' fix_report.json > /dev/null; then
  echo "❌ Batho integrity issues found"
  cat fix_report.json
  exit 1
fi
echo "✅ Batho integrity verified"
```

**Recommended CI check mode**: `--dry-run --target db,state` (fast phases only) to avoid slowing the pipeline. Use `--deep` only for nightly/weekly integrity runs.

---

## 7. Consuming the Index in AI Workflows

### Agent Context Injection

```bash
# Export compact view for LLM context injection
batho export --view agent \
  --token-budget 8000 \
  --category source \
  --output agent_context.json \
  --root .
```

### Filtering by Category or Glob

```bash
# Only export backend source files
batho export --view storage \
  --filter "src/api/**" \
  --category source \
  --output api_context.json \
  --root .

# Export test files only
batho export --view files \
  --category test \
  --output test_summary.json \
  --root .
```

### Symbol Index for Code Review

```bash
# Flat symbol index for PR review tooling
batho export --view symbols --root . --output symbols.json

# Dependency graph for impact analysis
batho export --view dependencies --root . --output deps.json
```

### Delta View for PR Impact Analysis

```bash
# Compare current state against main branch baseline
# 1. On main branch (or from previous artifact):
batho export --view storage --output baseline.json --root .

# 2. After PR changes:
batho export --view delta \
  --baseline baseline.json \
  --output pr_delta.json \
  --root .
```

---

## 8. Monorepo Pattern

For monorepos with multiple sub-projects, run Batho per sub-project:

```bash
# Build index for each service
for service in services/auth services/api services/worker; do
  batho build --root $service
  batho export --pack --root $service
done
```

Or use a single root with glob filters for export:

```bash
# Single index for the whole monorepo
batho build --root .

# Export per service
batho export --view agent --filter "services/auth/**" --output auth_context.json --root .
batho export --view agent --filter "services/api/**" --output api_context.json --root .
```

---

## 9. Common Pitfalls

### Artifact Not Included in ZIP

The `bsg/current/` directory must exist before packing. Always run `batho build` or `batho patch` before `batho export --pack`.

```bash
# ❌ Wrong: pack before build
batho export --pack

# ✅ Correct: build first, then pack
batho build --root .
batho export --pack --root .
```

### Cache Key Too Broad

Avoid using `${{ github.run_id }}` as the only cache key — this creates a new cache on every run and never benefits from the warm path.

```yaml
# ❌ Wrong: no warm hits
key: batho-${{ github.run_id }}

# ✅ Correct: content-based with fallback
key: batho-${{ hashFiles('**/*.py', '**/*.ts') }}
restore-keys: |
  batho-
```

### `batho load` Without Prior Build

`batho load` restores an artifact but does not automatically create a `batho.yaml`. If your `batho.yaml` is not committed (it's in `.gitignore` by default), the config auto-creates with defaults on first load — this is fine.

### Artifact Expiry

If the CI artifact expires before the next run, `batho load` will fail and the pipeline should fall back to `batho build`:

```bash
if [ -f artifact_*.batho ]; then
  batho load artifact_*.batho && batho patch || batho build --root .
else
  batho build --root .
fi
```

### `.batho/` Not in `.gitignore`

The `.batho/` directory should not be committed to git — it is a local artifact store. Ensure it is excluded:

```
# .gitignore
.batho/
artifact_*.batho
batho_export.json
```

---

## 10. Batho's Built-In `.gitignore` Defaults

Batho automatically ignores these paths during indexing (no configuration needed):

- `.batho/` — own artifact directory
- `artifact_*.batho*` — transport ZIPs
- `.venv/`, `venv/`, `node_modules/` — dependency directories
- `__pycache__/`, `*.pyc` — Python cache
- `build/`, `dist/`, `target/` — build artifacts
- `.git/` — git metadata

See [config.md — Default Ignore Patterns](config.md#default-ignore-patterns) for the complete list.

---

## 11. Related Documentation

| Doc | Description |
|-----|-------------|
| [BATHO_BUILD_FLOW.md](BATHO_BUILD_FLOW.md) | Build pipeline phases A–H |
| [ORCHESTRATOR_PATCH_SPEC.md](ORCHESTRATOR_PATCH_SPEC.md) | Patch incremental update flow |
| [ORCHESTRATOR_EXPORT_SPEC.md](ORCHESTRATOR_EXPORT_SPEC.md) | Export view types and pack mode |
| [ORCHESTRATOR_LOAD_SPEC.md](ORCHESTRATOR_LOAD_SPEC.md) | Load transport ZIP ingestion |
| [STORAGE_ENGINE.md](STORAGE_ENGINE.md) | Arrow IPC storage format |
| [config.md](config.md) | Complete configuration reference |
| [CLI_REFERENCE.md](CLI_REFERENCE.md) | All CLI commands and flags |

---

*Generated for Batho v1.1.0*
