import { loadIndex, loadOverview, loadMetrics, loadPatchesIndex, loadPatchDetail, loadSnapshotDiff, MissingArtifactError, IndexEntryMissingError } from '../assets/js/ctn-loader.js';
import { formatRelativeTime, formatInt, formatDuration } from '../assets/js/format.js';
import { createStatTile } from '../shared/components/stat-tile.js';
import { createKpiRow } from '../shared/components/kpi-row.js';
import { createTabBar } from '../shared/components/tab-bar.js';
import { createLatencyBar } from '../shared/components/latency-bar.js';
import { createStalenessGauge } from '../shared/components/staleness-gauge.js';
import { createAuditExportButton } from '../shared/components/audit-export.js';

let _activeTab = 'summary';
let _cachedIndexData = null;
let _cachedEntry = null;
let _cachedActiveIndexId = null;

export async function renderOverview(params) {
  const container = document.createElement('div');
  container.className = 'page page--overview';
  container.innerHTML = `
    <div class="panel overview-loading" aria-busy="true">
      <div class="overview-loading__content">
        <svg class="overview-loading__spinner" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/>
        </svg>
        <span>Loading overview…</span>
      </div>
    </div>
  `;

  try {
    const savedIndexId = localStorage.getItem('batho.activeIndexId');
    const indexData = await loadIndex();
    _cachedIndexData = indexData;
    const activeIndexId = savedIndexId && indexData.indexes[savedIndexId]
      ? savedIndexId
      : indexData.currentIndexId;
    _cachedActiveIndexId = activeIndexId;

    const entry = indexData.indexes[activeIndexId];
    if (!entry) throw new IndexEntryMissingError(activeIndexId);
    _cachedEntry = entry;

    const [overviewDoc, metrics] = await Promise.all([
      loadOverview(activeIndexId).catch((err) => {
        if (err.name === 'MissingArtifactError') return null;
        throw err;
      }),
      loadMetrics().catch(() => null),
    ]);

    // Build tab bar
    const tabBar = createTabBar(
      [
        { key: 'summary', label: 'Summary', active: _activeTab === 'summary' },
        { key: 'patches', label: 'Patches', active: _activeTab === 'patches' },
        { key: 'snapshots', label: 'Snapshots', active: _activeTab === 'snapshots' },
      ],
      (key) => {
        _activeTab = key;
        _renderTabContent(container, key, entry, indexData, overviewDoc, metrics, activeIndexId);
      }
    );

    // Build header with icons
    const headerHtml = `
      <div class="overview-header">
        <div class="overview-header__title-row">
          <h1 class="panel__title">
            <svg class="overview-title-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
            Overview
          </h1>
          <span class="overview-header__badge ${entry.stalenessScore > 0.5 ? 'overview-header__badge--warn' : 'overview-header__badge--ok'}">
            ${entry.stalenessScore > 0.5 ? '⚠ stale' : '✓ current'}
          </span>
        </div>
        <div class="overview-meta">
          <span class="overview-meta__icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          </span>
          <span class="overview-meta__root" title="${escapeHtml(entry.root || '')}">${escapeHtml(entry.root || '—')}</span>
          <span class="overview-meta__sep">·</span>
          <span class="overview-meta__icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          </span>
          <span class="overview-meta__time">${formatRelativeTime(entry.timestamp)}</span>
          <span class="overview-meta__sep">·</span>
          <span class="overview-meta__icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
          </span>
          <span class="overview-meta__id">${escapeHtml(activeIndexId.replace(/^batho_/, '').slice(0, 12))}</span>
        </div>
      </div>
    `;

    // Overview missing note
    const overviewMissingNote = overviewDoc
      ? ''
      : `
        <div class="overview-note">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 6px;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          overview.json not found for this index — re-run <code>batho index</code> to generate context artifacts.
        </div>
      `;

    container.innerHTML = `
      <div class="overview">
        <div class="panel">
          ${headerHtml}
          ${overviewMissingNote}
        </div>
        <div id="overview-tab-bar-mount"></div>
        <div id="overview-tab-content"></div>
      </div>
    `;

    const tabBarMount = container.querySelector('#overview-tab-bar-mount');
    if (tabBarMount) tabBarMount.appendChild(tabBar);

    _renderTabContent(container, _activeTab, entry, indexData, overviewDoc, metrics, activeIndexId);

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
        _activeTab = 'summary';
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

// ─── Tab Content Router ──────────────────────────────────────────────────────

function _renderTabContent(container, tabKey, entry, indexData, overviewDoc, metrics, activeIndexId) {
  const mount = container.querySelector('#overview-tab-content');
  if (!mount) return;
  mount.innerHTML = '';

  if (tabKey === 'summary') {
    mount.innerHTML = _renderSummaryTab(entry, overviewDoc, metrics, activeIndexId);
  } else if (tabKey === 'patches') {
    _renderPatchesTab(mount);
  } else if (tabKey === 'snapshots') {
    _renderSnapshotsTab(mount, indexData, activeIndexId);
  }
}

// ─── Summary Tab ─────────────────────────────────────────────────────────────

function _renderSummaryTab(entry, overviewDoc, metrics, activeIndexId) {
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

  return `
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
  `;
}

// ─── Patches Tab ─────────────────────────────────────────────────────────────

async function _renderPatchesTab(mount) {
  mount.innerHTML = `
    <div class="panel patches-loading" aria-busy="true">
      <div class="patches-loading__content">
        <svg class="patches-loading__spinner" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/>
        </svg>
        <span>Loading patches…</span>
      </div>
    </div>
  `;

  try {
    const patchesData = await loadPatchesIndex();
    const patches = patchesData.patches || [];

    if (patches.length === 0) {
      mount.innerHTML = `
        <div class="panel empty-panel">
          <div class="empty-panel__icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </div>
          <div class="empty-panel__title">No patches recorded</div>
          <div class="empty-panel__desc">Run <code>batho patch</code> to create your first patch.</div>
        </div>
      `;
      return;
    }

    // Aggregate KPIs
    const totalPatches = patches.length;
    const avgLatency = patches.reduce((s, p) => s + (p.metrics?.elapsedSeconds ?? 0), 0) / totalPatches;
    const totalFilesChanged = patches.reduce((s, p) => s + (p.metrics?.affectedFiles ?? 0), 0);
    const totalTokens = patches.reduce((s, p) => s + (p.metrics?.tokenSize ?? 0), 0);
    const maxLatency = Math.max(...patches.map((p) => p.metrics?.elapsedSeconds ?? 0));
    const lastPatchTime = patches[0]?.timestamp || '—';

    const kpiTiles = [
      { label: 'TOTAL PATCHES', value: formatInt(totalPatches) },
      { label: 'AVG LATENCY', value: formatDuration(avgLatency) },
      { label: 'FILES CHANGED', value: formatInt(totalFilesChanged) },
      { label: 'TOKEN THROUGHPUT', value: formatInt(totalTokens) },
      { label: 'SUCCESS RATE', value: '100%' },
      { label: 'LAST PATCH', value: formatRelativeTime(lastPatchTime) },
    ];
    const kpiRow = createKpiRow(kpiTiles.map((t) => createStatTile(t)));

    // Timeline
    const sorted = [...patches].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    const timelineHtml = sorted.map((patch) => _renderPatchRow(patch, maxLatency)).join('');

    mount.innerHTML = `
      <div class="kpi-section">${kpiRow.outerHTML}</div>
      <div class="panel">
        <div class="panel__title">Patch Timeline</div>
        <div class="patch-timeline">${timelineHtml}</div>
      </div>
      <div id="patches-audit-mount"></div>
    `;

    // Wire expand/collapse
    mount.querySelectorAll('[data-action="toggle-patch"]').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const opId = e.currentTarget.dataset.operationId;
        const detailEl = mount.querySelector(`[data-patch-detail="${opId}"]`);
        if (!detailEl) return;

        if (detailEl.style.display === 'none') {
          // Load detail if not yet loaded
          if (detailEl.dataset.loaded !== 'true') {
            try {
              const detail = await loadPatchDetail(opId);
              const changes = detail.changesApplied || [];
              detailEl.innerHTML = _renderPatchDetailTable(changes);
              detailEl.dataset.loaded = 'true';
            } catch (err) {
              detailEl.innerHTML = `<div class="empty-state">Failed to load patch detail: ${escapeHtml(err.message)}</div>`;
            }
          }
          detailEl.style.display = 'block';
          e.currentTarget.textContent = 'collapse';
        } else {
          detailEl.style.display = 'none';
          e.currentTarget.textContent = 'expand';
        }
      });
    });

    // Audit export
    const auditMount = mount.querySelector('#patches-audit-mount');
    if (auditMount) {
      auditMount.appendChild(createAuditExportButton(patchesData, 'batho-patches-export'));
    }

  } catch (err) {
    mount.innerHTML = `
      <div class="panel error-panel">
        <div class="error-panel__icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        </div>
        <div class="error-panel__title">Error</div>
        <div class="error-panel__message">${escapeHtml(err.message || 'Failed to load patches')}</div>
      </div>
    `;
  }
}

