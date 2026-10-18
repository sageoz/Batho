# Contributor Contract — Batho

Every rule below is derived from patterns already present in the codebase
 Applies to `batho/` (engine), `sdk/batho_plugin/`
(including `core/` and `external/` packs), and user-facing tooling.

## Module structure

- Header docstring: path-style title + em-dash purpose; invariants and fix
  references (`T03:`, `FIX 10:`, `ENR-05`) live in design notes, not inline
  comments.
- `from __future__ import annotations` in every module, first.
- Import order: stdlib → third-party → `batho.*`. No wildcard imports.
- Lazy imports inside functions for heavy/optional deps.

## Typing

- Modern syntax only: `str | None`, `list[str]`, `dict[str, Any]` — never
  `Optional[]`/`List[]`.
- `TYPE_CHECKING` guards for protocol/circular imports.

## Data modeling — immutability is the law

- Pydantic domain models: `frozen` + `slots`; updates **evolve, never
  mutate** (`_evolve()` / `model_copy(update=...)`).
- Frozen dataclasses for value objects.
- Config objects are pydantic `BaseModel`; `.model_dump()` before dict
  access.

## Constants

- Module-level `UPPER_SNAKE_CASE`, declared once, annotated; prefer
  `frozenset`/`tuple` over `set`/`list`.
- Compile regexes once at module load; pre-lower/pre-normalize matcher data
  at construction, never per-call.

## Logging

- One logger per module: `get_logger(__name__, component="<area>")`.
- Event-style calls — never f-strings in log arguments; snake_case
  past-tense/state event names.
- `debug` for per-entity tracing; `warning` for recoverable degradation;
  `error` only for run-fatal.

## Error handling

- Per-unit isolation: one bad file never aborts the scan; one bad rule never
  aborts the apply.
- Catch specific exceptions; wrap-and-log with context, then continue. No
  bare `except:`; no silent `pass` without a log.
- Validate at boundaries (ReDoS guard on user regexes, path sanitization,
  plugin YAML schema validation).
- Fail fast on contract violations; degrade gracefully on environmental
  issues.

## Determinism & performance

- Sorted everything that feeds output; deterministic tie-breaks (priority
  desc, then id asc). Same input ⇒ byte-identical output — a testable
  invariant.
- Hot paths use O(1) set/dict lookups, never linear scans; memoize
  per-directory/per-file, not per-entity; batch per file, not per entity;
  thread-local expensive parsers; lazy-decode source bytes.

## Contracts & boundaries

- Protocols for backends — depend on the interface.
- Metadata namespace discipline: engine writes bare keys; plugins write
  `bsg.*`; ownership classes E1/E2/E3 determine strip/re-derive behavior.
  Never write a `bsg.*` key from engine code (sole grandfathered exception:
  `bsg.index_id`).
- Plugins are additive; the engine is subtractive-capable. Only the engine
  may prune/create/resolve entities.
- Serialization: msgpack (internal caches), orjson (JSON I/O), Arrow IPC
  (artifacts), zstd (compression) — one library per job.

## Testing

- pytest; fixtures under `tests/fixtures/`; golden-output files for
  deterministic pipelines.
- Every deterministic pipeline gets a byte-identical golden test.
- Per-file exception isolation gets a dedicated "one poisoned file" test.
- Plugin fixtures: `tests/fixtures/plugins/{golden,bad}_plugin.yaml`.

> If a rule of thumb conflicts with performance, measure first — the
> codebase's fix IDs document every such decision.
