/**
 * Data table component with virtual scrolling.
 *
 * Only renders rows visible in the viewport plus a configurable buffer,
 * making it efficient for large datasets (8K+ rows).
 *
 * Usage:
 *   const table = createDataTable({
 *     columns: [{ key: 'name', label: 'Name' }, { key: 'type', label: 'Type' }],
 *     rows: myData,
 *     rowHeight: 28,
 *     buffer: 10,
 *     onRowClick: (row) => console.log(row),
 *   });
 *   container.appendChild(table);
 *   // Later:
 *   setRows(table, filteredData);
 */

const DEFAULT_ROW_HEIGHT = 28;
const DEFAULT_BUFFER = 10;
const HEADER_HEIGHT = 32;

export function createDataTable(props = {}) {
  const {
    columns = [],
    rows = [],
    rowHeight = DEFAULT_ROW_HEIGHT,
    buffer = DEFAULT_BUFFER,
    onRowClick = null,
    emptyMessage = 'No data',
  } = props;

  const state = {
    rows: [...rows],
    scrollTop: 0,
    containerHeight: 400,
    rafId: null,
    dirty: false,
  };

  const container = document.createElement('div');
  container.className = 'data-table';
  container.setAttribute('role', 'grid');
  container.__dtState = state;
  container.__dtProps = { columns, rowHeight, buffer, onRowClick, emptyMessage };

  // Header
  const header = document.createElement('div');
  header.className = 'data-table__header';
  header.setAttribute('role', 'row');
  for (const col of columns) {
    const th = document.createElement('div');
    th.className = 'data-table__th';
    th.setAttribute('role', 'columnheader');
    th.textContent = col.label;
    if (col.width) th.style.width = col.width;
    header.appendChild(th);
  }
  container.appendChild(header);

  // Viewport (scrollable area)
  const viewport = document.createElement('div');
  viewport.className = 'data-table__viewport';
  viewport.setAttribute('role', 'rowgroup');
  container.appendChild(viewport);

  // Spacer (total height to enable scrollbar)
  const spacer = document.createElement('div');
  spacer.className = 'data-table__spacer';
  viewport.appendChild(spacer);

  // Rendered rows container (positioned absolutely)
  const body = document.createElement('div');
  body.className = 'data-table__body';
  viewport.appendChild(body);

  // Scroll handler with rAF debounce
  viewport.addEventListener('scroll', () => {
    state.scrollTop = viewport.scrollTop;
    if (!state.rafId) {
      state.rafId = requestAnimationFrame(() => {
        state.rafId = null;
        renderVisibleRows(container);
      });
    }
  });

  // ResizeObserver to track container height
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        state.containerHeight = entry.contentRect.height - HEADER_HEIGHT;
        renderVisibleRows(container);
      }
    });
    ro.observe(viewport);
    container.__dtRO = ro;
  }

  // Initial render
  spacer.style.height = `${state.rows.length * rowHeight}px`;
  renderVisibleRows(container);

  return container;
}

function renderVisibleRows(container) {
  const state = container.__dtState;
  const { columns, rowHeight, buffer, onRowClick, emptyMessage } = container.__dtProps;
  const viewport = container.querySelector('.data-table__viewport');
  const spacer = container.querySelector('.data-table__spacer');
  const body = container.querySelector('.data-table__body');

  const totalRows = state.rows.length;
  spacer.style.height = `${totalRows * rowHeight}px`;

  if (totalRows === 0) {
    body.innerHTML = `<div class="data-table__empty">${escapeHtml(emptyMessage)}</div>`;
    body.style.transform = '';
    return;
  }

  const viewHeight = state.containerHeight || viewport.clientHeight || 400;
  const startIdx = Math.max(0, Math.floor(state.scrollTop / rowHeight) - buffer);
  const endIdx = Math.min(totalRows, Math.ceil((state.scrollTop + viewHeight) / rowHeight) + buffer);

  // Build rows HTML
  const fragments = [];
  for (let i = startIdx; i < endIdx; i++) {
    const row = state.rows[i];
    const cells = columns.map((col) => {
      const value = col.render ? col.render(row) : (row[col.key] ?? '');
      return `<div class="data-table__td" role="gridcell">${value}</div>`;
    }).join('');
    fragments.push(
      `<div class="data-table__row" data-row-index="${i}" role="row">${cells}</div>`
    );
  }

  body.innerHTML = fragments.join('');
  body.style.transform = `translateY(${startIdx * rowHeight}px)`;

  // Attach click handlers
  if (onRowClick) {
    body.querySelectorAll('.data-table__row').forEach((el) => {
      el.addEventListener('click', () => {
        const idx = parseInt(el.dataset.rowIndex, 10);
        if (idx >= 0 && idx < state.rows.length) {
          onRowClick(state.rows[idx], idx);
        }
      });
    });
  }
}

export function setRows(container, rows) {
  const state = container.__dtState;
  state.rows = rows ? [...rows] : [];
  state.scrollTop = container.querySelector('.data-table__viewport')?.scrollTop || 0;
  renderVisibleRows(container);
}

export function scrollToIndex(container, idx) {
  const viewport = container.querySelector('.data-table__viewport');
  const state = container.__dtState;
  const { rowHeight } = container.__dtProps;
  if (viewport && idx >= 0 && idx < state.rows.length) {
    viewport.scrollTop = idx * rowHeight;
  }
}

export function destroyDataTable(container) {
  if (container.__dtRO) container.__dtRO.disconnect();
  if (container.__dtState?.rafId) cancelAnimationFrame(container.__dtState.rafId);
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

// Styles
const dataTableStyles = `
  .data-table { display: flex; flex-direction: column; border: var(--hairline); background: var(--surface-container); overflow: hidden; }
  .data-table__header { display: flex; align-items: center; height: ${HEADER_HEIGHT}px; background: var(--surface-container-high); border-bottom: var(--hairline); font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); padding: 0 var(--space-tight); flex-shrink: 0; }
  .data-table__th { flex: 1; min-width: 60px; padding: var(--space-tight) var(--space-gutter); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .data-table__viewport { flex: 1; overflow-y: auto; position: relative; }
  .data-table__spacer { width: 1px; pointer-events: none; }
  .data-table__body { position: absolute; top: 0; left: 0; right: 0; will-change: transform; }
  .data-table__row { display: flex; align-items: center; height: ${DEFAULT_ROW_HEIGHT}px; border-bottom: 1px solid var(--outline-variant); cursor: pointer; transition: background 0.1s; }
  .data-table__row:hover { background: var(--surface-container-high); }
  .data-table__td { flex: 1; min-width: 60px; padding: 0 var(--space-gutter); font-family: var(--font-mono); font-size: var(--type-node-code-size); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--on-surface); }
  .data-table__empty { padding: var(--space-gutter); text-align: center; color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); }
`;

function injectStyles() {
  if (document.getElementById('data-table-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'data-table-styles';
  styleEl.textContent = dataTableStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
