---
title: "batho build"
description: "Full index build for a repository"
---

# `batho build`

Build a complete code graph, BSG map, and baseline snapshot for a repository. If the artifact bundle already exists, the command will exit with guidance to use `batho patch` for incremental updates.

## Description

The `build` subcommand performs a full analysis of the codebase. It discovers files (respecting `.gitignore`), parses them using tree-sitter, extracts entities and relationships, resolves cross-file symbols, and serializes the result into an Arrow IPC Bundle saved in the `.batho/artifact/` directory.

## Usage

```bash
batho build [options]
```

## Options

- `--root PATH`
  Repository root directory (default: current directory `.` ).
- `--verbose`
  Enable verbose debug logging.
- `--full`
  Force a full rebuild. This will delete any existing database and rebuild the entire graph from scratch.
- `--max-workers N`
  Maximum parallel worker threads for parsing files (default: automatically matches the CPU thread count).
- `--max-file-size-kb N`
  Skip files exceeding this size limit in kilobytes during indexing.
- `--no-progress`
  Disable progress bars (also: `BATHO_NO_PROGRESS=1`).

## Progress Output

While building, each phase renders a pytest-style progress line on **stderr**:

```
batho build
  deps      done (0.1s)
  extract   [ 45%] 645/1432
  graph     done (0.2s)
  bsg       done (0.1s)
  persist   [100%] 312 files (0.4s)
✓ built in 42.3s — 312 files · 1542 entities · 4823 relationships
```

- The live `[ NN%]` bar appears only for phases longer than 2 seconds and is erased when the
  phase completes (only the completion line remains).
- When stderr is not a terminal (piped output, CI), no animation is shown — one completion
  line per phase instead.
- Phases finishing faster than 2 seconds never render a bar (no flashing).
- `NO_COLOR` disables color but keeps the bar.

### Disabling progress

```bash
batho build --no-progress
# or
BATHO_NO_PROGRESS=1 batho build
```

Progress is suppressed automatically when stderr is piped, when `logging.quiet` is set, or in
JSON mode. Some CI runners allocate pseudo-TTYs where terminal detection lies — prefer the
explicit flag or environment variable there. `TQDM_DISABLE` / `TQDM_MININTERVAL` (native tqdm
overrides) are also honored; note that **any non-empty `TQDM_DISABLE` value disables, including
`"0"`** — prefer `BATHO_NO_PROGRESS`.

## Output Summary

Upon a successful build, the command outputs a summary formatted as follows:

```
✓ built in 42.3s — 312 files · 1542 entities · 4823 relationships
```
