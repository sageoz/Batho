/**
 * Batho Nexus Dashboard SPA Client
 * Ancient-futuristic command center. Zero build step.
 * Nexus Layers: L1 (file topology) / L2 (intra-file symbols) / L3 (node neighborhood)
 *
 * Architecture:
 * - PixiRenderer: Pixi.js v8 WebGL infinite-canvas renderer
 * - SpatialClient: binary msgpack viewport culling
 * - AgentEventClient: SSE real-time agent action feed
 * - DrawerState: independent left/right glassmorphic overlays
 */

// --- IMPORTS (ES Modules) ---
import { PixiRenderer } from './pixi-renderer.js';
import { SpatialClient } from './spatial-client.js';

// --- STATE MANAGEMENT ---
const STATE = {
  currentIndexId: '',
  workspacePath:  '',
  indexes:        [],
  currentTab:     'overview',
  renderer:       null,    // PixiRenderer instance
  spatialClient:  null,    // SpatialClient instance
  agentClient:    null,    // AgentEventClient instance
  activeLayer:    'L1',    // 'L1' | 'L2'
  activeNode:     null,    // active node ID
  activeNodeData: null,    // full node data object
  activeFilePath: null,
  blastHops:      1,       // 1 | 2
  colorMode:      'kind',  // 'kind' | 'cai' | 'bis'
};

// --- DRAWER STATE ---
const DrawerState = {
  left:  { open: true,  tabId: 'overview' },
  right: { open: false, tabId: 'entity'   },

  toggleLeft() {
    this.left.open = !this.left.open;
    const el = document.getElementById('left-drawer');
    const btn = document.getElementById('btn-toggle-left');
    el.classList.toggle('drawer-open',   this.left.open);
    el.classList.toggle('drawer-closed', !this.left.open);
    const icon = btn.querySelector('svg polyline');
    if (icon) icon.setAttribute('points', this.left.open ? '6,2 2,5 6,8' : '4,2 8,5 4,8');
  },

  toggleRight() {
    this.right.open = !this.right.open;
    const el = document.getElementById('right-drawer');
    const btn = document.getElementById('btn-toggle-right');
    el.classList.toggle('drawer-open',   this.right.open);
    el.classList.toggle('drawer-closed', !this.right.open);
    const icon = btn.querySelector('svg polyline');
    if (icon) icon.setAttribute('points', this.right.open ? '4,2 8,5 4,8' : '6,2 2,5 6,8');
  },

  openRight(tabId) {
    if (!this.right.open) this.toggleRight();
    if (tabId) this.switchRightTab(tabId);
  },

  switchLeftTab(tabId) {
    this.left.tabId = tabId;
    document.querySelectorAll('[data-left-tab]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.leftTab === tabId);
    });
    document.querySelectorAll('#left-drawer .tab-content').forEach(el => {
      el.classList.toggle('hidden', el.id !== `tab-${tabId}`);
    });
  },

  switchRightTab(tabId) {
    this.right.tabId = tabId;
    document.querySelectorAll('[data-right-tab]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.rightTab === tabId);
    });
    document.querySelectorAll('#right-drawer .tab-content').forEach(el => {
      el.classList.toggle('hidden', el.id !== `tab-${tabId}`);
    });
  },
};