function _renderPatchRow(patch, maxLatency) {
  const opId = patch.operationId || '';
  const shortId = opId.replace(/^batho_/, '').slice(0, 12);
  const ts = patch.timestamp || '';
  const opType = patch.operationType || 'incremental_patch';
  const metrics = patch.metrics || {};
  const elapsed = metrics.elapsedSeconds ?? 0;
  const added = metrics.addedFiles ?? 0;
  const modified = metrics.modifiedFiles ?? 0;
  const deleted = metrics.deletedFiles ?? 0;
  const tokenSize = metrics.tokenSize ?? 0;
  const affectedFiles = metrics.affectedFiles ?? (added + modified + deleted);

  const typeBadge = opType === 'incremental_patch'
    ? '<span class="change-badge change-badge--patch">incremental</span>'
    : '<span class="change-badge change-badge--reindex">full reindex</span>';

  const latencyBar = createLatencyBar(elapsed, maxLatency, { showValue: true });

  // Only show non-zero deltas; always show modified since that's the common case
  const deltaHtml = [
    added > 0 ? `<span class="delta delta--pos">+${added}</span>` : '',
    modified > 0 ? `<span class="delta delta--mod">~${modified}</span>` : '',
    deleted > 0 ? `<span class="delta delta--neg">-${deleted}</span>` : '',
  ].filter(Boolean).join('') || '<span class="delta delta--neutral">no changes</span>';

  return `
    <article class="patch-row">
      <div class="patch-row__header">
        <div class="patch-row__left">
          <div class="patch-row__id">${escapeHtml(shortId)}</div>
          ${typeBadge}
        </div>
        <div class="patch-row__center">
          <div class="patch-row__latency">${latencyBar.outerHTML}</div>
          <div class="patch-row__stats">
            <span class="patch-row__stat-label">files</span>
            <span class="patch-row__stat-value">${formatInt(affectedFiles)}</span>
          </div>
          <div class="patch-row__stats">
            <span class="patch-row__stat-label">tokens</span>
            <span class="patch-row__stat-value">${formatInt(tokenSize)}</span>
          </div>
          <div class="patch-row__deltas">${deltaHtml}</div>
        </div>
        <div class="patch-row__right">
          <div class="patch-row__time">${formatRelativeTime(ts)}</div>
          <button class="btn btn--ghost patch-row__expand" data-action="toggle-patch" data-operation-id="${escapeAttr(opId)}">expand</button>
        </div>
      </div>
      <div class="patch-row__detail" data-patch-detail="${escapeAttr(opId)}" style="display:none"></div>
    </article>
  `;
}

