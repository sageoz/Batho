# Batho Review Results

This file is an append-only ledger of code-review findings. Each issue has a stable `issue_id` and a `status` (`open` or `fixed`). Do not delete old entries; add observations or update `status` only.

---

## Run Metadata

- **Review Date:** 2026-08-04 (re-run + 2 new fixes)
- **Branch / Working Tree:** uncommitted changes on main (v1.3.2)
- **Tests Run:** `.venv/bin/python -m pytest tests -x --timeout=60 -q` — 864 passed in 56.06s
- **Compilation:** `python -m compileall -q batho batho_cli.py` — no syntax errors
- **Scope:** Working-tree changes plus committed baseline for ADR alignment across all 15 review areas
- **Prior Issues Verified:** All 11 previously reported issues (ef4dc734, 506cfc49, c59798e6, e67e3c75, a96bd947, 8d1c9f8f, a4411e58, 785f0f51, b36776d3, 383b2fbc, cdb4dca8) re-verified as fixed in the codebase.
- **Current Run:** 2 new issues found and fixed (8a0fce4b, c39ad8ba). All 864 tests pass.

---


---
issue_id: ef4dc734afed76ba
status: fixed
title: External symbol entities are written twice in the build artifact
subsystem: Orchestrator
category: Logic Error
severity: High
location: batho/orchestrator/build.py (Lines 475-706)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Removed the dedicated pre-legacy insert_file_artifacts_batch call for __external_symbols__; the legacy write path already adds them to entities_by_file and writes them once.
related_issues: []
---

### External symbol entities are written twice in the build artifact

- **Severity:** High
- **Subsystem:** Orchestrator
- **Category:** Logic Error
- **Location:** `batho/orchestrator/build.py` (Lines 475-706)
- **Description:**
  `EXTERNAL_SYMBOL` entities are inserted once via `db.insert_file_artifacts_batch(..., ext_batch, ...)` at line 524, and then a second time through the legacy write loop at lines 611-706 after `__external_symbols__` is deliberately added to `legacy_files`. `BathoBundleWriter.write_file_artifact` appends rows to in-memory column buffers, so the same entities are written twice in the Arrow bundle. This inflates `entity_count` metrics and produces duplicate rows that consumers see.
- **Code Evidence:**
  ```python
  # First write (line 524)
  db.insert_file_artifacts_batch(run_internal_id, ext_batch, store=store, entity_ids_global=all_entity_ids)

  # Added to legacy batch (lines 561-572)
  legacy_files.add(external_file_rel)
  entities_by_file[external_file_rel] = [e.to_dict() for e in external_entities]

  # Second write via _flush_legacy_batch (lines 683, 705-706)
  _flush_legacy_batch(legacy_write_batch)
  ```
- **Suggested Fix:**
  Remove the dedicated pre-legacy `insert_file_artifacts_batch` call for `__external_symbols__` and rely on the `entities_by_file[__external_symbols__]` entry that is already added to the legacy batch. Alternatively, exclude `__external_symbols__` from `legacy_files` and write it once with a single call.
- **Test Impact:**
  Existing tests pass (864) but do not cover external-symbol de-duplication. Add `tests/orchestrator/test_build.py` assertion that `EXTERNAL_SYMBOL` rows appear exactly once per file in `agent_views`.
- **ADR / System-Decision Impact:**
  Violates build metrics accuracy and the deterministic/reproducible-output ADR. It also wastes Arrow IPC space and can mislead downstream consumers.

---
issue_id: 506cfc49b2e35e2a
status: fixed
title: Scope manager cache IPC is written non-atomically
subsystem: Orchestrator
category: ADR/Architecture
severity: Medium
location: batho/orchestrator/patch.py (Lines 457-460)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Write the scope manager cache to .tmp.ipc and .meta.json.tmp, then Path.replace them atomically into place so readers never observe a partial file.
related_issues: []
---

