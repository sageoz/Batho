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
`;

function injectStyles() {
  if (document.getElementById('chip-filter-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'chip-filter-styles';
  styleEl.textContent = chipFilterStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
