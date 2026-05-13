/**
 * Stat tile component - KPI display with optional trend indicator.
 */

export function createStatTile({ label, value, delta, deltaTone = 'neutral', glyph }) {
  const tile = document.createElement('div');
  tile.className = 'stat-tile';
  tile.setAttribute('role', 'group');
  tile.setAttribute('aria-label', label);

  const deltaHtml = delta !== undefined
    ? `<div class="stat-tile__delta stat-tile__delta--${deltaTone}">${delta}</div>`
    : '';

  const glyphHtml = glyph ? `<span class="stat-tile__glyph">${glyph}</span>` : '';

  tile.innerHTML = `
    <div class="stat-tile__label">${glyphHtml}${label}</div>
    <div class="stat-tile__value">${value}</div>
    ${deltaHtml}
  `;
  return tile;
}

export function updateStatTile(tile, { value, delta, deltaTone }) {
  if (!tile) return;
  const valueEl = tile.querySelector('.stat-tile__value');
  const deltaEl = tile.querySelector('.stat-tile__delta');
  if (value !== undefined && valueEl) valueEl.textContent = value;
  if (delta !== undefined) {
    if (deltaEl) {
      deltaEl.textContent = delta;
      deltaEl.className = `stat-tile__delta stat-tile__delta--${deltaTone || 'neutral'}`;
    } else if (delta !== null) {
      const newDelta = document.createElement('div');
      newDelta.className = `stat-tile__delta stat-tile__delta--${deltaTone || 'neutral'}`;
      newDelta.textContent = delta;
      tile.appendChild(newDelta);
    }
  }
}
