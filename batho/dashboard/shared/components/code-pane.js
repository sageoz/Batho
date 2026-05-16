/**
 * Code pane component - monospace pre-wrap display with line numbers.
 */

export function createCodePane(props = {}) {
  const { content = '', language = '', highlightLine = null } = props;

  const pane = document.createElement('div');
  pane.className = 'code-pane';
  if (language) pane.dataset.language = language;

  const lines = content.split('\n');
  const lineNums = lines.map((_, i) => i + 1).join('\n');
  const contentHtml = lines.map((line, i) => {
    const isHighlight = highlightLine !== null && i + 1 === highlightLine;
    return `<span class="code-pane__line${isHighlight ? ' code-pane__line--highlight' : ''}">${escapeHtml(line)}</span>`;
  }).join('\n');

  pane.innerHTML = `
    <div class="code-pane__gutter">${escapeHtml(lineNums)}</div>
    <div class="code-pane__content">${contentHtml}</div>
  `;
  return pane;
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

const codePaneStyles = `
  .code-pane { display: flex; font-family: var(--font-mono); font-size: var(--type-node-code-size); line-height: 1.6; background: var(--surface-container); border: var(--hairline); overflow: auto; max-height: 400px; }
  .code-pane__gutter { flex-shrink: 0; padding: var(--space-tight) var(--space-gutter); text-align: right; color: var(--on-surface-variant); opacity: 0.5; user-select: none; border-right: var(--hairline); white-space: pre; }
  .code-pane__content { flex: 1; padding: var(--space-tight) var(--space-gutter); white-space: pre; overflow-x: auto; }
  .code-pane__line--highlight { background: rgb(0 188 212 / 0.1); display: inline-block; width: 100%; border-left: 2px solid var(--accent-cyan); padding-left: 4px; margin-left: -6px; }
`;

function injectStyles() {
  if (document.getElementById('code-pane-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'code-pane-styles';
  styleEl.textContent = codePaneStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
