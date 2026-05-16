/**
 * Tab bar component — renders a horizontal tab strip with active state.
 */

export function createTabBar(tabs, onSwitch) {
  const bar = document.createElement('div');
  bar.className = 'tab-bar';

  tabs.forEach((tab, i) => {
    const btn = document.createElement('button');
    btn.className = 'tab-bar__item' + (tab.active ? ' tab-bar__item--active' : '');
    btn.textContent = tab.label;
    btn.dataset.tabKey = tab.key;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-selected', String(!!tab.active));

    btn.addEventListener('click', () => {
      bar.querySelectorAll('.tab-bar__item').forEach((b) => {
        b.classList.remove('tab-bar__item--active');
        b.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('tab-bar__item--active');
      btn.setAttribute('aria-selected', 'true');
      if (onSwitch) onSwitch(tab.key);
    });

    bar.appendChild(btn);
  });

  return bar;
}

const tabBarStyles = `
  .tab-bar {
    display: flex;
    gap: 0;
    border-bottom: var(--hairline);
    margin-bottom: var(--space-gutter);
  }
  .tab-bar__item {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    font-weight: var(--type-node-code-weight);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: var(--space-tight) var(--space-gutter);
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--on-surface-variant);
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }
  .tab-bar__item:hover {
    color: var(--on-surface);
  }
  .tab-bar__item--active {
    color: var(--accent-cyan);
    border-bottom-color: var(--accent-cyan);
  }
`;

function injectStyles() {
  if (document.getElementById('tab-bar-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'tab-bar-styles';
  styleEl.textContent = tabBarStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