// --- API LAYER ---
async function apiGet(path, retries = 5, delay = 500) {
  for (let i = 0; i < retries; i++) {
    try {
      const response = await fetch(path);
      if (response.status === 503 && i < retries - 1) {
        console.warn(`Bridge starting up (503). Retrying ${path} in ${delay}ms...`);
        await new Promise(res => setTimeout(res, delay));
        continue;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const json = await response.json();
      return json.ok !== undefined ? json : { ok: true, data: json };
    } catch (err) {
      if (i === retries - 1) {
        console.error(`API GET failed for ${path}:`, err);
        throw err;
      }
      console.warn(`API GET failed (attempt ${i + 1}/${retries}). Retrying in ${delay}ms...`);
      await new Promise(res => setTimeout(res, delay));
    }
  }
}

// --- CORE UTILS ---
function formatTimestamp(ts) {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function updateElementText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function showError(message) {
  const bootstrapper = document.getElementById('bootstrapper');
  if (bootstrapper) {
    bootstrapper.innerHTML = `
      <div style="color: #ff3333; text-align:center;">
        <div style="font-size: 16px; font-weight: bold; margin-bottom: 8px;">⟁ ERROR</div>
        <div style="font-size: 12px; font-family: monospace;">${escapeHtml(message)}</div>
        <button class="btn btn-sm" style="margin-top: 16px; border-color: #ff3333; color: #ff3333;" onclick="window.location.reload()">RETRY</button>
      </div>
    `;
    bootstrapper.classList.remove('hidden');
  }
  console.error(message);
}

// --- ROUTER ---
const Router = {
  routes: {},
  register(route, callback) {
    this.routes[route] = callback;
  },
  init() {
    window.addEventListener('hashchange', () => this.handle());
    this.handle();
  },
  navigate(route) {
    window.location.hash = route;
  },
  handle() {
    const hash = window.location.hash || '#overview';
    
    // Parse route and parameters
    // Simple parser: #overview, #file/path/to/file.py, #search
    let route = hash;
    let param = null;
    
    if (hash.startsWith('#file/')) {
      route = '#file';
      param = decodeURIComponent(hash.slice(6));
    }
    
    const handler = this.routes[route] || this.routes['#overview'];
    handler(param);
  }
};

// ══════════════════════════════════════════════════════════════
// AGENT EVENT CLIENT (SSE real-time feed)
// ══════════════════════════════════════════════════════════════

class AgentEventClient {
  constructor(url = '/api/v2/events/stream') {
    this._url = url;
    this._es  = null;
    this._reconnectDelay = 2000;
    this._reconnectTimer = null;
  }

  connect() {
    if (this._es) return;
    try {
      this._es = new EventSource(this._url);

      this._es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data);
          this._dispatch(event);
        } catch { /* ignore parse errors */ }
      };

      this._es.onerror = () => {
        this._es.close();
        this._es = null;
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = setTimeout(() => this.connect(), this._reconnectDelay);
      };

      this._es.onopen = () => {
        clearTimeout(this._reconnectTimer);
        const dot = document.querySelector('.status-dot');
        if (dot) dot.style.background = 'var(--accent-green)';
      };
    } catch (err) {
      console.warn('AgentEventClient: SSE not available', err);
    }
  }

  _dispatch(event) {
    const nodeId = event.node_id;
    if (!STATE.renderer || !nodeId) return;

    switch (event.type) {
      case 'agent_read':
        STATE.renderer.flashNodeGold(nodeId);
        break;
      case 'agent_write':
        STATE.renderer.flashNodeCyan(nodeId);
        break;
      case 'agent_error':
        STATE.renderer.flashNodeRed(nodeId);
        break;
      default:
        STATE.renderer.flashNodeGold(nodeId, 1000);
    }
  }

  disconnect() {
    clearTimeout(this._reconnectTimer);
    if (this._es) { this._es.close(); this._es = null; }
  }
}

// ══════════════════════════════════════════════════════════════
// RENDERER INITIALISATION
// ══════════════════════════════════════════════════════════════

async function initRenderer() {
  if (STATE.renderer) STATE.renderer.destroy();

  STATE.renderer = new PixiRenderer('graph-canvas-container');
  await STATE.renderer.init();

  // Node click → HUD + blast radius
  STATE.renderer.onNodeClick((nodeData) => {
    STATE.activeNode     = String(nodeData.id);
    STATE.activeNodeData = nodeData;
    const isTwoHop = document.getElementById('toggle-2hop').checked;
    applyBlastRadius(STATE.activeNode, isTwoHop);
    showHud(nodeData);

    if (DrawerState.right.open && DrawerState.right.tabId === 'entity') {
      updateRightEntityPanel(nodeData);
    }
  });

  // Viewport moved → fetch next quadtree chunk
  STATE.renderer.onViewportMoved((bounds) => {
    loadViewportChunk(bounds);
  });

  // Spatial client wired to Pixi viewport
  STATE.spatialClient = new SpatialClient();

  STATE.spatialClient.onLayoutReady = (result) => {
    console.log('[Batho] onLayoutReady fired', result);
    loadViewportChunk();
  };

  STATE.spatialClient.onGeometryUpdate = (data) => {
    console.log('[Batho] onGeometryUpdate', data?.nodes?.length, 'nodes', data?.edges?.length, 'edges');
    if (!STATE.renderer || (!data.nodes?.length && !data.edges?.length)) {
      console.warn('[Batho] onGeometryUpdate: empty data, nothing to render');
      return;
    }
    if (STATE._l1DataLoaded) {
      // Topology already rendered — only update spatial positions, skip full reload
      if (typeof STATE.renderer.updatePositions === 'function') {
        STATE.renderer.updatePositions(data);
      }
    } else {
      STATE.renderer.loadData(data);
    }
  };

  // Compute layout
  console.log('[Batho] calling computeLayout', STATE.activeLayer);
  STATE.spatialClient.computeLayout(STATE.activeLayer)
    .then(r => console.log('[Batho] computeLayout resolved', r))
    .catch(err => console.error('[Batho] Spatial layout failed:', err));

  // Start SSE agent event stream
  if (!STATE.agentClient) {
    STATE.agentClient = new AgentEventClient();
    STATE.agentClient.connect();
  }

  return STATE.renderer;
}

