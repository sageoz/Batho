/**
 * Hypergraph page — three-level drill-down viewer.
 *
 *   L1 (#/hypergraph/files)            : one node per file, weighted edges.
 *   L2 (#/hypergraph/file/:fileId)     : intra-file symbol graph.
 *   L3 (#/hypergraph/node/:nodeId)     : node + immediate neighborhood.
 *
 * A single Cytoscape instance is mounted for the lifetime of the page; per
 * level we swap elements via `cy.elements().remove() / cy.add()` so layout
 * transitions are smooth and cheap. Filter state is retained per level.
 */

import { loadIndex, loadBsg, loadGraph, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { router } from '../assets/js/router.js';
import { formatInt } from '../assets/js/format.js';
import { matchGlob } from '../assets/js/glob.js';
import { buildStylesheet } from '../assets/js/cy-stylesheet.js';
import { createChipFilter } from '../shared/components/chip-filter.js';
import { createDrawer, openDrawer } from '../shared/components/drawer.js';
import {
  buildFileGraph,
  buildFileSubgraph,
  buildNeighborhood,
} from '../assets/js/bsg-projections.js';

const LAYOUTS = ['cose', 'breadthfirst', 'concentric'];
const BSG_CACHE_PREFIX = 'batho.bsg:';
const BSG_CACHE_LIMIT_BYTES = 6_000_000;
const L2_NODE_BUDGET = 2000;

// Default layout per level. L2 prefers breadthfirst (file structure tends to
// have a clear hierarchy), L3 uses concentric (center node in the middle),
// and L1 falls back to fcose via 'cose' for organic file clustering.
const DEFAULT_LAYOUT_BY_LEVEL = {
  1: 'cose',
  2: 'breadthfirst',
  3: 'concentric',
};

// --- module-scoped state ---------------------------------------------------
// All persist for the page lifetime; cleared on route exit when the page
// element is unmounted by the router (no explicit teardown needed because
// the Cytoscape instance lives on the DOM node which is replaced).

let _cy = null;
let _bsgData = null;
let _drawer = null;
let _currentLevel = 1;
let _currentTarget = ''; // fileId for L2, nodeId for L3.
let _currentLayout = DEFAULT_LAYOUT_BY_LEVEL[1];
let _filterStateByLevel = {
  1: makeEmptyFilterState(),
  2: makeEmptyFilterState(),
  3: makeEmptyFilterState(),
};
let _facetCountsByLevel = { 1: null, 2: null, 3: null };

function makeEmptyFilterState() {
  return {
    types: new Set(),
    languages: new Set(),
    services: new Set(),
    scopes: new Set(),
    categories: new Set(),
    path: '',
    initialized: false,
  };
}

// --- entry point -----------------------------------------------------------

/**
 * Router handler. The router supplies a URLSearchParams object which may
 * carry the route's `:param` capture (`fileId` or `nodeId`) along with any
 * `?query=string` values such as `layout`.
 */
export async function renderHypergraph(params, routeMeta) {
  const container = document.createElement('div');
  container.className = 'page page--hypergraph';

  // Determine which level we are rendering from the matched route, falling
  // back to inspecting the params themselves when the meta is unavailable.
  const matchedRoute = routeMeta?.matchedRoute || '';
  let level = 1;
  let target = '';
  if (matchedRoute.includes('/file/') || params.get('fileId')) {
    level = 2;
    target = params.get('fileId') || '';
  } else if (matchedRoute.includes('/node/') || params.get('nodeId')) {
    level = 3;
    target = params.get('nodeId') || '';
  }

  _currentLevel = level;
  _currentTarget = target;
  _currentLayout = params.get('layout') && LAYOUTS.includes(params.get('layout'))
    ? params.get('layout')
    : DEFAULT_LAYOUT_BY_LEVEL[level];

  container.innerHTML = renderShellHtml();
  _drawer = createDrawer();
  container.appendChild(_drawer);

  const progressFill = container.querySelector('#graph-progress-fill');
  const progressLabel = container.querySelector('#graph-progress-label');
  setProgress(progressFill, progressLabel, 5, 'initializing…');

  try {
    const bsgData = await ensureBsgData(progressFill, progressLabel);
    _bsgData = bsgData;

    setProgress(progressFill, progressLabel, 60, 'building level view…');

    const cyEl = container.querySelector('#graph-canvas');
    const cytoscapeLib = await (await import('../assets/js/cy-import.js')).default();

    requestAnimationFrame(() => {
      try {
        // Boot empty Cytoscape once, then route into the active level which
        // pushes the right elements + layout.
        _cy = bootCytoscape(cytoscapeLib, cyEl);
        wireBreadcrumbAndLayout(container);
        loadLevel(container, level, target);
        setProgress(
          progressFill,
          progressLabel,
          100,
          `${describeLevel(level, target)} ready`
        );
        setTimeout(() => {
          const prog = container.querySelector('.graph-progress');
          if (prog) prog.classList.add('graph-progress--done');
        }, 1500);
      } catch (err) {
        console.error('[batho] Hypergraph init failed:', err);
        const canvasWrap = container.querySelector('.graph-canvas-wrap');
        if (canvasWrap) {
          canvasWrap.innerHTML = renderErrorPanel(err);
          const retryBtn = canvasWrap.querySelector('[data-action="retry"]');
          if (retryBtn) retryBtn.addEventListener('click', () => location.reload());
        }
      }
    });

    window.addEventListener('batho:index-changed', () => {
      // Force a clean reload when the active index changes — we have to
      // refetch the bsg artifact.
      router.handle();
    }, { once: true });
  } catch (err) {
    container.innerHTML = renderErrorPanel(err);
    const retryBtn = container.querySelector('[data-action="retry"]');
    if (retryBtn) retryBtn.addEventListener('click', () => location.reload());
  }

  return container;
}

// --- shell rendering -------------------------------------------------------

function renderShellHtml() {
  return `
    <div class="graph-shell">
      <div class="graph-header">
        <h1 class="panel__title graph-header__title">Hypergraph</h1>
        <nav class="graph-breadcrumb" id="graph-breadcrumb" aria-label="Drill-down"></nav>
        <div class="graph-header__controls">
          <div class="graph-layout-switcher" role="group" aria-label="Layout">
            ${LAYOUTS.map((l) => `<button class="btn graph-layout-btn" data-layout="${l}">${l}</button>`).join('')}
          </div>
        </div>
      </div>
      <div class="graph-body">
        <aside class="graph-sidebar" aria-label="Filters">
          <div class="graph-sidebar__section" id="graph-types-section">
            <div class="panel__title" style="font-size:10px;margin-bottom:4px">Types</div>
            <div id="graph-types-mount" class="graph-chip-group"></div>
          </div>
          <div class="graph-sidebar__section" id="graph-langs-section">
            <div class="panel__title" style="font-size:10px;margin-bottom:4px">Languages</div>
            <div id="graph-langs-mount" class="graph-chip-group"></div>
          </div>
          <div class="graph-sidebar__section" id="graph-services-section">
            <div class="panel__title" style="font-size:10px;margin-bottom:4px">Services</div>
            <div id="graph-services-mount" class="graph-chip-group"></div>
          </div>
          <div class="graph-sidebar__section" id="graph-scopes-section">
            <div class="panel__title" style="font-size:10px;margin-bottom:4px">Scope</div>
            <div id="graph-scopes-mount" class="graph-chip-group"></div>
          </div>
          <div class="graph-sidebar__section" id="graph-categories-section" hidden>
            <div class="panel__title" style="font-size:10px;margin-bottom:4px">Categories</div>
            <div id="graph-categories-mount" class="graph-chip-group"></div>
          </div>
          <div class="graph-sidebar__section">
            <div class="panel__title" style="font-size:10px;margin-bottom:4px">Path</div>
            <input class="graph-path-input" type="text" placeholder="glob: src/**/*.ts" aria-label="Path filter" />
          </div>
        </aside>
        <div class="graph-canvas-wrap">
          <div class="graph-canvas" id="graph-canvas"></div>
          <div class="graph-budget-warning" id="graph-budget-warning" hidden></div>
        </div>
      </div>
      <div class="graph-progress">
        <div class="graph-progress__bar"><div class="graph-progress__fill" id="graph-progress-fill"></div></div>
        <span class="graph-progress__label" id="graph-progress-label">loading…</span>
      </div>
    </div>
  `;
}

// --- BSG fetch + cache -----------------------------------------------------

async function ensureBsgData(progressFill, progressLabel) {
  const savedIndexId = localStorage.getItem('batho.activeIndexId');
  const indexData = await loadIndex();
  const activeIndexId = savedIndexId && indexData.indexes[savedIndexId]
    ? savedIndexId
    : indexData.currentIndexId;

  const indexEntry = indexData.indexes[activeIndexId] || null;
  const repoHash = indexEntry?.repoHash || '';
  const cacheKey = buildBsgCacheKey(activeIndexId, repoHash);
  const cachedBsg = readBsgCache(cacheKey);

  if (cachedBsg && cachedBsg.nodes?.length) {
    setProgress(progressFill, progressLabel, 45, 'using cached graph…');
    return cachedBsg;
  }

  setProgress(progressFill, progressLabel, 15, 'loading bsg…');
  let bsgData = null;
  let source = 'bsg';
  try {
    const bsgProgress = makeProgressReporter(progressFill, progressLabel, 15, 30, 'loading bsg…');
    bsgData = await loadBsg(activeIndexId, bsgProgress);
  } catch (_) {
    bsgData = null;
  }

  if (!bsgData || !bsgData.nodes?.length) {
    setProgress(progressFill, progressLabel, 30, 'loading graph fallback…');
    const graphProgress = makeProgressReporter(progressFill, progressLabel, 30, 20, 'loading graph…');
    const graphData = await loadGraph(activeIndexId, graphProgress);
    bsgData = {
      nodes: (graphData.entities || []).map((e) => ({
        id: e.id,
        type: (e.type || 'unknown').toUpperCase(),
        name: e.name || e.id,
        file: e.file || '',
        language: '',
        serviceTag: '',
        scopeTier: '',
        category: 'SOURCE',
        metadata: {},
      })),
      edges: (graphData.relationships || []).map((r) => ({
        sourceId: r.sourceId,
        targetId: r.targetId,
        type: (r.relationshipType || r.type || 'references').toLowerCase(),
      })),
    };
    source = 'graph';
  }

  if (cacheKey) {
    writeBsgCache(cacheKey, { ...bsgData, _cacheSource: source });
  }
  return bsgData;
}

// --- Cytoscape boot --------------------------------------------------------

function bootCytoscape(cytoscape, container) {
  const cy = cytoscape({
    container,
    elements: [],
    style: buildStylesheet(),
    layout: { name: 'preset', fit: true, padding: 40 },
    minZoom: 0.05,
    maxZoom: 8,
    wheelSensitivity: 0.2,
    hideEdgesOnViewport: true,
    hideLabelsOnViewport: true,
    textureOnViewport: true,
    motionBlur: false,
    desktopTapThreshold: 4,
  });

  // Click semantics:
  //   L1: click file node → navigate to L2.
  //   L2: click symbol node → navigate to L3.
  //   L3: click any node → navigate to L3 of that node (re-focus).
  cy.on('tap', 'node', (evt) => {
    const data = evt.target.data();
    if (_currentLevel === 1) {
      router.navigate('/hypergraph/file/' + encodeURIComponent(data.id));
    } else if (_currentLevel === 2) {
      router.navigate('/hypergraph/node/' + encodeURIComponent(data.id));
    } else {
      if (data.id && data.id !== _currentTarget) {
        router.navigate('/hypergraph/node/' + encodeURIComponent(data.id));
      } else {
        showNodeDrawer(data);
      }
    }
  });
  // Edge interactions (mostly for L1 aggregated edges).
  cy.on('tap', 'edge', (evt) => showEdgeDrawer(evt.target.data()));
  cy.on('mouseover', 'node', (evt) => { evt.target.addClass('hovered'); });
  cy.on('mouseout', 'node', (evt) => { evt.target.removeClass('hovered'); });
  cy.on('mouseover', 'edge', (evt) => { evt.target.addClass('hovered'); });
  cy.on('mouseout', 'edge', (evt) => { evt.target.removeClass('hovered'); });

  return cy;
}

// --- level dispatch --------------------------------------------------------

function loadLevel(container, level, target) {
  if (!_cy || !_bsgData) return;

  const budgetEl = container.querySelector('#graph-budget-warning');
  if (budgetEl) {
    budgetEl.hidden = true;
    budgetEl.innerHTML = '';
  }

  let elements;
  let facetCounts;
  let centerId = null;

  if (level === 2) {
    const { nodes, edges, file } = buildFileSubgraph(_bsgData, target);
    if (nodes.length > L2_NODE_BUDGET) {
      renderBudgetWarning(container, file, nodes.length);
      _cy.elements().remove();
      renderBreadcrumb(container, level, target);
      return;
    }
    elements = nodesToCyElements(nodes).concat(edgesToCyElements(edges, nodes));
    facetCounts = computeNodeFacets(nodes);
  } else if (level === 3) {
    const { nodes, edges, center } = buildNeighborhood(_bsgData, target);
    centerId = center;
    elements = nodesToCyElements(nodes, { centerId }).concat(edgesToCyElements(edges, nodes));
    facetCounts = computeNodeFacets(nodes);
  } else {
    const { nodes, edges } = buildFileGraph(_bsgData);
    elements = fileNodesToCyElements(nodes).concat(fileEdgesToCyElements(edges));
    facetCounts = computeFileFacets(nodes);
  }

  _cy.elements().remove();
  _cy.add(elements);
  _facetCountsByLevel[level] = facetCounts;

  buildFilterChipsForLevel(container, level, facetCounts);
  renderBreadcrumb(container, level, target);
  syncLayoutButtons(container);
  applyFilters();
  scheduleLayout(_currentLayout, centerId);
}

// --- element converters ----------------------------------------------------

function nodesToCyElements(nodes, opts = {}) {
  const out = new Array(nodes.length);
  for (let i = 0; i < nodes.length; i += 1) {
    const n = nodes[i];
    const type = (n.type || 'unknown').toUpperCase();
    const shortName = (n.name || n.id || '').split(/[/:.]/).pop() || n.id;
    const data = {
      id: n.id,
      label: n.name || n.id,
      shortName,
      kind: type,
      language: n.language || 'unknown',
      serviceTag: n.serviceTag || n.service_tag || '',
      scopeTier: n.scopeTier || n.scope_tier || '',
      category: (n.category || '') + '',
      file: n.file || '',
    };
    const classes = [];
    if (opts.centerId && n.id === opts.centerId) classes.push('center-node');
    out[i] = { data, classes: classes.join(' ') };
  }
  return out;
}

function edgesToCyElements(edges, nodes) {
  const ids = new Set();
  for (const n of nodes) ids.add(n.id);
  const out = [];
  const seen = new Set();
  for (const e of edges) {
    const source = e.sourceId ?? e.source_id ?? e.source;
    const target = e.targetId ?? e.target_id ?? e.target;
    if (!source || !target || !ids.has(source) || !ids.has(target)) continue;
    const relType = ((e.relationshipType ?? e.relationship_type ?? e.type ?? 'references') + '').toLowerCase();
    const key = `${source}\u0000${target}\u0000${relType}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      data: {
        id: `${source}->${target}:${relType}`,
        source,
        target,
        relationshipType: relType,
      },
    });
  }
  return out;
}

function fileNodesToCyElements(fileNodes) {
  const out = new Array(fileNodes.length);
  for (let i = 0; i < fileNodes.length; i += 1) {
    const n = fileNodes[i];
    const shortName = (n.file || '').split('/').pop() || n.file;
    out[i] = {
      data: {
        id: n.id,
        label: n.file,
        shortName,
        kind: 'FILE',
        language: n.language || 'unknown',
        serviceTag: n.serviceTag || '',
        category: n.category || '',
        scopeTier: '',
        file: n.file,
        nodeCount: n.nodeCount,
      },
      classes: 'file-node',
    };
  }
  return out;
}

function fileEdgesToCyElements(fileEdges) {
  const out = new Array(fileEdges.length);
  for (let i = 0; i < fileEdges.length; i += 1) {
    const e = fileEdges[i];
    const weightLog = Math.log2(e.weight + 1);
    out[i] = {
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        weight: e.weight,
        weightLog,
        types: e.types,
      },
      classes: 'aggregated',
    };
  }
  return out;
}

// --- breadcrumb + layout buttons ------------------------------------------

function wireBreadcrumbAndLayout(container) {
  container.querySelectorAll('.graph-layout-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      _currentLayout = btn.dataset.layout;
      syncLayoutButtons(container);
      runLayout(_currentLayout, _currentLevel === 3 ? _currentTarget : null);
    });
  });

  const pathInput = container.querySelector('.graph-path-input');
  if (pathInput) {
    const onPathInput = debounce(() => {
      filterStateForLevel().path = pathInput.value.trim();
      applyFilters();
    }, 150);
    pathInput.addEventListener('input', onPathInput);
  }
}

function renderBreadcrumb(container, level, target) {
  const el = container.querySelector('#graph-breadcrumb');
  if (!el) return;

  const segments = [
    { label: 'Files', route: '/hypergraph/files', active: level === 1 },
  ];

  if (level >= 2) {
    let fileForCrumb = target;
    if (level === 3) {
      const nodeRec = _bsgData?.nodes?.find?.((n) => n.id === target);
      fileForCrumb = nodeRec?.file || '';
    }
    if (fileForCrumb) {
      segments.push({
        label: fileForCrumb,
        route: '/hypergraph/file/' + encodeURIComponent(fileForCrumb),
        active: level === 2,
      });
    }
  }

  if (level === 3) {
    const nodeRec = _bsgData?.nodes?.find?.((n) => n.id === target);
    segments.push({
      label: nodeRec?.name || target,
      route: '/hypergraph/node/' + encodeURIComponent(target),
      active: true,
    });
  }

  el.innerHTML = segments.map((s, i) => `
    <span class="graph-breadcrumb__sep" ${i === 0 ? 'hidden' : ''}>›</span>
    <button class="graph-breadcrumb__seg ${s.active ? 'graph-breadcrumb__seg--active' : ''}"
            data-route="${escapeAttr(s.route)}"
            title="${escapeAttr(s.label)}"
            ${s.active ? 'disabled' : ''}>${escapeHtml(truncate(s.label, 48))}</button>
  `).join('');

  el.querySelectorAll('button[data-route]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const r = btn.dataset.route;
      if (r) router.navigate(r);
    });
  });
}

function syncLayoutButtons(container) {
  container.querySelectorAll('.graph-layout-btn').forEach((btn) => {
    btn.classList.toggle('graph-layout-btn--active', btn.dataset.layout === _currentLayout);
  });
}

// --- filter machinery ------------------------------------------------------

function filterStateForLevel() {
  return _filterStateByLevel[_currentLevel];
}

function computeFileFacets(fileNodes) {
  const langs = {};
  const services = {};
  const categories = {};
  for (const n of fileNodes) {
    if (n.language) langs[n.language] = (langs[n.language] || 0) + 1;
    if (n.serviceTag) services[n.serviceTag] = (services[n.serviceTag] || 0) + 1;
    if (n.category) categories[n.category] = (categories[n.category] || 0) + 1;
  }
  return { langs, services, categories, types: null, scopes: null };
}

function computeNodeFacets(nodes) {
  const types = {};
  const langs = {};
  const services = {};
  const scopes = {};
  for (const n of nodes) {
    const t = (n.type || 'unknown').toUpperCase();
    types[t] = (types[t] || 0) + 1;
    const l = n.language || 'unknown';
    langs[l] = (langs[l] || 0) + 1;
    if (n.serviceTag) services[n.serviceTag] = (services[n.serviceTag] || 0) + 1;
    const scope = n.scopeTier || n.scope_tier;
    if (scope) scopes[scope] = (scopes[scope] || 0) + 1;
  }
  return { types, langs, services, scopes, categories: null };
}

function buildFilterChipsForLevel(container, level, facets) {
  const typesSection = container.querySelector('#graph-types-section');
  const scopesSection = container.querySelector('#graph-scopes-section');
  const categoriesSection = container.querySelector('#graph-categories-section');

  // Show/hide sections appropriate to the level.
  if (typesSection) typesSection.hidden = !facets.types;
  if (scopesSection) scopesSection.hidden = !facets.scopes;
  if (categoriesSection) categoriesSection.hidden = !facets.categories;

  // Reset chip mounts.
  for (const id of ['types', 'langs', 'services', 'scopes', 'categories']) {
    const mount = container.querySelector(`#graph-${id}-mount`);
    if (mount) mount.innerHTML = '';
  }

  // First-time selection seed: pick everything visible.
  const state = filterStateForLevel();
  if (!state.initialized) {
    if (facets.types) state.types = new Set(Object.keys(facets.types));
    if (facets.langs) state.languages = new Set(Object.keys(facets.langs));
    if (facets.services) state.services = new Set(Object.keys(facets.services));
    if (facets.scopes) state.scopes = new Set(Object.keys(facets.scopes));
    if (facets.categories) state.categories = new Set(Object.keys(facets.categories));
    state.initialized = true;
  }

  const mounts = [
    ['types', facets.types, state.types],
    ['langs', facets.langs, state.languages],
    ['services', facets.services, state.services],
    ['scopes', facets.scopes, state.scopes],
    ['categories', facets.categories, state.categories],
  ];

  for (const [key, counts, selected] of mounts) {
    if (!counts) continue;
    const mount = container.querySelector(`#graph-${key}-mount`);
    if (!mount) continue;
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    for (const [label, count] of sorted) {
      const chip = createChipFilter({
        label,
        count,
        active: selected.has(label),
        onChange: (active) => {
          if (active) selected.add(label);
          else selected.delete(label);
          applyFilters();
        },
      });
      mount.appendChild(chip);
    }
  }

  const pathInput = container.querySelector('.graph-path-input');
  if (pathInput) pathInput.value = state.path || '';
}

function applyFilters() {
  if (!_cy) return;
  const state = filterStateForLevel();
  const facets = _facetCountsByLevel[_currentLevel] || {};

  _cy.batch(() => {
    _cy.nodes().forEach((node) => {
      const d = node.data();
      let visible = true;

      if (facets.types && !state.types.has(d.kind)) visible = false;
      if (visible && facets.langs && !state.languages.has(d.language)) visible = false;
      if (visible && facets.services && d.serviceTag && state.services.size > 0
          && !state.services.has(d.serviceTag)) visible = false;
      if (visible && facets.scopes && d.scopeTier && state.scopes.size > 0
          && !state.scopes.has(d.scopeTier)) visible = false;
      if (visible && facets.categories && d.category && state.categories.size > 0
          && !state.categories.has(d.category)) visible = false;
      if (visible && state.path && !matchGlob(state.path, d.file || d.id || '')) visible = false;

      if (visible) node.removeClass('filtered-out');
      else node.addClass('filtered-out');
    });

    // Edges hide when either endpoint is filtered out.
    _cy.edges().forEach((edge) => {
      const src = edge.source();
      const tgt = edge.target();
      const hidden = src.hasClass('filtered-out') || tgt.hasClass('filtered-out');
      if (hidden) edge.addClass('filtered-out');
      else edge.removeClass('filtered-out');
    });
  });
}

// --- layout runner ---------------------------------------------------------

function scheduleLayout(name, centerId) {
  const run = () => runLayout(name, centerId);
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(run, { timeout: 400 });
  } else {
    setTimeout(run, 0);
  }
}

