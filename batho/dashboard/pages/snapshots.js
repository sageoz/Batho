/**
 * Snapshots page - timeline of all indexes with deltas.
 */

import { loadIndex, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { formatRelativeTime, formatInt } from '../assets/js/format.js';

export async function renderSnapshots(params) {
  const container = document.createElement('div');
  container.className = 'page page--snapshots';
  container.innerHTML = `<div class="panel" aria-busy="true"><div class="loading"><span class="loading__cursor"></span><span>loading snapshots …</span></div></div>`;

  try {
    const indexData = await loadIndex();
    const indexes = Object.values(indexData.indexes);

    if (indexes.length === 0) {
      container.innerHTML = `
        <div class="panel">
          <div class="panel__title">Snapshots</div>
          <div class="empty-state">No snapshots yet. Run <code>batho scan</code> to create your first index.</div>
        </div>
      `;
      return container;
    }

    const sorted = [...indexes].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    const savedId = localStorage.getItem('batho.activeIndexId');
    const currentId = savedId && indexData.indexes[savedId] ? savedId : indexData.currentIndexId;

    const rows = sorted.map((entry, i) => {
      const prev = sorted[i + 1];
      const isActive = entry.id === currentId;
      const shortId = (entry.id || '').replace(/^batho_/, '').slice(0, 12);
      const shortHash = entry.repoHash
        ? entry.repoHash.slice(0, 8) + '…' + entry.repoHash.slice(-4)
        : '—';

      const delta = prev
        ? {
            files: (entry.fileCount ?? 0) - (prev.fileCount ?? 0),
            entities: (entry.entityCount ?? 0) - (prev.entityCount ?? 0),
            relationships: (entry.relationshipCount ?? 0) - (prev.relationshipCount ?? 0),
          }
        : null;

      const staleness = entry.stalenessScore ?? 0;
      const stalenessPct = Math.round(staleness * 100);

      return { entry, isActive, shortId, shortHash, delta, staleness, stalenessPct };
    });

    container.innerHTML = `
      <div class="snapshots">
        <div class="panel">
          <div class="snapshots-header">
            <h1 class="panel__title">Snapshots</h1>
            <div class="snapshots-meta">
              <span>${rows.length} indexes</span>
              <span class="snapshots-meta__sep">·</span>
              <span>current <strong>${escapeHtml(currentId.replace(/^batho_/, '').slice(0, 8))}…</strong></span>
            </div>
          </div>
        </div>
        <div class="timeline">
          ${rows.map((r) => renderSnapshotRow(r)).join('')}
        </div>
      </div>
    `;

    container.querySelectorAll('[data-action="make-active"]').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const indexId = e.currentTarget.dataset.indexId;
        if (!indexId) return;
        localStorage.setItem('batho.activeIndexId', indexId);
        window.dispatchEvent(new CustomEvent('batho:index-changed', { detail: { indexId } }));
        const newSnapshots = await renderSnapshots(params);
        const mountPoint = document.getElementById('page-mount');
        if (mountPoint) {
          mountPoint.innerHTML = '';
          mountPoint.appendChild(newSnapshots);
        }
      });
    });
  } catch (err) {
    container.innerHTML = renderErrorPanel(err);
    bindErrorActions(container);
  }
  return container;
}

