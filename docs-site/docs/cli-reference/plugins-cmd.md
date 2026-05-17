---
sidebar_position: 12
title: "plugins"
description: "BSG plugin management and validation"
---

# `plugins` Command

Manage BSG (Batho Structured Graph) plugins for semantic analysis and rule-based transformations.

## Usage

```bash
batho plugins <subcommand> [options]
```

## Subcommands

| Subcommand | Purpose |
|-----------|---------|
| `list` | List available BSG plugins |
| `validate` | Validate a BSG plugin YAML file |
| `test` | Run BSG plugin fixture tests |
| `validate-strict` | Validate a plugin YAML with strict-mode (promotes warnings to errors) |
| `trace` | Inspect rule resolution and optionally apply rules with a trace log |

## `plugins list`

List all available BSG plugins in the repository.

```bash
batho plugins list --root /path/to/repo
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |
| `-v`, `--verbose` | off | Show detailed plugin information |

## `plugins validate`

Validate a BSG plugin YAML file against the schema.

```bash
batho plugins validate /path/to/plugin.yaml
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `plugin_file` | Yes | Path to plugin YAML file to validate |

## `plugins test`

Run BSG plugin fixture tests using YAML give/expect files.

```bash
# Test all fixtures in a directory
batho plugins test --fixtures /path/to/fixtures --root /path/to/repo

# Test a single fixture file
batho plugins test --fixture /path/to/fixture.yaml --root /path/to/repo

# Output structured JSON
batho plugins test --fixtures /path/to/fixtures --json
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--fixtures` | none | Directory containing `*.yaml` fixture files |
| `--fixture` | none | Path to a single fixture YAML file |
| `--root` | none | Optional root path for file-content matchers |
| `--json` | off | Emit structured JSON output instead of human summary |

## `plugins validate-strict`

Validate a plugin YAML file with strict-mode, which promotes warnings to errors.

```bash
batho plugins validate-strict /path/to/plugin.yaml
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `plugin_file` | Yes | Path to plugin YAML file to validate |

## `plugins trace`

Inspect rule resolution and optionally apply rules with a trace log for debugging.

```bash
batho plugins trace --root /path/to/repo
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | required | Path to repository root |

## Plugin Schema

BSG plugins follow the schema defined in `batho/bsg/schemas/bsg-plugin-schema-v1.json`.

### Example Plugin

```yaml
version: bsg-plugin-v1
name: token-optimization
description: Optimize token usage for LLM context
rules:
  - name: truncate-docstrings
    entity_types: [function, method]
    actions:
      - type: truncate_docstring
        max_length: 100
  - name: normalize-entry-points
    entity_types: [function]
    name_patterns: [main, run, start]
    actions:
      - type: normalize_entry_point
```

## Use Cases

- **Development**: Validate custom plugins before deployment
- **Testing**: Ensure plugin rules work as expected with fixture tests
- **Debugging**: Use trace to understand rule resolution
- **CI/CD**: Integrate validation into build pipelines