async function loadViewportChunk(bounds) {
  if (!STATE.renderer || !STATE.spatialClient) return;
  /* The backend spatial engine uses igraph world coordinates (~-20 to +20).
     We always request a very large viewport so we get all nodes; the backend
     quadtree handles culling. On subsequent pan/zoom calls we pass tighter
     bounds (converted back from Pixi space) but for initial load this
     ensures nodes are never missed due to coordinate space mismatch. */
  const LARGE = 10000;
  console.log('[Batho] loadViewportChunk firing, layer=', STATE.activeLayer);
  try {
    const result = await STATE.spatialClient.loadViewportChunk(
      -LARGE / 2, -LARGE / 2, LARGE, LARGE, 1.0, STATE.activeLayer, false
    );
    console.log('[Batho] loadViewportChunk returned', result?.nodes?.length, 'nodes');
  } catch (err) {
    console.error('[Batho] Viewport chunk load failed:', err);
  }
}

async function renderGraph() {
  if (!STATE.renderer) {
    await initRenderer();
  }
}

// ══════════════════════════════════════════════════════════════
// ADJACENCY INDEX  (rebuilt on each L1/L2 load)
// ══════════════════════════════════════════════════════════════

// Maps nodeId -> { out: Set<string>, in: Set<string> }
const _adj = new Map();

function _buildAdjacencyIndex(edges) {
  _adj.clear();
  for (const edge of edges) {
    const s = String(edge.source ?? edge.s);
    const t = String(edge.target ?? edge.t);
    if (!_adj.has(s)) _adj.set(s, { out: new Set(), in: new Set() });
    if (!_adj.has(t)) _adj.set(t, { out: new Set(), in: new Set() });
    _adj.get(s).out.add(t);
    _adj.get(t).in.add(s);
  }
}

// ══════════════════════════════════════════════════════════════
// BLAST RADIUS
// ══════════════════════════════════════════════════════════════

function applyBlastRadius(nodeId, isTwoHop) {
  if (!STATE.renderer) return;

  const hop1 = [];
  const hop2 = [];

  // O(degree) using adjacency index
  const entry = _adj.get(nodeId);
  if (entry) {
    for (const t of entry.out) if (t !== nodeId) hop1.push(t);
    for (const s of entry.in)  if (s !== nodeId && !entry.out.has(s)) hop1.push(s);
  } else {
    // Fallback: scan renderer edges (small graphs or index not yet built)
    for (const [key] of STATE.renderer._edges) {
      const [s, t] = key.split('→');
      if (s === nodeId && !hop1.includes(t)) hop1.push(t);
      if (t === nodeId && !hop1.includes(s)) hop1.push(s);
    }
  }

  if (isTwoHop) {
    const hop1Set = new Set(hop1);
    for (const h1 of hop1) {
      const h1Entry = _adj.get(h1);
      if (h1Entry) {
        for (const t of h1Entry.out) {
          if (t !== nodeId && !hop1Set.has(t) && !hop2.includes(t)) hop2.push(t);
        }
        for (const s of h1Entry.in) {
          if (s !== nodeId && !hop1Set.has(s) && !hop2.includes(s)) hop2.push(s);
        }
      }
    }
  }

  STATE.renderer.applyBlastRadius(nodeId, hop1, hop2);
}

function resetBlastRadius() {
  if (!STATE.renderer) return;
  STATE.renderer.clearBlastRadius();
  STATE.activeNode     = null;
  STATE.activeNodeData = null;
}

// ══════════════════════════════════════════════════════════════
// FLOATING HUD STRIP
// ══════════════════════════════════════════════════════════════

