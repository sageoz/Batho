# Batho Plugin Architecture Specification

**Spec ID:** BATHO-PLUGIN-ARCH-v1
**Status:** Draft for review
**Target version:** batho 1.5.0
**Date:** 2026-10-01

---

## 1. Overview

This specification defines the migration of Batho from a monolithic engine with
embedded semantic heuristics to a **tiered plugin architecture** where:

- The extractor engine becomes **pure AST** (parsing, captures, entity
  construction, identity).
- All semantic matching, classification heuristics, and hardcoded constants
  move to **plugins** that can be invoked at defined stages of the
  indexing/build pipeline — including stages where the AST is alive.
- The plugin system is a **single separate installable Python package**
  (`batho-plugin-sdk`) that ships both plugin packs as **submodules**:
  `batho_plugin_sdk.core` (foundation pack — mandatory) and
  `batho_plugin_sdk.external` (external pack — optional, enabled via config).

### 1.1 Goals

1. Single source of truth for every classification heuristic (eliminates the
   10 documented engine/plugin redundancies).
2. Language support becomes data (language packs), not engine code.
3. Pruning policy, resolution confidence, and noise sets become configurable
   without engine code changes.
4. Plugins can observe and influence every pipeline stage, with AST access
   where the AST is alive.
5. Zero net performance regression (±5%) and zero accuracy regression
   (byte-identical outputs per migration phase).

### 1.2 Non-Goals

- Plugins will **not** own entity ID generation.
- Plugins will **not** own the 11-tier stub resolution strategy
  implementations.
- Plugins will **not** run as separate OS processes / network services
  (tree-sitter nodes are process-local C pointers and cannot be serialized).
- No breaking change to the on-disk artifact format (Arrow IPC schemas stay
  column-compatible).

---

## 2. Verified Current-State Constraints

These facts, verified against the codebase, constrain the design:

| # | Constraint | Evidence |
|---|---|---|
| C1 | Tree-sitter `Node` objects are process-local; AST-stage plugins must execute inside the extraction worker while the tree is alive. | `extractor.py:809,816` |
| C2 | Extraction runs in forked worker processes; per-worker plugin preloading is an established pattern. | `pipeline.py:478-484, 628-645` |
| C3 | Language detection precedes parsing; the extractor receives language as a constructor argument. | `detector.py:405-470`, `extractor.py:691` |
| C4 | Rule matching costs ~1.5–60 µs/call; pruning is an O(1) set lookup (~0.1 µs) invoked ~100K+ times per build. | `score.md` avg_ns; `extractor.py:239-291` |
| C5 | Entity IDs are computed from entity names at extraction time; entry-point normalization must precede ID generation. | `extractor.py:1147-1169`, `schemas.py:663-677` |
| C6 | The AST cache stores extracted entities per file; plugin-logic changes require a cache-key fingerprint or stale results are served. | `ast_cache.py` |
| C7 | `plugins apply` strips and re-derives all `bsg.*` metadata (subtractive semantics), keeping only `bsg.index_id`. | `plugins_apply.py:117-132` |
| C8 | Derived annotation edges are restricted to `ANNOTATION_RELATIONS` and carry `semantic`/`edge_class`/`source` markers. | `rules.py:3038-3060`, `schemas.py:573` |

---

## 3. Target Module Architecture

