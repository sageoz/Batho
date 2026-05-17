/**
 * Files page - categorized file tree + flat document list.
 */

import { loadIndex, loadFiles, loadGraph, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { formatInt } from '../assets/js/format.js';
import { filterByGlob } from '../assets/js/glob.js';
import { router } from '../assets/js/router.js';
import { createDataTable, setRows } from '../shared/components/data-table.js';
import { entityChipHtml } from '../shared/components/entity-chip.js';

export async function renderFiles(params) {
  const container = document.createElement('div');
  container.className = 'page page--files';
  container.innerHTML = `<div class="panel" aria-busy="true"><div class="loading"><span class="loading__cursor"></span><span>loading files …</span></div></div>`;

  try {
    const savedIndexId = localStorage.getItem('batho.activeIndexId');
    const indexData = await loadIndex();
    const activeIndexId = savedIndexId && indexData.indexes[savedIndexId]
      ? savedIndexId
      : indexData.currentIndexId;

    const [filesDoc, graphData] = await Promise.all([
      loadFiles(activeIndexId).catch((err) => {
        if (err.name === 'MissingArtifactError') return null;
        throw err;
      }),
      loadGraph(activeIndexId).catch((err) => {
        if (err.name === 'MissingArtifactError') return null;
        throw err;
      }),
    ]);

    let viewMode = 'tree';
    let globFilter = '';

    const totalFiles = filesDoc?.summary?.totalFiles || 0;
    const totalEntities = filesDoc?.summary?.totalEntities || 0;

    container.innerHTML = `
      <div class="files">
        <div class="panel">
          <div class="files-header">
            <h1 class="panel__title">Files</h1>
            <div class="files-meta">
              <span>${formatInt(totalFiles)} files</span>
              <span class="files-meta__sep">·</span>
              <span>${formatInt(totalEntities)} entities</span>
            </div>
          </div>
          <div class="files-toolbar">
            <input class="files-filter" type="text" placeholder="filter by path glob (e.g. tests/**/*.py)" value="" />
            <div class="files-view-toggle">
              <button class="btn btn--sm files-view-btn files-view-btn--tree active" data-view="tree">Tree</button>
              <button class="btn btn--sm files-view-btn files-view-btn--flat" data-view="flat">Flat</button>
            </div>
          </div>
        </div>
        <div class="files-content" id="files-content-mount"></div>
      </div>
    `;

    const contentMount = container.querySelector('#files-content-mount');
    const filterInput = container.querySelector('.files-filter');

    function renderTree() {
      if (!filesDoc) {
        contentMount.innerHTML = '<div class="empty-state">No files data available. Run <code>batho index</code> to generate context artifacts.</div>';
        return;
      }

      const filteredCategories = filesDoc.categories.map((cat) => {
        const filteredDirs = cat.directories.map((dir) => {
          const filteredFiles = globFilter
            ? filterByGlob(dir.files, globFilter, 'relativePath')
            : dir.files;
          return { ...dir, files: filteredFiles };
        }).filter((dir) => dir.files.length > 0);
        return { ...cat, directories: filteredDirs };
      }).filter((cat) => cat.directories.length > 0);

      if (filteredCategories.length === 0) {
        contentMount.innerHTML = '<div class="empty-state">No files match the filter.</div>';
        return;
      }

      const html = filteredCategories.map((cat) => {
        const dirHtml = cat.directories.map((dir) => {
          const fileRows = dir.files.map((f) => {
            const breakdownChips = Object.entries(f.entitySummary.breakdown || {})
              .map(([type, count]) => `<span class="entity-chip__type" style="background:rgb(120 120 120 / 0.15)">${escapeHtml(type)} ${count}</span>`)
              .join(' ');
            const entityListHtml = f.entities.length
              ? `<div class="file-entities" style="display:none">${f.entities.map((e) =>
                  entityChipHtml(e.type, e.name, `${e.startLine || ''}`)
                ).join('')}</div>`
              : '';
            return `
              <div class="file-row file-row--clickable" data-path="${escapeAttr(f.relativePath)}" title="Click to view file">
                <div class="file-row__name">${escapeHtml(f.name)}</div>
                <div class="file-row__path">${escapeHtml(f.relativePath)}</div>
                <div class="file-row__entities">${formatInt(f.entitySummary.total)} entities ${breakdownChips}</div>
                <button class="file-row__hypergraph" data-hypergraph-path="${escapeAttr(f.relativePath)}" title="View in Hypergraph (L2)" aria-label="View ${escapeAttr(f.relativePath)} in Hypergraph">⌥</button>
                <div class="file-row__expand" data-file-path="${escapeAttr(f.relativePath)}" title="Show entities">▸</div>
              </div>
              ${entityListHtml}
            `;
          }).join('');

          return `
            <div class="dir-group">
              <div class="dir-group__path">${escapeHtml(dir.path)}</div>
              ${fileRows}
            </div>
          `;
        }).join('');

        return `
          <details class="category-group" open>
            <summary class="category-group__header">
              <span class="category-group__name">${escapeHtml(cat.name)}</span>
              <span class="category-group__count">${formatInt(cat.fileCount)} files · ${formatInt(cat.entityCount)} entities</span>
            </summary>
            ${dirHtml}
          </details>
        `;
      }).join('');

      contentMount.innerHTML = html;

      contentMount.querySelectorAll('.file-row__expand').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const row = e.currentTarget.closest('.file-row');
          const entityList = row?.nextElementSibling;
          if (entityList && entityList.classList.contains('file-entities')) {
            const isHidden = entityList.style.display === 'none';
            entityList.style.display = isHidden ? '' : 'none';
            e.currentTarget.textContent = isHidden ? '▾' : '▸';
          }
        });
      });

      contentMount.querySelectorAll('.file-row__hypergraph').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const path = e.currentTarget.dataset.hypergraphPath;
          if (path) router.navigate('/hypergraph/file/' + encodeURIComponent(path));
        });
      });

      // Click on file row to open file viewer
      contentMount.querySelectorAll('.file-row').forEach((row) => {
        row.addEventListener('click', (e) => {
          // Don't navigate if clicking on hypergraph button or expand button
          if (e.target.closest('.file-row__hypergraph') || e.target.closest('.file-row__expand')) {
            return;
          }
          const path = row.dataset.path;
          if (path) router.navigate('/file/' + encodeURIComponent(path));
        });
      });
    }

    function renderFlat() {
      if (!graphData) {
        contentMount.innerHTML = '<div class="empty-state">No graph data available. Run <code>batho index</code> to generate context artifacts.</div>';
        return;
      }

      let docEntities = graphData.entities.filter((e) => e.type === 'DOCUMENT');
      if (globFilter) {
        docEntities = filterByGlob(docEntities, globFilter, 'file');
      }

      const table = createDataTable({
        columns: [
          { key: 'name', label: 'Name', width: '200px' },
          { key: 'file', label: 'Path', width: '300px' },
          { key: 'startLine', label: 'Lines', width: '80px', render: (row) => `${row.startLine || ''}–${row.endLine || ''}` },
          { key: 'type', label: 'Type', width: '100px', render: (row) => entityChipHtml(row.type, '') },
        ],
        rows: docEntities,
        rowHeight: 28,
        buffer: 10,
        onRowClick: (row) => {
          window.dispatchEvent(new CustomEvent('batho:focus-entity', { detail: { entity: row } }));
        },
        emptyMessage: 'No documents match the filter',
      });
      table.style.height = 'calc(100vh - 220px)';

      contentMount.innerHTML = '';
      contentMount.appendChild(table);
    }

    function render() {
      if (viewMode === 'tree') renderTree();
      else renderFlat();
    }

    container.querySelectorAll('.files-view-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        viewMode = btn.dataset.view;
        container.querySelectorAll('.files-view-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        render();
      });
    });

    let filterTimeout;
    filterInput.addEventListener('input', () => {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => {
        globFilter = filterInput.value.trim();
        render();
      }, 200);
    });

    render();

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

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, '&quot;');
}

