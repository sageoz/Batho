# Sageoz Core Engine Scope Validation (Batho)

## Summary
Batho’s core indexing, RepoMap compression, and Time Machine snapshot/diff capabilities align well with the PDD’s foundational CodeGraphIndexer/RepoMap/ingestion scope, validated by a successful Supabase index run with graph/repomap/architecture outputs. Key PDD v1 areas still missing are agentic architecture generation, standards-based documentation (C4/SRS/OWASP/ADR), live state engine (ticket sync), MR validation, and production webhook/incremental patching.

## Evidence (current completion)
- **Supabase index metadata** confirms a full index with graph/repomap/architecture outputs and stack detection populated (file/entity/relationship counts and outputs paths) @/Users/rishirajsharma/Sageoz/batho/supabase/.ctn/index.json#1-63.
- **RepoMap and CodeGraphIndexer** are implemented with caching, binary guards, parallel extraction, ignore support, and compression outputs @/Users/rishirajsharma/Sageoz/batho/README.md#4-74.
- **Time Machine snapshot/diff** functionality is in place; CLI includes snapshots and diff-snapshots @/Users/rishirajsharma/Sageoz/batho/README.md#8-74.
- **Stack detection** and multi-language coverage are implemented and validated in the v1 checklist @/Users/rishirajsharma/Sageoz/batho/docs/v1-feature-checklist.md#5-23.
- **Webhook + incremental patching** are explicitly stubbed and deferred @/Users/rishirajsharma/Sageoz/batho/docs/v1-feature-checklist.md#17-23.

## Scope matrix (PDD v1 vs Batho)
| PDD v1 module | PDD expectation | Current Batho state | Evidence | Status |
| --- | --- | --- | --- | --- |
| CodeGraphIndexer | Multi-language AST, graph topology, stack detection, fast reindex | Implemented (core extraction, graph, stack detection) | README + v1 checklist | ✅ Implemented |
| RepoMap | Token-budgeted hierarchical compression | Implemented (JSON + Markdown) | README + v1 checklist | ✅ Implemented |
| High-Performance Ingestion | Caching, parallel extraction, binary guards, ignores | Implemented | README + v1 checklist | ✅ Implemented |
| Time Machine | Snapshotting, diff, staleness, webhook-driven patching | Snapshots/diff/staleness done; webhook patching stubbed | README + v1 checklist | ⚠️ Partial |
| Agentic Architecture Generation | C4 models + directory summaries | Not implemented | PDD scope only | ❌ Missing |
| Standards Docs (SRS/OWASP/ADR) | Auto-doc generation from graph | Not implemented | PDD scope only | ❌ Missing |
| Live State Engine (Ticket Sync) | Issue ingestion + mapping | Not implemented | PDD scope only | ❌ Missing |
| MR Validation & Auto-Approval | Diff-to-ticket validation, persona routing | Not implemented | PDD scope only | ❌ Missing |
| CLI/API Command Surface | index/analyze/timeline/diff/roadmap/status | index/stats/snapshots/diff/patch/invalidate/webhook stub | README + CLI | ⚠️ Partial |

## Gaps and improvements (prioritized)
1. **Incremental patching + webhook handling (P0)**
   - Replace webhook stub with minimal GitHub push/PR parsing and queueing.
   - Implement selective graph updates for changed files (reuse existing patch flow, add correctness checks).
2. **Analyze pipeline (P0)**
   - Add `analyze_command` to generate initial C4 L1/L2 summaries + SRS scaffolding + OWASP checklist placeholders.
   - Keep outputs versioned in `sageoz/` or `.ctn/` for auditability.
3. **CLI alignment (P1)**
   - Add aliases or new commands to match PDD naming: `timeline_command` (snapshots), `diff_command` (diff-snapshots), `status_command` (stats).
4. **MR validation starter (P1)**
   - Build diff-to-ticket linking stub that identifies ticket IDs from branch/commit metadata and references graph entities.
5. **Live state engine starter (P2)**
   - Add GitHub/Jira ingestion scaffold and mapping schema for nodes.
6. **Observability (P2)**
   - Add structured metrics for indexing and patching runs (counts, latency, cache hits).

## Suggested next milestones
1. **Milestone A: Webhook + Incremental Patch MVP**
   - Webhook handler parses push/PR payloads, extracts file list, runs selective reindex, updates current graph/repomap.
   - Acceptance: single PR diff updates index within target for medium repo (≤5s best-effort).
2. **Milestone B: Analyze Command MVP**
   - Generate initial C4 L1/L2 summary, SRS skeleton, OWASP checklist with detected endpoints/auth heuristics.
   - Acceptance: produces versioned docs from current graph on Supabase repo.
3. **Milestone C: CLI Alignment + Status**
   - Add PDD-aligned commands or aliases without breaking current CLI.
4. **Milestone D: MR Validation Starter**
   - Ticket ID extraction + diff-to-graph evidence report (pass/fail + missing criteria stub).

## Recommendation on v2 backlog promotion
Promote **incremental indexing + webhook integration** into v1 (P0) because the PDD’s Time Machine explicitly depends on it and it unlocks continuous validation flows. Others can remain v2 unless the launch target requires governance outputs (SRS/OWASP).