```
batho-engine/            core package (exists today as batho/)
  core/                    schemas, config, cache (Entity/Relationship models UNCHANGED)
  modules/extraction/      pure-AST extractor + pipeline + scope manager
  modules/graph/           builder (resolution strategies), community, diff, incremental
  modules/enrich/          gap report (reads metadata; duplicates deleted)
  mcp/                     search ranking (reads metadata; re-derivations deleted)
  orchestrator/            build, patch, plugins-apply orchestration

batho-plugin-sdk/        NEW single package — the pluggable plugin service module
  stages.py                Stage enum + stage contracts
  context.py               PluginContext dataclass
  api.py                   DataPlugin / HookPlugin / RulePlugin protocols
  host.py                  PluginHost: discover, validate, compile, dispatch, telemetry
  fingerprint.py           plugin-set fingerprint computation
  compat.py                YAML rule-plugin loader (wraps existing rules.py engine)

  core/                    SUBMODULE — foundation pack (MANDATORY, ships with SDK)
    language_packs/          python.yaml, typescript.yaml, javascript.yaml,
                             go.yaml, rust.yaml
    pruning_policy.yaml      prunable method names, noise symbols
    resolution_policy.yaml   strategy → confidence map
    classification.yaml      file categorization rules (consolidated single source)

  external/                SUBMODULE — external pack (OPTIONAL, config-enabled)
    interceptors/            security, performance, data, reliability (existing YAML)
    domain_taxonomy.yaml     domain tagging (existing)
    quarantine.yaml          view-level quarantine (existing)
    service_tags.yaml        service-tag derivation (existing)
```

### 3.1 Dependency direction

```
batho-engine ──► batho-plugin-sdk
                     ├── core/       (foundation — auto-loaded, mandatory)
                     └── external/   (opt-in via plugins.external.enabled)
```

`batho-engine` depends only on the SDK package, never on engine internals of
the packs. `core/` is imported and compiled at host startup unconditionally;
`external/` submodules are discovered and loaded only when enabled in config
(`plugins.external.enabled: true` or per-plugin toggles). The engine refuses
to build if `core/` is missing or fails validation unless `--no-plugins` is
passed (loud warning, compiled-in fallback defaults).

---

## 4. Plugin SDK Specification

### 4.1 Pipeline Stages

```python
class Stage(Enum):
    ON_FILE_DETECTED    = "on_file_detected"     # ctx: path, content bytes
    ON_PRE_PARSE        = "on_pre_parse"          # ctx: path, content, language
    ON_POST_PARSE       = "on_post_parse"         # ctx: + tree.root_node (AST ALIVE)
    ON_COMMENT_CLASSIFY = "on_comment_classify"   # ctx: + comment nodes (AST ALIVE)
    ON_PROPERTY_CLASSIFY= "on_property_classify"  # ctx: + property nodes (AST ALIVE)
    ON_PRE_STUB_CREATE  = "on_pre_stub_create"    # ctx: + ref text, imports; → keep/prune
    ON_POST_ENTITIES    = "on_post_entities"      # ctx: + entity buffer (batch, per file)
    # ---- ENGINE-OWNED: stub resolution (no plugin hooks inside) ----
    ON_POST_RESOLVE     = "on_post_resolve"       # ctx: graph (no AST)
    ON_POST_BUILD       = "on_post_build"         # ctx: graph (no AST); semantic overlay
```

AST availability: stages `ON_POST_PARSE` through `ON_POST_ENTITIES` receive a
live `tree.root_node` and execute inside the worker process (C1). Stages
`ON_POST_RESOLVE` and `ON_POST_BUILD` execute in the parent process with graph
access only.

### 4.2 PluginContext

```python
@dataclass(frozen=True)
class PluginContext:
    file_path: str                    # repo-relative posix path
    root_path: Path
    language: str | None              # set after ON_FILE_DETECTED
    source_bytes: bytes | None        # alive in worker stages
    tree_root: Node | None            # alive in worker stages only (C1)
    imported_names: frozenset[str]    # extractor-built import index (O(1) reuse)
    file_imports: list                # (module_path, symbols, ...) tuples
    entities: list[Entity]            # mutable buffer (ON_POST_ENTITIES)
    relationship_buffer: list         # read-only in v1 (see §7.3)
    run_id: str
    config: Mapping[str, Any]         # read-only view
```

### 4.3 Plugin Types

**DataPlugin** — exposes precompiled structures. Loaded once per worker;
consulted via O(1) lookups by the engine. This is the mechanism that keeps hot
paths (pruning) at set-lookup speed (C4).

