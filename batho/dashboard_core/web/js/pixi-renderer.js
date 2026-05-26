/**
 * pixi-renderer.js — Batho Nexus WebGL Infinite-Canvas Renderer
 *
 * Replaces sigma-renderer.js. Uses Pixi.js v8 with a built-in
 * NativeViewport for infinite-canvas pan/zoom (no pixi-viewport CDN dep).
 * Supports LOD, blast-radius, flash animations, and heatmap color modes.
 *
 * API surface mirrors SigmaRenderer for minimal app.js changes.
 */

/* ── Design token palette (mirrors theme.css) ──────────────────── */
const COLORS = {
  bgVoid:       0x0e0e18,
  cyan:         0x00d9ff,
  violet:       0x9d7cff,
  gold:         0xffab00,
  green:        0x00ff88,
  magenta:      0xff2d78,
  red:          0xff3333,
  edgeDefault:  0x2a2a3a,
  edgeBlast:    0x00d9ff,
  nodeDim:      0x252535,
};

/* ── Kind → color map ───────────────────────────────────────────── */
const KIND_COLORS = {
  FILE:       0x00d9ff,
  MODULE:     0x00d9ff,
  CLASS:      0x9d7cff,
  FUNCTION:   0x00ff88,
  METHOD:     0x4da8ff,
  VARIABLE:   0xffab00,
  CONSTANT:   0xffab00,
  IMPORT:     0xaa99cc,
  EXPORT:     0xaa99cc,
  INTERFACE:  0xff9d5c,
  TYPE:       0xff9d5c,
  DECORATOR:  0xff2d78,
  DEFAULT:    0x888899,
};

/* ── LOD tier thresholds ────────────────────────────────────────── */
const LOD = {
  DOTS:       0.5,   // zoom < 0.5  → dots only
  NORMAL:     2.0,   // zoom 0.5–2  → normal circles
  FULL:       5.0,   // zoom 2–5    → full nodes + labels
  SYMBOLS:    20.0,  // zoom > 5    → L2 diamond expansion
};

/* ── CAI heatmap gradient helper ────────────────────────────────── */
function caiColor(risk) {
  // risk: 0.0 = safe (cyan), 1.0 = amnesia (red)
  const r = Math.round(0x00 + risk * 0xff);
  const g = Math.round(0xd9 - risk * 0xd9);
  const b = Math.round(0xff - risk * 0x99);
  return (r << 16) | (g << 8) | b;
}

/* ── BIS heatmap gradient helper ────────────────────────────────── */
function bisColor(score) {
  // score: 0–100
  if (score >= 80) return COLORS.green;
  if (score >= 50) return COLORS.gold;
  return COLORS.red;
}

/* ══════════════════════════════════════════════════════════════════
   NativeViewport — built-in pan/zoom container (no external dep)
   ══════════════════════════════════════════════════════════════════ */
class NativeViewport {
  constructor(PIXI, app, { worldWidth = 8000, worldHeight = 8000 } = {}) {
    this._PIXI = PIXI;
    this._app  = app;
    this.worldWidth  = worldWidth;
    this.worldHeight = worldHeight;

    /* Root container added to stage */
    this._root = new PIXI.Container();
    this._root.eventMode = 'static';
    this._root.hitArea = app.screen;
    app.stage.addChild(this._root);

    /* Pan/zoom state */
    this._scale  = 1.0;
    this._ox     = 0;   // world-space origin x
    this._oy     = 0;
    this._minScale = 0.05;
    this._maxScale = 20;

    /* Event listeners */
    this._dragging   = false;
    this._lastPtr    = { x: 0, y: 0 };
    this._onMoved    = null;
    this._onZoomed   = null;
    this._eventHandlers = [];

    this._bindEvents();
  }

