# `batho fix` — Integrity Verification & Repair

## Overview

`batho fix` performs **comprehensive integrity checking and automatic repair** of the Batho artifact database. It detects corruption, validates data structures across all subsystems, and repairs issues where possible.

Quick mode (default) runs fast surface-level checks. Use `--deep` for a full data scan. Use `--rollback-to` to restore the database to a prior known-good state without running checks.

---

## Synopsis

```
batho fix [--root PATH] [--deep] [--dry-run] [--format text|json|csv]
          [--output PATH] [--rollback-to SNAPSHOT_ID|last-known-good]
          [--repair-only database|registry|index|bsg|snapshots|cache|views]
          [--create-checkpoint NAME] [--no-audit]
```

---

## Flags & Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--root` | `Path` | `.` (cwd) | Repository root containing the `.batho` database |
| `--deep` | flag | `false` | Full data verification (slower, checks all rows and checksums) |
| `--dry-run` | flag | `false` | Check only — report issues without performing any repairs |
| `--format` | `text\|json\|csv` | `text` | Report output format |
| `--output` | `Path` | stdout | Write report to file instead of stdout |
| `--rollback-to` | `SNAPSHOT_ID` or `last-known-good` | — | Restore DB to a specific snapshot; skips all checks |
| `--repair-only` | one or more of repair targets | all | Scope repairs to specific subsystems only |
| `--create-checkpoint` | `NAME` | — | Create a named checkpoint **before** any repairs are applied |
| `--no-audit` | flag | `false` | Disable detailed audit logging of repair actions |

### `--repair-only` Targets

| Target | What It Checks / Repairs |
|--------|--------------------------|
| `database` | SQLite integrity, schema version, WAL state |
| `registry` | Run registry consistency, orphaned run records |
| `index` | Graph entities and relationships referential integrity |
| `bsg` | BSG entry checksums and entity counts |
| `snapshots` | Snapshot record completeness and hash validity |
| `cache` | AST cache entries against current file hashes |
| `views` | Context output JSON validity |

---

## Execution Flow

```mermaid
flowchart TD
    START([batho fix invoked]):::success

    subgraph VALIDATION["Phase 1: Locate Database"]
        FIND_DB{artifact_*.batho\nexists?}
        SCAN_ALT[Glob scan: artifact_*.batho\nin root directory]
        FOUND_ALT{Alternative\nfound?}
        EXIT_NO_DB["Exit 1: No artifact database found.\nRun: batho build --root root"]:::error
        DB_READY[Database path resolved]
    end

    subgraph CHECKPOINT["Phase 2: Optional Pre-Repair Checkpoint"]
        HAS_CHECKPOINT{--create-checkpoint\nflag set?}
        CREATE_CHECKPOINT[RollbackManager.create_named_checkpoint\nStore named snapshot before repairs]
        CHECKPOINT_OK{Created\nsuccessfully?}
        EXIT_CHECKPOINT_FAIL["Exit 1: Failed to create checkpoint"]:::error
    end

    subgraph ROLLBACK_PATH["Phase 3a: Rollback (if --rollback-to)"]
        HAS_ROLLBACK{--rollback-to\nprovided?}
        IS_LKG{target ==\nlast-known-good?}
        FIND_LKG[RollbackManager.find_last_known_good\nScan snapshots for healthy state]
        LKG_FOUND{Healthy snapshot\nfound?}
        EXIT_NO_LKG["Exit 1: No healthy snapshot found"]:::error
        USE_SNAPSHOT_ID[Use provided SNAPSHOT_ID]
        ROLLBACK_DRY{--dry-run?}
        EXIT_DRY_ROLLBACK["Exit 0: dry-run, no changes made"]:::success
        DO_ROLLBACK[RollbackManager.rollback_to_snapshot]
        ROLLBACK_OK{Rollback\nsucceeded?}
        EXIT_ROLLBACK_FAIL["Exit 1: Rollback failed"]:::error
        EXIT_ROLLBACK_OK["Exit 0: Successfully rolled back"]:::success
    end

    subgraph FIX_PATH["Phase 3b: Fix & Repair"]
        RUN_ENGINE[FixEngine.run\nroot + deep_mode + dry_run\naudit_log + repair_only]
        ENGINE_OK{Engine\nsucceeded?}
        EXIT_ENGINE_FAIL["Exit 2: Fix engine failed"]:::error
    end

    subgraph REPORT["Phase 4: Report Generation"]
        GEN_REPORT[ReportGenerator.generate\nformat: text / json / csv]
        REPORT_OK{Report\ngenerated?}
        EXIT_REPORT_FAIL["Exit 2: Report generation failed"]:::error
        HAS_OUTPUT{--output\nprovided?}
        WRITE_FILE[Write report to file\noutput.write_text]
        PRINT_STDOUT[Print report to stdout]
    end

    EXIT_CODE["Exit via result.summary.exit_code\n0=clean, 1=issues remain, 2=engine error"]

    START --> FIND_DB
    FIND_DB -->|Yes| DB_READY
    FIND_DB -->|No| SCAN_ALT
    SCAN_ALT --> FOUND_ALT
    FOUND_ALT -->|No| EXIT_NO_DB
    FOUND_ALT -->|Yes| DB_READY

    DB_READY --> HAS_CHECKPOINT
    HAS_CHECKPOINT -->|Yes| CREATE_CHECKPOINT
    HAS_CHECKPOINT -->|No| HAS_ROLLBACK
    CREATE_CHECKPOINT --> CHECKPOINT_OK
    CHECKPOINT_OK -->|Fail| EXIT_CHECKPOINT_FAIL
    CHECKPOINT_OK -->|OK| HAS_ROLLBACK

    HAS_ROLLBACK -->|Yes| IS_LKG
    HAS_ROLLBACK -->|No| RUN_ENGINE
    IS_LKG -->|Yes| FIND_LKG
    IS_LKG -->|No| USE_SNAPSHOT_ID
    FIND_LKG --> LKG_FOUND
    LKG_FOUND -->|No| EXIT_NO_LKG
    LKG_FOUND -->|Yes| ROLLBACK_DRY
    USE_SNAPSHOT_ID --> ROLLBACK_DRY
    ROLLBACK_DRY -->|Yes| EXIT_DRY_ROLLBACK
    ROLLBACK_DRY -->|No| DO_ROLLBACK
    DO_ROLLBACK --> ROLLBACK_OK
    ROLLBACK_OK -->|Fail| EXIT_ROLLBACK_FAIL
    ROLLBACK_OK -->|OK| EXIT_ROLLBACK_OK

    RUN_ENGINE --> ENGINE_OK
    ENGINE_OK -->|Fail| EXIT_ENGINE_FAIL
    ENGINE_OK -->|OK| GEN_REPORT
    GEN_REPORT --> REPORT_OK
    REPORT_OK -->|Fail| EXIT_REPORT_FAIL
    REPORT_OK -->|OK| HAS_OUTPUT
    HAS_OUTPUT -->|Yes| WRITE_FILE
    HAS_OUTPUT -->|No| PRINT_STDOUT
    WRITE_FILE --> EXIT_CODE
    PRINT_STDOUT --> EXIT_CODE

    classDef error fill:#fca5a5,stroke:#dc2626,color:#7f1d1d
    classDef success fill:#bbf7d0,stroke:#16a34a,color:#14532d
```

