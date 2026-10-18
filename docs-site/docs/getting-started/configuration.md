---
sidebar_position: 3
title: "Configuration"
description: "Configure Batho with batho.yaml and environment variables"
---

# Configuration

Batho works out of the box with zero config. For production use, configure with the unified root config file `./batho.yaml` (or start from `batho.yaml.example`) plus optional environment overrides.

## Configuration Precedence

1. Built-in defaults
2. `./batho.yaml`
3. Environment variables (override file values)
4. CLI flags (override for a specific run)

## Core Config Areas (`batho.yaml`)

The `batho.yaml` config is structured into the following sections:

### 1. `schema_version`
String identifier for configuration schema compatibility. As of v2.0.0, this is `"batho-config.v1"`.

### 2. `logging`
Controls process-wide logging and CLI verbosity behavior.
- `level`: Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
- `json_format`: `true` for structured JSON logs, `false` for console logging, `null` to auto-detect.
- `quiet`: `true` to suppress non-error outputs.
- `file`: Path to an optional log file.
- `format`: Log format string.

### 3. `paths`
Controls artifact and cache locations.
- `db_path`: Base database directory path. Default is `.batho`.
- `cache_dir`: Shared cache directory for rules, dependencies, and AST caches. Default is `.batho/cache`.

### 4. `indexer`
Controls indexing limits and warning/strict levels.
- `max_file_size_kb`: Skip files exceeding this size (default: `500`).
- `max_indexed_files`: Hard cap on total indexed files (default: `200000`).
- `max_workers`: Max parallel workers for parsing (`0` = auto CPU count).
- `ignore_patterns`: List of gitignore-style glob patterns.
- `ignore_files`: Custom ignore files path.
- `default_patterns_file`: Custom patterns file path.
- `ignore_defaults`: Whether built-in default ignore patterns apply (default: `true`). Covers lockfiles, `node_modules/`, build artifacts, sourcemaps/minified bundles, and agent-tool output dirs (`graphify-out/`, `.cursor/`, `.claude/`, `.devin/`, `.specs/`, …). Set to `false` only for exotic repos — `ignore_patterns` and `.gitignore` still apply. Build, `batho patch` change detection, and watch mode all honor this flag, and build logs `ignore_skip_breakdown` (INFO) with the defaults-vs-user skip counts.
- `package_roots`: Extra import-root directories (default: `[]`). Batho normally derives a file's import namespace from repo evidence — `__init__.py` marker chains, `pyproject.toml`/`setup.cfg`/`Cargo.toml`/`go.mod`/`tsconfig*.json` (`paths`, `baseUrl`) — so `backend/app/…` imported as `app.…` resolves with no configuration. Use this list only for layouts no evidence describes (e.g. `sys.path` manipulation at runtime): `package_roots: ["backend"]` makes `backend/` an import root.
- `fail_on_warning`: Treat indexing warnings as failure.
- `strict`: Parse strictly, treating warnings as errors.
- `strict_hashing`: When `true`, force SHA-256 content hashing on every tracked file during patch change detection. When `false` (default), skip hashing when `mtime`+`inode`+`size` all match (fast-path).

### 5. `graph`
Configures hypergraph consistency.
- `backend`: Graph storage backend (`auto`, `in-memory`, `arrow`).
- `auto_threshold_files`: File count threshold to switch backend (default `500`).
- `auto_threshold_entities`: Entity count threshold to switch backend (default `30000`).
- `cycle_detection`:
  - `enabled`: Detect inheritance or import cycles.
  - `fatal`: If `true`, fails the build when a cycle is detected.
- `orphan_pruning`:
  - `enabled`: Remove nodes with no edges.
  - `keep_entry_points`: Do not prune program entry points.
  - `keep_exports`: Do not prune exported symbols.

### 6. `flags`
Top-level parser execution controls.
- `fail_on_warning`: Stop execution on warning.
- `strict`: Enable strict mode.
- `audit_log_enabled`: Write patch audit trails to `run_artifacts` in the database.