```python
class DataPlugin(Protocol):
    plugin_id: str
    version: str
    def compile(self) -> PluginData: ...
        # PluginData = {"sets": {key: frozenset}, "maps": {key: dict},
        #               "per_language": {lang: PluginData}}
```

**HookPlugin** — registers callbacks at stages; may mutate
`ctx.entities` metadata in place; returns a stage-specific result
(e.g., `PruneDecision` for `ON_PRE_STUB_CREATE`).

```python
class HookPlugin(Protocol):
    plugin_id: str
    version: str
    stages: tuple[Stage, ...]
    def on_<stage>(self, ctx: PluginContext) -> StageResult: ...
```

**RulePlugin** — the existing YAML `bsg-plugin.v2` matcher→action system,
unchanged in behavior, loaded through `compat.py`. Runs per-file in workers
(non-bidirectional) and post-build (bidirectional/semantic overlay), exactly as
today.

### 4.4 PluginHost

Responsibilities:

1. **Discover** plugins from the SDK submodules (`batho_plugin_sdk.core`,
   `batho_plugin_sdk.external`), user directories (`.batho/plugins/*.yaml`).
2. **Validate** — JSON Schema for YAML rules (existing); structural checks for
   Python plugins; stage/priority cycle detection.
3. **Compile** — build frozensets/dicts once; cache per worker
   (replaces `_WORKER_RULES_CACHE` with `_WORKER_PLUGIN_HOST`).
4. **Fingerprint** — SHA-256 over sorted `(plugin_id, version, data_hash)`
   tuples (see §9).
5. **Dispatch** — deterministic ordering: stage → priority (descending) →
   plugin_id (lexicographic). Identical inputs produce identical outputs.
6. **Telemetry** — per-plugin/per-stage call counts and nanoseconds, reusing
   the existing `rule_perf` plumbing.

### 4.5 Plugin classes and the fixture gate

A new plugin class is introduced for load-bearing plugins:

| Class | Selectivity gate | Version pinning | Golden tests | Who ships |
|---|---|---|---|---|
| `core` | **Exempt** (intentionally broad) | Required | Required | SDK `core/` submodule |
| `standard` | Existing cap (<10–15%) | Optional | Optional | SDK `external/` submodule or user |
| `experimental` | Existing cap + warning | No | No | user |

Rationale: pruning rules are intentionally broad (they match most external
symbols by design) and can never pass the enrichment-oriented selectivity cap.
Core-class plugins instead require golden-output tests: a fixture corpus whose
expected prune/tag counts are asserted in CI.

---

## 5. Engine Constant → Plugin Data Migration Map

Every hardcoded constant leaves the engine. The engine performs O(1) lookups
against host-compiled data.

| Constant (current location) | Target plugin | Data key | Consumers after migration |
|---|---|---|---|
| `_BUILTINS_BY_LANG` (`extractor.py:230-236`) | language-pack | `builtins` (per-language set) | `ON_PRE_STUB_CREATE` prune hook |
| Noise symbols `{"self","cls",...}` (`extractor.py:269`) | language-pack | `noise_symbols` (set) | prune hook |
| `_LINE_COMMENT_PREFIXES`, `_BLOCK_COMMENT_PAIRS` (`extractor.py`) | language-pack | `comment_syntax` (per-language map) | comment classification hook, gap extraction |
| `_PRUNABLE_METHOD_NAMES` (`codegraph.py:1138-1160`) | pruning-policy | `prunable_methods` (set) | `CodeGraphIndexer._should_prune_stub` |
| `_RESOLUTION_CONFIDENCE` (`codegraph.py:844-858`) | resolution-policy | `strategy_confidence` (map) | resolution pass, edge confidence |
| `_LANG_TO_MANAGER` (`pipeline.py:41-48`) | language-pack | `lang_to_manager` (map) | `_package_for_file` |
| Test-dir segments / test-file regex (`search_ranking.py:136-139`) | classification | `test_dir_segments`, `test_file_regex` | MCP ranking (until metadata read lands) |
| `_NOISE_FILE_PATTERNS`, `_MANIFEST_NAMES` (`gap_report.py:16-38`) | classification | `noise_paths`, `manifests` | gap report (or deleted in favor of metadata reads) |
| Per-extension language map `_EXT_TO_LANG` (`registry.py:55`) | **stays in engine** | — | Detector fallback; language packs may extend, not replace |

