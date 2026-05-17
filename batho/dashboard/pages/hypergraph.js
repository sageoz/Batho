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
import { buildStylesheet } from '../assets/js/cy-stylesheet.js?v=2';
import { createChipFilter } from '../shared/components/chip-filter.js';
import { createDrawer, openDrawer, closeDrawer } from '../shared/components/drawer.js';
import {
  buildFileGraph,
  buildFileSubgraph,
  buildNeighborhood,
  listBsgFiles,
} from '../assets/js/bsg-projections.js';

const LAYOUTS = ['cose', 'breadthfirst', 'concentric', 'circle', 'grid'];
const BSG_CACHE_PREFIX = 'batho.bsg:';
const BSG_CACHE_LIMIT_BYTES = 6_000_000;
const L2_NODE_BUDGET = 2000;

// Default layout per level. L2 prefers breadthfirst (file structure tends to
// have a clear hierarchy), L3 uses concentric (center node in the middle),
// and L1 falls back to cose for organic file clustering.
const DEFAULT_LAYOUT_BY_LEVEL = {
  1: 'cose',
  2: 'breadthfirst',
  3: 'concentric',
};

// --- module-scoped state ---------------------------------------------------
// Persist across route changes for caching; explicit teardown on unmount
// prevents leaked Cytoscape instances and stale event handlers.

