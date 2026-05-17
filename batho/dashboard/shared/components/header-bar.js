/**
 * Header bar component - brand, repo path, functional index switcher.
 */

import { formatRelativeTime } from '../../assets/js/format.js';

let currentIndexes = {};
let currentActiveId = null;

export function createHeaderBar(props = {}) {
  const { repoRoot = '…', indexId = '—', indexes = {}, warningCount = 0 } = props;
  currentIndexes = indexes;
  currentActiveId = indexId;

  const container = document.createElement('header');
  container.className = 'header-bar';
  container.id = 'header-bar';

  const sortedIndexes = Object.values(indexes).sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  const activeEntry = indexes[indexId];
  const staleness = activeEntry?.stalenessScore ?? 0;
  const showStalenessBadge = staleness >= 0.5;

  const optionsHtml = sortedIndexes.map(idx => {
    const id = idx.indexId || idx.index_id || idx.id;
    const isActive = id === indexId;
    const shortId = (id || '').replace(/^batho_/, '').slice(0, 12);
    return `<button class="header-bar__dropdown-item ${isActive ? 'header-bar__dropdown-item--active' : ''}" data-index-id="${escapeHtml(id)}">
      <span class="header-bar__dropdown-item-id">${shortId}</span>
      <span class="header-bar__dropdown-item-time">${formatRelativeTime(idx.timestamp)}</span>
    </button>`;
  }).join('');

  container.innerHTML = `
    <a class="header-bar__brand" href="#/overview" title="Batho — Bidirectional AST Traversal & Hypergraph Orchestrator">
      <div class="header-bar__brand-text">
        <span class="header-bar__title">BATHO</span>
        <span class="header-bar__tagline">code intelligence engine</span>
      </div>
    </a>
    <div class="header-bar__divider"></div>
    <div class="header-bar__path" title="${escapeHtml(repoRoot)}">
      <svg class="header-bar__path-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
      </svg>
      <span class="header-bar__path-text">${escapeHtml(repoRoot)}</span>
    </div>
    <div class="header-bar__spacer"></div>
    <div class="header-bar__index-wrapper">
      ${showStalenessBadge ? `
        <div class="header-bar__staleness" title="Index is stale">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
        </div>
      ` : ''}
      <details class="header-bar__dropdown">
        <summary class="header-bar__index">
          <svg class="header-bar__index-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/>
          </svg>
          <span class="header-bar__index-label">Index</span>
          <span class="header-bar__index-value">${escapeHtml(indexId.replace(/^batho_/, '').slice(0, 12))}</span>
          <svg class="header-bar__index-arrow" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </summary>
        <div class="header-bar__dropdown-menu">
          <div class="header-bar__dropdown-header">Select Index</div>
          ${optionsHtml}
        </div>
      </details>
    </div>
    ${warningCount > 0 ? `
      <div class="header-bar__warnings" title="${warningCount} BSG quality warnings">
        <svg class="header-bar__warning-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <span class="header-bar__warning-count">${warningCount}</span>
      </div>
    ` : ''}
  `;

  const dropdown = container.querySelector('.header-bar__dropdown');
  if (dropdown) {
    dropdown.addEventListener('toggle', async (e) => {
      if (dropdown.open && (!indexes || Object.keys(indexes).length === 0)) {
        const { loadIndex } = await import('../../assets/js/ctn-loader.js');
        try {
          const indexData = await loadIndex();
          currentIndexes = indexData.indexes || {};
          currentActiveId = indexData.currentIndexId;
          updateIndexList(container, currentIndexes, currentActiveId);
        } catch (err) {
          console.error('Failed to load indexes:', err);
        }
      }
    });

    const menu = container.querySelector('.header-bar__dropdown-menu');
    if (menu) {
      menu.addEventListener('click', async (e) => {
        const item = e.target.closest('.header-bar__dropdown-item');
        if (item) {
          const newIndexId = item.dataset.indexId;
          dropdown.removeAttribute('open');
          await selectIndex(newIndexId, container);
        }
      });
    }
  }

  return container;
}

