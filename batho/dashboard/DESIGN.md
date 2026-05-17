# Batho Dashboard Design

## Professional Enterprise Design System

The Batho Dashboard follows a **Modern Enterprise** design aesthetic with subtle technological undertones — precise, reliable, and sophisticated. The interface prioritizes clarity and density without sacrificing breathability.

### Design Tokens

CSS tokens are defined in `assets/css/tokens.css`:

**Surface Hierarchy (Midnight Palette):**
| Token | Value | Usage |
|-------|-------|-------|
| `--background` | `#131317` | Page background |
| `--surface` | `#1a1a1f` | Main surfaces |
| `--surface-container` | `#1f1f23` | Cards, panels |
| `--surface-container-high` | `#2a292e` | Elevated elements |
| `--surface-container-highest` | `#353439` | Highest elevation |

**Color Palette:**
| Token | Value | Usage |
|-------|-------|-------|
| `--primary` | `#4f46e5` | Primary actions, focus states |
| `--primary-container` | `#4f46e5` | Primary buttons |
| `--on-primary-container` | `#dad7ff` | Text on primary |
| `--secondary` | `#06b6d4` | Technical accents |
| `--tertiary` | `#10b981` | Success states |
| `--error` | `#ffb4ab` | Error states |
| `--accent-amber` | `#f59e0b` | Warnings |

**Typography:**
- **Headings**: Space Grotesk, 600 weight (modern, geometric)
- **UI Text**: Inter, 400-500 weight (maximum legibility)
- **Code**: JetBrains Mono, 400 weight (developer-friendly)

**Spacing Scale:**
- `--space-xs`: 4px
- `--space-sm`: 8px
- `--space-md`: 12px
- `--space-lg`: 16px
- `--space-xl`: 24px
- `--space-2xl`: 32px

**Shape:**
- `--radius-sm`: 4px (small elements)
- `--radius-md`: 8px (buttons, cards, panels)
- `--radius-lg`: 12px (large cards)
- `--radius-full`: 9999px (badges, pills)

**Shadows:**
- `--shadow-sm`: 0 1px 2px 0 rgb(0 0 0 / 0.30)
- `--shadow-md`: 0 4px 6px -1px rgb(0 0 0 / 0.30)
- `--shadow-lg`: 0 10px 15px -3px rgb(0 0 0 / 0.30)

**Transitions:**
- `--transition-fast`: 100ms ease
- `--transition-base`: 150ms ease
- `--transition-slow`: 250ms ease

### Component Classes

**Cards & Panels:**
```css
.panel          /* Basic panel with border-radius and shadow */
.card           /* Hover-elevating card */
.stat-card      /* KPI stat card with hover lift */
```

**Buttons:**
```css
.btn            /* Base button (rounded, 8px radius) */
.btn--primary   /* Indigo primary */
.btn--secondary /* Outlined secondary */
.btn--ghost     /* Transparent ghost */
.btn--sm        /* Small size */
.btn--lg        /* Large size */
```

**Badges:**
```css
.badge              /* Base pill badge */
.badge--primary     /* Indigo accent */
.badge--success     /* Emerald */
.badge--warning     /* Amber */
.badge--error       /* Coral */
```

**Legacy Classes (Backward Compatible):**
```css
.stat-tile      /* Legacy stat display */
.chip           /* Legacy chips */
.glow-badge     /* Legacy status badge */
```

### Files
- `assets/css/tokens.css` — Design tokens
- `assets/css/base.css` — Reset, typography, layout
- `assets/css/components.css` — Buttons, cards, tables
- `assets/css/animations.css` — Motion
- `assets/css/graph.css` — Cytoscape styling

See also:
- `plans/dashboard/01-design-system.md` — Original design tokens
- `plans/dashboard/00-architecture.md` — Architecture overview
- `plans/dashboard/02-data-contracts.md` — Data schemas

## Hypergraph: Three-level drill-down

The Hypergraph page implements a hierarchical viewer over the `bsg.json`
artifact. All three levels share a single mounted Cytoscape instance and a
single page shell; level transitions swap `cy.elements()` in place rather
than tearing down the canvas.

| Level | Route                              | Nodes                 | Edges                                          | Click action                  |
|-------|------------------------------------|-----------------------|------------------------------------------------|-------------------------------|
| L1    | `#/hypergraph/files`               | one per source file   | aggregated (one weighted edge per file pair)   | navigate to L2 for that file  |
| L2    | `#/hypergraph/file/:fileId`        | symbols inside `file` | edges with both endpoints inside `file`        | navigate to L3 for that node  |
| L3    | `#/hypergraph/node/:nodeId`        | center + neighbors    | every edge incident to the center node         | re-focus on the clicked node  |

### Data source

All three projections are computed client-side in
`batho/dashboard/assets/js/bsg-projections.js`:

- `buildFileGraph(bsg)` — walks `bsg.edges` once, aggregating each edge into
  a `(sourceFile, targetFile)` bucket. Self-file edges are dropped; weight =
  count of underlying symbol edges; the `types` field records the breakdown
  by relationship type (`CALLS`, `IMPORTS`, ...). Result is memoized on the
  bsg reference via a `WeakMap`.
- `buildFileSubgraph(bsg, file)` — uses `indexes.nodes_by_file[file]` when
  present, falls back to scanning `bsg.nodes` when the index is missing.
- `buildNeighborhood(bsg, nodeId)` — uses `indexes.inbound_edges[id]` +
  `indexes.outbound_edges[id]` to resolve neighbors in O(1); falls back to
  a brute scan of `bsg.edges` for legacy artifacts.

No new backend artifact is required. The existing `bsg.json` payload
already carries the indexes the projections need.

### URL deep-linking

L2 and L3 routes carry the entity identifier as a URL-encoded path segment
(`#/hypergraph/file/src%2Fauth%2Flogin.py`). The router was extended in
`batho/dashboard/assets/js/router.js` to support a single `:param` segment
per route; matches expose the captured value via `params.get(name)`.
Browser back/forward and bookmarking work naturally.

### Breadcrumb

The header carries a breadcrumb `Files › <file> › <node>` whose segments
are clickable buttons that navigate up the hierarchy. The active segment
is rendered disabled.

### Adaptive filters

Filter facets shown in the sidebar adapt to the current level:

- **L1**: languages (dominant per file), services, categories, path glob.
- **L2 / L3**: types, languages, scope tiers, services, path glob.

Filter selections are retained per level in `_filterStateByLevel`, so
drilling down and back preserves intermediate filter context. On first
entry into a level every visible facet is selected by default.

### Performance

- Single Cytoscape instance, per-level `cy.elements().remove()` then
  `cy.add()` (no destroy/recreate).
- L1 derivation is `WeakMap`-memoized on the bsg payload identity.
- `bsg.json` payload itself is cached in `sessionStorage` keyed by
  `indexId:repoHash`.
- Aggregated edge widths are log-scaled (`weightLog = log₂(weight + 1)`)
  to keep dense L1 graphs readable.
- L2 ships a 2 000-node budget cap; oversize files render a placeholder
  card linking back to L1 or to the Files page.

### Layouts

Each level defaults to a layout tailored to its shape:

- L1: `fcose` (organic clustering, longer ideal edges).
- L2: `breadthfirst` (rooted, falls back to grid on failure).
- L3: `concentric` (center node weighted to the inner ring).

Users can still pick any of `cose / breadthfirst / concentric` from the
header at any level.