### 7. `dependency`
Consolidated Dependency Extraction Utility (CDEU) settings.
- `enabled`: Enable indexing of stdlib and third-party dependencies.
- `introspection`:
  - `enabled`: Introspect installed packages. Every manager with an install store is supported: Python (venv), npm (`node_modules`), Cargo (registry cache), Go modules (GOPATH cache), Maven (`~/.m2`) **and** Gradle (`~/.gradle/caches`), Ruby gems (`GEM_HOME`), PHP/Hack composer (`vendor/`), NuGet (`~/.nuget/packages`), Dart pub (`.dart_tool` / `PUB_CACHE`), Julia (depot), R (renv / `R_LIBS_USER`), Haskell (cabal store), Swift SPM (`.build/checkouts`), Zig (zigmod), Erlang (rebar3 `_build`), OCaml (opam), Lua (luarocks), and Perl (local::lib).
  - `mode`: `shallow` (exports only) or `deep` (recursive).
  - `venv_auto_detect`: Find `.venv` directories automatically.
  - `timeout_seconds`: Timeout for introspecting one package.
  - `full_scan`: **The declared-deps switch.** `true` attempts every declared dependency (subject to the env-skip policy and no-ecosystem classification); `false` attempts only packages in the bundled popular-packages DB. With `false`, deps not in the popular DB are reported as `gate_dropped` in the `dependency_index_complete` build log with a hint to enable `full_scan`. This flag is the only declared-dep bypass — there is no always-introspect bypass.
  - `popular_packages_db_path`: Custom popular packages path.
  - `skip_missing_env` (default `true`): **Skip-when-env-missing policy** — when a dependency's environment (venv, `node_modules`, `vendor/`, user package store) cannot be found, the dependency is skipped: no introspection attempt, no fallback `{name: [name]}` stub symbols, no cache write. Skips are counted in build stats (`dependency_index_complete` → `skipped_no_env`) with a log hint. Set `false` to restore legacy best-effort behavior. Python note: Batho never falls back to its own interpreter — a project without a resolvable venv is skipped, not introspected against the wrong environment.
  - `managers`: Per-manager enable overrides, e.g. `{gem: false}` disables gem introspection. Keys are manager names (`pip`, `npm`, `cargo`, `go`, `maven`, `gradle`, `gem`, `composer`, `nuget`, `pub`, `julia`, `cran`, `cabal`, `spm`, `zigmod`, `rebar3`, `opam`, `luarocks`, `cpan`); unknown keys log a warning.
- `stdlib`:
  - `enabled`: Index built-in language libraries.
  - `languages`: Languages to index. Defaults to 27 languages: `python`, `javascript`, `typescript`, `go`, `rust`, `c`, `cpp`, `java`, `ruby`, `csharp`, `php`, `kotlin`, `swift`, `scala`, `dart`, `haskell`, `lua`, `r`, `perl`, `julia`, `zig`, `bash`, `objc`, `erlang`, `ocaml`, `hack`, `verilog`. See `batho.yaml.example` for the full list.
- `cache`:
  - `enabled`: Cache dependency lookups.
  - `ttl_days`: Days before dependency cache entries expire.
- `max_deps_per_manifest`: Limit on dependencies parsed per manifest file.

### 8. `artifact_blobs`
Fine-grained control over database size. Disable unused blobs to conserve disk space.
- `file_artifacts` (blobs written per file):
  - `bsg_agent_view`: LLM-optimized structural nodes.
  - `bsg_storage_view`: Full-fidelity delta blobs.
  - `bsg_rel_view`: Relationships array.
- `run_artifacts` (blobs written per run):
  - `context_overview`: Metadata summary.
  - `telemetry_metrics`: Timing and counts.
  - `structural_metrics`: LOC, fan-in/out, etc.
  - `security_audit`: Security rule violations (default `false` — opt in to persist).
  - `artifact_payload`: Minified LLM injection payload.
  - `delta_stats`: Churn and node diffs.
  - `rule_stats`: Per-rule match/edge stats from the rules engine.
  - `enrich_profile`: Enrichment profile report.
  - `enrich_score`: Enrichment score payload.

