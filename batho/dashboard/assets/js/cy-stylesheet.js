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
        'text-outline-width': 0,
        'background-color': '#9e9e9e',
        'border-width': 1,
        'border-color': 'rgba(148, 142, 156, 0.2)',
        'width': 20,
        'height': 20,
        'shape': 'roundrectangle',
        'transition-property': 'border-width, border-color',
        'transition-duration': '0.15s',
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-width': 2,
        'border-color': '#7df9ff',
        'z-index': 999,
      },
    },
    {
      selector: 'node.hovered',
      style: {
        'border-width': 2,
        'border-color': '#7df9ff',
        'z-index': 999,
      },
    },
    {
      selector: 'node.focus-hidden',
      style: {
        'opacity': 0.08,
      },
    },
    {
      selector: 'node.focus-visible-node',
      style: {
        'border-width': 2,
        'border-color': '#7df9ff',
        'z-index': 998,
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
        'width': 'mapData(nodeCount, 1, 200, 32, 96)',
        'height': 'mapData(nodeCount, 1, 200, 22, 48)',
        'background-color': '#2a2330',
        'border-width': 1.5,
        'border-color': 'rgba(207, 188, 255, 0.55)',
        'label': 'data(shortName)',
        'font-size': 11,
        'min-zoomed-font-size': 7,
        'color': '#e6e0e9',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'ellipsis',
        'text-max-width': 88,
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
        'width': 28,
        'height': 28,
        'z-index': 1000,
      },
    },
  ];

  for (const [kind, color] of Object.entries(KIND_COLORS)) {
    stylesheet.push({
      selector: `node[kind = "${kind}"]`,
      style: {
        'background-color': color,
      },
    });
  }

  for (const [relationshipType, color] of Object.entries(EDGE_COLORS)) {
    if (relationshipType === 'default') continue;
    stylesheet.push({
      selector: `edge[relationshipType = "${relationshipType}"]`,
      style: {
        'line-color': color,
        'target-arrow-color': color,
      },
    });
  }

  return stylesheet;
}
