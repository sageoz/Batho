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
    const isActive = idx.id === indexId;
    const shortId = idx.id.replace(/^batho_/, '').slice(0, 12);
    return `<button class="header-bar__dropdown-item ${isActive ? 'header-bar__dropdown-item--active' : ''}" data-index-id="${escapeHtml(idx.id)}">
      <span class="header-bar__dropdown-item-id">${shortId}</span>
      <span class="header-bar__dropdown-item-time">${formatRelativeTime(idx.timestamp)}</span>
    </button>`;
  }).join('');

  container.innerHTML = `
    <div class="header-bar__brand">
      <span class="header-bar__logo">▮</span>
      <span class="header-bar__title">BATHO</span>
    </div>
    <div class="header-bar__path">${escapeHtml(repoRoot)}</div>
    <div class="header-bar__index-wrapper">
      ${showStalenessBadge ? '<div class="glow-badge"><div class="glow-badge__dot"></div></div>' : ''}
      <details class="header-bar__dropdown">
        <summary class="header-bar__index">
          <span class="header-bar__index-label">IDX</span>
          <span class="header-bar__index-value">${escapeHtml(indexId.replace(/^batho_/, '').slice(0, 12))}</span>
          <span class="header-bar__index-arrow">▾</span>
        </summary>
        <div class="header-bar__dropdown-menu">
          ${optionsHtml}
        </div>
      </details>
    </div>
    ${warningCount > 0 ? `<div class="header-bar__warnings"><span class="header-bar__warning-icon">⚠</span><span class="header-bar__warning-count">${warningCount}</span></div>` : ''}
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

  localStorage.setItem('batho.activeIndexId', newIndexId);

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
    const isActive = idx.id === activeId;
    const shortId = idx.id.replace(/^batho_/, '').slice(0, 12);
    return `<button class="header-bar__dropdown-item ${isActive ? 'header-bar__dropdown-item--active' : ''}" data-index-id="${escapeHtml(idx.id)}">
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

  if (props.repoRoot !== undefined && pathEl) pathEl.textContent = props.repoRoot;
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

function escapeHtml(text) { const d = document.createElement('div'); d.textContent = text; return d.innerHTML; }

const headerBarStyles = `
  .header-bar { display: flex; align-items: center; height: 32px; padding: 0 var(--space-pad); background: var(--surface-container); border-bottom: var(--hairline); gap: var(--space-pad); }
  .header-bar__brand { display: flex; align-items: center; gap: var(--space-tight); }
  .header-bar__logo { font-family: var(--font-mono); font-size: 16px; color: var(--accent-cyan); }
  .header-bar__title { font-family: var(--font-mono); font-size: var(--type-heading-glyph-size); font-weight: var(--type-heading-glyph-weight); letter-spacing: var(--type-heading-glyph-tracking); text-transform: uppercase; color: var(--on-surface); }
  .header-bar__path { flex: 1; font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--tint-on-surface-70); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .header-bar__index-wrapper { display: flex; align-items: center; gap: var(--space-tight); }
  .header-bar__dropdown { position: relative; }
  .header-bar__index { display: flex; align-items: center; gap: var(--space-tight); padding: var(--space-tight) var(--space-gutter); background: var(--surface-container-low); border: var(--hairline); cursor: pointer; list-style: none; }
  .header-bar__index::-webkit-details-marker { display: none; }
  .header-bar__index:hover { background: var(--surface-container); }
  .header-bar__index-label { font-family: var(--font-sans); font-size: var(--type-ui-label-size); font-weight: var(--type-ui-label-weight); color: var(--on-surface-variant); }
  .header-bar__index-value { font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .header-bar__index-arrow { font-size: 8px; color: var(--on-surface-variant); }
  .header-bar__dropdown-menu { position: absolute; top: 100%; right: 0; z-index: 100; min-width: 240px; max-height: 300px; overflow-y: auto; background: var(--surface-container); border: var(--hairline); box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
  .header-bar__dropdown-item { display: flex; justify-content: space-between; align-items: center; width: 100%; padding: var(--space-tight) var(--space-gutter); background: none; border: none; border-bottom: 1px solid var(--outline-variant); color: var(--on-surface); cursor: pointer; font-family: var(--font-mono); font-size: var(--type-node-code-size); text-align: left; }
  .header-bar__dropdown-item:last-child { border-bottom: none; }
  .header-bar__dropdown-item:hover { background: var(--surface-container-high); }
  .header-bar__dropdown-item--active { background: var(--surface-container-high); color: var(--accent-cyan); }
  .header-bar__dropdown-item-id { font-weight: var(--type-node-code-weight); }
  .header-bar__dropdown-item-time { font-size: var(--type-terminal-size); color: var(--on-surface-variant); }
  .header-bar__warnings { display: flex; align-items: center; gap: var(--space-tight); padding: var(--space-tight) var(--space-gutter); color: var(--tertiary); }
  .header-bar__warning-icon { font-size: 12px; }
  .header-bar__warning-count { font-family: var(--font-mono); font-size: var(--type-node-code-size); }
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
