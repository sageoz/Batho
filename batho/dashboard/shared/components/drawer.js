/**
 * Right-side detail drawer component.
 * Slides in from the right edge to show entity detail, neighbours, etc.
 *
 * Usage:
 *   const drawer = createDrawer();
 *   document.body.appendChild(drawer);
 *   openDrawer(drawer, { title: 'Entity Detail', content: '<p>...</p>' });
 *   closeDrawer(drawer);
 */

export function createDrawer() {
  const drawer = document.createElement('div');
  drawer.className = 'drawer';
  drawer.setAttribute('role', 'dialog');
  drawer.setAttribute('aria-hidden', 'true');
  drawer.innerHTML = `
    <div class="drawer__backdrop"></div>
    <div class="drawer__panel">
      <div class="drawer__header">
        <h2 class="drawer__title"></h2>
        <button class="drawer__close" aria-label="Close drawer">&times;</button>
      </div>
      <div class="drawer__body"></div>
    </div>
  `;

  drawer.querySelector('.drawer__close').addEventListener('click', () => closeDrawer(drawer));
  drawer.querySelector('.drawer__backdrop').addEventListener('click', () => closeDrawer(drawer));

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && drawer.classList.contains('drawer--open')) {
      closeDrawer(drawer);
    }
  });

  return drawer;
}

export function openDrawer(drawer, { title = '', content = '' } = {}) {
  const titleEl = drawer.querySelector('.drawer__title');
  const bodyEl = drawer.querySelector('.drawer__body');
  if (titleEl) titleEl.textContent = title;
  if (bodyEl) bodyEl.innerHTML = content;
  drawer.classList.add('drawer--open');
  drawer.setAttribute('aria-hidden', 'false');
}

export function closeDrawer(drawer) {
  drawer.classList.remove('drawer--open');
  drawer.setAttribute('aria-hidden', 'true');
}

