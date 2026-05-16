import { loadIndex, loadBsg, loadGraph, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { router } from '../assets/js/router.js';
import { formatInt } from '../assets/js/format.js';
import { matchGlob } from '../assets/js/glob.js';
import { buildStylesheet } from '../assets/js/cy-stylesheet.js';
import { createChipFilter } from '../shared/components/chip-filter.js';
import { createDrawer, openDrawer } from '../shared/components/drawer.js';

let _cy = null;
let _bsgData = null;
let _filterState = {
  types: new Set(),
  languages: new Set(),
  services: new Set(),
  scopes: new Set(),
  path: '',
  focusId: null,
};
let _drawer = null;
const LAYOUTS = ['cose', 'breadthfirst', 'concentric'];
const DEFAULT_LAYOUT = 'cose';

export async function renderHypergraph(params) {
  const container = document.createElement('div');
  container.className = 'page page--hypergraph';

  container.innerHTML = `
    <div class="graph-shell">
      <div class="graph-header">
        <h1 class="panel__title graph-header__title">Hypergraph</h1>
        <div class="graph-header__controls">
          <div class="graph-layout-switcher" role="group" aria-label="Layout">
            ${LAYOUTS.map((l) => `<button class="btn graph-layout-btn${l === DEFAULT_LAYOUT ? ' graph-layout-btn--active' : ''}" data-layout="${l}">${l}</button>`).join('')}
          </div>
          <div class="graph-focus-bar">
            <input class="graph-focus-input" type="text" placeholder="focus entity id\u2026" aria-label="Focus entity" />
            <button class="btn btn--ghost graph-focus-clear" aria-label="Clear focus" style="display:none">&times;</button>
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
          <div class="graph-sidebar__section">
            <div class="panel__title" style="font-size:10px;margin-bottom:4px">Path</div>
            <input class="graph-path-input" type="text" placeholder="glob: src/**/*.ts" aria-label="Path filter" />
          </div>
        </aside>
        <div class="graph-canvas-wrap">
          <div class="graph-canvas" id="graph-canvas"></div>
        </div>
      </div>
      <div class="graph-progress">
        <div class="graph-progress__bar"><div class="graph-progress__fill" id="graph-progress-fill"></div></div>
        <span class="graph-progress__label" id="graph-progress-label">loading\u2026</span>
      </div>
    </div>
  `;

  _drawer = createDrawer();
  container.appendChild(_drawer);

  const progressFill = container.querySelector('#graph-progress-fill');
  const progressLabel = container.querySelector('#graph-progress-label');

  setProgress(progressFill, progressLabel, 5, 'initializing\u2026');

  try {
    const savedIndexId = localStorage.getItem('batho.activeIndexId');
    const indexData = await loadIndex();
    const activeIndexId = savedIndexId && indexData.indexes[savedIndexId]
      ? savedIndexId
      : indexData.currentIndexId;

    setProgress(progressFill, progressLabel, 15, 'loading bsg\u2026');

    let bsgData = null;
    let dataSource = 'bsg';

    try {
      bsgData = await loadBsg(activeIndexId);
    } catch (_) {
      bsgData = null;
    }

    if (!bsgData || !bsgData.nodes?.length) {
      setProgress(progressFill, progressLabel, 25, 'loading graph\u2026');
      const graphData = await loadGraph(activeIndexId);
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
      dataSource = 'graph';
    }

    _bsgData = bsgData;

    setProgress(progressFill, progressLabel, 50, `building graph (${formatInt(bsgData.nodes.length)} nodes)\u2026`);

    const typeCounts = {};
    const langCounts = {};
    const serviceCounts = {};
    const scopeCounts = {};
    for (const n of bsgData.nodes) {
      const t = (n.type || 'unknown').toUpperCase();
      typeCounts[t] = (typeCounts[t] || 0) + 1;
      const l = n.language || 'unknown';
      langCounts[l] = (langCounts[l] || 0) + 1;
      if (n.serviceTag) serviceCounts[n.serviceTag] = (serviceCounts[n.serviceTag] || 0) + 1;
      if (n.scopeTier) scopeCounts[n.scopeTier] = (scopeCounts[n.scopeTier] || 0) + 1;
    }

    if (params.get('types')) {
      params.get('types').split(',').forEach((k) => _filterState.types.add(k));
    } else {
      _filterState.types = new Set(Object.keys(typeCounts));
    }
    if (params.get('languages')) {
      params.get('languages').split(',').forEach((k) => _filterState.languages.add(k));
    } else {
      _filterState.languages = new Set(Object.keys(langCounts));
    }
    if (params.get('services')) {
      params.get('services').split(',').forEach((k) => _filterState.services.add(k));
    } else {
      _filterState.services = new Set(Object.keys(serviceCounts));
    }
    if (params.get('scopes')) {
      params.get('scopes').split(',').forEach((k) => _filterState.scopes.add(k));
    } else {
      _filterState.scopes = new Set(Object.keys(scopeCounts));
    }
    if (params.get('path')) _filterState.path = params.get('path');
    if (params.get('focus')) _filterState.focusId = params.get('focus');

    buildFilterChips(container, typeCounts, langCounts, serviceCounts, scopeCounts);

    const pathInput = container.querySelector('.graph-path-input');
    if (pathInput) {
      pathInput.value = _filterState.path;
      pathInput.addEventListener('input', () => {
        _filterState.path = pathInput.value.trim();
        applyFilters();
        syncUrl();
      });
    }

    setProgress(progressFill, progressLabel, 75, 'rendering graph\u2026');

    const cyEl = container.querySelector('#graph-canvas');
    const cytoscapeLib = await (await import('../assets/js/cy-import.js')).default();

    const requestedLayout = params.get('layout') || DEFAULT_LAYOUT;
    const requestedFocus = _filterState.focusId;

    requestAnimationFrame(() => {
      try {
        _cy = bootCytoscape(cytoscapeLib, cyEl, bsgData);

        if (LAYOUTS.includes(requestedLayout)) {
          container.querySelectorAll('.graph-layout-btn').forEach((btn) => {
            btn.classList.toggle('graph-layout-btn--active', btn.dataset.layout === requestedLayout);
          });
          runLayout(requestedLayout);
        }

        setupEvents(container);

        if (requestedFocus) {
          applyFocus(requestedFocus);
          const focusInput = container.querySelector('.graph-focus-input');
          if (focusInput) focusInput.value = requestedFocus;
          const clearBtn = container.querySelector('.graph-focus-clear');
          if (clearBtn) clearBtn.style.display = '';
        }

        setProgress(progressFill, progressLabel, 100, `${formatInt(bsgData.nodes.length)} nodes from ${dataSource}`);
        setTimeout(() => {
          const prog = container.querySelector('.graph-progress');
          if (prog) prog.classList.add('graph-progress--done');
        }, 1500);
      } catch (err) {
        console.error('[batho] Cytoscape init failed:', err);
        const canvasWrap = container.querySelector('.graph-canvas-wrap');
        if (canvasWrap) {
          canvasWrap.innerHTML = renderErrorPanel(err);
          const retryBtn = canvasWrap.querySelector('[data-action="retry"]');
          if (retryBtn) retryBtn.addEventListener('click', () => location.reload());
        }
      }
    });

    window.addEventListener('batho:index-changed', () => {
      const newPage = renderHypergraph(params);
      const mount = document.getElementById('page-mount');
      if (mount) { mount.innerHTML = ''; newPage.then((p) => mount.appendChild(p)); }
    }, { once: true });

  } catch (err) {
    container.innerHTML = renderErrorPanel(err);
    const retryBtn = container.querySelector('[data-action="retry"]');
    if (retryBtn) retryBtn.addEventListener('click', () => location.reload());
  }

  return container;
}

function bootCytoscape(cytoscape, container, bsgData) {
  const elements = [];
  const nodeIds = new Set();

  for (const n of bsgData.nodes) {
    if (!n || !n.id) continue;
    const type = (n.type || 'unknown').toUpperCase();
    const shortName = (n.name || n.id || '').split(/[/:.]/).pop() || n.id;
    nodeIds.add(n.id);
    elements.push({
      data: {
        id: n.id,
        label: n.name || n.id,
        shortName,
        kind: type,
        color: nodeColor(type),
        language: n.language || '',
        serviceTag: n.serviceTag || '',
        scopeTier: n.scopeTier || '',
        file: n.file || '',
        entityCount: 1,
      },
    });
  }

  for (const e of (bsgData.edges || [])) {
    const src = e.sourceId || e.source_id || e.from || e.source;
    const tgt = e.targetId || e.target_id || e.to || e.target;
    if (!src || !tgt || !nodeIds.has(src) || !nodeIds.has(tgt)) continue;
    const relType = (e.relationshipType || e.relationship_type || e.type || 'references').toLowerCase();
    elements.push({
      data: {
        id: `${src}->${tgt}:${relType}`,
        source: src,
        target: tgt,
        relationshipType: relType,
        edgeColor: edgeColor(relType),
      },
    });
  }

  const cy = cytoscape({
    container,
    elements,
    style: buildStylesheet(),
    layout: { name: 'grid', fit: true, padding: 40 },
    minZoom: 0.05,
    maxZoom: 8,
    wheelSensitivity: 0.2,
    hideEdgesOnViewport: true,
    textureOnViewport: false,
    motionBlur: false,
  });

  cy.on('zoom', () => {
    const z = cy.zoom();
    cy.nodes().style('font-size', z < 0.6 ? 0 : 10);
  });

  cy.on('tap', 'node', (evt) => {
    showNodeDrawer(evt.target.data(), bsgData);
  });

  cy.on('mouseover', 'node', (evt) => { evt.target.addClass('hovered'); });
  cy.on('mouseout', 'node', (evt) => { evt.target.removeClass('hovered'); });

  return cy;
}

function runLayout(name) {
  if (!_cy) return;
  try {
    _cy.layout({
      name,
      animate: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      animationDuration: 400,
      fit: true,
      padding: 40,
      ...(name === 'cose' ? { nodeRepulsion: () => 4000, idealEdgeLength: () => 50, randomize: false } : {}),
      ...(name === 'breadthfirst' ? { directed: true, spacingFactor: 1.2 } : {}),
      ...(name === 'concentric' ? { concentric: (n) => n.degree(), levelWidth: () => 3 } : {}),
    }).run();
  } catch (_) {
    _cy.layout({ name: 'grid', fit: true, padding: 40 }).run();
  }
}

function applyFilters() {
  if (!_cy) return;
  const { types, languages, services, scopes, path, focusId } = _filterState;

  _cy.batch(() => {
    _cy.nodes().forEach((node) => {
      const d = node.data();
      const typeMatch = types.has(d.kind);
      const langMatch = languages.has(d.language || 'unknown');
      const svcMatch = services.size === 0 || !d.serviceTag || services.has(d.serviceTag);
      const scopeMatch = scopes.size === 0 || !d.scopeTier || scopes.has(d.scopeTier);
      const pathMatch = !path || matchGlob(path, d.file || '');
      node.style('display', typeMatch && langMatch && svcMatch && scopeMatch && pathMatch ? 'element' : 'none');
    });

    if (focusId) applyFocus(focusId);
  });
}

function applyFocus(focusId) {
  if (!_cy) return;
  _filterState.focusId = focusId;

  const target = _cy.getElementById(focusId);
  if (!target || target.empty()) return;

  _cy.nodes().removeClass('focus-hidden focus-visible-node');

  const visibleNodes = _cy.nodes().filter((n) => n.style('display') !== 'none');

  visibleNodes.forEach((n) => {
    if (n.id() !== focusId) n.addClass('focus-hidden');
    else n.addClass('focus-visible-node');
  });

  _cy.animate({
    center: { eles: target },
    zoom: Math.max(_cy.zoom(), 1.5),
    duration: 300,
  });

  const clearBtn = document.querySelector('.graph-focus-clear');
  if (clearBtn) clearBtn.style.display = '';
}

function clearFocus() {
  if (!_cy) return;
  _filterState.focusId = null;
  _cy.nodes().removeClass('focus-hidden focus-visible-node');
  const clearBtn = document.querySelector('.graph-focus-clear');
  if (clearBtn) clearBtn.style.display = 'none';
  const focusInput = document.querySelector('.graph-focus-input');
  if (focusInput) focusInput.value = '';
  applyFilters();
  syncUrl();
}

function buildFilterChips(container, typeCounts, langCounts, serviceCounts, scopeCounts) {
  const mounts = {
    types: [container.querySelector('#graph-types-mount'), typeCounts],
    languages: [container.querySelector('#graph-langs-mount'), langCounts],
    services: [container.querySelector('#graph-services-mount'), serviceCounts],
    scopes: [container.querySelector('#graph-scopes-mount'), scopeCounts],
  };

  for (const [facet, [mount, counts]] of Object.entries(mounts)) {
    if (!mount) continue;
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    for (const [label, count] of sorted) {
      const chip = createChipFilter({
        label,
        count,
        active: _filterState[facet].has(label),
        onChange: (active) => {
          if (active) _filterState[facet].add(label);
          else _filterState[facet].delete(label);
          applyFilters();
          syncUrl();
        },
      });
      mount.appendChild(chip);
    }
  }
}

function showNodeDrawer(data, bsgData) {
  if (!_drawer) return;

  const props = [
    ['id', data.id],
    ['name', data.label],
    ['type', data.kind],
    ['language', data.language],
    ['service', data.serviceTag],
    ['scope', data.scopeTier],
    ['file', data.file],
  ].filter(([, v]) => v);

  const bsgNode = bsgData.nodes.find((n) => n.id === data.id);
  let metaHtml = '';
  if (bsgNode?.metadata && typeof bsgNode.metadata === 'object') {
    const metaEntries = Object.entries(bsgNode.metadata).filter(([, v]) => v != null && v !== '');
    if (metaEntries.length) {
      metaHtml = `<div class="drawer-section"><div class="drawer-section__title">Metadata</div>${
        metaEntries.map(([k, v]) =>
          `<div class="drawer-prop"><span class="drawer-prop__key">${escapeHtml(k)}</span><span class="drawer-prop__val" title="${escapeHtml(String(v))}">${escapeHtml(String(v))}</span></div>`
        ).join('')
      }</div>`;
    }
  }

  const propsHtml = props.map(([k, v]) =>
    `<div class="drawer-prop"><span class="drawer-prop__key">${escapeHtml(k)}</span><span class="drawer-prop__val" title="${escapeHtml(String(v))}">${escapeHtml(String(v))}</span></div>`
  ).join('');

  openDrawer(_drawer, {
    title: data.label || data.id || 'Node',
    content: propsHtml + metaHtml,
  });
}

function setupEvents(container) {
  container.querySelectorAll('.graph-layout-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.graph-layout-btn').forEach((b) => b.classList.remove('graph-layout-btn--active'));
      btn.classList.add('graph-layout-btn--active');
      runLayout(btn.dataset.layout);
      syncUrl();
    });
  });

  const focusInput = container.querySelector('.graph-focus-input');
  const clearBtn = container.querySelector('.graph-focus-clear');

  if (focusInput) {
    focusInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const val = focusInput.value.trim();
        if (val) applyFocus(val);
        else clearFocus();
        syncUrl();
      }
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', clearFocus);
  }
}