Language-pack YAML shape:

```yaml
# batho_plugin_sdk/core/language_packs/python.yaml
plugin_id: lang-python
version: 1.0.0
class: core
language: python
data:
  builtins: [int, str, float, bool, dict, list, set, tuple, len, range, ...]
  noise_symbols: [self, cls, args, kwargs, ctx, context]
  comment_syntax:
    line: ["#"]
    block: [['"""', '"""'], ["'''", "'''"]]
  lang_to_manager: pip
```

---

## 6. Graph Schema Impact

### 6.1 Entity model — structural fields

**No structural change.** The Pydantic model (`schemas.py:622-677`) keeps every
field:

```
type, name, file, start_line, end_line, start_byte, end_byte, signature,
metadata, parent_id, raw_content, content_hash, raw_bytes,
leading_whitespace, trailing_whitespace, ast_node_type, children_order,
enclosing_start_byte, enclosing_end_byte, is_documentation, id_override
```

All migration happens **inside `metadata`** (the `EntityMetadata` dict). This
is deliberate: Arrow IPC views (`agent_views`, `file_tracking`, `rels_views`)
project `metadata_json` as an opaque column, so no artifact schema migration is
required.

### 6.2 Entity metadata — ownership contract (the core change)

Metadata keys are partitioned into three ownership classes. Ownership — not
key name — determines lifecycle (who writes, who strips, when re-derived).

#### Class E1 — `engine.core` (engine-only; never stripped)

| Key | Writer (after) | Writer (before) | Stage | Change |
|---|---|---|---|---|
| `language` | engine (value from detector plugin result) | engine | extraction | **Writer of detection logic moves to plugin; key + engine stamp stay** |
| `is_exported` | engine | engine | extraction (AST capture) | unchanged |
| `docstring` | engine (capture + clean) | engine | extraction | capture stays; **truncation/omission stays Tier-3 rule** |
| `implements`, `bases`, `extends`, `trait`, `receiver`, `visibility`, `field_type` | engine | engine | extraction (AST captures) | unchanged |
| `invocation_snippet` | engine | engine | extraction (AST capture) | unchanged |
| `is_docstring` | engine | engine | extraction | unchanged |
| entry-point normalization (entity `name` → `__main__`) | engine | engine | pre-ID | **stays in engine** (C5); plugin rule `bsg-normalize-entry-points` **deleted** |
| `stub_resolution_state` | engine | engine | resolution | unchanged |
| `resolved_target_id` | engine | engine | resolution | unchanged |
| `resolution_strategy` | engine | engine | resolution | unchanged |
| `resolution_confidence` | engine (values from resolution-policy **data plugin**) | engine (hardcoded map) | resolution | **values become configurable** |
| `prune_reason` | engine (decision from pruning-policy **data plugin** via hook) | engine (hardcoded sets) | pre-stub / post-resolve | **decision inputs become plugin data** |
| `ambiguous`, `ambiguous_candidates` | engine | engine | resolution | unchanged |
| `caller_scope`, `target_name`, `receiver_var` | engine | engine | stub creation | unchanged |
| `reference_type`, `resolution_reason`, `created_at`, `is_visible` | engine | engine | stub creation | unchanged |
| `bsg.index_id` | engine | engine | extraction | unchanged (grandfathered in strip-keep set, C7) |
| `is_hollow`, `is_external`, `symbol_type`, `scope_path` | engine | engine | materialization | unchanged |
| `synthesized`, `module_path` | engine | engine | module synthesis | unchanged |