---

## Output

### Success (text format)

```
✅ Fix complete: 0 issues found, 0 repairs applied
   database  [OK]
   registry  [OK]
   index     [OK]
   bsg       [OK]
   snapshots [OK]
   cache     [OK]
   views     [OK]
```

### Issues Found & Repaired

```
⚠️  Fix complete: 2 issues found, 2 repairs applied
   database  [OK]
   bsg       [REPAIRED] 3 entries had stale checksums — recomputed
   cache     [REPAIRED] 12 entries invalidated
```

### Checkpoint Created

```
✅ Created checkpoint: chk_1716499200_mycheckpoint
```

### Rollback Success

```
Found last known good snapshot: snap_build_1716499100_abc12345
Rolling back to snapshot: snap_build_1716499100_abc12345
✅ Successfully rolled back to snap_build_1716499100_abc12345
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Clean or fully repaired |
| `1` | Issues found that could not be automatically repaired |
| `2` | Engine or report generation failed (internal error) |

---

## Error Cases

| Error | Cause | Resolution |
|-------|-------|-----------|
| `No artifact database found` | `batho build` not run yet | Run `batho build --root <path>` |
| `Failed to create checkpoint` | Storage write error | Check disk space and file permissions |
| `No healthy snapshot found for rollback` | All snapshots are marked unhealthy | Run `batho fix --deep` to attempt repair, or rebuild |
| `Fix engine failed` | Unexpected internal error | Check logs; run with `--verbose` if supported |
| `Report generation failed` | Serialization or write error | Try `--format json` or specify `--output` path |

---

## Examples

```bash
# Quick integrity check + auto-repair (default)
batho fix

# Deep verification (all rows, all checksums)
batho fix --deep

# Check only — no repairs (safe for CI)
batho fix --dry-run

# Export a JSON report to file
batho fix --format json --output reports/fix-report.json

# Only check BSG and snapshot subsystems
batho fix --repair-only bsg snapshots

# Create a checkpoint before risky repairs
batho fix --create-checkpoint pre-migration

# Rollback to last known-good snapshot
batho fix --rollback-to last-known-good

# Rollback to a specific snapshot ID
batho fix --rollback-to snap_build_1716499100_abc12345

# Dry-run rollback (preview only)
batho fix --rollback-to last-known-good --dry-run
```
