/**
 * Main bootstrap - mounts header, rail, registers routes.
 */

import { router } from './router.js';
import { createHeaderBar } from '../shared/components/header-bar.js';
import { createSideRail } from '../shared/components/side-rail.js';
import { renderOverview } from '../pages/overview.js';
import { renderHypergraph } from '../pages/hypergraph.js';
import { renderFiles } from '../pages/files.js';
import { renderRelationships } from '../pages/relationships.js';
import { renderRules } from '../pages/rules.js';
import { renderSnapshots } from '../pages/snapshots.js';
import { renderMetrics } from '../pages/metrics.js';
import { renderSearch } from '../pages/search.js';

function init() {
  const app = document.getElementById('app');
  if (!app) { console.error('[batho] #app not found'); return; }

  app.className = 'app';

  const header = createHeaderBar({ repoRoot: '…', indexId: '—' });
  header.classList.add('app__header');
  app.appendChild(header);

  const sideRail = createSideRail(router);
  sideRail.classList.add('app__rail');
  app.appendChild(sideRail);

  const main = document.createElement('main');
  main.id = 'page-mount';
  main.className = 'app__main';
  app.appendChild(main);

  const aside = document.createElement('aside');
  aside.id = 'notice-slot';
  aside.setAttribute('aria-live', 'polite');
  aside.setAttribute('aria-atomic', 'true');
  aside.className = 'notice-slot';
  app.appendChild(aside);

  router.register('#/overview', renderOverview);
  router.register('#/hypergraph', renderHypergraph);
  router.register('#/files', renderFiles);
  router.register('#/relationships', renderRelationships);
  router.register('#/rules', renderRules);
  router.register('#/snapshots', renderSnapshots);
  router.register('#/metrics', renderMetrics);
  router.register('#/search', renderSearch);
  router.register('*', async () => {
    const container = document.createElement('div');
    container.className = 'panel panel--stub not-found';
    container.innerHTML = `
      <div class="not-found__code">404</div>
      <div class="not-found__divider"></div>
      <div class="not-found__message">Route is not part of the cockpit.</div>
      <button class="btn" data-navigate="#/overview">return to overview</button>
    `;
    container.querySelector('[data-navigate]').addEventListener('click', () => router.navigate('#/overview'));
    return container;
  });

  router.on('change', ({ path }) => localStorage.setItem('batho.lastRoute', path));

  if (isDevMode()) runTokenDriftCheck();

  router.start();
}

function isDevMode() { return new URLSearchParams(window.location.search).get('dev') === '1'; }

async function runTokenDriftCheck() {
  try {
    const response = await fetch('/dashboard/DESIGN.md');
    if (!response.ok) return;
    const text = await response.text();
    const match = text.match(/^---\n([\s\S]*?)\n---/);
    if (!match) return;
    const yaml = match[1];
    const colorsMatch = yaml.match(/colors:\s*\n((?:\s{2}.+\n?)+)/);
    if (!colorsMatch) return;
    const designColors = {};
    colorsMatch[1].split('\n').forEach(line => { const [key, value] = line.trim().split(/:\s*/); if (key && value) designColors[key] = value; });
    const rootStyles = getComputedStyle(document.documentElement);
    const checkColors = ['surface', 'primary', 'tertiary', 'error'];
    const drift = [];
    checkColors.forEach(color => {
      const cssValue = rootStyles.getPropertyValue(`--${color}`).trim();
      const designValue = designColors[color];
      if (designValue && cssValue.toLowerCase() !== designValue.toLowerCase()) drift.push({ color, css: cssValue, design: designValue });
    });
    if (drift.length > 0) {
      const notice = document.createElement('div');
      notice.className = 'notice notice--warn';
      notice.innerHTML = `<strong>Token Drift Detected:</strong>${drift.map(d => `<br>--${d.color}: ${d.css} (DESIGN: ${d.design})`).join('')}`;
      const slot = document.getElementById('notice-slot');
      if (slot) slot.appendChild(notice);
    }
  } catch (e) { console.warn('[batho] Token drift check failed:', e); }
}

document.addEventListener('DOMContentLoaded', init);