#### Class E2 — `engine.hook` (hook plugins write during extraction; stripped on
re-extraction/patch; **not** stripped by `plugins apply`, which cannot re-derive
them without an AST)

| Key | Writer (after) | Writer (before) | Stage | Change |
|---|---|---|---|---|
| `access_type` (`read`/`write`) | hook `on_property_classify` | engine (`extractor.py:1108-1141`) | extraction | **moves** |
| `rationale_kind` | hook `on_comment_classify` | engine (`extractor.py:1212,2174`) | extraction | **moves** |
| `marker_comment` | hook `on_comment_classify` | engine (`extractor.py:2175`) | extraction | **moves** |
| `line_scan_fallback` | hook `on_comment_classify` | engine (`extractor.py:2179`) | extraction | **moves** |
| `bsg.hooks` *(new, optional)* | host auto-stamp | — | extraction | list of hook plugin_ids that mutated the entity; **debug-gated** (`plugins.telemetry.hooks_metadata: true`), absent by default |

Key names are preserved so existing artifacts and downstream consumers remain
compatible.

#### Class E3 — `plugin.rule` (`bsg.*`; stripped + re-derived on every
`plugins apply`, existing subtractive semantics)

| Key | Owner plugin (after) | Change |
|---|---|---|
| `bsg.category` | `classification.yaml` (consolidated single source) | **consolidated** — the 4 duplicate rules in `bsg_graph_foundation.yaml` are deleted; values unchanged: `TEST`, `DOC`, `CONFIG`, `SOURCE`, `INFRA` |
| `bsg.domain` | external `domain_taxonomy.yaml` | unchanged |
| `bsg.service_tag` | external `service_tags.yaml` | unchanged |
| `bsg.scope_tier` | core `bsg-derive-scope-tier` | unchanged (`GLOBAL`/`MODULE`/`CLASS`/`LOCAL`) |
| `bsg.language` | core detection plugins (**manifest-based rules only**) | **per-extension detection rules deleted** — engine `language` key + `_EXT_TO_LANG` remain the per-file source of truth |
| `bsg.frameworks` | core framework plugins | unchanged |
| `bsg.package_manager` | core detection plugins | unchanged |
| `bsg.infra` | core cicd/cloud plugins | unchanged |
| `bsg.usn` | various | unchanged |
| `bsg.rules` | engine auto-stamp | unchanged |
| `bsg.generated`, `bsg.gen.reason` | provenance convention | unchanged |
| `bsg.quarantined`, `bsg.noise` | external quarantine | unchanged |
| `bsg.intercept.category`, `bsg.intercept.message` | external interceptors | unchanged |
| `bsg.verify_coverage`, `bsg.verify_integrity`, `bsg.flag_for_reconstruction`, `bsg.reconstruction.*`, `bsg.bidirectional.*`, `bsg.token_budget` | core bidirectional | unchanged |
| `bsg.optimization`, `bsg.optimization_version`, `bsg.optimization_enabled` | core token optimization | unchanged |
| `bsg.normalized_name` | — | **REMOVED** (rule deleted; engine normalization writes entity name pre-ID) |

Legacy exception: Tier-3 rules may write the bare key `docstring` **only** for
truncation/fixture-omission (existing behavior in `bsg_token_optimization.yaml`).
All other rule writes must be `bsg.*`-namespaced; the schema validator enforces
this for new plugins.

### 6.3 Relationship model — structural fields

**No structural change.** (`schemas.py:853-875`)

```
source_id, target_id, type, roles, reference_start_byte, reference_end_byte,
definition_start_byte, definition_end_byte, metadata, confidence
```

`RelationshipType` enum: **unchanged** (26 types, including deprecated
legacy types handled by the T09/T15 reclassification validator).

### 6.4 Relationship metadata — ownership contract