function runLayout(name, centerId) {
  if (!_cy) return;
  try {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const nodeCount = _cy.nodes().length;
    const animate = nodeCount < 1500 && !prefersReducedMotion;
    const animationDuration = animate ? 400 : 0;
    const layoutName = name === 'cose' ? 'fcose' : name;

    const opts = {
      name: layoutName,
      animate,
      animationDuration,
      fit: true,
      padding: 40,
    };

    if (layoutName === 'fcose') {
      Object.assign(opts, {
        quality: nodeCount > 5000 ? 'draft' : 'default',
        randomize: false,
        nodeRepulsion: 4500,
        idealEdgeLength: _currentLevel === 1 ? 110 : 50,
        nodeSeparation: 75,
        packComponents: true,
        sampleSize: 25,
      });
    } else if (name === 'cose') {
      Object.assign(opts, {
        nodeRepulsion: () => 4000,
        idealEdgeLength: () => 50,
        randomize: false,
      });
    } else if (name === 'breadthfirst') {
      Object.assign(opts, { directed: true, spacingFactor: 1.2 });
    } else if (name === 'concentric') {
      Object.assign(opts, {
        concentric: (n) => (centerId && n.data('id') === centerId ? 1000 : n.degree()),
        levelWidth: () => 3,
      });
    }

    _cy.layout(opts).run();
  } catch (_) {
    try {
      _cy.layout({ name: 'grid', fit: true, padding: 40 }).run();
    } catch (_e) {
      // ignore
    }
  }
}