let _cy = null;
let _bsgData = null;
let _drawer = null;
let _currentLevel = 1;
let _currentTarget = '';
let _currentLayout = DEFAULT_LAYOUT_BY_LEVEL[1];
let _filterStateByLevel = {
  1: makeEmptyFilterState(),
  2: makeEmptyFilterState(),
  3: makeEmptyFilterState(),
};
let _facetCountsByLevel = { 1: null, 2: null, 3: null };
let _pageAbortController = null;
let _tooltipEl = null;
let _focusNodeId = null;
let _cleanupRegistered = false;
let _navigating = false;
let _l2Mode = 'clustered';
let _l2PaginatedCount = 500;
let _shortcutsOverlay = null;
let _minimapCanvas = null;
let _minimapRAF = null;
let _renderStartTime = 0;
let _matchBannerEl = null;
let _exportMenu = null;
let _cyResizeObserver = null;
let _cyContainer = null;
let _nodePositionsByLevel = { 1: new Map(), 2: new Map(), 3: new Map() };
let _pendingSingleTap = null;
let _lastTapNodeId = null;

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
  // Ensure we clean up BEFORE the router removes the DOM container,
  // so Cytoscape can properly detach its global listeners.
  if (!_cleanupRegistered) {
    _cleanupRegistered = true;
    router.on('change', () => {
      console.debug('[batho] Router change - cleaning up hypergraph');
      if (_cy) { try { _cy.destroy(); } catch (_) {} _cy = null; }
      if (_drawer) { try { _drawer.remove(); } catch (_) {} _drawer = null; }
      if (_pageAbortController) { try { _pageAbortController.abort(); } catch (_) {} _pageAbortController = null; }
      if (_cyResizeObserver) { try { _cyResizeObserver.disconnect(); } catch (_) {} _cyResizeObserver = null; }
      _cyContainer = null;
      if (_pendingSingleTap) { clearTimeout(_pendingSingleTap); _pendingSingleTap = null; }
      _focusNodeId = null;
      _tooltipEl = null;
      _navigating = false;
      if (_shortcutsOverlay) { try { _shortcutsOverlay.remove(); } catch (_) {} _shortcutsOverlay = null; }
      if (_minimapRAF) { cancelAnimationFrame(_minimapRAF); _minimapRAF = null; }
      _minimapCanvas = null;
      _matchBannerEl = null;
      if (_exportMenu) { try { _exportMenu.remove(); } catch (_) {} _exportMenu = null; }
    });
  }

  // Tear down any previous instance (defensive fallback for page reloads).
  if (_cy) {
    try { _cy.destroy(); } catch (_) {}
    _cy = null;
  }
  if (_drawer) {
    try { _drawer.remove(); } catch (_) {}
    _drawer = null;
  }
  if (_pageAbortController) {
    try { _pageAbortController.abort(); } catch (_) {}
    _pageAbortController = null;
  }
  _focusNodeId = null;

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

  // Reset filter state when entering a new level/target combination to prevent
  // stale filters from hiding all nodes
  const filterKey = `${level}:${target}`;
  const lastFilterKey = `_lastFilterKey_${level}`;
  if (window[lastFilterKey] !== filterKey) {
    window[lastFilterKey] = filterKey;
    _filterStateByLevel[level] = makeEmptyFilterState();
    console.debug('[batho] Reset filter state for', filterKey);
  }

  _currentLevel = level;
  _currentTarget = target;
  _currentLayout = params.get('layout') && LAYOUTS.includes(params.get('layout'))
    ? params.get('layout')
    : DEFAULT_LAYOUT_BY_LEVEL[level];

  container.innerHTML = renderShellHtml();
  _drawer = createDrawer();
  container.appendChild(_drawer);
  _pageAbortController = new AbortController();

  const progressFill = container.querySelector('#graph-progress-fill');
  const progressLabel = container.querySelector('#graph-progress-label');
  setProgress(progressFill, progressLabel, 5, 'initializing…');

  // Add timeout protection for data loading
  const BSG_LOAD_TIMEOUT = 30000; // 30 seconds

  try {
    const bsgData = await Promise.race([
      ensureBsgData(progressFill, progressLabel),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('BSG data loading timed out after 30s')), BSG_LOAD_TIMEOUT)
      )
    ]);
    _bsgData = bsgData;

    // Validate BSG data
    if (!_bsgData || !_bsgData.nodes) {
      throw new Error('Invalid BSG data: no nodes found. Run "batho scan" to generate graph data.');
    }

    setProgress(progressFill, progressLabel, 60, 'building level view…');

    const cyEl = container.querySelector('#graph-canvas');
    const cytoscapeLib = await (await import('../assets/js/cy-import.js?v=3')).default();

    // Use ResizeObserver to ensure Cytoscape boots with proper container dimensions
    // and stays responsive to size changes
    const canvasWrap = container.querySelector('.graph-canvas-wrap');
    let cyBooted = false;
    let resizeDebounceTimer = null;

    const bootCyWhenReady = () => {
      if (cyBooted || !cyEl || !canvasWrap) return;
      
      const rect = cyEl.getBoundingClientRect();
      
      if (rect.width > 0 && rect.height > 0 && cyEl.isConnected) {
        cyBooted = true;
        
        // Clean up previous resize observer if exists
        if (_cyResizeObserver) {
          _cyResizeObserver.disconnect();
        }
        
        // Set up ResizeObserver for responsive resizing
        _cyResizeObserver = new ResizeObserver((entries) => {
          if (resizeDebounceTimer) clearTimeout(resizeDebounceTimer);
          resizeDebounceTimer = setTimeout(() => {
            if (_cy && _cy.container()?.isConnected) {
              _cy.resize();
              console.debug('[batho] Cytoscape resized via ResizeObserver');
            }
          }, 50);
        });
        _cyResizeObserver.observe(canvasWrap);
        _cyContainer = canvasWrap;

        try {
          // Boot empty Cytoscape once, then route into the active level which
          // pushes the right elements + layout.
          _cy = bootCytoscape(cytoscapeLib, cyEl);
          wireBreadcrumbAndLayout(container);
          loadLevel(container, level, target);
          if (progressFill) progressFill.style.width = '100%';
          setTimeout(() => {
            const prog = container.querySelector('.graph-progress');
            if (prog) prog.classList.add('graph-progress--done');
          }, 1500);
        } catch (err) {
          console.error('[batho] Hypergraph init failed:', err);
          hideSkeleton(container);
          canvasWrap.innerHTML = renderErrorPanel(err);
          const retryBtn = canvasWrap.querySelector('[data-action="retry"]');
          if (retryBtn) retryBtn.addEventListener('click', () => location.reload());
        }
      }
    };

    // Try immediately, then use requestAnimationFrame as fallback
    bootCyWhenReady();
    if (!cyBooted) {
      requestAnimationFrame(() => {
        bootCyWhenReady();
        // Final fallback after a delay
        if (!cyBooted) {
          setTimeout(bootCyWhenReady, 100);
        }
      });
    }

    window.addEventListener('batho:index-changed', () => {
      // Force a clean reload when the active index changes — we have to
      // refetch the bsg artifact.
      router.handle();
    }, { once: true, signal: _pageAbortController.signal });
  } catch (err) {
    hideSkeleton(container); // Ensure skeleton is hidden on error
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
      <header class="graph-header">
        <div class="graph-header__brand">
          <img class="graph-header__icon" src="/dashboard/assets/img/batho-logo.svg" alt="" width="22" height="22" />
          <div class="graph-header__heading">
            <h1 class="graph-header__title">Hypergraph</h1>
            <span class="graph-header__subtitle">three-level drill-down · files → file → node</span>
          </div>
        </div>
        <nav class="graph-breadcrumb" id="graph-breadcrumb" aria-label="Drill-down"></nav>
        <div class="graph-header__controls">
          <div class="graph-stats" id="graph-stats">
            <span class="graph-stat" title="Visible nodes">
              <span class="graph-stat__dot graph-stat__dot--node"></span>
              <span class="graph-stat__value" id="graph-stat-nodes">—</span>
              <span class="graph-stat__label">nodes</span>
            </span>
            <span class="graph-stat" title="Visible edges">
              <span class="graph-stat__dot graph-stat__dot--edge"></span>
              <span class="graph-stat__value" id="graph-stat-edges">—</span>
              <span class="graph-stat__label">edges</span>
            </span>
            <span class="graph-stat graph-stat--time" title="Render time" id="graph-stat-time-wrap" hidden>
              <span class="graph-stat__value" id="graph-stat-time">—</span>
              <span class="graph-stat__label">ms</span>
            </span>
          </div>
          <div class="graph-layout-switcher" role="group" aria-label="Layout">
            <span class="graph-layout-switcher__label">layout</span>
            ${LAYOUTS.map((l) => `<button class="graph-layout-btn" data-layout="${l}" title="Apply ${l} layout">${l}</button>`).join('')}
          </div>
        </div>
      </header>
      <div class="graph-body">
        <aside class="graph-sidebar" aria-label="Filters">
          <div class="graph-sidebar__header">
            <span class="graph-sidebar__title">Filters</span>
            <button class="graph-sidebar__reset" id="graph-filter-reset" title="Reset all filters">reset</button>
          </div>
          <div class="graph-sidebar__scroll">
            <div class="graph-sidebar__section" id="graph-types-section">
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">Types</span>
                <span class="graph-sidebar__hint" id="graph-types-count"></span>
              </div>
              <div id="graph-types-mount" class="graph-chip-group"></div>
            </div>
            <div class="graph-sidebar__section" id="graph-langs-section">
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">Languages</span>
                <span class="graph-sidebar__hint" id="graph-langs-count"></span>
              </div>
              <div id="graph-langs-mount" class="graph-chip-group"></div>
            </div>
            <div class="graph-sidebar__section" id="graph-services-section">
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">Services</span>
                <span class="graph-sidebar__hint" id="graph-services-count"></span>
              </div>
              <div id="graph-services-mount" class="graph-chip-group"></div>
            </div>
            <div class="graph-sidebar__section" id="graph-scopes-section">
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">Scope</span>
                <span class="graph-sidebar__hint" id="graph-scopes-count"></span>
              </div>
              <div id="graph-scopes-mount" class="graph-chip-group"></div>
            </div>
            <div class="graph-sidebar__section" id="graph-categories-section">
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">Categories</span>
                <span class="graph-sidebar__hint" id="graph-categories-count"></span>
              </div>
              <div id="graph-categories-mount" class="graph-chip-group"></div>
            </div>
            <div class="graph-sidebar__section" id="graph-l2-insights" hidden>
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">File Insights</span>
              </div>
              <div class="graph-stats-compact">
                <div id="insight-imports">Imports: <span>-</span></div>
                <div id="insight-exports">Exports: <span>-</span></div>
                <div id="insight-complexity">Classes/Funcs: <span>-</span></div>
              </div>
            </div>
            <div class="graph-sidebar__section" id="graph-l2-mode-section" hidden>
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">View Mode</span>
              </div>
              <div class="graph-l2-mode-toggle" id="graph-l2-mode-toggle" role="group" aria-label="L2 View Mode">
                <button class="graph-l2-mode-btn graph-l2-mode-btn--active" data-mode="clustered">Clustered</button>
                <button class="graph-l2-mode-btn" data-mode="paginated">Paginated</button>
              </div>
            </div>
            <div class="graph-sidebar__section" id="graph-l2-search-section" hidden>
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">Search</span>
              </div>
              <div class="graph-l2-search">
                <span class="graph-l2-search__icon" aria-hidden="true">⌕</span>
                <input class="graph-l2-search__input" type="text" placeholder="filter symbols… (/)" aria-label="Search within file" />
              </div>
            </div>
            <div class="graph-sidebar__section" id="graph-l2-structure" hidden>
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">Structure</span>
              </div>
              <div class="graph-structure-tree" id="graph-structure-tree"></div>
            </div>
            <div class="graph-sidebar__section" id="graph-l2-deps" hidden>
              <div class="graph-sidebar__label">
                <span class="graph-sidebar__label-title">Dependencies</span>
              </div>
              <div id="graph-deps-inbound" class="graph-dep-section" hidden></div>
              <div id="graph-deps-outbound" class="graph-dep-section" hidden></div>
            </div>
            <div class="graph-sidebar__section">
              <div class="graph-sidebar__label"><span>Path glob</span></div>
              <div class="graph-path-wrap">
                <span class="graph-path-icon" aria-hidden="true">⌕</span>
                <input class="graph-path-input" type="text" placeholder="src/**/*.ts" aria-label="Path filter" />
              </div>
            </div>
          </div>
        </aside>
        <div class="graph-canvas-wrap">
          <div class="graph-match-banner" id="graph-match-banner" hidden></div>
          <div class="graph-canvas" id="graph-canvas"></div>
          <div class="graph-canvas__hint" id="graph-canvas-hint" aria-hidden="true">
            <span class="graph-canvas__hint-row">🖱️ Interaction Guide</span>
            <span class="graph-canvas__hint-row"><kbd>click</kbd> select + details</span>
            <span class="graph-canvas__hint-row"><kbd>double-click</kbd> navigate</span>
            <span class="graph-canvas__hint-row"><kbd>scroll</kbd> zoom</span>
            <span class="graph-canvas__hint-row"><kbd>drag</kbd> pan</span>
            <span class="graph-canvas__hint-row"><kbd>+ / -</kbd> zoom</span>
            <span class="graph-canvas__hint-row"><kbd>f</kbd> fit</span>
            <span class="graph-canvas__hint-row"><kbd>esc</kbd> clear selection</span>
          </div>
          <div class="graph-zoom-controls" role="group" aria-label="Zoom">
            <button class="graph-zoom-btn" data-action="zoom-in" title="Zoom in" aria-label="Zoom in">+</button>
            <button class="graph-zoom-btn" data-action="zoom-out" title="Zoom out" aria-label="Zoom out">−</button>
            <button class="graph-zoom-btn" data-action="fit" title="Fit to view" aria-label="Fit">⤢</button>
          </div>
          <div class="graph-legend" id="graph-legend" aria-label="Edge legend">
            <div class="graph-legend__title">edges</div>
            <div class="graph-legend__items">
              <span class="graph-legend__item"><i class="graph-legend__swatch graph-legend__swatch--calls"></i>calls</span>
              <span class="graph-legend__item"><i class="graph-legend__swatch graph-legend__swatch--contains"></i>contains</span>
              <span class="graph-legend__item"><i class="graph-legend__swatch graph-legend__swatch--imports"></i>imports</span>
              <span class="graph-legend__item"><i class="graph-legend__swatch graph-legend__swatch--extends"></i>extends</span>
              <span class="graph-legend__item"><i class="graph-legend__swatch graph-legend__swatch--implements"></i>implements</span>
              <span class="graph-legend__item"><i class="graph-legend__swatch graph-legend__swatch--references"></i>references</span>
            </div>
          </div>
          <div class="graph-budget-warning" id="graph-budget-warning" hidden></div>
          <div class="graph-tooltip" id="graph-tooltip" hidden></div>
          <div class="graph-minimap" id="graph-minimap" hidden><canvas></canvas><div class="graph-minimap__viewport"></div></div>
          <div class="graph-skeleton" id="graph-skeleton" hidden>
            <div class="graph-skeleton__nodes">
              <div class="graph-skeleton__dot"></div>
              <div class="graph-skeleton__dot"></div>
              <div class="graph-skeleton__dot"></div>
              <div class="graph-skeleton__dot"></div>
              <div class="graph-skeleton__dot"></div>
              <div class="graph-skeleton__dot"></div>
            </div>
            <div class="graph-skeleton__msg">Loading graph</div>
          </div>
        </div>
      </div>
      <div class="graph-progress" id="graph-progress">
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
    zoomingEnabled: true,
    userZoomingEnabled: true,
    panningEnabled: true,
    userPanningEnabled: true,
    motionBlur: false,
  });

  // Click semantics (REVISED for better UX):
  //   Single click: select node + focus mode (highlight neighbourhood) + show drawer
  //   Double click: navigate to next level
  //   L1: dbl-click file node → navigate to L2.
  //   L2: dbl-click symbol node → navigate to L3.
  //   L3: dbl-click any node → navigate to L3 of that node (re-focus).
  // Using native dbltap + delayed tap for clean single-vs-double semantics.
  let _selectedNodeId = null;

  function handleNodeSingleTap(evt) {
    const data = evt.target.data();
    const id = data.id;
    const cyInstance = evt.cy;
    if (!id) return;

    // Cancel any pending single tap if we get a double tap
    if (_pendingSingleTap) {
      clearTimeout(_pendingSingleTap);
      _pendingSingleTap = null;
    }

    // Delay single-tap action to allow dbltap to preempt
    _pendingSingleTap = setTimeout(() => {
      _pendingSingleTap = null;
      _lastTapNodeId = null;
      
      // Always select the node visually
      cyInstance.nodes().unselect();
      evt.target.select();
      _selectedNodeId = id;

      // Single click: focus mode + show drawer
      setFocusNode(id, cyInstance);
      showNodeDrawer(data);
    }, 250);
    
    _lastTapNodeId = id;
  }

  function handleNodeDoubleTap(evt) {
    const data = evt.target.data();
    const id = data.id;
    const cyInstance = evt.cy;
    if (!id) {
      console.warn('[batho] Node dbltap: missing data.id');
      return;
    }

    // Cancel pending single tap
    if (_pendingSingleTap) {
      clearTimeout(_pendingSingleTap);
      _pendingSingleTap = null;
    }

    console.debug('[batho] Node double tap:', id);

    // Double-click: navigate
    if (_navigating) return;
    _navigating = true;

    if (_currentLevel === 1) {
      const targetRoute = data.file || id;
      if (!targetRoute) {
        console.warn('[batho] L1 node dbl-tap: no file or id to navigate');
        _navigating = false;
        return;
      }
      router.navigate('/hypergraph/file/' + encodeURIComponent(targetRoute));
    } else if (_currentLevel === 2) {
      if (!_bsgData?.nodes?.some?.((n) => n.id === id)) {
        showToast(`Node "${id}" not found in graph data`);
        _navigating = false;
        return;
      }
      router.navigate('/hypergraph/node/' + encodeURIComponent(id));
    } else {
      if (id !== _currentTarget) {
        router.navigate('/hypergraph/node/' + encodeURIComponent(id));
      } else {
        showNodeDrawer(data);
      }
    }
    setTimeout(() => { _navigating = false; }, 300);
  }

  // Use native tap + dbltap for clean single-vs-double semantics
  cy.on('tap', 'node', handleNodeSingleTap);
  cy.on('dbltap', 'node', handleNodeDoubleTap);
  
  // Debug: global tap listener
  cy.on('tap', (evt) => {
    console.debug('[batho] Global tap:', evt.target?.classes ? Array.from(evt.target.classes()) : 'background', evt.target?.data?.()?.id);
  });
  
  function onEdgeTap(evt) { showEdgeDrawer(evt.target.data()); }
  cy.on('tap', 'edge', onEdgeTap);
  cy.on('mouseover', 'node', (evt) => {
    evt.target.addClass('hovered');
    showNodeTooltip(evt.target, cy.container().closest('.graph-canvas-wrap'));
  });
  cy.on('mouseout', 'node', (evt) => {
    evt.target.removeClass('hovered');
    hideNodeTooltip();
  });
  cy.on('mouseover', 'edge', (evt) => { 
    console.debug('[batho] Edge hover:', evt.target.id());
    evt.target.addClass('hovered'); 
  });
  cy.on('mouseout', 'edge', (evt) => { evt.target.removeClass('hovered'); });
  function onBackgroundTap(evt) {
    if (evt.target === cy) {
      clearFocusNode(cy);
      _selectedNodeId = null;
      // Close drawer if open
      if (_drawer) closeDrawer(_drawer);
    }
  }
  cy.on('tap', onBackgroundTap);

  // Add box selection for multi-select capability
  cy.on('boxselect', 'node', (evt) => {
    const nodes = evt.target;
    if (nodes.length === 1) {
      showNodeDrawer(nodes[0].data());
    }
  });

  return cy;
}