function syncUrl() {
  const params = {};
  const allTypes = _bsgData ? new Set(_bsgData.nodes.map((n) => (n.type || 'unknown').toUpperCase())) : new Set();
  const allLangs = _bsgData ? new Set(_bsgData.nodes.map((n) => n.language || 'unknown')) : new Set();
  const allServices = _bsgData ? new Set(_bsgData.nodes.filter((n) => n.serviceTag).map((n) => n.serviceTag)) : new Set();
  const allScopes = _bsgData ? new Set(_bsgData.nodes.filter((n) => n.scopeTier).map((n) => n.scopeTier)) : new Set();

  if (_filterState.types.size < allTypes.size) params.types = [..._filterState.types].join(',');
  if (_filterState.languages.size < allLangs.size) params.languages = [..._filterState.languages].join(',');
  if (_filterState.services.size < allServices.size) params.services = [..._filterState.services].join(',');
  if (_filterState.scopes.size < allScopes.size) params.scopes = [..._filterState.scopes].join(',');
  if (_filterState.path) params.path = _filterState.path;
  if (_filterState.focusId) params.focus = _filterState.focusId;

  const activeLayout = document.querySelector('.graph-layout-btn--active');
  if (activeLayout && activeLayout.dataset.layout !== DEFAULT_LAYOUT) params.layout = activeLayout.dataset.layout;

  router.navigate('/hypergraph', params);
}

