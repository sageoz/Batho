/**
 * Overview page stub - Phase 0 shows indexId, root, file/entity counts.
 */

import { loadIndex, MissingArtifactError } from '../ctn-loader.js';
import { formatRelativeTime, formatInt } from '../format.js';
import { store } from '../store.js';

export async function renderOverview(params) {
  const container = document.createElement('div');
  container.className = 'page page--overview';
  container.innerHTML = `<div class="panel" aria-busy="true"><div class="loading"><span class="loading__cursor"></span><span>scanning …</span></div></div>`;

  try {
    let indexData = store.get('current', 'index');
    if (!indexData) { indexData = await loadIndex(); store.put('current', 'index', indexData); }

    const entry = indexData.indexes[indexData.currentIndexId];
    if (!entry) throw new MissingArtifactError('No index entry found');

    container.innerHTML = `
      <div class="panel"><div class="overview-header"><h1 class="panel__title">Overview</h1></div></div>
      <div class="kpi-row">
        <div class="stat-tile"><div class="stat-tile__label">Index ID</div><div class="stat-tile__value">${escapeHtml(indexData.currentIndexId)}</div></div>
        <div class="stat-tile"><div class="stat-tile__label">Root</div><div class="stat-tile__value" style="font-size: 14px;">${escapeHtml(entry.root)}</div></div>
      </div>
      <div class="kpi-row">
        <div class="stat-tile"><div class="stat-tile__label">Files</div><div class="stat-tile__value">${formatInt(entry.fileCount)}</div></div>
        <div class="stat-tile"><div class="stat-tile__label">Entities</div><div class="stat-tile__value">${formatInt(entry.entityCount)}</div></div>
        <div class="stat-tile"><div class="stat-tile__label">Relationships</div><div class="stat-tile__value">${formatInt(entry.relationshipCount)}</div></div>
        <div class="stat-tile"><div class="stat-tile__label">Last Updated</div><div class="stat-tile__value" style="font-size: 14px;">${formatRelativeTime(entry.timestamp)}</div></div>
      </div>
    `;

    const headerBar = document.getElementById('header-bar');
    if (headerBar) {
      const { updateHeaderBar } = await import('../shared/components/header-bar.js');
      updateHeaderBar(headerBar, { repoRoot: entry.root, indexId: indexData.currentIndexId });
    }
  } catch (err) {
    if (err.name === 'MissingArtifactError') {
      container.innerHTML = `<div class="panel error-panel"><div class="error-panel__icon">⚠</div><div class="error-panel__title">Structural Fault</div><div class="error-panel__message">No \`.ctn/\` folder found. Run \`batho index\` from the repo root to populate \`.ctn/\`.</div><div class="error-panel__actions"><button class="btn" data-action="retry">retry</button><button class="btn" data-action="docs">open docs</button></div></div>`;
    } else {
      container.innerHTML = `<div class="panel error-panel"><div class="error-panel__icon">⚠</div><div class="error-panel__title">Error</div><div class="error-panel__message">${escapeHtml(err.message)}</div><div class="error-panel__actions"><button class="btn" data-action="retry">retry</button></div></div>`;
    }
    const retryBtn = container.querySelector('[data-action="retry"]');
    if (retryBtn) retryBtn.addEventListener('click', () => { store.clear('current'); location.reload(); });
  }
  return container;
}

function escapeHtml(text) { const d = document.createElement('div'); d.textContent = text; return d.innerHTML; }
