# Module: `batho.cli` (+ `batho_cli.py`)

## Overview

The CLI layer is the outermost entry point of Batho. `batho_cli.py` is the package entry-point that constructs the top-level `argparse` parser and dispatches to one of the five subcommands: `build`, `patch`, `export`, `fix`, and `diff`. Each subcommand lives in its own file under `batho/cli/` and follows the same thin-wrapper pattern: register argparse arguments, collect them into an Options dataclass, delegate all real work to the corresponding orchestrator or engine, and print a human-readable summary. The shared utilities module `_utils.py` provides a base parser (with `--root` and `--verbose`) that every subcommand inherits as a parent.

## Files Covered

| Filename | Size (bytes) | Purpose |
|---|---|---|
| `batho_cli.py` | 1 296 | Package entry point — builds top-level parser, dispatches `args.func(args)` |
| `batho/cli/_utils.py` | 800 | Shared argparse helpers (`create_base_parser`) |
| `batho/cli/build.py` | 2 440 | `batho build` — full index build wrapper |
| `batho/cli/patch.py` | 2 429 | `batho patch` — incremental patch wrapper |
| `batho/cli/export.py` | 4 239 | `batho export` — BSG artifact export wrapper |
| `batho/cli/fix.py` | 5 781 | `batho fix` — integrity check / repair / rollback wrapper |
| `batho/cli/gc.py` | 2 084 | `batho gc` — garbage collection and storage optimization |
| `batho/cli/diff.py` | 10 089 | `batho diff` — node-level changelog query | |

---

## Classes & Functions

### `batho_cli.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `_build_parser` | function | Constructs top-level `argparse.ArgumentParser` and registers all 5 subcommand parsers via lazy imports | build, patch, export, fix, diff | ✅ Used |
| `main` | function | CLI entry point — parses args, validates `args.command`, calls `args.func(args)`, exits | build, patch, export, fix, diff | ✅ Used |

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["python -m batho / batho console-script"] --> B["main()"]
    B --> C["_build_parser()"]
    C --> D["register_build_parser(subparsers)"]
    C --> E["register_patch_parser(subparsers)"]
    C --> F["register_export_parser(subparsers)"]
    C --> G["register_fix_parser(subparsers)"]
    C --> H["register_diff_parser(subparsers)"]
    B --> I["parser.parse_args()"]
    I --> J{"args.command?"}
    J -- "None" --> K["print_help + exit(0)"]
    J -- "set" --> L{"args.func?"}
    L -- "yes" --> M["args.func(args) → exit_code"]
    L -- "no" --> N["print_help + exit(1)"]
```

---

### `batho/cli/_utils.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `create_base_parser` | function | Creates an `ArgumentParser(add_help=False)` with `--root` (Path, default `.`) and `--verbose` (bool). Used as `parents=[create_base_parser()]` in every subcommand parser | build, patch, export, fix, diff, gc | ✅ Used |


#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["register_*_parser(subparsers)"] --> B["create_base_parser()"]
    B --> C["ArgumentParser(add_help=False)"]
    C --> D["add_argument --root"]
    C --> E["add_argument --verbose"]
    B --> F["returned as parents=[]"]

```

---

### `batho/cli/build.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `register_build_parser` | function | Registers `build` subcommand with args: `--full`, `--max-workers`, `--max-file-size-kb`; sets `func=cmd_build` | build | ✅ Used |
| `cmd_build` | function | Entry point for `batho build`. Constructs `BuildOptions`, calls `run_build()`, interprets result: warns if already built, prints error on failure, prints success summary | build | ✅ Used |

#### Argument Reference

| Argument | Type | Default | Purpose |
|---|---|---|---|
| `--root` | `Path` | `.` | Repository root (inherited from base parser) |
| `--verbose` | flag | `False` | Enable debug logging (inherited) |
| `--full` | flag | `False` | Force full rebuild — deletes existing DB first |
| `--max-workers` | `int` | `None` (→ CPU count) | Parallel workers for parsing |
| `--max-file-size-kb` | `int` | `None` (→ config) | Skip files larger than N KB |

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["batho build [args]"] --> B["cmd_build(args)"]
    B --> C["BuildOptions(root, force_full, verbose, max_workers, max_file_size_kb)"]
    C --> D["run_build(options)"]
    D --> E{result.success?}
    E -- "already_built warning" --> F["print guidance message + return 0"]
    E -- "failure" --> G["print errors to stderr + return 1"]
    E -- "success" --> H["print summary: entities/rels/files/ms + return 0"]
