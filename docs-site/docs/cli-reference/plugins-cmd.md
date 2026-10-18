---
title: "batho plugins"
description: "Validate, list, and apply BSG rule plugins"
---

# `batho plugins`

Validate, list, and retro-apply repository-specific `bsg-plugin.v2` rule files — enabling rule-based graph enrichment on an existing artifact without re-extracting files.

## Description

Generated plugins live in the custom rules dir (`rules.custom_rules_dir`, default `.batho/plugins/`). `validate` runs the two-stage acceptance gate (schema + deterministic fixture gate on real sampled entities); `apply` re-runs the effective rule set against the built artifact's graph and writes back only changed per-file views.

## Usage

```bash
batho plugins <subcommand> [options]
```

## Subcommands

### `validate [PATH]`

Two-stage acceptance for BSG plugin files. With no `PATH`, every `*.yaml`/`*.yml` in the plugins dir is validated; `PATH` may be a single file or a directory.

- `--json` — Emit machine-readable JSON result.
- `--entities-sample N` — Fixture-gate entity sample size (default `2000`).
- `--selectivity F` — Max allowed hit % of sampled entities (default `10`).

### `list`

List discovered builtin + custom plugin files.

### `apply`

Re-enrich the built artifact's graph with rules (no re-extraction).

- `--plugin PATH` — Apply only rules from this plugin file (implies `--plugins-only`); omit to apply every plugin in the plugins dir.
- `--plugins-only` — Skip builtin plugins — apply custom rules only.
- `--dry-run` — Report the delta without writing blobs.
- `--json` — Emit machine-readable JSON result.

### `fingerprint`

Print the current plugin-set fingerprint and the number of loaded plugins — the same fingerprint stored in run artifacts and used to detect plugin drift.

### `doctor`

Report plugin-host status, worker preload health, and drift of the active plugin set vs the built artifact. Also available as top-level `batho doctor` — both invocations run the same check.

## Examples

```bash
batho plugins validate                 # gate every plugin in .batho/plugins/
batho plugins validate rules/my.yaml --json
batho plugins apply --dry-run          # preview the enrichment delta
batho plugins apply --plugins-only     # custom rules only, write changed views
```