// --- level dispatch --------------------------------------------------------

function loadLevel(container, level, target) {
  if (!_cy || !_bsgData) return;
  _renderStartTime = performance.now();

  const budgetEl = container.querySelector('#graph-budget-warning');
  if (budgetEl) {
    budgetEl.hidden = true;
    budgetEl.innerHTML = '';
  }
  const matchBanner = container.querySelector('.graph-match-banner');
  if (matchBanner) matchBanner.remove();

  let elements;
  let facetCounts;
  let centerId = null;

  // Hide L2-specific sections by default.
  const insightsSection = container.querySelector('#graph-l2-insights');
  if (insightsSection) insightsSection.hidden = true;
  const l2ModeSection = container.querySelector('#graph-l2-mode-section');
  if (l2ModeSection) l2ModeSection.hidden = true;
  const l2SearchSection = container.querySelector('#graph-l2-search-section');
  if (l2SearchSection) l2SearchSection.hidden = true;
  const l2Structure = container.querySelector('#graph-l2-structure');
  if (l2Structure) l2Structure.hidden = true;
  const l2Deps = container.querySelector('#graph-l2-deps');
  if (l2Deps) l2Deps.hidden = true;

  if (level === 2) {
    const result = buildFileSubgraph(_bsgData, target);
    const { nodes, edges, file, matchType } = result;

    // Phase 1.3 — Show fuzzy match banner.
    if (matchType !== 'exact' && matchType !== 'none' && file !== target) {
      showMatchBanner(container, target, file, matchType);
    }

    if (nodes.length === 0) {
      renderMissingFilePanel(container, target);
      _cy.batch(() => { _cy.elements().remove(); });
      renderBreadcrumb(container, level, target);
      return;
    }

    // Phase 2.2 — Dual-mode L2 rendering for large files.
    if (nodes.length > L2_NODE_BUDGET) {
      if (l2ModeSection) l2ModeSection.hidden = false;
      if (l2SearchSection) l2SearchSection.hidden = false;

      if (_l2Mode === 'clustered') {
        elements = buildClusteredElements(nodes, edges);
      } else {
        const slice = nodes.slice(0, _l2PaginatedCount);
        const sliceIds = new Set(slice.map((n) => n.id));
        const sliceEdges = edges.filter((e) => {
          const s = e.sourceId ?? e.source_id ?? e.source ?? e.from;
          const t = e.targetId ?? e.target_id ?? e.target ?? e.to;
          return sliceIds.has(s) && sliceIds.has(t);
        });
        elements = nodesToCyElements(slice).concat(edgesToCyElements(sliceEdges, slice));
      }
      facetCounts = computeNodeFacets(nodes);
    } else {
      elements = nodesToCyElements(nodes).concat(edgesToCyElements(edges, nodes));
      facetCounts = computeNodeFacets(nodes);
    }

    updateL2Insights(container, nodes, edges);
    buildL2StructureTree(container, nodes, edges);
    buildL2DependencyPanel(container, nodes, edges, file);
    if (l2SearchSection && nodes.length > 0) l2SearchSection.hidden = false;
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

  // Phase 5.6 — Show skeleton while loading.
  showSkeleton(container);

  // Safety timeout: force hide skeleton after 60 seconds no matter what
  const skeletonSafetyTimeout = setTimeout(() => {
    console.warn('[batho] Skeleton safety timeout triggered - forcing hide');
    hideSkeleton(container);
    showToast('Graph loading timed out. Try refreshing or check console for errors.');
  }, 60000);

  // Wrap rendering in try-catch to ensure skeleton is always hidden
  try {
    // Deduplicate elements upfront to avoid silent rejections during progressive loading
    const seenIds = new Set();
    const uniqueElements = elements.filter(el => {
      const id = el.data?.id || el.data?.name;
      if (id && seenIds.has(id)) return false;
      if (id) seenIds.add(id);
      return true;
    });
    if (uniqueElements.length < elements.length) {
      elements = uniqueElements;
    }

    // Phase 2.1 — Progressive loading for large L1 graphs.
    if (level === 1 && elements.length > 500) {
        loadElementsProgressive(container, elements, () => {
        // Final pass: add any remaining edges whose endpoints are now available
        const remainingEdges = elements.filter(el => {
          if (!el.data.source || !el.data.target) return false; // Not an edge
          if (_cy.getElementById(el.data.id).length > 0) return false; // Already added
          const srcExists = _cy.getElementById(el.data.source).length > 0;
          const tgtExists = _cy.getElementById(el.data.target).length > 0;
          return srcExists && tgtExists;
        });
        if (remainingEdges.length > 0) {
          _cy.batch(() => { _cy.add(remainingEdges); });
        }
        _cy.resize();
        _facetCountsByLevel[level] = facetCounts;
        buildFilterChipsForLevel(container, level, facetCounts);
        renderBreadcrumb(container, level, target);
        syncLayoutButtons(container);
        applyFilters();
        hideSkeleton(container);
        scheduleLayout(_currentLayout, centerId, container);
        initMinimap(container);
      });
      // Note: skeleton will be hidden by the callback, but also ensure it's hidden
      // if the callback never fires (e.g., container unmounted)
      return;
    }

    _cy.batch(() => {
      _cy.elements().remove();
      _cy.add(elements);
    });
    _cy.resize();
    _facetCountsByLevel[level] = facetCounts;

    buildFilterChipsForLevel(container, level, facetCounts);
    renderBreadcrumb(container, level, target);
    syncLayoutButtons(container);
    applyFilters();

    const progressLabel = container.querySelector('#graph-progress-label');
    if (progressLabel) progressLabel.textContent = 'computing layout…';

    scheduleLayout(_currentLayout, centerId, container);
    initMinimap(container);
  } catch (err) {
    console.error('[batho] Error loading level:', err);
    showToast('Failed to render graph: ' + err.message);
  } finally {
    // Always hide skeleton, even if there was an error
    clearTimeout(skeletonSafetyTimeout);
    hideSkeleton(container);
  }
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
      runLayout(_currentLayout, _currentLevel === 3 ? _currentTarget : null, container);
    });
  });

  // Export button (Phase 5.3 — dropdown with format options).
  const layoutSwitcher = container.querySelector('.graph-layout-switcher');
  if (layoutSwitcher) {
    const exportWrap = document.createElement('div');
    exportWrap.style.position = 'relative';
    exportWrap.style.display = 'inline-block';
    layoutSwitcher.appendChild(exportWrap);

    const exportBtn = document.createElement('button');
    exportBtn.className = 'graph-layout-btn';
    exportBtn.title = 'Export Graph';
    exportBtn.innerHTML = '⭳ Export';
    exportWrap.appendChild(exportBtn);

    exportBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleExportMenu(exportWrap);
    });
  }

  const pathInput = container.querySelector('.graph-path-input');
  if (pathInput) {
    const onPathInput = debounce(() => {
      filterStateForLevel().path = pathInput.value.trim();
      applyFilters();
    }, 150);
    pathInput.addEventListener('input', onPathInput);
  }

  // Zoom controls.
  const zoomIn = container.querySelector('[data-action="zoom-in"]');
  const zoomOut = container.querySelector('[data-action="zoom-out"]');
  const fitBtn = container.querySelector('[data-action="fit"]');

  if (zoomIn) zoomIn.addEventListener('click', () => {
    if (!_cy) return;
    const next = Math.min(_cy.zoom() * 1.25, _cy.maxZoom());
    _cy.zoom({ level: next, renderedPosition: { x: _cy.width() / 2, y: _cy.height() / 2 } });
  });
  if (zoomOut) zoomOut.addEventListener('click', () => {
    if (!_cy) return;
    const next = Math.max(_cy.zoom() * 0.8, _cy.minZoom());
    _cy.zoom({ level: next, renderedPosition: { x: _cy.width() / 2, y: _cy.height() / 2 } });
  });
  if (fitBtn) fitBtn.addEventListener('click', () => {
    if (!_cy) return;
    _cy.fit(undefined, 40);
  });

  // Keyboard shortcuts.
  document.addEventListener('keydown', (e) => {
    if (e.key === 'e' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      exportGraphPng();
      return;
    }
    if (e.key === '/') {
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return;
      e.preventDefault();
      const search = container.querySelector('.graph-l2-search__input') || container.querySelector('.graph-path-input');
      if (search) search.focus();
      return;
    }
    if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return;
      e.preventDefault();
      toggleShortcutsOverlay(container);
      return;
    }
    if (e.key === 'm' && !e.ctrlKey && !e.metaKey) {
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return;
      e.preventDefault();
      toggleMinimap(container);
      return;
    }
    if (e.key === 'n' && !e.ctrlKey && !e.metaKey) {
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return;
      e.preventDefault();
      toggleNodeLabels();
      return;
    }
    if (e.key === 'l' && !e.ctrlKey && !e.metaKey) {
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return;
      e.preventDefault();
      cycleLayout(container);
      return;
    }
    if (!_cy) return;
    const tag = (e.target?.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return;
    switch (e.key) {
      case '+':
      case '=':
        e.preventDefault();
        _cy.zoom({ level: Math.min(_cy.zoom() * 1.25, _cy.maxZoom()), renderedPosition: { x: _cy.width() / 2, y: _cy.height() / 2 } });
        break;
      case '-':
      case '_':
        e.preventDefault();
        _cy.zoom({ level: Math.max(_cy.zoom() * 0.8, _cy.minZoom()), renderedPosition: { x: _cy.width() / 2, y: _cy.height() / 2 } });
        break;
      case 'f':
        e.preventDefault();
        _cy.fit(undefined, 40);
        break;
      case '1':
        e.preventDefault();
        if (_currentLevel !== 1) router.navigate('/hypergraph/files');
        break;
      case '2':
        e.preventDefault();
        if (_currentLevel === 3 && _currentTarget) {
          const nodeRec = _bsgData?.nodes?.find?.((n) => n.id === _currentTarget);
          if (nodeRec?.file) router.navigate('/hypergraph/file/' + encodeURIComponent(nodeRec.file));
        }
        break;
      case 'Escape':
        if (_drawer) closeDrawer(_drawer);
        clearFocusNode(_cy);
        break;
    }
  }, { signal: (_pageAbortController || new AbortController()).signal });

  // Filter reset.
  const resetBtn = container.querySelector('#graph-filter-reset');
  if (resetBtn) resetBtn.addEventListener('click', () => {
    const state = filterStateForLevel();
    state.initialized = false;
    state.path = '';
    const facets = _facetCountsByLevel[_currentLevel];
    if (facets) buildFilterChipsForLevel(container, _currentLevel, facets);
    applyFilters();
  });

  const canvasWrap = container.querySelector('.graph-canvas-wrap');

  // Phase 4.4 — L2 quick search.
  const l2SearchInput = container.querySelector('.graph-l2-search__input');
  if (l2SearchInput) {
    const onL2Search = debounce(() => {
      applyL2Search(l2SearchInput.value.trim());
    }, 120);
    l2SearchInput.addEventListener('input', onL2Search);
  }

  // Phase 2.2 — L2 mode toggle.
  const l2ModeToggle = container.querySelector('#graph-l2-mode-toggle');
  if (l2ModeToggle) {
    l2ModeToggle.querySelectorAll('.graph-l2-mode-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        _l2Mode = btn.dataset.mode;
        if (_l2Mode === 'paginated') _l2PaginatedCount = 500;
        l2ModeToggle.querySelectorAll('.graph-l2-mode-btn').forEach((b) => {
          b.classList.toggle('graph-l2-mode-btn--active', b.dataset.mode === _l2Mode);
        });
        loadLevel(container, 2, _currentTarget);
      });
    });
  }

  // Hide the canvas hint after first interaction with the canvas.
  const hint = container.querySelector('#graph-canvas-hint');
  if (hint && canvasWrap) {
    const dismiss = () => { hint.classList.add('graph-canvas__hint--dismissed'); };
    canvasWrap.addEventListener('mousedown', dismiss, { once: true });
    canvasWrap.addEventListener('wheel', dismiss, { once: true, passive: true });
  }
}