| Key | Class | Writer | Change |
|---|---|---|---|
| `reversed` | engine.core | engine (T15 reclassification validator) | unchanged |
| `confidence` (field, not metadata) | engine.core | engine — values from **resolution-policy data plugin** | values become configurable |
| `ambiguous`, `ambiguous_candidates` (on rewritten stub edges) | engine.core | engine resolution pass | unchanged |
| `semantic` (`True`) | plugin.rule | rule engine derived edges | unchanged |
| `edge_class` (`"annotation"`) | plugin.rule | rule engine | unchanged; still restricted to `ANNOTATION_RELATIONS` (C8) |
| `source` (`"tag_postpass"`) | plugin.rule | rule engine | unchanged |
| `reason` | plugin.rule | rule engine | unchanged |
| `derived` (`True`) | engine.core | engine hierarchy/doc-link derivations | unchanged |

**Hook plugins cannot create, delete, or retarget relationships in v1.** They
mutate entity metadata only. Relationship creation remains: (a) extractor
structural edges, (b) engine derivations, (c) rule-engine annotation edges.
This keeps the edge contract auditable and the subtractive strip logic
(`plugins_apply.py:134-151`) intact.

### 6.5 Graph-level / run-level additions

| Artifact | Addition |
|---|---|
| `run_artifacts` row | `plugin_fingerprint` (SHA-256 hex), `metadata_schema: "batho-meta.v2"`, `hook_telemetry` (per-stage call counts/ns) |
| AST cache key | gains fingerprint component (§9) |
| `overview.md` / `score.md` | new sections: hook plugin stats; core-pack versions |

No new per-entity mandatory keys. No Arrow column changes.

---

## 7. Behavioral Changes to Engine Components

### 7.1 Extractor (`extractor.py`) — slim-down

Removed from engine (replaced by host calls):

- `_BUILTINS_BY_LANG`, noise-symbol set, `_should_prune_unresolved` decision
  logic (engine keeps the *call site*; the hook returns keep/prune)
- `_LINE_COMMENT_PREFIXES` / `_BLOCK_COMMENT_PAIRS` maps
- rationale/marker comment classification body
- `access_type` read/write inference body
- language stamping (engine still writes `language`, value supplied by
  detection stage)

Kept in engine: parsing, query compilation/captures, entity construction,
byte ranges, hierarchy, **ID generation**, stub creation mechanics,
entry-point normalization, decoding, caching.

Estimated reduction: **−600 to −800 lines**.

### 7.2 Graph builder (`codegraph.py`)

- `_PRUNABLE_METHOD_NAMES` → pruning-policy data plugin lookup.
- `_RESOLUTION_CONFIDENCE` → resolution-policy data plugin lookup.
- `_should_prune_stub` logic stays; its name set becomes plugin data.
- **Resolution strategies (11 tiers) untouched.**

Estimated reduction: **−150 lines**.

### 7.3 Deletions (redundancy cleanup)

| Deletion | Reason |
|---|---|
| `bsg_graph_foundation.yaml` rules `bsg-category-tests/docs/config/infra` | duplicated by `classification.yaml` (consolidated `bsg_file_categorization`) |
| `bsg_token_optimization.yaml` rule `bsg-normalize-entry-points` | engine normalizes pre-ID (C5) |
| Per-extension `detect_language` rules in all 13 detection plugins | engine `language` key is the per-file truth; manifest-based rules retained |
| `render_storage.py`: `_derive_category`, `_derive_language`, `_derive_service_tag`, `_derive_scope_tier` | wrong/incompatible fallbacks; metadata is authoritative |
| `gap_report.py`: `_NOISE_FILE_PATTERNS`, `_MANIFEST_NAMES` | replaced by plugin data / metadata reads |
| `search_ranking.py`: `_is_test_path`, `language_for_path` | replaced by `bsg.category` / `language` metadata reads (keep as fallback for raw-Arrow paths) |