const drawerStyles = `
  .drawer { position: fixed; inset: 0; z-index: 2000; pointer-events: none; }
  .drawer--open { pointer-events: auto; }
  .drawer__backdrop { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.5); opacity: 0; transition: opacity 0.25s ease; }
  .drawer--open .drawer__backdrop { opacity: 1; }
  .drawer__panel {
    position: absolute; top: 0; right: 0; bottom: 0;
    width: min(420px, 85vw);
    background: var(--surface-container);
    border-left: var(--hairline-strong);
    box-shadow: -4px 0 24px rgba(0, 0, 0, 0.4);
    transform: translateX(100%);
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    display: flex; flex-direction: column;
    overflow: hidden;
  }
  .drawer--open .drawer__panel { transform: translateX(0); }
  .drawer__header {
    display: flex; align-items: center; justify-content: space-between;
    padding: var(--space-gutter) var(--space-pad);
    border-bottom: var(--hairline);
    flex-shrink: 0;
    background: linear-gradient(180deg, var(--surface-container-high) 0%, var(--surface-container) 100%);
  }
  .drawer__title {
    font-family: var(--font-mono);
    font-size: var(--type-heading-glyph-size);
    font-weight: var(--type-heading-glyph-weight);
    letter-spacing: var(--type-heading-glyph-tracking);
    text-transform: uppercase;
    color: var(--on-surface);
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .drawer__close {
    background: none; border: none; cursor: pointer;
    font-size: 20px; color: var(--on-surface-variant);
    padding: var(--space-tight);
    line-height: 1;
    transition: color 0.15s, transform 0.15s;
    border-radius: 4px;
  }
  .drawer__close:hover { color: var(--on-surface); transform: scale(1.1); background: var(--surface-container-high); }
  .drawer__body {
    flex: 1; overflow-y: auto;
    padding: 0;
    font-family: var(--font-mono);
    font-size: var(--type-node-code-size);
    color: var(--on-surface);
  }

  /* Legacy drawer property styles (keep for backwards compatibility) */
  .drawer__body .drawer-prop { display: flex; justify-content: space-between; padding: var(--space-tight) 0; border-bottom: var(--hairline); }
  .drawer__body .drawer-prop__key { color: var(--on-surface-variant); text-transform: uppercase; font-size: var(--type-terminal-size); letter-spacing: 0.04em; }
  .drawer__body .drawer-prop__val { color: var(--on-surface); text-align: right; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .drawer__body .drawer-section { margin-top: 0; }
  .drawer__body .drawer-section__title {
    font-family: var(--font-mono); font-size: var(--type-terminal-size);
    color: var(--accent-cyan); text-transform: uppercase; letter-spacing: 0.06em;
    margin-bottom: var(--space-tight);
  }

  /* New enhanced drawer styles */
  .drawer-section { padding: var(--space-pad); border-bottom: var(--hairline); }
  .drawer-section:last-child { border-bottom: none; }

  /* Identity section */
  .drawer-section--identity { background: linear-gradient(135deg, var(--surface-container-high) 0%, var(--surface-container) 100%); }
  .drawer-identity { display: flex; align-items: flex-start; gap: 12px; }
  .drawer-identity__icon { font-size: 32px; line-height: 1; filter: grayscale(0.2); }
  .drawer-identity__info { flex: 1; min-width: 0; }
  .drawer-identity__name {
    font-family: var(--font-mono);
    font-size: 16px;
    font-weight: 600;
    color: var(--on-surface);
    word-break: break-all;
    line-height: 1.3;
    margin-bottom: 4px;
  }
  .drawer-identity__type {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  /* Stats grid */
  .drawer-section--stats { background: var(--surface-container-low); }
  .drawer-stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
    gap: var(--space-gutter);
  }
  .drawer-stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 8px;
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: 4px;
  }
  .drawer-stat__value {
    font-family: var(--font-mono);
    font-size: 20px;
    font-weight: 600;
    color: var(--accent-cyan);
  }
  .drawer-stat__label {
    font-family: var(--font-mono);
    font-size: 9px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 2px;
  }

  /* File property with action */
  .drawer-prop--file {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px;
    background: var(--surface-container-low);
    border-radius: 4px;
  }
  .drawer-prop__val--file {
    flex: 1;
    font-family: var(--font-mono);
    font-size: var(--type-node-code-size);
    color: var(--on-surface);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .drawer-prop__action {
    background: var(--surface-container-high);
    border: var(--hairline);
    color: var(--on-surface-variant);
    padding: 4px 8px;
    font-size: 14px;
    cursor: pointer;
    border-radius: 3px;
    transition: all 0.15s;
  }
  .drawer-prop__action:hover {
    background: var(--accent-cyan);
    color: var(--surface);
    border-color: var(--accent-cyan);
  }

  /* Metadata grid */
  .drawer-metadata {
    display: grid;
    grid-template-columns: 1fr;
    gap: 4px;
  }
  .drawer-metadata__item {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 4px 0;
  }
  .drawer-metadata__key {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    flex-shrink: 0;
  }
  .drawer-metadata__key::after { content: ':'; }
  .drawer-metadata__val {
    font-family: var(--font-mono);
    font-size: var(--type-node-code-size);
    color: var(--on-surface);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Actions */
  .drawer-section--actions { background: var(--surface-container-low); padding-top: var(--space-gutter); padding-bottom: var(--space-gutter); }
  .drawer-actions { display: flex; flex-direction: column; gap: 8px; }
  .drawer-action {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 10px 16px;
    font-family: var(--font-mono);
    font-size: var(--type-node-code-size);
    font-weight: 500;
    color: var(--on-surface);
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .drawer-action:hover {
    background: var(--surface-container-high);
    border-color: var(--accent-cyan);
    color: var(--accent-cyan);
    transform: translateY(-1px);
  }
  .drawer-action--primary {
    background: linear-gradient(135deg, var(--primary-container) 0%, var(--surface-container-high) 100%);
    border-color: var(--primary);
    color: var(--on-primary-container);
    font-weight: 600;
  }
  .drawer-action--primary:hover {
    background: var(--primary-container);
    border-color: var(--accent-cyan);
    box-shadow: 0 2px 8px rgba(125, 249, 255, 0.2);
  }
  .drawer-action--source {
    background: linear-gradient(135deg, rgba(96, 165, 250, 0.15) 0%, var(--surface-container) 100%);
    border-color: rgba(96, 165, 250, 0.5);
    color: #60a5fa;
  }
  .drawer-action--source:hover {
    background: rgba(96, 165, 250, 0.25);
    border-color: #60a5fa;
    color: #93c5fd;
    box-shadow: 0 2px 8px rgba(96, 165, 250, 0.15);
  }

  /* Hint at bottom */
  .drawer-hint {
    padding: var(--space-gutter) var(--space-pad);
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    text-align: center;
    background: var(--surface-container-lowest);
    border-top: var(--hairline);
  }
  .drawer-hint kbd {
    display: inline-block;
    padding: 1px 6px;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--accent-cyan);
    background: var(--surface-container);
    border: 1px solid var(--outline-variant);
    border-radius: 3px;
  }

  /* Legacy neighbour styles (keep for backwards compatibility) */
  .drawer__body .drawer-neighbour {
    display: flex; align-items: center; gap: var(--space-tight);
    padding: var(--space-tight) 0; border-bottom: var(--hairline);
    font-size: var(--type-node-code-size);
  }
  .drawer__body .drawer-neighbour__type {
    font-size: var(--type-terminal-size); text-transform: uppercase;
    padding: 1px 4px; border-radius: 2px; opacity: 0.7;
  }

  @media (prefers-reduced-motion: reduce) {
    .drawer__backdrop { transition: none; }
    .drawer__panel { transition: none; }
    .drawer-action, .drawer-prop__action { transition: none; }
  }
`;

function injectStyles() {
  if (document.getElementById('drawer-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'drawer-styles';
  styleEl.textContent = drawerStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
