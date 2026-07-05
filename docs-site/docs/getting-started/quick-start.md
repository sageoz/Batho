---
sidebar_position: 1
title: "Quick Start"
description: "Get Batho running in 30 seconds"
---

# Quick Start

> **Tip**  
> **Setup with your AI Agent**  
> Prefer to let your AI agent handle setup? Give it the [Batho Setup Skill](https://github.com/sageoz/batho/blob/main/SKILL.md) — your agent installs Batho, builds the graph, and configures MCP automatically. See [Setup with AI Agent Skill](/docs/getting-started/skill-setup).

Get running in 30 seconds:

```bash
pip install batho

# Build full code graph for your repository (baseline)
batho build --root . --verbose

# Auto-detect and patch changes incrementally
batho patch --root . --verbose

# Export transport artifact (default)
batho export --root .

# Or export JSON view (e.g. storage view)
batho export --root . --json --view storage --output batho_export.json

# Query node-level evolution history or run diffs
batho diff --root . --run <run-id>

# Run integrity check and auto-repair on database
batho fix --root . --dry-run

# Run garbage collection and sweep old runs
batho gc --root . status

# Unpack transport zip bundle (.batho) into artifact directory
batho load path/to/artifact.batho

# Show all commands
batho --help
```

Batho scans your codebase, extracts every function, class, import, and relationship, and writes structured output to `.batho/`.

## Next Steps

- [Installation](/docs/getting-started/installation) - Detailed installation options
- [Configuration](/docs/getting-started/configuration) - Configure Batho for your needs
- [MCP Server](/docs/mcp) - Set up AI agent integration via Model Context Protocol
- [CLI Reference](/docs/cli-reference) - Complete command documentation
- [Whitepaper](/docs/whitepaper) - Deep technical reference
