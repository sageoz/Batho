---
sidebar_position: 5
title: "bsg"
description: "BSG rendering and generation"
---

# `bsg` Command

Render BSG outputs in multiple formats.

## BSG Options

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `compressed` | Rendering mode: `compressed`, `full`, `hierarchical` |
| `--budget` | `12000` | Token budget for compressed mode |

## Examples

```bash
# Generate full bsg with signatures
batho bsg --root . --mode full

# Generate hierarchical directory view
batho bsg --root . --mode hierarchical

# Generate compressed bsg for LLM injection
batho bsg --root . --mode compressed --budget 12000
```

| Mode | Best for | Output File |
|------|----------|-------------|
| **Full** | Developer reference with signatures + line numbers | `bsg_full.json` |
| **Hierarchical** | Directory-tree overviews | `bsg_hierarchical.json` |
| **Compressed** | LLM prompt injection (4K–40K tokens) | `bsg_compressed.json` |