// --- drawer for node + edge details ---------------------------------------

function showNodeDrawer(data) {
  if (!_drawer) return;
  const props = [
    ['id', data.id],
    ['name', data.label],
    ['type', data.kind],
    ['language', data.language],
    ['service', data.serviceTag],
    ['scope', data.scopeTier],
    ['category', data.category],
    ['file', data.file],
    ['node count', data.nodeCount],
  ].filter(([, v]) => v !== undefined && v !== null && v !== '');

  let metaHtml = '';
  const bsgNode = _bsgData?.nodes?.find?.((n) => n.id === data.id);
  if (bsgNode?.metadata && typeof bsgNode.metadata === 'object') {
    const entries = Object.entries(bsgNode.metadata).filter(([, v]) => v != null && v !== '');
    if (entries.length) {
      metaHtml = `<div class="drawer-section"><div class="drawer-section__title">Metadata</div>${
        entries.map(([k, v]) =>
          `<div class="drawer-prop"><span class="drawer-prop__key">${escapeHtml(k)}</span><span class="drawer-prop__val" title="${escapeHtml(String(v))}">${escapeHtml(String(v))}</span></div>`
        ).join('')
      }</div>`;
    }
  }

  const propsHtml = props.map(([k, v]) =>
    `<div class="drawer-prop"><span class="drawer-prop__key">${escapeHtml(k)}</span><span class="drawer-prop__val" title="${escapeHtml(String(v))}">${escapeHtml(String(v))}</span></div>`
  ).join('');

  openDrawer(_drawer, { title: data.label || data.id || 'Node', content: propsHtml + metaHtml });
}

