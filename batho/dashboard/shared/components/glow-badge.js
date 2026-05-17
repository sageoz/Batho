/**
 * Glow badge component for quality warnings and status indicators.
 * Features pulsing animation for active warnings.
 *
 * Usage:
 *   const badge = createGlowBadge({ variant: 'warning', content: '!', pulse: true });
 *   container.appendChild(badge);
 *
 *   const html = glowBadgeHtml({ variant: 'error', content: '3', size: 'sm' });
 */

/**
 * Create a glow badge element.
 * @param {Object} options
 * @param {string} options.variant - Badge variant: 'info' | 'warning' | 'error' | 'success' | 'pulse'
 * @param {string} options.size - Badge size: 'sm' | 'md' | 'lg'
 * @param {string} options.children - Inner content (HTML string or text)
 * @param {boolean} options.pulse - Whether to apply pulsing animation
 * @returns {HTMLElement} The badge element
 */
export function createGlowBadge({
  variant = 'info',
  size = 'md',
  children = '',
  pulse = false,
} = {}) {
  const badge = document.createElement('span');
  badge.className = `glow-badge glow-badge--${variant} glow-badge--${size}`;
  if (pulse) badge.classList.add('glow-badge--pulse');
  badge.innerHTML = children;
  return badge;
}

/**
 * Generate glow badge HTML string.
 * @param {Object} options
 * @param {string} options.variant - Badge variant
 * @param {string} options.size - Badge size
 * @param {string} options.content - Inner content
 * @param {boolean} options.pulse - Whether to apply pulsing animation
 * @returns {string} HTML string
 */
export function glowBadgeHtml({
  variant = 'info',
  size = 'md',
  content = '',
  pulse = false,
} = {}) {
  const pulseClass = pulse ? ' glow-badge--pulse' : '';
  return `<span class="glow-badge glow-badge--${variant} glow-badge--${size}${pulseClass}">${escapeHtml(String(content))}</span>`;
}

/**
 * Create a glow badge for severity levels.
 * @param {string} severity - 'info' | 'warning' | 'block' | 'error' | 'success'
 * @param {string} content - Badge content
 * @param {Object} options - Additional options
 * @returns {string} HTML string
 */
export function severityBadge(severity, content, options = {}) {
  const variantMap = {
    info: 'info',
    warning: 'warning',
    block: 'error',
    error: 'error',
    success: 'success',
  };
  const variant = variantMap[severity] || 'info';
  return glowBadgeHtml({ variant, content, ...options });
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

const glowBadgeStyles = `
  .glow-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px 8px;
    border-radius: var(--radius-full, 9999px);
    font-family: var(--font-mono, 'JetBrains Mono', monospace);
    font-size: var(--type-terminal-size, 11px);
    font-weight: 500;
    letter-spacing: 0.02em;
    border: 1px solid transparent;
    transition: all var(--transition-base, 150ms ease);
    white-space: nowrap;
  }

  /* Size variants */
  .glow-badge--sm { padding: 1px 6px; font-size: 10px; }
  .glow-badge--md { padding: 2px 8px; font-size: 11px; }
  .glow-badge--lg { padding: 4px 12px; font-size: 12px; }

  /* Info variant - Indigo */
  .glow-badge--info {
    background: rgb(79 70 229 / 0.15);
    color: #c3c0ff;
    border-color: rgb(79 70 229 / 0.3);
    box-shadow: 0 0 6px rgb(79 70 229 / 0.2);
  }

  /* Warning variant - Amber */
  .glow-badge--warning {
    background: rgb(245 158 11 / 0.15);
    color: #fbbf24;
    border-color: rgb(245 158 11 / 0.3);
    box-shadow: 0 0 6px rgb(245 158 11 / 0.2);
  }

  /* Error variant - Red */
  .glow-badge--error {
    background: rgb(239 68 68 / 0.15);
    color: #f87171;
    border-color: rgb(239 68 68 / 0.3);
    box-shadow: 0 0 6px rgb(239 68 68 / 0.2);
  }

  /* Success variant - Emerald */
  .glow-badge--success {
    background: rgb(16 185 129 / 0.15);
    color: #34d399;
    border-color: rgb(16 185 129 / 0.3);
    box-shadow: 0 0 6px rgb(16 185 129 / 0.2);
  }

  /* Pulse variant - Amber with stronger glow */
  .glow-badge--pulse {
    background: rgb(245 158 11 / 0.2);
    color: #fbbf24;
    border-color: rgb(245 158 11 / 0.4);
    box-shadow: 0 0 8px rgb(245 158 11 / 0.3);
  }

  /* Pulsing animation */
  .glow-badge--pulse.glow-badge--pulse {
    animation: glow-pulse 2s ease-in-out infinite;
  }

  @keyframes glow-pulse {
    0%, 100% {
      box-shadow: 0 0 6px rgb(245 158 11 / 0.3);
      transform: scale(1);
    }
    50% {
      box-shadow: 0 0 12px rgb(245 158 11 / 0.6);
      transform: scale(1.02);
    }
  }

  /* Hover effects */
  .glow-badge:hover {
    filter: brightness(1.1);
  }

  /* Active/pressed state */
  .glow-badge:active {
    transform: scale(0.98);
  }

  /* High contrast mode support */
  @media (prefers-contrast: high) {
    .glow-badge {
      border-width: 2px;
    }
  }

  /* Reduced motion support */
  @media (prefers-reduced-motion: reduce) {
    .glow-badge--pulse {
      animation: none;
    }
  }
`;

function injectStyles() {
  if (document.getElementById('glow-badge-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'glow-badge-styles';
  styleEl.textContent = glowBadgeStyles;
  document.head.appendChild(styleEl);
}

injectStyles();