  /* ── Public pixi-viewport-compatible API ── */
  get scaled() { return this._scale; }
  get left()   { return this._ox; }
  get right()  { return this._ox + this._app.screen.width  / this._scale; }
  get top()    { return this._oy; }
  get bottom() { return this._oy + this._app.screen.height / this._scale; }
  get center() { return {
    x: this._ox + (this._app.screen.width  / 2) / this._scale,
    y: this._oy + (this._app.screen.height / 2) / this._scale,
  }; }
  get screenWidth()  { return this._app.screen.width; }
  get screenHeight() { return this._app.screen.height; }

  addChild(child)    { this._root.addChild(child); return this; }
  removeChild(child) { this._root.removeChild(child); return this; }

  on(event, fn) {
    this._eventHandlers.push({ event, fn });
    return this;
  }

  /* Fluent no-op chainable methods for API compat */
  drag()          { return this; }
  pinch()         { return this; }
  wheel()         { return this; }
  decelerate()    { return this; }
  clampZoom(opts) {
    if (opts.minScale != null) this._minScale = opts.minScale;
    if (opts.maxScale != null) this._maxScale = opts.maxScale;
    return this;
  }

  /* ── animate (for centerOnNode) ── */
  animate({ position, scale, time = 400 }) {
    if (!position) return;
    const screen = this._app.screen;
    const startOx = this._ox, startOy = this._oy, startScale = this._scale;
    const targetScale = scale ?? this._scale;
    const targetOx = position.x - (screen.width  / 2) / targetScale;
    const targetOy = position.y - (screen.height / 2) / targetScale;
    const start = performance.now();
    const tick = () => {
      const t = Math.min((performance.now() - start) / time, 1);
      const e = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; // ease in-out
      this._scale = startScale + (targetScale - startScale) * e;
      this._ox    = startOx    + (targetOx    - startOx)    * e;
      this._oy    = startOy    + (targetOy    - startOy)    * e;
      this._applyTransform();
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  /* ── moveCenter / setZoom ── */
  moveCenter(wx, wy) {
    /* Set ox/oy so that world point (wx,wy) appears at screen center.
       ox = world coord at screen left edge = wx - (screenW/2)/scale */
    this._ox = wx - (this._app.screen.width  / 2) / this._scale;
    this._oy = wy - (this._app.screen.height / 2) / this._scale;
    this._applyTransform();
  }

  setZoom(newScale) {
    /* Zoom toward screen center: keep the world point under screen center fixed */
    const screenCX = this._app.screen.width  / 2;
    const screenCY = this._app.screen.height / 2;
    /* World point currently at screen center */
    const worldCX = this._ox + screenCX / this._scale;
    const worldCY = this._oy + screenCY / this._scale;
    this._scale = Math.max(this._minScale, Math.min(this._maxScale, newScale));
    /* Re-center on same world point */
    this._ox = worldCX - screenCX / this._scale;
    this._oy = worldCY - screenCY / this._scale;
    this._applyTransform();
  }

  /* ── resize ── */
  resize(w, h) { /* screen size already updated by renderer */ }

  /* ── Internal ── */
  _applyTransform() {
    this._root.scale.set(this._scale);
    this._root.x = -this._ox * this._scale;
    this._root.y = -this._oy * this._scale;
    for (const { event, fn } of this._eventHandlers) {
      if (event === 'moved' || event === 'zoomed') fn();
    }
  }

  _bindEvents() {
    const canvas = this._app.canvas;
    const screen = this._app.screen;

    /* Pointer drag */
    const onPointerDown = (e) => {
      if (e.button !== 0) return;
      this._dragging = true;
      this._lastPtr  = { x: e.clientX, y: e.clientY };
    };
    const onPointerMove = (e) => {
      if (!this._dragging) return;
      const dx = (e.clientX - this._lastPtr.x) / this._scale;
      const dy = (e.clientY - this._lastPtr.y) / this._scale;
      this._lastPtr = { x: e.clientX, y: e.clientY };
      this._ox -= dx;
      this._oy -= dy;
      this._applyTransform();
    };
    const onPointerUp = () => { this._dragging = false; };

    /* Wheel zoom */
    const onWheel = (e) => {
      e.preventDefault();
      const rect   = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      /* World coords under cursor before zoom */
      const wx = this._ox + mouseX / this._scale;
      const wy = this._oy + mouseY / this._scale;
      const factor  = e.deltaY < 0 ? 1.1 : 0.9;
      this._scale   = Math.max(this._minScale, Math.min(this._maxScale, this._scale * factor));
      /* Adjust origin so world point stays under cursor */
      this._ox = wx - mouseX / this._scale;
      this._oy = wy - mouseY / this._scale;
      this._applyTransform();
      for (const { event, fn } of this._eventHandlers) {
        if (event === 'zoomed') fn();
      }
    };

    canvas.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup',   onPointerUp);
    canvas.addEventListener('wheel',       onWheel, { passive: false });

    this._cleanup = () => {
      canvas.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup',   onPointerUp);
      canvas.removeEventListener('wheel',       onWheel);
    };
  }

  destroy() {
    if (this._cleanup) this._cleanup();
    this._app.stage.removeChild(this._root);
    this._root.destroy({ children: true });
  }
}

/* ══════════════════════════════════════════════════════════════════
   PixiRenderer
   ══════════════════════════════════════════════════════════════════ */
export class PixiRenderer {
  constructor(containerId) {
    this.containerId = containerId;
    this.app = null;
    this.viewport = null;

    this._nodes = new Map();       // nodeId → { gfx, label, data }
    this._edges = new Map();       // edgeKey → { gfx, data }
    this._culledSet = new Map();   // nodeId → insertion-order LRU

    this._blastCenter = null;
    this._blastIds = { hop1: new Set(), hop2: new Set() };

    this._colorMode = 'kind';      // 'kind' | 'cai' | 'bis'
    this._caiData = {};            // nodeId → { risk: 0–1 }
    this._bisData = {};            // nodeId → { score: 0–100 }

    this._currentLOD = 'NORMAL';
    this._flashTickers = new Map(); // nodeId → Ticker cleanup fn

    this._onNodeClick = null;
    this._onViewportMoved = null;
    this._viewportMoveDebounce = null;

    this._edgeContainer = null;
    this._nodeContainer = null;
    this._labelContainer = null;
  }

  /* ── init ─────────────────────────────────────────────────────── */
  async init() {
    const container = document.getElementById(this.containerId);
    if (!container) throw new Error(`Container #${this.containerId} not found`);

    const PIXI = window.PIXI;
    if (!PIXI) throw new Error('PIXI not found on window — check CDN script load order');

    this.app = new PIXI.Application();
    await this.app.init({
      width:           container.clientWidth  || window.innerWidth,
      height:          container.clientHeight || window.innerHeight,
      backgroundColor: COLORS.bgVoid,
      antialias:       true,
      resolution:      window.devicePixelRatio || 1,
      autoDensity:     true,
      powerPreference: 'high-performance',
    });

    /* Canvas fills container */
    this.app.canvas.style.width  = '100%';
    this.app.canvas.style.height = '100%';
    container.appendChild(this.app.canvas);

    /* Radial gradient background overlay */
    this._drawBackground();

    /* Built-in NativeViewport — no external CDN dependency */
    this.viewport = new NativeViewport(PIXI, this.app, {
      worldWidth:  8000,
      worldHeight: 8000,
    });
    this.viewport.clampZoom({ minScale: 0.05, maxScale: 20 });

    /* Layered containers — draw order: edges → nodes → labels */
    this._edgeContainer  = new PIXI.Container();
    this._nodeContainer  = new PIXI.Container();
    this._labelContainer = new PIXI.Container();

    this._edgeContainer.eventMode  = 'none';
    this._nodeContainer.eventMode  = 'auto';
    this._labelContainer.eventMode = 'none';

    this.viewport.addChild(this._edgeContainer);
    this.viewport.addChild(this._nodeContainer);
    this.viewport.addChild(this._labelContainer);

    /* Viewport move → debounced callback for viewport culling */
    this.viewport.on('moved',  () => this._onViewportChange());
    this.viewport.on('zoomed', () => this._onViewportChange());

    /* LOD updates on zoom */
    this.viewport.on('zoomed', () => this._applyLOD(this.viewport.scaled));

    /* Resize observer */
    new ResizeObserver(() => this._handleResize()).observe(container);

    return this;
  }

  /* ── _drawBackground ──────────────────────────────────────────── */
  _drawBackground() {
    const PIXI = window.PIXI;
    const bg = new PIXI.Graphics();
    const w = this.app.screen.width;
    const h = this.app.screen.height;

    bg.rect(0, 0, w, h).fill({ color: COLORS.bgVoid });

    /* Subtle radial center brightening */
    const cx = w / 2, cy = h / 2;
    const r = Math.max(w, h) * 0.6;
    for (let i = 10; i > 0; i--) {
      const alpha = 0.015 * (1 - i / 10);
      bg.circle(cx, cy, r * (i / 10)).fill({ color: 0x1a1a2e, alpha });
    }

    this.app.stage.addChild(bg);
    this._bgGfx = bg;
  }

  /* ── loadData ─────────────────────────────────────────────────── */
  loadData(data) {
    const { nodes = [], edges = [] } = data;
    if (!nodes.length) return;

    /* ── Normalise coordinates to Pixi canvas space ─────────────── */
    /* igraph returns world coords in a small float range (~-20 to +20).
       We scale them up to fill ~80% of the 8000×8000 world. */
    const WORLD = 8000;
    const MARGIN = 0.1; // 10% padding on each side

    /* Assign fallback circular positions to any nodes missing x/y */
    const missingCoords = nodes.filter(n => n.x == null || n.y == null);
    if (missingCoords.length > 0) {
      const r = missingCoords.length * 8;
      missingCoords.forEach((n, i) => {
        const angle = (i / missingCoords.length) * Math.PI * 2;
        n.x = Math.cos(angle) * r;
        n.y = Math.sin(angle) * r;
      });
    }

    let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
    for (const n of nodes) {
      if (n.x != null) { xMin = Math.min(xMin, n.x); xMax = Math.max(xMax, n.x); }
      if (n.y != null) { yMin = Math.min(yMin, n.y); yMax = Math.max(yMax, n.y); }
    }

    const rangeX = xMax - xMin || 1;
    const rangeY = yMax - yMin || 1;
    const usable = WORLD * (1 - 2 * MARGIN);
    const scaleX = usable / rangeX;
    const scaleY = usable / rangeY;
    const scale  = Math.min(scaleX, scaleY); // uniform scale
    const offX   = WORLD * MARGIN - xMin * scale + (usable - rangeX * scale) / 2;
    const offY   = WORLD * MARGIN - yMin * scale + (usable - rangeY * scale) / 2;

    const scaledNodes = nodes.map(n => ({
      ...n,
      x: (n.x ?? 0) * scale + offX,
      y: (n.y ?? 0) * scale + offY,
    }));

    /* Fast-path Float32Array for large graphs */
    let posArray = null;
    if (scaledNodes.length > 2000) {
      posArray = new Float32Array(scaledNodes.length * 2);
      for (let i = 0; i < scaledNodes.length; i++) {
        posArray[i * 2]     = scaledNodes[i].x;
        posArray[i * 2 + 1] = scaledNodes[i].y;
      }
    }

    /* Clear existing */
    this._edgeContainer.removeChildren();
    this._nodeContainer.removeChildren();
    this._labelContainer.removeChildren();
    this._nodes.clear();
    this._edges.clear();
    this._culledSet.clear();

    /* Draw edges first */
    for (const edge of edges) {
      this._addEdge(edge, scaledNodes);
    }

    /* Draw nodes */
    for (let i = 0; i < scaledNodes.length; i++) {
      const node = scaledNodes[i];
      const x = posArray ? posArray[i * 2]     : node.x;
      const y = posArray ? posArray[i * 2 + 1] : node.y;
      this._addNode({ ...node, x, y });
    }

    /* Center viewport on graph centroid at a comfortable initial zoom.
       moveCenter AFTER setZoom so ox/oy reflect the final scale. */
    const cx = offX + (rangeX * scale) / 2;
    const cy = offY + (rangeY * scale) / 2;
    const screenW = this.app.screen.width  || window.innerWidth;
    const screenH = this.app.screen.height || window.innerHeight;
    const graphPixW = rangeX * scale;
    const graphPixH = rangeY * scale;
    const fitZoom = Math.min(screenW / (graphPixW * 1.2), screenH / (graphPixH * 1.2));
    const clampedZoom = Math.max(0.05, Math.min(fitZoom, 2));
    console.log('[PixiRenderer] loadData: nodes=', scaledNodes.length,
      'world range=', rangeX.toFixed(1), 'x', rangeY.toFixed(1),
      'scale=', scale.toFixed(1), 'fitZoom=', clampedZoom.toFixed(3),
      'center=', cx.toFixed(1), cy.toFixed(1));
    this.viewport.setZoom(clampedZoom);
    this.viewport.moveCenter(cx, cy);

    this._applyLOD(this.viewport.scaled);
  }

  /* ── _addNode ─────────────────────────────────────────────────── */
  _addNode(node) {
    const PIXI = window.PIXI;
    const color = this._nodeColor(node);
    const size  = Math.max(4, Math.min(28, (node.size ?? node.entity_count ?? 6)));

    const gfx = new PIXI.Graphics();
    this._drawNodeShape(gfx, node, color, size);
    gfx.x = node.x;
    gfx.y = node.y;
    gfx.eventMode = 'static';
    gfx.cursor = 'pointer';
    gfx.on('pointerdown', (e) => {
      e.stopPropagation();
      if (this._onNodeClick) this._onNodeClick(node);
    });

    this._nodeContainer.addChild(gfx);

    /* Label */
    const label = new PIXI.Text({
      text: node.label || node.id || '',
      style: {
        fontFamily:  'JetBrains Mono, monospace',
        fontSize:    10,
        fill:        0xd0d0e8,
        align:       'center',
        resolution:  window.devicePixelRatio || 2,
      },
    });
    label.anchor.set(0.5, 1.3);
    label.x = node.x;
    label.y = node.y - size;
    label.visible = false;
    this._labelContainer.addChild(label);

    this._nodes.set(String(node.id), { gfx, label, data: node, color, size });
  }

  /* ── _drawNodeShape ───────────────────────────────────────────── */
  _drawNodeShape(gfx, node, color, size, glowAlpha = 0) {
    gfx.clear();
    const isL2 = node.type && node.type !== 'FILE' && node.type !== 'MODULE';
    const glowColor = glowAlpha > 0 ? color : null;

    if (glowAlpha > 0) {
      gfx.circle(0, 0, size + 8).fill({ color, alpha: glowAlpha * 0.35 });
      gfx.circle(0, 0, size + 4).fill({ color, alpha: glowAlpha * 0.25 });
    }

    if (isL2) {
      /* Diamond for symbol nodes */
      const s = size;
      gfx.poly([0, -s, s, 0, 0, s, -s, 0]).fill({ color });
    } else {
      /* Circle for file/module nodes */
      gfx.circle(0, 0, size).fill({ color });
      /* Outer ring */
      gfx.circle(0, 0, size + 2).stroke({ color, width: 1, alpha: 0.4 });
    }
  }

  /* ── _addEdge ─────────────────────────────────────────────────── */
  _addEdge(edge, nodes) {
    const PIXI = window.PIXI;
    const src = nodes.find(n => String(n.id) === String(edge.source || edge.s));
    const tgt = nodes.find(n => String(n.id) === String(edge.target || edge.t));
    if (!src || !tgt) return;

    const gfx = new PIXI.Graphics();
    gfx.moveTo(src.x, src.y)
       .lineTo(tgt.x, tgt.y)
       .stroke({ color: COLORS.edgeDefault, width: 1, alpha: 0.35 });

    this._edgeContainer.addChild(gfx);
    const key = `${edge.source || edge.s}→${edge.target || edge.t}`;
    this._edges.set(key, { gfx, data: { ...edge, srcX: src.x, srcY: src.y, tgtX: tgt.x, tgtY: tgt.y } });
  }

  /* ── _nodeColor ───────────────────────────────────────────────── */
  _nodeColor(node) {
    if (this._colorMode === 'cai') {
      const d = this._caiData[String(node.id)];
      return d ? caiColor(d.risk) : COLORS.nodeDim;
    }
    if (this._colorMode === 'bis') {
      const d = this._bisData[String(node.id)];
      return d ? bisColor(d.score) : COLORS.nodeDim;
    }
    const kind = (node.type || node.node_type || 'DEFAULT').toUpperCase();
    return KIND_COLORS[kind] ?? KIND_COLORS.DEFAULT;
  }

  /* ── setColorMode ─────────────────────────────────────────────── */
  setColorMode(mode) {
    if (this._colorMode === mode) return;
    this._colorMode = mode;
    this._refreshNodeColors();
  }

  /* ── setCaiData / setBisData ──────────────────────────────────── */
  setCaiData(data) {
    this._caiData = data;
    if (this._colorMode === 'cai') this._refreshNodeColors();
  }

  setBisData(data) {
    this._bisData = data;
    if (this._colorMode === 'bis') this._refreshNodeColors();
  }

  /* ── _refreshNodeColors ───────────────────────────────────────── */
  _refreshNodeColors() {
    for (const [id, entry] of this._nodes) {
      const color = this._nodeColor(entry.data);
      entry.color = color;
      this._drawNodeShape(entry.gfx, entry.data, color, entry.size, 0);
    }
  }

  /* ── updatePositions ──────────────────────────────────────────── */
  updatePositions(positions) {
    for (const [id, pos] of Object.entries(positions)) {
      const entry = this._nodes.get(String(id));
      if (!entry) continue;
      entry.gfx.x = pos.x;
      entry.gfx.y = pos.y;
      if (entry.label) { entry.label.x = pos.x; entry.label.y = pos.y - entry.size; }
    }
  }

  /* ── applyBlastRadius ─────────────────────────────────────────── */
  applyBlastRadius(centerNodeId, hop1Ids, hop2Ids) {
    this._blastCenter = String(centerNodeId);
    this._blastIds.hop1 = new Set(hop1Ids.map(String));
    this._blastIds.hop2 = new Set(hop2Ids.map(String));

    for (const [id, entry] of this._nodes) {
      const { gfx, data, size } = entry;
      if (id === this._blastCenter) {
        this._drawNodeShape(gfx, data, COLORS.violet, size, 1.0);
        gfx.alpha = 1.0;
      } else if (this._blastIds.hop1.has(id)) {
        this._drawNodeShape(gfx, data, COLORS.cyan, size, 0.6);
        gfx.alpha = 1.0;
      } else if (this._blastIds.hop2.has(id)) {
        this._drawNodeShape(gfx, data, COLORS.gold, size, 0.3);
        gfx.alpha = 0.7;
      } else {
        this._drawNodeShape(gfx, data, COLORS.nodeDim, size, 0);
        gfx.alpha = 0.08;
      }
    }

    /* Edges: highlight blast edges */
    for (const [key, entry] of this._edges) {
      const [src, tgt] = key.split('→');
      const inBlast = (
        (src === this._blastCenter || this._blastIds.hop1.has(src)) &&
        (tgt === this._blastCenter || this._blastIds.hop1.has(tgt))
      );
      const { gfx: egfx, data: ed } = entry;
      egfx.clear();
      if (inBlast) {
        egfx.moveTo(ed.srcX, ed.srcY).lineTo(ed.tgtX, ed.tgtY)
            .stroke({ color: COLORS.cyan, width: 1.5, alpha: 0.8 });
      } else {
        egfx.moveTo(ed.srcX, ed.srcY).lineTo(ed.tgtX, ed.tgtY)
            .stroke({ color: COLORS.edgeDefault, width: 1, alpha: 0.1 });
      }
    }
  }

  /* ── clearBlastRadius ─────────────────────────────────────────── */
  clearBlastRadius() {
    this._blastCenter = null;
    this._blastIds.hop1.clear();
    this._blastIds.hop2.clear();

    for (const [id, entry] of this._nodes) {
      const { gfx, data, size, color } = entry;
      gfx.alpha = 1.0;
      this._drawNodeShape(gfx, data, color, size, 0);
    }
    for (const [key, entry] of this._edges) {
      const { gfx: egfx, data: ed } = entry;
      egfx.clear();
      egfx.moveTo(ed.srcX, ed.srcY).lineTo(ed.tgtX, ed.tgtY)
          .stroke({ color: COLORS.edgeDefault, width: 1, alpha: 0.35 });
    }
  }

  /* ── flashNodeGold / flashNodeCyan / flashNodeRed ─────────────── */
  flashNode(nodeId, flashColor, decayMs = 2000) {
    const PIXI = window.PIXI;
    const entry = this._nodes.get(String(nodeId));
    if (!entry) return;

    /* Cancel any existing flash on this node */
    if (this._flashTickers.has(nodeId)) {
      this._flashTickers.get(nodeId)();
      this._flashTickers.delete(nodeId);
    }

    const { gfx, data, size } = entry;
    const startMs = performance.now();

    const ticker = this.app.ticker.add(() => {
      const elapsed = performance.now() - startMs;
      const t = Math.max(0, 1 - elapsed / decayMs);
      if (t <= 0) {
        this._drawNodeShape(gfx, data, entry.color, size, 0);
        this.app.ticker.remove(ticker);
        this._flashTickers.delete(nodeId);
        return;
      }
      this._drawNodeShape(gfx, data, flashColor, size, t);
    });

    this._flashTickers.set(nodeId, () => {
      this.app.ticker.remove(ticker);
    });
  }

  flashNodeGold(nodeId, decayMs = 2000)  { this.flashNode(nodeId, COLORS.gold,  decayMs); }
  flashNodeCyan(nodeId, decayMs = 1500)  { this.flashNode(nodeId, COLORS.cyan,  decayMs); }
  flashNodeRed(nodeId,  decayMs = 400)   { this.flashNode(nodeId, COLORS.red,   decayMs); }

  /* ── _applyLOD ────────────────────────────────────────────────── */
  _applyLOD(zoom) {
    let tier;
    if (zoom < LOD.DOTS)    tier = 'DOTS';
    else if (zoom < LOD.NORMAL) tier = 'NORMAL';
    else if (zoom < LOD.FULL)   tier = 'FULL';
    else tier = 'SYMBOLS';

    if (tier === this._currentLOD) return;
    this._currentLOD = tier;

    const showLabels = tier === 'FULL' || tier === 'SYMBOLS';
    const showEdges  = tier !== 'DOTS';

    for (const [id, entry] of this._nodes) {
      entry.label.visible = showLabels;

      if (tier === 'DOTS') {
        /* Override with tiny dot */
        entry.gfx.clear();
        entry.gfx.circle(0, 0, 2).fill({ color: entry.color, alpha: 0.7 });
      } else {
        this._drawNodeShape(entry.gfx, entry.data, entry.color, entry.size,
          this._blastCenter === id ? 1.0 :
          this._blastIds.hop1.has(id) ? 0.6 :
          this._blastIds.hop2.has(id) ? 0.3 : 0
        );
      }
    }

    this._edgeContainer.visible = showEdges;
  }

  /* ── Viewport culling ─────────────────────────────────────────── */
  _onViewportChange() {
    clearTimeout(this._viewportMoveDebounce);
    this._viewportMoveDebounce = setTimeout(() => {
      this._cullNodes();
      if (this._onViewportMoved) {
        const b = this.getViewportBounds();
        this._onViewportMoved(b);
      }
    }, 150);
  }

  _cullNodes() {
    const vp = this.viewport;
    const left   = vp.left;
    const right  = vp.right;
    const top    = vp.top;
    const bottom = vp.bottom;

    const MEMORY_CEILING = 50000;
    const EVICT_COUNT    = 10000;

    for (const [id, entry] of this._nodes) {
      const { x, y } = entry.gfx;
      const inView = x >= left && x <= right && y >= top && y <= bottom;

      if (!inView) {
        entry.gfx.visible = false;
        if (entry.label) entry.label.visible = false;
        if (!this._culledSet.has(id)) {
          this._culledSet.set(id, Date.now());
          /* Memory ceiling: evict oldest entries */
          if (this._culledSet.size > MEMORY_CEILING) {
            let evicted = 0;
            for (const k of this._culledSet.keys()) {
              this._culledSet.delete(k);
              if (++evicted >= EVICT_COUNT) break;
            }
          }
        }
      } else {
        entry.gfx.visible = true;
        if (entry.label) entry.label.visible = (this._currentLOD === 'FULL' || this._currentLOD === 'SYMBOLS');
        this._culledSet.delete(id);
      }
    }
  }

  /* ── getViewportBounds ────────────────────────────────────────── */
  getViewportBounds() {
    const vp = this.viewport;
    return {
      x:      vp.center.x,
      y:      vp.center.y,
      width:  vp.screenWidth  / vp.scaled,
      height: vp.screenHeight / vp.scaled,
      zoom:   vp.scaled,
    };
  }

  /* ── Camera controls ──────────────────────────────────────────── */
  resetCamera() {
    this.viewport.moveCenter(0, 0);
    this.viewport.setZoom(1.0);
  }

  centerOnNode(nodeId) {
    const entry = this._nodes.get(String(nodeId));
    if (!entry) return;
    this.viewport.animate({
      position: { x: entry.gfx.x, y: entry.gfx.y },
      scale:    2.5,
      time:     400,
      ease:     'easeInOutSine',
    });
  }

  /* ── Event bindings ───────────────────────────────────────────── */
  onNodeClick(fn) { this._onNodeClick = fn; }
  onViewportMoved(fn) { this._onViewportMoved = fn; }

  /* ── Resize ───────────────────────────────────────────────────── */
  _handleResize() {
    const container = document.getElementById(this.containerId);
    if (!container || !this.app) return;
    const w = container.clientWidth;
    const h = container.clientHeight;
    this.app.renderer.resize(w, h);
    this.viewport.resize(w, h);
    if (this._bgGfx) {
      this.app.stage.removeChild(this._bgGfx);
      this._bgGfx.destroy();
      this._drawBackground();
      this.app.stage.setChildIndex(this._bgGfx, 0);
    }
  }

  /* ── destroy ──────────────────────────────────────────────────── */
  destroy() {
    for (const cancel of this._flashTickers.values()) cancel();
    this._flashTickers.clear();
    if (this.viewport && this.viewport._cleanup) {
      this.viewport._cleanup();
      this.viewport = null;
    }
    if (this.app) {
      this.app.destroy(true, { children: true });
      this.app = null;
    }
  }
}