### 9. `rules`
Configures the BSG rule plugins engine.
- `enabled`: Enable semantic rule checks during indexing.
- `auto_load_all_plugins`: Auto-load all built-in rules.
- `builtin_plugins`: List of built-in plugins to run.
- `disabled_rules`: List of rules to explicitly disable.
- `custom_rules_path`: Path to an external YAML file with custom rules.
- `custom_rules_dir`: Directory of `*.yaml`/`*.yml` plugin files loaded as custom rules (default `.batho/plugins`; each file is fingerprinted individually).
- `custom_rules_inline`: List of inline custom rules.
- `strict_validation`: Fail if a rule is invalid.
- `cache_ttl`: Cache time-to-live for rule evaluations.
- `fail_on_rule_error`: Fail build on rule execution error.

### 10. `plugins`
Plugin-host configuration plus per-rule overrides (e.g., setting a rule severity to `warning` or `error`).
- `core.required` (default `true`): the mandatory core pack (`batho_plugin.core`) failing to load fails the build with guidance. Set `false` to degrade gracefully.
- `external.enabled` (default `false`): opt-in gate for the external pack — the 9 security/quality interceptor plugins (`silent_failure_catcher`, `dependency_blast_radius`, `resource_leak_preventer`, `nplus1_query_catcher`, `iac_drift_sentinel`, `schema_migration_enforcer`, `api_contract_guardian`, `hardcoded_secret_catcher`, `auth_boundary_shield`) that tag risks during BSG compression. **Interceptors do not run unless this is `true`.**
- `external.select` (default `[]`): per-plugin allowlist of external plugin stems; empty loads every external plugin.
- `fingerprint_in_cache` (default `true`): the plugin-set fingerprint participates in the AST cache variant, so a changed plugin set invalidates stale hook-derived cache entries.
- `reextract_on_drift` (default `true`): when the plugin fingerprint differs from the previous run, `batho patch` escalates to a full-repo re-extraction so every file's entities are re-stamped under the current plugin set. Set to `false` for warn-only legacy behavior.
- `telemetry.hooks_metadata` (default `false`): debug flag — stamp `bsg.hooks` (the list of plugin ids that mutated each entity) onto entity metadata.
- `host.dispatch_order` (default `priority_then_id`): canonical hook dispatch order — priority descending, then `plugin_id` ascending (the only supported value).
- `overrides`: per-plugin, per-rule field overrides keyed by plugin stem then `rule_id`.

### 11. `bsg`
Configures the Batho Structured Graph engine.
- `parallel`:
  - `enabled`: Enable parallel BSG rendering.
  - `max_workers`: Worker cap (1-32).
  - `chunk_size`: Files per chunk.
- `cache`:
  - `enabled`: Cache rendered BSGs.
  - `max_size_mb`: Memory limit.
  - `ttl_days`: Cache expiry.
- `symbol_resolution`:
  - `enabled`: Cross-file symbol mapping.
  - `prune_unresolved`: Prune common stdlib method stubs on unknown receivers.
- `parsing`:
  - `error_recovery`: Continue past tree-sitter parse errors.
  - `skip_comments`: Skip parsing comments.
- `bidirectional`:
  - `enabled`: Emit syntax glue for lossless byte-for-byte source reconstruction.
  - `include_gaps`: Emit `SYNTAX_GLUE` entities.
  - `verify_integrity`: Cryptographically check SHA-256 integrity on reconstruction.
  - `storage_view`: Keep raw content in the storage view.

### 12. `extraction`
Configures the AST parser cache and opt-in entity extraction.
- `cache`:
  - `enabled`: Cache parsed AST structures.
  - `ttl_days`: Expiry for AST entries.
  - `max_entries`: Max files in the cache.
- `extract_parameters`: Extract function/method parameters as `PARAMETER` entities (default: `false`). Enabling this can significantly increase entity counts. Note: parameter *type annotations* and return types are always captured in the stored signature regardless of this flag — receiver-type resolution (`svc: GraphService = Depends(...)`, `svc = get_svc()` assignment flow) does not require `extract_parameters: true`.
- `extract_type_parameters`: Extract generic type parameters (T, K, V) as `TYPE_PARAMETER` entities (default: `false`). Enabling this can significantly increase entity counts.
- `rationale_markers`: Comment prefixes that promote a standalone comment into a first-class `COMMENT_BLOCK` entity with a `RATIONALE_FOR` edge to the entity it annotates (default: `["WHY:", "NOTE:"]`).
- `rationale_markers_case_sensitive`: Whether `rationale_markers` matching is case-sensitive (default: `true`). Set `false` to also match `why:`, `note:`, etc.