```

---

### `batho/cli/patch.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `register_patch_parser` | function | Registers `patch` subcommand with `--max-file-size-kb`; sets `func=cmd_patch` | patch | ✅ Used |
| `cmd_patch` | function | Entry point for `batho patch`. Constructs `PatchOptions`, calls `run_patch()`, handles "no database", "no baseline", "no changes" warnings, prints change summary on success | patch | ✅ Used |

#### Argument Reference

| Argument | Type | Default | Purpose |
|---|---|---|---|
| `--root` | `Path` | `.` | Repository root (inherited) |
| `--verbose` | flag | `False` | Debug logging (inherited) |
| `--max-file-size-kb` | `int` | `None` (→ config) | Skip large files during hash scan |

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["batho patch [args]"] --> B["cmd_patch(args)"]
    B --> C["PatchOptions(root, verbose, max_file_size_kb)"]
    C --> D["run_patch(options)"]
    D --> E{result.success?}
    E -- "failure" --> F["print errors to stderr + return 1"]
    E -- "no changes" --> G["print no-changes message + return 0"]
    E -- "success" --> H["print change summary (added/modified/deleted)"]
    H --> I{"node stats non-zero?"}
    I -- "yes" --> J["print node-level summary"]
    I --> K["return 0"]
```

---

### `batho/cli/export.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `register_export_parser` | function | Registers `export` subcommand with `--view`, `--output`, `--index-id`, `--filter`, `--format`, `--category`, `--token-budget`, `--baseline`, `--rel`; sets `func=cmd_export` | export | ✅ Used |
| `cmd_export` | function | Entry point for `batho export`. Constructs `ExportOptions`, calls `run_export()`, prints error on failure, prints summary (file/entity count, output path) to stderr | export | ✅ Used |

#### Argument Reference

| Argument | Dest | Type | Default | Purpose |
|---|---|---|---|---|
| `--root` | `root` | `Path` | `.` | Repository root (inherited) |
| `--verbose` | `verbose` | flag | `False` | Debug logging (inherited) |
| `--view` | `view` | `str` | `storage` | JSON view type: `storage`, `agent`, `overview`, `files`, `symbols`, `dependencies`, `delta`, `rel` |
| `--output` | `output` | `Path` | `None` (→ `batho_export.json`) | Output file path |
| `--index-id` | `index_id` | `str` | `None` (→ latest) | Specific run ID to export |
| `--filter` | `filter_pattern` | `str` (glob) | `None` | Glob filter on file paths |
| `--format` | `output_format` | `str` | `json` | `json` or `pretty` |
| `--category` | `category` | `str` | `all` | BSG category filter: `source`, `test`, `doc`, `config`, `infra`, `all` |
| `--token-budget` | `token_budget` | `int` | `None` | Token limit for agent view |
| `--baseline` | `baseline_path` | `Path` | `None` | Previous export JSON for delta view |
| `--rel` | `include_relationships` | flag | `False` | Include relationship blob in output |

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["batho export [args]"] --> B["cmd_export(args)"]
    B --> C["ExportOptions(root, view, output, format, filter_pattern, category, index_id, token_budget, baseline_path, include_relationships)"]
    C --> D["run_export(options)"]
    D --> E{result.success?}
    E -- "failure" --> F["print errors to stderr + return 1"]
    E -- "success" --> G["print summary to stderr: files/entities/path"]
    G --> H["return 0"]
```

---

### `batho/cli/fix.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `register_fix_parser` | function | Registers `fix` subcommand with `--deep`, `--dry-run`, `--format`, `--output`, `--rollback-to`, `--repair-only`, `--create-checkpoint`, `--no-audit`; sets `func=cmd_fix` | fix | ✅ Used |
| `cmd_fix` | function | Entry point for `batho fix`. Validates DB exists, dispatches to `handle_rollback()` if `--rollback-to`, optionally creates a checkpoint, runs `FixEngine`, generates and outputs report | fix | ✅ Used |
| `handle_rollback` | function | Handles the `--rollback-to` path: opens DB, creates `RollbackManager`, resolves `"last-known-good"` snapshot ID, calls `rollback_to_snapshot()` | fix | ✅ Used |

