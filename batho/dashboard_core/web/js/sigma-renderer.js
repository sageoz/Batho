/**
 * Sigma.js WebGL Renderer for Batho Dashboard
 * 
 * Replaces Cytoscape with a WebGL-first engine for 100k+ node performance.
 * Uses backend-computed coordinates and viewport-based data fetching.
 */

import Sigma from 'https://cdn.jsdelivr.net/npm/sigma@3.0.0/+esm';
import Graph from 'https://cdn.jsdelivr.net/npm/graphology@0.25.4/+esm';

// --- KIND COLORS (matching existing theme) ---
const KIND_COLORS = {
  FUNCTION: '#00d9ff',
  METHOD: '#0099ff',
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
  python: '#3572A5',
  javascript: '#f1e05a',
  typescript: '#3178c6',
  rust: '#dea584',
  go: '#00add8',
  cpp: '#f34b7d',
  c: '#555555',
  java: '#b07219',
  file: '#00d9ff',
  unknown: '#8e8a94',
};

/**
 * SigmaRenderer - WebGL graph renderer using sigma.js
 */
export class SigmaRenderer {
  constructor(containerId) {
    this.containerId = containerId;
    this.container = document.getElementById(containerId);
    this.graph = new Graph();
    this.sigma = null;
    this.activeNode = null;
    this.onNodeClick = null;
    this.onBackgroundClick = null;
  }

  /**
   * Initialize sigma instance with empty graph
   */
  init() {
    if (this.sigma) {
      this.sigma.kill();
      this.sigma = null;
    }

    // Create sigma instance
    this.sigma = new Sigma(this.graph, this.container, {
      renderLabels: true,
      labelSize: 10,
      labelFont: 'JetBrains Mono, Fira Code, monospace',
      labelColor: { color: '#e6e2ea' },
      labelWeight: 'normal',
      defaultNodeType: 'circle',
      defaultEdgeType: 'line',
      nodeReducer: this._nodeReducer.bind(this),
      edgeReducer: this._edgeReducer.bind(this),
      minCameraRatio: 0.1,
      maxCameraRatio: 10,
    });

    // Bind events
    this.sigma.on('clickNode', (e) => {
      this.activeNode = e.node;
      if (this.onNodeClick) {
        const nodeData = this.graph.getNodeAttributes(e.node);
        this.onNodeClick(e.node, nodeData);
      }
    });

    this.sigma.on('clickStage', () => {
      this.activeNode = null;
      if (this.onBackgroundClick) {
        this.onBackgroundClick();
      }
    });

    // Set dark background
    this.container.style.background = '#060608';

    return this;
  }

  /**
   * Load nodes and edges from backend data
   */
  loadData(nodes, edges) {
    // Clear existing
    this.graph.clear();

    // Add nodes
    for (const node of nodes) {
      const color = this._getNodeColor(node);
      const size = this._getNodeSize(node);
      
      this.graph.addNode(node.id, {
        label: node.label || node.name || node.id,
        x: node.x || Math.random() * 100,
        y: node.y || Math.random() * 100,
        size: size,
        color: color,
        ...node, // spread remaining metadata
      });
    }

    // Add edges
    for (const edge of edges) {
      if (this.graph.hasNode(edge.source) && this.graph.hasNode(edge.target)) {
        this.graph.addEdge(edge.source, edge.target, {
          size: edge.weight || 1,
          color: '#2a2a3a',
          ...edge,
        });
      }
    }

    // Refresh
    this.sigma.refresh();
    
    // Camera to fit
    this.sigma.camera.animate({ ratio: 1.2 }, { duration: 0 });

    return this;
  }

  /**
   * Update node positions from backend spatial data
   */
  updatePositions(nodes) {
    for (const node of nodes) {
      if (this.graph.hasNode(node.id)) {
        this.graph.setNodeAttribute(node.id, 'x', node.x);
        this.graph.setNodeAttribute(node.id, 'y', node.y);
      }
    }
    this.sigma.refresh();
  }

  /**
   * Apply blast radius highlighting
   */
  applyBlastRadius(nodeId, isTwoHop = false) {
    this.blastCenter = nodeId;
    this.blastTwoHop = isTwoHop;
    
    if (!nodeId) {
      this.blastCenter = null;
      this.blastTwoHop = false;
    }
    
    this.sigma.refresh();
  }

  /**
   * Reset blast radius
   */
  resetBlastRadius() {
    this.applyBlastRadius(null, false);
  }

  /**
   * Get current viewport bounds
   */
  getViewportBounds() {
    const rect = this.container.getBoundingClientRect();
    const camera = this.sigma.camera;
    const state = camera.getState();
    
    // Calculate visible bounds based on camera
    const width = rect.width * state.ratio;
    const height = rect.height * state.ratio;
    
    return {
      x: state.x,
      y: state.y,
      width: width,
      height: height,
      zoom: 1 / state.ratio,
    };
  }

  /**
   * Center camera on node
   */
  centerOnNode(nodeId) {
    if (this.graph.hasNode(nodeId)) {
      const node = this.graph.getNodeAttributes(nodeId);
      this.sigma.camera.animate(
        { x: node.x, y: node.y, ratio: 0.5 },
        { duration: 300 }
      );
    }
  }

  /**
   * Reset camera to fit all
   */
  resetCamera() {
    this.sigma.camera.animate({ x: 0, y: 0, ratio: 1.2 }, { duration: 300 });
  }

  /**
   * Destroy instance
   */
  destroy() {
    if (this.sigma) {
      this.sigma.kill();
      this.sigma = null;
    }
  }

  // --- INTERNAL HELPERS ---

  _getNodeColor(node) {
    const type = node.type || node.node_type || 'unknown';
    const lang = node.language || 'unknown';
    
    return KIND_COLORS[type] || KIND_COLORS[lang] || KIND_COLORS.unknown;
  }

  _getNodeSize(node) {
    if (node.size) return node.size;
    if (node.entity_count) return Math.min(node.entity_count / 5 + 5, 20);
    return 8;
  }

  _nodeReducer(node, data) {
    // Apply blast radius styling
    if (this.blastCenter) {
      const isCenter = node === this.blastCenter;
      const isNeighbor = this.graph.areNeighbors(node, this.blastCenter);
      
      let isHop2 = false;
      if (this.blastTwoHop && !isNeighbor && !isCenter) {
        // Check if 2-hop neighbor
        const neighbors = this.graph.neighbors(this.blastCenter);
        for (const n of neighbors) {
          if (this.graph.areNeighbors(node, n)) {
            isHop2 = true;
            break;
          }
        }
      }

      if (isCenter) {
        return { ...data, color: '#cfbcff', size: data.size * 1.5, zIndex: 10 };
      } else if (isNeighbor) {
        return { ...data, opacity: 1, zIndex: 5 };
      } else if (isHop2 && this.blastTwoHop) {
        return { ...data, opacity: 0.55, zIndex: 3 };
      } else {
        return { ...data, opacity: 0.1, zIndex: 0 };
      }
    }

    return data;
  }

  _edgeReducer(edge, data) {
    if (this.blastCenter) {
      const isConnected = this.graph.extremities(edge).some(
        n => n === this.blastCenter || this.graph.areNeighbors(n, this.blastCenter)
      );
      
      return { ...data, opacity: isConnected ? 0.8 : 0.05 };
    }

    return data;
  }
}

/**
 * Create renderer instance
 */
export function createSigmaRenderer(containerId) {
  return new SigmaRenderer(containerId).init();
}

export default SigmaRenderer;