### 13. `community_detection`
Configures greedy modularity clustering (networkx) for community detection.
- `enabled`: Enable community detection (`true`).
- `skip_threshold`: Skip detection if node count exceeds this (`200000`).
- `sample_threshold`: Sample graph if node count exceeds this (`100000`).
- `edge_weights`: Per-relationship-kind weights for clustering input (`CALLS`/`INHERITS`/`IMPLEMENTS` 3, `IMPORTS` 2, `READS`/`WRITES` 1, `CONTAINS` 0). A weight of `0` excludes the kind; effective edge weight = kind weight × call-site multiplicity × edge confidence.
- `min_community_entities`: Communities smaller than this merge into their strongest neighbor; unmergeable ones are flagged `is_singleton` and hidden from overview (`3`).
- `max_community_fraction`: Communities exceeding this fraction of clustered entities are re-clustered on their induced subgraph (`0.25`).
- `superhub_degree_percentile`: Entities above this degree percentile are dropped before detection and reattached afterward (`99`).
- `generic_dir_blocklist`: Directory names too generic for community labels (`src, lib, app, core, utils, common, shared, helpers, test, tests`).
- `overview_top_n`: Number of communities shown in `graph_overview` (`12`).
- `domain_grouping`: When `true` (default `false`), entities are pre-grouped by dominant `bsg.*` metadata (`bsg.domain` → `bsg.service_tag` → `bsg.category`, untagged → `(untagged)`) and clustering runs within each domain group, producing domain → community → sub-community trees.
- `llm`: Optional post-build LLM labeler used by `batho communities label`. Disabled by default; never runs in the query path — labels persist to `communities.ipc` so later reads are deterministic and LLM-free.
  - `enabled`: Enable LLM labeling (default `false`).
  - `provider`: LLM provider (default `anthropic`).
  - `model`: Labeling model (default `claude-haiku-4-5-20251001`).
  - `max_card_tokens`: Cap on community-card content sent to the LLM (default `200`; ~200 tokens ≈ ~800 chars).

### 14. `memory`
Configures memory usage limits and warnings.
- `warning_threshold_mb`: Memory usage warning threshold (`800`).
- `critical_threshold_mb`: Critical memory usage threshold (`1500`).
- `rss_flush_threshold_mb`: Memory threshold to force cache flush (`1000`).
- `max_per_worker_mb`: Maximum memory allowed per worker process (`150`).

### 15. `mcp`
Configures the MCP server tool registration and gating.
- `tools`:
  - `disabled`: Blocklist of tool names NOT to register. When unset, defaults to the secure-by-default set: `["batho_build", "batho_export", "batho_load", "batho_gc"]`. Set to `[]` to enable all tools.
  - `enabled`: Optional allowlist. If set, ONLY these tools register (overrides `disabled`). Example: `["graph_overview", "graph_query", "batho_build"]`.
- `toolsets`: Named tool groups resolved to a disabled set, consulted only when `tools.disabled`/`tools.enabled` are both unset (`null` = secure defaults). `true` enables a group, `false` disables it. Groups: `retrieval` (`graph_overview`, `graph_query`, `get_entity`, `trace_path`, `get_file_graph`, `file_connectivity`, `search_entities`, `get_delta`), `diagnostics` (`batho_status`, `batho_list_runs`, `batho_history`), `registry` (`list_repos`, `add_repo`, `remove_repo`), `admin` (`batho_build`, `batho_patch`, `batho_export`, `batho_gc`, `batho_fix`, `batho_load`). Examples: `{admin: true}` exposes everything including Tier-3 admin tools; `{retrieval: true, diagnostics: false, registry: false, admin: false}` is a minimal retrieval-only surface.

