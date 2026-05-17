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
  container.innerHTML = `
    <div class="panel files-loading" aria-busy="true">
      <div class="files-loading__content">
        <svg class="files-loading__spinner" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/>
        </svg>
        <span>Loading files…</span>
      </div>
    </div>
  `;

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
        contentMount.innerHTML = `
          <div class="empty-state empty-state--error">
            <div class="empty-state__icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="18"/><line x1="9" y1="18" x2="15" y2="18"/></svg>
            </div>
            <div class="empty-state__title">No files indexed</div>
            <div class="empty-state__desc">Run <code>batho index</code> to generate context artifacts and browse your codebase.</div>
          </div>
        `;
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
        contentMount.innerHTML = `
          <div class="empty-state">
            <div class="empty-state__icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            </div>
            <div class="empty-state__title">No matches found</div>
            <div class="empty-state__desc">Try adjusting your filter pattern</div>
          </div>
        `;
        return;
      }

      const html = filteredCategories.map((cat) => {
        const dirHtml = cat.directories.map((dir) => {
          const fileRows = dir.files.map((f) => {
            const breakdownChips = Object.entries(f.entitySummary.breakdown || {})
              .map(([type, count]) => `<span class="entity-chip__type" style="background:rgb(120 120 120 / 0.15)">${escapeHtml(type)} ${count}</span>`)
              .join(' ');
            const entityListHtml = f.entities.length
              ? `<div class="file-entities" style="display:none">${f.entities.map((e) => {
                  const startLine = e.startLine || e.start_line || 0;
                  const endLine = e.endLine || e.end_line || startLine;
                  const lineRange = startLine === endLine ? `L${startLine}` : `L${startLine}-${endLine}`;
                  return entityChipHtml(e.type, e.name, lineRange);
                }).join('')}</div>`
              : '';
            const fileIcon = getFileIconSvg(f.name);
            return `
              <div class="file-row file-row--clickable" data-path="${escapeAttr(f.relativePath)}" title="Click to view file">
                <div class="file-row__icon">${fileIcon}</div>
                <div class="file-row__content">
                  <div class="file-row__name">${escapeHtml(f.name)}</div>
                  <div class="file-row__path">${escapeHtml(f.relativePath)}</div>
                </div>
                <div class="file-row__meta">
                  <div class="file-row__entities">${formatInt(f.entitySummary.total)} entities ${breakdownChips}</div>
                </div>
                <div class="file-row__actions">
                  <button class="file-row__action-btn file-row__hypergraph" data-hypergraph-path="${escapeAttr(f.relativePath)}" title="View in Hypergraph">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
                  </button>
                  <button class="file-row__action-btn file-row__expand" data-file-path="${escapeAttr(f.relativePath)}" title="Show entities" aria-expanded="false">
                    <svg class="expand-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                  </button>
                </div>
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
            btn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
            btn.classList.toggle('is-expanded', isHidden);
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
        contentMount.innerHTML = `
          <div class="empty-state empty-state--error">
            <div class="empty-state__icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>
            </div>
            <div class="empty-state__title">No graph data</div>
            <div class="empty-state__desc">Run <code>batho index</code> to build the code graph and browse entities.</div>
          </div>
        `;
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
  let icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';

  if (isMissing) {
    title = 'Missing Artifact';
    message = `Could not load \`${err.path}\`.`;
    icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="18"/></svg>';
  }

  return `
    <div class="panel error-panel">
      <div class="error-panel__icon">${icon}</div>
      <div class="error-panel__title">${escapeHtml(title)}</div>
      <div class="error-panel__message">${escapeHtml(message)}</div>
      <div class="error-panel__actions">
        <button class="btn" data-action="retry">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          Retry
        </button>
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

function getFileIconSvg(filename) {
  const ext = filename.split('.').pop()?.toLowerCase();
  const icons = {
    py: { color: '#60a5fa', icon: '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>' },
    js: { color: '#fbbf24', icon: '<path d="M3 3h18v18H3V3zm4.73 15.04c.4.85 1.27 1.33 2.18 1.33.91 0 1.77-.41 2.18-1.33.22-.42.33-.91.33-1.41v-5.5h-1.5v5.43c0 .45-.14.68-.4.68-.25 0-.4-.15-.57-.45l-1.21.75zm5.54.04c.77 1.35 2.07 1.33 2.62 1.33.91 0 2.04-.41 2.62-1.33.37-.57.56-1.28.56-2.04v-5.47h-1.5v5.39c0 .61-.1 1.02-.32 1.33-.26.37-.68.56-1.2.56-.68 0-1.05-.33-1.37-.95l-1.41.78z"/>' },
    ts: { color: '#60a5fa', icon: '<path d="M3 3h18v18H3V3zm10.71 11.29c.4.85 1.27 1.33 2.18 1.33.91 0 1.77-.41 2.18-1.33.22-.42.33-.91.33-1.41v-1.17h-1.5v1.1c0 .45-.14.68-.4.68-.25 0-.4-.15-.57-.45l-1.21.75.04.08v.02zm-2.5-4.29v1.5h2.5v5h1.5v-5h2.5v-1.5h-6.5z"/>' },
    json: { color: '#9ca3af', icon: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8 12h2v2H8v-2zm0 4h2v2H8v-2zm4-4h2v2h-2v-2zm0 4h2v2h-2v-2z"/>' },
    yaml: { color: '#f87171', icon: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8 12l2 3 2-3h-4zm4 5l-2 3-2-3h4z"/>' },
    md: { color: '#fff', icon: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8 12h2v6H8v-6zm4 0h2v6h-2v-6z"/>' },
    html: { color: '#f97316', icon: '<path d="M12 2l-8 4 8 4 8-4-8-4zm0 6.5L4.5 5 12 2l7.5 3L12 8.5zM3 9l9 4.5L21 9v6l-9 4.5L3 15V9z"/>' },
    css: { color: '#60a5fa', icon: '<path d="M3 3h18v18H3V3zm13.5 13.5L12 18l-4.5-1.5L6.75 6h10.5l-1.5 10.5h-1.5l.75-6H9.75l-.75 6H12l.75-3h-3l.75-3h7.5l-1.5 10.5h-1.5z"/>' },
    rs: { color: '#f97316', icon: '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>' },
    go: { color: '#22d3ee', icon: '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>' },
    java: { color: '#ef4444', icon: '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>' },
  };
  const { color = '#9ca3af', icon = '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>' } = icons[ext] || {};
  return `<svg width="20" height="20" viewBox="0 0 24 24" fill="${color}">${icon}</svg>`;
}

const filesStyles = `
  .files { display: flex; flex-direction: column; gap: var(--space-gutter); }
  .files-header { display: flex; flex-direction: column; gap: var(--space-tight); }
  .files-meta { display: flex; align-items: center; gap: var(--space-tight); font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface-variant); }
  .files-meta__sep { opacity: 0.5; }
  .files-toolbar { display: flex; align-items: center; gap: var(--space-gutter); margin-top: var(--space-tight); }
  .files-filter { flex: 1; padding: var(--space-tight) var(--space-gutter); font-family: var(--font-mono); font-size: var(--type-node-code-size); background: var(--surface-container); border: var(--hairline); color: var(--on-surface); outline: none; border-radius: 4px; transition: border-color 0.15s ease; }
  .files-filter:focus { border-color: var(--accent-cyan); }
  .files-filter::placeholder { color: var(--on-surface-variant); opacity: 0.6; }
  .files-view-toggle { display: flex; gap: 2px; }
  .files-view-btn { font-family: var(--font-mono); font-size: var(--type-terminal-size); padding: var(--space-tight) var(--space-gutter); background: var(--surface-container); border: var(--hairline); color: var(--on-surface-variant); cursor: pointer; border-radius: 4px; transition: all 0.15s ease; }
  .files-view-btn:hover { background: var(--surface-container-high); color: var(--on-surface); }
  .files-view-btn.active { background: var(--accent-cyan); color: var(--on-primary); border-color: var(--accent-cyan); }
  .category-group { border: var(--hairline); background: var(--surface-container); border-radius: 6px; overflow: hidden; }
  .category-group__header { display: flex; align-items: center; gap: var(--space-gutter); padding: var(--space-gutter); cursor: pointer; font-family: var(--font-mono); font-size: var(--type-node-code-size); background: var(--surface-container-high); transition: background 0.15s ease; }
  .category-group__header:hover { background: var(--surface-container-highest); }
  .category-group__name { color: var(--on-surface); font-weight: var(--type-node-code-weight); }
  .category-group__count { color: var(--on-surface-variant); margin-left: auto; font-size: var(--type-terminal-size); }
  .dir-group { padding: var(--space-tight) var(--space-gutter); }
  .dir-group__path { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); padding: var(--space-tight) var(--space-gutter); border-bottom: 1px solid var(--outline-variant); margin-bottom: var(--space-tight); display: flex; align-items: center; gap: var(--space-tight); }
  .dir-group__path::before { content: ''; display: inline-block; width: 14px; height: 14px; background: currentColor; mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'%3E%3Cpath d='M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'/%3E%3C/svg%3E") no-repeat center; mask-size: contain; opacity: 0.6; }
  .file-row { display: flex; align-items: center; gap: var(--space-gutter); padding: 8px var(--space-gutter); border-bottom: 1px solid var(--outline-variant); transition: background 0.15s ease; }
  .file-row:hover { background: var(--surface-container-high); }
  .file-row--clickable { cursor: pointer; }
  .file-row__icon { flex-shrink: 0; display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; background: var(--surface-container-high); border-radius: 4px; }
  .file-row__content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .file-row__name { font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface); font-weight: 500; }
  .file-row__path { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .file-row__meta { display: flex; align-items: center; gap: var(--space-tight); }
  .file-row__entities { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); display: flex; gap: var(--space-tight); flex-wrap: wrap; align-items: center; }
  .file-row__actions { display: flex; align-items: center; gap: 4px; opacity: 0; transition: opacity 0.15s ease; }
  .file-row:hover .file-row__actions { opacity: 1; }
  .file-row__action-btn { cursor: pointer; color: var(--on-surface-variant); background: transparent; border: var(--hairline); padding: 6px; display: flex; align-items: center; justify-content: center; border-radius: 4px; transition: all 0.15s ease; }
  .file-row__action-btn:hover { color: var(--accent-cyan); border-color: var(--accent-cyan); background: var(--surface-container-high); }
  .file-row__expand .expand-icon { transition: transform 0.2s ease; }
  .file-row__expand.is-expanded .expand-icon { transform: rotate(90deg); }
  .entity-chip__type { font-size: 10px; padding: 2px 6px; border-radius: 3px; background: var(--surface-container-high); color: var(--on-surface-variant); border: var(--hairline); }
  .file-entities { padding: var(--space-gutter); display: flex; flex-wrap: wrap; gap: var(--space-tight); background: var(--surface); border-bottom: 1px solid var(--outline-variant); }
  .empty-state { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); padding: calc(var(--space-gutter) * 3); text-align: center; display: flex; flex-direction: column; align-items: center; gap: var(--space-gutter); }
  .empty-state code { color: var(--accent-cyan); background: var(--surface-container-high); padding: 2px 6px; border-radius: 3px; }
  .btn--sm { font-size: var(--type-terminal-size); }

  /* Empty states */
  .empty-state__icon { color: var(--on-surface-variant); opacity: 0.5; margin-bottom: var(--space-gutter); }
  .empty-state__title { font-size: var(--type-section-header-size); font-weight: var(--type-section-header-weight); color: var(--on-surface); margin-bottom: var(--space-tight); }
  .empty-state__desc { color: var(--on-surface-variant); max-width: 400px; line-height: 1.5; }
  .empty-state--error .empty-state__icon { color: var(--tertiary); }

  /* Error panel */
  .error-panel { display: flex; flex-direction: column; align-items: center; text-align: center; padding: calc(var(--space-gutter) * 3); }
  .error-panel__icon { color: var(--tertiary); margin-bottom: var(--space-gutter); }
  .error-panel__title { font-size: var(--type-section-header-size); font-weight: var(--type-section-header-weight); color: var(--on-surface); margin-bottom: var(--space-tight); }
  .error-panel__message { color: var(--on-surface-variant); margin-bottom: var(--space-gutter); max-width: 400px; }
  .error-panel__actions { display: flex; gap: var(--space-tight); }

  /* Loading state */
  .files-loading { display: flex; align-items: center; justify-content: center; min-height: 300px; }
  .files-loading__content { display: flex; align-items: center; gap: var(--space-gutter); color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); }
  .files-loading__spinner { animation: files-loading-spin 1s linear infinite; color: var(--accent-cyan); }
  @keyframes files-loading-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

  @media (max-width: 768px) {
    .file-row { flex-wrap: wrap; }
    .file-row__meta { width: 100%; padding-left: 36px; }
    .file-row__actions { opacity: 1; }
  }
`;

function injectStyles() {
  if (document.getElementById('files-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'files-styles';
  styleEl.textContent = filesStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
