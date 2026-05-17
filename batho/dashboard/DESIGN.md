# Batho Dashboard Design

The canonical dashboard design tokens live in:
- `plans/dashboard/01-design-system.md` — Design tokens and components
- `plans/dashboard/00-architecture.md` — Architecture overview
- `plans/dashboard/02-data-contracts.md` — Data schemas

See `phase-0-skeleton.md` for the original implementation plan.

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
