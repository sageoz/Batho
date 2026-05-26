/**
 * Spatial Client - Viewport-driven geometry fetching
 * 
 * Manages viewport state, fetches geometry chunks from backend,
 * and coordinates with the sigma renderer.
 */

/* msgpack decode — resolved from UMD global loaded by index.html */
const _msgpackDecode = () => (
  (window.MessagePack && window.MessagePack.decode) ||
  (window.msgpack    && window.msgpack.decode)
);

/**
 * SpatialClient - Fetches and caches viewport geometry
 */
export class SpatialClient {
  constructor(apiBase = '') {
    this.apiBase = apiBase;
    this.layoutComputed = false;
    this.bounds = null;
    this.cache = new Map(); // chunk_id -> geometry
    this.pendingRequests = new Set();
    this.onGeometryUpdate = null;
    this.onLayoutReady = null;
  }

  /**
   * Trigger layout computation on backend
   */
  async computeLayout(layer = 'L1', algorithm = 'fruchterman_reingold') {
    try {
      const response = await fetch(`${this.apiBase}/api/v2/spatial/layout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layer, algorithm, seed: 42 }),
      });

      const result = await response.json();
      
      if (result.ok) {
        this.layoutComputed = true;
        this.bounds = result.bounds;
        
        if (this.onLayoutReady) {
          this.onLayoutReady(result);
        }
        
        return result;
      } else {
        throw new Error(result.error || 'Layout computation failed');
      }
    } catch (error) {
      console.error('Spatial layout error:', error);
      throw error;
    }
  }

  /**
   * Fetch geometry for viewport (JSON format)
   */
  async fetchViewport(x, y, width, height, zoom = 1.0, layer = 'L1') {
    const params = new URLSearchParams({
      x: x.toString(),
      y: y.toString(),
      width: width.toString(),
      height: height.toString(),
      zoom: zoom.toString(),
      layer,
    });

    try {
      const response = await fetch(`${this.apiBase}/api/v2/spatial/viewport?${params}`);
      const result = await response.json();

      if (result.ok) {
        const nodes = (result.nodes || []).map(n => ({
          ...n,
          ...(n.metadata || {}),
          label: n.label || (n.metadata && (n.metadata.file || n.metadata.name)) || n.id,
        }));
        return {
          nodes,
          edges: result.edges || [],
          bounds: result.bounds,
          nodeCount: result.node_count,
          edgeCount: result.edge_count,
        };
      } else {
        throw new Error(result.error || 'Viewport fetch failed');
      }
    } catch (error) {
      console.error('Viewport fetch error:', error);
      throw error;
    }
  }

  /**
   * Fetch geometry for viewport (binary msgpack format)
   */
  async fetchViewportBinary(x, y, width, height, zoom = 1.0) {
    const params = new URLSearchParams({
      x: x.toString(),
      y: y.toString(),
      width: width.toString(),
      height: height.toString(),
      zoom: zoom.toString(),
    });

    try {
      const response = await fetch(`${this.apiBase}/api/v2/spatial/viewport.bin?${params}`);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const buffer = await response.arrayBuffer();
      const decodeFn = _msgpackDecode();
      if (!decodeFn) throw new Error('msgpack decode not available');
      const decoded = decodeFn(new Uint8Array(buffer));

      if (!decoded.ok) {
        throw new Error(decoded.error || 'Binary decode failed');
      }

      // Transform compact binary format to full node/edge objects
      const nodes = (decoded.n || []).map(n => ({
        id: n.i,
        x: n.x,
        y: n.y,
        size: n.s,
        type: n.t,
      }));

      const edges = (decoded.e || []).map(e => ({
        source: e.s,
        target: e.t,
        weight: e.w,
      }));

      return {
        nodes,
        edges,
        bounds: decoded.b,
        zoom: decoded.z,
        nodeCount: decoded.c,
      };
    } catch (error) {
      console.error('Binary viewport fetch error:', error);
      // Fallback to JSON
      return this.fetchViewport(x, y, width, height, zoom);
    }
  }

  /**
   * Get quadtree metadata
   */
  async getQuadtreeMetadata() {
    try {
      const response = await fetch(`${this.apiBase}/api/v2/spatial/quadtree`);
      return await response.json();
    } catch (error) {
      console.error('Quadtree metadata error:', error);
      return { ok: false, error: error.message };
    }
  }

  /**
   * Get position for specific node
   */
  async getNodePosition(nodeId) {
    try {
      const params = new URLSearchParams({ node_id: nodeId });
      const response = await fetch(`${this.apiBase}/api/v2/spatial/node-position?${params}`);
      const result = await response.json();
      
      if (result.ok) {
        return { x: result.x, y: result.y };
      }
      return null;
    } catch (error) {
      console.error('Node position error:', error);
      return null;
    }
  }

  /**
   * Viewport-aware chunk loading with debouncing
   */
  loadViewportChunk(x, y, width, height, zoom, layer = 'L1', useBinary = true) {
    // Create chunk key
    const chunkKey = this._getChunkKey(x, y, width, height, zoom, layer);
    
    // Check cache
    if (this.cache.has(chunkKey)) {
      return Promise.resolve(this.cache.get(chunkKey));
    }

    // Check pending
    if (this.pendingRequests.has(chunkKey)) {
      return new Promise((resolve) => {
        const checkInterval = setInterval(() => {
          if (this.cache.has(chunkKey)) {
            clearInterval(checkInterval);
            resolve(this.cache.get(chunkKey));
          }
        }, 50);
      });
    }

    // Mark as pending
    this.pendingRequests.add(chunkKey);

    // Fetch
    const fetcher = useBinary ? this.fetchViewportBinary.bind(this) : this.fetchViewport.bind(this);
    
    return fetcher(x, y, width, height, zoom, layer)
      .then(data => {
        // Cache result
        this.cache.set(chunkKey, data);
        this.pendingRequests.delete(chunkKey);
        
        // Notify update
        if (this.onGeometryUpdate) {
          this.onGeometryUpdate(data);
        }
        
        return data;
      })
      .catch(error => {
        this.pendingRequests.delete(chunkKey);
        throw error;
      });
  }

  /**
   * Clear cache
   */
  clearCache() {
    this.cache.clear();
    this.pendingRequests.clear();
  }

  // --- INTERNAL HELPERS ---

  _getChunkKey(x, y, width, height, zoom, layer) {
    // Round to reduce unique keys (spatial hashing)
    const precision = zoom > 1 ? 10 : 100;
    const rx = Math.round(x * precision) / precision;
    const ry = Math.round(y * precision) / precision;
    const rw = Math.round(width * precision) / precision;
    const rh = Math.round(height * precision) / precision;
    const rz = Math.round(zoom * 10) / 10;
    
    return `${layer}:${rx},${ry}:${rw}x${rh}:${rz}`;
  }
}

/**
 * ViewportTracker - Tracks viewport changes and triggers fetches
 */
export class ViewportTracker {
  constructor(renderer, spatialClient, options = {}) {
    this.renderer = renderer;
    this.client = spatialClient;
    this.debounceMs = options.debounceMs || 150;
    this.layer = options.layer || 'L1';
    this.useBinary = options.useBinary !== false;
    
    this.debounceTimer = null;
    this.lastBounds = null;
    
    // Bind to sigma camera events
    this._bindEvents();
  }

  _bindEvents() {
    if (!this.renderer.sigma) return;

    // Track camera movement
    this.renderer.sigma.on('afterRender', () => {
      this._scheduleUpdate();
    });

    // Also track zoom
    this.renderer.sigma.on('wheel', () => {
      this._scheduleUpdate();
    });
  }

  _scheduleUpdate() {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }

    this.debounceTimer = setTimeout(() => {
      this._updateViewport();
    }, this.debounceMs);
  }

  async _updateViewport() {
    const bounds = this.renderer.getViewportBounds();
    
    // Skip if no significant change
    if (this.lastBounds && this._boundsSimilar(bounds, this.lastBounds)) {
      return;
    }
    
    this.lastBounds = bounds;

    try {
      const data = await this.client.loadViewportChunk(
        bounds.x,
        bounds.y,
        bounds.width,
        bounds.height,
        bounds.zoom,
        this.layer,
        this.useBinary
      );

      // Merge new data with existing graph
      this._mergeGeometry(data);
    } catch (error) {
      console.warn('Viewport update failed:', error);
    }
  }

  _mergeGeometry(data) {
    if (!data.nodes || data.nodes.length === 0) return;

    // Add/update nodes in renderer
    for (const node of data.nodes) {
      if (!this.renderer.graph.hasNode(node.id)) {
        this.renderer.graph.addNode(node.id, {
          label: node.label || node.id,
          x: node.x,
          y: node.y,
          size: node.size || 8,
          color: this._getNodeColor(node),
          ...node,
        });
      } else {
        // Update position if changed
        const existing = this.renderer.graph.getNodeAttributes(node.id);
        if (existing.x !== node.x || existing.y !== node.y) {
          this.renderer.graph.setNodeAttribute(node.id, 'x', node.x);
          this.renderer.graph.setNodeAttribute(node.id, 'y', node.y);
        }
      }
    }

    // Add edges
    for (const edge of data.edges || []) {
      const edgeId = `${edge.source}->${edge.target}`;
      if (!this.renderer.graph.hasEdge(edgeId) && 
          this.renderer.graph.hasNode(edge.source) && 
          this.renderer.graph.hasNode(edge.target)) {
        this.renderer.graph.addEdge(edgeId, edge.source, edge.target, {
          size: edge.weight || 1,
          color: '#2a2a3a',
        });
      }
    }

    // Refresh
    this.renderer.sigma.refresh();
  }

  _boundsSimilar(a, b, threshold = 0.1) {
    const dx = Math.abs(a.x - b.x) / (a.width + 1);
    const dy = Math.abs(a.y - b.y) / (a.height + 1);
    const dz = Math.abs(a.zoom - b.zoom) / (a.zoom + 1);
    
    return dx < threshold && dy < threshold && dz < threshold;
  }

  _getNodeColor(node) {
    const KIND_COLORS = {
      FUNCTION: '#00d9ff', METHOD: '#0099ff', CLASS: '#cfbcff',
      STRUCT: '#b8a9e0', INTERFACE: '#a998d4', ENUM: '#c4b5e8',
      TRAIT: '#bfa6da', NAMESPACE: '#64b5f6', FIELD: '#4ac4cc',
      VARIABLE: '#9e9e9e', MODULE: '#b0bec5', DOCUMENT: '#78909c',
      python: '#3572A5', javascript: '#f1e05a', typescript: '#3178c6',
      rust: '#dea584', go: '#00add8', cpp: '#f34b7d', c: '#555555',
      java: '#b07219', file: '#00d9ff', unknown: '#8e8a94',
    };
    
    const type = node.type || node.node_type || 'unknown';
    const lang = node.language || 'unknown';
    
    return KIND_COLORS[type] || KIND_COLORS[lang] || KIND_COLORS.unknown;
  }

  clearCache() {
    this.cache.clear();
    this.pendingRequests.clear();
  }

  async getNodePosition(nodeId) {
    for (const chunk of this.cache.values()) {
      const nodes = chunk.nodes || [];
      const node = nodes.find(n => String(n.id) === String(nodeId));
      if (node && node.x != null) return { x: node.x, y: node.y };
    }
    return null;
  }
}

export default SpatialClient;