function renderBreadcrumb(container, level, target) {
  const el = container.querySelector('#graph-breadcrumb');
  if (!el) return;

  const segments = [
    { label: 'Files', route: '/hypergraph/files', active: level === 1, icon: '📁' },
  ];

  if (level >= 2) {
    let fileForCrumb = target;
    let nodeRecForL3 = null;
    if (level === 3) {
      nodeRecForL3 = _bsgData?.nodes?.find?.((n) => n.id === target);
      fileForCrumb = nodeRecForL3?.file || '';
    }
    if (fileForCrumb) {
      const shortFile = fileForCrumb.split('/').pop() || fileForCrumb;
      segments.push({
        label: shortFile,
        fullLabel: fileForCrumb,
        route: '/hypergraph/file/' + encodeURIComponent(fileForCrumb),
        active: level === 2,
        icon: '📄',
      });
    }
  }

  if (level === 3 && nodeRecForL3) {
    const nodeIcon = getNodeIcon(nodeRecForL3.type);
    segments.push({
      label: nodeRecForL3.name || target,
      route: '/hypergraph/node/' + encodeURIComponent(target),
      active: true,
      icon: nodeIcon,
    });
  }

  el.innerHTML = segments.map((s, i) => `
    <span class="graph-breadcrumb__sep" ${i === 0 ? 'hidden' : ''}>›</span>
    <button class="graph-breadcrumb__seg ${s.active ? 'graph-breadcrumb__seg--active' : ''}"
            data-route="${escapeAttr(s.route)}"
            title="${escapeAttr(s.fullLabel || s.label)}"
            ${s.active ? 'disabled aria-current="page"' : ''}>
      <span class="graph-breadcrumb__icon">${s.icon}</span>
      <span class="graph-breadcrumb__text">${escapeHtml(truncate(s.label, 36))}</span>
    </button>
  `).join('');

  el.querySelectorAll('button[data-route]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const r = btn.dataset.route;
      if (r) router.navigate(r);
    });
  });
}

