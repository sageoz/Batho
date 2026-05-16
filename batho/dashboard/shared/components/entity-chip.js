/**
 * Entity chip component - inline badge showing entity type, name, location.
 */

const TYPE_COLORS = {
  FUNCTION: 'cyan',
  METHOD: 'teal',
  CLASS: 'purple',
  DOCUMENT: 'neutral',
  ELEMENT: 'neutral',
  SECTION: 'neutral',
  SETTING: 'amber',
  FIELD: 'teal',
  ENTRY_POINT: 'green',
  STRUCT: 'purple',
  NAMESPACE: 'blue',
  INTERFACE: 'purple',
  ENUM: 'purple',
  TRAIT: 'purple',
};

const COLOR_CSS = {
  cyan: 'rgb(0 188 212 / 0.2)',
  teal: 'rgb(0 150 136 / 0.2)',
  purple: 'rgb(103 80 164 / 0.2)',
  green: 'rgb(67 160 71 / 0.2)',
  amber: 'rgb(255 160 0 / 0.2)',
  blue: 'rgb(33 150 243 / 0.2)',
  neutral: 'rgb(120 120 120 / 0.15)',
};

export function createEntityChip(props = {}) {
  const { type = '', name = '', location = '' } = props;
  const color = TYPE_COLORS[type] || 'neutral';
  const bg = COLOR_CSS[color] || COLOR_CSS.neutral;

  const chip = document.createElement('span');
  chip.className = 'entity-chip';
  chip.innerHTML = `
    <span class="entity-chip__type" style="background:${bg}">${escapeHtml(type)}</span>
    <span class="entity-chip__name">${escapeHtml(name)}</span>
    ${location ? `<span class="entity-chip__loc">${escapeHtml(location)}</span>` : ''}
  `;
  return chip;
}

export function entityChipHtml(type, name, location) {
  const color = TYPE_COLORS[type] || 'neutral';
  const bg = COLOR_CSS[color] || COLOR_CSS.neutral;
  const locHtml = location ? `<span class="entity-chip__loc">${escapeHtml(location)}</span>` : '';
  return `<span class="entity-chip"><span class="entity-chip__type" style="background:${bg}">${escapeHtml(type)}</span><span class="entity-chip__name">${escapeHtml(name)}</span>${locHtml}</span>`;
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

const entityChipStyles = `
  .entity-chip { display: inline-flex; align-items: center; gap: var(--space-tight); font-family: var(--font-mono); font-size: var(--type-node-code-size); }
  .entity-chip__type { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: var(--type-terminal-size); color: var(--on-surface); text-transform: uppercase; letter-spacing: 0.5px; }
  .entity-chip__name { color: var(--on-surface); font-weight: var(--type-node-code-weight); }
  .entity-chip__loc { color: var(--on-surface-variant); font-size: var(--type-terminal-size); }
`;

function injectStyles() {
  if (document.getElementById('entity-chip-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'entity-chip-styles';
  styleEl.textContent = entityChipStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