const filesStyles = `
  .files { display: flex; flex-direction: column; gap: var(--space-gutter); }
  .files-header { display: flex; flex-direction: column; gap: var(--space-tight); }
  .files-meta { display: flex; align-items: center; gap: var(--space-tight); font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface-variant); }
  .files-meta__sep { opacity: 0.5; }
  .files-toolbar { display: flex; align-items: center; gap: var(--space-gutter); margin-top: var(--space-tight); }
  .files-filter { flex: 1; padding: var(--space-tight) var(--space-gutter); font-family: var(--font-mono); font-size: var(--type-node-code-size); background: var(--surface-container); border: var(--hairline); color: var(--on-surface); outline: none; }
  .files-filter:focus { border-color: var(--accent-cyan); }
  .files-view-toggle { display: flex; gap: 2px; }
  .files-view-btn { font-family: var(--font-mono); font-size: var(--type-terminal-size); padding: var(--space-tight) var(--space-gutter); background: var(--surface-container); border: var(--hairline); color: var(--on-surface-variant); cursor: pointer; }
  .files-view-btn.active { background: var(--accent-cyan); color: var(--on-primary); border-color: var(--accent-cyan); }
  .category-group { border: var(--hairline); background: var(--surface-container); }
  .category-group__header { display: flex; align-items: center; gap: var(--space-gutter); padding: var(--space-tight) var(--space-gutter); cursor: pointer; font-family: var(--font-mono); font-size: var(--type-node-code-size); background: var(--surface-container-high); }
  .category-group__name { color: var(--on-surface); font-weight: var(--type-node-code-weight); }
  .category-group__count { color: var(--on-surface-variant); }
  .dir-group { padding: var(--space-tight) var(--space-gutter); }
  .dir-group__path { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); padding: var(--space-tight) 0; border-bottom: 1px solid var(--outline-variant); margin-bottom: var(--space-tight); }
  .file-row { display: flex; align-items: center; gap: var(--space-gutter); padding: var(--space-tight) 0; border-bottom: 1px solid var(--outline-variant); }
  .file-row:hover { background: var(--surface-container-high); }
  .file-row--clickable { cursor: pointer; position: relative; }
  .file-row--clickable::after {
    content: '👁';
    position: absolute;
    right: 8px;
    opacity: 0;
    transition: opacity 0.2s;
    font-size: 12px;
  }
  .file-row--clickable:hover::after { opacity: 0.5; }
  .file-row__name { font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface); min-width: 120px; }
  .file-row__path { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .file-row__entities { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); display: flex; gap: var(--space-tight); flex-wrap: wrap; }
  .file-row__expand { cursor: pointer; color: var(--accent-cyan); padding: 0 var(--space-tight); }
  .file-row__hypergraph {
    cursor: pointer;
    color: var(--on-surface-variant);
    background: transparent;
    border: var(--hairline);
    padding: 2px var(--space-tight);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    line-height: 1;
    border-radius: 2px;
  }
  .file-row__hypergraph:hover { color: var(--accent-cyan); border-color: var(--accent-cyan); }
  .file-entities { padding: var(--space-tight) var(--space-gutter); display: flex; flex-wrap: wrap; gap: var(--space-tight); border-bottom: 1px solid var(--outline-variant); }
  .empty-state { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); padding: var(--space-gutter); text-align: center; }
  .empty-state code { color: var(--accent-cyan); }
  .btn--sm { font-size: var(--type-terminal-size); }
`;

function injectStyles() {
  if (document.getElementById('files-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'files-styles';
  styleEl.textContent = filesStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
