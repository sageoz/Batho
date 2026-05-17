---
sidebar_position: 3
title: "Architecture for Contributors"
description: "High-level code map for contributors"
---

# Architecture for Contributors

## Repository Layout

```
batho/
├── batho/                      # Core Python package
│   ├── context/                # AST extraction, graph, cache, pipeline
│   ├── bsg/                    # BSG rules, plugins, schemas
│   ├── bridge/                 # REST API + MCP server
│   ├── cloud_sync/             # Artifact synchronization
│   ├── cli/                    # CLI entrypoints (bridge, dashboard)
│   ├── config.py               # Pydantic configuration
│   ├── synthesizer.py          # Evolution ledger
│   └── time_machine.py         # Snapshots + incremental patching
├── tests/                      # Test suite (pytest)
├── docs/                       # Raw documentation
├── docs-site/                  # Docusaurus documentation site
├── scripts/                    # CI/build scripts
├── cicd/                       # GitHub Actions + CI templates
├── batho_cli.py                # Main CLI entrypoint
├── batho.yaml                  # Example configuration
└── pyproject.toml              # Project metadata + dependencies
```

## Key Modules

| Module | Responsibility |
|--------|--------------|
| `batho/context/extractor.py` | tree-sitter based AST extraction |
| `batho/context/codegraph.py` | In-memory hypergraph with adjacency indexing |
| `batho/context/pipeline.py` | Parallel graph construction orchestration |
| `batho/context/cache.py` | SQLite-backed entity caching |
| `batho/bsg/rules.py` | Plugin loader + semantic overlay engine |
| `batho/time_machine.py` | Snapshot creation, diffing, incremental patches |
| `batho/bridge/` | REST API + MCP server implementation |

## Adding a New Language

1. Add a detector in `batho/context/languages/`
2. Implement the extractor subclass
3. Register in the language registry
4. Add tests in `tests/`

## Adding a BSG Plugin

1. Define the plugin YAML in `batho/bsg/plugins/`
2. Register in `batho/bsg/plugins/` registry
3. Add schema validation in `batho/bsg/schemas/`
4. Add integration tests