### 7.4 Pipeline (`pipeline.py`)

- `_WORKER_RULES_CACHE` → `_WORKER_PLUGIN_HOST` (host object; rules are one
  plugin kind inside it). Preload once per worker, unchanged pattern (C2).
- `_LANG_TO_MANAGER` → language-pack data lookup.

---

## 8. CLI & Configuration Changes

### 8.1 CLI

| Command | Change |
|---|---|
| `batho plugins list` | shows plugin class (`core`/`standard`/`experimental`), type (data/hook/rule), stages, version |
| `batho plugins validate` | unchanged for YAML; adds structural validation for Python plugins |
| `batho plugins apply` | unchanged semantics (Tier-3 subtractive re-derivation); E2 hook keys untouched |
| `batho plugins fingerprint` | **new** — prints the current plugin-set fingerprint |
| `batho build` | new flag `--no-plugins` (compiled-in fallbacks + loud warning); default requires the SDK `core/` submodule |
| `batho doctor` *(new, optional)* | reports plugin host status, worker preload health, fingerprint drift vs artifact |

### 8.2 Configuration (`batho.yaml`)

```yaml
plugins:
  core:                       # batho_plugin_sdk.core submodule (foundation)
    required: true            # build fails (with guidance) if missing/invalid
  external:                   # batho_plugin_sdk.external submodule (opt-in)
    enabled: true             # master switch for the external pack
    select:                   # optional per-plugin allowlist; empty = all
      - interceptors
      - domain_taxonomy
      - quarantine
      - service_tags
  fingerprint_in_cache: true  # AST cache key includes plugin fingerprint
  telemetry:
    hooks_metadata: false     # when true, stamp bsg.hooks on entities (debug)
  host:
    dispatch_order: "priority_then_id"   # deterministic; only supported value in v1
```

---

## 9. Cache Invalidation & Fingerprint

**Problem (C6):** cached entities embed hook-plugin outputs. Changing a
language pack must invalidate affected cache entries.

**Fingerprint algorithm:**

```
fingerprint = sha256(
  sorted( for each loaded plugin:
             f"{plugin_id}|{version}|{sha256(canonical_compiled_data)}" )
  |> join("\n")
)
```

- Stored in: AST cache index, `run_artifacts.plugin_fingerprint`.
- **Granularity:** v1 uses a single global fingerprint (simple, safe).
  Per-language fingerprints are a documented future optimization.
- On mismatch: affected cache entries are re-extracted (correctness over
  speed). `batho patch` reports fingerprint drift in its summary.

---

## 10. Artifact & Backward Compatibility

| Concern | Resolution |
|---|---|
| Existing `.batho` artifacts | Fully valid — no Arrow schema change; metadata key names unchanged |
| Entities enriched by old rules | `plugins apply` re-derives `bsg.*` as today; E1/E2 keys untouched |
| `bsg.normalized_name` | disappears on next `plugins apply` (strip) or rebuild; consumers reading it must read entity `name` instead |
| Old plugin YAML | loads unchanged through `compat.py` |
| `DOC` vs `DOCS` inconsistency | `_normalize_category` retained in render path until v1.1 cleanup; consolidation in `classification.yaml` emits `DOC` (existing builtin value) |

---

## 11. Testing & Verification Gates

Each migration phase must pass its gate before the next begins:

| Phase | Scope | Exit gate |
|---|---|---|
| **P0** | SDK package skeleton (with `core/` + `external/` submodules); constants → `core/` data files; engine reads via host | build output **byte-identical** (entity metadata diff = ∅); perf ±0% |
| **P1** | Stage hooks land as no-ops; language detection + stamping via plugin | identical entity counts/metadata; perf within 5% |
| **P2** | Pruning decision → `ON_PRE_STUB_CREATE` hook + pruning-policy data; **fingerprint in cache key** | identical prune counts (`prune_reason` distribution identical); perf within 10% |
| **P3** | Comment/property classification → AST hooks | identical `rationale_kind`/`marker_comment`/`access_type` distributions |
| **P4** | Redundancy deletions (§7.3); `core` plugin class in fixture gate | identical `bsg.*` metadata; fixture gate green |
| **P5** *(optional)* | resolution-policy tuning docs; `batho doctor` | — |

