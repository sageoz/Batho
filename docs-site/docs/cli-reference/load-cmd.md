---
title: "batho load"
description: "Unpack a transport artifact ZIP"
---

# `batho load`

Unpack a transport artifact ZIP (`.batho` bundle) into the target repository's `.batho/artifact/` directory.

## Description

The `load` command is the counterpart to `batho export`. It takes a transport ZIP archive (typically containing a compressed Arrow IPC database and configurations) and extracts it into the repository root so it can be queried locally or integrated with downstream tools.

## Usage

```bash
batho load [options] <ARTIFACT_PATH>
```

## Arguments

- `ARTIFACT_PATH` (Positional, Required)
  Path to the `artifact_<dirname>.batho` ZIP file to unpack.

## Options

- `--root PATH`
  Repository root directory where the artifact should be loaded (default: current directory `.` ).
- `--force`
  Overwrite the existing artifact database if one is already present in `.batho/artifact/`.

## Examples

Load a transport artifact into the current directory:
```bash
batho load artifact_batho-v1-1-0.batho
```

Force overwrite an existing bundle:
```bash
batho load artifact_batho-v1-1-0.batho --force
```

Load into a specific repository root:
```bash
batho load /downloads/artifact_myrepo.batho --root /projects/myrepo
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Artifact unpacked successfully. |
| `1` | Error (e.g., missing artifact, schema mismatch, or existing bundle without `--force`). |

## Common Errors

| Error | Cause | Resolution |
|-------|-------|------------|
| `Artifact bundle already exists at ... Use --force to overwrite.` | A previous `.batho/artifact/` bundle is present. | Run with `--force` to replace it. |
| `Invalid artifact: manifest.json missing ...` | The ZIP is corrupt or was not produced by `batho export --pack`. | Re-export from a valid build. |
| `Bundle schema mismatch: found ... expected ...` | The artifact was built with a different Batho version. | Rebuild with `batho build --full` and re-export. |

## CI/CD Workflow

`batho load` is the ingestion step in a typical CI/CD pipeline:

```
batho build --full                 # Initial indexing
  |
batho export --pack                 # Produces artifact_<dir>.batho
  |
[Upload to CI artifact store]
  |
[Next job: Download artifact_<dir>.batho]
  |
batho load artifact_<dir>.batho     # Restore into .batho/artifact/
  |
batho patch                         # Incrementally update changed files
```

This avoids re-parsing the entire codebase on every CI run.

## See Also

- [`batho export`](/docs/cli-reference/export-cmd) — Produce the transport artifact ZIP consumed by `load`.
- [`batho patch`](/docs/cli-reference/patch-cmd) — Incrementally update after loading.
- [CI/CD Integration](/docs/cicd) — Full workflow guides for GitHub Actions and GitLab CI.
