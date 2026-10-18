---
sidebar_position: 100
title: "Changelog"
description: "Batho release history"
---

# Changelog

## v2.0.0 — 2026-10-08

**Graph-accuracy overhaul (T1–T6, T8, T11–T12): receiver-type resolutions now land on real METHOD entities with per-source confidence tiers; unresolved reference stubs are quarantined from default query surfaces; the default ignore list covers all ecosystem lockfiles, sourcemaps/minified bundles, and agent-tool state dirs — with per-build skip reporting and an opt-out; import namespaces are now derived from repo evidence (package markers, manifests) instead of hardcoded `src`/`lib` conventions; `trace_path` traverses a default-deny structural whitelist with deterministic edge-priority tie-breaking; search results are scored by kind-aware ranking; and marker comments/docstrings link to the symbols they explain via `RATIONALE_FOR` edges; and community detection now produces readable, labeled communities — weighted input, isolate/super-hub policies, and split/merge post-processing replace the thousands of mechanical fragments.**

### New Features

- **Receiver-type method resolution (T1)**: `svc.getEntity()`-style member calls now resolve to first-party METHOD entities instead of `unresolved:` ghosts. Type inference gains four new sources — parameter annotations from stored signatures (`graph_svc: GraphService = Depends(...)` — no `extract_parameters` needed), DI-default expressions (`Depends(get_graph_service)`), position-aware assignment flow (`svc = get_graph_service()`; the latest binding at or before the call wins, so reassignment infers correctly), and static/module receivers. Receiver/context capture is language-neutral: Python (`call`), TS/JS/Go/Rust/C++ (`call_expression`), Java (`method_invocation`), and PHP (`*_call_expression`). Assignment bindings record `assigned_to`/`assigned_inner` edge metadata at extraction time.
- **Per-source confidence tiers**: annotated parameter → `receiver_param` (0.90); assignment/DI-default flow → `receiver_assignment` (0.75); hints/self/static/fallback → `receiver_type` (0.65). Tagged on edges and stubs as `resolution_strategy` + `resolution_confidence` / `confidence`.
- **Unresolved-ref quarantine (T2)**: `unresolved:` stubs stay in storage (provenance kept, `include_unresolved=true` restores old behavior exactly) but no longer pollute defaults — `search_entities` excludes them and reports `… N unresolved reference(s) suppressed`, `graph_query` gains `include_unresolved` (default false), `graph_overview` counts resolved entities only (`unresolved_refs` reported separately), and community detection excludes ghosts from clustering input.
- **Default ignore hygiene (T3)**: new built-in patterns — `pnpm-lock.yaml`, `bun.lock(b)`, `deno.lock`, `flake.lock`, `pdm.lock`, `composer.lock`, `packages.lock.json`, `Pipfile.lock`, `conda-lock.yml`, `*.tsbuildinfo`, `*.map`, `*.min.js`, `*.min.css`, `graphify-out/`, `.graphify/`, and agent/tool state dirs (`.cursor/`, `.claude/`, `.codeium/`, `.specs/`). `.gitignore` is always honored additively.
- **`indexer.ignore_defaults`** (default `true`): set to `false` for exotic repos to skip built-in defaults entirely (user patterns + `.gitignore` still apply). Build, `batho patch` change detection, watch mode (including catch-up), and incremental scans all honor the same repo-configured ignore spec — auto-patch can no longer re-index files the build excludes.
- **Skip reporting**: after collection, build logs `ignore_skip_breakdown` (INFO) with counts of paths filtered by built-in defaults vs user/gitignore patterns.
- **Package-root aliasing (T11)**: imports resolve under the namespace the repo actually declares, not the file's directory path. `__init__.py` marker chains detect package boundaries (`backend/app/x.py` imported as `app.x` resolves); `pyproject.toml` (`package-dir`, `packages.find where`), `setup.cfg`, `Cargo.toml`, `go.mod` `module`, and `tsconfig` `baseUrl`/`paths` (`@/*` aliases) are read as evidence; a module-suffix index joins import-path refs to file-path registrations when no marker exists (namespace packages). New resolution strategy `package_alias` (confidence 0.85). The previous `("src", "lib")` directory-name heuristics are removed — no repo-layout names remain in the resolution path.
- **`indexer.package_roots`** (default `[]`): optional user-declared import roots for layouts with no filesystem/manifest evidence (e.g. runtime `sys.path` tricks).
- **External-constructor receivers**: `app = FastAPI()` (or any capitalized external callee) now types the binding as the introspected external class, so `app.include_router()` synthesizes and materializes the external member entity (`fastapi/FastAPI().include_router`) instead of ghosting. DI wrappers keep precedence (`x = Depends(get_svc())` still types `x` from the inner callee).
- **`trace_path` default-deny traversal (T6)**: path expansion is restricted to a whitelist of structural edge kinds (`TRACE_EDGE_PRIORITY`); equal-length paths prefer CALLS > INHERITS/IMPLEMENTS > IMPORTS > READS/WRITES > CONTAINS via priority-sorted adjacency, and `meta.edge_priority` reports the preference order, kinds used, and kinds excluded. Annotation edges (e.g. `RATIONALE_FOR`) can never be traversed — even when shorter — and a `relation_types` filter can only narrow the whitelist. A manifest-driven ground-truth suite (`tests/fixtures/trace_ground_truth.yaml` + checked-in fixture repos for python/ts/rust/go/java) locks endpoint→service resolution into CI.
- **Kind-aware search ranking (T8)**: `search_entities` scores hits deterministically — exact > prefix > substring (regex-only hits score at substring strength), kind boosts (code symbols up, comments/externals down), exported and fqn/path-segment signals, plus a per-language separator hint driven by the hit's language (covers php `\`, go `/`, ts `@/`). Ordering is a stable total order; recall is unchanged (reorder only). The `get_entity` bare-name fallback ranks candidates with the same scorer.
- **Rationale layer (T5)**: marker comments — `WHY:`/`NOTE:` by default, per-language comment syntax (`#`, `//`, `--`, `%`, `/* */`, `(* *)`, `{- -}`) — become `COMMENT_BLOCK` entities, and every comment/doc entity links to its enclosing or immediately-following FUNCTION/METHOD/CLASS via `RATIONALE_FOR` (confidence 0.75; 0.5 when the marker was found by the unverified line-scan fallback). Markdown documents link to modules on unique exact path-segment matches. Tunable via `extraction.rationale_markers` and `extraction.rationale_markers_case_sensitive`. `RATIONALE_FOR` is an annotation edge: excluded from `trace_path` traversal and from community-detection input.
- **Import-specifier resolution (T12)**: relative specifiers (`./x`, `../x`, `/x`) now resolve against the importing file's directory via a new `relative_path` strategy (confidence 0.85) — `./spatial-collision` lands on `src/lib/spatial-collision.ts`. Manifest names strip PEP 508 extras at parse (`uvicorn[standard]` → `uvicorn`, so the package actually introspects). Rust/Ruby `::`-style stdlib names register dot-normalized aliases, making existing table coverage (`std::io::Read`, `std::io::Write`) reachable. Extraction noise dropped: brace-group literals (`{Read, Write}`) and scoped-package leaf candidates (`@tauri-apps/plugin-dialog` → `plugin-dialog`) no longer emit doomed stubs.
- **Community labels + pruning (T4)**: clustering input is now weighted (`community_detection.edge_weights` per kind × call-site multiplicity × confidence; CONTAINS defaults to 0 — file layout no longer drowns coupling), degree-0 entities attach post-hoc to their file/directory's majority community, super-hubs above the P99 degree percentile are dropped and reattached by shared weight, oversized communities re-cluster recursively, and small ones merge into their strongest neighbor or flag `is_singleton`. Every community gets a deterministic `heuristic_label` (dominant non-generic directory → c-TF-IDF tokens → common identifier affix → hub name), and `graph_overview` shows the top-12 labeled communities with one-line descriptions plus a "N smaller communities" aggregate.
- **Generated plugin pipeline (batho-calibrate)**: repository-specific `bsg-plugin.v2` files can be generated into `.batho/plugins/` (new `rules.custom_rules_dir` — each file fingerprinted into the rules config and into the AST cache variant, so plugin changes invalidate correctly), validated with `batho plugins validate`, and retro-applied to an existing artifact with `batho plugins apply` — full rule-set re-enrichment (metadata + semantic overlay) without re-extracting files.
- **Quarantine metadata + filters**: rules can stamp `bsg.noise`/`bsg.quarantined`; `search_entities` and `graph_query` exclude quarantined entities by default with an `include_quarantined` opt-in and report the suppressed count; `graph_overview` and community detection exclude them unconditionally (`graph_overview` reports `quarantined_entities`). Entities stay in storage — exclusion is a view concern.
- **Tag-driven edge derivation (annotation layer)**: plugin-applied tags/metadata now materialize annotation edges — `metadata["bsg.edge_hints"]` resolves declarative targets (entity id / fqn / name pattern, annotation types only, per-source cap), `bsg.semantic_family` produces directory-bounded `SEMANTICALLY_SIMILAR_TO` edges (top-K by name-token overlap), and test naming conventions (`test_<stem>`) mint `TESTED_BY` edges boosted by existing call/import affinity. All carry `edge_class: "annotation"` + INFERRED confidence and are excluded from structural clustering and `trace_path` by construction.
- **Rule telemetry (`rule-stats.v1`)**: build, patch, and `plugins apply` write a per-run `rule_stats` record into the `run_artifacts` IPC table — `rules_fingerprint`, `run_kind`, `rule_hits`, `plugin_hits`, `rule_perf`, `plugin_files` — enabling longitudinal fitness scoring of generated plugins (opt-out via `artifact_blobs.run_artifacts.rule_stats`).
- **`batho-calibrate` agent skill** (`.devin/skills/batho-calibrate/`): every `batho build`/`patch` now writes an `enrich_profile` gap report (noise/ghost/category/service-tag/fan-in/community stats with suggested rule shapes) and an `enrich_score` rule-fitness report (promote/shadow/regenerate/disable/stale verdicts from `rule_stats` history) into `run_artifacts`, plus human-readable `.batho/report/overview.md` + `.batho/report/score.md`. `batho plugins validate` runs the two-stage acceptance (schema + deterministic fixture gate on real sampled entities) for a single file, a directory, or — with no path — every `*.yaml`/`*.yml` in `.batho/plugins/`. The skill itself is script-free — it reads reports and calls CLI verbs only.
- **Community hierarchy + optional LLM labels**: recursive community splits now persist `parent_id`/`level` (domain → community → sub-community when `community_detection.domain_grouping` groups by `bsg.domain`/`service_tag`/`category` first). `batho communities label` optionally writes `llm_label`/`label_source`/`label_input_hash` via a configured LLM — compile-time only, hash-gated incremental re-labeling, `heuristic_label` fallback preserved (`community_detection.llm` + `BATHO_LLM_API_KEY`; off by default). `batho communities list --tree` renders the hierarchy.
- **`batho install` — one-command agent setup (replaces `batho skills`)**: installs the Batho skill pack (`batho`, `batho-setup`, `batho-specs`, `batho-execute`, `batho-review`, `batho-calibrate`) AND registers the Batho MCP server with every detected coding-agent client in a single invocation. Skill pack: fetched checksum-verified from batho-skills releases, installed to `~/.agents/skills` (vendor-neutral path covering Cursor, Copilot, Codex, Gemini CLI, OpenCode, Devin) plus native mirrors for detected agents. MCP registration merges the stdio server entry (`batho mcp`) into each detected client's config — `claude-desktop` (`claude_desktop_config.json`), `claude-code` (`~/.claude.json` user scope), `cursor` (`~/.cursor/mcp.json`), `windsurf` (legacy `~/.codeium/windsurf/mcp_config.json` + Cortex `~/.config/devin/mcp_config.json`), `vscode` (user-profile `mcp.json`, top-level `servers` key), `codex` (`~/.codex/config.toml` `[mcp_servers.batho]` TOML), `gemini` (`~/.gemini/settings.json`), `opencode` (`opencode.json` `mcp` key with argv-array command), `copilot` (`~/.copilot/mcp-config.json`). Merge-not-clobber (only the `batho` key is touched), atomic tmp+rename writes, per-file error isolation, idempotent re-runs (`installed` → `updated`); re-running `batho install` also updates a drifted pack. Flags: `--agent NAME` (repeatable; skills-only agents like `roo` install skills with an MCP note), `--all`, `--project`, `--version V`, `--copy`, `--force`, `--no-mcp`. Global scope only — no project files written. Per-client config surfaces live in `agent-paths.json` schema v2 (`mcp_agents` section) alongside the skill-path table. Auto-sync on `batho mcp` start unchanged (opt out via `skills.auto_install: false`; pin via `BATHO_VERSION`).
- **Watcher v2 — git-sentinel engine**: the MCP watcher now triggers auto-patch on git-operation boundaries (index/HEAD/ref settle via a `.git` sentinel watcher) instead of raw file-event floods, with a `vcs_op_in_progress` hold that defers patches while git mutations are in flight. Tunable via `watch:` config — `mode` (`auto`/`fs`/`off`), `max_staleness_ms`, `flush_threshold`, `git_settle_ms`, `vcs_op_hold_ms`. `watch.mode: off` still tracks state for staleness banners without auto-patching.
- **`indexer.strict_hashing`** (default `false`): when enabled, `batho patch` change detection SHA-256-hashes every tracked file on every run; when disabled, the mtime/inode/size fast-path in `IncrementalEngine.scan_changes` is used (`BATHO_STRICT_HASHING`).
- **`indexer.file_changelog_max_runs`** (default `100`, ≥1): cap on `file_changelog` rows retained per file across patch runs (`BATHO_FILE_CHANGELOG_MAX_RUNS`).

