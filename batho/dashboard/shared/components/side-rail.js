/**
 * Side rail component - vertical navigation.
 */

const ROUTES = [
  { path: '#/overview', icon: 'index', label: 'Overview', group: 'nav' },
  // Hypergraph nav target points at L1 directly; the `activePrefix` is used
  // by the highlight logic so L2/L3 routes (e.g. `#/hypergraph/file/...`)
  // also light up this rail item.
  { path: '#/hypergraph/files', icon: 'graph', label: 'Hypergraph', group: 'nav', activePrefix: '#/hypergraph' },
  { path: '#/files', icon: 'files', label: 'Files', group: 'nav' },
  { path: '#/relationships', icon: 'relationships', label: 'Relationships', group: 'nav' },
  { path: '#/plugins', icon: 'plugins', label: 'Plugins', group: 'tools' },
  { path: '#/metrics', icon: 'metrics', label: 'Metrics', group: 'tools' },
  { path: '#/snapshots', icon: 'snapshots', label: 'Snapshots', group: 'tools' },
  { path: '#/search', icon: 'search', label: 'Search', group: 'tools' },
  { path: '#/mcp', icon: 'mcp', label: 'MCP', group: 'tools' },
];

const ICONS = {
  index: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="8" y1="8" x2="16" y2="8"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="13" y2="16"/></svg>`,
  graph: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><path d="M8.5 8.5l2.5 7.5"/><path d="M15.5 8.5l-2.5 7.5"/></svg>`,
  files: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`,
  relationships: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="12" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="19" cy="19" r="3"/><line x1="8" y1="12" x2="16" y2="7"/><line x1="8" y1="12" x2="16" y2="17"/></svg>`,
  plugins: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>`,
  snapshots: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
  metrics: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`,
  search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
  mcp: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6"/><path d="M9 13h6"/><path d="M9 17h4"/></svg>`,
};

export function createSideRail(router) {
  const container = document.createElement('aside');
  container.className = 'side-rail';
  container.id = 'side-rail';
  container.setAttribute('role', 'navigation');
  container.setAttribute('aria-label', 'Primary');

  // Brand mark at top
  const brand = document.createElement('div');
  brand.className = 'side-rail__brand';
  brand.innerHTML = `<img src="/dashboard/assets/img/batho-logo.svg" alt="Batho" width="32" height="32" class="side-rail__brand-logo" />`;
  brand.setAttribute('role', 'link');
  brand.setAttribute('aria-label', 'Batho — Overview');
  brand.setAttribute('tabindex', '0');
  brand.addEventListener('click', () => router.navigate('#/overview'));
  brand.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      router.navigate('#/overview');
    }
  });
  container.appendChild(brand);

  const nav = document.createElement('nav');
  nav.className = 'side-rail__nav';
  nav.setAttribute('aria-label', 'Primary pages');

  let currentGroup = null;
  let groupEl = null;

  ROUTES.forEach((route, index) => {
    // Insert group dividers
    if (route.group !== currentGroup) {
      currentGroup = route.group;
      if (index > 0) {
        const divider = document.createElement('div');
        divider.className = 'side-rail__divider';
        nav.appendChild(divider);
      }
      groupEl = document.createElement('div');
      groupEl.className = 'side-rail__group';
      nav.appendChild(groupEl);
    }

    const item = document.createElement('a');
    item.className = 'side-rail__item';
    item.href = route.path;
    item.dataset.route = route.path;
    if (route.activePrefix) item.dataset.activePrefix = route.activePrefix;
    item.setAttribute('role', 'link');
    item.setAttribute('aria-label', route.label);
    item.setAttribute('tabindex', '0');
    item.innerHTML = `
      <span class="side-rail__icon">${ICONS[route.icon]}</span>
      <span class="side-rail__label">${route.label}</span>
    `;
    item.addEventListener('click', (e) => { e.preventDefault(); router.navigate(route.path); });
    item.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        router.navigate(route.path);
      }
    });
    groupEl.appendChild(item);
  });

  container.appendChild(nav);

  // Keyboard navigation for the rail
  container.addEventListener('keydown', (e) => {
    const items = Array.from(container.querySelectorAll('.side-rail__item'));
    const current = document.activeElement;
    const idx = items.indexOf(current);
    if (idx === -1) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = items[Math.min(idx + 1, items.length - 1)];
      next.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = items[Math.max(idx - 1, 0)];
      prev.focus();
    } else if (e.key === 'Home') {
      e.preventDefault();
      items[0]?.focus();
    } else if (e.key === 'End') {
      e.preventDefault();
      items[items.length - 1]?.focus();
    }
  });

  router.on('change', ({ path }) => {
    container.querySelectorAll('.side-rail__item').forEach(item => {
      const prefix = item.dataset.activePrefix;
      const active = prefix
        ? (path === prefix || path.startsWith(prefix + '/'))
        : item.dataset.route === path;
      item.classList.toggle('side-rail__item--active', active);
      item.setAttribute('aria-current', active ? 'page' : 'false');
    });
  });
  return container;
}

const sideRailStyles = `
  .side-rail {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 72px;
    min-width: 72px;
    background: var(--surface-container-low);
    border-right: var(--hairline);
    padding: var(--space-md) 0 var(--space-md);
    gap: var(--space-md);
    overflow-y: auto;
    overflow-x: hidden;
    scrollbar-width: none;
    -ms-overflow-style: none;
  }
  .side-rail::-webkit-scrollbar { display: none; }

  /* Brand mark */
  .side-rail__brand {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    cursor: pointer;
    transition: all 0.15s ease;
    flex-shrink: 0;
    border-radius: var(--radius-md);
  }
  .side-rail__brand:hover { transform: scale(1.08); filter: drop-shadow(0 0 8px rgba(34, 211, 238, 0.35)); }
  .side-rail__brand:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--accent-cyan); }
  .side-rail__brand-logo {
    width: 36px;
    height: 36px;
    display: block;
  }

  /* Navigation */
  .side-rail__nav {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
    gap: var(--space-xs);
    flex: 1;
    min-height: 0;
  }

  .side-rail__group {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
    gap: var(--space-xs);
  }

  .side-rail__divider {
    width: 24px;
    height: 1px;
    background: var(--outline-variant);
    opacity: 0.5;
    margin: var(--space-xs) 0;
    flex-shrink: 0;
  }

  .side-rail__item {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 52px;
    color: var(--on-surface-variant);
    text-decoration: none;
    transition: all 0.15s ease;
    gap: var(--space-xs);
    border-radius: var(--radius-md);
    cursor: pointer;
    flex-shrink: 0;
  }
  .side-rail__item:hover {
    color: var(--on-surface);
    background: var(--surface-container-high);
  }
  .side-rail__item:focus-visible {
    outline: none;
    box-shadow: 0 0 0 2px var(--accent-cyan);
  }
  .side-rail__item--active {
    color: var(--accent-cyan);
    background: rgb(6 182 212 / 0.08);
  }
  .side-rail__item--active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    width: 3px;
    height: 28px;
    background: var(--accent-cyan);
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    box-shadow: var(--glow-cyan);
  }

  .side-rail__icon {
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .side-rail__icon svg { width: 100%; height: 100%; }

  .side-rail__label {
    font-family: var(--font-sans);
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.02em;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 52px;
    line-height: 1.2;
  }
`;

function injectStyles() {
  if (document.getElementById('side-rail-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'side-rail-styles';
  styleEl.textContent = sideRailStyles;
  document.head.appendChild(styleEl);
}

injectStyles();
