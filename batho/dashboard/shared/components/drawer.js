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
  .drawer__backdrop { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.4); opacity: 0; transition: opacity 0.2s ease; }
  .drawer--open .drawer__backdrop { opacity: 1; }
  .drawer__panel {
    position: absolute; top: 0; right: 0; bottom: 0;
    width: min(420px, 80vw);
    background: var(--surface-container);
    border-left: var(--hairline-strong);
    transform: translateX(100%);
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    display: flex; flex-direction: column;
    overflow: hidden;
  }
  .drawer--open .drawer__panel { transform: translateX(0); }
  .drawer__header {
    display: flex; align-items: center; justify-content: space-between;
    padding: var(--space-gutter) var(--space-pad);
    border-bottom: var(--hairline);
    flex-shrink: 0;
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
    font-size: 18px; color: var(--on-surface-variant);
    padding: var(--space-tight);
    line-height: 1;
    transition: color 0.15s;
  }
  .drawer__close:hover { color: var(--on-surface); }
  .drawer__body {
    flex: 1; overflow-y: auto;
    padding: var(--space-gutter) var(--space-pad);
    font-family: var(--font-mono);
    font-size: var(--type-node-code-size);
    color: var(--on-surface);
  }
  .drawer__body .drawer-prop { display: flex; justify-content: space-between; padding: var(--space-tight) 0; border-bottom: var(--hairline); }
  .drawer__body .drawer-prop__key { color: var(--on-surface-variant); text-transform: uppercase; font-size: var(--type-terminal-size); letter-spacing: 0.04em; }
  .drawer__body .drawer-prop__val { color: var(--on-surface); text-align: right; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .drawer__body .drawer-section { margin-top: var(--space-gutter); }
  .drawer__body .drawer-section__title {
    font-family: var(--font-mono); font-size: var(--type-terminal-size);
    color: var(--accent-cyan); text-transform: uppercase; letter-spacing: 0.06em;
    margin-bottom: var(--space-tight);
  }
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
