/**
 * Latency bar component — inline proportional bar visualizing a duration.
 */

export function createLatencyBar(value, max, opts = {}) {
  // Use a floor of 10s so a single fast patch doesn't show 100%
  const effectiveMax = Math.max(max || 0, 10);
  const pct = effectiveMax > 0 ? Math.min(100, Math.round((value / effectiveMax) * 100)) : 0;

  // Color by threshold: <2s green, <10s cyan, >=10s amber
  const tone = value < 2 ? 'fast' : value < 10 ? 'normal' : 'slow';

  const container = document.createElement('div');
  container.className = 'latency-bar';
  container.dataset.tone = tone;

  const fill = document.createElement('div');
  fill.className = 'latency-bar__fill';
  fill.style.width = `${pct}%`;
  container.appendChild(fill);

  if (opts.showValue) {
    const label = document.createElement('span');
    label.className = 'latency-bar__value';
    label.textContent = value < 1 ? `${Math.round(value * 1000)}ms` : `${value.toFixed(1)}s`;
    container.appendChild(label);
  }

  return container;
}

const latencyBarStyles = `
  .latency-bar {
    display: inline-flex;
    align-items: center;
    gap: var(--space-tight);
    width: 120px;
    height: 4px;
    background: var(--surface-container-high);
    border-radius: 2px;
    position: relative;
    flex-shrink: 0;
  }
  .latency-bar__fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.3s ease;
  }
  .latency-bar[data-tone="fast"] .latency-bar__fill { background: #4caf50; }
  .latency-bar[data-tone="normal"] .latency-bar__fill { background: var(--accent-cyan); }
  .latency-bar[data-tone="slow"] .latency-bar__fill { background: #ffc107; }
  .latency-bar__value {
    position: absolute;
    right: -48px;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    white-space: nowrap;
  }
`;

function injectStyles() {
  if (document.getElementById('latency-bar-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'latency-bar-styles';
  styleEl.textContent = latencyBarStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
