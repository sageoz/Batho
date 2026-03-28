---
title: Batho Core Level-5 Knowledge Transfer (v1)
---

## 1) What Batho Core is
Enterprise-grade, multi-language code indexer with RepoMap compression and Time Machine snapshots/diffs; no LLM dependency. See highlights in README @batho/README.md#1-72.

## 2) Component map (scope + responsibilities)
- **CLI (`batho_core/cli.py`)**: Orchestrates commands (index, stats, patch, snapshots, diff, webhook). Manages `.ctn` directory, index metadata, repo hash + staleness score.
- **CodeGraphIndexer (`context/codegraph.py`)**: Walks repo, honors `.gitignore`/`.bathoignore`, size + binary guard, mtime+SHA cache, parallel extraction, import resolution; emits `InMemoryGraph` (entities + relationships).
- **RepoMap (`context/repomap.py`)**: Converts graph into relative-path keyed map; captures dependencies (imports/calls/uses); renders JSON + Markdown (architecture.md) with optional token budgets.
- **Time Machine (`time_machine.py`)**: Snapshot create/list/load/diff; staleness scoring; incremental patch stub; webhook stub.
- **Config (`config.py`)**: Env-driven settings (log level, `.ctn` path, max file size, worker cap).

## 3) Execution flows
- **Full index**: `batho-core index --root <repo> --max-workers 0 --max-file-size-kb 500 --budget-tokens 200000 --verbose`
  - Ensures `.ctn`, builds graph via CodeGraphIndexer (cache-aware), builds RepoMap, writes `.ctn/<index_id>/{graph.json, repomap.json, architecture.md}`, updates `.ctn/index.json` metadata (current index, counts, repo hash, staleness).
- **Stats**: `batho-core stats --root <repo>` prints current index metadata.
- **Patch**: `batho-core patch --root <repo> --diff pr.diff` (or explicit files). Loads current graph, reindexes changed files, rebuilds repomap + metadata/staleness.
- **Snapshots**: `batho-core snapshots --root <repo>` lists snapshots; `diff-snapshots` compares entity/relationship deltas + file add/remove.
- **Webhook stub**: `batho-core webhook --payload '{"event":"pull_request","repository":{"full_name":"org/repo"}}'` logs + echoes (no automation yet).

## 4) Data & outputs
- `.ctn/<index_id>/graph.json` — entities + relationships.
- `.ctn/<index_id>/repomap.json` — RepoMap structure (relative paths, deps).
- `.ctn/<index_id>/architecture.md` — hierarchical view (compressed/full).
- `.ctn/index.json` — index metadata (current index id, counts, repo hash, staleness, outputs).
- `.ctn/snapshots/<snapshot_id>.json` — snapshot with graph, repomap, stats, label.

## 5) Safeguards & hardening
- Binary detection: magic bytes + entropy + null-byte ratio; size guard (default 500KB) before parsing.
- Ignore rules: `.gitignore` + `.bathoignore` via pathspec.
- Cache: mtime+SHA file cache at `.ctn/file_cache.json` to skip unchanged files.
- Atomic writes: JSON/text outputs written via temp files then replaced.
- Security posture: parse-only; no code execution.

## 6) Known gaps / risks (v1 to close)
- Incremental patching is stub-level: hashes changed files; repomap still rebuilt; no graph-level PR diff patch.
- Webhook is stub: does not trigger indexing/snapshot; no signature validation.
- Staleness scoring coarse (0.0/0.7/1.0 based on repo hash equality only).
- No file locking for `.ctn`; concurrent runs could race.
- Test/CI missing: extractor smokes, binary/size/ignore guards, import resolution, token budget enforcement, snapshot diff fidelity.
- Token budget handling in RepoMap should be verified/enforced before launch.

## 7) Operational playbook (new engineer)
1) Install: `pip install -e .`
2) Run full index: `batho-core index --root <path> --verbose --log-json`
3) Inspect outputs: `.ctn/<index_id>/architecture.md` + `repomap.json`
4) Iterate on PR: `batho-core patch --root <path> --diff pr.diff`; confirm `.ctn/index.json` updates (staleness, counts).
5) Snapshots: `batho-core snapshots --root <path>` then `diff-snapshots SNAP_A SNAP_B` to see deltas.

## 8) Future work checklist (ordered)
1) Implement real incremental patching from PR diffs (graph delta, avoid full rebuild when safe).
2) Wire webhook to trigger patch/index + snapshot; add HMAC signature validation.
3) Refine staleness metric (changed-file ratio, recency, MR frequency); surface in CLI.
4) Enforce token budgets in RepoMap rendering; expose in metadata.
5) Add CI with tests (extractor smokes, binary/size/ignore guards, import resolution, budget, snapshot diff fidelity).
6) Add locks around `.ctn` writes; checksum validation for corruption recovery.
7) Observability: standardize JSON logging defaults; counters for skipped/errored files.

## 9) Key references
- README highlights and CLI usage: @batho/README.md
- CodeGraphIndexer: @batho/batho_core/context/codegraph.py
- RepoMap: @batho/batho_core/context/repomap.py
- CLI commands + metadata handling: @batho/batho_core/cli.py
- Time Machine snapshots/diffs/stubs: @batho/batho_core/time_machine.py
- Config knobs: @batho/batho_core/config.py