function renderErrorPanel(err) {
  const isCtnIndexMissing =
    err && err.name === 'MissingArtifactError' && typeof err.path === 'string' && err.path.endsWith('/.ctn/index.json');

  let title = 'Error';
  let message = err?.message || 'An unknown error occurred';

  if (isCtnIndexMissing) {
    title = 'Structural Fault';
    message = 'No `.ctn/` folder found. Run `batho scan` first to populate `.ctn/`.';
  } else if (err?.name === 'MissingArtifactError') {
    title = 'Missing Artifact';
    message = `Could not load \`${err.path}\`.`;
  } else if (err?.name === 'ParseError') {
    title = 'Corrupt Artifact';
  } else if (err?.name === 'SchemaMismatchError') {
    title = 'Schema Mismatch';
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

function bindErrorActions(container) {
  const retryBtn = container.querySelector('[data-action="retry"]');
  if (retryBtn) retryBtn.addEventListener('click', () => location.reload());
}

function renderSnapshotRow(row) {
  const { entry, isActive, shortId, shortHash, delta, staleness, stalenessPct } = row;

  const markerClass = isActive ? 'timeline__marker--active' : 'timeline__marker--inactive';
  const activeBadge = isActive ? '<span class="timeline__active-badge">● ACTIVE</span>' : '';

  const deltaHtml = delta
    ? `
      <div class="timeline__deltas">
        <span class="delta ${delta.files >= 0 ? 'delta--pos' : 'delta--neg'}">Δ files ${delta.files >= 0 ? '+' : ''}${delta.files}</span>
        <span class="delta ${delta.entities >= 0 ? 'delta--pos' : 'delta--neg'}">Δ ent ${delta.entities >= 0 ? '+' : ''}${delta.entities}</span>
        <span class="delta ${delta.relationships >= 0 ? 'delta--pos' : 'delta--neg'}">Δ rel ${delta.relationships >= 0 ? '+' : ''}${delta.relationships}</span>
      </div>
    `
    : '<div class="timeline__deltas"><span class="delta delta--neutral">Δ —</span></div>';

  const stalenessClass = isActive && staleness >= 0.5 ? 'timeline__staleness--stale' : '';

  return `
    <article class="timeline__item ${isActive ? 'timeline__item--active' : ''}">
      <div class="timeline__marker ${markerClass}"></div>
      <div class="timeline__content">
        <div class="timeline__header">
          <span class="timeline__id">${escapeHtml(shortId)}</span>
          <span class="timeline__time">${formatRelativeTime(entry.timestamp)}</span>
          ${activeBadge}
        </div>
        <div class="timeline__meta">
          <span class="timeline__hash">repo_hash ${escapeHtml(shortHash)}</span>
          <span class="timeline__sep">·</span>
          <span>files ${formatInt(entry.fileCount ?? 0)}</span>
          <span class="timeline__sep">·</span>
          <span>ent ${formatInt(entry.entityCount ?? 0)}</span>
          <span class="timeline__sep">·</span>
          <span>rel ${formatInt(entry.relationshipCount ?? 0)}</span>
        </div>
        ${deltaHtml}
        <div class="timeline__actions">
          ${!isActive ? `<button class="btn btn--ghost" data-action="make-active" data-index-id="${escapeAttr(entry.id)}">make active</button>` : ''}
          <div class="timeline__staleness ${stalenessClass}">
            <span>staleness</span>
            <div class="timeline__staleness-bar">
              <div class="timeline__staleness-fill" style="width: ${stalenessPct}%"></div>
            </div>
            <span>${stalenessPct}</span>
          </div>
        </div>
      </div>
    </article>
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

const snapshotsStyles = `
  .snapshots { display: flex; flex-direction: column; gap: var(--space-gutter); }
  .snapshots-header { display: flex; flex-direction: column; gap: var(--space-tight); }
  .snapshots-meta { display: flex; align-items: center; gap: var(--space-tight); font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface-variant); }
  .snapshots-meta__sep { opacity: 0.5; }
  .snapshots-meta strong { color: var(--accent-cyan); }
  .timeline { display: flex; flex-direction: column; gap: var(--space-gutter); }
  .timeline__item { display: flex; gap: var(--space-gutter); padding: var(--space-gutter); background: var(--surface-container); border: var(--hairline); }
  .timeline__item--active { border-color: var(--accent-cyan); }
  .timeline__marker { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; }
  .timeline__marker--active { background: var(--accent-cyan); box-shadow: 0 0 8px var(--accent-cyan); }
  .timeline__marker--inactive { background: transparent; border: 2px solid var(--outline); }
  .timeline__content { flex: 1; display: flex; flex-direction: column; gap: var(--space-tight); min-width: 0; }
  .timeline__header { display: flex; align-items: center; gap: var(--space-gutter); flex-wrap: wrap; }
  .timeline__id { font-family: var(--font-mono); font-size: var(--type-node-code-size); font-weight: var(--type-node-code-weight); color: var(--on-surface); }
  .timeline__time { font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface-variant); }
  .timeline__active-badge { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--accent-cyan); font-weight: bold; }
  .timeline__meta { display: flex; align-items: center; gap: var(--space-tight); flex-wrap: wrap; font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--tint-on-surface-70); }
  .timeline__sep { opacity: 0.5; }
  .timeline__hash { color: var(--on-surface-variant); }
  .timeline__deltas { display: flex; gap: var(--space-gutter); flex-wrap: wrap; }
  .delta { font-family: var(--font-mono); font-size: var(--type-terminal-size); }
  .delta--pos { color: var(--accent-cyan); }
  .delta--neg { color: var(--tertiary); }
  .delta--neutral { color: var(--on-surface-variant); }
  .timeline__actions { display: flex; align-items: center; gap: var(--space-gutter); flex-wrap: wrap; margin-top: var(--space-tight); }
  .timeline__staleness { display: flex; align-items: center; gap: var(--space-tight); font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); }
  .timeline__staleness-bar { width: 60px; height: 4px; background: var(--surface-container-high); border: var(--hairline); }
  .timeline__staleness-fill { height: 100%; background: var(--tertiary); transition: width 0.3s; }
  .timeline__staleness--stale .timeline__staleness-fill { background: var(--error); animation: pulse-warn 1.6s ease-in-out infinite; }
  .empty-state { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); padding: var(--space-gutter); text-align: center; }
  .empty-state code { color: var(--accent-cyan); }
`;

function injectStyles() {
  if (document.getElementById('snapshots-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'snapshots-styles';
  styleEl.textContent = snapshotsStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