function getNodeIcon(type) {
  const icons = {
    'FUNCTION': '⚡',
    'METHOD': '🔧',
    'CLASS': '🏛️',
    'INTERFACE': '🔌',
    'TRAIT': '🎭',
    'ENUM': '📋',
    'STRUCT': '🏗️',
    'NAMESPACE': '📦',
    'MODULE': '📦',
    'VARIABLE': '📌',
    'FIELD': '🔍',
  };
  return icons[(type || '').toUpperCase()] || '🔹';
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
  let visibleNodes = 0;
  let visibleEdges = 0;

  _cy.batch(() => {
    _cy.nodes().forEach((node) => {
      const d = node.data();
      let visible = true;

      // Only filter by type if user has explicitly selected types (not empty = all)
      if (facets.types && state.types.size > 0 && !state.types.has(d.kind)) visible = false;
      if (visible && facets.langs && state.languages.size > 0 && !state.languages.has(d.language)) visible = false;
      if (visible && facets.services && d.serviceTag && state.services.size > 0
          && !state.services.has(d.serviceTag)) visible = false;
      if (visible && facets.scopes && d.scopeTier && state.scopes.size > 0
          && !state.scopes.has(d.scopeTier)) visible = false;
      if (visible && facets.categories && d.category && state.categories.size > 0
          && !state.categories.has(d.category)) visible = false;
      if (visible && state.path && !matchGlob(state.path, d.file || d.id || '')) visible = false;

      if (visible) { node.removeClass('filtered-out'); visibleNodes += 1; }
      else node.addClass('filtered-out');
    });

    // Edges hide when either endpoint is filtered out.
    _cy.edges().forEach((edge) => {
      const src = edge.source();
      const tgt = edge.target();
      const hidden = src.hasClass('filtered-out') || tgt.hasClass('filtered-out');
      if (hidden) edge.addClass('filtered-out');
      else { edge.removeClass('filtered-out'); visibleEdges += 1; }
    });
  });

  updateStats(visibleNodes, visibleEdges);
}

function updateStats(nodeCount, edgeCount) {
  const nodeEl = document.getElementById('graph-stat-nodes');
  const edgeEl = document.getElementById('graph-stat-edges');
  if (nodeEl) nodeEl.textContent = formatInt(nodeCount);
  if (edgeEl) edgeEl.textContent = formatInt(edgeCount);
}

// --- layout runner ---------------------------------------------------------

function scheduleLayout(name, centerId, container) {
  const run = () => runLayout(name, centerId, container);
  setTimeout(run, 50);
}

function runLayout(name, centerId, container) {
  if (!_cy || _cy.nodes().length === 0) return;

  const progressLabel = container?.querySelector('#graph-progress-label');
  if (progressLabel) progressLabel.textContent = 'computing layout…';
  const doneLabel = `${describeLevel(_currentLevel, _currentTarget)} ready`;

  try {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const nodeCount = _cy.nodes().length;
    const animate = nodeCount < 1500 && !prefersReducedMotion;
    const animationDuration = animate ? 400 : 0;

    const opts = {
      name: name,
      animate,
      animationDuration,
      fit: true,
      padding: 40,
    };

    if (name === 'cose') {
      // Phase 2.3 — Optimize COSE for all graph sizes.
      // Always randomize to spread nodes out initially
      Object.assign(opts, {
        randomize: true,
        componentSpacing: 200,
        nodeRepulsion: 8_000_000,
        nodeOverlap: 50,
        idealEdgeLength: _currentLevel === 1 ? 150 : 80,
        edgeElasticity: 50,
        nestingFactor: 2,
        gravity: 0.1,
        gravityRange: 3.8,
        numIter: nodeCount > 300 ? 800 : 1200,
        initialTemp: nodeCount * 2,
        coolingFactor: 0.95,
        minTemp: 0.5,
      });
    } else if (name === 'breadthfirst') {
      Object.assign(opts, { directed: true, spacingFactor: 1.2 });
    } else if (name === 'concentric') {
      Object.assign(opts, {
        concentric: (n) => (centerId && n.data('id') === centerId ? 1000 : n.degree()),
        levelWidth: () => 3,
      });
    } else if (name === 'circle') {
      Object.assign(opts, { padding: 30, avoidOverlap: true });
    } else if (name === 'grid') {
      Object.assign(opts, { fit: true, padding: 30 });
    }

    const layout = _cy.layout(opts).run();

    const onLayoutDone = () => {
      if (progressLabel) progressLabel.textContent = doneLabel;
      showRenderTime(container);
      // Force fit to ensure nodes are visible
      setTimeout(() => {
        _cy.fit(_cy.nodes().filter(n => !n.hasClass('filtered-out')), 50);
      }, 100);
    };

    if (animate && typeof layout.promise === 'function') {
      layout.promise().then(onLayoutDone);
    } else {
      onLayoutDone();
    }
  } catch (err) {
    console.error('[batho] layout error:', err);
    try {
      _cy.layout({ name: 'grid', fit: true, padding: 40 }).run();
    } catch (_e) {
      console.error('[batho] grid fallback error:', _e);
    }
    if (progressLabel) progressLabel.textContent = doneLabel;
    showRenderTime(container);
  }
}

function showNodeDrawer(data) {
  if (!_drawer) return;

  const bsgNode = _bsgData?.nodes?.find?.((n) => n.id === data.id);
  const nodeIcon = getNodeIcon(data.kind);

  // Build detailed properties sections
  let detailsHtml = '';

  // Identity section
  detailsHtml += `<div class="drawer-section drawer-section--identity">
    <div class="drawer-identity">
      <span class="drawer-identity__icon">${nodeIcon}</span>
      <div class="drawer-identity__info">
        <div class="drawer-identity__name" title="${escapeAttr(data.label || data.id)}">${escapeHtml(data.label || data.id)}</div>
        <div class="drawer-identity__type">${escapeHtml(data.kind || 'Unknown')}${data.language && data.language !== 'unknown' ? ` · ${escapeHtml(data.language)}` : ''}</div>
      </div>
    </div>
  </div>`;

  // Location section (if available)
  if (data.file) {
    detailsHtml += `<div class="drawer-section">
      <div class="drawer-section__title">📍 Location</div>
      <div class="drawer-prop drawer-prop--file">
        <span class="drawer-prop__val drawer-prop__val--file" title="${escapeAttr(data.file)}">${escapeHtml(data.file)}</span>
        ${_currentLevel !== 2 ? `<button class="drawer-prop__action" data-action="open-file" title="Open file graph">↗</button>` : ''}
      </div>
    </div>`;
  }

  // Stats section
  const stats = [];
  if (data.nodeCount) stats.push(['Entities', data.nodeCount]);
  if (bsgNode) {
    const inbound = _bsgData?.edges?.filter?.(e => (e.targetId || e.target_id || e.target) === data.id)?.length || 0;
    const outbound = _bsgData?.edges?.filter?.(e => (e.sourceId || e.source_id || e.source) === data.id)?.length || 0;
    if (inbound) stats.push(['Inbound refs', inbound]);
    if (outbound) stats.push(['Outbound refs', outbound]);
  }

  if (stats.length > 0) {
    detailsHtml += `<div class="drawer-section drawer-section--stats">
      <div class="drawer-section__title">📊 Stats</div>
      <div class="drawer-stats-grid">
        ${stats.map(([label, val]) => `
          <div class="drawer-stat">
            <span class="drawer-stat__value">${val}</span>
            <span class="drawer-stat__label">${escapeHtml(label)}</span>
          </div>
        `).join('')}
      </div>
    </div>`;
  }

  // Metadata section
  if (bsgNode?.metadata && typeof bsgNode.metadata === 'object') {
    const entries = Object.entries(bsgNode.metadata).filter(([, v]) => v != null && v !== '');
    if (entries.length) {
      detailsHtml += `<div class="drawer-section">
        <div class="drawer-section__title">🔖 Metadata</div>
        <div class="drawer-metadata">
          ${entries.slice(0, 6).map(([k, v]) =>
            `<div class="drawer-metadata__item">
              <span class="drawer-metadata__key">${escapeHtml(k)}</span>
              <span class="drawer-metadata__val" title="${escapeAttr(String(v))}">${escapeHtml(String(v).slice(0, 50))}${String(v).length > 50 ? '…' : ''}</span>
            </div>`
          ).join('')}
        </div>
      </div>`;
    }
  }

  // Actions section
  let actionsHtml = '<div class="drawer-section drawer-section--actions"><div class="drawer-actions">';
  if (_currentLevel === 2 && data.id) {
    actionsHtml += `<button class="drawer-action drawer-action--primary" data-action="l3">🔍 View Neighborhood</button>`;
  } else if (_currentLevel === 3 && data.id) {
    actionsHtml += `<button class="drawer-action drawer-action--primary" data-action="refocus">🎯 Refocus Here</button>`;
  }
  if (_currentLevel === 3 && data.file) {
    actionsHtml += `<button class="drawer-action" data-action="l2">📄 Back to File</button>`;
  }
  if (_currentLevel === 2 && data.file) {
    actionsHtml += `<button class="drawer-action" data-action="l1">📁 All Files</button>`;
  }
  actionsHtml += '</div></div>';

  // Hint about interactions
  const hintHtml = `<div class="drawer-hint">
    <kbd>Double-click</kbd> node to navigate · <kbd>Esc</kbd> to close
  </div>`;

  openDrawer(_drawer, { title: '', content: detailsHtml + actionsHtml + hintHtml });

  _drawer.querySelectorAll('[data-action]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action;
      if (action === 'l3' && data.id) {
        router.navigate('/hypergraph/node/' + encodeURIComponent(data.id));
      } else if (action === 'l2' && data.file) {
        router.navigate('/hypergraph/file/' + encodeURIComponent(data.file));
      } else if (action === 'l1') {
        router.navigate('/hypergraph/files');
      } else if (action === 'open-file' && data.file) {
        router.navigate('/hypergraph/file/' + encodeURIComponent(data.file));
      } else if (action === 'refocus' && data.id) {
        router.navigate('/hypergraph/node/' + encodeURIComponent(data.id));
      }
    });
  });
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

