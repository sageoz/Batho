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
│   ├── core/                   # Schemas and configuration models
│   ├── cli/                    # CLI subcommand handlers
│   ├── orchestrator/           # Orchestrators (build, patch, export, gc, load)
│   ├── modules/                # Modules (extraction, graph, compression, dependency, integrity, storage)
│   └── utils/                  # General utilities (hashes, locks, file I/O)
├── tests/                      # Test suite (pytest)
├── docs-site/                  # Docusaurus documentation site
├── cicd/                       # GitHub Actions + CI templates
├── batho_cli.py                # Main CLI entrypoint
├── batho.yaml.example          # Example configuration
└── pyproject.toml              # Project metadata + dependencies
```

## Key Modules

| Module | Responsibility |
|--------|--------------|
| `batho/modules/extraction/` | tree-sitter based AST extraction and parsing caches |
| `batho/modules/graph/` | InMemoryGraph engine and node-level diff tracking |
| `batho/modules/compression/` | BSGMap mapping and plugin rules engine |
| `batho/modules/dependency/` | Consolidated Dependency Extraction Utility (stdlib + venv) |
| `batho/modules/integrity/` | Database verification, repair engine, and report generator |
| `batho/modules/storage/` | Arrow IPC Bundle registry and views |
| `batho/orchestrator/` | High-level subcommand orchestrators (build, patch, export, gc, load) |

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