> **`__all__`**: Only `register_fix_parser` and `cmd_fix` are exported. `handle_rollback` is a module-level function called internally from `cmd_fix` but not exported.

#### Argument Reference

| Argument | Type | Default | Purpose |
|---|---|---|---|
| `--root` | `Path` | `.` | Repository root (inherited) |
| `--verbose` | flag | `False` | Debug logging (inherited) |
| `--deep` | flag | `False` | Comprehensive verification of all data |
| `--dry-run` | flag | `False` | Check only, no writes |
| `--format` | `str` | `text` | Report format: `text`, `json`, `csv` |
| `--output` | `Path` | `None` (stdout) | Write report to file |
| `--rollback-to` | `str` | `None` | Snapshot ID or `last-known-good` |
| `--repair-only` | `list[str]` | `None` (all checks) | Limit checks to: `database`, `registry`, `index`, `bsg`, `snapshots`, `cache`, `views` |
| `--create-checkpoint` | `str` | `None` | Create a named checkpoint before repairs |
| `--no-audit` | flag | `False` | Disable audit logging |

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["batho fix [args]"] --> B["cmd_fix(args)"]
    B --> C{"db_path exists?"}
    C -- "no" --> D["try glob artifact_*.batho"]
    D -- "none found" --> E["print error + return 1"]
    C -- "yes" --> F{"--rollback-to set?"}
    D -- "found" --> F
    F -- "yes" --> G["handle_rollback(args)"]
    G --> G1["get_database(root)"]
    G1 --> G2["RollbackManager(db, root)"]
    G2 --> G3{"target == 'last-known-good'?"}
    G3 -- "yes" --> G4["find_last_known_good()"]
    G3 -- "no" --> G5["use target as snapshot_id"]
    G4 --> G6["rollback_to_snapshot(snapshot_id)"]
    G5 --> G6
    F -- "no" --> H{"--create-checkpoint set?"}
    H -- "yes" --> I["RollbackManager.create_named_checkpoint(name)"]
    H --> J["FixEngine(root, deep_mode, dry_run, audit_log, repair_only)"]
    J --> K["engine.run() → result"]
    K --> L["ReportGenerator(format).generate(result)"]
    L --> M{"--output set?"}
    M -- "yes" --> N["write to file"]
    M -- "no" --> O["print to stdout"]
    N --> P["return result.summary.exit_code"]
    O --> P
```

---

### `batho/cli/diff.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `register_diff_parser` | function | Registers `diff` subcommand with mutually exclusive `--run`, `--entity`, `--file` and optional `--since`, `--json`; sets `func=cmd_diff` | diff | ✅ Used |
| `cmd_diff` | function | Entry point for `batho diff`. Validates `--since` only used with `--entity`, opens DB directly, dispatches to one of the three `_handle_*` functions | diff | ✅ Used |
| `_handle_run_diff` | function | Fetches all node changes in a single patch run via `db.get_run()` + `db.get_run_file_changelog()`, formats them grouped by change kind (`added`, `removed`, `modified`, `renamed`) | diff | ✅ Used |
| `_handle_entity_diff` | function | Fetches full evolution history of a single entity via `db.get_file_node_history()`, optionally filtered by `--since` run's `completed_at` timestamp | diff | ✅ Used |
| `_handle_file_diff` | function | Directly queries `file_changelog` table using raw SQL + `orjson` blob decompression to show all node changes across runs for a given relative file path | diff | ✅ Used |

#### Argument Reference

| Argument | Type | Default | Purpose |
|---|---|---|---|
| `--root` | `Path` | `.` | Repository root (inherited) |
| `--verbose` | flag | `False` | Debug logging (inherited) |
| `--run` | `str` | — | Show all node changes in a specific run UUID |
| `--entity` | `str` | — | Show full history of one entity ID |
| `--file` | `str` | — | Show all node changes in a file across runs |
| `--since` | `str` | `None` | Bound `--entity` history to runs after this run ID |
| `--json` | flag | `False` | Machine-readable JSON output |