See [MCP Tool Gating](/docs/mcp#tool-gating) for details.

### 16. `progress`
Configures the pytest-style progress display for `batho build` and `batho patch`.
- `enabled`: Master switch for progress rendering (`true`).
- `style`: `progress` renders `[ NN%]` percentages, `classic` renders counts only (`progress`).
- `mininterval_s`: Minimum seconds between bar redraws (`0.2`).
- `show_after_s`: Phases finishing faster than this never render a bar (`2.0`).
- `keepalive_s`: Non-TTY long-phase keep-alive line interval; `0` disables (`60`).

Bars render on stderr only and are suppressed automatically for quiet/JSON modes and piped
output. `NO_COLOR` disables color but keeps the bar.

### 17. `workspace`
Multi-repo / monorepo manifest scoping (optional — omit entirely for single-package repos).
Each discovered manifest dir maps to a package identity; these keys restrict which manifests
are read.
- `manifest_dirs`: Which manifest dirs govern dependencies (`null` = every discovered
  manifest). List form is an allowlist of repo-relative dir prefixes; dict form supports
  `allow` + `deny` (deny wins). Example — keep a vendored docs site out of dependency
  introspection: `manifest_dirs: {deny: [docs-site, examples]}`.

### 18. `project`
Optional explicit project identity — overrides the manifest-derived package identity
(`manager`/`name`/`version` used in every entity id prefix).
- `package`:
  - `manager`: Package manager (`pip` — also `npm`, `cargo`, `go`, `maven`, …).
  - `name`: Project name (**required** when `project.package` is set).
  - `version`: Project version (`0.0.0`).

```yaml
project:
  package:
    manager: pip
    name: my-project
    version: 1.0.0
```

### 19. `watch`
Tuning for the MCP watcher engine's auto-patch triggers. Per-repo overrides live in
`~/.batho/mcp-repos.json` via `add_repo(name, path, watch=True, watch_mode=..., ...)`.
- `mode`: `auto` (default) adds a git-sentinel trigger layer when the repo resolves a
  git dir — writes to `index`, `HEAD`, `refs/` (stage/commit/checkout/merge) flush the
  pending queue after a short settle delay — falling back to file events in non-git
  repos. `fs` = file events only. `off` = pending state is still tracked for staleness
  banners, but nothing auto-patches.
- `max_staleness_ms`: Hard bound — pending changes flush within this window even when
  edits never stop (`60000`, range `5000`–`600000`). Fixes debounce starvation during
  long agent sessions.
- `flush_threshold`: Flush immediately once this many files are pending (`300`).
- `git_settle_ms`: Settle delay after a git boundary event before flushing (`300`).
- `vcs_op_hold_ms`: While `index.lock` or an in-progress sentinel (`rebase-merge/`,
  `MERGE_HEAD`, `sequencer/` …) exists, flushes are deferred — capped at this duration
  so a stale lock after a crash can't block patching forever (`30000`).

While a git operation is mid-flight, `batho_status` reports
`Git operation in progress — re-index deferred`, and query banners show pending file
counts and oldest-pending age.

### 20. `skills`
Agent skill-pack management (`batho install` + auto-sync on `batho mcp` start).
- `auto_install`: When `true` (default), `batho mcp` installs/refreshes the skill
  pack on start when it's missing or version-drifted. Set to `false` to opt out —
  e.g. enterprise/CI environments that must not fetch from the network.
  `BATHO_NO_SKILL_SYNC=1` also disables sync regardless of this setting.

> **Note:** Unknown top-level sections in `batho.yaml` are ignored during
> validation — a `config_unknown_sections_ignored` warning is logged naming
> them, so a misspelled section can't silently disable an intended setting.

---

## Environment Variables

Override settings on demand without changing your `batho.yaml` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `BATHO_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `BATHO_LOG_JSON` | `null` | Force JSON logs (`true`) or console (`false`) |
| `BATHO_LOG_QUIET` | `false` | Suppress non-error stdout outputs |
| `BATHO_LOG_FILE` | unset | Log file output destination |
| `BATHO_MAX_FILE_SIZE_KB` | `500` | Max file size to parse |
| `BATHO_MAX_INDEXED_FILES` | `200000` | Upper limit on file counts |
| `BATHO_INDEX_WORKERS` | `0` | Workers count (0 = auto CPU count) |
| `BATHO_RULES_ENABLED` | `true` | Enable or disable rule plugins |
| `BATHO_RULES_CUSTOM_RULES_PATH` | unset | Custom rules file path override |
| `BATHO_RULES_CUSTOM_RULES_DIR` | `.batho/plugins` | Directory of `*.yaml`/`*.yml` rule plugin files |
| `BATHO_RULES_BUILTIN_PLUGINS` | config list | Comma-separated built-in plugin list |
| `BATHO_RULES_DISABLED_RULES` | unset | Comma-separated rule names to disable |
| `BATHO_RULES_STRICT_VALIDATION` | `false` | Fail if a rule definition is invalid |
| `BATHO_RULES_FAIL_ON_RULE_ERROR` | `false` | Fail the build on rule execution error |
| `BATHO_RULES_CACHE_TTL` | `3600` | Rules-evaluation cache TTL (seconds) |
| `BATHO_IGNORE_PATTERNS` | unset | Comma-separated extra ignore globs |
| `BATHO_IGNORE_FILES` | unset | Comma-separated ignore file paths |
| `BATHO_IGNORE_DEFAULTS` | `true` | Apply the bundled default ignore patterns |
| `BATHO_DEFAULT_PATTERNS_FILE` | unset | Override path for the default-patterns YAML |
| `BATHO_PACKAGE_ROOTS` | unset | Comma-separated user-declared package roots |
| `BATHO_NO_PROGRESS` | unset | `1`/`true`/`yes` disables progress bars (strict — `0` does NOT disable) |
| `BATHO_STRICT_HASHING` | `false` | `true` forces SHA-256 hashing of every tracked file during patch change detection |
| `BATHO_FILE_CHANGELOG_MAX_RUNS` | `100` | Cap on `file_changelog` rows retained per file |
| `BATHO_WATCH_MODE` | `auto` | Watcher mode: `auto` (git sentinels in git repos), `fs`, `off` |
| `BATHO_WATCH_MAX_STALENESS_MS` | `60000` | Max time pending changes may go unpatched |
| `BATHO_WATCH_FLUSH_THRESHOLD` | `300` | Immediate flush when this many files are pending |
| `BATHO_GRAPH_BACKEND` | `auto` | Graph storage backend: `auto`, `in-memory`, `arrow` |
| `BATHO_COMMUNITY_DETECTION_ENABLED` | `true` | Enable community detection at build time |
| `BATHO_COMMUNITY_DETECTION_SKIP_THRESHOLD` | `200000` | Skip detection above this node count |
| `BATHO_COMMUNITY_DETECTION_SAMPLE_THRESHOLD` | `100000` | Sample graph above this node count |
| `BATHO_COMMUNITY_DOMAIN_GROUPING` | `false` | Pre-group entities by `bsg.*` domain metadata before clustering |
| `BATHO_COMMUNITY_LLM_ENABLED` | `false` | Enable LLM community labeling (`batho communities label`) |
| `BATHO_COMMUNITY_LLM_PROVIDER` | `anthropic` | LLM provider for community labeling |
| `BATHO_COMMUNITY_LLM_MODEL` | `claude-haiku-4-5-20251001` | LLM model for community labeling |
| `BATHO_COMMUNITY_LLM_MAX_CARD_TOKENS` | `200` | Token cap on community cards sent to the LLM |
| `BATHO_LLM_API_KEY` | unset | API key for the configured LLM provider |
| `BATHO_NO_SKILL_SYNC` | unset | `1`/`true` disables skill auto-sync on `batho mcp` start |
| `BATHO_VERSION` | unset | Pin the skill-pack release tag instead of `latest` |
| `BATHO_MCP_TOOLS_ENABLED` | unset | Comma-separated allowlist of MCP tools to register |
| `BATHO_MCP_TOOLS_DISABLED` | unset | Comma-separated blocklist of MCP tools |

Native tqdm overrides (`TQDM_DISABLE`, `TQDM_MININTERVAL`, `TQDM_MINITERS`, ...) are also
honored. Caution: **any non-empty `TQDM_DISABLE` value disables, including `"0"`** — prefer
`BATHO_NO_PROGRESS`.

---

## Scenario Playbooks

### 1) Local Dev Setup (Fast Iteration)

Configured for maximum AST caching and incremental patching:

```yaml
# ./batho.yaml
indexer:
  max_workers: 0
  max_file_size_kb: 500
bsg:
  cache:
    enabled: true
extraction:
  cache:
    enabled: true
```

Run CLI commands locally:
```bash
# Initialize database and build full graph
batho build --root .

# Apply incremental patches as files change
batho patch --root .

# Export light LLM-optimized agent view
batho export --root . --view agent --output bsg_agent.json
```