### Changed

- **`plugins.reextract_on_drift`** (default `true`): `batho patch` now escalates to a full-repo re-extraction when the plugin fingerprint drifts from the previous run, instead of only warning — unchanged files no longer keep entities stamped by an outdated plugin set. Escalated runs log `patch_drift_escalation` (tracked/scanned counts), resolve `bsg.parallel.max_workers` for extraction, and record the current fingerprint so the next patch settles. Set `reextract_on_drift: false` to restore warn-only behavior.
- **AST cache variant now includes the rules fingerprint**: any change to plugin files under `rules.custom_rules_dir`, `disabled_rules`, `builtin_plugins`, or `plugins.overrides` produces a new cache variant — stale rule-enriched entities can no longer be served from cache. Expect a one-time fleet-wide cache invalidation on the first build after this lands (correct behavior, not a bug).
- **AST cache schema bumped to `v4`**: hollow-topology entries now carry `signature`/`start_line`/`end_line` so receiver-type resolution works on cached results and `batho patch` produces identical resolution to a full build.
- `test_e2e_watcher_auto_patch` and other watch flows use the repo-aware ignore spec (`_repo_ignore_spec`); watcher falls back to defaults + `.gitignore` if config loading fails.
- **Breaking: `batho diff` renamed to `batho history`** (no alias kept): bare invocation now lists recent runs newest-first (`--last N`, default 10); `--run`, `--entity`, `--file`, `--since`, and `--json` keep their previous semantics — `--entity`/`--file` additionally accept `--last` (default 10). The MCP tool `batho_diff` is renamed `batho_history` (same parameters; clients allowlisting tool names must update).
- **`file_changelog` rows now store `file_path`**: history entries survive file deletion (`batho history --file` works on deleted files, and delete+recreate no longer splits history across `file_id`s). The patch flow records `removed` node rows *before* deleting tracking rows — removals for deleted files were previously never written to the changelog.
- **Plugin architecture migration**: the BSG rule engine and built-in rule YAMLs moved into the `batho-plugin-sdk` workspace package (`batho_plugin.rule_engine`, `batho_plugin/core/`); `batho.modules.compression` re-exports the public API via a deprecated lazy shim. Extraction decisions (language detection, marker/property classification, stub pruning, language stamping) now dispatch through a `PluginHost` stage pipeline; `--no-plugins` (`batho build --no-plugins`) runs the compiled-in fallbacks with `plugin_fingerprint` absent from run artifacts.
- **Breaking change (opt-in interceptors)**: the 9 security/quality interceptor plugins moved to the external pack and are now **off by default** — enable them via `plugins.external.enabled: true` (optionally narrowed by `plugins.external.select`, which matches file stems or plugin_ids). `rules.builtin_plugins` only resolves core-pack stems; listing interceptor stems without enabling the external pack produces `Unknown built-in rule plugin` warnings.
- **Behavior change (entry-point names)**: the rule pipeline no longer renames `ENTRY_POINT` entities to `__main__` after rule application. The `normalize_entry_point` action still detects `if __name__ == "__main__":` entry points and stamps `bsg.normalized_name` + `invocation_snippet` metadata, but the post-rule entity rename was removed (spec risk register: deferred; the capability stays declared-unused until the SDK schema rework) so entity names remain stable across rule changes. Entry-point names produced by v1.4.3 builds will differ from v2.0.0 builds.

