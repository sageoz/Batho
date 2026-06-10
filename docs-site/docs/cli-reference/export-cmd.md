---
title: "batho export"
description: "Export BSG artifacts as a transport bundle or JSON views"
---

# `batho export`

Export the latest Batho Structured Graph (BSG) artifacts from a database into a transport ZIP, or export JSON views for downstream ingestion.

## Description

The `export` command produces a transportable ZIP archive containing the local database artifact by default. Use the `--json` flag to export one of several predefined JSON views for downstream ingestion instead.

## Usage

```bash
batho export [options]
```

## Options

- `--root PATH`
  Repository root directory (default: current directory `.` ).
- `--verbose`
  Enable verbose debug logging.
- `--view VIEW`
  The view to export (default: `storage`). Options:
  - `storage`: Full-fidelity representation including raw content and syntax glue.
  - `agent`: LLM-optimized view with lightweight structural nodes.
  - `overview`: High-level statistics on entities, languages, and LOC.
  - `files`: File-centric outline list.
  - `symbols`: Flat symbol indexing.
  - `dependencies`: Dependency graph layout.
  - `delta`: Node-level modifications versus the baseline.
  - `rel`: Relationships list only.
- `--output PATH`
  Output file path. If not specified, defaults to `<root>/artifact_<dirname>.batho` (or `<root>/batho_export.json` if `--json` is used).
- `--index-id ID`
  Export a specific index run UUID. Default is the latest completed run.
- `--filter GLOB`
  Filter exported files using a glob pattern (e.g. `'src/**/*.py'`).
- `--format FORMAT`
  Output format: `json` (compact) or `pretty` (indented). Default: `json`.
- `--category CATEGORY`
  Filter files by BSG category (`source`, `test`, `doc`, `config`, `infra`, `all`). Default: `all`.
- `--token-budget N`
  Limit the agent view to a maximum token budget (by truncating lower priority entities).
- `--baseline PATH`
  Path to a previous export JSON file for comparison in `delta` view.
- `--rel`
  Include relationships array explicitly in the export output.
- `--json`
  Export a JSON view instead of the default transport ZIP. Use `--view`, `--format`, `--filter`, and `--category` to control the JSON output.

## Examples

Export a transport artifact (default):
```bash
batho export --root .
```

Export an agent-optimized JSON view:
```bash
batho export --json --view agent --token-budget 8000 --output context.json
```
