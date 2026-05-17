/**
 * Toggleable filter chip with count badge.
 *
 * Usage:
 *   const chip = createChipFilter({ label: 'fn', count: 42, active: true, onChange: (active) => {} });
 *   container.appendChild(chip);
 */

export function createChipFilter({ label = '', count = 0, active = true, onChange = null } = {}) {
  const chip = document.createElement('button');
  chip.className = `chip-filter${active ? ' chip-filter--active' : ''}`;
  chip.type = 'button';
  chip.setAttribute('aria-pressed', String(active));
  chip.dataset.value = label;

  chip.innerHTML = `
    <span class="chip-filter__check">${active ? '\u25A3' : '\u25A1'}</span>
    <span class="chip-filter__label">${escapeHtml(label)}</span>
    ${count > 0 ? `<span class="chip-filter__count">${formatCount(count)}</span>` : ''}
  `;

  chip.addEventListener('click', () => {
    const isActive = chip.classList.toggle('chip-filter--active');
    chip.setAttribute('aria-pressed', String(isActive));
    const check = chip.querySelector('.chip-filter__check');
    if (check) check.textContent = isActive ? '\u25A3' : '\u25A1';
    if (typeof onChange === 'function') onChange(isActive);
  });

  return chip;
}

export function setChipActive(chip, active) {
  chip.classList.toggle('chip-filter--active', active);
  chip.setAttribute('aria-pressed', String(active));
  const check = chip.querySelector('.chip-filter__check');
  if (check) check.textContent = active ? '\u25A3' : '\u25A1';
}

/**
 * Create a chip filter group with header, bulk actions, and chips.
 *
 * Usage:
 *   const group = createChipFilterGroup({
 *     label: 'Plugins',
 *     items: [{ value: 'foundation', label: 'Foundation (12)', active: true }],
 *     onChange: (activeValues) => console.log(activeValues)
 *   });
 *   container.appendChild(group);
 */
export function createChipFilterGroup({
  label = '',
  items = [], // [{ value, label, count, active }]
  showBulkActions = true,
  onChange = null,
} = {}) {
  const group = document.createElement('div');
  group.className = 'chip-filter-group';

  // Header with label and bulk actions
  const header = document.createElement('div');
  header.className = 'chip-filter-group__header';

  const labelEl = document.createElement('span');
  labelEl.className = 'chip-filter-group__label';
  labelEl.textContent = label;
  header.appendChild(labelEl);

  const activeValues = new Set(items.filter(i => i.active !== false).map(i => i.value));

  if (showBulkActions) {
    const actions = document.createElement('div');
    actions.className = 'chip-filter-group__actions';
    actions.innerHTML = `
      <button class="chip-action" data-action="all">All</button>
      <button class="chip-action" data-action="none">None</button>
    `;
    header.appendChild(actions);

    actions.querySelector('[data-action="all"]')?.addEventListener('click', () => {
      items.forEach(item => activeValues.add(item.value));
      updateChips();
      if (onChange) onChange([...activeValues]);
    });

    actions.querySelector('[data-action="none"]')?.addEventListener('click', () => {
      activeValues.clear();
      updateChips();
      if (onChange) onChange([]);
    });
  }

  group.appendChild(header);

  // Chips container
  const chipsContainer = document.createElement('div');
  chipsContainer.className = 'chip-filter-group__chips';

  const chipElements = [];

  function updateChips() {
    chipElements.forEach(({ value, chip }) => {
      setChipActive(chip, activeValues.has(value));
    });
  }

  items.forEach(item => {
    const chip = createChipFilter({
      label: item.label || item.value,
      count: item.count || 0,
      active: activeValues.has(item.value),
      onChange: (active) => {
        if (active) activeValues.add(item.value);
        else activeValues.delete(item.value);
        if (onChange) onChange([...activeValues]);
      },
    });
    chip.dataset.value = item.value;
    if (item.color) {
      chip.style.setProperty('--chip-color', item.color);
    }
    chipsContainer.appendChild(chip);
    chipElements.push({ value: item.value, chip });
  });

  group.appendChild(chipsContainer);

  return group;
}

function formatCount(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

const chipFilterStyles = `
  .chip-filter__check { font-size: 11px; line-height: 1; }
  .chip-filter__label { white-space: nowrap; }
  .chip-filter__count { font-size: 9px; color: var(--on-surface-variant); opacity: 0.7; margin-left: 2px; }
  .chip-filter--active .chip-filter__count { color: var(--accent-cyan); opacity: 1; }

  /* Chip filter group */
  .chip-filter-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .chip-filter-group__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .chip-filter-group__label {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .chip-filter-group__actions {
    display: flex;
    gap: 4px;
  }

  .chip-action {
    font-family: var(--font-mono);
    font-size: 10px;
    padding: 2px 8px;
    background: var(--surface-container-high);
    border: var(--hairline);
    border-radius: var(--radius-sm);
    color: var(--on-surface-variant);
    cursor: pointer;
    transition: all 100ms ease;
  }

  .chip-action:hover {
    background: var(--surface-container-highest);
    color: var(--on-surface);
  }

  .chip-filter-group__chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  /* Base chip filter styles */
  .chip-filter {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    background: var(--surface-container);
    border: var(--hairline);
    border-color: var(--outline-variant);
    border-radius: var(--radius-full);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    cursor: pointer;
    transition: all 150ms ease;
  }

  .chip-filter:hover {
    background: var(--surface-container-high);
    border-color: var(--outline);
  }

  .chip-filter--active {
    background: var(--surface-container-high);
    border-color: var(--chip-color, var(--accent-cyan));
    color: var(--chip-color, var(--on-surface));
  }

  .chip-filter--active:hover {
    background: var(--surface-container-highest);
  }
`;

function injectStyles() {
  if (document.getElementById('chip-filter-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'chip-filter-styles';
  styleEl.textContent = chipFilterStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