function setProgress(fill, label, pct, text) {
  if (fill) fill.style.width = `${pct}%`;
  if (label) label.textContent = text;
}

const KIND_COLORS = {
  FUNCTION: '#7df9ff',
  METHOD: '#4ac4cc',
  CLASS: '#cfbcff',
  STRUCT: '#b8a9e0',
  INTERFACE: '#a998d4',
  ENUM: '#c4b5e8',
  TRAIT: '#bfa6da',
  NAMESPACE: '#64b5f6',
  FIELD: '#4ac4cc',
  VARIABLE: '#9e9e9e',
  MODULE: '#b0bec5',
  DOCUMENT: '#78909c',
  SETTING: '#e7c365',
  ENTRY_POINT: '#81c784',
  SECTION: '#90a4ae',
  ELEMENT: '#b0bec5',
};

const EDGE_COLORS = {
  calls: '#7df9ff',
  contains: '#cfbcff',
  imports: '#cdc0e9',
  extends: '#e7c365',
  implements: '#a5d6a7',
  references: '#90a4ae',
  defines: '#b0bec5',
  uses: '#80cbc4',
};

function nodeColor(kind) {
  return KIND_COLORS[kind] || '#9e9e9e';
}

function edgeColor(type) {
  return EDGE_COLORS[type] || '#494551';
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
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
        <div class="error-panel__icon">\u26A0</div>
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
