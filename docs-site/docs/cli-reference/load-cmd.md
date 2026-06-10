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
- `--verbose`
  Enable verbose debug logging.
- `--force`
  Overwrite the existing artifact database if one is already present in `.batho/artifact/`.