function _renderPatchDetailTable(changes) {
  if (!changes.length) return '<div class="empty-state">No file changes recorded</div>';
  const rows = changes.map((c) => {
    const typeClass = c.changeType === 'added' ? 'change-badge--added'
      : c.changeType === 'deleted' ? 'change-badge--deleted'
      : 'change-badge--modified';
    return `
      <tr>
        <td class="patch-detail__path">${escapeHtml(c.path || '')}</td>
        <td><span class="change-badge ${typeClass}">${escapeHtml(c.changeType || '')}</span></td>
        <td class="patch-detail__hash">${escapeHtml((c.oldHash || '').slice(0, 8))}…</td>
        <td class="patch-detail__hash">${escapeHtml((c.newHash || '').slice(0, 8))}…</td>
        <td class="num">${formatInt(c.fileSize ?? 0)}</td>
        <td class="patch-detail__mtime">${c.mtime ? formatRelativeTime(c.mtime) : '—'}</td>
      </tr>
    `;
  }).join('');

  return `
    <table class="table patch-detail__table">
      <thead>
        <tr><th>File</th><th>Change</th><th>Old Hash</th><th>New Hash</th><th>Size</th><th>Mtime</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

// ─── Snapshots Tab ───────────────────────────────────────────────────────────

async function _renderSnapshotsTab(mount, indexData, activeIndexId) {
  const indexes = Object.values(indexData.indexes);
  const sorted = [...indexes].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  // Collect unique snapshot IDs from patches index
  let snapshotIds = new Set();
  try {
    const patchesData = await loadPatchesIndex();
    (patchesData.patches || []).forEach((p) => {
      if (p.baseSnapshotId) snapshotIds.add(p.baseSnapshotId);
      if (p.newSnapshotId) snapshotIds.add(p.newSnapshotId);
    });
  } catch (_) { /* ignore */ }

  // Also add snapshot IDs from index entries
  indexes.forEach((e) => {
    if (e.snapshotId) snapshotIds.add(e.snapshotId);
  });

  const snapshotOptions = [...snapshotIds].sort().map((id) => {
    const short = id.replace(/^batho_frontend_/, '').slice(0, 12);
    return `<option value="${escapeAttr(id)}">${escapeHtml(short)}…</option>`;
  }).join('');

  // Staleness for active index
  const activeEntry = indexData.indexes[activeIndexId];
  const stalenessScore = activeEntry?.stalenessScore ?? 0;
  const stalenessGauge = createStalenessGauge(stalenessScore);

  // Compact timeline
  const timelineHtml = sorted.map((entry) => {
    const entryId = entry.indexId || entry.id || '';
    const isActive = entryId === activeIndexId;
    const shortId = entryId.replace(/^batho_/, '').slice(0, 12);
    const staleness = entry.stalenessScore ?? 0;
    const stalenessPct = Math.round(staleness * 100);

    return `
      <div class="snapshot-row ${isActive ? 'snapshot-row--active' : ''}">
        <span class="snapshot-row__marker">${isActive ? '●' : '○'}</span>
        <span class="snapshot-row__id">${escapeHtml(shortId)}</span>
        <span class="snapshot-row__time">${formatRelativeTime(entry.timestamp)}</span>
        <span class="snapshot-row__count">ent ${formatInt(entry.entityCount ?? 0)}</span>
        <div class="snapshot-row__staleness">
          <div class="timeline__staleness-bar"><div class="timeline__staleness-fill" style="width:${stalenessPct}%"></div></div>
          <span>${stalenessPct}%</span>
        </div>
      </div>
    `;
  }).join('');

  mount.innerHTML = `
    <div class="panel">
      <div class="panel__title">Snapshot Comparison</div>
      <div class="snapshot-diff__selectors">
        <div class="snapshot-diff__field">
          <label class="snapshot-diff__label">Base</label>
          <select id="snapshot-base-select" class="snapshot-diff__select">
            <option value="">— select base —</option>
            ${snapshotOptions}
          </select>
        </div>
        <div class="snapshot-diff__arrow">→</div>
        <div class="snapshot-diff__field">
          <label class="snapshot-diff__label">New</label>
          <select id="snapshot-new-select" class="snapshot-diff__select">
            <option value="">— select new —</option>
            ${snapshotOptions}
          </select>
        </div>
        <button class="btn" id="snapshot-diff-btn">Compare</button>
      </div>
      <div id="snapshot-diff-result"></div>
    </div>
    <div class="panel">
      <div class="panel__title">Index Staleness</div>
      <div class="snapshot-staleness-current">
        <span>Active index staleness</span>
        <div id="staleness-gauge-mount"></div>
      </div>
    </div>
    <div class="panel">
      <div class="panel__title">Snapshot Timeline</div>
      <div class="snapshot-timeline">${timelineHtml}</div>
    </div>
    <div id="snapshots-audit-mount"></div>
  `;

  // Mount staleness gauge
  const gaugeMount = mount.querySelector('#staleness-gauge-mount');
  if (gaugeMount) gaugeMount.appendChild(stalenessGauge);

  // Wire compare button
  const diffBtn = mount.querySelector('#snapshot-diff-btn');
  if (diffBtn) {
    diffBtn.addEventListener('click', async () => {
      const baseId = mount.querySelector('#snapshot-base-select')?.value;
      const newId = mount.querySelector('#snapshot-new-select')?.value;
      const resultEl = mount.querySelector('#snapshot-diff-result');
      if (!baseId || !newId || !resultEl) return;

      resultEl.innerHTML = '<div class="loading"><span class="loading__cursor"></span><span>computing diff …</span></div>';

      try {
        const diff = await loadSnapshotDiff(baseId, newId);
        resultEl.innerHTML = _renderSnapshotDiffResult(diff);
      } catch (err) {
        resultEl.innerHTML = `<div class="empty-state">Diff failed: ${escapeHtml(err.message)}</div>`;
      }
    });
  }

  // Audit export
  const auditMount = mount.querySelector('#snapshots-audit-mount');
  if (auditMount) {
    const exportData = {
      indexes: sorted.map((e) => ({
        indexId: e.indexId || e.id,
        timestamp: e.timestamp,
        fileCount: e.fileCount,
        entityCount: e.entityCount,
        stalenessScore: e.stalenessScore,
        snapshotId: e.snapshotId,
      })),
    };
    auditMount.appendChild(createAuditExportButton(exportData, 'batho-snapshots-export'));
  }
}

function _renderSnapshotDiffResult(diff) {
  const entities = diff.entities || {};
  const files = diff.files || {};
  const loc = diff.loc || {};

  const entityDeltaHtml = `
    <div class="snapshot-diff__deltas">
      <span class="delta delta--pos">+${entities.added ?? 0} entities</span>
      <span class="delta delta--mod">~${entities.modified ?? 0} entities</span>
      <span class="delta delta--neg">-${entities.removed ?? 0} entities</span>
      <span class="delta delta--neutral">=${entities.unchanged ?? 0} unchanged</span>
    </div>
  `;

  const fileDeltaHtml = `
    <div class="snapshot-diff__file-delta">
      <span>Files: ${files.baseCount ?? 0} → ${files.newCount ?? 0}</span>
      <span class="delta ${(files.delta ?? 0) >= 0 ? 'delta--pos' : 'delta--neg'}">
        Δ ${files.delta >= 0 ? '+' : ''}${files.delta ?? 0}
      </span>
    </div>
  `;

  const locDeltaHtml = loc.base !== undefined ? `
    <div class="snapshot-diff__loc-delta">
      <span>LOC: ${formatInt(loc.base)} → ${formatInt(loc.new)}</span>
      <span class="delta ${(loc.delta ?? 0) >= 0 ? 'delta--pos' : 'delta--neg'}">
        Δ ${loc.delta >= 0 ? '+' : ''}${loc.delta ?? 0}
      </span>
    </div>
  ` : '';

  // Show sample IDs if available
  const addedIds = entities.addedIds || [];
  const removedIds = entities.removedIds || [];
  const modifiedIds = entities.modifiedIds || [];

  const sampleIdsHtml = (addedIds.length + removedIds.length + modifiedIds.length) > 0 ? `
    <div class="snapshot-diff__samples">
      ${addedIds.length ? `<div class="snapshot-diff__sample-group"><strong>Added:</strong> ${addedIds.slice(0, 10).map((id) => escapeHtml(id)).join(', ')}${addedIds.length > 10 ? ' …' : ''}</div>` : ''}
      ${modifiedIds.length ? `<div class="snapshot-diff__sample-group"><strong>Modified:</strong> ${modifiedIds.slice(0, 10).map((id) => escapeHtml(id)).join(', ')}${modifiedIds.length > 10 ? ' …' : ''}</div>` : ''}
      ${removedIds.length ? `<div class="snapshot-diff__sample-group"><strong>Removed:</strong> ${removedIds.slice(0, 10).map((id) => escapeHtml(id)).join(', ')}${removedIds.length > 10 ? ' …' : ''}</div>` : ''}
    </div>
  ` : '';

  return `
    <div class="snapshot-diff__result">
      ${entityDeltaHtml}
      ${fileDeltaHtml}
      ${locDeltaHtml}
      ${sampleIdsHtml}
    </div>
  `;
}

// ─── Shared Helpers ──────────────────────────────────────────────────────────

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
  if (stack.languages?.length) allChips.push(...stack.languages.map((s) => ({ label: s, type: 'lang', icon: '⌘' })));
  if (stack.frameworks?.length) allChips.push(...stack.frameworks.map((s) => ({ label: s, type: 'fw', icon: '◆' })));
  if (stack.packageManagers?.length) allChips.push(...stack.packageManagers.map((s) => ({ label: s, type: 'pm', icon: '⚡' })));
  if (stack.infra?.length) allChips.push(...stack.infra.map((s) => ({ label: s, type: 'infra', icon: '□' })));
  if (!allChips.length) return '<div class="empty-state"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.5; margin-bottom: 8px;"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg><div>no stack detected</div></div>';
  const chips = allChips.map((c) => `<span class="chip chip--${c.type}"><span class="chip__icon">${c.icon}</span>${escapeHtml(c.label)}</span>`).join('');
  return `<div class="stack-chips">${chips}</div>`;
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
  let icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';

  if (isIndexMissing) {
    title = 'Structural Fault';
    message = 'No index data found. Run <code>batho index</code> first to populate `.ctn/`.';
    icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>';
  } else if (isEntryMissing) {
    title = 'Index Not Found';
    message = `Active index \`${err.id}\` is not present in the registry.`;
    hint = 'Open Snapshots and select another index, or run <code>batho scan</code> to create a new one.';
    icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>';
  } else if (isArtifactMissing) {
    title = 'Missing Artifact';
    message = `Could not load \`${err.path}\`.`;
    hint = 'Re-run <code>batho scan</code> to regenerate context artifacts.';
    icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="18"/></svg>';
  } else if (err && err.name === 'ParseError') {
    title = 'Corrupt Artifact';
    icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
  } else if (err && err.name === 'SchemaMismatchError') {
    title = 'Schema Mismatch';
    icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>';
  }

  const showSnapshotsBtn = isEntryMissing || isIndexMissing;

  return `
    <div class="panel error-panel">
      <div class="error-panel__icon">${icon}</div>
      <div class="error-panel__title">${escapeHtml(title)}</div>
      <div class="error-panel__message">${escapeHtml(message)}</div>
      ${hint ? `<div class="error-panel__hint">${hint}</div>` : ''}
      <div class="error-panel__actions">
        <button class="btn" data-action="retry">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          retry
        </button>
        ${showSnapshotsBtn ? '<button class="btn btn--ghost" data-action="snapshots"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>open snapshots</button>' : ''}
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

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, '&quot;');
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const overviewStyles = `
  .overview { display: flex; flex-direction: column; gap: var(--space-gutter); }
  
  /* Loading states */
  .overview-loading, .patches-loading { display: flex; align-items: center; justify-content: center; min-height: 200px; }
  .overview-loading__content, .patches-loading__content { display: flex; align-items: center; gap: var(--space-gutter); color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); }
  .overview-loading__spinner, .patches-loading__spinner { animation: overview-loading-spin 1s linear infinite; color: var(--secondary); }
  @keyframes overview-loading-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  
  /* Header */
  .overview-header { display: flex; flex-direction: column; gap: var(--space-tight); }
  .overview-header__title-row { display: flex; align-items: center; gap: var(--space-gutter); flex-wrap: wrap; }
  .overview-title-icon { color: var(--primary); opacity: 0.9; }
  .overview-header__badge { font-family: var(--font-mono); font-size: var(--type-terminal-size); padding: 2px 8px; border-radius: 12px; text-transform: lowercase; }
  .overview-header__badge--ok { background: var(--tint-success-15); color: var(--accent-emerald); }
  .overview-header__badge--warn { background: var(--tint-warning-15); color: var(--accent-amber); }
  
  .overview-meta { display: flex; align-items: center; gap: var(--space-tight); font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface-variant); flex-wrap: wrap; }
  .overview-meta__icon { display: flex; align-items: center; opacity: 0.6; }
  .overview-meta__sep { opacity: 0.5; }
  .overview-meta__root { color: var(--tint-on-surface-70); max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .overview-meta__id { color: var(--primary); }
  
  /* Note */
  .overview-note { margin-top: var(--space-tight); padding: var(--space-tight) var(--space-gutter); border-left: 2px solid var(--accent-amber); background: var(--surface-container-low); font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); display: flex; align-items: center; }
  .overview-note code { color: var(--secondary); background: var(--surface-container-high); padding: 1px 4px; border-radius: var(--radius-sm); }
  
  /* Empty panel */
  .empty-panel { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: calc(var(--space-gutter) * 3); text-align: center; }
  .empty-panel__icon { color: var(--on-surface-variant); opacity: 0.4; margin-bottom: var(--space-gutter); }
  .empty-panel__title { font-size: var(--type-section-header-size); font-weight: var(--type-section-header-weight); color: var(--on-surface); margin-bottom: var(--space-tight); }
  .empty-panel__desc { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); }
  .empty-panel__desc code { color: var(--secondary); background: var(--surface-container-high); padding: 2px 6px; border-radius: var(--radius-sm); }
  
  /* Error panel */
  .error-panel { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: calc(var(--space-gutter) * 3); text-align: center; min-height: 300px; }
  .error-panel__icon { color: var(--error); opacity: 0.8; margin-bottom: var(--space-gutter); }
  .error-panel__title { font-size: var(--type-section-header-size); font-weight: var(--type-section-header-weight); color: var(--on-surface); margin-bottom: var(--space-tight); }
  .error-panel__message { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); margin-bottom: var(--space-gutter); max-width: 400px; }
  .error-panel__hint { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-terminal-size); margin-bottom: var(--space-gutter); }
  .error-panel__hint code { color: var(--secondary); background: var(--surface-container-high); padding: 2px 4px; border-radius: var(--radius-sm); }
  .error-panel__actions { display: flex; gap: var(--space-tight); }
  .error-panel__actions .btn { display: inline-flex; align-items: center; gap: 4px; }
  
  .kpi-section { margin: var(--space-gutter) 0; }
  .dist-section { display: flex; flex-direction: column; gap: var(--space-tight); margin-top: var(--space-gutter); }
  .dist-row { display: flex; align-items: center; gap: var(--space-gutter); }
  .dist-row__bar { flex: 1; height: 6px; background: linear-gradient(to right, var(--primary-container) 0% var(--pct), var(--surface-container-high) var(--pct) 100%); border: var(--hairline); border-radius: var(--radius-sm); }
  .dist-row__label { min-width: 120px; font-family: var(--font-mono); font-size: var(--type-node-code-size); color: var(--on-surface-variant); }
  .dist-row__label em { color: var(--on-surface); font-style: normal; }
  .overview-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-gutter); }
  @media (max-width: 900px) { .overview-grid { grid-template-columns: 1fr; } }
  .panel--language .table { margin-top: var(--space-gutter); }
  .panel--stack .stack-chips { display: flex; flex-wrap: wrap; gap: var(--space-tight); margin-top: var(--space-gutter); }
  .chip { display: inline-flex; align-items: center; gap: 4px; font-family: var(--font-mono); font-size: var(--type-terminal-size); padding: 3px 8px; border-radius: 12px; border: var(--hairline); }
  .chip__icon { opacity: 0.7; font-size: 10px; }
  .chip--lang { background: var(--tint-primary-15); border-color: var(--primary-container); }
  .chip--fw { background: rgba(6, 182, 212, 0.15); border-color: var(--secondary-container); }
  .chip--pm { background: var(--tint-warning-15); border-color: var(--accent-amber-dim); }
  .chip--infra { background: var(--tint-success-15); border-color: var(--tertiary-container); }
  .empty-state { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); padding: var(--space-gutter); text-align: center; }
  .empty-state code { color: var(--secondary); }
  .num { text-align: right; }
  .error-panel__hint { color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-terminal-size); margin-top: var(--space-tight); }
  .error-panel__hint code { color: var(--secondary); }

  /* Patch timeline */
  .patch-timeline { display: flex; flex-direction: column; gap: 2px; margin-top: var(--space-gutter); }
  .patch-row { border: var(--hairline); padding: var(--space-pad) var(--space-gutter); background: var(--surface-container-low); transition: background 0.15s; }
  .patch-row:hover { background: var(--surface-container); }
  .patch-row__header { display: flex; align-items: center; gap: var(--space-gutter); min-height: 40px; }
  .patch-row__left { display: flex; align-items: center; gap: var(--space-gutter); min-width: 180px; flex-shrink: 0; }
  .patch-row__id { font-family: var(--font-mono); font-size: var(--type-node-code-size); font-weight: var(--type-node-code-weight); color: var(--on-surface); letter-spacing: 0.02em; }
  .patch-row__center { display: flex; align-items: center; gap: var(--space-gutter); flex: 1; min-width: 0; }
  .patch-row__stats { display: flex; flex-direction: column; align-items: center; gap: 0; }
  .patch-row__stat-label { font-family: var(--font-mono); font-size: 9px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--on-surface-variant); opacity: 0.7; }
  .patch-row__stat-value { font-family: var(--font-mono); font-size: var(--type-node-code-size); font-weight: var(--type-node-code-weight); color: var(--on-surface); }
  .patch-row__deltas { display: flex; gap: var(--space-tight); align-items: center; }
  .patch-row__right { display: flex; align-items: center; gap: var(--space-gutter); margin-left: auto; flex-shrink: 0; }
  .patch-row__time { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); white-space: nowrap; }
  .patch-row__detail { margin-top: var(--space-pad); padding-top: var(--space-pad); border-top: var(--hairline); }

  /* Change badges */
  .change-badge { font-family: var(--font-mono); font-size: 10px; font-weight: var(--type-node-code-weight); text-transform: uppercase; letter-spacing: 0.06em; padding: 2px 8px; border-radius: var(--radius-sm); white-space: nowrap; }
  .change-badge--patch { background: rgba(6, 182, 212, 0.15); color: var(--secondary); }
  .change-badge--reindex { background: var(--tint-primary-15); color: var(--primary); }
  .change-badge--added { background: var(--tint-success-15); color: var(--accent-emerald); }
  .change-badge--modified { background: var(--tint-warning-15); color: var(--accent-amber); }
  .change-badge--deleted { background: var(--tint-error-15); color: #ef4444; }

  /* Delta colors */
  .delta--mod { color: var(--accent-amber); }
  .delta--neutral { color: var(--on-surface-variant); opacity: 0.5; }
  .delta { font-family: var(--font-mono); font-size: var(--type-node-code-size); font-weight: var(--type-node-code-weight); }

  /* Patch detail table */
  .patch-detail__table { margin-top: var(--space-tight); }
  .patch-detail__path { font-family: var(--font-mono); font-size: var(--type-terminal-size); max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .patch-detail__hash { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); }
  .patch-detail__mtime { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); }

  /* Snapshot diff */
  .snapshot-diff__selectors { display: flex; align-items: flex-end; gap: var(--space-gutter); flex-wrap: wrap; margin-top: var(--space-gutter); }
  .snapshot-diff__field { display: flex; flex-direction: column; gap: var(--space-tight); }
  .snapshot-diff__label { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); text-transform: uppercase; letter-spacing: 0.04em; }
  .snapshot-diff__select { font-family: var(--font-mono); font-size: var(--type-node-code-size); background: var(--surface-container); color: var(--on-surface); border: var(--hairline); padding: var(--space-tight); min-width: 200px; }
  .snapshot-diff__arrow { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); padding-bottom: var(--space-tight); }
  .snapshot-diff__result { margin-top: var(--space-gutter); }
  .snapshot-diff__deltas { display: flex; gap: var(--space-gutter); flex-wrap: wrap; margin-bottom: var(--space-tight); }
  .snapshot-diff__file-delta, .snapshot-diff__loc-delta { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); margin-bottom: var(--space-tight); }
  .snapshot-diff__samples { margin-top: var(--space-gutter); }
  .snapshot-diff__sample-group { font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); margin-bottom: var(--space-tight); }
  .snapshot-diff__sample-group strong { color: var(--on-surface); }

  /* Staleness current */
  .snapshot-staleness-current { display: flex; align-items: center; gap: var(--space-gutter); margin-top: var(--space-gutter); font-family: var(--font-mono); font-size: var(--type-terminal-size); color: var(--on-surface-variant); }

  /* Snapshot timeline (compact) */
  .snapshot-timeline { display: flex; flex-direction: column; gap: var(--space-tight); margin-top: var(--space-gutter); }
  .snapshot-row { display: flex; align-items: center; gap: var(--space-gutter); padding: var(--space-tight); border: var(--hairline); font-family: var(--font-mono); font-size: var(--type-node-code-size); }
  .snapshot-row--active { border-color: var(--primary-container); }
  .snapshot-row__marker { color: var(--primary); font-size: 8px; }
  .snapshot-row__id { color: var(--on-surface); font-weight: var(--type-node-code-weight); }
  .snapshot-row__time { color: var(--on-surface-variant); }
  .snapshot-row__count { color: var(--tint-on-surface-70); }
  .snapshot-row__staleness { display: flex; align-items: center; gap: var(--space-tight); margin-left: auto; }
`;

function injectStyles() {
  if (document.getElementById('overview-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'overview-styles';
  styleEl.textContent = overviewStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
