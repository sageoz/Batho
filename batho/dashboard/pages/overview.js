import { loadIndex, loadOverview, loadMetrics, MissingArtifactError, IndexEntryMissingError } from '../assets/js/ctn-loader.js';
import { formatRelativeTime, formatInt, formatDuration } from '../assets/js/format.js';
import { createStatTile } from '../shared/components/stat-tile.js';
import { createKpiRow } from '../shared/components/kpi-row.js';

export async function renderOverview(params) {
  const container = document.createElement('div');
  container.className = 'page page--overview';
  container.innerHTML = `<div class="panel" aria-busy="true"><div class="loading"><span class="loading__cursor"></span><span>scanning …</span></div></div>`;

  try {
    const savedIndexId = localStorage.getItem('batho.activeIndexId');
    const indexData = await loadIndex();
    const activeIndexId = savedIndexId && indexData.indexes[savedIndexId]
      ? savedIndexId
      : indexData.currentIndexId;

    const entry = indexData.indexes[activeIndexId];
    if (!entry) throw new IndexEntryMissingError(activeIndexId);

    const [overviewDoc, metrics] = await Promise.all([
      loadOverview(activeIndexId).catch((err) => {
        if (err.name === 'MissingArtifactError') return null;
        throw err;
      }),
      loadMetrics().catch(() => null),
    ]);

    const stats = entry.stats || {};
    const rulesStats = stats.rules || {};
    const elapsed = metrics?.stats?.elapsedSeconds ?? stats.elapsedSeconds;
    const errors = metrics?.stats?.errors ?? stats.errors ?? 0;

    const tiles = [
      { label: 'FILES', value: formatInt(entry.fileCount) },
      { label: 'ENTITIES', value: formatInt(entry.entityCount) },
      { label: 'RELATIONSHIPS', value: formatInt(entry.relationshipCount) },
      { label: 'RULES', value: `${rulesStats.rulesLoaded || stats.rulesLoaded || 0}/${rulesStats.rulesApplied || stats.rulesApplied || 0}` },
      { label: 'TAGGED', value: formatInt(stats.entitiesRuleTagged || 0) },
      { label: 'ELAPSED', value: elapsed ? formatDuration(elapsed) : '—' },
      { label: 'ERRORS', value: errors, deltaTone: errors > 0 ? 'warn' : 'neutral' },
    ];

    const kpiRow = createKpiRow(tiles.map((t) => createStatTile(t)));
    const fileDist = overviewDoc?.fileDistribution || [];
    const langs = overviewDoc?.languageBreakdown || [];
    const fileDistHtml = renderFileDistribution(fileDist, entry.fileCount);
    const langBreakdownHtml = renderLanguageBreakdown(langs);
    const stackHtml = renderStackChips(entry.stack || {});
    const overviewMissingNote = overviewDoc
      ? ''
      : '<div class="overview-note">overview.json not found for this index — re-run <code>batho index</code> to generate context artifacts.</div>';

    container.innerHTML = `
      <div class="overview">
        <div class="panel">
          <div class="overview-header">
            <h1 class="panel__title">Overview</h1>
            <div class="overview-meta">
              <span class="overview-meta__root" title="${escapeHtml(entry.root || '')}">${escapeHtml(entry.root || '—')}</span>
              <span class="overview-meta__sep">·</span>
              <span class="overview-meta__time">${formatRelativeTime(entry.timestamp)}</span>
              <span class="overview-meta__sep">·</span>
              <span class="overview-meta__id">idx ${escapeHtml(activeIndexId.replace(/^batho_/, '').slice(0, 8))}…</span>
            </div>
          </div>
          ${overviewMissingNote}
        </div>
        <div class="kpi-section">${kpiRow.outerHTML}</div>
        ${fileDistHtml}
        <div class="overview-grid">
          <div class="panel panel--language">
            <div class="panel__title">Languages</div>
            ${langBreakdownHtml}
          </div>
          <div class="panel panel--stack">
            <div class="panel__title">Stack</div>
            ${stackHtml}
          </div>
        </div>
      </div>
    `;

    const headerBar = document.getElementById('header-bar');
    if (headerBar) {
      const { updateHeaderBar } = await import('../shared/components/header-bar.js');
      updateHeaderBar(headerBar, {
        repoRoot: entry.root,
        indexId: activeIndexId,
        indexes: indexData.indexes,
      });
    }

    if (!container.__indexChangedBound) {
      container.__indexChangedBound = true;
      window.addEventListener('batho:index-changed', async () => {
        const newOverview = await renderOverview(params);
        const mountPoint = document.getElementById('page-mount');
        if (mountPoint) {
          mountPoint.innerHTML = '';
          mountPoint.appendChild(newOverview);
        }
      }, { once: true });
    }
  } catch (err) {
    container.innerHTML = renderErrorPanel(err);
    bindErrorActions(container);
  }
  return container;
}