function updateL2Insights(container, nodes, edges) {
  const section = container.querySelector('#graph-l2-insights');
  if (!section) return;

  const nodeIds = new Set();
  for (const n of nodes) nodeIds.add(n.id);

  let imports = 0;
  let exports = 0;
  let classes = 0;
  let funcs = 0;

  for (const e of edges) {
    const type = ((e.relationshipType ?? e.relationship_type ?? e.type ?? '') + '').toLowerCase();
    const source = e.sourceId ?? e.source_id ?? e.source;
    const target = e.targetId ?? e.target_id ?? e.target;
    if (type === 'imports') {
      // This file imports from others (outbound)
      if (nodeIds.has(source)) imports += 1;
      // Others import from this file (inbound)
      if (nodeIds.has(target)) exports += 1;
    }
  }

  for (const n of nodes) {
    const t = ((n.type || '') + '').toUpperCase();
    if (t === 'CLASS') classes += 1;
    if (t === 'FUNCTION' || t === 'METHOD') funcs += 1;
  }

  const importsEl = section.querySelector('#insight-imports span');
  const exportsEl = section.querySelector('#insight-exports span');
  const complexityEl = section.querySelector('#insight-complexity span');
  if (importsEl) importsEl.textContent = String(imports);
  if (exportsEl) exportsEl.textContent = String(exports);
  if (complexityEl) complexityEl.textContent = `${classes} / ${funcs}`;
  section.hidden = false;
}

function renderMissingFilePanel(container, filePath) {
  const budgetEl = container.querySelector('#graph-budget-warning');
  if (!budgetEl) return;
  budgetEl.hidden = false;
  budgetEl.innerHTML = `
    <div class="panel graph-missing-file__panel">
      <div class="panel__title">File Not Indexed</div>
      <p class="graph-budget-warning__copy">
        <strong class="graph-budget-warning__file">${escapeHtml(filePath)}</strong>
        was not found in the active BSG graph.
      </p>
      <p class="graph-budget-warning__copy">
        Run <code>batho scan</code> to regenerate the graph artifact.
      </p>
      <div class="graph-budget-warning__actions">
        <button class="btn" data-action="open-files">Open in Files</button>
        <button class="btn btn--ghost" data-action="back">Back to Files</button>
      </div>
    </div>
  `;
  const openBtn = budgetEl.querySelector('[data-action="open-files"]');
  if (openBtn) openBtn.addEventListener('click', () => router.navigate('/files', { path: filePath }));
  const backBtn = budgetEl.querySelector('[data-action="back"]');
  if (backBtn) backBtn.addEventListener('click', () => router.navigate('/hypergraph/files'));
}

