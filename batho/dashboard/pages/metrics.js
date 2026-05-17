/**
 * Metrics page - comprehensive analytics dashboard for codebase metrics.
 * Features KPI cards, trend charts, and detailed performance breakdowns.
 */

import { loadIndex, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { formatInt, formatRelativeTime, formatDuration, formatBytes } from '../assets/js/format.js';

// Cache for patches data
let patchesCache = null;

// Cache for historical data
let metricsCache = null;

export async function renderMetrics(params) {
  const container = document.createElement('div');
  container.className = 'page page--metrics';
  container.innerHTML = `<div class="panel" aria-busy="true"><div class="loading"><span class="loading__cursor"></span><span>loading metrics …</span></div></div>`;

  try {
    const indexData = await loadIndex();
    const indexes = Object.values(indexData.indexes);

    if (indexes.length === 0) {
      container.innerHTML = `
        <div class="panel">
          <div class="panel__title">Metrics</div>
          <div class="empty-state">No metrics available. Run <code>batho scan</code> to generate data.</div>
        </div>
      `;
      return container;
    }

    // Sort indexes by timestamp (newest first)
    const sortedIndexes = [...indexes].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    const currentIndex = sortedIndexes[0];
    const stats = currentIndex.stats || {};
    const rules = stats.rules || {};

    // Calculate historical trends
    const trends = calculateTrends(sortedIndexes);

    // Calculate language distribution from stack
    const stack = currentIndex.stack || {};
    const languages = stack.languages || [];
    const frameworks = stack.frameworks || [];

    // Load patches data
    const patchesData = await loadPatches();
    const patchMetrics = calculatePatchMetrics(patchesData);
    const snapshotMetrics = calculateSnapshotMetrics(sortedIndexes, patchesData);

    // Entity density (entities per file)
    const entityDensity = currentIndex.fileCount > 0
      ? (currentIndex.entityCount / currentIndex.fileCount).toFixed(1)
      : '0';

    // Relationship density (relationships per entity)
    const relationshipDensity = currentIndex.entityCount > 0
      ? (currentIndex.relationshipCount / currentIndex.entityCount).toFixed(1)
      : '0';

    container.innerHTML = `
      <div class="metrics-page">
        <!-- Enhanced Header with Actions -->
        <div class="panel metrics-header-panel">
          <div class="metrics-header">
            <div class="metrics-title-group">
              <h1 class="panel__title">
                <svg class="metrics-title-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 20V10M12 20V4M6 20v-6"/>
                </svg>
                Metrics Dashboard
              </h1>
              <div class="metrics-subtitle">
                Real-time insights into your codebase health and performance
              </div>
            </div>
            <div class="metrics-actions">
              <div class="metrics-meta">
                <span class="meta-badge meta-badge--live">
                  <span class="live-dot"></span> Live
                </span>
                <span class="meta-sep">·</span>
                <span class="meta-item">Index: <strong class="meta-index-id">${formatShortId(currentIndex.indexId || currentIndex.id)}</strong></span>
                <span class="meta-sep">·</span>
                <span class="meta-item" title="${currentIndex.timestamp}">${formatRelativeTime(currentIndex.timestamp)}</span>
              </div>
              <button class="btn btn--refresh" id="refresh-metrics" title="Refresh data">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                </svg>
                Refresh
              </button>
            </div>
          </div>
        </div>

        <!-- KPI Cards Grid with Sparklines -->
        <div class="metrics-section">
          <div class="section-header">
            <h2 class="section-title">Key Performance Indicators</h2>
            <div class="section-actions">
              <button class="chip chip--active" data-view="all">All</button>
              <button class="chip" data-view="code">Code</button>
              <button class="chip" data-view="performance">Perf</button>
            </div>
          </div>
          <div class="metrics-kpi-grid">
            ${renderKpiCard({
              label: 'Total Entities',
              value: formatInt(currentIndex.entityCount || 0),
              trend: trends.entityTrend,
              trendValue: trends.entityDelta,
              color: 'primary',
              iconSvg: ICONS.hexagon,
              sparkline: generateSparkline(sortedIndexes.slice(0, 7).reverse().map(i => i.entityCount || 0)),
              description: 'Classes, functions, variables, and other code elements'
            })}
            ${renderKpiCard({
              label: 'Relationships',
              value: formatInt(currentIndex.relationshipCount || 0),
              trend: trends.relationshipTrend,
              trendValue: trends.relationshipDelta,
              color: 'info',
              iconSvg: ICONS.gitBranch,
              sparkline: generateSparkline(sortedIndexes.slice(0, 7).reverse().map(i => i.relationshipCount || 0)),
              description: 'Calls, imports, inheritance, and other connections'
            })}
            ${renderKpiCard({
              label: 'Files Parsed',
              value: formatInt(stats.filesParsed || currentIndex.fileCount || 0),
              subtitle: `of ${formatInt(stats.filesCandidates || currentIndex.fileCount || 0)} candidates`,
              color: 'success',
              iconSvg: ICONS.fileCode,
              progress: stats.filesCandidates ? (stats.filesParsed / stats.filesCandidates) : 1,
              description: 'Source files successfully analyzed'
            })}
            ${renderKpiCard({
              label: 'Scan Duration',
              value: formatDuration(stats.elapsedSeconds || 0),
              subtitle: `${formatInt(stats.workersUsed || 1)} workers`,
              color: 'amber',
              iconSvg: ICONS.zap,
              description: 'Time to complete last codebase scan'
            })}
            ${renderKpiCard({
              label: 'Entity Density',
              value: entityDensity,
              subtitle: 'entities per file',
              color: 'purple',
              iconSvg: ICONS.target,
              description: 'Average complexity per source file'
            })}
            ${renderKpiCard({
              label: 'Rules Applied',
              value: formatInt(rules.rulesApplied || 0),
              subtitle: `of ${formatInt(rules.rulesLoaded || 0)} loaded`,
              trend: rules.rulesApplied > 0 ? 'up' : 'neutral',
              color: 'cyan',
              iconSvg: ICONS.settings,
              description: 'BSG rules that matched and transformed code'
            })}
          </div>
        </div>

        <!-- Charts Row -->
        <div class="metrics-section">
          <div class="section-header">
            <h2 class="section-title">Trends & Distribution</h2>
          </div>
          <div class="metrics-charts-row">
            <!-- Historical Trend Chart -->
            <div class="panel metrics-chart-panel metrics-chart-panel--large">
              <div class="panel__header">
                <div class="panel__title">Historical Trends</div>
                <div class="panel__actions">
                  <button class="chart-toggle chart-toggle--active" data-metric="entities">Entities</button>
                  <button class="chart-toggle" data-metric="relationships">Relationships</button>
                  <button class="chart-toggle" data-metric="files">Files</button>
                </div>
              </div>
              <div class="metrics-chart" id="trend-chart">
                ${renderTrendChart(sortedIndexes.slice(0, 10).reverse())}
              </div>
              <div class="chart-insight">
                ${trends.entityTrend === 'up' ? '📈 Entity count is growing' : trends.entityTrend === 'down' ? '📉 Entity count is declining' : '➡️ Entity count is stable'}
                ${trends.entityDelta ? `by ${trends.entityDelta} since last scan` : ''}
              </div>
            </div>

            <!-- Language Distribution -->
            <div class="panel metrics-chart-panel metrics-chart-panel--narrow">
              <div class="panel__header">
                <div class="panel__title">Languages</div>
                <span class="panel__badge">${languages.length}</span>
              </div>
              <div class="metrics-distribution">
                ${languages.length > 0 ? languages.map((lang, i) => `
                  <div class="distribution-row" style="animation-delay: ${i * 50}ms">
                    <div class="distribution-info">
                      <span class="distribution-icon" style="color: ${getLanguageColor(lang)}">●</span>
                      <span class="distribution-label">${escapeHtml(lang)}</span>
                    </div>
                    <div class="distribution-bar-container">
                      <div class="distribution-bar">
                        <div class="distribution-bar__fill" style="width: 100%; background: ${getLanguageColor(lang)}; animation-delay: ${i * 100}ms"></div>
                      </div>
                    </div>
                  </div>
                `).join('') : `
                  <div class="empty-state">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                      <circle cx="12" cy="12" r="10"/>
                      <path d="M8 12h8M12 8v8"/>
                    </svg>
                    <p>No language data available</p>
                  </div>
                `}
              </div>
            </div>
          </div>
        </div>

        <!-- Framework Detection -->
        ${frameworks.length > 0 ? `
          <div class="panel">
            <div class="panel__title">Frameworks Detected</div>
            <div class="metrics-frameworks">
              ${frameworks.map(fw => `
                <span class="framework-badge" style="background: ${getFrameworkColor(fw)}">
                  ${escapeHtml(fw)}
                </span>
              `).join('')}
            </div>
          </div>
        ` : ''}

        <!-- Performance Metrics -->
        <div class="panel">
          <div class="panel__title">Performance Breakdown</div>
          <div class="metrics-performance">
            <div class="performance-metric">
              <span class="performance-metric__label">Parsing Rate</span>
              <span class="performance-metric__value">${calculateParsingRate(stats)} entities/sec</span>
            </div>
            <div class="performance-metric">
              <span class="performance-metric__label">Cache Hit Rate</span>
              <span class="performance-metric__value">${calculateCacheRate(stats)}%</span>
            </div>
            <div class="performance-metric">
              <span class="performance-metric__label">Symbol Resolution</span>
              <span class="performance-metric__value">${stats.symbolResolutionEnabled ? 'Enabled' : 'Disabled'}</span>
            </div>
            <div class="performance-metric">
              <span class="performance-metric__label">Symbol Index Size</span>
              <span class="performance-metric__value">${formatInt(stats.symbolIndexSize || 0)}</span>
            </div>
            <div class="performance-metric">
              <span class="performance-metric__label">Semantic Tags Added</span>
              <span class="performance-metric__value">${formatInt(stats.semanticTagsAdded || 0)}</span>
            </div>
            <div class="performance-metric">
              <span class="performance-metric__label">Semantic Edges Added</span>
              <span class="performance-metric__value">${formatInt(stats.semanticEdgesAdded || 0)}</span>
            </div>
          </div>
        </div>

        <!-- Rules Engine Metrics -->
        <div class="panel">
          <div class="panel__title">Rules Engine Performance</div>
          <div class="metrics-rules">
            <div class="rules-metric">
              <span class="rules-metric__label">Plugins Requested</span>
              <span class="rules-metric__value">${formatInt(rules.builtinPluginsRequested || 0)}</span>
            </div>
            <div class="rules-metric">
              <span class="rules-metric__label">Plugins Loaded</span>
              <span class="rules-metric__value">${formatInt(rules.builtinPluginsLoaded || 0)}</span>
            </div>
            <div class="rules-metric">
              <span class="rules-metric__label">Custom Rules (Inline)</span>
              <span class="rules-metric__value">${formatInt(rules.customInlineCount || 0)}</span>
            </div>
            <div class="rules-metric">
              <span class="rules-metric__label">Custom Rules (File)</span>
              <span class="rules-metric__value">${formatInt(rules.customFileCount || 0)}</span>
            </div>
            <div class="rules-metric">
              <span class="rules-metric__label">Entities Updated</span>
              <span class="rules-metric__value">${formatInt(rules.entitiesUpdated || 0)}</span>
            </div>
            <div class="rules-metric">
              <span class="rules-metric__label">Cache Status</span>
              <span class="rules-metric__value ${rules.cacheHit ? 'value--success' : 'value--neutral'}">${rules.cacheHit ? 'HIT' : 'MISS'}</span>
            </div>
          </div>
        </div>

        <!-- Snapshots & Patches Metrics -->
        <div class="panel panel--snapshots-patches">
          <div class="panel__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 6px;">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
            Snapshots & Patches
          </div>

          <!-- Summary Cards -->
          <div class="snapshots-patches-summary">
            ${renderSnapshotPatchCard({
              label: 'Total Snapshots',
              value: formatInt(snapshotMetrics.totalSnapshots),
              iconSvg: ICONS.camera,
              color: 'primary'
            })}
            ${renderSnapshotPatchCard({
              label: 'Total Patches',
              value: formatInt(patchMetrics.totalPatches),
              iconSvg: ICONS.layers,
              color: 'info'
            })}
            ${renderSnapshotPatchCard({
              label: 'Avg Patch Time',
              value: formatDuration(patchMetrics.avgDuration),
              iconSvg: ICONS.clock,
              color: 'amber'
            })}
            ${renderSnapshotPatchCard({
              label: 'Total Changes',
              value: formatInt(patchMetrics.totalChanges),
              iconSvg: ICONS.barChart,
              color: 'success'
            })}
          </div>

          <!-- Latest Patch Details -->
          ${patchesData?.patches?.length > 0 ? `
            <div class="latest-patch-section">
              <div class="latest-patch-header">Latest Patch Details</div>
              <div class="latest-patch-id">${escapeHtml(patchesData.patches[patchesData.patches.length - 1].operation_id.slice(0, 40))}...</div>
              <div class="latest-patch-meta">
                <span>${formatRelativeTime(patchesData.patches[patchesData.patches.length - 1].timestamp)}</span>
                <span class="meta-sep">·</span>
                <span>${formatInt(patchesData.patches[patchesData.patches.length - 1].metrics.affected_files)} files affected</span>
              </div>
            </div>
          ` : ''}

          <!-- Patch History Chart -->
          ${patchesData?.patches?.length > 0 ? `
            <div class="patch-history-section">
              <div class="patch-history-header">Patch History</div>
              <div class="patch-chart">
                ${patchesData.patches.map(patch => {
                  const m = patch.metrics;
                  const maxFiles = Math.max(...patchesData.patches.map(p => p.metrics.affected_files));
                  const barHeight = maxFiles > 0 ? (m.affected_files / maxFiles) * 100 : 0;
                  return `
                    <div class="patch-chart-bar" title="${patch.operation_id}: ${formatInt(m.affected_files)} files, ${formatDuration(m.elapsed_seconds)}">
                      <div class="patch-bar-segment patch-bar--added" style="height: ${barHeight * (m.added_files / m.affected_files)}%"></div>
                      <div class="patch-bar-segment patch-bar--modified" style="height: ${barHeight * (m.modified_files / m.affected_files)}%"></div>
                      <div class="patch-bar-segment patch-bar--deleted" style="height: ${barHeight * (m.deleted_files / m.affected_files)}%"></div>
                    </div>
                  `;
                }).join('')}
              </div>
              <div class="patch-legend">
                <span class="patch-legend-item"><span class="patch-legend-color patch-legend--added"></span>Added</span>
                <span class="patch-legend-item"><span class="patch-legend-color patch-legend--modified"></span>Modified</span>
                <span class="patch-legend-item"><span class="patch-legend-color patch-legend--deleted"></span>Deleted</span>
              </div>
            </div>
          ` : ''}

          <!-- Patch Metrics Table -->
          <div class="snapshots-patches-metrics">
            <div class="sp-metric">
              <span class="sp-metric__label">Files Added (total)</span>
              <span class="sp-metric__value sp-metric__value--success">+${formatInt(patchMetrics.totalAdded)}</span>
            </div>
            <div class="sp-metric">
              <span class="sp-metric__label">Files Modified (total)</span>
              <span class="sp-metric__value sp-metric__value--warning">~${formatInt(patchMetrics.totalModified)}</span>
            </div>
            <div class="sp-metric">
              <span class="sp-metric__label">Files Deleted (total)</span>
              <span class="sp-metric__value sp-metric__value--error">-${formatInt(patchMetrics.totalDeleted)}</span>
            </div>
            <div class="sp-metric">
              <span class="sp-metric__label">Avg Files per Patch</span>
              <span class="sp-metric__value">${formatInt(patchMetrics.avgFilesPerPatch)}</span>
            </div>
            <div class="sp-metric">
              <span class="sp-metric__label">Avg Token Size</span>
              <span class="sp-metric__value">${formatBytes(patchMetrics.avgTokenSize)}</span>
            </div>
            <div class="sp-metric">
              <span class="sp-metric__label">Patch Frequency</span>
              <span class="sp-metric__value">${patchMetrics.frequency}</span>
            </div>
          </div>
        </div>

        <!-- Staleness Gauge -->
        <div class="panel">
          <div class="panel__title">Repository Staleness</div>
          <div class="metrics-staleness">
            <div class="staleness-gauge">
              <div class="staleness-gauge__track">
                <div class="staleness-gauge__fill" style="width: ${(currentIndex.stalenessScore || 0) * 100}%; background: ${getStalenessColor(currentIndex.stalenessScore || 0)}"></div>
              </div>
              <div class="staleness-gauge__labels">
                <span>Fresh</span>
                <span class="staleness-gauge__value">${Math.round((currentIndex.stalenessScore || 0) * 100)}%</span>
                <span>Stale</span>
              </div>
            </div>
            <p class="staleness-hint">
              Staleness indicates how much the repository has changed since the last scan.
              A score of 100% means the index is fully up-to-date.
            </p>
          </div>
        </div>

        <!-- Export Actions -->
        <div class="panel metrics-export-panel">
          <div class="panel__title">Export Data</div>
          <div class="metrics-export">
            <button class="btn btn--secondary" id="export-json">Export as JSON</button>
            <button class="btn btn--secondary" id="export-csv">Export as CSV</button>
          </div>
        </div>
      </div>
    `;

    // Wire up export buttons
    container.querySelector('#export-json')?.addEventListener('click', () => {
      exportData(sortedIndexes[0], 'json');
    });

    container.querySelector('#export-csv')?.addEventListener('click', () => {
      exportData(sortedIndexes[0], 'csv');
    });

    // Wire up refresh button with spin animation
    const refreshBtn = container.querySelector('#refresh-metrics');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', async () => {
        refreshBtn.style.pointerEvents = 'none';
        refreshBtn.querySelector('svg').style.animation = 'spin 1s linear infinite';

        // Clear caches
        patchesCache = null;
        metricsCache = null;

        // Re-render (simplified - full page reload for fresh data)
        setTimeout(() => {
          window.dispatchEvent(new CustomEvent('batho:index-changed'));
          refreshBtn.style.pointerEvents = '';
          refreshBtn.querySelector('svg').style.animation = '';
        }, 800);
      });
    }

    // Wire up chart toggles
    container.querySelectorAll('.chart-toggle').forEach(toggle => {
      toggle.addEventListener('click', () => {
        // Update active state
        container.querySelectorAll('.chart-toggle').forEach(t => {
          t.classList.toggle('chart-toggle--active', t === toggle);
        });

        // Get metric type
        const metric = toggle.dataset.metric;

        // Re-render chart with selected metric
        const chartContainer = container.querySelector('#trend-chart');
        if (chartContainer && metric) {
          chartContainer.style.opacity = '0.5';
          setTimeout(() => {
            chartContainer.innerHTML = renderTrendChart(sortedIndexes.slice(0, 10).reverse(), metric);
            chartContainer.style.opacity = '1';
          }, 150);
        }
      });
    });

    // Wire up KPI view chips
    container.querySelectorAll('.section-actions .chip').forEach(chip => {
      chip.addEventListener('click', () => {
        container.querySelectorAll('.section-actions .chip').forEach(c => {
          c.classList.toggle('chip--active', c === chip);
        });

        const view = chip.dataset.view;
        const kpiCards = container.querySelectorAll('.kpi-card');

        kpiCards.forEach((card, index) => {
          const cardLabel = card.querySelector('.kpi-card__label')?.textContent?.toLowerCase() || '';
          let shouldShow = true;

          if (view === 'code') {
            shouldShow = ['entities', 'relationships', 'files', 'density'].some(term =>
              cardLabel.includes(term)
            );
          } else if (view === 'performance') {
            shouldShow = ['duration', 'rules', 'scan', 'workers'].some(term =>
              cardLabel.includes(term)
            );
          }

          card.style.transition = 'all 0.3s ease';
          if (shouldShow) {
            card.style.display = '';
            card.style.opacity = '1';
            card.style.transform = 'scale(1)';
          } else {
            card.style.opacity = '0';
            card.style.transform = 'scale(0.95)';
            setTimeout(() => {
              if (card.style.opacity === '0') card.style.display = 'none';
            }, 300);
          }
        });
      });
    });

    // Add spin animation for refresh button
    if (!document.getElementById('spin-animation')) {
      const style = document.createElement('style');
      style.id = 'spin-animation';
      style.textContent = `
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `;
      document.head.appendChild(style);
    }

  } catch (err) {
    container.innerHTML = renderErrorPanel(err);
  }

  return container;
}