function showEdgeDrawer(data) {
  if (!_drawer) return;
  const baseProps = [
    ['source', data.source],
    ['target', data.target],
    ['weight', data.weight],
    ['relationship', data.relationshipType],
  ].filter(([, v]) => v !== undefined && v !== null && v !== '');

  let breakdownHtml = '';
  if (data.types && typeof data.types === 'object') {
    const entries = Object.entries(data.types).sort((a, b) => b[1] - a[1]);
    if (entries.length) {
      breakdownHtml = `<div class="drawer-section"><div class="drawer-section__title">Relationship Types</div>${
        entries.map(([k, v]) =>
          `<div class="drawer-prop"><span class="drawer-prop__key">${escapeHtml(k)}</span><span class="drawer-prop__val">${escapeHtml(String(v))}</span></div>`
        ).join('')
      }</div>`;
    }
  }

  const propsHtml = baseProps.map(([k, v]) =>
    `<div class="drawer-prop"><span class="drawer-prop__key">${escapeHtml(k)}</span><span class="drawer-prop__val" title="${escapeHtml(String(v))}">${escapeHtml(String(v))}</span></div>`
  ).join('');

  openDrawer(_drawer, {
    title: data.id || 'Edge',
    content: propsHtml + breakdownHtml,
  });
}