function showHud(nodeData) {
  const data     = nodeData;
  const isFile   = data.type === 'FILE' || data.type === 'file' || (String(data.id)).startsWith('file:');
  const filePath = isFile ? (data.file || String(data.id).replace('file:', '')) : data.file;

  updateElementText('inspector-title',
    isFile ? (filePath ? filePath.split('/').pop() : data.label || data.id)
           : (data.name || data.label || data.id));

  updateElementText('insp-entities', data.entity_count != null ? data.entity_count : '—');
  updateElementText('insp-out', data.out_degree ?? '—');
  updateElementText('insp-in',  data.in_degree  ?? '—');

  const badge = document.getElementById('details-layer-badge');
  badge.textContent = STATE.activeLayer;
  badge.classList.remove('hidden');

  document.getElementById('btn-drill-down').classList.toggle('hidden', STATE.activeLayer !== 'L1' || !isFile);
  document.getElementById('btn-isolate-file').classList.toggle('hidden', !isFile);

  if (isFile && filePath) STATE.activeFilePath = filePath;

  document.getElementById('node-inspector').classList.remove('hidden');
}

function hideHud() {
  document.getElementById('node-inspector').classList.add('hidden');
  STATE.activeNode = null;
}

// ══════════════════════════════════════════════════════════════
// RIGHT DRAWER — ENTITY PANEL
// ══════════════════════════════════════════════════════════════

function updateRightEntityPanel(data) {
  const isFile   = data.type === 'FILE' || data.type === 'file' || (String(data.id)).startsWith('file:');
  const filePath = isFile ? (data.file || String(data.id).replace('file:', '')) : data.file;
  const lang     = data.language || '';

  document.getElementById('right-drawer-title').textContent =
    isFile ? 'File Inspector' : 'Symbol Inspector';

  const body = document.getElementById('right-entity-body');
  body.innerHTML = `
    <div class="node-meta-block">
      <div class="node-meta-title">${escapeHtml(data.label || data.name || data.id || '—')}</div>
      <div class="node-meta-tag">${escapeHtml((data.type || 'FILE').toUpperCase())}</div>
    </div>
    <div class="meta-list">
      ${filePath ? `<div class="meta-item"><span class="meta-label">Path</span><span class="meta-val" title="${escapeHtml(filePath)}">${escapeHtml(filePath)}</span></div>` : ''}
      ${lang     ? `<div class="meta-item"><span class="meta-label">Language</span><span class="meta-val">${escapeHtml(lang)}</span></div>` : ''}
      ${data.entity_count != null ? `<div class="meta-item"><span class="meta-label">Symbols</span><span class="meta-val">${data.entity_count}</span></div>` : ''}
      ${data.line != null         ? `<div class="meta-item"><span class="meta-label">Line</span><span class="meta-val">${data.line}</span></div>` : ''}
      ${data.signature            ? `<div class="meta-item"><span class="meta-label">Signature</span><span class="meta-val" title="${escapeHtml(data.signature)}">${escapeHtml(data.signature)}</span></div>` : ''}
    </div>
    <div style="margin-top:12px;display:flex;gap:6px;padding:0 14px;">
      <button class="btn btn-sm outline-btn" id="rd-btn-load-code">View Code</button>
      <button class="btn btn-sm btn-violet"  id="rd-btn-telemetry">Telemetry</button>
    </div>
  `;

  document.getElementById('rd-btn-load-code')?.addEventListener('click', () => {
    DrawerState.switchRightTab('code');
    loadCodeViewer(filePath, lang);
  });

  document.getElementById('rd-btn-telemetry')?.addEventListener('click', () => {
    DrawerState.switchRightTab('telemetry');
    loadTelemetryPanel(String(data.id));
  });
}

// ══════════════════════════════════════════════════════════════
// RIGHT DRAWER — CODE VIEWER
// ══════════════════════════════════════════════════════════════

async function loadCodeViewer(filePath, lang) {
  if (!filePath) return;

  updateElementText('code-viewer-filename', filePath.split('/').pop());
  const langBadge = document.getElementById('code-viewer-lang');
  if (lang) { langBadge.textContent = lang; langBadge.classList.remove('hidden'); }

  const scroll = document.getElementById('code-viewer-content');
  scroll.innerHTML = '<div class="empty-state">Loading source...</div>';

  try {
    const result = await apiGet(`/api/v2/file/content?path=${encodeURIComponent(filePath)}`);
    if (result.ok && result.data && result.data.content) {
      const langClass = (lang && lang !== 'unknown') ? `language-${lang}` : 'language-none';
      scroll.innerHTML = `<pre><code class="${langClass}" id="code-block">${escapeHtml(result.data.content)}</code></pre>`;
      const cb = document.getElementById('code-block');
      if (cb && typeof Prism !== 'undefined') Prism.highlightElement(cb);
    } else {
      scroll.innerHTML = '<div class="empty-state">Source not available.</div>';
    }
  } catch {
    scroll.innerHTML = '<div class="empty-state" style="color:var(--accent-red);">Error loading source.</div>';
  }
}