function renderKpiCard({ label, value, subtitle, trend, trendValue, color = 'primary', icon, iconSvg, sparkline, progress, description }) {
  const trendIcon = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→';
  const trendClass = trend === 'up' ? 'trend--up' : trend === 'down' ? 'trend--down' : 'trend--neutral';

  const tooltipAttr = description ? `title="${escapeHtml(description)}"` : '';

  return `
    <div class="kpi-card kpi-card--${color}" ${tooltipAttr}>
      <div class="kpi-card__header">
        ${iconSvg ? `<span class="kpi-card__icon kpi-card__icon--svg">${iconSvg}</span>` : icon ? `<span class="kpi-card__icon">${icon}</span>` : ''}
        <span class="kpi-card__label">${label}</span>
      </div>
      <div class="kpi-card__body">
        <div class="kpi-card__value">${value}</div>
        ${subtitle ? `<div class="kpi-card__subtitle">${subtitle}</div>` : ''}
      </div>
      ${progress !== undefined ? `
        <div class="kpi-card__progress">
          <div class="kpi-progress-bar">
            <div class="kpi-progress-fill" style="width: ${Math.round(progress * 100)}%"></div>
          </div>
          <span class="kpi-progress-text">${Math.round(progress * 100)}%</span>
        </div>
      ` : ''}
      ${sparkline ? `
        <div class="kpi-card__sparkline">
          ${sparkline}
        </div>
      ` : ''}
      ${trend ? `
        <div class="kpi-card__footer">
          <div class="kpi-card__trend ${trendClass}">
            <span class="trend-icon">${trendIcon}</span>
            ${trendValue ? `<span class="trend-value">${trendValue}</span>` : ''}
          </div>
        </div>
      ` : ''}
    </div>
  `;
}