### Scope manager cache IPC is written non-atomically

- **Severity:** Medium
- **Subsystem:** Orchestrator
- **Category:** ADR/Architecture
- **Location:** `batho/orchestrator/patch.py` (Lines 457-460)
- **Description:**
  The patch path serializes the dependency-scope cache directly to `batho_dir / "scope_manager_cache.ipc"` and immediately writes `scope_manager_cache.meta.json`. If the process is interrupted between the file open and close, the IPC can be partially written and the meta file can already claim a valid cache. This contradicts the MVCC artifact write pattern.
- **Code Evidence:**
  ```python
  _serialize_scope_manager_to_ipc(dep_scope_manager, cache_ipc)
  cache_meta.write_text(json.dumps({
      "manifest_hash": manifest_hash,
  }))
  ```
- **Suggested Fix:**
  Write the cache to `scope_manager_cache.tmp.ipc`, use `os.replace`/`Path.replace` to atomically swap it into place, then write the meta file only after the swap succeeds.
- **Test Impact:**
  Add a test that kills/crashes a patch run mid-write and confirms the cache files are either fully old or fully new, never corrupt or half-written.
- **ADR / System-Decision Impact:**
  Violates the MVCC atomic-artifact-writes ADR (tmp file -> rename to `.v<N>.ipc` -> update `meta.json` pointer).

---
issue_id: c59798e6eac65aa0
status: fixed
title: Patch materializes full agent_views table via to_pylist
subsystem: Orchestrator
category: Performance
severity: Medium
location: batho/orchestrator/patch.py (Lines 192-198)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Filter the agent_views table with pyarrow.compute (exclude UNRESOLVED and changed file_id rows) before calling to_pylist(), so only needed rows are materialized.
related_issues: []
---

### Patch materializes full agent_views table via to_pylist

- **Severity:** Medium
- **Subsystem:** Orchestrator
- **Category:** Performance
- **Location:** `batho/orchestrator/patch.py` (Lines 192-198)
- **Description:**
  `_load_project_scope_from_store` calls `agent_table.to_pylist()` on the entire `agent_views` table for the base run, then filters out `UNRESOLVED` and changed-file rows in Python. For large repositories, this materializes the full entity table into Python lists before any filtering, increasing RSS and pushing toward the 800MB warning/1500MB critical thresholds.
- **Code Evidence:**
  ```python
  agent_table = db._reader._get_table("agent_views")
  if agent_table.num_rows == 0:
      return scope

  for row in agent_table.to_pylist():
      entity_type = row.get("entity_type", "")
      if entity_type == "UNRESOLVED":
          continue
      ...
  ```
- **Suggested Fix:**
  Use `pyarrow.compute` to build a boolean mask that excludes `UNRESOLVED` and changed `file_id` rows, then call `table.filter(mask).to_pylist()` (or iterate columns directly) to materialize only the rows that are needed.
- **Test Impact:**
  Add a memory-regression test in `tests/orchestrator/test_patch.py` with a synthetic base run containing many entities and changed files.
- **ADR / System-Decision Impact:**
  Conflicts with the ADR guidance to avoid unnecessary `to_pylist()` on large tables before filtering and with the memory thresholds (warning 800MB / critical 1500MB).

---
issue_id: e67e3c759101c78e
status: fixed
title: Custom rules path is not sanitized
subsystem: BSG Compression
category: Security
severity: High
location: batho/modules/compression/rules.py (Lines 1541-1545)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: _resolve_custom_rules_path now routes the input through batho.utils.path_sanitizer.sanitize_path with root_path as the base directory, rejecting traversal and unsafe inputs.
related_issues: []
---

### Custom rules path is not sanitized