// ══════════════════════════════════════════════════════════════
// RIGHT DRAWER — TELEMETRY PANEL
// ══════════════════════════════════════════════════════════════

async function loadTelemetryPanel(nodeId) {
  /* CAI */
  try {
    const r = await apiGet(`/api/v2/analysis/amnesia?node_id=${encodeURIComponent(nodeId)}`);
    if (r.ok && r.data) {
      const d = r.data;
      const pct = d.coverage_percent ?? 0;
      document.getElementById('cai-bar').style.width = `${pct}%`;
      updateElementText('cai-coverage-val', `${pct}%`);
      updateElementText('cai-amnesia-val',  d.amnesia_zone?.length ?? '—');
      updateElementText('cai-critical-val', d.critical_misses?.length ?? '—');

      const missesList = document.getElementById('cai-misses-list');
      missesList.innerHTML = '';
      (d.critical_misses || []).slice(0, 5).forEach(m => {
        const el = document.createElement('div');
        el.className = 'critical-miss-item';
        el.innerHTML = `<span>⚠</span> ${escapeHtml(m.name || m.id || '')}`;
        missesList.appendChild(el);
      });

      /* Update renderer CAI heatmap data */
      const caiMap = {};
      (d.amnesia_zone || []).forEach(n => { caiMap[n.id] = { risk: 1.0 }; });
      (d.within_reach || []).forEach(n  => { caiMap[n.id] = { risk: 0.1 }; });
      (d.critical_misses || []).forEach(n => { caiMap[n.id] = { risk: 0.8 }; });
      if (STATE.renderer) STATE.renderer.setCaiData(caiMap);
    }
  } catch { /* CAI not available for this node */ }

  /* BIS */
  try {
    const r = await apiGet(`/api/v2/hypergraph/level3?node_id=${encodeURIComponent(nodeId)}`);
    if (r.ok && r.data && r.data.bis_score != null) {
      const score = Math.round(r.data.bis_score);
      updateBisGauge(score);
      if (STATE.renderer) {
        const bisMap = {};
        (r.data.nodes || []).forEach(n => { bisMap[n.id] = { score: n.bis_score ?? score }; });
        STATE.renderer.setBisData(bisMap);
      }
    }
  } catch { /* BIS not available */ }

  /* Green telemetry */
  try {
    const r = await apiGet('/api/v2/telemetry/stats');
    if (r.ok && r.data) {
      updateElementText('tel-avg-ms',  r.data.avg_duration_ms ?? '—');
      updateElementText('tel-requests', r.data.total_requests ?? '—');
      updateElementText('tel-carbon',  r.data.carbon_estimate_mg ?? '—');
    }
  } catch { /* telemetry not available */ }
}

function updateBisGauge(score) {
  const circumference = 131.95;
  const offset = circumference - (score / 100) * circumference;
  const fill = document.getElementById('bis-gauge-fill');
  const label = document.getElementById('bis-gauge-label');
  const val = document.getElementById('bis-score-val');
  const detail = document.getElementById('bis-detail');

  if (!fill) return;

  fill.style.strokeDashoffset = offset;

  let color = '#00ff88'; let cls = 'good';
  if (score < 50) { color = '#ff3333'; cls = 'bad'; }
  else if (score < 80) { color = '#ffab00'; cls = 'warn'; }
  fill.style.stroke = color;

  if (label)  label.textContent = `${score}`;
  if (val) {
    val.textContent = `${score}/100`;
    val.className = `bis-score-val ${cls}`;
  }
  if (detail) detail.textContent = score >= 80 ? 'High integrity' : score >= 50 ? 'Moderate integrity' : 'Low integrity — review imports';
}

// ══════════════════════════════════════════════════════════════
// UI HELPERS
// ══════════════════════════════════════════════════════════════

function setActiveLayer(layer) {
  STATE.activeLayer = layer;
  document.querySelectorAll('.layer-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-layer') === layer);
  });
  const titles = {
    L1: ['Dependency Hypergraph (L1)', 'File topology · infinite canvas'],
    L2: [`Symbol Graph (L2)${STATE.activeFilePath ? ': ' + STATE.activeFilePath.split('/').pop() : ''}`, 'Intra-file symbol relations'],
  };
  const [title, subtitle] = titles[layer] || titles.L1;
  updateElementText('graph-view-title', title);
  updateElementText('graph-view-subtitle', subtitle);
}

