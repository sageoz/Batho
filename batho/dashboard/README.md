# Batho Dashboard

A brutalist, high-density code intelligence viewer for Batho workspaces.

## Quick Start

```bash
# From any directory in a Batho workspace
batho dashboard

# Or specify a custom port
batho dashboard --port 9000

# Or skip browser opening
batho dashboard --no-browser
```

## Requirements

- A Batho workspace with `.ctn/` directory populated
- Run `batho index` first if you haven't already

## Routes

| Route | Description |
|-------|-------------|
| `#/overview` | Index summary, file/entity counts |
| `#/hypergraph` | Interactive code graph (Phase 3) |
| `#/files` | File browser with entity counts (Phase 2) |
| `#/relationships` | Cross-file relationship viewer (Phase 4) |
| `#/rules` | BSG rule inspector (Phase 4) |
| `#/snapshots` | Time Machine timeline (Phase 1) |
| `#/metrics` | Performance and quality metrics (Phase 5) |
| `#/search` | Full-text search interface (Phase 5) |

## Development

```bash
# Run with dev mode for token drift checking
batho dashboard?dev=1
```

## Architecture

- **Shell**: Single `index.html` with ES modules
- **Router**: Hash-based with error boundaries
- **Store**: LRU cache keyed by index_id
- **Loader**: Streaming JSON parser for CTN artifacts
- **Styling**: CSS custom properties (tokens), @layer organization

See `plans/dashboard/` for full specifications.
