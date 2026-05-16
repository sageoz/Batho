/**
 * Staleness gauge component — SVG circular progress ring (0–100%).
 */

export function createStalenessGauge(score, opts = {}) {
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const size = opts.size || 60;
  const stroke = opts.stroke || 5;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pct / 100) * circumference;

  const container = document.createElement('div');
  container.className = 'staleness-gauge';

  const colorClass = pct >= 50 ? 'staleness-gauge--stale' : pct >= 25 ? 'staleness-gauge--warn' : 'staleness-gauge--fresh';

  container.innerHTML = `
    <svg class="staleness-gauge__svg ${colorClass}" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <circle class="staleness-gauge__bg" cx="${size / 2}" cy="${size / 2}" r="${radius}"
        fill="none" stroke="var(--surface-container-high)" stroke-width="${stroke}" />
      <circle class="staleness-gauge__ring" cx="${size / 2}" cy="${size / 2}" r="${radius}"
        fill="none" stroke-width="${stroke}"
        stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
        stroke-linecap="round" transform="rotate(-90 ${size / 2} ${size / 2})" />
    </svg>
    <span class="staleness-gauge__label">${pct}%</span>
  `;

  return container;
}

const stalenessGaugeStyles = `
  .staleness-gauge {
    display: inline-flex;
    align-items: center;
    gap: var(--space-tight);
  }
  .staleness-gauge__svg {
    transform: rotate(0deg);
  }
  .staleness-gauge__ring {
    transition: stroke-dashoffset 0.5s ease;
  }
  .staleness-gauge--fresh .staleness-gauge__ring {
    stroke: var(--accent-cyan);
  }
  .staleness-gauge--warn .staleness-gauge__ring {
    stroke: var(--tertiary);
  }
  .staleness-gauge--stale .staleness-gauge__ring {
    stroke: var(--error);
    animation: pulse-warn 1.6s ease-in-out infinite;
  }
  .staleness-gauge__label {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
  }
`;

function injectStyles() {
  if (document.getElementById('staleness-gauge-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'staleness-gauge-styles';
  styleEl.textContent = stalenessGaugeStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