// Generate SVG sparkline from data points
function generateSparkline(data) {
  if (!data || data.length < 2) return '';

  const width = 80;
  const height = 24;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;

  const points = data.map((val, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((val - min) / range) * height;
    return `${x},${y}`;
  }).join(' ');

  const color = data[data.length - 1] >= data[0] ? '#34d399' : '#ef4444';

  return `
    <svg class="sparkline" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      <polyline
        fill="none"
        stroke="${color}"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        points="${points}"
        class="sparkline-line"
      />
      <circle cx="${width}" cy="${height - ((data[data.length - 1] - min) / range) * height}" r="3" fill="${color}" class="sparkline-dot"/>
    </svg>
  `;
}

function renderTrendChart(indexes, activeMetric = 'entities') {
  if (indexes.length < 2) {
    return `<div class="empty-state">Need at least 2 scans for trends</div>`;
  }

  const maxEntities = Math.max(...indexes.map(i => i.entityCount || 0));
  const maxRelationships = Math.max(...indexes.map(i => i.relationshipCount || 0));
  const maxFiles = Math.max(...indexes.map(i => i.fileCount || 0));

  const getValue = (idx, metric) => {
    switch (metric) {
      case 'entities': return idx.entityCount || 0;
      case 'relationships': return idx.relationshipCount || 0;
      case 'files': return idx.fileCount || 0;
      default: return idx.entityCount || 0;
    }
  };

  const getMax = (metric) => {
    switch (metric) {
      case 'entities': return maxEntities;
      case 'relationships': return maxRelationships;
      case 'files': return maxFiles;
      default: return maxEntities;
    }
  };

  const getColor = (metric) => {
    switch (metric) {
      case 'entities': return 'var(--accent-cyan)';
      case 'relationships': return 'var(--accent-purple)';
      case 'files': return '#fbbf24';
      default: return 'var(--accent-cyan)';
    }
  };

  const activeMax = getMax(activeMetric);
  const activeColor = getColor(activeMetric);

  return `
    <div class="trend-chart">
      <div class="trend-chart__bars">
        ${indexes.map(idx => {
          const value = getValue(idx, activeMetric);
          const pct = activeMax > 0 ? (value / activeMax) * 100 : 0;
          const displayValue = formatInt(value);
          return `
            <div class="trend-bar-group" title="${formatShortId(idx.indexId || idx.id)}: ${displayValue} ${activeMetric}">
              <div class="trend-bar trend-bar--active" style="height: ${pct}%; background: ${activeColor}"></div>
              <div class="trend-bar__label">${formatShortDate(idx.timestamp)}</div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function calculateTrends(indexes) {
  if (indexes.length < 2) {
    return {
      entityTrend: null,
      entityDelta: null,
      relationshipTrend: null,
      relationshipDelta: null,
    };
  }

  const current = indexes[0];
  const previous = indexes[1];

  const entityDelta = (current.entityCount || 0) - (previous.entityCount || 0);
  const relationshipDelta = (current.relationshipCount || 0) - (previous.relationshipCount || 0);

  return {
    entityTrend: entityDelta > 0 ? 'up' : entityDelta < 0 ? 'down' : 'neutral',
    entityDelta: entityDelta !== 0 ? formatInt(Math.abs(entityDelta)) : null,
    relationshipTrend: relationshipDelta > 0 ? 'up' : relationshipDelta < 0 ? 'down' : 'neutral',
    relationshipDelta: relationshipDelta !== 0 ? formatInt(Math.abs(relationshipDelta)) : null,
  };
}

// Load patches data from API
async function loadPatches() {
  if (patchesCache) return patchesCache;

  try {
    const response = await fetch('/api/v1/bridge/patches');
    if (!response.ok) return null;
    const envelope = await response.json();
    patchesCache = envelope.data || null;
    return patchesCache;
  } catch (err) {
    console.warn('[metrics] Failed to load patches:', err);
    return null;
  }
}

// Calculate patch metrics from patches data
function calculatePatchMetrics(patchesData) {
  if (!patchesData?.patches?.length) {
    return {
      totalPatches: 0,
      totalAdded: 0,
      totalModified: 0,
      totalDeleted: 0,
      totalChanges: 0,
      avgDuration: 0,
      avgFilesPerPatch: 0,
      avgTokenSize: 0,
      frequency: 'N/A',
    };
  }

  const patches = patchesData.patches;
  const total = patches.length;

  const totals = patches.reduce((acc, p) => {
    const m = p.metrics;
    acc.added += m.added_files || 0;
    acc.modified += m.modified_files || 0;
    acc.deleted += m.deleted_files || 0;
    acc.duration += m.elapsed_seconds || 0;
    acc.files += m.affected_files || 0;
    acc.tokens += m.token_size || 0;
    return acc;
  }, { added: 0, modified: 0, deleted: 0, duration: 0, files: 0, tokens: 0 });

  // Calculate frequency
  let frequency = 'N/A';
  if (total >= 2) {
    const firstDate = new Date(patches[0].timestamp);
    const lastDate = new Date(patches[patches.length - 1].timestamp);
    const daysDiff = (lastDate - firstDate) / (1000 * 60 * 60 * 24);
    if (daysDiff > 0) {
      const patchesPerDay = total / daysDiff;
      frequency = patchesPerDay >= 1 ? `${patchesPerDay.toFixed(1)}/day` : `${(1 / patchesPerDay).toFixed(1)} days`;
    }
  }

  return {
    totalPatches: total,
    totalAdded: totals.added,
    totalModified: totals.modified,
    totalDeleted: totals.deleted,
    totalChanges: totals.added + totals.modified + totals.deleted,
    avgDuration: totals.duration / total,
    avgFilesPerPatch: Math.round(totals.files / total),
    avgTokenSize: Math.round(totals.tokens / total),
    frequency,
  };
}

// Calculate snapshot metrics from index data
function calculateSnapshotMetrics(indexes, patchesData) {
  const totalSnapshots = indexes.length;

  // Count incremental scans (those with base_snapshot_id in stats)
  const incrementalScans = indexes.filter(idx => idx.stats?.baseSnapshotId || idx.stats?.base_snapshot_id).length;

  // Check if we have snapshot files in .ctn/snapshots
  const snapshotFilesCount = patchesData?.patches?.reduce((acc, p) => {
    // Each patch creates a new snapshot
    return acc + 1;
  }, 1) || totalSnapshots; // Start with at least 1 for initial snapshot

  return {
    totalSnapshots: Math.max(totalSnapshots, snapshotFilesCount),
    incrementalScans,
    fullScans: totalSnapshots - incrementalScans,
  };
}

// Enterprise SVG Icon Library (Lucide style)
const ICONS = {
  // Core icons
  hexagon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>`,
  gitBranch: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="3" x2="6" y2="15"></line><circle cx="18" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><path d="M18 9a9 9 0 0 1-9 9"></path></svg>`,
  fileCode: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><polyline points="9 13 12 16 15 13"/><path d="M12 16v-4"/></svg>`,
  zap: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  target: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>`,
  settings: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  camera: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>`,
  layers: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,
  clock: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
  barChart: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>`,
  activity: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`,
  database: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>`,
  code: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`,
  box: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>`,
};

// Render snapshot/patch summary card
function renderSnapshotPatchCard({ label, value, icon, iconSvg, color = 'primary' }) {
  return `
    <div class="sp-summary-card sp-summary-card--${color}">
      <div class="sp-summary-card__icon">${iconSvg || icon || ''}</div>
      <div class="sp-summary-card__value">${value}</div>
      <div class="sp-summary-card__label">${label}</div>
    </div>
  `;
}

function calculateParsingRate(stats) {
  const entities = stats.entityCount || 0;
  const seconds = stats.elapsedSeconds || 1;
  return (entities / seconds).toFixed(0);
}

function calculateCacheRate(stats) {
  const candidates = stats.filesCandidates || 0;
  const cached = stats.filesCached || 0;
  return candidates > 0 ? Math.round((cached / candidates) * 100) : 0;
}

function formatShortId(id) {
  if (!id) return '—';
  return id.replace(/^batho_/, '').slice(0, 12);
}

function formatShortDate(timestamp) {
  if (!timestamp) return '—';
  const date = new Date(timestamp);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function getLanguageColor(lang) {
  const colors = {
    'Python': '#3776ab',
    'JavaScript': '#f7df1e',
    'TypeScript': '#3178c6',
    'Node.js': '#339933',
    'Java': '#b07219',
    'Go': '#00add8',
    'Rust': '#dea584',
    'C++': '#f34b7d',
    'C': '#555555',
    'Ruby': '#701516',
    'PHP': '#4F5D95',
    'Swift': '#ffac45',
    'Kotlin': '#A97BFF',
  };
  return colors[lang] || 'var(--accent-cyan)';
}

function getFrameworkColor(fw) {
  const colors = {
    'React': 'rgb(97 218 251 / 0.2)',
    'Flask': 'rgb(255 255 255 / 0.2)',
    'Pytest': 'rgb(0 128 0 / 0.2)',
    'TypeScript': 'rgb(49 120 198 / 0.2)',
    'Vite': 'rgb(100 108 255 / 0.2)',
    'pytest': 'rgb(0 128 0 / 0.2)',
  };
  return colors[fw] || 'var(--surface-container-high)';
}

function getStalenessColor(score) {
  if (score >= 0.8) return '#34d399'; // green
  if (score >= 0.5) return '#fbbf24'; // amber
  return '#ef4444'; // red
}

function exportData(index, format) {
  const data = {
    timestamp: index.timestamp,
    indexId: index.indexId || index.id,
    stats: index.stats,
    stack: index.stack,
  };

  if (format === 'json') {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `batho-metrics-${formatShortId(index.indexId || index.id)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  } else if (format === 'csv') {
    const csv = convertToCsv(data);
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `batho-metrics-${formatShortId(index.indexId || index.id)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }
}

function convertToCsv(data) {
  const rows = [
    ['Metric', 'Value'],
    ['Timestamp', data.timestamp],
    ['Index ID', data.indexId || ''],
    ['Entity Count', data.stats?.entityCount || 0],
    ['Relationship Count', data.stats?.relationshipCount || 0],
    ['Files Parsed', data.stats?.filesParsed || 0],
    ['Elapsed Seconds', data.stats?.elapsedSeconds || 0],
    ['Workers Used', data.stats?.workersUsed || 0],
    ['Semantic Tags Added', data.stats?.semanticTagsAdded || 0],
    ['Semantic Edges Added', data.stats?.semanticEdgesAdded || 0],
  ];
  return rows.map(r => r.join(',')).join('\n');
}

function renderErrorPanel(err) {
  return `
    <div class="panel error-panel">
      <div class="error-panel__icon">⚠</div>
      <div class="error-panel__title">Failed to Load Metrics</div>
      <div class="error-panel__message">${escapeHtml(err.message || 'Unknown error')}</div>
    </div>
  `;
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

// Inject styles
const metricsStyles = `
  .page--metrics { height: 100%; overflow: hidden; }
  .metrics-page { display: flex; flex-direction: column; gap: var(--space-gutter); height: 100%; padding: var(--space-gutter); overflow-y: auto; }

  .metrics-header-panel { border-left: 3px solid var(--accent-cyan); }

  .metrics-title-icon {
    vertical-align: middle;
    margin-right: 8px;
    color: var(--accent-cyan);
  }

  .metrics-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-sm);
  }

  .metrics-meta {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
  }

  .meta-sep { opacity: 0.4; }

  /* KPI Cards */
  .metrics-kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-gutter);
  }

  .kpi-card {
    padding: var(--space-md);
    border: var(--hairline);
    border-radius: var(--radius-md);
    background: var(--surface-container);
    text-align: center;
  }

  .kpi-card--primary { border-color: var(--accent-cyan); }
  .kpi-card--primary .kpi-card__icon--svg { color: var(--accent-cyan); }

  .kpi-card--info { border-color: #22d3ee; }
  .kpi-card--info .kpi-card__icon--svg { color: #22d3ee; }

  .kpi-card--success { border-color: #34d399; }
  .kpi-card--success .kpi-card__icon--svg { color: #34d399; }

  .kpi-card--amber { border-color: var(--accent-amber); }
  .kpi-card--amber .kpi-card__icon--svg { color: var(--accent-amber); }

  .kpi-card--purple { border-color: #818cf8; }
  .kpi-card--purple .kpi-card__icon--svg { color: #818cf8; }

  .kpi-card--cyan { border-color: #22d3ee; }
  .kpi-card--cyan .kpi-card__icon--svg { color: #22d3ee; }

  .kpi-card__label {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: var(--space-sm);
  }

  .kpi-card__value {
    font-family: var(--font-heading);
    font-size: 28px;
    font-weight: 700;
    color: var(--on-surface);
    margin-bottom: 4px;
  }

  .kpi-card__subtitle {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    margin-bottom: var(--space-sm);
  }

  .kpi-card__trend {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    font-family: var(--font-mono);
    font-size: 11px;
    padding: 2px 8px;
    border-radius: var(--radius-sm);
  }

  .trend--up { background: rgb(52 211 153 / 0.15); color: #34d399; }
  .trend--down { background: rgb(239 68 68 / 0.15); color: #ef4444; }
  .trend--neutral { background: var(--surface-container-high); color: var(--on-surface-variant); }

  /* Charts */
  .metrics-charts-row {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: var(--space-gutter);
  }

  @media (max-width: 900px) {
    .metrics-charts-row { grid-template-columns: 1fr; }
  }

  .metrics-chart-panel { min-height: 200px; }

  .metrics-chart { padding: var(--space-md) 0; }

  .trend-chart { height: 150px; }

  .trend-chart__legend {
    display: flex;
    gap: var(--space-md);
    margin-bottom: var(--space-md);
  }

  .trend-legend-item {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--on-surface-variant);
  }

  .trend-legend-color {
    width: 12px;
    height: 12px;
    border-radius: 2px;
  }

  .trend-chart__bars {
    display: flex;
    align-items: flex-end;
    gap: var(--space-sm);
    height: 120px;
    padding-bottom: 20px;
    border-bottom: var(--hairline);
  }

  .trend-bar-group {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    height: 100%;
    justify-content: flex-end;
  }

  .trend-bar {
    width: 100%;
    border-radius: 2px 2px 0 0;
    min-height: 2px;
  }

  .trend-bar--entities { background: var(--accent-cyan); }
  .trend-bar--relationships { background: var(--accent-purple); opacity: 0.7; }

  .trend-bar__label {
    font-family: var(--font-mono);
    font-size: 9px;
    color: var(--on-surface-variant);
    transform: rotate(-45deg);
    transform-origin: left center;
    white-space: nowrap;
  }

  /* Distribution */
  .metrics-distribution {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
    padding: var(--space-md) 0;
  }

  .distribution-row {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
  }

  .distribution-label {
    width: 100px;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface);
  }

  .distribution-bar {
    flex: 1;
    height: 8px;
    background: var(--surface-container-high);
    border-radius: 4px;
    overflow: hidden;
  }

  .distribution-bar__fill {
    height: 100%;
    border-radius: 4px;
  }

  /* Frameworks */
  .metrics-frameworks {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm);
    padding: var(--space-md) 0;
  }

  .framework-badge {
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-md);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface);
    border: var(--hairline);
  }

  /* Performance */
  .metrics-performance,
  .metrics-rules {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-md);
    padding: var(--space-md) 0;
  }

  .performance-metric,
  .rules-metric {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-sm) var(--space-md);
    background: var(--surface-container-high);
    border-radius: var(--radius-sm);
  }

  .performance-metric__label,
  .rules-metric__label {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
  }

  .performance-metric__value,
  .rules-metric__value {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface);
    font-weight: 500;
  }

  .value--success { color: #34d399; }
  .value--neutral { color: var(--on-surface-variant); }

  /* Staleness */
  .metrics-staleness {
    padding: var(--space-md) 0;
  }

  .staleness-gauge {
    margin-bottom: var(--space-md);
  }

  .staleness-gauge__track {
    height: 12px;
    background: var(--surface-container-high);
    border-radius: 6px;
    overflow: hidden;
    margin-bottom: var(--space-sm);
  }

  .staleness-gauge__fill {
    height: 100%;
    border-radius: 6px;
    transition: width 0.3s ease;
  }

  .staleness-gauge__labels {
    display: flex;
    justify-content: space-between;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
  }

  .staleness-gauge__value {
    font-weight: 600;
    color: var(--on-surface);
  }

  .staleness-hint {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
    margin: 0;
  }

  /* Export */
  .metrics-export-panel {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-md);
  }

  .metrics-export {
    display: flex;
    gap: var(--space-sm);
  }

  .btn--secondary {
    background: var(--surface-container-high);
    border: var(--hairline);
    color: var(--on-surface);
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-md);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .btn--secondary:hover {
    background: var(--surface-container-highest);
    border-color: var(--accent-cyan);
  }

  /* Empty state */
  .empty-state {
    padding: var(--space-xl);
    text-align: center;
    color: var(--on-surface-variant);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
  }

  .empty-state code {
    background: var(--surface-container-high);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
  }

  /* Error panel */
  .error-panel {
    text-align: center;
    padding: var(--space-3xl);
  }

  .error-panel__icon {
    font-size: 32px;
    margin-bottom: var(--space-md);
  }

  .error-panel__title {
    font-family: var(--font-heading);
    font-size: var(--type-headline-sm-size);
    color: var(--on-surface);
    margin-bottom: var(--space-sm);
  }

  .error-panel__message {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
  }

  /* Snapshots & Patches Section */
  .panel--snapshots-patches {
    border-left: 3px solid var(--accent-purple);
  }

  .snapshots-patches-summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: var(--space-md);
    margin-bottom: var(--space-lg);
    padding: var(--space-md) 0;
  }

  .sp-summary-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: var(--space-md);
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: var(--radius-md);
    text-align: center;
  }

  .sp-summary-card--primary { border-color: var(--accent-cyan); }
  .sp-summary-card--primary .sp-summary-card__icon { color: var(--accent-cyan); }

  .sp-summary-card--info { border-color: #818cf8; }
  .sp-summary-card--info .sp-summary-card__icon { color: #818cf8; }

  .sp-summary-card--amber { border-color: var(--accent-amber); }
  .sp-summary-card--amber .sp-summary-card__icon { color: var(--accent-amber); }

  .sp-summary-card--success { border-color: #34d399; }
  .sp-summary-card--success .sp-summary-card__icon { color: #34d399; }

  .sp-summary-card__icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    margin-bottom: var(--space-xs);
    color: var(--accent-cyan);
  }

  .sp-summary-card__icon svg {
    width: 100%;
    height: 100%;
  }

  .sp-summary-card__value {
    font-family: var(--font-heading);
    font-size: 22px;
    font-weight: 700;
    color: var(--on-surface);
  }

  .sp-summary-card__label {
    font-family: var(--font-mono);
    font-size: 9px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 2px;
  }

  /* Latest Patch Section */
  .latest-patch-section {
    padding: var(--space-md);
    background: var(--surface-container-high);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-lg);
  }

  .latest-patch-header {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: var(--space-xs);
  }

  .latest-patch-id {
    font-family: var(--font-mono);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface);
    margin-bottom: var(--space-xs);
    word-break: break-all;
  }

  .latest-patch-meta {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--on-surface-variant);
  }

  /* Patch History Chart */
  .patch-history-section {
    margin-bottom: var(--space-lg);
  }

  .patch-history-header {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: var(--space-md);
  }

  .patch-chart {
    display: flex;
    align-items: flex-end;
    gap: var(--space-sm);
    height: 100px;
    padding: var(--space-sm);
    background: var(--surface-container-high);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-sm);
  }

  .patch-chart-bar {
    flex: 1;
    display: flex;
    flex-direction: column-reverse;
    height: 100%;
    gap: 1px;
    cursor: pointer;
    transition: opacity var(--transition-fast);
  }

  .patch-chart-bar:hover {
    opacity: 0.8;
  }

  .patch-bar-segment {
    width: 100%;
    min-height: 2px;
    border-radius: 1px;
  }

  .patch-bar--added { background: #34d399; }
  .patch-bar--modified { background: #fbbf24; }
  .patch-bar--deleted { background: #ef4444; }

  .patch-legend {
    display: flex;
    justify-content: center;
    gap: var(--space-md);
  }

  .patch-legend-item {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
  }

  .patch-legend-color {
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }

  .patch-legend--added { background: #34d399; }
  .patch-legend--modified { background: #fbbf24; }
  .patch-legend--deleted { background: #ef4444; }

  /* Snapshots & Patches Metrics Grid */
  .snapshots-patches-metrics {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-sm);
  }

  .sp-metric {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-sm) var(--space-md);
    background: var(--surface-container-high);
    border-radius: var(--radius-sm);
  }

  .sp-metric__label {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
  }

  .sp-metric__value {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface);
    font-weight: 500;
  }

  .sp-metric__value--success { color: #34d399; }
  .sp-metric__value--warning { color: #fbbf24; }
  .sp-metric__value--error { color: #ef4444; }

  /* Enhanced Header Styles */
  .metrics-title-group {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .metrics-subtitle {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
    font-weight: 400;
  }

  .metrics-actions {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--space-sm);
  }

  .meta-badge--live {
    display: inline-flex;
    align-items: center;
    gap: var(--space-xs);
    padding: 2px 8px;
    background: rgb(52 211 153 / 0.15);
    border: 1px solid rgb(52 211 153 / 0.3);
    border-radius: 12px;
    font-family: var(--font-mono);
    font-size: 10px;
    color: #34d399;
    font-weight: 600;
  }

  .live-dot {
    width: 6px;
    height: 6px;
    background: #34d399;
    border-radius: 50%;
    animation: pulse-live 2s ease-in-out infinite;
  }

  @keyframes pulse-live {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
  }

  .meta-index-id {
    color: var(--accent-cyan);
    font-weight: 600;
  }

  .btn--refresh {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-sm) var(--space-md);
    background: var(--surface-container-high);
    border: var(--hairline);
    border-radius: var(--radius-md);
    color: var(--on-surface);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .btn--refresh:hover {
    background: var(--surface-container-highest);
    border-color: var(--accent-cyan);
    color: var(--accent-cyan);
  }

  .btn--refresh:active {
    transform: scale(0.98);
  }

  /* Section Headers */
  .metrics-section {
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
  }

  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-sm);
  }

  .section-title {
    font-family: var(--font-heading);
    font-size: var(--type-headline-sm-size);
    font-weight: var(--type-headline-sm-weight);
    color: var(--on-surface);
    margin: 0;
  }

  .section-actions {
    display: flex;
    gap: var(--space-xs);
  }

  .chip {
    padding: var(--space-xs) var(--space-sm);
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: var(--radius-md);
    color: var(--on-surface-variant);
    font-family: var(--font-mono);
    font-size: 11px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .chip:hover {
    background: var(--surface-container-high);
    color: var(--on-surface);
  }

  .chip--active {
    background: var(--accent-cyan);
    border-color: var(--accent-cyan);
    color: #000;
  }

  /* Enhanced KPI Cards */
  .kpi-card {
    position: relative;
    padding: var(--space-md);
    border: var(--hairline);
    border-radius: var(--radius-md);
    background: var(--surface-container);
    transition: all var(--transition-fast);
    overflow: hidden;
  }

  .kpi-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, transparent, var(--accent-cyan), transparent);
    opacity: 0;
    transition: opacity var(--transition-fast);
  }

  .kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }

  .kpi-card:hover::before {
    opacity: 1;
  }

  .kpi-card__header {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    margin-bottom: var(--space-sm);
  }

  .kpi-card__icon {
    font-size: 16px;
    opacity: 0.8;
  }

  .kpi-card__icon--svg {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    color: var(--accent-cyan);
  }

  .kpi-card__icon--svg svg {
    width: 100%;
    height: 100%;
  }

  .kpi-card__label {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .kpi-card__body {
    margin-bottom: var(--space-sm);
  }

  .kpi-card__value {
    font-family: var(--font-heading);
    font-size: 28px;
    font-weight: 700;
    color: var(--on-surface);
    line-height: 1.2;
  }

  .kpi-card__subtitle {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    margin-top: 2px;
  }

  /* Progress Bar in KPI Card */
  .kpi-card__progress {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-top: var(--space-sm);
  }

  .kpi-progress-bar {
    flex: 1;
    height: 4px;
    background: var(--surface-container-high);
    border-radius: 2px;
    overflow: hidden;
  }

  .kpi-progress-fill {
    height: 100%;
    background: var(--accent-cyan);
    border-radius: 2px;
    transition: width 0.6s ease;
  }

  .kpi-progress-text {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
  }

  /* Sparkline */
  .kpi-card__sparkline {
    margin-top: var(--space-sm);
    padding-top: var(--space-sm);
    border-top: 1px solid var(--outline-variant);
  }

  .sparkline {
    display: block;
    width: 100%;
  }

  .sparkline-line {
    animation: draw-line 1s ease-out forwards;
  }

  @keyframes draw-line {
    from { stroke-dasharray: 200; stroke-dashoffset: 200; }
    to { stroke-dasharray: 200; stroke-dashoffset: 0; }
  }

  .sparkline-dot {
    animation: pulse-dot 2s ease-in-out infinite;
  }

  @keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }

  .kpi-card__footer {
    margin-top: var(--space-sm);
    padding-top: var(--space-sm);
    border-top: 1px solid var(--outline-variant);
  }

  /* Chart Panel Enhancements */
  .panel__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-sm);
    margin-bottom: var(--space-md);
  }

  .panel__badge {
    padding: 2px 8px;
    background: var(--surface-container-high);
    border-radius: 10px;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
  }

  .panel__actions {
    display: flex;
    gap: var(--space-xs);
  }

  .chart-toggle {
    padding: var(--space-xs) var(--space-sm);
    background: transparent;
    border: var(--hairline);
    border-radius: var(--radius-sm);
    color: var(--on-surface-variant);
    font-family: var(--font-mono);
    font-size: 11px;
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .chart-toggle:hover {
    background: var(--surface-container-high);
    color: var(--on-surface);
  }

  .chart-toggle--active {
    background: var(--accent-cyan);
    border-color: var(--accent-cyan);
    color: #000;
  }

  .chart-insight {
    margin-top: var(--space-md);
    padding: var(--space-sm) var(--space-md);
    background: var(--surface-container-high);
    border-radius: var(--radius-md);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
  }

  /* Distribution Row Animations */
  .distribution-row {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-xs) 0;
    opacity: 0;
    animation: slide-in 0.3s ease-out forwards;
  }

  @keyframes slide-in {
    from { opacity: 0; transform: translateX(-10px); }
    to { opacity: 1; transform: translateX(0); }
  }

  .distribution-info {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    width: 100px;
    flex-shrink: 0;
  }

  .distribution-icon {
    font-size: 10px;
  }

  .distribution-bar-container {
    flex: 1;
  }

  .distribution-bar__fill {
    animation: grow-bar 0.6s ease-out forwards;
    transform-origin: left;
  }

  @keyframes grow-bar {
    from { transform: scaleX(0); }
    to { transform: scaleX(1); }
  }

  /* Empty State Enhancement */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--space-2xl);
    text-align: center;
    color: var(--on-surface-variant);
  }

  .empty-state svg {
    margin-bottom: var(--space-md);
    opacity: 0.5;
  }

  .empty-state p {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    margin: 0;
  }
`;

function injectStyles() {
  if (document.getElementById('metrics-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'metrics-styles';
  styleEl.textContent = metricsStyles;
  document.head.appendChild(styleEl);
}

injectStyles();