function renderBudgetWarning(container, file, count) {
  const budgetEl = container.querySelector('#graph-budget-warning');
  if (!budgetEl) return;
  budgetEl.hidden = false;
  budgetEl.innerHTML = `
    <div class="panel graph-budget-warning__panel">
      <div class="panel__title">Large File</div>
      <p class="graph-budget-warning__copy">
        <strong class="graph-budget-warning__file">${escapeHtml(file)}</strong>
        contains ${formatInt(count)} entities, above the L2 render budget of
        ${formatInt(L2_NODE_BUDGET)}.
      </p>
      <div class="graph-budget-warning__actions">
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

// --- focus mode + tooltip helpers ----------------------------------------

function setFocusNode(nodeId, cy) {
  if (!cy) return;
  _focusNodeId = nodeId;
  const node = cy.getElementById(nodeId);
  if (!node.length) return;
  const neighbors = node.neighborhood();
  cy.batch(() => {
    cy.nodes().addClass('focus-hidden');
    cy.edges().addClass('focus-hidden');
    node.removeClass('focus-hidden').addClass('focus-visible-node focus-pulse');
    neighbors.nodes().removeClass('focus-hidden').addClass('focus-visible-node');
    neighbors.edges().removeClass('focus-hidden').addClass('focus-visible-edge');
  });

  // Center the view on the selected node with smooth animation
  cy.animate({
    center: { eles: node },
    zoom: Math.min(cy.zoom() * 1.2, cy.maxZoom()),
    duration: 300,
    easing: 'ease-out-cubic'
  });
}

function clearFocusNode(cy) {
  if (!cy) return;
  _focusNodeId = null;
  cy.batch(() => {
    cy.nodes().removeClass('focus-hidden focus-visible-node');
    cy.edges().removeClass('focus-hidden focus-visible-edge');
  });
}

function showNodeTooltip(cyNode, wrapEl) {
  if (!_tooltipEl && wrapEl) {
    _tooltipEl = wrapEl.querySelector('#graph-tooltip');
  }
  if (!_tooltipEl) return;
  const data = cyNode.data();
  const degree = cyNode.degree();
  const nameHtml = `<div class="graph-tooltip__name">${escapeHtml(data.label || data.id)}</div>`;
  let badgeHtml = '';
  if (data.kind) {
    badgeHtml += `<span class="graph-tooltip__badge">${escapeHtml(data.kind)}</span>`;
  }
  if (data.language && data.language !== 'unknown') {
    badgeHtml += `<span class="graph-tooltip__badge">${escapeHtml(data.language)}</span>`;
  }
  let metaHtml = '';
  if (data.file && _currentLevel !== 2) {
    metaHtml += `<div class="graph-tooltip__meta">${escapeHtml(truncate(data.file, 40))}</div>`;
  }
  metaHtml += `<div class="graph-tooltip__meta">${degree} connection${degree !== 1 ? 's' : ''}</div>`;
  if (data.nodeCount) {
    metaHtml += `<div class="graph-tooltip__meta">${data.nodeCount} entities</div>`;
  }
  _tooltipEl.innerHTML = nameHtml + (badgeHtml ? `<div>${badgeHtml}</div>` : '') + metaHtml;

  // Position tooltip, clamping to viewport.
  const pos = cyNode.renderedPosition();
  let left = pos.x + 14;
  let top = pos.y - 10;
  const tw = 260;
  const th = 80;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (left + tw > vw) left = pos.x - tw - 10;
  if (top + th > vh) top = vh - th - 8;
  if (top < 4) top = 4;
  if (left < 4) left = 4;
  _tooltipEl.style.left = `${left}px`;
  _tooltipEl.style.top = `${top}px`;
  _tooltipEl.hidden = false;
}

function hideNodeTooltip() {
  if (_tooltipEl) _tooltipEl.hidden = true;
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

function showMatchBanner(container, requested, resolved, matchType) {
  const banner = container.querySelector('#graph-match-banner');
  if (!banner) return;
  const label = matchType === 'normalized' ? 'normalized path match' : 'suffix match';
  banner.innerHTML = `<span>Showing <strong>${escapeHtml(resolved)}</strong> (${label}) for <code>${escapeHtml(requested)}</code></span>`;
  banner.hidden = false;
}

function buildClusteredElements(nodes, edges) {
  const clusters = new Map();
  for (const n of nodes) {
    const type = (n.type || 'unknown').toUpperCase();
    if (!clusters.has(type)) clusters.set(type, []);
    clusters.get(type).push(n);
  }
  const elements = [];
  let clusterId = 0;
  const clusterChildNodes = [];
  for (const [type, members] of clusters) {
    const cid = `cluster:${clusterId++}`;
    elements.push({
      data: { id: cid, label: `${type} (${members.length})`, kind: 'CLUSTER', memberCount: members.length },
      classes: 'cluster-parent'
    });
    for (const n of members) {
      const shortName = (n.name || n.id || '').split(/[/:.]/).pop() || n.id;
      clusterChildNodes.push({
        data: {
          id: n.id,
          label: n.name || n.id,
          shortName,
          kind: (n.type || 'unknown').toUpperCase(),
          language: n.language || 'unknown',
          serviceTag: n.serviceTag || n.service_tag || '',
          scopeTier: n.scopeTier || n.scope_tier || '',
          category: (n.category || '') + '',
          file: n.file || '',
          parent: cid,
        },
      });
    }
  }
  elements.push(...clusterChildNodes);
  elements.push(...edgesToCyElements(edges, nodes));
  return elements;
}

function applyL2Search(query) {
  if (!_cy) return;
  const q = (query || '').toLowerCase().trim();
  _cy.batch(() => {
    _cy.nodes().removeClass('search-match');
    if (!q) return;
    _cy.nodes().forEach((n) => {
      const label = (n.data('label') || n.id() || '').toLowerCase();
      const kind = (n.data('kind') || '').toLowerCase();
      if (label.includes(q) || kind.includes(q)) n.addClass('search-match');
    });
  });
}

function initMinimap(container) {
  const wrap = container.querySelector('#graph-minimap');
  if (!wrap || !_cy) return;
  _minimapCanvas = wrap.querySelector('canvas');
  if (!_minimapCanvas) return;
  const ctx = _minimapCanvas.getContext('2d', { alpha: true });
  const viewport = wrap.querySelector('.graph-minimap__viewport');
  const update = () => {
    if (!_cy || !_minimapCanvas) return;
    const w = _minimapCanvas.width = wrap.clientWidth || 160;
    const h = _minimapCanvas.height = wrap.clientHeight || 120;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = 'rgba(15,23,42,0.6)';
    ctx.fillRect(0, 0, w, h);
    const bb = _cy.elements().boundingBox();
    const scaleX = w / (bb.w || 1);
    const scaleY = h / (bb.h || 1);
    ctx.strokeStyle = 'rgba(103,232,249,0.9)';
    ctx.lineWidth = 1;
    _cy.nodes().forEach((n) => {
      const p = n.renderedPosition();
      const x = (p.x - bb.x1) * scaleX;
      const y = (p.y - bb.y1) * scaleY;
      ctx.fillStyle = n.hasClass('search-match') ? '#67e8f9' : '#64748b';
      ctx.fillRect(x - 1, y - 1, 3, 3);
    });
    const vr = _cy.extent();
    const vx = (vr.x1 - bb.x1) * scaleX;
    const vy = (vr.y1 - bb.y1) * scaleY;
    const vw = (vr.w) * scaleX;
    const vh = (vr.h) * scaleY;
    if (viewport) {
      viewport.style.left = `${Math.max(0, vx)}px`;
      viewport.style.top = `${Math.max(0, vy)}px`;
      viewport.style.width = `${Math.max(4, vw)}px`;
      viewport.style.height = `${Math.max(4, vh)}px`;
    }
  };
  _minimapRAF = requestAnimationFrame(function loop() {
    update();
    if (_minimapCanvas) _minimapRAF = requestAnimationFrame(loop);
  });
  wrap.onclick = () => {
    if (!_cy) return;
    _cy.fit(_cy.elements(), 50);
  };
}

function toggleExportMenu(wrap) {
  if (!wrap) return;
  if (!_exportMenu) {
    _exportMenu = document.createElement('div');
    _exportMenu.className = 'graph-export-menu';
    _exportMenu.innerHTML = `
      <button class="graph-export-menu__item" data-export="png">PNG</button>
      <button class="graph-export-menu__item" data-export="svg">SVG</button>
      <button class="graph-export-menu__item" data-export="json">JSON</button>
    `;
    wrap.appendChild(_exportMenu);
    _exportMenu.onclick = (e) => {
      const act = e.target.dataset.export;
      if (!act || !_cy) return;
      if (act === 'png') downloadBlob(_cy.png({ output: 'blob' }), 'hypergraph.png');
      else if (act === 'svg') downloadBlob(new Blob([_cy.svg()]), 'hypergraph.svg');
      else if (act === 'json') downloadBlob(new Blob([JSON.stringify(_cy.json(), null, 2)]), 'hypergraph.json');
      _exportMenu.style.display = 'none';
    };
  }
  _exportMenu.style.display = _exportMenu.style.display === 'block' ? 'none' : 'block';
}

function showRenderTime(container) {
  const el = container.querySelector('#graph-stat-time');
  const wrap = container.querySelector('#graph-stat-time-wrap');
  if (!el || !_renderStartTime) return;
  const ms = Math.round(performance.now() - _renderStartTime);
  el.textContent = `${ms}`;
  if (wrap) wrap.hidden = false;
}

function downloadBlob(blob, name) {
  const a = document.createElement('a');
  const url = URL.createObjectURL(blob);
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Phase 2.1 — Progressive loading for large graphs
function loadElementsProgressive(container, elements, callback) {
  const batchSize = 200;
  let index = 0;
  let isCancelled = false;

  function addBatch() {
    if (isCancelled) return;
    if (!_cy || !container?.isConnected) {
      if (callback) callback();
      return;
    }
    const progressFill = container?.querySelector('#graph-progress-fill');
    const progressLabel = container?.querySelector('#graph-progress-label');
    const batch = elements.slice(index, index + batchSize);
    // Deduplicate within the batch
    const seen = new Set();
    const uniqueBatch = batch.filter(el => {
      const id = el.data?.id || el.data?.name || el.group;
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
    if (batch.length === 0) {
      if (callback) callback();
      return;
    }
    if (uniqueBatch.length === 0) {
      index += batchSize;
      requestAnimationFrame(addBatch);
      return;
    }
    try {
      // Filter out elements that already exist or edges with missing endpoints
      const newElements = uniqueBatch.filter(el => {
        if (el.data?.id && _cy.getElementById(el.data.id).length > 0) return false;
        if (el.data.source && el.data.target) {
          const srcExists = _cy.getElementById(el.data.source).length > 0;
          const tgtExists = _cy.getElementById(el.data.target).length > 0;
          if (!srcExists || !tgtExists) return false;
        }
        return true;
      });
      _cy.batch(() => { _cy.add(newElements); });
    } catch (err) {
      console.error('[batho] Error adding batch:', err);
      if (callback) callback();
      return;
    }
    index += batchSize;
    const pct = Math.min(100, 60 + Math.round((index / elements.length) * 35));
    if (progressFill) progressFill.style.width = `${pct}%`;
    if (progressLabel) progressLabel.textContent = `loading ${Math.min(index, elements.length)} / ${elements.length} elements…`;
    requestAnimationFrame(addBatch);
  }

  try {
    _cy.batch(() => { _cy.elements().remove(); });
    addBatch();
  } catch (err) {
    console.error('[batho] Error in progressive loading:', err);
    if (callback) callback();
  }
}

// Simple toast notification
function showToast(message) {
  const existing = document.querySelector('.graph-toast');
  if (existing) existing.remove();
  const toast = document.createElement('div');
  toast.className = 'graph-toast';
  toast.textContent = message;
  toast.style.cssText = `
    position: fixed;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--surface-container, #2a2330);
    color: var(--on-surface, #e6e0e9);
    padding: 8px 16px;
    border-radius: 4px;
    font-family: var(--font-mono, monospace);
    font-size: 12px;
    z-index: 1000;
    border: 1px solid var(--outline-variant, #494551);
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  `;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// Phase 4.1 — Build L2 structure tree in sidebar
function buildL2StructureTree(container, nodes, edges) {
  const treeEl = container?.querySelector('#graph-structure-tree');
  if (!treeEl) return;

  const byType = new Map();
  for (const n of nodes) {
    const type = (n.type || 'unknown').toUpperCase();
    if (!byType.has(type)) byType.set(type, []);
    byType.get(type).push(n);
  }

  const typeOrder = ['CLASS', 'FUNCTION', 'METHOD', 'INTERFACE', 'TRAIT', 'ENUM', 'STRUCT', 'NAMESPACE', 'MODULE', 'FIELD', 'VARIABLE'];
  const sortedTypes = Array.from(byType.keys()).sort((a, b) => {
    const ia = typeOrder.indexOf(a);
    const ib = typeOrder.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });

  let html = '';
  for (const type of sortedTypes) {
    const items = byType.get(type);
    const typeIcon = getNodeIcon(type);
    html += `<div class="graph-structure-tree__section">`;
    html += `<div class="graph-structure-tree__type">
      <span class="graph-structure-tree__type-icon">${typeIcon}</span>
      <span class="graph-structure-tree__type-name">${escapeHtml(type)}</span>
      <span class="graph-structure-tree__type-count">${items.length}</span>
    </div>`;
    html += `<div class="graph-structure-tree__items">`;
    for (const n of items.slice(0, 25)) {
      const shortName = (n.name || n.id || '').split(/[/:.]/).pop() || n.id;
      html += `<div class="graph-structure-tree__item" data-node-id="${escapeAttr(n.id)}" title="${escapeAttr(n.name || n.id)}">`;
      html += `<span class="graph-structure-tree__name">${escapeHtml(shortName)}</span>`;
      html += `</div>`;
    }
    if (items.length > 25) {
      html += `<button class="graph-structure-tree__more" data-type="${escapeAttr(type)}">+ ${items.length - 25} more…</button>`;
    }
    html += `</div>`;
    html += `</div>`;
  }

  treeEl.innerHTML = html;

  // Wire up click handlers for items
  treeEl.querySelectorAll('.graph-structure-tree__item').forEach((item) => {
    item.addEventListener('click', () => {
      const nodeId = item.dataset.nodeId;
      if (nodeId && _cy) {
        // Highlight in graph
        const node = _cy.getElementById(nodeId);
        if (node.length) {
          setFocusNode(nodeId, _cy);
          _cy.animate({
            center: { eles: node },
            duration: 300,
            easing: 'ease-out-cubic'
          });
        }
      }
    });
  });

  // Wire up "more" buttons
  treeEl.querySelectorAll('.graph-structure-tree__more').forEach((btn) => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.type;
      const items = byType.get(type);
      if (!items) return;

      // Expand and show all items
      const section = btn.closest('.graph-structure-tree__items');
      if (section) {
        let moreHtml = '';
        for (const n of items.slice(25)) {
          const shortName = (n.name || n.id || '').split(/[/:.]/).pop() || n.id;
          moreHtml += `<div class="graph-structure-tree__item graph-structure-tree__item--expanded" data-node-id="${escapeAttr(n.id)}" title="${escapeAttr(n.name || n.id)}">`;
          moreHtml += `<span class="graph-structure-tree__name">${escapeHtml(shortName)}</span>`;
          moreHtml += `</div>`;
        }
        btn.insertAdjacentHTML('beforebegin', moreHtml);
        btn.remove();

        // Re-wire handlers for new items
        section.querySelectorAll('.graph-structure-tree__item--expanded').forEach((item) => {
          item.addEventListener('click', () => {
            const nodeId = item.dataset.nodeId;
            if (nodeId && _cy) {
              const node = _cy.getElementById(nodeId);
              if (node.length) {
                setFocusNode(nodeId, _cy);
                _cy.animate({ center: { eles: node }, duration: 300 });
              }
            }
          });
        });
      }
    });
  });

  // Show the section
  const sectionEl = container?.querySelector('#graph-l2-structure');
  if (sectionEl) sectionEl.hidden = false;
}

// Phase 4.2 — Build L2 dependency panel
function buildL2DependencyPanel(container, nodes, edges) {
  const inboundEl = container?.querySelector('#graph-deps-inbound');
  const outboundEl = container?.querySelector('#graph-deps-outbound');
  if (!inboundEl || !outboundEl) return;

  const nodeIds = new Set(nodes.map((n) => n.id));
  const thisFile = nodes[0]?.file || '';

  const inboundFiles = new Set();
  const outboundFiles = new Set();

  for (const e of edges) {
    const type = ((e.relationshipType ?? e.relationship_type ?? e.type ?? '') + '').toLowerCase();
    const source = e.sourceId ?? e.source_id ?? e.source ?? e.from;
    const target = e.targetId ?? e.target_id ?? e.target ?? e.to;
    if (!source || !target) continue;

    // Cross-file edges only
    const srcNode = _bsgData?.nodes?.find?.((n) => n.id === source);
    const tgtNode = _bsgData?.nodes?.find?.((n) => n.id === target);
    if (!srcNode || !tgtNode) continue;

    if (type === 'imports') {
      if (nodeIds.has(source) && tgtNode.file && tgtNode.file !== thisFile) {
        outboundFiles.add(tgtNode.file);
      }
      if (nodeIds.has(target) && srcNode.file && srcNode.file !== thisFile) {
        inboundFiles.add(srcNode.file);
      }
    }
  }

  function renderFileChips(files, el) {
    if (files.size === 0) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    const list = Array.from(files).slice(0, 10);
    el.innerHTML = list.map((f) =>
      `<span class="graph-dep-chip" data-file="${escapeAttr(f)}">${escapeHtml(f.split('/').pop())}</span>`
    ).join('');
    el.querySelectorAll('.graph-dep-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        const file = chip.dataset.file;
        if (file) router.navigate('/hypergraph/file/' + encodeURIComponent(file));
      });
    });
  }

  inboundEl.innerHTML = '<div class="graph-dep-section__title">Imported by</div>';
  outboundEl.innerHTML = '<div class="graph-dep-section__title">Imports from</div>';
  renderFileChips(inboundFiles, inboundEl);
  renderFileChips(outboundFiles, outboundEl);
}

// Phase 5.6 — Show/hide skeleton loading state
function showSkeleton(container) {
  const skeleton = container?.querySelector('#graph-skeleton');
  if (skeleton) skeleton.hidden = false;
}

function hideSkeleton(container) {
  const skeleton = container?.querySelector('#graph-skeleton');
  if (skeleton) skeleton.hidden = true;
}

// Phase 5.2 — Toggle keyboard shortcuts overlay
function toggleShortcutsOverlay(container) {
  if (_shortcutsOverlay) {
    _shortcutsOverlay.remove();
    _shortcutsOverlay = null;
    return;
  }

  const overlay = document.createElement('div');
  overlay.className = 'graph-shortcuts-overlay';
  overlay.innerHTML = `
    <div class="graph-shortcuts-panel">
      <div class="graph-shortcuts-panel__title">Keyboard & Mouse Shortcuts</div>

      <div class="graph-shortcuts-panel__section">🖱️ Mouse</div>
      <div class="graph-shortcuts-panel__row"><span>Click node</span><kbd>select + details</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>Double-click node</span><kbd>navigate</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>Click background</span><kbd>clear selection</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>Scroll</span><kbd>zoom</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>Drag</span><kbd>pan</kbd></div>

      <div class="graph-shortcuts-panel__section">⌨️ Navigation</div>
      <div class="graph-shortcuts-panel__row"><span>f</span><kbd>fit to view</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>1</span><kbd>go to L1 (files)</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>2</span><kbd>go to L2 (from L3)</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>Esc</span><kbd>clear focus</kbd></div>

      <div class="graph-shortcuts-panel__section">⌨️ Controls</div>
      <div class="graph-shortcuts-panel__row"><span>+ / -</span><kbd>zoom in/out</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>/</span><kbd>focus search</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>?</span><kbd>toggle this help</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>Ctrl+E</span><kbd>export PNG</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>n</span><kbd>toggle labels</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>l</span><kbd>cycle layout</kbd></div>
      <div class="graph-shortcuts-panel__row"><span>m</span><kbd>toggle minimap</kbd></div>
      <button class="graph-shortcuts-panel__close">Close</button>
    </div>
  `;

  overlay.querySelector('.graph-shortcuts-panel__close')?.addEventListener('click', () => {
    overlay.remove();
    _shortcutsOverlay = null;
  });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      overlay.remove();
      _shortcutsOverlay = null;
    }
  });

  (container || document.body).appendChild(overlay);
  _shortcutsOverlay = overlay;
}

// Phase 5.4 — Toggle minimap visibility
function toggleMinimap(container) {
  const wrap = container?.querySelector('#graph-minimap');
  if (!wrap) return;
  const isHidden = wrap.hidden;
  wrap.hidden = !isHidden;
  if (isHidden && _cy) {
    initMinimap(container);
  }
}

// Phase 5.x — Toggle node labels
function toggleNodeLabels() {
  if (!_cy) return;
  const hasLabels = _cy.nodes()[0]?.style('label') !== '';
  _cy.batch(() => {
    _cy.nodes().forEach((n) => {
      n.style('label', hasLabels ? '' : n.data('label'));
    });
  });
}

// Phase 5.x — Cycle through layouts
function cycleLayout(container) {
  const currentIdx = LAYOUTS.indexOf(_currentLayout);
  const nextIdx = (currentIdx + 1) % LAYOUTS.length;
  _currentLayout = LAYOUTS[nextIdx];
  syncLayoutButtons(container);
  runLayout(_currentLayout, _currentLevel === 3 ? _currentTarget : null, container);
}

// Phase 5.3 — Export graph as PNG
function exportGraphPng() {
  if (!_cy) return;
  const blob = _cy.png({ output: 'blob', bg: 'transparent' });
  downloadBlob(blob, 'hypergraph.png');
}

// MissingArtifactError is imported above for type clarity; re-export so any
// stale call site keeps working.
export { MissingArtifactError };
