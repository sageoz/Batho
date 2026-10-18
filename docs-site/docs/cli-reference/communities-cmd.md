---
title: "batho communities"
description: "Post-build community operations (label, list)"
---

# `batho communities`

Post-build community operations on the existing artifact: optional LLM labeling and hierarchy-aware listing.

## Description

The `communities` command operates on `communities.ipc` written by the last build/patch. `label` builds a deterministic card per community and calls the configured LLM (`community_detection.llm` + `BATHO_LLM_API_KEY`); `list` renders communities with their labels and `parent_id`/`level` hierarchy.

## Usage

```bash
batho communities <subcommand> [options]
```

## Subcommands

### `label`

LLM-label communities (writes labels into the artifact). Incremental: only communities whose card changed are re-labeled (hash-gated via `label_input_hash`). Off by default — disabled config or missing API key → clean no-op. `heuristic_label` is always preserved as fallback.

- `--dry-run` — Build cards and report what *would* be labeled (no writes, no LLM calls).
- `--json` — Emit JSON result.

### `list`

List communities with hierarchy + labels.

- `--tree` — Render the parent/level hierarchy as an indented tree.
- `--top N` — Max rows (default `30`).
- `--json` — Emit JSON result.

## Examples

```bash
batho communities list --tree          # domain → community → sub-community tree
batho communities label --dry-run      # preview LLM labeling cost
batho communities label                # write llm_label/label_source into the artifact
```
