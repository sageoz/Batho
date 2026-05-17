/**
 * Build a Cytoscape stylesheet array from design tokens.
 * Uses the batho dashboard CSS custom properties for consistent theming.
 */

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
  default: '#494551',
};

// Phase 3.1 — Shape encoding per node type.
const KIND_SHAPES = {
  FUNCTION: 'ellipse',
  METHOD: 'ellipse',
  CLASS: 'roundrectangle',
  STRUCT: 'roundrectangle',
  INTERFACE: 'diamond',
  ENUM: 'hexagon',
  TRAIT: 'diamond',
  NAMESPACE: 'tag',
  MODULE: 'tag',
  FIELD: 'ellipse',
  VARIABLE: 'ellipse',
  DOCUMENT: 'roundrectangle',
  SETTING: 'roundrectangle',
  ENTRY_POINT: 'ellipse',
  SECTION: 'roundrectangle',
  ELEMENT: 'roundrectangle',
};

// Phase 3.1 — Dashed border for interfaces/traits (abstract types).
const DASHED_BORDER_KINDS = new Set(['INTERFACE', 'TRAIT']);

// Phase 3.2 — Edge line styles per relationship type.
const EDGE_LINE_STYLES = {
  calls: { 'line-style': 'solid', 'target-arrow-shape': 'triangle' },
  imports: { 'line-style': 'dashed', 'target-arrow-shape': 'triangle' },
  extends: { 'line-style': 'solid', 'target-arrow-shape': 'triangle', 'width': 2.5 },
  implements: { 'line-style': 'dotted', 'target-arrow-shape': 'triangle' },
  references: { 'line-style': 'solid', 'target-arrow-shape': 'none' },
  contains: { 'line-style': 'solid', 'target-arrow-shape': 'triangle', 'width': 3 },
  defines: { 'line-style': 'solid', 'target-arrow-shape': 'none' },
  uses: { 'line-style': 'dashed', 'target-arrow-shape': 'none' },
};