async function selectIndex(newIndexId, container) {
  if (newIndexId === currentActiveId) return;

  try {
    localStorage.setItem('batho.activeIndexId', newIndexId);
  } catch (e) {
    console.warn('[batho] Failed to save active index to localStorage:', e);
  }

  const entry = currentIndexes[newIndexId];
  if (entry) {
    const indexValueEl = container.querySelector('.header-bar__index-value');
    if (indexValueEl) {
      indexValueEl.textContent = newIndexId.replace(/^batho_/, '').slice(0, 12);
    }

    const staleness = entry.stalenessScore ?? 0;
    const wrapper = container.querySelector('.header-bar__index-wrapper');
    const existingBadge = wrapper?.querySelector('.glow-badge');
    if (staleness >= 0.5) {
      if (!existingBadge) {
        const badge = document.createElement('div');
        badge.className = 'glow-badge';
        badge.innerHTML = '<div class="glow-badge__dot"></div>';
        wrapper?.insertBefore(badge, wrapper.firstChild);
      }
    } else if (existingBadge) {
      existingBadge.remove();
    }
  }

  currentActiveId = newIndexId;

  window.dispatchEvent(new CustomEvent('batho:index-changed', { detail: { indexId: newIndexId } }));

  const liveRegion = document.getElementById('batho-live-region') || (() => {
    const lr = document.createElement('div');
    lr.id = 'batho-live-region';
    lr.className = 'visually-hidden';
    lr.setAttribute('aria-live', 'polite');
    document.body.appendChild(lr);
    return lr;
  })();
  liveRegion.textContent = `Index changed to ${newIndexId}`;
}

function updateIndexList(container, indexes, activeId) {
  const menu = container.querySelector('.header-bar__dropdown-menu');
  if (!menu) return;

  const sortedIndexes = Object.values(indexes).sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  menu.innerHTML = sortedIndexes.map(idx => {
    const id = idx.indexId || idx.index_id || idx.id;
    const isActive = id === activeId;
    const shortId = (id || '').replace(/^batho_/, '').slice(0, 12);
    return `<button class="header-bar__dropdown-item ${isActive ? 'header-bar__dropdown-item--active' : ''}" data-index-id="${escapeHtml(id)}">
      <span class="header-bar__dropdown-item-id">${shortId}</span>
      <span class="header-bar__dropdown-item-time">${formatRelativeTime(idx.timestamp)}</span>
    </button>`;
  }).join('');
}

