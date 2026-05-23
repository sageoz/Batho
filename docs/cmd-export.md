# `batho export` — BSG Artifact Export

## Overview

`batho export` reads the latest BSG artifact from the `artifact_<dirname>.batho` database and serializes it into one of **seven JSON views**. Views range from full-fidelity storage format to LLM-optimized agent payloads, flat symbol indexes, dependency graphs, and incremental deltas.

Supports optional glob and category filtering, compact or pretty-printed output, a streaming mode for large repositories, and a token budget for the `agent` view.

---

## Synopsis

```
batho export [--root PATH] [--view VIEW] [--output PATH]
             [--index-id ID] [--filter GLOB] [--format json|pretty]
             [--category source|test|doc|config|infra|all]
             [--stream] [--token-budget N] [--baseline PATH]
```

---

## Flags & Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root` | `Path` | `.` (cwd) | Repository root containing the `.batho` database |
| `--view` | `enum` | `storage` | JSON view to export (see View Reference below) |
| `--output` | `Path` | stdout | Write JSON output to file instead of stdout |
| `--index-id` | `str` | latest | Specific run ID to export; defaults to the latest completed run |
| `--filter` | `GLOB` | none | Glob pattern to include only matching file paths (e.g. `src/**/*.py`) |
| `--format` | `json\|pretty` | `json` | Compact JSON or indented pretty-print |
| `--category` | `enum` | `all` | Filter by file category (see Category Reference below) |
| `--stream` | flag | `false` | Streaming mode — memory-efficient for large repositories |
| `--token-budget` | `int` | no limit | Maximum token budget for `agent` view output |
| `--baseline` | `Path` | — | Path to a previous export JSON; **required** for `--view delta` |

### View Reference

| View | Description |
|------|-------------|
| `storage` | Full-fidelity serialization of all BSG entities with all fields |
| `agent` | LLM-optimized payload; respects `--token-budget`; trims low-signal entities |
| `overview` | High-level statistics: entity counts, type distribution, file distribution |
| `files` | File-centric map grouped by extension and category |
| `symbols` | Flat symbol index: name, type, file, line, signature for every entity |
| `dependencies` | Dependency graph with forward + reverse edges per file |
| `delta` | Diff vs a `--baseline` export JSON: added, modified, removed, unchanged |

### Category Reference

| Category | Heuristic |
|----------|-----------|
| `source` | Default for files not matching other categories |
| `test` | Path contains `test` |
| `doc` | Path contains `doc` or ends in `.md`, `.rst`, `.txt` |
| `config` | Ends in `.yaml`, `.yml`, `.toml`, `.json`, `.ini`, `.cfg`, `.env` |
| `infra` | Ends in `.dockerfile`, `.tf`, `.hcl`, `.sh`, `.bash` |
| `all` | No category filtering applied (default) |

---

## Execution Flow

