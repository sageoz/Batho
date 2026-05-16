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

function nodeColor(kind) {
  return KIND_COLORS[kind] || '#9e9e9e';
}

function edgeColor(relationshipType) {
  return EDGE_COLORS[relationshipType] || EDGE_COLORS.default;
}

export function buildStylesheet() {
  return [
    {
      selector: 'node',
      style: {
        'label': 'data(shortName)',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': 10,
        'font-weight': 'normal',
        'color': '#e6e0e9',
        'text-outline-width': 0,
        'background-color': 'data(color)',
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
        'background-color': 'data(color)',
        'z-index': 999,
      },
    },
    {
      selector: 'node:active',
      style: {
        'overlay-opacity': 0.15,
        'overlay-color': '#7df9ff',
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
      selector: 'edge',
      style: {
        'width': 1,
        'line-color': 'data(edgeColor)',
        'target-arrow-color': 'data(edgeColor)',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.6,
        'curve-style': 'bezier',
        'opacity': 0.4,
        'transition-property': 'opacity, width, line-color',
        'transition-duration': '0.15s',
      },
    },
    {
      selector: 'edge:selected',
      style: {
        'width': 2,
        'opacity': 1,
        'line-color': '#7df9ff',
        'target-arrow-color': '#7df9ff',
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
        'z-index': 998,
      },
    },
  ];
}