function renderErrorPanel(err) {
  const isIndexMissing =
    err && err.name === 'MissingArtifactError' && typeof err.path === 'string' &&
    (err.path.endsWith('/.ctn/index.json') || err.path.includes('/indexes'));
  const isEntryMissing = err && err.name === 'IndexEntryMissingError';
  const isArtifactMissing = err && err.name === 'MissingArtifactError' && !isIndexMissing;

  let title = 'Error';
  let message = err?.message || 'An unknown error occurred';
  let hint = '';

  if (isIndexMissing) {
    title = 'Structural Fault';
    message = 'No index data found. Run <code>batho index</code> first to populate `.ctn/`.';
  } else if (isEntryMissing) {
    title = 'Index Not Found';
    message = `Active index \`${err.id}\` is not present in the registry.`;
    hint = 'Open Snapshots and select another index, or run <code>batho scan</code> to create a new one.';
  } else if (isArtifactMissing) {
    title = 'Missing Artifact';
    message = `Could not load \`${err.path}\`.`;
    hint = 'Re-run <code>batho scan</code> to regenerate context artifacts.';
  } else if (err && err.name === 'ParseError') {
    title = 'Corrupt Artifact';
  } else if (err && err.name === 'SchemaMismatchError') {
    title = 'Schema Mismatch';
  }

  const showSnapshotsBtn = isEntryMissing || isCtnIndexMissing;

  return `
    <div class="panel error-panel">
      <div class="error-panel__icon">⚠</div>
      <div class="error-panel__title">${escapeHtml(title)}</div>
      <div class="error-panel__message">${escapeHtml(message)}</div>
      ${hint ? `<div class="error-panel__hint">${hint}</div>` : ''}
      <div class="error-panel__actions">
        <button class="btn" data-action="retry">retry</button>
        ${showSnapshotsBtn ? '<button class="btn btn--ghost" data-action="snapshots">open snapshots</button>' : ''}
      </div>
    </div>
  `;
}

function bindErrorActions(container) {
  const retryBtn = container.querySelector('[data-action="retry"]');
  if (retryBtn) retryBtn.addEventListener('click', () => location.reload());
  const snapBtn = container.querySelector('[data-action="snapshots"]');
  if (snapBtn) snapBtn.addEventListener('click', () => { location.hash = '#/snapshots'; });
}

function renderFileDistribution(distribution, totalFiles) {
  if (!distribution.length) return '';
  const rows = distribution.map((d) => {
    const pct = totalFiles > 0 ? Math.round((d.files / totalFiles) * 100) : d.percent;
    return `
      <div class="dist-row">
        <div class="dist-row__bar" style="--pct: ${pct}%"></div>
        <span class="dist-row__label">${escapeHtml(d.category)} <em>${pct}%</em></span>
      </div>
    `;
  }).join('');
  return `
    <div class="panel">
      <div class="panel__title">File Distribution</div>
      <div class="dist-section">${rows}</div>
    </div>
  `;
}

function renderLanguageBreakdown(languages) {
  if (!languages.length) return '<div class="empty-state">No language data</div>';
  const rows = languages.slice(0, 15).map((l) => `
    <tr>
      <td>${escapeHtml(l.language)}</td>
      <td class="num">${formatInt(l.files)}</td>
      <td class="num">${l.percent.toFixed(1)}%</td>
    </tr>
  `).join('');
  return `
    <table class="table">
      <thead>
        <tr><th>Language</th><th>Files</th><th>%</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderStackChips(stack) {
  const allChips = [];
  if (stack.languages?.length) allChips.push(...stack.languages.map((s) => ({ label: s, type: 'lang' })));
  if (stack.frameworks?.length) allChips.push(...stack.frameworks.map((s) => ({ label: s, type: 'fw' })));
  if (stack.packageManagers?.length) allChips.push(...stack.packageManagers.map((s) => ({ label: s, type: 'pm' })));
  if (stack.infra?.length) allChips.push(...stack.infra.map((s) => ({ label: s, type: 'infra' })));
  if (!allChips.length) return '<div class="empty-state">no stack detected</div>';
  const chips = allChips.map((c) => `<span class="chip chip--${c.type}">${escapeHtml(c.label)}</span>`).join('');
  return `<div class="stack-chips">${chips}</div>`;
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

const overviewStyles = `
  .overview { display: flex; flex-direction: column; gap: var(--space-gutter); }
  .overview-header { display: flex; flex-direction: column; gap: var(--space-tight); }
  .overview-meta { display: flex; align-items: center; gap: var(--space-tight); font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface-variant); flex-wrap: wrap; }
  .overview-meta__sep { opacity: 0.5; }
  .overview-meta__root { color: var(--tint-on-surface-70); max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .overview-meta__id { color: var(--accent-cyan); }
  .overview-note { margin-top: var(--space-tight); padding: var(--space-tight) var(--space-gutter); border-left: 2px solid var(--tertiary); background: var(--surface-container-low); font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); }
  .overview-note code { color: var(--accent-cyan); }
  .kpi-section { margin: var(--space-gutter) 0; }
  .dist-section { display: flex; flex-direction: column; gap: var(--space-tight); margin-top: var(--space-gutter); }
  .dist-row { display: flex; align-items: center; gap: var(--space-gutter); }
  .dist-row__bar { flex: 1; height: 6px; background: linear-gradient(to right, var(--accent-cyan) 0% var(--pct), var(--surface-container-high) var(--pct) 100%); border: var(--hairline); }
  .dist-row__label { min-width: 120px; font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface-variant); }
  .dist-row__label em { color: var(--on-surface); font-style: normal; }
  .overview-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-gutter); }
  @media (max-width: 900px) { .overview-grid { grid-template-columns: 1fr; } }
  .panel--language .table { margin-top: var(--space-gutter); }
  .panel--stack .stack-chips { display: flex; flex-wrap: wrap; gap: var(--space-tight); margin-top: var(--space-gutter); }
  .chip--lang { background: rgb(103 80 164 / 0.2); }
  .chip--fw { background: rgb(77 68 101 / 0.3); }
  .chip--pm { background: rgb(201 122 77 / 0.2); }
  .chip--infra { background: rgb(56 124 100 / 0.2); }
  .empty-state { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); padding: var(--space-gutter); text-align: center; }
  .num { text-align: right; }
  .error-panel__hint { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-terminal-size); margin-top: var(--space-tight); }
  .error-panel__hint code { color: var(--accent-cyan); }
`;

function injectStyles() {
  if (document.getElementById('overview-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'overview-styles';
  styleEl.textContent = overviewStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