- **Severity:** High
- **Subsystem:** BSG Compression
- **Category:** Security
- **Location:** `batho/modules/compression/rules.py` (Lines 1541-1545)
- **Description:**
  `_resolve_custom_rules_path` resolves the `custom_rules_path` config value with `Path(path_value).expanduser()` and `resolve()`, accepting absolute paths and following symlinks without going through `batho.utils.path_sanitizer`. A malicious config can point `custom_rules_path` to any file on the filesystem (e.g., `/etc/shadow`, `~/.ssh/id_rsa`), which is then read and parsed with `yaml.safe_load`.
- **Code Evidence:**
  ```python
  def _resolve_custom_rules_path(path_value: str, root_path: Path) -> Path:
      candidate = Path(path_value).expanduser()
      if candidate.is_absolute():
          return candidate
      return (root_path / candidate).resolve()
  ```
- **Suggested Fix:**
  Validate the resolved path through `batho.utils.path_sanitizer.sanitize_path()` and require custom rule files to live inside `root_path` (or an explicitly allowed config directory). Reject absolute paths unless explicitly opted in.
- **Test Impact:**
  Add `tests/modules/compression/test_rules_path_validation.py` with traversal vectors, absolute paths, null bytes, and symlinks.
- **ADR / System-Decision Impact:**
  Violates the ADR that all `file_path` / path arguments are canonicalized through `batho.utils.path_sanitizer` before use.

---
issue_id: a96bd947693c8cf1
status: fixed
title: Non-Python dependency introspectors do not validate package names
subsystem: Dependency Intelligence
category: Security
severity: Medium
location: batho/modules/dependency/introspector.py (Lines 102-149, 176-232, 250-290, 295-354)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Added _is_safe_dependency_name validation and safe_join-based path construction to introspect_npm, introspect_crate, introspect_go_module, and introspect_jar, preventing traversal outside the package cache.
related_issues: []
---

### Non-Python dependency introspectors do not validate package names

- **Severity:** Medium
- **Subsystem:** Dependency Intelligence
- **Category:** Security
- **Location:** `batho/modules/dependency/introspector.py` (Lines 102-149, 176-232, 250-290, 295-354)
- **Description:**
  `introspect_python` validates `package_name` with a regex before use, but `introspect_npm`, `introspect_crate`, `introspect_go_module`, and `introspect_jar` construct filesystem paths directly from the package/module/crate/artifact name. A malicious manifest could use names containing `..` or absolute segments to traverse outside the intended package cache and read arbitrary files.
- **Code Evidence:**
  ```python
  # npm
  pkg_dir = node_modules_path / package_name

  # cargo
  candidates = [reg_dir / crate_name]

  # go
  for d in mod_cache.rglob("*"):
      if d_name_lower == module_lower or d_name_lower.startswith(f"{module_lower}@"):

  # maven
  candidate = m2.joinpath(*parts)
  ```
- **Suggested Fix:**
  Apply the same package-name validation to all language introspectors before building paths, and additionally run the final constructed path through `path_sanitizer` / ensure it stays within the expected cache directory.
- **Test Impact:**
  Add `tests/modules/dependency/test_introspector_validation.py` covering malicious package names for npm, cargo, go, and maven.
- **ADR / System-Decision Impact:**
  Violates the path-sanitization ADR and the dependency-introspection checklist item that package names must be validated before subprocess or file access.

---
issue_id: 8d1c9f8f27fd6ae6
status: fixed
title: batho.yaml.example stdlib language list is outdated
subsystem: Configuration
category: Doc Accuracy
severity: Low
location: batho.yaml.example (Line 53)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Updated batho.yaml.example to list the full default stdlib/dependency introspection language set and added a comment noting npm, Cargo, Go, and Maven support.
related_issues: []
---

### batho.yaml.example stdlib language list is outdated