Test additions:

1. **Golden metadata tests** — fixture corpus; assert full `metadata_json`
   equality across phases.
2. **Fingerprint tests** — plugin version bump ⇒ cache miss; identical plugin
   set ⇒ cache hit.
3. **Determinism tests** — same input, shuffled plugin load order ⇒ identical
   outputs (dispatch order is canonicalized).
4. **Worker preload tests** — host loads in forked workers; AST hooks receive
   live nodes; no pickling of `Node` anywhere (regression guard).
5. **Core-pack golden tests** — prune/tag counts on fixture corpus asserted in
   CI (replaces selectivity cap for `core` class).

---

## 12. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Plugin missing/disabled → no pruning → noise explosion | High | `core/` submodule mandatory (`plugins.core.required`); compiled-in fallback defaults; loud warnings |
| AST cache serves stale plugin-derived entities | High | Fingerprint in cache key (§9); `batho patch` drift report |
| Nondeterminism from plugin ordering | High | Canonical dispatch order; determinism tests (§11.3) |
| Hot-path slowdown if hooks route through generic rule matching | Medium | Tier-1 data plugins for all hot paths; hooks batch per-file; only per-entity call is pruning (~50 ms/build here) |
| `plugins apply` stripping hook-written keys | Medium | E2 class explicitly excluded from strip set; ownership classes documented in schema docs |
| API instability burden | Medium | SDK semver; `core` pack version-pinned; deprecation policy (one minor version) |
| Over-engineering / indirection cost | Medium | Only 3 plugin types; stages fixed enum; no dynamic stage registration in v1 |

---

## 13. What Never Moves (Constitutional Constraints)

1. **Entity ID generation** (`schemas.py:663-677`) — identity contract for
   caching, patching, diffing.
2. **Resolution strategy implementations** (`codegraph.py:1607-2415`) — the
   11-tier pipeline is the algorithmic core; only its *confidence values* and
   *prunable-name inputs* become plugin data.
3. **Relationship derivation** (CONTAINS, RATIONALE_FOR wiring, hierarchy
   edges) — structural contract.
4. **Orchestration** — multiprocessing, AST cache, serialization, Arrow
   writers.

---

## 14. Summary of Schema-Level Deltas

| Surface | Change |
|---|---|
| `Entity` Pydantic model | **unchanged** |
| `Relationship` Pydantic model | **unchanged** |
| `RelationshipType` enum | **unchanged** |
| Arrow IPC view schemas | **unchanged** (column-compatible) |
| Entity metadata ownership | 4 keys move engine → hook (`access_type`, `rationale_kind`, `marker_comment`, `line_scan_fallback`); 1 key removed (`bsg.normalized_name`); 1 optional key added (`bsg.hooks`, debug-gated); `resolution_confidence`/`prune_reason` values become plugin-configurable |
| `bsg.*` namespace | unchanged set except `bsg.normalized_name` removal; `bsg.category` consolidated to one source; per-extension `bsg.language` rules removed |
| Relationship metadata | unchanged contract; `confidence` values from resolution-policy data plugin |
| Run artifacts | + `plugin_fingerprint`, + `metadata_schema`, + `hook_telemetry` |
| AST cache key | + plugin fingerprint |

**One-line summary:** the graph schema itself does not change — the change is
a formal **metadata ownership contract** (engine.core / engine.hook /
plugin.rule) that determines who writes each attribute, when it is stripped,
and how it is re-derived, with the engine keeping identity, resolution
algorithms, and relationship derivation, and plugins owning every constant,
classification, and `bsg.*` enrichment.
