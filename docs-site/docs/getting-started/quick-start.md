---
sidebar_position: 1
title: "Quick Start"
description: "Get Batho running in 30 seconds"
---

# Quick Start

Get running in 30 seconds:

```bash
# Install
uv add batho
# or
pip install batho

# Index your project
batho index --root . --verbose --snapshot

# Generate compressed bsg for LLM injection
batho bsg --root . --mode compressed --budget 12000

# Create snapshot
batho index --root . --snapshot

# Auto-detect and patch changes
batho patch --root . --scan

# Install Git hooks for automated checks
batho hooks install --all

# Launch the interactive Dashboard (v1)
batho dashboard --root .

# Start the artifact bridge (REST API + MCP server)
batho bridge serve --root .
batho bridge mcp --transport stdio

# Show all commands
batho --help
```

Batho scans your codebase, extracts every function, class, import, and relationship, and writes structured output to `.ctn/`.
