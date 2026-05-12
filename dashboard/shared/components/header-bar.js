/**
 * Header bar component - brand, repo path, index switcher.
 */

export function createHeaderBar(props = {}) {
  const { repoRoot = '…', indexId = '—', warningCount = 0 } = props;
  const container = document.createElement('header');
  container.className = 'header-bar';
  container.id = 'header-bar';
  container.innerHTML = `
    <div class="header-bar__brand">
      <span class="header-bar__logo">▮</span>
      <span class="header-bar__title">BATHO</span>
    </div>
    <div class="header-bar__path">${escapeHtml(repoRoot)}</div>
    <div class="header-bar__index">
      <span class="header-bar__index-label">IDX</span>
      <span class="header-bar__index-value">${escapeHtml(indexId)}</span>
      <span class="header-bar__index-arrow">▾</span>
    </div>
    ${warningCount > 0 ? `<div class="header-bar__warnings"><span class="header-bar__warning-icon">⚠</span><span class="header-bar__warning-count">${warningCount}</span></div>` : ''}
  `;
  return container;
}

export function updateHeaderBar(container, props) {
  if (!container) return;
  const pathEl = container.querySelector('.header-bar__path');
  const indexValueEl = container.querySelector('.header-bar__index-value');
  const warningsEl = container.querySelector('.header-bar__warnings');
  if (props.repoRoot !== undefined) pathEl.textContent = props.repoRoot;
  if (props.indexId !== undefined) indexValueEl.textContent = props.indexId;
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
}

function escapeHtml(text) { const d = document.createElement('div'); d.textContent = text; return d.innerHTML; }

const headerBarStyles = `
  .header-bar { display: flex; align-items: center; height: 32px; padding: 0 var(--space-pad); background: var(--surface-container); border-bottom: var(--hairline); gap: var(--space-pad); }
  .header-bar__brand { display: flex; align-items: center; gap: var(--space-tight); }
  .header-bar__logo { font-family: var(--font-mono); font-size: 16px; color: var(--accent-cyan); }
  .header-bar__title { font-family: var(--font-mono); font-size: var(--type-heading-glyph-size); font-weight: var(--type-heading-glyph-weight); letter-spacing: var(--type-heading-glyph-tracking); text-transform: uppercase; color: var(--on-surface); }
  .header-bar__path { flex: 1; font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--tint-on-surface-70); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .header-bar__index { display: flex; align-items: center; gap: var(--space-tight); padding: var(--space-tight) var(--space-gutter); background: var(--surface-container-low); border: var(--hairline); cursor: pointer; }
  .header-bar__index:hover { background: var(--surface-container); }
  .header-bar__index-label { font-family: var(--font-sans); font-size: var(--type-ui-label-size); font-weight: var(--type-ui-label-weight); color: var(--on-surface-variant); }
  .header-bar__index-value { font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .header-bar__index-arrow { font-size: 8px; color: var(--on-surface-variant); }
  .header-bar__warnings { display: flex; align-items: center; gap: var(--space-tight); padding: var(--space-tight) var(--space-gutter); color: var(--tertiary); }
  .header-bar__warning-icon { font-size: 12px; }
  .header-bar__warning-count { font-family: var(--font-mono); font-size: var(--type-node-code-size); }
`;

function injectStyles() {
  if (document.getElementById('header-bar-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'header-bar-styles';
  styleEl.textContent = headerBarStyles;
  document.head.appendChild(styleEl);
}

injectStyles();