function setColorMode(mode) {
  STATE.colorMode = mode;
  document.querySelectorAll('.color-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
  if (STATE.renderer) STATE.renderer.setColorMode(mode);
}

function populateFilesList(nodes) {
  const filesList = document.getElementById('files-list');
  filesList.innerHTML = '';
  nodes.forEach(n => {
    const div = document.createElement('div');
    div.className = 'file-item';
    div.dataset.path = n.file;
    div.innerHTML = `
      <span>${escapeHtml((n.file || '').split('/').pop())}</span>
      <span class="file-meta">${n.entity_count || 0} sym</span>
    `;
    div.addEventListener('click', () => {
      document.querySelectorAll('.file-item').forEach(el => el.classList.remove('active'));
      div.classList.add('active');
      loadL2(n.file);
    });
    filesList.appendChild(div);
  });
}

// ══════════════════════════════════════════════════════════════
// GRAPH DATA LOADERS
// ══════════════════════════════════════════════════════════════

async function loadL1() {
  hideHud();
  resetBlastRadius();
  setActiveLayer('L1');

  try {
    /* Step 1: Fetch topology immediately so the UI is responsive */
    const graphPromise = apiGet('/api/v2/hypergraph/level1');

    /* Step 2: Fire layout in the background using a scalable algorithm (FR).
       Do NOT await this before pushing nodes to the renderer. */
    fetch('/api/v2/spatial/layout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ layer: 'L1', algorithm: 'fruchterman_reingold', seed: 42 }),
    }).then(() => {
      /* Once layout completes, trigger a spatial client viewport update */
      if (STATE.spatialClient) {
        STATE.spatialClient.loadViewportChunk(-5000, -5000, 10000, 10000, 1.0, 'L1');
      }
    }).catch(console.error);

    const graphResponse = await graphPromise;
    if (!graphResponse.ok || !graphResponse.data) return;
    const graphData = graphResponse.data;
    populateFilesList(graphData.nodes || []);

    /* Step 3: init renderer and feed data directly */
    await renderGraph();
    STATE.renderer.loadData({
      nodes: graphData.nodes || [],
      edges: graphData.edges || [],
    });
    // Build adjacency index for O(degree) blast radius lookups
    _buildAdjacencyIndex(graphData.edges || []);
    STATE._l1DataLoaded = true;
    console.log('[Batho] L1 rendered:', (graphData.nodes || []).length, 'nodes');
  } catch (err) {
    console.error('Failed to load L1 graph:', err);
  }
}

async function loadL2(filePath) {
  if (!filePath) return;
  hideHud();
  resetBlastRadius();
  STATE._l1DataLoaded = false;
  STATE.activeFilePath = filePath;
  setActiveLayer('L2');

  document.querySelectorAll('.file-item').forEach(el => {
    el.classList.toggle('active', el.dataset.path === filePath);
  });

  try {
    const l2Response = await apiGet(`/api/v2/hypergraph/level2?file=${encodeURIComponent(filePath)}`);
    await renderGraph();
    if (l2Response.ok && l2Response.data) {
      STATE.renderer.loadData({
        nodes: l2Response.data.nodes || [],
        edges: l2Response.data.edges || [],
      });
      _buildAdjacencyIndex(l2Response.data.edges || []);
    }
    if (STATE.spatialClient) {
      await STATE.spatialClient.computeLayout('L2');
      loadViewportChunk();
    }
  } catch (err) {
    console.error('Failed to load L2 graph:', err);
  }
}

async function loadL3(nodeId, nodeName) {
  hideHud();
  resetBlastRadius();
  STATE._l1DataLoaded = false;

  updateElementText('graph-view-title', `Neighborhood (L3): ${nodeName}`);
  updateElementText('graph-view-subtitle', `Bidirectional context graph for ${nodeName}`);

  try {
    const l3Response = await apiGet(`/api/v2/hypergraph/level3?node_id=${encodeURIComponent(nodeId)}`);
    if (!l3Response.ok || !l3Response.data) return;

    await renderGraph();

    if (STATE.spatialClient) {
      await STATE.spatialClient.computeLayout('L3');
      loadViewportChunk();
    }

    if (STATE.renderer) STATE.renderer.centerOnNode(nodeId);
  } catch (err) {
    console.error('Failed to load L3 neighborhood:', err);
  }
}