> `--run`, `--entity`, `--file` are mutually exclusive and one is **required**.

#### Implementation Detail — `_handle_file_diff`

`_handle_file_diff` uses the public `db.get_file_changelog_raw(rel_path)` method which provides optimized raw SQL access to the `file_changelog` table while maintaining proper abstraction boundaries.

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["batho diff [args]"] --> B["cmd_diff(args)"]
    B --> C{"--since without --entity?"}
    C -- "yes" --> D["print error + return 1"]
    C -- "no" --> E["artifact_filename(root) → db_path"]
    E --> F{"db_path exists?"}
    F -- "no" --> G["print error + return 1"]
    F -- "yes" --> H["get_database(root) → db"]
    H --> I{which flag?}
    I -- "--run" --> J["_handle_run_diff(db, run_uuid, json)"]
    I -- "--entity" --> K["_handle_entity_diff(db, entity_id, since, json)"]
    I -- "--file" --> L["_handle_file_diff(db, rel_path, json)"]

    J --> J1["db.get_run(run_uuid)"]
    J1 --> J2["db.get_run_file_changelog(run_uuid)"]
    J2 --> J3["group by change_kind → print table"]

    K --> K1["db.get_run(since_run_uuid)? → completed_at"]
    K1 --> K2["db.get_file_node_history(entity_id)"]
    K2 --> K3["filter by completed_at → print timeline"]

    L --> L1["db.get_file_changelog_raw(rel_path)"]
    L1 --> L2["group by run transition → print per-file table"]
```

---

## Unused Symbols Summary

*(All symbols in this module are reachable from CLI commands)*

---

## Cross-File Architecture Notes

- **Pattern**: Every CLI file is a pure thin wrapper. All business logic lives in `batho/orchestrator/` (build, patch, export) or `batho/integrity/` (fix). `diff` is the exception — it directly queries the storage engine to avoid round-trips through an orchestrator.
- **`args.func` dispatch**: Each `register_*_parser()` calls `parser.set_defaults(func=cmd_*)`. `main()` then calls `args.func(args)` generically with no knowledge of specific commands.
- **Lazy imports**: All orchestrator imports (`from batho.orchestrator.build import ...`) happen inside the `cmd_*` functions, not at module level. This keeps CLI startup fast and avoids circular imports.
- **Exit codes**: All `cmd_*` functions return an integer exit code (`0` = success, `1` = user error, `2` = internal/engine error for `fix`). `main()` passes this to `sys.exit()`.
- **`diff` raw SQL**: `_handle_file_diff` uses the public `get_file_changelog_raw()` method which provides optimized access without breaking encapsulation.

```mermaid
classDiagram
    class main {
        +_build_parser() ArgumentParser
        +main() None
    }
    class create_base_parser {
        +__root Path
        +__verbose bool
    }
    class cmd_build {
        +register_build_parser(subparsers)
        +cmd_build(args) int
    }
    class cmd_patch {
        +register_patch_parser(subparsers)
        +cmd_patch(args) int
    }
    class cmd_export {
        +register_export_parser(subparsers)
        +cmd_export(args) int
    }
    class cmd_fix {
        +register_fix_parser(subparsers)
        +cmd_fix(args) int
        +handle_rollback(args) int
    }
    class cmd_diff {
        +register_diff_parser(subparsers)
        +cmd_diff(args) int
        +_handle_run_diff(db, run_uuid, json) int
        +_handle_entity_diff(db, entity_id, since, json) int
        +_handle_file_diff(db, rel_path, json) int
    }
    class cmd_gc {
        +register_gc_parser(subparsers)
        +cmd_gc(args) int
    }

    main --> cmd_build : registers
    main --> cmd_patch : registers
    main --> cmd_export : registers
    main --> cmd_fix : registers
    main --> cmd_diff : registers
    cmd_build --> create_base_parser : parents
    cmd_patch --> create_base_parser : parents
    cmd_export --> create_base_parser : parents
    cmd_fix --> create_base_parser : parents
    cmd_diff --> create_base_parser : parents
```