## v1.4.3 — 2026-09-20

**Universal dependency introspection (19 managers) and the skip-when-env-missing policy; pytest-style progress bars for `batho build` and `batho patch`; fully pinned dependency set and fastmcp 3.4.7 for deterministic installs.**

### New Features

- **Real introspection for every manager with an offline install store**: 12 new introspectors — Ruby gems (`GEM_HOME` → `gem env gemdir`), PHP/Hack composer (`vendor/` + PSR-4 namespace-qualified classes), NuGet (XML doc `T:` members, `.nuspec` fallback), Dart pub (`.dart_tool/package_config.json` — dart's own resolution — with `PUB_CACHE` fallback), Julia (depot `export` lists), R/CRAN (renv library / `R_LIBS_USER`, `NAMESPACE` `export()` directives), Haskell cabal (`exposed-modules:`, `ghc-pkg` fallback), Swift SPM (`.build/checkouts`, `public`/`open` only), Zig (vendored `.zigmod/deps` + global cache matched by `build.zig.zon` `.name`), Erlang rebar3 (`-export([...]).` lists), OCaml opam (`.mli` interfaces), Lua luarocks (rock trees), Perl cpan (local::lib `.pm`).
- **Gradle store support in jar introspection**: `introspect_jar` now searches `~/.gradle/caches/modules-2/files-2.1` in addition to `~/.m2`, with binary-jar entry-name parsing when no `-sources` jar exists — Kotlin/Scala/Java deps declared via Gradle are introspectable.
- **Skip-when-env-missing policy** (default on, `dependency.introspection.skip_missing_env`): when a dep's environment (venv, `node_modules`, `vendor/`, user package store) cannot be found, the dep is skipped — no introspection attempt, no fallback `{name: [name]}` stub symbols, no cache write. `deps_skipped_no_env` / `deps_no_symbols` / `deps_no_ecosystem` counters in build stats (`dependency_index_complete`), one warning per manager with a fix hint. `skip_missing_env: false` restores legacy best-effort behavior.
- **`full_scan` contract formalized** — the single explicit switch for declared-dep introspection: `true` attempts every declared dependency (subject to the env-skip policy and no-ecosystem classification); `false` attempts only popular-DB members. The per-dependency gate chain is pinned (① cache → ② popular → ③ managers → ④ route → ⑤ env → ⑥ introspect) with a **completeness invariant**: every unique declared dep reaches exactly one terminal bucket (`deps_unique == cached + gate_dropped + manager_disabled + no_ecosystem + skipped_no_env + introspected + no_symbols`), asserted after every run (log-only `introspection_accounting_mismatch` warning). New stats: `deps_unique`, `deps_gate_dropped`, `deps_manager_disabled`; `dependency_gate_drops` log line with a "set full_scan: true" hint when the popular gate drops deps.
- **Python never introspects the wrong interpreter**: `introspect_python` lost the `sys.executable` fallback — only the project venv's python binaries are used; a venv-less project is skipped (configurable via the policy above).
- **Per-manager introspection toggles** (`dependency.introspection.managers`, e.g. `{gem: false}`); unknown manager keys warn and are ignored.
- **Env-resolution matrix**: declarative per-manager environment resolution (project-scoped walk-up markers vs user-level store env-var → home default → glob fallbacks), memoized per (manager, manifest dir), shared by the skip policy and the introspectors.
- **No-ecosystem classification**: `bash`, `verilog`, `c`, `cpp`, `objc`, `agda` deps are explicitly classified (`deps_no_ecosystem`, debug log) instead of falling through stub branches; `hack` deps route through the composer introspector. A routing table maps every language → introspector (or `None`).

### Changed

- **`{name: [name]}` fallback stubs removed** from `_introspect_dep` and `introspect_jar` — stubs inflated I2 metrics with unresolvable package-name symbols.
- **Resolution cache version bumped** (`v3:` hash prefix, now including the declaring manifest-dir scope) so previously-cached fallback stubs are invalidated on first run.
- **Phase progress display**: `batho build` and `batho patch` now render phase-level progress on stderr in pytest's `[ NN%]` style — `  extract   [ 45%] 645/1432` — with one completion line per phase and a one-line final summary (`✓ built in 42.3s — 312 files · 1542 entities · 4823 relationships`). The live bar appears only for phases longer than 2 seconds and is transient (erased on completion), keeping terminal logs clean.
- **Graceful non-TTY degradation**: when stderr is not a terminal (pipes, CI), no animation is rendered — one completion line per phase instead, with a keep-alive line every 60 s for long phases so CI log viewers never look frozen. `NO_COLOR` disables color but keeps the bar (per the NO_COLOR standard).
- **`--no-progress` flag** on `build` and `patch`, plus the `BATHO_NO_PROGRESS=1` environment variable (strict parsing: only `1`/`true`/`yes` disable — unlike `TQDM_DISABLE`, `"0"` does not). Native `TQDM_DISABLE` / `TQDM_MININTERVAL` / `TQDM_MINITERS` overrides pass through for power users.
- **`progress:` config section** in `batho.yaml`: `enabled`, `style` (`progress` | `classic`), `mininterval_s`, `show_after_s`, `keepalive_s`.
- **Parent-process-only progress hooks**: the extraction pipeline exposes a `progress_callback` invoked once per completed file result in the parent process; worker processes (spawn-context `multiprocessing.Pool`) never touch the bar. A failing progress callback can never break a build or patch.
- **Log interleaving safety**: while a bar is active, structlog output (routed through stdlib logging) is emitted via tqdm's write mode, which clears and redraws the bar instead of corrupting it.
- **Build/patch success summaries** restyled to one line: `✓ built in 42.3s — 312 files · 1542 entities · 4823 relationships` (was `Built /path: N entities, N relationships, N files in Nms`).
- **New dependency**: `tqdm>=4.66` (zero runtime dependencies off Windows, ~80 KB wheel, ~60 ns/iteration documented overhead, wall-clock regression guard). A benchmark guard asserts progress overhead stays under 10% of build wall-clock (design budget: 1%); it runs only where the measurement is meaningful — skipped under coverage tracing and on CI, where the tracer's overhead dominates and the per-test timeout can fire mid-build.

### Dependencies & Packaging

- **All dependencies pinned to exact versions (`==`)**: 18 runtime, 6 test, and 8 dev dependencies, plus the `hatchling` build requirement. Fresh `uv tool install` / `pip install` resolutions are now fully deterministic — upstream releases can no longer change Batho's behavior until a new Batho release deliberately bumps the pins. (Lockfiles do not ship inside wheels, so pins in `pyproject.toml` are the only author-controlled constraint on what `uv tool install` resolves.)
- **`fastmcp==3.4.7`** (was `>=3.4.0`, which resolved to the breaking fastmcp 4.0.x on fresh installs): fastmcp 4.0 removed the `fastmcp.tools.tool` module, crashing `batho mcp` at import time. 3.4.7 is the maintained 3.x head and carries security backports — SSRF via NAT64/6to4/Teredo transition addresses, a DNS-rebinding Host/Origin guard, and JWT/OAuth fixes — that 3.4.2 predates.
- **fastmcp 4.x-ready imports**: `batho.mcp.tools` and `batho.mcp.errors` now import `ToolResult` from the canonical `fastmcp.tools` package instead of the removed `fastmcp.tools.tool` deep path. The canonical path works on both fastmcp 3.4.x and 4.x, so the import layer of any future 4.x migration is already in place.

### Fixed

- **Config loader tolerates explicit `null` values in `batho.yaml`**: `_merge_config` now treats an explicit YAML null as "not set" and keeps the schema default, instead of copying the `None` into the config dict and failing pydantic validation. Symptom: a `batho.yaml` written by v1.4.3 (`dependency.stdlib.languages: null`, as produced by `batho.yaml.example` and default config dumps) crashed every batho command on the v1.4.2 model with `RuntimeError: Invalid Batho configuration in 'batho.yaml': dependency.stdlib.languages — Input should be a valid list` before any work ran (reported in CI via the composite action). Blank hand-edited values (`key:` with no value) get the same graceful fallback. Workaround while pinned to v1.4.2: delete the `languages: null` line or set an explicit list — or upgrade to v1.4.3.
- **Path-containment guard no longer rejects symlinked repo roots**: the artifact/cache/bsg path sanitizer compared each resolved config path against the *unresolved* `root_dir`, so a repository root reached through a symlink (macOS `/tmp` → `/private/tmp`, CI workspace symlinks) raised a false `PathSecurityError: Unsafe config path ... escaping repository root` for perfectly ordinary relative paths like `.batho/artifact`. The root is now resolved once and used for both path joining and containment checking; genuine escapes (symlinks pointing outside the repo) are still rejected.

## v1.4.2 — 2026-09-08

**MCP relationship filtering (symbol roles, confidence, direction), entity categories and PROPERTY extraction, the `file_connectivity` tool, stub-based cross-file traversal, and unambiguous stub IDs.**

### New Features

- **`symbol_roles` filter in MCP tools**: `graph_query`, `trace_path`, and `search_entities` now accept a `symbol_roles` parameter to filter relationships by `SymbolRole` bitmask (Definition, Import, WriteAccess, ReadAccess, Generated, Declaration, Dynamic, Heuristic). Role names are case-insensitive; OR semantics within the parameter, AND semantics across filters.
- **`confidence_threshold` filter in MCP tools**: `graph_query` and `trace_path` now accept a `confidence_threshold` parameter (0.0–1.0) to filter edges by resolution confidence. Exposes the existing 8-tier confidence scoring system directly to AI agents.
- **`relation_direction` parameter in MCP tools**: `graph_query` and `trace_path` now accept `relation_direction` (`outgoing`, `incoming`, `both`) to filter by edge direction. `incoming` enables "who calls X?" queries without requiring inverse relationship types (`CALLED_BY`, `IMPORTED_BY`, etc.), paving the way for their deprecation in Phase 3.
- **Ambiguous resolution detection**: When the graph builder finds multiple equally-plausible target candidates, the edge is emitted with `confidence=0.5`, `metadata.ambiguous=True`, and `metadata.ambiguous_candidates=[...]` instead of being silently dropped. Ambiguous edges are preserved for manual review and are never pruned. A new `ambiguous: 0.50` tier was added to `_RESOLUTION_CONFIDENCE` (now 8 tiers).
- **`ambiguous_edge_count` in `graph_overview`**: The `graph_overview` tool now reports the count of ambiguous edges in its stats, computed via Arrow substring pre-filtering for performance.
- **`EntityCategory` enum** (T01): New 5-value enum (`CODE`, `EXTERNAL`, `INFRASTRUCTURE`, `MARKUP`, `STRUCTURAL`) that groups `EntityType` values into coarse categories. Every `EntityType` now has a `.category` property. Enables category-level filtering without listing 20+ individual types.
- **4 new `EntityType` values** (T02): `CONSTRUCTOR` (OO constructors — Python `__init__`, Java/C# `constructor_declaration`, TypeScript `constructor`), `ENUM_MEMBER` (Rust `enum_variant`, C# `enum_member_declaration`), `PARAMETER` (function/method parameters — opt-in), `TYPE_PARAMETER` (generic type parameters T, K, V — opt-in). All 4 are in the `CODE` category.
- **`PROPERTY` extraction** (T03): Python `@property` and `@x.setter` decorated methods are now extracted as `PROPERTY` (not `METHOD`). Setters get `metadata.access_type="write"`, getters get `"read"`. TypeScript `get`/`set` accessors and C# auto-properties are also extracted as `PROPERTY`. Fixed pre-existing C# query compilation bugs (`base_clause`, `accessibility_modifier` invalid node types).
- **`entity_categories` filter in MCP tools** (T07): `graph_query` and `search_entities` now accept `entity_categories: list[str]` to filter by category name (case-insensitive). Expands to member `EntityType` values and combines with `entity_types` using OR semantics. Example: `graph_query(entity_categories=["code"])` filters to all 18+ code symbol types in one parameter.
- **`entity_categories` in `batho://schema` resource**: The schema resource now includes `entity_categories` with their member entity types for MCP client discoverability.
- **`file_connectivity` MCP tool** (T21): File-level dependency connectivity in both directions. Cross-file references (stored as unresolved stubs) are resolved to their defining files and aggregated per file with relation-type counts and confidence. Supports `direction` (`outgoing`/`incoming`/`both`), `include_external`, and `min_confidence` parameters. Default-enabled.
- **READS/WRITES relationship types** (T09): `ref.read` and `ref.write` captures now emit `READS`/`WRITES` relationship types instead of the legacy `REFERENCES` type. Legacy `REFERENCES` edges are reclassified to `READS`/`WRITES` by their `SymbolRole` on every construction path (model validator), so old artifacts load with correct types.
- **Deprecated inverse relationship types** (T15): `CALLED_BY`, `IMPORTED_BY`, `REFERENCED_IN`, and `CONTAINED_WITHIN` are deprecated — use the forward type (`CALLS`, `IMPORTS`, `READS`, `CONTAINS`) with `relation_direction="incoming"` instead. Legacy edges are reclassified (forward type + swapped endpoints, `metadata.reversed=true`) on model construction **and** on the MCP raw-row read path (`graph_query`, `get_entity`, `get_file_graph`, `trace_path`, `file_connectivity`), so fresh and legacy artifacts behave identically. `relation_types=["CALLS"]` now matches legacy `CALLED_BY` rows.
- **Stub-based cross-file traversal** (T20): `graph_query` and `trace_path` resolve `unresolved:` stub targets to their defining files/entities, so cross-file references participate in direction filtering and BFS path tracing without a rebuild.
- **Indirect call detection** (T10): Bare-identifier indirect calls (`map(func, xs)`) emit `CALLS` edges with `confidence=0.7` and `metadata.indirect=True`, with soundness guards: parameter/local shadowing suppresses false edges, and same-named callables are disambiguated by caller scope (ambiguous names emit no edge).
- **`entity_types` filter case-insensitivity**: `graph_query` and `search_entities` normalize `entity_types` values to uppercase, matching the existing `relation_types` and `entity_categories` behavior (`entity_types=["function"]` now works).
- **`batho://schema` deprecated types**: The schema resource now lists `deprecated_entity_types` and `deprecated_relation_types` for the T14/T15 deprecation contract.
- **Dot-normalized stub ref keys**: Contextual stub IDs (`unresolved:<caller_scope>::<ref_key>`) now dot-normalize the ref key (`::` → `.`), so the `::` scope separator is unambiguous for languages whose reference text contains `::` (Rust paths like `std::io::Write`, Ruby constant paths like `Foo::Bar`). Display names and metadata keep the caller-written spelling.
- **Rust std roots in the stdlib bucket**: `core`, `alloc`, and `proc_macro` join `std` in the resolver's stdlib prefixes. The module-index longest-prefix match runs first, so an indexed local module with one of these names always wins.

### Extraction

- **Kotlin query rewrite**: The Kotlin query was rewritten with positional captures (the grammar has no `name` fields — field-name references silently disabled the whole query). Adds `object_declaration` coverage for methods and properties, enum-entry (`ENUM_MEMBER`) capture, and interface reclassification (`interface X` now yields an `INTERFACE` entity instead of `CLASS`).
- **Contextual stubs are `EXTERNAL_SYMBOL`** (T13): Unresolved cross-file reference stubs are emitted as `EXTERNAL_SYMBOL` entities with a stable `unresolved:` entity-ID prefix (the `UNRESOLVED` entity type is deprecated). Legacy `UNRESOLVED` entities are remapped to `EXTERNAL_SYMBOL` on deserialization (T14, along with `ATTRIBUTE`, `GLOBAL_STATEMENT`, `IMPORT_BLOCK`).

### Storage

- **New Arrow IPC columns**: `rels_views` table now includes `roles` (int32) and `confidence` (float32) columns, both nullable for backward compatibility with older artifacts. The writer populates them with `int(rel.roles)` and `float(rel.confidence)` respectively (defaulting to 0 and 1.0 when absent).

### Configuration

- **`extraction.extract_parameters`** (default: `false`): Opt-in flag to extract function/method parameters as `PARAMETER` entities. Disabled by default to avoid entity-count inflation.
- **`extraction.extract_type_parameters`** (default: `false`): Opt-in flag to extract generic type parameters as `TYPE_PARAMETER` entities. Disabled by default.
- Both flags are documented in `batho.yaml.example` and `docs-site/docs/getting-started/configuration.md`.

### Performance

- **Arrow compute filters in `trace_path`**: `symbol_roles` and `confidence_threshold` filters are applied via `pc.bit_wise_and` and `pc.greater_equal` before materializing to Python, avoiding full-table `to_pylist()` on large repos.
- **Substring pre-filter for ambiguous count**: `graph_overview` uses `pc.match_substring(metadata_json, '"ambiguous"')` to narrow candidates before JSON-parsing only the matched subset.
- **Lazy ambiguity detection**: Ambiguity is detected via a cheap set-difference on pre-computed candidates — no re-resolution needed. Zero overhead in lazy mode (stubs resolved on-demand).
- **EndpointResolver column projection**: Index building projects only the needed Arrow columns (`entity_id`/`file_id`/`name`; `file_id`/`target_id`/`relation_type`/`confidence` for cross-file edges) and pre-filters CONTAINS rows via Arrow compute instead of full-table `to_pylist()` per generation.
- **graph_overview stub count**: The "External dependencies significant" pattern counts contextual stubs via an Arrow `starts_with` filter on the `unresolved:` entity-ID prefix (the legacy `UNRESOLVED` type key is always 0 in new artifacts).

### Bug Fixes

- **Parsing config propagation** (`c46e8dc5`): `ASTExtractor` now has a `set_parsing_config()` method, and `registry.set_parsing_config()` updates already-cached extractor instances. The pipeline (`codegraph.py`) now wires `ExtractionConfig.extract_parameters` and `extract_type_parameters` into the parsing config dict. Previously, these flags were never applied in production builds (only in direct `create_extractor()` unit tests).
- **C# query compilation**: Fixed invalid `base_clause` and `accessibility_modifier` node types in `CSHARP_QUERY` that caused silent query compilation failures.
- **AST cache variant consistency** (`dc2f0e61`): `index_file` now derives its AST cache variant from the same merged parsing config (bsg.parsing + extraction flags) as the parallel pipeline, so flags-ON entries can never be served to a flags-OFF build.
- **Arrow store stub exclusion** (`83e6c290`): Dangling-reference resolution no longer resolves names to `unresolved:`-prefixed stub entities.
- **Rust/Ruby scoped refs resolve correctly**: Scoped ref text no longer collides with the stub-ID separator — stdlib refs such as `std::io::Write` now classify as `external_stdlib` (root `std`) instead of landing in `unresolved_stubs`, and scope-aware name fallbacks retain module context. Legacy artifacts keep their previous (last-segment) behavior until a rebuild.
- **Single stub-ID parse helper**: All stub-ID `::` parsing now flows through `stub_fqn()` in `entity_resolution.py`; `file_connectivity`'s stdlib extraction and the arrow-store blob patcher share the same semantics (the legacy `split(":")[1]` probe compared the caller *scope* and could never match a scoped stub).
- **`file_connectivity` `via` is direction-aware**: `depends_on` cells name the referenced (remote) symbol; `depended_on_by` cells name the referencing (caller-side) symbol. The markdown renderer now actually renders `(via ...)` — it previously read a non-existent top-level `via` key and never showed one.

### Documentation

- Updated `mcp/tools-reference.md` with new parameters for `graph_query`, `trace_path`, `search_entities`, and a new "Relationship Filtering" section documenting symbol roles, confidence tiers, and direction filtering.
- Updated `mcp/index.md` Tool Matrix with new filter parameters.
- Updated `whitepaper/code-graph.md` confidence scoring table with the `ambiguous: 0.50` tier and ambiguous resolution behavior.
- Added `file_connectivity` to the MCP tool matrix and tools reference; tool counts updated to 20 total (16 default-enabled).
- `mcp/tools-reference.md` `file_connectivity` entry documents the direction-aware `via` semantics and the `external.stdlib` root extraction.
- `whitepaper/code-graph.md` documents the stub-ID format (`unresolved:[<pkg> ]<caller_scope>::<dotted_target_fqn>`) with the dot-normalization and legacy-artifact notes.

### Tests

- **1314 tests** (up from 1052). Added `test_symbol_roles_e2e.py` (16 tests), `test_confidence_threshold_e2e.py` (16 tests), `test_relation_direction_e2e.py` (13 tests), `test_t02_entity_types.py` (12 tests), `test_t03_property_extraction.py` (15 tests), `test_t07_entity_categories.py` (19 tests), `test_file_connectivity.py` (18 tests), `test_entity_resolution.py` (27 tests), `test_review_fixes.py` (13 tests), `test_review_round2_fixes.py` (22 tests), `test_review_round3_fixes.py` (16 tests), `test_review_round4_fixes.py` (12 tests), `test_stub_ref_key.py` (10 tests), `test_phase2_schema_upgrade.py` (28 tests), and `test_language_capture_parity.py` (20 tests); added `TestStubFqn` / `TestRustStdlibStubs` in `test_entity_resolution.py` and `TestStubTargetMatches` in `test_bsg_scratch_store.py`; extended `test_graph_query.py`, `test_graph_overview.py`, `test_phase4_pruning_confidence.py`, `test_phase5_performance.py`, and `test_rust_go_contains.py`.

---

## v1.4.1 — 2026-08-26

**File watcher engine, registry v2/v3 schema, MCP tool gating, 9 new lifecycle tools, networkx migration, review hardening, thread safety, path sanitization, atomic writes, and performance optimizations.**

### New Features

- **File watcher engine** (`batho/mcp/watcher.py`): `BathoWatcherEngine` monitors watched repositories for filesystem events using `watchdog`, debounces rapid changes, and triggers automatic `batho patch` runs. Configure per-repo via `add_repo(watch=true, debounce_ms=2000)`.
- **Registry v2/v3 schema**: `RepoEntry` now includes `id` (uuid4 hex), `mode` (`local` | `github`), `branch`, `status` (`not_indexed` | `indexing` | `ready` | `stale` | `error`), `last_built_at`, and `created_at` fields. v2 entries are auto-migrated on load: stable IDs generated, status derived from on-disk artifact, migration persisted. Added `get_by_id()` and `update_status()` registry methods for dashboard keying and build lifecycle tracking.
- **MCP tool gating** (allowlist/blocklist): Secure-by-default tool registration — 4 admin tools (`batho_build`, `batho_export`, `batho_load`, `batho_gc`) are disabled by default. Enable via `batho.yaml` (`mcp.tools.disabled: []`), `mcp.tools.enabled` allowlist, or `--enable-tool` CLI flag. See [Tool Gating](/docs/mcp#tool-gating).
- **9 new lifecycle MCP tools**: `batho_status`, `batho_list_runs`, `batho_diff`, `batho_patch`, `batho_fix` (default-enabled) + `batho_build`, `batho_export`, `batho_load`, `batho_gc` (opt-in). Total tool count: 19 (15 default + 4 admin).
- **networkx replaces leidenalg/igraph**: Community detection migrated from `leidenalg`/`igraph` (GPL/non-Apache licenses) to `networkx` greedy modularity clustering for Apache-2.0 license compatibility.

### Bug Fixes

- **Watcher engine deadlock** (`d484150`): `BathoWatcherEngine.stop()` could deadlock when the observer thread was actively processing an event. The observer's dispatch lock and `self._lock` could form a classic deadlock. Fix: pop the watch entry and cancel the debounce timer under the lock, but stop/join the observer outside the lock.
- **Thread safety in graph mutations**: `InMemoryGraph._lock` upgraded from `Lock` to `RLock`; `remove_entities_for_file` and `add_entities_for_file` now wrap mutations in `with graph._lock:` for atomic multi-entity updates without deadlocking.
- **Path sanitization in MCP tools**: Replaced naive `str.replace("\\", "/")` with `_canonicalize_untrusted_path()` in `graph_overview`, `graph_query`, `get_file_graph`, and `batho_diff` for proper canonicalization per the path sanitization ADR.
- **Config validation fail-fast**: `get_config_with_root` now raises `RuntimeError` on invalid config instead of silently backing up and overwriting the user's `batho.yaml`.
- **Atomic resolution cache writes**: `ResolutionCache` metadata writes now use `tempfile.mkstemp` + `os.replace` to prevent cache corruption on interruption.
- **AST cache mtime invalidation**: `AstCache.get` now accepts an optional `mtime` parameter to detect stale entries even when content hash matches.
- **Unicode identifier extraction**: `extractor.py` and `fallback_parser.py` regexes updated from `[a-zA-Z_]` to `[^\W0-9]` for PEP 3131 compliance, preserving non-ASCII identifiers.
- **Case-insensitive XML entity detection**: `manifest_parser.py` now uppercases content before checking for `<!ENTITY`/`<!DOCTYPE`, matching XML's case-insensitive grammar.
- **Unified cache field types**: `is_indexed` changed from `int` to `bool`; `last_run_id` renamed to `last_run_uuid` to match the actual schema.
- **Bundle reader zero-copy preservation**: Removed redundant sort in `BathoBundleReader` (writer already sorts by `file_id`); index now handles non-contiguous `file_id` ranges with multi-slice support.
- **Blob repairer memory**: `blob_repairer.py` now uses `pa.ipc.new_file` with a table directly instead of `to_pylist()`, avoiding unnecessary row materialization.
- **Tool removal fix**: `remove_repo` now uses `app.local_provider.remove_tool()` instead of `app.remove_tool()` for correct FastMCP cleanup.

### Security Hardening

- **Tamper-evident audit log**: `FixContext` audit entries now include `previous_hash` and `hash` fields forming a SHA-256 chain, enabling tamper detection.
- **Security audit flag gating**: BSG plugin hit collection in `apply_bsg_rules_to_entities` is now guarded behind `security_audit_enabled`, avoiding unnecessary work when the flag is off.

### Performance

- **Early stream cleanup**: `store.cleanup_streams()` moved before community detection in `build.py` to free memory earlier in the pipeline.
- **Hot path optimizations** (`19ac506`):
  - FIX 3: Cache per-file variable→type mappings in `resolve_contextual_stubs` to avoid O(E) re-scans per stub.
  - FIX 9: Replace O(M) method scan per Rust impl block with `bisect_left` + forward scan (O(log M + k)).
  - FIX 10: Precompute per-file import lookup structures (`from_symbol_to_module` dict, `non_from_modules` list, `imported_names` set) once instead of O(I) scan per reference node.
  - FIX 15: Pre-lower content patterns at `RuleMatch` construction to avoid repeated regex compilation.

### Other Changes

- `schema_version` in `Config` now uses `Literal["batho-config.v1"]` for stricter validation.
- Python version capped to `<3.14`; `watchdog` minimum relaxed to `6.0.0`.
- Added error `hint` parameters to `_err()` calls in `batho_export`, `batho_diff`, `batho_gc`, and `batho_fix` MCP tools.
- Documentation: added `graph`, `community_detection`, and `memory` config sections; documented `watch`, `debounce_ms`, `max_file_size_kb` params for `add_repo`.
- Added `CITATION.cff` to the bump-version script's file list for future releases.
- Fixed `CHANGELOG_PATH` `NameError` in `generate_changelog_entry.py`.
- **1052 tests** (up from 864).

---

## v1.4.0 — 2026-08-04

**Stdlib expansion, graph builder phases 4-5, BSG interceptors, and security/performance hardening.**

### New Features

- **Stdlib expansion to 27 languages**: Standard library symbol tables now cover 27 languages (up from 5), including C/C++, Java, Ruby, C#, PHP, Kotlin, Swift, Scala, Dart, Haskell, Lua, R, Perl, Julia, Zig, Bash, Objective-C, Erlang, OCaml, Hack, and Verilog.
- **Multi-ecosystem dependency introspection**: Live introspection now supports five package ecosystems — Python (venv), npm (`node_modules/`), Cargo (`~/.cargo/registry/`), Go modules (`~/go/pkg/mod/`), and Maven (`~/.m2/repository/`) — with package-name validation on all ecosystems to prevent path traversal.
- **Graph builder Phase 4 — Confidence scoring**: Every resolved stub is tagged with a `resolution_confidence` score (0.0–0.95) and `resolution_strategy` label across 6 tiers, enabling downstream consumers to filter by confidence level.
- **Graph builder Phase 4 — Conservative pruning**: Unresolved stubs targeting common stdlib method names on unknown receiver types are pruned instead of left as false gaps, reducing graph noise.
- **Graph builder Phase 5 — Receiver-type inference**: Method calls are resolved by inferring the receiver variable's declared type from scope, following the rust-analyzer two-phase resolution pattern.
- **Graph builder Phase 5 — Lazy resolution**: When `lazy=True`, stubs remain pending and are resolved on-demand via `resolve_stub_on_demand()`, avoiding unnecessary work for stubs that no query will ever reference.
- **9 BSG interceptor plugins enhanced**: API Contract Guardian, Auth Boundary Shield, Dependency Blast Radius, Hardcoded Secret Catcher, IaC Drift Sentinel, N+1 Query Catcher, Resource Leak Preventer, Schema Migration Enforcer, and Silent Failure Catcher updated with improved detection patterns.

### Security Hardening

- **Custom rules path sanitization**: `_resolve_custom_rules_path` now routes through `batho.utils.path_sanitizer.sanitize_path`, rejecting traversal and unsafe absolute paths.
- **Log file path sanitization**: `configure_logging` sanitizes the configured log file path before creating directories or opening a FileHandler.
- **Non-Python introspector validation**: All language introspectors (npm, Cargo, Go, Maven) now validate package names with `_is_safe_dependency_name` and use safe-join path construction.

### Bug Fixes

- **External symbol double-write**: Removed duplicate `EXTERNAL_SYMBOL` entity insertion in the build pipeline that inflated `entity_count` metrics and produced duplicate Arrow rows.
- **Atomic scope manager cache writes**: Scope manager cache IPC is now written to `.tmp` files and atomically `Path.replace`d into place, preventing partial writes on interruption.
- **Agent views filtering in patch**: `agent_views` table is now filtered with `pyarrow.compute` before `to_pylist()`, materializing only needed rows and reducing RSS on large repos.

### Other Changes

- Capped `structlog` dependency to `<26` to prevent breaking changes.
- Added stdlib resolution benchmark (`benchmarks/bench_stdlib_resolution.py`).
- Added 9 new test modules covering stdlib expansion, pipeline serialization, sentinel cache, graph phases 4-5, and incremental synthetic paths.
- **864 tests** (up from 609).

---

## v1.3.2 — 2026-07-27

- H2: Hardened path sanitization with shared canonicalization helper (`_canonicalize_untrusted_path`) to reject encoded, Unicode, and null-byte traversal vectors across `sanitize_path`, `safe_join`, `sanitize_diff_path`, and `is_safe_filename`.
- H5: Added Unicode identifier support for Python and JavaScript entities in extraction and hierarchical descriptors; fallback parser regexes now match PEP 3131-style identifiers.

## v1.3.1 — 2026-07-22

**Bug fixes and MCP UX improvements.**

### Bug Fixes

- **CLI root resolution crash**: `batho_cli.py` no longer crashes when `--root` is omitted or passed as a string. `args.root` is now wrapped in `Path()` and checked for `None` before calling `.resolve()`.
- **MCP test isolation**: `test_repos_resource_no_registry` now uses `registry_path=tmp_path` instead of reading the real `~/.batho/mcp-repos.json`, preventing failures when a local registry exists.

### MCP UX Improvements

- **Entity ID visibility**: `search_entities`, `format_concise`, and `format_detailed` markdown output now include entity_ids in backticks, enabling agents to copy-paste them into `get_entity` and `trace_path`.
- **Name-based lookup fallback**: `get_entity` and `trace_path` now accept display names as fallback when an exact entity_id is not found. If the name uniquely matches, it resolves automatically. If multiple matches exist, a disambiguation list with entity_ids is returned.

### Tests

- 9 new tests in `tests/mcp/test_entity_lookup.py` covering entity_id visibility and name-based lookup.
- Updated `tests/mcp/test_dual_output.py` to reflect that entity_ids are now intentionally included in markdown.
- Total: 609 tests passing.

## v1.3.0 — 2026-07-22

**Arrow graph backend, build metrics accuracy, memory optimization, and documentation cleanup.**

### New Features

- **Arrow Graph Backend**: Columnar memory-mapped graph storage (`ArrowGraph`) as an alternative to the default `InMemoryGraph`, enabling streaming compaction for large codebases without holding the entire graph in RAM.
- **Graph Backend Auto-Selection**: Heuristic-based backend resolution using file count and estimated entity count thresholds (`auto_threshold_files=500`, `auto_threshold_entities=30,000`). Automatically selects Arrow for large repos.
- **Graph Backend Protocol**: Formal `GraphBackend` protocol defining the contract between in-memory and Arrow backends.
- **Public API Exports**: `ArrowGraph` and `create_graph` now exported from `batho` top-level package.

### Bug Fixes

- **`symbol_index_size` reporting**: Added `ScopeManager.global_symbol_count` property to accurately report total global symbols across all partitions instead of reporting 0.
- **Unresolved stub resolution counts**: `resolve_contextual_stubs` now returns `(resolved_count, unresolved_count)` tuple, propagated to `build_stats` for accurate metrics.
- **Self-loop cycle detection false positives**: `find_cycles` now skips self-loops only for `IMPORTS` relationships (where they're noise), preserving `INHERITS` self-loop detection (which indicates real circular inheritance).
- **Negative RSS recovery logging**: `gc.collect()` that increases RSS now logs a warning instead of info, with a descriptive message about memory pressure.

### Performance

- **Memory optimization in extraction pipeline**: `agent_blob` and `storage_blob` are stripped from `raw_results` after being streamed via `result_callback`, preventing ~1.6 GB of redundant blob retention during graph materialization on large repos.
- **Worker log suppression**: `load_effective_rules` accepts `quiet=True` to suppress info-level logging in worker processes, eliminating log spam during parallel extraction.
- **RSS flush log spam reduction**: `rss_flush_released_memory` now only logs when memory was actually recovered (`> 0`) or when RSS increased (`< 0`), silencing no-op `gc.collect()` calls that recovered 0 MB.

### Configuration

- **Updated default memory thresholds**: `warning_threshold_mb` raised to 800 MB, `critical_threshold_mb` to 1,500 MB, `rss_flush_threshold_mb` to 1,000 MB — better suited for large codebase indexing.

### Documentation

- **Stale SQLite references cleanup**: Replaced all legacy "SQLite" references in docstrings and comments with accurate terminology ("AST cache (flat-file msgpack)", "Arrow Bundle") across 15 source and test files.

### Tests

- **600 tests** (up from 507) — new tests for Arrow graph backend, graph factory, backend config validation, and graph consistency.

---

## v1.2.1 — 2026-07-20

**Bug fixes, concurrency safety, and documentation alignment.**

### Bug Fixes

- **Critical: `patch.py` NameError on delete-only runs** — `indexer` variable was only defined inside the `if added_or_modified:` block; delete-only patch runs crashed with `NameError`. Fixed by initializing `indexer = None` and guarding the `getattr` call.
- **`RepoRegistry` race condition** — `add()` and `remove()` performed load→mutate→save without locking. Concurrent MCP tool calls could lose entries. Fixed with `threading.Lock` and atomic file writes.
- **`ResolutionCache` non-atomic writes** — `put_symbols()` and `_save_index()` wrote directly to cache files without temp+rename. Crash during write could corrupt the cache. Fixed with `tempfile.mkstemp` + `os.replace` pattern.

### Improvements

- **`graph_overview` truncation indicator** — Truncated output now appends a visible notice to the markdown, matching `graph_query` and `get_file_graph` behavior.
- **`get_file_graph` cross-file ref performance** — Replaced per-entity `pc.equal()` loop with single `pc.is_in()` batch filter.
- **`graph_overview` file entity counts** — Fixed hardcoded `entities: 0` in file list; now computes actual entity counts per file from the agent table.
- **Dependency introspector input validation** — Added package name regex validation before subprocess execution.
- **Git subprocess hardening** — Added `GIT_PAGER=cat` to environment to prevent pager invocation.

### Documentation

- Updated all version references from `v1.2.0` to `v1.2.1` across whitepaper, CI/CD, configuration, and test docs.

---

## v1.2.0 — 2026-07-05

**MCP server, multi-repo registry, and community detection — Batho becomes an AI agent platform.**

### New Features & Enhancements

- **MCP Server** (`batho mcp`): FastMCP-based stdio server exposing 10 core tools for AI agents to query the code graph (expanded to 19 tools in v1.4.1 — see [Tools Reference](/docs/mcp/tools-reference)):
  - `graph_overview` — high-level codebase summary with entity counts, relationships, and communities
  - `graph_query` — filtered graph query by file, entity type, relation type, or name pattern
  - `get_entity` — detailed info for a single entity with relationships and optional source code
  - `trace_path` — shortest dependency path between two entities (BFS traversal)
  - `get_file_graph` — all entities and relationships within a single file
  - `search_entities` — substring/regex search across entity names
  - `get_delta` — incremental changes from the latest patch
  - `list_repos` / `add_repo` / `remove_repo` — multi-repo registry management
- **Multi-Repo Registry**: JSON-based registry at `~/.batho/mcp-repos.json` — one MCP config entry serves all repos. Register repos at runtime via `add_repo` tool.
- **Community Detection**: Greedy modularity clustering via `networkx` — automatically groups related entities into communities for codebase overview.
- **Dual-Output Architecture**: All MCP tools return both markdown `content` (model-facing, ~34% fewer tokens) and JSON `structuredContent` (machine-facing).
- **Token Budget Truncation**: Configurable `max_tokens` parameter on graph tools with automatic truncation and reporting.
- **MCP Prompts**: Workflow-specific prompt templates for agent onboarding (`explore_codebase`, `understand_function`, `analyze_file`, `trace_dependency`, `review_changes`, `impact_analysis`, `architecture_overview`).
- **MCP Resources**: Static schema and dynamic repo-list resources accessible via URI references.
- **Structured Error Handling**: Typed errors (`CLIENT_ERROR`, `EXTERNAL_ERROR`) with retry hints and actionable messages.
- **SKILL.md**: AI agent setup skill file for automated global install, MCP configuration across Claude Desktop, Cursor, Windsurf, and VS Code.
- **GitHub Actions Fleet Indexer**: Automated code graph indexing workflow with incremental patching on every push/PR.
- **New CLI Command**: `batho mcp` — starts the MCP server (8th CLI command).
- **New Dependencies**: `fastmcp>=3.4.0`, `networkx>=3.0`, `watchdog>=6.0.0`

### Tests

- **507 tests** (up from 381) — 126 new MCP tests covering tools, prompts, resources, registry, community detection, token budget, and error handling.

---

## v1.1.0 — 2026-06-10

**Refactored v1.1.0 release focusing on unified configuration, performance, and CLI simplicity.**

### New Features & Enhancements

- **Unified Configuration**: All settings consolidated into a single `./batho.yaml` (see `batho.yaml.example` for the complete schema).
- **Arrow IPC Bundle Storage**: Relational data and symbol indices are serialized in high-performance Arrow IPC table formats directly in the `.batho/artifact/` directory.
- **Lossless Bidirectional Traversal**: Graph-to-code reconstruction supported via `SYNTAX_GLUE` entity preservation and cryptographic hash validation.
- **Simplified CLI Interface**: Restructured the toolchain into exactly 7 command entrypoints:
  - `build` — baseline repository builds.
  - `patch` — native content-hash-based incremental indexing.
  - `export` — JSON and pack ZIP exports.
  - `fix` — database diagnostic and auto-repair routines.
  - `diff` — node-level evolution history.
  - `gc` — garbage collection, Sweeping, and vacuums.
  - `load` — unpack transport ZIPs.

### Removals

- **Subsystem Removal**: Removed the legacy Web Dashboard, REST API Bridge, MCP Hub Context Server, and client-side Git Hook automation to focus exclusively on high-performance developer command-line workflows.

---

## v1.0.0 — 2026-05-17

**Initial pre-refactor production baseline.**

### Features

- Multi-language AST extraction (40+ languages via tree-sitter).
- In-memory hypergraph with cross-file symbol resolution.
- BSG compression with token-budgeted rendering.
- Time Machine snapshots with incremental patching.
- Pre-refactor subsystems (legacy dashboard, REST bridge, MCP server, git hooks).
- 381 automated tests.