export function buildStylesheet() {
  const stylesheet = [
    {
      selector: 'node',
      style: {
        'label': 'data(shortName)',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': 10,
        'min-zoomed-font-size': 8,
        'font-weight': 'normal',
        'color': '#e6e0e9',
        'text-outline-width': 2,
        'text-outline-color': 'rgba(14, 12, 18, 0.8)',
        'background-color': '#9e9e9e',
        'border-width': 1.5,
        'border-color': 'rgba(148, 142, 156, 0.3)',
        'width': 22,
        'height': 22,
        'shape': 'roundrectangle',
        'events': 'yes',
        'text-events': 'yes',
        'transition-property': 'border-width, border-color, background-color, width, height, opacity',
        'transition-duration': '0.25s',
        'transition-timing-function': 'ease-out',
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-width': 3,
        'border-color': '#cfbcff',
        'border-style': 'solid',
        'z-index': 999,
        'width': 26,
        'height': 26,
      },
    },
    {
      selector: 'node.hovered',
      style: {
        'border-width': 2.5,
        'border-color': '#7df9ff',
        'border-style': 'solid',
        'z-index': 999,
        'width': 24,
        'height': 24,
      },
    },
    {
      selector: 'node.focus-hidden',
      style: {
        'opacity': 0.06,
        'transition-property': 'opacity',
        'transition-duration': '0.35s',
        'transition-timing-function': 'ease-out',
      },
    },
    {
      selector: 'node.focus-visible-node',
      style: {
        'border-width': 2,
        'border-color': '#7df9ff',
        'border-style': 'solid',
        'opacity': 0.85,
        'z-index': 998,
      },
    },
    {
      selector: 'node.focus-pulse',
      style: {
        'border-width': 3,
        'border-color': '#7df9ff',
        'border-style': 'solid',
        'z-index': 1000,
        'width': 28,
        'height': 28,
      },
    },
    {
      selector: '.filtered-out',
      style: {
        'display': 'none',
      },
    },
    {
      selector: 'edge',
      style: {
        'width': 1,
        'line-color': EDGE_COLORS.default,
        'target-arrow-color': EDGE_COLORS.default,
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.6,
        'curve-style': 'straight',
        'opacity': 0.4,
        'events': 'yes',
        'transition-property': 'opacity, width, line-color',
        'transition-duration': '0.2s',
      },
    },
    {
      selector: 'edge:selected',
      style: {
        'width': 2,
        'opacity': 1,
        'line-color': '#7df9ff',
        'target-arrow-color': '#7df9ff',
        'curve-style': 'bezier',
        'z-index': 999,
      },
    },
    {
      selector: 'edge.hovered',
      style: {
        'width': 2,
        'opacity': 0.9,
        'line-color': '#7df9ff',
        'target-arrow-color': '#7df9ff',
        'curve-style': 'bezier',
        'z-index': 999,
      },
    },
    {
      selector: 'edge.focus-hidden',
      style: {
        'opacity': 0.04,
        'transition-property': 'opacity',
        'transition-duration': '0.3s',
      },
    },
    {
      selector: 'edge.focus-visible-edge',
      style: {
        'width': 2,
        'opacity': 0.9,
        'line-color': '#7df9ff',
        'target-arrow-color': '#7df9ff',
        'curve-style': 'bezier',
        'z-index': 998,
      },
    },
    // ---- L1 (inter-file) styling ----
    {
      selector: 'node.file-node',
      style: {
        'shape': 'round-rectangle',
        'width': 'mapData(nodeCount, 1, 200, 36, 100)',
        'height': 'mapData(nodeCount, 1, 200, 26, 52)',
        'background-color': '#2a2330',
        'border-width': 2,
        'border-color': 'rgba(207, 188, 255, 0.55)',
        'border-style': 'solid',
        'label': 'data(shortName)',
        'font-size': 11,
        'min-zoomed-font-size': 7,
        'color': '#e6e0e9',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'ellipsis',
        'text-max-width': 90,
        'text-outline-width': 2,
        'text-outline-color': 'rgba(14, 12, 18, 0.9)',
        'transition-property': 'border-width, border-color, background-color, width, height',
        'transition-duration': '0.25s',
      },
    },
    {
      selector: 'node.file-node.hovered',
      style: {
        'border-width': 3,
        'border-color': '#7df9ff',
        'background-color': '#3a3340',
      },
    },
    {
      selector: 'node.file-node:selected',
      style: {
        'border-width': 3,
        'border-color': '#cfbcff',
        'background-color': '#4a4350',
      },
    },
    {
      selector: 'edge.aggregated',
      style: {
        'width': 'mapData(weightLog, 0, 6, 1.2, 6)',
        'opacity': 0.55,
        'line-color': '#90a4ae',
        'target-arrow-color': '#90a4ae',
        'curve-style': 'bezier',
        'arrow-scale': 0.5,
      },
    },
    {
      selector: 'edge.aggregated.hovered',
      style: {
        'opacity': 1,
        'line-color': '#7df9ff',
        'target-arrow-color': '#7df9ff',
        'z-index': 999,
      },
    },
    // ---- L3 (neighborhood) center node highlight ----
    {
      selector: 'node.center-node',
      style: {
        'border-width': 3,
        'border-color': '#7df9ff',
        'border-style': 'solid',
        'width': 32,
        'height': 32,
        'z-index': 1000,
      },
    },
    {
      selector: 'node.center-node:selected',
      style: {
        'border-width': 4,
        'border-color': '#cfbcff',
      },
    },
    // Phase 3.4 — L3: 1-hop vs 2-hop neighbor opacity.
    {
      selector: 'node.l3-hop-2',
      style: {
        'opacity': 0.45,
      },
    },
    {
      selector: 'edge.l3-hop-2',
      style: {
        'opacity': 0.2,
      },
    },
    // ---- Phase 2.2 — Clustered compound nodes ----
    {
      selector: 'node.cluster-parent',
      style: {
        'shape': 'round-rectangle',
        'background-color': 'rgba(42, 35, 48, 0.75)',
        'background-opacity': 0.6,
        'border-width': 2,
        'border-color': 'rgba(207, 188, 255, 0.4)',
        'border-style': 'dashed',
        'label': 'data(label)',
        'font-size': 11,
        'font-weight': 600,
        'color': '#e6e0e9',
        'text-valign': 'top',
        'text-halign': 'center',
        'text-margin-y': 8,
        'width': 'mapData(memberCount, 1, 200, 85, 210)',
        'height': 'mapData(memberCount, 1, 200, 65, 160)',
      },
    },
    {
      selector: '$node > node',
      style: {
        'padding-top': '10px',
        'padding-left': '10px',
        'padding-bottom': '10px',
        'padding-right': '10px',
      },
    },
    // ---- Phase 2.2 — Clustered mode edge aggregation ----
    {
      selector: 'edge.cluster-edge',
      style: {
        'width': 'mapData(weight, 1, 50, 1.5, 8)',
        'opacity': 0.5,
        'line-color': '#90a4ae',
        'target-arrow-color': '#90a4ae',
        'curve-style': 'bezier',
      },
    },
  ];

  // Phase 3.1 — Per-kind shape + color.
  for (const [kind, color] of Object.entries(KIND_COLORS)) {
    const shape = KIND_SHAPES[kind] || 'roundrectangle';
    const isDashed = DASHED_BORDER_KINDS.has(kind);
    const style = {
      'background-color': color,
      'shape': shape,
    };
    if (isDashed) {
      style['border-style'] = 'dashed';
      style['border-width'] = 1.5;
      style['border-color'] = color;
    }
    stylesheet.push({
      selector: `node[kind = "${kind}"]`,
      style,
    });
  }

  // Phase 3.2 — Per-relationship edge styles.
  for (const [relationshipType, color] of Object.entries(EDGE_COLORS)) {
    if (relationshipType === 'default') continue;
    const edgeStyle = EDGE_LINE_STYLES[relationshipType] || {};
    stylesheet.push({
      selector: `edge[relationshipType = "${relationshipType}"]`,
      style: {
        'line-color': color,
        'target-arrow-color': color,
        ...edgeStyle,
      },
    });
  }

  // Phase 3.3 — Search highlight style.
  stylesheet.push({
    selector: 'node.search-match',
    style: {
      'border-width': 2,
      'border-color': '#e7c365',
      'z-index': 997,
    },
  });
  stylesheet.push({
    selector: 'node.search-dimmed',
    style: {
      'opacity': 0.15,
    },
  });

  return stylesheet;
}
