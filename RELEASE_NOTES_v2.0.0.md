# Batho v2.0.0 — Release Notes

**Release date:** 2026-10-18
**Tag:** `v2.0.0`
**Version:** 2.0.0
**Test suite:** 2331 tests passing
**Supported Python:** 3.12, 3.13

---

## Overview

Batho v2.0.0 is a major release that changes **how accurate the graph is**, **how plugins work**, and **how agents get set up**. In short:

- **Graph-accuracy work (T1–T6, T8, T11–T12).** Member calls now resolve to real METHOD entities, with a confidence tier for each inference source. Unresolved stubs are quarantined from default views. Import namespaces come from evidence in the repo instead of hardcoded `src`/`lib` names. `trace_path` only follows a whitelist of structural edges. Search results are ranked by entity kind. Communities are readable and labeled.
- **Plugin architecture.** The BSG rule engine and the built-in rule packs moved into the `batho_plugin` SDK. A new `batho-calibrate` loop generates, validates, scores and retro-applies plugins for a specific repo without re-extracting files.
- **`batho install`.** One command installs the Batho skill pack and registers the MCP server with every coding-agent client it detects.
- **Watcher v2.** Auto-patch now fires on git-operation boundaries instead of on floods of raw file events.

This is a **major** version because it has breaking changes to CLI and MCP names, plugin defaults, and entity naming. Read [Breaking Changes](#breaking-changes) before you upgrade.

---

## Breaking Changes

| Change | Action required |
|--------|-----------------|
| `batho diff` renamed to **`batho history`**, with no alias. MCP tool `batho_diff` renamed to **`batho_history`**. | Update scripts and any MCP tool allowlists. Parameters are unchanged. Bare `batho history` lists recent runs (`--last N`, default 10). |
| The 9 security/quality **interceptor plugins** moved to the external pack and are **off by default**. | Set `plugins.external.enabled: true`. You can narrow it with `plugins.external.select`. If `rules.builtin_plugins` lists interceptor stems while the external pack is off, you get `Unknown built-in rule plugin` warnings. |
| **Entry-point names are no longer renamed** to `__main__` after rules run. | Entry-point entity names differ from v1.4.3 builds. `bsg.normalized_name` and `invocation_snippet` are still stamped. |
| `batho skills` replaced by **`batho install`**. | Run `batho install` once after you upgrade. |
| `unresolved:` stubs are **excluded from default query surfaces**. | Pass `include_unresolved=true` to `search_entities` / `graph_query` to get the old behavior back. |
| AST cache schema bumped to **v4**, and the cache variant now includes the rules fingerprint. | Nothing to do. Expect a one-time full cache invalidation on the first build. |

---

## New Features

### Graph accuracy

- **Receiver-type method resolution (T1).** `svc.getEntity()`-style calls resolve to first-party METHOD entities. Types are inferred from parameter annotations, DI defaults (`Depends(...)`), position-aware assignment flow, and static/module receivers. Works across Python, TS/JS, Go, Rust, C++, Java and PHP.
- **Per-source confidence tiers:** `receiver_param` (0.90), `receiver_assignment` (0.75), `receiver_type` (0.65).
- **External-constructor receivers.** `app = FastAPI()` types `app` as the introspected external class, so `app.include_router()` materializes instead of becoming a ghost entity.
- **Unresolved-ref quarantine (T2).** Ghost stubs stay in storage but are hidden from `search_entities`, `graph_query`, `graph_overview` and community detection. Suppressed counts are reported.
- **Package-root aliasing (T11).** Imports resolve under the namespace the repo actually declares. Evidence comes from `__init__.py` chains, `pyproject.toml`, `setup.cfg`, `Cargo.toml`, `go.mod` and `tsconfig` paths. This adds the `package_alias` strategy (0.85) and the `indexer.package_roots` override.
- **Import-specifier resolution (T12).** Relative specifiers resolve against the importing file (`relative_path`, 0.85). PEP 508 extras are stripped from manifest names. Rust/Ruby `::` stdlib names get dot-normalized aliases.
- **`trace_path` default-deny traversal (T6).** Only structural edges are traversed. Ties break in this order: CALLS > INHERITS/IMPLEMENTS > IMPORTS > READS/WRITES > CONTAINS. A ground-truth suite (python/ts/rust/go/java) locks this behavior into CI.
- **Kind-aware search ranking (T8).** Scoring is deterministic: exact > prefix > substring, then kind boosts, then export/fqn signals. Recall is unchanged.
- **Rationale layer (T5).** `WHY:`/`NOTE:` marker comments become `COMMENT_BLOCK` entities, linked to the code they explain through `RATIONALE_FOR` annotation edges.
- **Community labels and pruning (T4).** Clustering input is weighted, isolates and super-hubs are reattached, and oversized or tiny communities are split or merged. Every community gets a deterministic `heuristic_label`. `graph_overview` shows the top 12 labeled communities.
- **Community hierarchy and optional LLM labels.** Communities nest as domain → community → sub-community. `batho communities label` adds LLM labels at compile time only and re-labels incrementally based on a hash; it is off by default. `batho communities list --tree` prints the hierarchy.

### Plugins and calibration

- **`batho_plugin` SDK.** Contains the rule engine, the `PluginHost` stage pipeline, the core packs and the external packs. `batho build --no-plugins` runs the compiled-in fallbacks instead.
- **Generated plugin pipeline.** Repo-specific `bsg-plugin.v2` files go in `.batho/plugins/` (`rules.custom_rules_dir`). `batho plugins validate` checks them with a schema check plus a deterministic gate against sampled entities. `batho plugins apply` re-enriches an existing artifact without re-extracting files.
- **`batho-calibrate` skill.** Every build and patch writes an `enrich_profile` gap report and an `enrich_score` fitness report, plus `.batho/report/overview.md` and `.batho/report/score.md`.
- **Quarantine metadata.** `bsg.noise` / `bsg.quarantined` exclude entities from views without deleting them. Opt back in with `include_quarantined`.
- **Annotation-edge derivation.** `bsg.edge_hints`, `bsg.semantic_family` (`SEMANTICALLY_SIMILAR_TO`) and test naming conventions (`TESTED_BY`) create edges. These edges are never used for clustering or `trace_path`.
- **Rule telemetry (`rule-stats.v1`).** Each run writes hits, perf and fingerprints into `run_artifacts`.

### Agent setup and watching

- **`batho install`.** Installs the checksum-verified skill pack (`batho`, `batho-setup`, `batho-specs`, `batho-execute`, `batho-review`, `batho-calibrate`) and registers `batho mcp` with Claude Desktop, Claude Code, Cursor, Windsurf/Devin, VS Code, Codex, Gemini CLI, OpenCode and Copilot. Config files are merged rather than overwritten, writes are atomic, and the command is idempotent.
- **Watcher v2 (git-sentinel).** Patches fire once git index/HEAD/ref state settles and are held while git operations are in progress. Tune it with `watch.mode`, `max_staleness_ms`, `flush_threshold`, `git_settle_ms` and `vcs_op_hold_ms`.

### Indexing hygiene

- **Default ignore list expanded (T3).** Adds every ecosystem lockfile, `*.map`, `*.min.js`/`*.min.css`, `*.tsbuildinfo`, and agent/tool state dirs. `.gitignore` is always honored. Set `indexer.ignore_defaults: false` to opt out.
- **Skip reporting.** Each build logs an `ignore_skip_breakdown`.
- **`indexer.strict_hashing`** turns on SHA-256 change detection for every file on every patch. **`indexer.file_changelog_max_runs`** caps changelog retention.

---

## Other Changes

- **`plugins.reextract_on_drift`** (default `true`): if the plugin fingerprint changes, `batho patch` escalates to a full re-extraction.
- **`file_changelog` stores `file_path`.** History survives file deletion, and removals are now recorded correctly.
- **Packaging:** the `batho_plugin` SDK ships **inside the `batho` wheel**, so there is no separate package to install. Its dependencies (`pyyaml`, `jsonschema`) were already pinned by `batho`.
- `batho.modules.compression` re-exports the rule-engine API through a deprecated lazy shim. Import from `batho_plugin` going forward.
- Fixes: the config loader handles explicit YAML `null` values, the path sanitizer resolves the repo root once (no false traversal errors on symlinked workspaces), and the progress-overhead benchmark is skipped under coverage/CI.

---

## Metrics

| Metric | v1.4.3 | v2.0.0 |
|--------|--------|--------|
| Total tests | 1603 | 2331 |
| Resolution strategies | 6 | 10 (+ `receiver_param`, `receiver_assignment`, `package_alias`, `relative_path`) |
| Agent clients auto-configured by `batho install` | — | 9 |
| Interceptor plugins | 9 (on by default) | 9 (opt-in external pack) |

---

## Upgrade Guide

```bash
# Upgrade via uv (recommended)
uv tool upgrade batho

# Verify version
batho --version  # should show 2.0.0

# Re-install skills + register MCP with your agents
batho install

# Rebuild the graph (one-time cache invalidation is expected)
batho build
```

Then:

1. Replace `batho diff` with `batho history` in your scripts, and `batho_diff` with `batho_history` in MCP allowlists.
2. If you relied on the interceptor plugins, add `plugins.external.enabled: true` to `batho.yaml`.
3. Restart any running MCP clients.

**Full Changelog:** https://github.com/sageoz/batho/blob/main/docs-site/docs/changelog.md
**Documentation:** https://batho.sageoz.org
**PyPI:** https://pypi.org/project/batho/