// --- BOOTSTRAP DATA LOADING ---
async function bootstrapApp() {
  try {
    const indexResponse = await apiGet('/.batho/index.json');
    if (!indexResponse.ok) throw new Error('Failed to load indexes catalog');

    const indexData = indexResponse.data;
    STATE.indexes = indexData.indexes || [];
    STATE.currentIndexId = indexData.current_index_id || '';

    const selector = document.getElementById('index-selector');
    selector.innerHTML = '';

    if (STATE.indexes.length === 0) {
      selector.innerHTML = '<option value="">No indexes</option>';
    }

    STATE.indexes.forEach(idx => {
      const option = document.createElement('option');
      option.value = idx.index_id || idx.id;
      option.textContent = (idx.index_id || idx.id).slice(0, 12) + '...';
      if (idx.index_id === STATE.currentIndexId || idx.id === STATE.currentIndexId) {
        option.selected = true;
        STATE.workspacePath = idx.root || '';
      }
      selector.appendChild(option);
    });

    updateElementText('workspace-label', `workspace: ${STATE.workspacePath || 'unknown'}`);

    const activeIdx = STATE.indexes.find(idx => (idx.index_id || idx.id) === STATE.currentIndexId);
    if (activeIdx) {
      updateElementText('stat-files', activeIdx.file_count || '0');
      updateElementText('stat-entities', activeIdx.entity_count || '0');
      updateElementText('stat-relationships', activeIdx.relationship_count || '0');
      updateElementText('meta-index-id', activeIdx.index_id || activeIdx.id || '—');
      updateElementText('meta-created', formatTimestamp(activeIdx.timestamp));
      updateElementText('meta-hash', activeIdx.repo_hash ? activeIdx.repo_hash.slice(0, 8) : '—');
    }

    const historyContainer = document.getElementById('run-history');
    historyContainer.innerHTML = '';
    if (STATE.indexes.length > 1) {
      STATE.indexes.forEach(idx => {
        const id = idx.index_id || idx.id;
        const item = document.createElement('div');
        item.className = `history-item ${id === STATE.currentIndexId ? 'active' : ''}`;
        item.innerHTML = `
          <span>${id.slice(0, 8)}</span>
          <span class="history-time">${formatTimestamp(idx.timestamp)}</span>
        `;
        item.addEventListener('click', () => {
          STATE.currentIndexId = id;
          bootstrapApp();
        });
        historyContainer.appendChild(item);
      });
    } else {
      historyContainer.innerHTML = '<div class="empty-state">No other runs recorded.</div>';
    }

    // Reveal shell, then load graph
    document.getElementById('bootstrapper').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');

    await loadL1();

  } catch (err) {
    document.getElementById('bootstrapper').innerHTML = `
      <div style="color: #ff3333; text-align:center;">
        <div style="font-size: 16px; font-weight: bold; margin-bottom: 8px;">⟁ CORE TELEMETRY CRITICAL FAULT</div>
        <div style="font-size: 12px; font-family: monospace;">${escapeHtml(err.message)}</div>
        <button class="btn btn-sm" style="margin-top: 16px; border-color: #ff3333; color: #ff3333;" onclick="window.location.reload()">RETRY CONNECTION</button>
      </div>
    `;
  }
}

// ══════════════════════════════════════════════════════════════
// VIEW ROUTES
// ══════════════════════════════════════════════════════════════

Router.register('#overview', () => {
  DrawerState.switchLeftTab('overview');
  if (STATE.activeLayer !== 'L1') loadL1();
});

Router.register('#file', async (filePath) => {
  DrawerState.switchLeftTab('files');
  if (filePath) loadL2(filePath);
});

Router.register('#search', () => {
  DrawerState.switchLeftTab('search');
});

// ══════════════════════════════════════════════════════════════
// GLOBAL EVENT LISTENERS
// ══════════════════════════════════════════════════════════════

/* Left drawer tab buttons */
document.querySelectorAll('[data-left-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    const tabId = btn.dataset.leftTab;
    DrawerState.switchLeftTab(tabId);
    if (tabId === 'overview') Router.navigate('#overview');
    else if (tabId === 'search') Router.navigate('#search');
  });
});

/* Right drawer tab buttons */
document.querySelectorAll('[data-right-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    const tabId = btn.dataset.rightTab;
    DrawerState.switchRightTab(tabId);
    if (tabId === 'telemetry' && STATE.activeNode) {
      loadTelemetryPanel(STATE.activeNode);
    }
    if (tabId === 'entity' && STATE.activeNodeData) {
      updateRightEntityPanel(STATE.activeNodeData);
    }
    if (tabId === 'code' && STATE.activeFilePath) {
      loadCodeViewer(STATE.activeFilePath, STATE.activeNodeData?.language);
    }
  });
});