export function updateHeaderBar(container, props) {
  if (!container) return;

  const pathEl = container.querySelector('.header-bar__path');
  const indexValueEl = container.querySelector('.header-bar__index-value');
  const warningsEl = container.querySelector('.header-bar__warnings');
  const wrapper = container.querySelector('.header-bar__index-wrapper');

  if (props.repoRoot !== undefined && pathEl) {
    const textEl = pathEl.querySelector('.header-bar__path-text');
    if (textEl) textEl.textContent = props.repoRoot;
    pathEl.title = props.repoRoot;
  }
  if (props.indexId !== undefined && indexValueEl) {
    indexValueEl.textContent = props.indexId.replace(/^batho_/, '').slice(0, 12);
    currentActiveId = props.indexId;
  }
  if (props.indexes !== undefined) {
    currentIndexes = props.indexes;
    updateIndexList(container, props.indexes, props.indexId || currentActiveId);
  }
  if (props.warningCount !== undefined) {
    if (props.warningCount > 0) {
      if (!warningsEl) {
        const warningDiv = document.createElement('div');
        warningDiv.className = 'header-bar__warnings';
        warningDiv.innerHTML = `<span class="header-bar__warning-icon">⚠</span><span class="header-bar__warning-count">${props.warningCount}</span>`;
        container.appendChild(warningDiv);
      } else { warningsEl.querySelector('.header-bar__warning-count').textContent = props.warningCount; }
    } else if (warningsEl) { warningsEl.remove(); }
  }

  if (props.indexId) {
    const entry = currentIndexes[props.indexId];
    if (entry) {
      const staleness = entry.stalenessScore ?? 0;
      const existingBadge = wrapper?.querySelector('.glow-badge');
      if (staleness >= 0.5) {
        if (!existingBadge) {
          const badge = document.createElement('div');
          badge.className = 'glow-badge';
          badge.innerHTML = '<div class="glow-badge__dot"></div>';
          wrapper?.insertBefore(badge, wrapper.firstChild);
        }
      } else if (existingBadge) {
        existingBadge.remove();
      }
    }
  }
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

const headerBarStyles = `
  .header-bar {
    display: flex; align-items: center;
    height: 56px; padding: 0 var(--space-pad-lg);
    background: linear-gradient(180deg, var(--surface-container) 0%, var(--surface-container-low) 100%);
    border-bottom: var(--hairline-strong);
    gap: var(--space-md);
    position: relative;
    flex-shrink: 0;
  }
  .header-bar::after {
    content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 1px;
    background: linear-gradient(90deg, transparent 0%, var(--primary-container) 20%, var(--accent-cyan) 50%, var(--primary-container) 80%, transparent 100%);
    opacity: 0.4; pointer-events: none;
  }
  .header-bar__brand {
    display: flex; align-items: center; gap: var(--space-sm);
    text-decoration: none; color: inherit;
    padding: var(--space-xs) var(--space-sm) var(--space-xs) 0;
    cursor: pointer;
    transition: all 0.15s ease;
    border-radius: var(--radius-sm);
  }
  .header-bar__brand:hover { background: var(--surface-container-high); }
  .header-bar__brand:focus-visible { outline: 1px solid var(--accent-cyan); outline-offset: -1px; }
  .header-bar__brand-text { display: flex; flex-direction: column; gap: 0; line-height: 1.2; }
  .header-bar__title { font-family: var(--font-mono); font-size: 15px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--on-surface); }
  .header-bar__tagline {
    font-family: var(--font-sans); font-size: 11px; font-weight: 400;
    color: var(--on-surface-variant); opacity: 0.8;
    letter-spacing: 0.06em;
  }
  @media (max-width: 720px) { .header-bar__tagline { display: none; } }
  .header-bar__divider { width: 1px; height: 24px; background: var(--outline-variant); }
  .header-bar__path {
    display: flex; align-items: center; gap: var(--space-sm);
    font-family: var(--font-mono); font-size: 13px;
    color: var(--on-surface-variant);
    overflow: hidden; min-width: 0;
    max-width: 400px;
  }
  .header-bar__path-icon { color: var(--accent-cyan); opacity: 0.7; flex-shrink: 0; width: 16px; height: 16px; }
  .header-bar__path-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .header-bar__spacer { flex: 1; min-width: 0; }
  .header-bar__index-wrapper { display: flex; align-items: center; gap: var(--space-sm); }
  .header-bar__staleness { color: #fbbf24; display: flex; align-items: center; }
  .header-bar__dropdown { position: relative; }
  .header-bar__index { display: flex; align-items: center; gap: var(--space-sm); padding: var(--space-xs) var(--space-sm); background: var(--surface-container-high); border: var(--hairline); border-radius: var(--radius-md); cursor: pointer; list-style: none; transition: all 0.15s ease; }
  .header-bar__index::-webkit-details-marker { display: none; }
  .header-bar__index:hover { background: var(--surface-container); border-color: var(--accent-cyan); }
  .header-bar__index-icon { color: var(--on-surface-variant); flex-shrink: 0; width: 16px; height: 16px; }
  .header-bar__index-label { font-family: var(--font-sans); font-size: 11px; font-weight: 600; color: var(--on-surface-variant); text-transform: uppercase; letter-spacing: 0.04em; }
  .header-bar__index-value { font-family: var(--font-mono); font-size: 13px; color: var(--on-surface); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .header-bar__index-arrow { color: var(--on-surface-variant); transition: transform 0.2s ease; flex-shrink: 0; }
  .header-bar__dropdown[open] .header-bar__index-arrow { transform: rotate(180deg); }
  .header-bar__dropdown-menu { position: absolute; top: calc(100% + 6px); right: 0; z-index: 300; min-width: 300px; max-height: 400px; overflow-y: auto; background: var(--surface-container); border: var(--hairline); border-radius: var(--radius-md); box-shadow: 0 12px 32px rgba(0,0,0,0.5); padding: var(--space-sm); }
  .header-bar__dropdown-header { font-family: var(--font-sans); font-size: 11px; font-weight: 600; color: var(--on-surface-variant); text-transform: uppercase; letter-spacing: 0.06em; padding: var(--space-xs) var(--space-sm) var(--space-sm); border-bottom: var(--hairline); margin-bottom: var(--space-xs); }
  .header-bar__dropdown-item { display: flex; justify-content: space-between; align-items: center; width: 100%; padding: var(--space-sm); background: none; border: none; border-radius: var(--radius-sm); color: var(--on-surface); cursor: pointer; font-family: var(--font-mono); font-size: 13px; text-align: left; transition: all 0.15s ease; margin-bottom: 2px; }
  .header-bar__dropdown-item:last-child { margin-bottom: 0; }
  .header-bar__dropdown-item:hover { background: var(--surface-container-high); }
  .header-bar__dropdown-item--active { background: rgb(34 211 238 / 0.1); color: var(--accent-cyan); border: 1px solid rgb(34 211 238 / 0.3); }
  .header-bar__dropdown-item-id { font-weight: 600; }
  .header-bar__dropdown-item-time { font-size: 12px; color: var(--on-surface-variant); }
  .header-bar__warnings { display: flex; align-items: center; gap: var(--space-xs); padding: var(--space-xs) var(--space-sm); color: #fbbf24; background: rgb(251 191 36 / 0.1); border: 1px solid rgb(251 191 36 / 0.3); border-radius: var(--radius-md); cursor: pointer; transition: all 0.15s ease; }
  .header-bar__warnings:hover { background: rgb(251 191 36 / 0.2); }
  .header-bar__warning-icon { flex-shrink: 0; width: 16px; height: 16px; }
  .header-bar__warning-count { font-family: var(--font-mono); font-size: 13px; font-weight: 600; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
`;

function injectStyles() {
  if (document.getElementById('header-bar-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'header-bar-styles';
  styleEl.textContent = headerBarStyles;
  document.head.appendChild(styleEl);
}

injectStyles();