function renderBudgetWarning(container, file, count) {
  const budgetEl = container.querySelector('#graph-budget-warning');
  if (!budgetEl) return;
  budgetEl.hidden = false;
  budgetEl.innerHTML = `
    <div class="panel">
      <div class="panel__title">Large File</div>
      <p style="font-size:12px;line-height:1.4;color:var(--dim, #9e9e9e)">
        <strong>${escapeHtml(file)}</strong> contains ${formatInt(count)} entities,
        above the L2 render budget of ${formatInt(L2_NODE_BUDGET)}.
      </p>
      <div style="display:flex;gap:8px;margin-top:8px">
        <button class="btn" data-action="open-files">Open in Files</button>
        <button class="btn btn--ghost" data-action="back">Back to L1</button>
      </div>
    </div>
  `;
  const openBtn = budgetEl.querySelector('[data-action="open-files"]');
  if (openBtn) openBtn.addEventListener('click', () => router.navigate('/files', { path: file }));
  const backBtn = budgetEl.querySelector('[data-action="back"]');
  if (backBtn) backBtn.addEventListener('click', () => router.navigate('/hypergraph/files'));
}

// --- BSG sessionStorage cache helpers --------------------------------------

function buildBsgCacheKey(indexId, repoHash) {
  if (!indexId) return null;
  return repoHash
    ? `${BSG_CACHE_PREFIX}${indexId}:${repoHash}`
    : `${BSG_CACHE_PREFIX}${indexId}`;
}