/* Drawer toggle buttons */
document.getElementById('btn-toggle-left').addEventListener('click', () => DrawerState.toggleLeft());
document.getElementById('btn-toggle-right').addEventListener('click', () => DrawerState.toggleRight());

/* Open right drawer from HUD "Inspect →" button */
document.getElementById('btn-open-right').addEventListener('click', () => {
  if (STATE.activeNodeData) {
    updateRightEntityPanel(STATE.activeNodeData);
    DrawerState.openRight('entity');
  }
});

/* Layer selector */
document.querySelectorAll('.layer-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const layer = btn.getAttribute('data-layer');
    if (layer === STATE.activeLayer) return;
    if (layer === 'L1') loadL1();
    else if (layer === 'L2') {
      if (STATE.activeFilePath) loadL2(STATE.activeFilePath);
      else console.warn('No active file for L2 view.');
    }
  });
});

/* Color mode selector */
document.querySelectorAll('.color-btn').forEach(btn => {
  btn.addEventListener('click', () => setColorMode(btn.dataset.mode));
});

/* Reset camera */
document.getElementById('btn-reset-layout').addEventListener('click', () => {
  if (STATE.renderer) STATE.renderer.resetCamera();
});

/* Reload/sync */
document.getElementById('btn-sync-graph').addEventListener('click', () => {
  if (STATE.spatialClient) { STATE.spatialClient.clearCache(); loadViewportChunk(); }
});

/* 2-hop blast toggle */
document.getElementById('toggle-2hop').addEventListener('change', (e) => {
  if (STATE.activeNode) applyBlastRadius(STATE.activeNode, e.target.checked);
});

/* Drill down to L2 */
document.getElementById('btn-drill-down').addEventListener('click', () => {
  if (STATE.activeFilePath) loadL2(STATE.activeFilePath);
});

/* Focus in L2 */
document.getElementById('btn-isolate-file').addEventListener('click', () => {
  if (STATE.activeFilePath) loadL2(STATE.activeFilePath);
});

/* Index selector */
document.getElementById('index-selector').addEventListener('change', (e) => {
  if (e.target.value) { STATE.currentIndexId = e.target.value; bootstrapApp(); }
});

/* File filter */
document.getElementById('file-filter').addEventListener('input', (e) => {
  const query = e.target.value.toLowerCase();
  document.querySelectorAll('.file-item').forEach(item => {
    const name = item.querySelector('span')?.textContent.toLowerCase() ?? '';
    item.classList.toggle('hidden', !name.includes(query));
  });
});

/* Global search */
let searchTimeout;
document.getElementById('global-search').addEventListener('input', (e) => {
  clearTimeout(searchTimeout);
  const query = e.target.value.trim();
  const container = document.getElementById('search-results');

  if (!query) {
    container.innerHTML = '<div class="empty-state">Type query to search symbol graph</div>';
    return;
  }

  searchTimeout = setTimeout(async () => {
    container.innerHTML = '<div class="empty-state">Searching...</div>';
    try {
      const response = await apiGet(`/api/v2/search?q=${encodeURIComponent(query)}`);
      if (response.ok && response.data?.results) {
        const results = response.data.results;
        container.innerHTML = '';
        if (!results.length) {
          container.innerHTML = '<div class="empty-state">No matching symbols found.</div>';
          return;
        }
        results.forEach(res => {
          const card = document.createElement('div');
          card.className = 'search-result-card';
          card.innerHTML = `
            <div class="result-header">
              <span class="result-name">${escapeHtml(res.name)}</span>
              <span class="result-type">${escapeHtml(res.type || 'symbol')}</span>
            </div>
            <div class="result-file">${escapeHtml(res.file || '')}</div>
          `;
          card.addEventListener('click', () => loadL3(res.id, res.name));
          container.appendChild(card);
        });
      }
    } catch (err) {
      container.innerHTML = `<div class="empty-state" style="color:var(--accent-red);">Search failed: ${escapeHtml(err.message)}</div>`;
    }
  }, 300);
});

/* Keyboard shortcuts */
document.addEventListener('keydown', (e) => {
  if (e.key === '[') DrawerState.toggleLeft();
  if (e.key === ']') DrawerState.toggleRight();
  if (e.key === 'Escape') { resetBlastRadius(); hideHud(); }
});

// ══════════════════════════════════════════════════════════════
// RUN INITIALIZATION
// ══════════════════════════════════════════════════════════════
bootstrapApp();
Router.init();