- **Severity:** Low
- **Subsystem:** Configuration
- **Category:** Doc Accuracy
- **Location:** `batho.yaml.example` (Line 53)
- **Description:**
  The example configuration only lists `languages: ["python", "javascript", "go", "rust"]`, but `batho/modules/dependency/indexer.py` now defaults to 25+ languages (C/C++, Java, Ruby, C#, PHP, Kotlin, Swift, etc.). Users following the example will not be aware of or enable the newly supported stdlib/dependency introspection languages.
- **Code Evidence:**
  ```yaml
  # batho.yaml.example line 53
  languages: ["python", "javascript", "go", "rust"]
  ```
  vs. `DependencyIndexer._index_stdlib` default list at lines 124-129.
- **Suggested Fix:**
  Update `batho.yaml.example` to match the new default language list and add a short comment that `introspection` now covers npm, cargo, Go modules, and Maven artifacts.
- **Test Impact:**
  Add `tests/modules/config/test_config_loader.py` to verify that defaults documented in `batho.yaml.example` stay in sync with `indexer.py` defaults.
- **ADR / System-Decision Impact:**
  Documentation and example configuration should accurately reflect the committed implementation.

---
issue_id: a4411e5866fc0d41
status: fixed
title: Log file path from config is not sanitized
subsystem: Core
category: Security
severity: Medium
location: batho/utils/logging.py (Lines 142-146)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: configure_logging now sanitizes the configured log file path via batho.utils.path_sanitizer.sanitize_path (local import to avoid circular import) before creating directories or opening a FileHandler.
related_issues: []
---

### Log file path from config is not sanitized

- **Severity:** Medium
- **Subsystem:** Core
- **Category:** Security
- **Location:** `batho/utils/logging.py` (Lines 142-146)
- **Description:**
  `configure_logging` creates parent directories and opens a `logging.FileHandler` from the user-supplied `file` config value without sanitizing it. An attacker who can influence the logging config can write logs to arbitrary filesystem locations, including paths outside the intended log directory.
- **Code Evidence:**
  ```python
  if file:
      file_path = Path(file)
      if file_path.parent and not file_path.parent.exists():
          file_path.parent.mkdir(parents=True, exist_ok=True)
      file_handler = logging.FileHandler(file)
  ```
- **Suggested Fix:**
  Run the `file` value through `batho.utils.path_sanitizer.sanitize_path()` and, if a relative path is intended, join it to a configured safe log directory. Reject paths that escape the allowed directory.
- **Test Impact:**
  Add `tests/utils/test_logging.py` with traversal paths, absolute paths, null bytes, and symlink targets.
- **ADR / System-Decision Impact:**
  Violates the path-sanitization ADR for all `file_path` / path arguments.

---
issue_id: 785f0f517ee90bc5
status: fixed
title: stub_resolution_ms metric double-counts when external symbols are materialized
subsystem: Graph Backend
category: Metrics
severity: Medium
location: batho/modules/graph/builder/codegraph.py (Lines 2037-2055)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Captured a fresh timestamp (_t_stub_res_2) before the second stub resolution pass and added only the second pass's own duration to stub_resolution_ms, eliminating the double-counting of the first pass + materialization time.
related_issues: []
---

### stub_resolution_ms metric double-counts when external symbols are materialized

- **Severity:** Medium
- **Subsystem:** Graph Backend
- **Category:** Metrics
- **Location:** `batho/modules/graph/builder/codegraph.py` (Lines 2037-2055)
- **Description:**
  `stub_resolution_ms` is set to `(time.monotonic() - _t_stub_res) * 1000` after the first resolution pass (line 2037). When `external_symbol_count > 0` and not in lazy mode, a second pass runs and the metric is updated with `stub_resolution_ms += (time.monotonic() - _t_stub_res) * 1000` (line 2055). Because `_t_stub_res` was captured before the FIRST pass, the second addition includes the full elapsed time of (first pass + materialization + second pass), which is then added on top of the already-recorded first-pass duration. This inflates `stub_resolution_ms` in `build_stats` by roughly 2x the actual total whenever external symbols are materialized, misleading downstream consumers and benchmark comparisons.
- **Code Evidence:**
  ```python
  _t_stub_res = time.monotonic()
  stub_resolved_count, stub_unresolved_count = self.resolve_contextual_stubs(
      graph, scope_manager, lazy=lazy_stub_resolution,
  )
  stub_resolution_ms = (time.monotonic() - _t_stub_res) * 1000  # line 2037

  external_symbol_count = _materialize_external_symbols(graph, scope_manager)

  if external_symbol_count > 0 and not lazy_stub_resolution:
      scope_manager.clear_failed_lookups()
      second_resolved, second_unresolved = self.resolve_contextual_stubs(graph, scope_manager)
      stub_resolved_count += second_resolved
      stub_unresolved_count = second_unresolved
      stub_resolution_ms += (time.monotonic() - _t_stub_res) * 1000  # line 2055 — double-counts
  ```
- **Suggested Fix:**
  Capture a fresh timestamp before the second pass (e.g. `_t_stub_res_2 = time.monotonic()`) and add `(time.monotonic() - _t_stub_res_2) * 1000` to `stub_resolution_ms`, so each pass contributes only its own duration.
- **Test Impact:**
  Add a test in `tests/modules/graph/test_phase5_performance.py` that builds a graph with external symbols, asserts `build_stats["stub_resolution_ms"]` is within a reasonable bound (e.g. <= wall-clock time of `resolve_contextual_stubs` calls), and verifies the metric is not inflated.
- **ADR / System-Decision Impact:**
  Conflicts with the metrics-accuracy ADR — `build_stats` must report accurate timing counters. Inflated `stub_resolution_ms` can mislead benchmark comparisons and production telemetry.

---
issue_id: b36776d3b21e341c
status: fixed
title: strict_hashing config flag silently ignored in IncrementalEngine.scan_changes
subsystem: Storage
category: ADR/Architecture
severity: Medium
location: batho/modules/storage/arrow_bundle/incremental.py (Lines 78-96)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Guarded the mtime+inode+size fast-path with `if not strict_hashing:` so users who opt into strict hashing get forced content hashing on every tracked file. Also documented the strict_hashing key in batho.yaml.example and docs-site/docs/getting-started/configuration.md.
related_issues: []
---

### strict_hashing config flag silently ignored in IncrementalEngine.scan_changes

- **Severity:** Medium
- **Subsystem:** Storage
- **Category:** ADR/Architecture
- **Location:** `batho/modules/storage/arrow_bundle/incremental.py` (Lines 78-96)
- **Description:**
  The `strict_hashing` parameter is still accepted by `scan_changes()` and passed from `patch.py` (line 341: `strict_hashing=strict_hashing`), but the code no longer branches on it. Previously, when `strict_hashing=True` the mtime+inode+size fast-path was skipped and every tracked file was content-hashed; now the fast-path always applies regardless of the flag. Users who set `indexer.strict_hashing: true` in `batho.yaml` expecting forced content hashing will silently get the fast-path instead. The config key is also undocumented in `configuration.md` and `batho.yaml.example`, making the silent behavior change harder to discover.
- **Code Evidence:**
  ```python
  # OLD code (removed):
  if not strict_hashing:
      tracked_mtime_ns = tracked.get("mtime_ns")
      ...
      if (tracked_mtime_ns == st_mtime_ns and ...):
          continue

  # NEW code — fast-path always runs, strict_hashing is unused:
  tracked_mtime_ns = tracked.get("mtime_ns")
  tracked_ino = tracked.get("inode")
  tracked_size = tracked.get("size")
  ...
  if (tracked_mtime_ns is not None and ... and st_mtime_ns == tracked_mtime_ns
      and st_ino == tracked_ino and st.st_size == tracked_size):
      continue
  ```
- **Suggested Fix:**
  Either (a) remove the `strict_hashing` parameter and document that change detection now always uses the mtime+inode+size fast-path with content-hash fallback, or (b) preserve the old semantics by guarding the fast-path with `if not strict_hashing:` so users who opt into strict hashing still get forced content hashing. Either way, document the key in `configuration.md` and `batho.yaml.example`.
- **Test Impact:**
  Add `tests/modules/storage/arrow_bundle/test_incremental_strict_hashing.py` verifying that when `strict_hashing=True`, a file whose mtime+inode+size match but whose content has changed (e.g. via touch + write) is still detected as modified.
- **ADR / System-Decision Impact:**
  Conflicts with the deterministic/reproducible-output ADR ("Change detection uses file `mtime` + SHA-256 content hash"). The fast-path skips the SHA-256 content hash for unchanged-stat files, relying solely on mtime+inode+size. While this matches git's approach, it silently contradicts the documented ADR and the `strict_hashing` config contract.

---
issue_id: 383b2fbc62b85eb1
status: fixed
title: configuration.md stdlib language example is outdated
subsystem: Documentation
category: Doc Accuracy
severity: Low
location: docs-site/docs/getting-started/configuration.md (Line 77)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Updated configuration.md to list all 27 default stdlib languages and added a note that introspection now supports npm, Cargo, Go modules, and Maven artifacts in addition to Python venv. Also documented the strict_hashing config key.
related_issues: [8d1c9f8f27fd6ae6]
---

### configuration.md stdlib language example is outdated

- **Severity:** Low
- **Subsystem:** Documentation
- **Category:** Doc Accuracy
- **Location:** `docs-site/docs/getting-started/configuration.md` (Line 77)
- **Description:**
  The configuration documentation still shows `languages: ["python", "javascript", "go", "rust"]` as the example for `dependency.stdlib.languages`, but `batho.yaml.example` and `batho/modules/dependency/indexer.py` now default to 27 languages (python, javascript, typescript, go, rust, c, cpp, java, ruby, csharp, php, kotlin, swift, scala, dart, haskell, lua, r, perl, julia, zig, bash, objc, erlang, ocaml, hack, verilog). Additionally, the `introspection` section (lines 68-74) only mentions Python venv introspection and does not document that npm, Cargo, Go modules, and Maven artifacts are now introspected. This is the same class of issue as the previously fixed `8d1c9f8f27fd6ae6` (which was for `batho.yaml.example`), but the documentation file was not updated alongside the example config.
- **Code Evidence:**
  ```markdown
  # configuration.md line 77
  - `languages`: Languages to index (e.g., `["python", "javascript", "go", "rust"]`).
  ```
  vs. `batho/modules/dependency/indexer.py` lines 62-68 default list of 27 languages.
- **Suggested Fix:**
  Update the example to list the full default language set (or reference "see `batho.yaml.example` for the full list"), and add a note under `introspection` that npm, Cargo, Go modules, and Maven artifacts are now supported in addition to Python packages.
- **Test Impact:**
  No test impact — documentation-only change.
- **ADR / System-Decision Impact:**
  Documentation should accurately reflect the committed implementation. The config docs are the canonical reference for user-facing keys.

---
issue_id: cdb4dca86ec424c3
status: fixed
title: Scope manager cache key does not cover nested manifest files
subsystem: Patching
category: Caching
severity: Medium
location: batho/orchestrator/patch.py (Lines 91-105, 193-196)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Rewrote _compute_manifests_hash to use ManifestParser._find_manifests for all pattern-based manifests (pyproject.toml, setup.cfg, package.json, Cargo.toml, go.mod, pom.xml, build.gradle, build.gradle.kts), covering both root-level and nested manifests up to _MAX_SEARCH_DEPTH. Requirements files remain root-level glob to match parse_manifests behavior.
related_issues: []
---

### Scope manager cache key does not cover nested manifest files

- **Severity:** Medium
- **Subsystem:** Patching
- **Category:** Caching
- **Location:** `batho/orchestrator/patch.py` (Lines 91-105, 193-196)
- **Description:**
  `_compute_manifests_hash(root)` hashes only root-level manifest files (`pyproject.toml`, `setup.cfg`, `package.json`, `Cargo.toml`, `go.mod`, `pom.xml`) plus root-level `requirements*.txt` and `build.gradle*` globs. However, `ManifestParser.parse_manifests` (and `detect_project_metadata`) now recursively search up to 3 levels deep for nested manifests (e.g. `subdir/Cargo.toml` in a Rust workspace, `packages/foo/package.json` in a JS monorepo). If a nested manifest file is added, removed, or modified without any root-level manifest changing, the scope manager cache key (`manifest_hash`) will be identical to the previous run and the stale cached `ScopeManager` will be reused. This means new dependencies declared in the nested manifest won't be indexed until the cache is manually cleared or a root manifest changes, leading to stale dependency resolution and potentially unresolved stubs in the patched graph.
- **Code Evidence:**
  ```python
  # _compute_manifests_hash — only root-level files
  def _compute_manifests_hash(root: Path) -> str:
      h = hashlib.sha256()
      for name in _MANIFEST_FILES:
          p = root / name              # root-level only
          if p.is_file():
              h.update(name.encode())
              h.update(p.read_bytes())
      for req in root.glob("requirements*.txt"):   # root-level only
          ...
      for gradle in root.glob("build.gradle*"):    # root-level only
          ...
      return h.hexdigest()

  # ManifestParser._find_manifests — searches up to 3 levels deep
  for path in root.rglob(pattern):
      ...
      depth = len(rel.parts) - 1
      if depth <= cls._MAX_SEARCH_DEPTH:
          found.append(path)
  ```
- **Suggested Fix:**
  Either (a) use `ManifestParser._find_manifests` to collect all manifest files (root + nested) and hash them all into `manifest_hash`, or (b) hash the content of all files returned by `ManifestParser.parse_manifests(root)` (the parser already discovers them). This ensures the cache key changes whenever any parsed manifest changes.
- **Test Impact:**
  Add `tests/orchestrator/test_patch_scope_cache.py` that creates a repo with a nested `Cargo.toml`, runs a patch to populate the cache, modifies the nested manifest to add a dependency, runs another patch, and asserts the cache is invalidated (new dependency symbols appear in the scope manager).
- **ADR / System-Decision Impact:**
  Conflicts with the cache-invalidation ADR guidance ("cache must invalidate on patch runs and use content-hash cache keys"). The cache key omits the content hashes of nested manifests that are actually parsed, leading to stale cache hits.

---
issue_id: 8a0fce4b0c25c925
status: fixed
title: receiver_var metadata not preserved in hollow topology serialization
subsystem: Extraction
category: Correctness
severity: High
location: batho/modules/extraction/pipeline.py (Lines 126-129) + batho/modules/graph/builder/codegraph.py (Lines 1985-1993)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Added receiver_var to the hollow topology serialization in pipeline.py (_serialize_extraction_result) and to the hollow entity materialization in codegraph.py (build_graph). The field is now serialized alongside caller_scope and target_name for contextual stubs, and preserved during graph materialization.
related_issues: []
---

### receiver_var metadata not preserved in hollow topology serialization

- **Severity:** High
- **Subsystem:** Extraction
- **Category:** Correctness
- **Location:** `batho/modules/extraction/pipeline.py` (Lines 126-129) + `batho/modules/graph/builder/codegraph.py` (Lines 1985-1993)
- **Description:**
  The extractor sets `receiver_var` metadata on UNRESOLVED stub entities (extractor.py line 885) to enable receiver-type-aware method resolution (Phase 2). However, the hollow topology serialization in `_serialize_extraction_result` only preserves `caller_scope` and `target_name` — `receiver_var` is dropped. During graph materialization in `build_graph`, the hollow entity is reconstructed without `receiver_var`, so `_resolve_by_receiver_type` (codegraph.py line 1052) always reads `None` and returns early, silently disabling receiver-type-aware method resolution for all stubs that go through the parallel extraction path.
- **Code Evidence:**
  ```python
  # pipeline.py — serialization (MISSING receiver_var)
  if e.is_contextual_stub:
      node["caller_scope"] = e.metadata.get("caller_scope")
      node["target_name"] = e.metadata.get("target_name")
      # receiver_var was NOT included here

  # codegraph.py — materialization (MISSING receiver_var)
  metadata = {"is_hollow": True}
  if "caller_scope" in node:
      metadata["caller_scope"] = node["caller_scope"]
  if "target_name" in node:
      metadata["target_name"] = node["target_name"]
      # receiver_var was NOT restored here

  # codegraph.py — consumer (reads receiver_var, always None)
  receiver_var = stub.metadata.get("receiver_var")  # always None!
  if not receiver_var or "." not in target_name:
      return None  # early return — method resolution never runs
  ```
- **Suggested Fix:**
  Add `node["receiver_var"] = e.metadata.get("receiver_var")` to the serialization in `pipeline.py`, and `if "receiver_var" in node: metadata["receiver_var"] = node["receiver_var"]` to the materialization in `codegraph.py`.
- **Test Impact:**
  Add a test in `tests/modules/extraction/test_pipeline_serialize.py` that verifies `receiver_var` is preserved through serialize → deserialize round-trip for contextual stub entities.
- **ADR / System-Decision Impact:**
  Silently disables the Phase 2 receiver-type-aware method resolution feature, contradicting the stub-resolution ADR. The feature appears to work in unit tests (which use direct Entity construction) but fails in production (which uses the hollow topology path).

---
issue_id: c39ad8ba5f7bd48e
status: fixed
title: _find_manifests skips nested manifests when root manifest exists
subsystem: Dependency
category: Correctness
severity: High
location: batho/modules/dependency/manifest_parser.py (Lines 76-89)
first_seen: 2026-08-04
last_seen: 2026-08-04
fixed_at: 2026-08-04
resolution: Removed the `if not found:` guard so recursive search always runs. Added a `seen` set to deduplicate paths (rglob includes root-level files), preventing double-parsing of root manifests.
related_issues: [cdb4dca86ec424c3]
---

### _find_manifests skips nested manifests when root manifest exists

- **Severity:** High
- **Subsystem:** Dependency
- **Category:** Correctness
- **Location:** `batho/modules/dependency/manifest_parser.py` (Lines 76-89)
- **Description:**
  `_find_manifests` has an `if not found:` guard that skips the recursive `rglob` search when a root-level manifest is found. This means in a Rust workspace (root `Cargo.toml` + member crates at `subdir/Cargo.toml`) or a JS monorepo (root `package.json` + `packages/foo/package.json`), the nested manifests are never discovered. Dependencies declared only in nested manifests are silently missed during dependency indexing, leading to incomplete scope manager population and unresolved stubs for those dependencies.
- **Code Evidence:**
  ```python
  # Root-level check (fast path)
  root_file = root / pattern
  if root_file.is_file():
      found.append(root_file)

  # Recursive search — SKIPPED if root manifest exists!
  if not found:  # ← this guard is the bug
      for path in root.rglob(pattern):
          ...
  ```
- **Suggested Fix:**
  Remove the `if not found:` guard so recursive search always runs. Use a `seen` set to deduplicate paths (since `rglob` includes root-level files in its results), preventing double-parsing.
- **Test Impact:**
  Add a test in `tests/modules/dependency/test_manifest_parser.py` that creates a root `Cargo.toml` plus a nested `subdir/Cargo.toml` with different dependencies, and asserts both are parsed.
- **ADR / System-Decision Impact:**
  Conflicts with the nested-manifest discovery ADR ("ManifestParser searches recursively up to 3 levels deep for nested manifest files"). The `if not found` guard silently disables nested discovery for the most common case (root manifest exists).
