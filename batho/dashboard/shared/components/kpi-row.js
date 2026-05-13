/**
 * KPI row component - tile row layout.
 */

export function createKpiRow(tiles = []) {
  const row = document.createElement('div');
  row.className = 'kpi-row';
  tiles.forEach(tile => {
    if (tile instanceof HTMLElement) {
      row.appendChild(tile);
    } else if (tile.element) {
      row.appendChild(tile.element);
    }
  });
  return row;
}

export function updateKpiRow(row, tiles = []) {
  if (!row) return;
  row.innerHTML = '';
  tiles.forEach(tile => {
    if (tile instanceof HTMLElement) {
      row.appendChild(tile);
    } else if (tile.element) {
      row.appendChild(tile.element);
    }
  });
}
