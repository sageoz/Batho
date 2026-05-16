/**
 * Entities page - virtualized table of all graph entities with type/path filtering.
 */

import { loadIndex, loadGraph, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { formatInt } from '../assets/js/format.js';
import { filterByGlob } from '../assets/js/glob.js';
import { createDataTable, setRows } from '../shared/components/data-table.js';
import { entityChipHtml } from '../shared/components/entity-chip.js';

const ENTITY_TYPES = [
  'FUNCTION', 'METHOD', 'CLASS', 'DOCUMENT', 'ELEMENT', 'SECTION',
  'SETTING', 'FIELD', 'ENTRY_POINT', 'STRUCT', 'NAMESPACE', 'INTERFACE', 'ENUM', 'TRAIT',
];

export async function renderRelationships(params) {
  const container = document.createElement('div');
  container.className = 'page page--entities';
  container.innerHTML = `<div class="panel" aria-busy="true"><div class="loading"><span class="loading__cursor"></span><span>loading entities …</span></div></div>`;

  try {
    const savedIndexId = localStorage.getItem('batho.activeIndexId');
    const indexData = await loadIndex();
    const activeIndexId = savedIndexId && indexData.indexes[savedIndexId]
      ? savedIndexId
      : indexData.currentIndexId;

    const graphData = await loadGraph(activeIndexId).catch((err) => {
      if (err.name === 'MissingArtifactError') return null;
      throw err;
    });

    if (!graphData || !graphData.entities.length) {
      container.innerHTML = `
        <div class="panel">
          <div class="panel__title">Entities</div>
          <div class="empty-state">No entities found. Run <code>batho scan</code> to index your codebase.</div>
        </div>
      `;
      return container;
    }

    let typeFilter = '';
    let globFilter = '';

    // Compute available types from data
    const typeCounts = {};
    for (const e of graphData.entities) {
      typeCounts[e.type] = (typeCounts[e.type] || 0) + 1;
    }
    const sortedTypes = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);

    const totalEntities = graphData.entities.length;

    container.innerHTML = `
      <div class="entities">
        <div class="panel">
          <div class="entities-header">
            <h1 class="panel__title">Entities</h1>
            <div class="entities-meta">
              <span id="entities-count">${formatInt(totalEntities)}</span>
              <span class="entities-meta__sep">·</span>
              <span>${sortedTypes.length} types</span>
            </div>
          </div>
          <div class="entities-toolbar">
            <select class="entities-type-filter" id="entities-type-select">
              <option value="">All types</option>
              ${sortedTypes.map(([type, count]) => `<option value="${type}">${type} (${formatInt(count)})</option>`).join('')}
            </select>
            <input class="entities-path-filter" type="text" placeholder="filter by path glob (e.g. src/**/*.py)" value="" />
          </div>
        </div>
        <div class="entities-table-mount" id="entities-table-mount"></div>
      </div>
    `;

    const tableMount = container.querySelector('#entities-table-mount');
    const typeSelect = container.querySelector('#entities-type-select');
    const pathInput = container.querySelector('.entities-path-filter');
    const countEl = container.querySelector('#entities-count');

    // Create table once
    const table = createDataTable({
      columns: [
        { key: 'type', label: 'Type', width: '120px', render: (row) => entityChipHtml(row.type, '') },
        { key: 'name', label: 'Name', width: '200px' },
        { key: 'file', label: 'File', width: '300px', render: (row) => {
          const f = row.file || '';
          const short = f.split('/').slice(-2).join('/');
          return `<span title="${escapeHtml(f)}">${escapeHtml(short)}</span>`;
        }},
        { key: 'startLine', label: 'Line', width: '60px' },
        { key: 'signature', label: 'Signature', render: (row) => {
          const sig = row.signature || '';
          return sig ? `<span title="${escapeHtml(sig)}">${escapeHtml(sig.slice(0, 60))}${sig.length > 60 ? '…' : ''}</span>` : '—';
        }},
      ],
      rows: graphData.entities,
      rowHeight: 28,
      buffer: 10,
      onRowClick: (row) => {
        window.dispatchEvent(new CustomEvent('batho:focus-entity', { detail: { entity: row } }));
      },
      emptyMessage: 'No entities match the filters',
    });
    table.style.height = 'calc(100vh - 220px)';
    tableMount.appendChild(table);

    function applyFilters() {
      let filtered = graphData.entities;
      if (typeFilter) {
        filtered = filtered.filter((e) => e.type === typeFilter);
      }
      if (globFilter) {
        filtered = filterByGlob(filtered, globFilter, 'file');
      }
      setRows(table, filtered);
      countEl.textContent = formatInt(filtered.length);
    }

    typeSelect.addEventListener('change', () => {
      typeFilter = typeSelect.value;
      applyFilters();
    });

    let filterTimeout;
    pathInput.addEventListener('input', () => {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        globFilter = pathInput.value.trim();
        applyFilters();
      }, 200);
    });

  } catch (err) {
    container.innerHTML = renderErrorPanel(err);
  }
  return container;
}

function renderErrorPanel(err) {
  const isMissing = err && err.name === 'MissingArtifactError';
  let title = 'Error';
  let message = err?.message || 'An unknown error occurred';

  if (isMissing) {
    title = 'Missing Artifact';
    message = `Could not load \`${err.path}\`.`;
  }

  return `
    <div class="panel error-panel">
      <div class="error-panel__icon">⚠</div>
      <div class="error-panel__title">${escapeHtml(title)}</div>
      <div class="error-panel__message">${escapeHtml(message)}</div>
      <div class="error-panel__actions">
        <button class="btn" data-action="retry">retry</button>
      </div>
    </div>
  `;
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

const entitiesStyles = `
  .entities { display: flex; flex-direction: column; gap: var(--space-gutter); }
  .entities-header { display: flex; flex-direction: column; gap: var(--space-tight); }
  .entities-meta { display: flex; align-items: center; gap: var(--space-tight); font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface-variant); }
  .entities-meta__sep { opacity: 0.5; }
  .entities-toolbar { display: flex; align-items: center; gap: var(--space-gutter); margin-top: var(--space-tight); }
  .entities-type-filter { padding: var(--space-tight) var(--space-gutter); font-family: var(--font-mono); font-size: var(--type-node-code-size); background: var(--surface-container); border: var(--hairline); color: var(--on-surface); outline: none; }
  .entities-type-filter:focus { border-color: var(--accent-cyan); }
  .entities-path-filter { flex: 1; padding: var(--space-tight) var(--space-gutter); font-family: var(--font-mono); font-size: var(--type-node-code-size); background: var(--surface-container); border: var(--hairline); color: var(--on-surface); outline: none; }
  .entities-path-filter:focus { border-color: var(--accent-cyan); }
  .empty-state { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); padding: var(--space-gutter); text-align: center; }
  .empty-state code { color: var(--accent-cyan); }
`;

function injectStyles() {
  if (document.getElementById('entities-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'entities-styles';
  styleEl.textContent = entitiesStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