```mermaid
flowchart TD
    START([batho export invoked]):::success

    subgraph VALIDATION["Phase 1: Input Validation"]
        CHECK_VIEW{view in\nVALID_VIEWS?}
        EXIT_BAD_VIEW["Exit 1: Unknown view.\nValid: storage agent overview\nfiles symbols dependencies delta"]:::error
        CHECK_CAT{category in\nVALID_CATEGORIES?}
        EXIT_BAD_CAT["Exit 1: Unknown category.\nValid: source test doc config infra all"]:::error
        CHECK_DELTA{view == delta\nAND baseline\nnot provided?}
        EXIT_NO_BASELINE["Exit 1: --baseline required\nfor delta view"]:::error
    end

    subgraph DB["Phase 2: Database Lookup"]
        FIND_DB{artifact_*.batho\nexists?}
        EXIT_NO_DB["Exit 1: No artifact database found.\nRun: batho build --root root"]:::error
    end

    subgraph LOAD["Phase 3: Load BSGMap"]
        RESOLVE_RUN{--index-id\nprovided?}
        USE_LATEST[db.get_latest_run_id]
        USE_GIVEN[Use provided index_id]
        LOAD_BSG[Load bsg_entries from DB\nReconstruct BSGMap per file]
        BSG_OK{BSGMap\nloaded?}
        EXIT_NO_BSG["Exit 1: No BSG entries found.\nRun: batho build --root root"]:::error
    end

    subgraph FILTER["Phase 4: Apply Filters"]
        APPLY_GLOB{--filter\nprovided?}
        GLOB_FILTER[fnmatch each file_path\nagainst glob pattern]
        APPLY_CAT{--category\n!= all?}
        CAT_FILTER[_resolve_file_category\nentity metadata + path heuristics]
        FILTERED_MAP[Filtered BSGMap ready]
    end

    subgraph RENDER["Phase 5: View Rendering"]
        STREAM_MODE{--stream\nenabled?}

        subgraph STREAMING["Streaming Path"]
            BSG_EXPORTER[BSGExporter.export_streaming\nGenerator of JSON chunks]
            STREAM_OUTPUT{--output\nprovided?}
            STREAM_FILE[Write chunks to file]
            STREAM_STDOUT[Return generator\nfor stdout consumption]
        end

        subgraph BATCH["Batch Path"]
            DISPATCH{view}
            RENDER_STORAGE[bsg_map.render_storage_view]
            RENDER_AGENT[bsg_map.render_agent_view\ntoken_budget applied]
            RENDER_OVERVIEW[bsg_map.render_overview_json]
            RENDER_FILES[bsg_map.render_files_json]
            RENDER_SYMBOLS[_generate_symbols_view\nflat entity list]
            RENDER_DEPS[_generate_dependencies_view\nforward + reverse edges]
            RENDER_DELTA[_generate_delta_view\nload baseline JSON\nBSGMap.render_delta]
            SERIALIZE[_serialize\njson or pretty format]
            WRITE[_write_output\nfile or stdout]
        end
    end

    SUMMARY["stderr: Exported view: N files, M entities"]
    DONE([Exit 0]):::success

    START --> CHECK_VIEW
    CHECK_VIEW -->|Invalid| EXIT_BAD_VIEW
    CHECK_VIEW -->|Valid| CHECK_CAT
    CHECK_CAT -->|Invalid| EXIT_BAD_CAT
    CHECK_CAT -->|Valid| CHECK_DELTA
    CHECK_DELTA -->|Yes| EXIT_NO_BASELINE
    CHECK_DELTA -->|No| FIND_DB
    FIND_DB -->|No| EXIT_NO_DB
    FIND_DB -->|Yes| RESOLVE_RUN
    RESOLVE_RUN -->|No| USE_LATEST
    RESOLVE_RUN -->|Yes| USE_GIVEN
    USE_LATEST --> LOAD_BSG
    USE_GIVEN --> LOAD_BSG
    LOAD_BSG --> BSG_OK
    BSG_OK -->|No| EXIT_NO_BSG
    BSG_OK -->|Yes| APPLY_GLOB
    APPLY_GLOB -->|Yes| GLOB_FILTER
    APPLY_GLOB -->|No| APPLY_CAT
    GLOB_FILTER --> APPLY_CAT
    APPLY_CAT -->|Yes| CAT_FILTER
    APPLY_CAT -->|No| FILTERED_MAP
    CAT_FILTER --> FILTERED_MAP
    FILTERED_MAP --> STREAM_MODE
    STREAM_MODE -->|Yes| BSG_EXPORTER
    BSG_EXPORTER --> STREAM_OUTPUT
    STREAM_OUTPUT -->|Yes| STREAM_FILE
    STREAM_OUTPUT -->|No| STREAM_STDOUT
    STREAM_FILE --> SUMMARY
    STREAM_STDOUT --> SUMMARY
    STREAM_MODE -->|No| DISPATCH
    DISPATCH -->|storage| RENDER_STORAGE
    DISPATCH -->|agent| RENDER_AGENT
    DISPATCH -->|overview| RENDER_OVERVIEW
    DISPATCH -->|files| RENDER_FILES
    DISPATCH -->|symbols| RENDER_SYMBOLS
    DISPATCH -->|dependencies| RENDER_DEPS
    DISPATCH -->|delta| RENDER_DELTA
    RENDER_STORAGE --> SERIALIZE
    RENDER_AGENT --> SERIALIZE
    RENDER_OVERVIEW --> SERIALIZE
    RENDER_FILES --> SERIALIZE
    RENDER_SYMBOLS --> SERIALIZE
    RENDER_DEPS --> SERIALIZE
    RENDER_DELTA --> SERIALIZE
    SERIALIZE --> WRITE
    WRITE --> SUMMARY
    SUMMARY --> DONE

    classDef error fill:#fca5a5,stroke:#dc2626,color:#7f1d1d
    classDef success fill:#bbf7d0,stroke:#16a34a,color:#14532d
```

---

## Output

### Success (stderr summary — does not pollute stdout JSON)

```
Exported [agent]: 87 files, 1423 entities → output.json
```

### stdout (compact JSON, no `--output`)

```json
{"view_type":"agent","generated_at":"2024-05-23T17:00:00Z","files":[...]}
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Export succeeded |
| `1` | Validation failure, no DB, no BSG data, or write error |

---

## Error Cases

| Error | Cause | Resolution |
|-------|-------|-----------|
| `Unknown view` | Invalid `--view` value | Use one of: `storage agent overview files symbols dependencies delta` |
| `Unknown category` | Invalid `--category` value | Use one of: `source test doc config infra all` |
| `--baseline is required for the delta view` | `delta` view without `--baseline` | Provide path to a previous export JSON |
| `No artifact database found` | `batho build` not yet run | Run `batho build --root <path>` |
| `No BSG entries found` | DB exists but has no BSG data | Run `batho build --root <path> --full` |
| `Cannot load baseline from <path>` | Baseline file missing or invalid JSON | Provide a valid export JSON from a previous `batho export` run |
| `Streaming error` | `BSGExporter` failed to initialize | Check DB integrity with `batho fix` |

---

## Examples

```bash
# Export full storage view to stdout
batho export

# Export LLM-optimized agent view to file
batho export --view agent --output context.json

# Export with token budget for agent view (e.g. 32k tokens)
batho export --view agent --token-budget 32000 --output context.json

# Pretty-printed overview stats
batho export --view overview --format pretty

# Flat symbol index for all Python source files
batho export --view symbols --filter "**/*.py" --category source

# Dependency graph for the entire repo
batho export --view dependencies --output deps.json

# Delta diff against a previous export
batho export --view delta --baseline previous-export.json --output delta.json

# Stream a large repo agent view (memory-efficient)
batho export --view agent --stream --output context.json

# Export a specific historical run
batho export --view storage --index-id build_1716499100_abc12345

# Export only test files as a JSON report
batho export --view files --category test --format pretty
```