function readBsgCache(key) {
  if (!key) return null;
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (_) {
    return null;
  }
}

function writeBsgCache(key, data) {
  if (!key || !data) return;
  try {
    const raw = JSON.stringify(data);
    if (raw.length > BSG_CACHE_LIMIT_BYTES) return;
    sessionStorage.setItem(key, raw);
  } catch (_) { /* quota / privacy mode */ }
}

// --- misc helpers ----------------------------------------------------------

function makeProgressReporter(fill, label, base, span, text) {
  return (evt) => {
    if (!evt || typeof evt.percent !== 'number') return;
    const pct = Math.min(base + span, base + Math.round((evt.percent / 100) * span));
    setProgress(fill, label, pct, text);
  };
}

function setProgress(fill, label, pct, text) {
  if (fill) fill.style.width = `${pct}%`;
  if (label) label.textContent = text;
}

function describeLevel(level, target) {
  if (level === 2) return `L2 ${target || ''}`;
  if (level === 3) return `L3 ${target || ''}`;
  return 'L1 file graph';
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, '&quot;');
}

function truncate(text, max) {
  if (!text || text.length <= max) return text || '';
  return '…' + text.slice(-(max - 1));
}

function renderErrorPanel(err) {
  const title = err?.name === 'MissingArtifactError' ? 'Missing Artifact' : 'Error';
  const message = err?.message || 'An unknown error occurred';
  const hint = err?.name === 'MissingArtifactError'
    ? 'Run <code>batho scan</code> to generate BSG artifacts.'
    : '';
  return `
    <div class="page page--hypergraph">
      <div class="panel error-panel">
        <div class="error-panel__icon">⚠</div>
        <div class="error-panel__title">${escapeHtml(title)}</div>
        <div class="error-panel__message">${escapeHtml(message)}</div>
        ${hint ? `<div class="error-panel__hint">${hint}</div>` : ''}
        <div class="error-panel__actions">
          <button class="btn" data-action="retry">retry</button>
        </div>
      </div>
    </div>
  `;
}

// MissingArtifactError is imported above for type clarity; re-export so any
// stale call site keeps working.
export { MissingArtifactError };
