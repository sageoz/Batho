/**
 * Side rail component - vertical navigation.
 */

const ROUTES = [
  { path: '#/overview', icon: 'index', label: 'Overview' },
  { path: '#/hypergraph', icon: 'graph', label: 'Hypergraph' },
  { path: '#/files', icon: 'files', label: 'Files' },
  { path: '#/relationships', icon: 'relationships', label: 'Relationships' },
  { path: '#/rules', icon: 'rules', label: 'Rules' },
  { path: '#/snapshots', icon: 'snapshots', label: 'Snapshots' },
  { path: '#/metrics', icon: 'metrics', label: 'Metrics' },
  { path: '#/search', icon: 'search', label: 'Search' },
];

const ICONS = {
  index: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"><rect x="2" y="2" width="12" height="12" rx="0"/><line x1="5" y1="5" x2="11" y2="5"/><line x1="5" y1="8" x2="11" y2="8"/><line x1="5" y1="11" x2="9" y2="11"/></svg>`,
  graph: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"><circle cx="4" cy="4" r="2"/><circle cx="12" cy="4" r="2"/><circle cx="8" cy="12" r="2"/><line x1="5.5" y1="5.5" x2="7.5" y2="10.5"/><line x1="10.5" y1="5.5" x2="8.5" y2="10.5"/></svg>`,
  files: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"><path d="M3 2h6l4 4v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/></svg>`,
  relationships: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"><circle cx="3" cy="8" r="2"/><circle cx="13" cy="8" r="2"/><line x1="5" y1="8" x2="11" y2="8"/><line x1="8" y1="6" x2="8" y2="10"/></svg>`,
  rules: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"><path d="M2 2h12v12H2z"/><line x1="5" y1="5" x2="11" y2="5"/><line x1="5" y1="8" x2="11" y2="8"/><line x1="5" y1="11" x2="9" y2="11"/></svg>`,
  snapshots: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"><circle cx="8" cy="8" r="6"/><line x1="8" y1="2" x2="8" y2="5"/><line x1="8" y1="11" x2="8" y2="14"/><line x1="2" y1="8" x2="5" y2="8"/><line x1="11" y1="8" x2="14" y2="8"/></svg>`,
  metrics: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"><line x1="2" y1="14" x2="2" y2="10"/><line x1="5" y1="14" x2="5" y2="6"/><line x1="8" y1="14" x2="8" y2="8"/><line x1="11" y1="14" x2="11" y2="4"/><line x1="14" y1="14" x2="14" y2="12"/></svg>`,
  search: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"><circle cx="7" cy="7" r="4"/><line x1="10" y1="10" x2="14" y2="14"/></svg>`,
};

export function createSideRail(router) {
  const container = document.createElement('aside');
  container.className = 'side-rail';
  container.id = 'side-rail';
  const nav = document.createElement('nav');
  nav.className = 'side-rail__nav';

  ROUTES.forEach(route => {
    const item = document.createElement('a');
    item.className = 'side-rail__item';
    item.href = route.path;
    item.dataset.route = route.path;
    item.title = route.label;
    item.innerHTML = `<span class="side-rail__icon">${ICONS[route.icon]}</span>`;
    item.addEventListener('click', (e) => { e.preventDefault(); router.navigate(route.path); });
    nav.appendChild(item);
  });

  container.appendChild(nav);
  router.on('change', ({ path }) => {
    container.querySelectorAll('.side-rail__item').forEach(item => {
      item.classList.toggle('side-rail__item--active', item.dataset.route === path);
    });
  });
  return container;
}

const sideRailStyles = `
  .side-rail { display: flex; flex-direction: column; width: 40px; background: var(--surface-container-low); border-right: var(--hairline); }
  .side-rail__nav { display: flex; flex-direction: column; padding: var(--space-tight) 0; }
  .side-rail__item { position: relative; display: flex; align-items: center; justify-content: center; width: 40px; height: 40px; color: var(--on-surface-variant); text-decoration: none; transition: color 0.15s ease; }
  .side-rail__item:hover { color: var(--on-surface); }
  .side-rail__item--active { color: var(--accent-cyan); }
  .side-rail__item--active::before { content: ''; position: absolute; left: 0; top: 50%; transform: translateY(-50%); width: 2px; height: 24px; background: var(--accent-cyan); box-shadow: var(--glow-cyan); }
  .side-rail__icon { width: 16px; height: 16px; }
  .side-rail__icon svg { width: 100%; height: 100%; }
`;

function injectStyles() {
  if (document.getElementById('side-rail-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'side-rail-styles';
  styleEl.textContent = sideRailStyles;
  document.head.appendChild(styleEl);
}

injectStyles();
