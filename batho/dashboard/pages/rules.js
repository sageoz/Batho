/**
 * Plugins page - displays BSG plugins with their rules, categories, and execution stats.
 * Shows plugin catalog, loaded plugins, and rule applications.
 *
 * Enterprise Features:
 * - Plugin catalog with categories (foundation, interceptors, etc.)
 * - Plugin load status and version info
 * - Rule execution stats per plugin
 * - Plugin file browser
 */

import { loadIndex, loadBsg, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { formatInt, formatRelativeTime } from '../assets/js/format.js';
import { createChipFilter, setChipActive } from '../shared/components/chip-filter.js';
import { glowBadgeHtml, severityBadge } from '../shared/components/glow-badge.js';
import { createStatTile } from '../shared/components/stat-tile.js';
import { createKpiRow } from '../shared/components/kpi-row.js';
import { router } from '../assets/js/router.js';

// Active tab state
let _activeTab = 'overview';

// Plugin color mapping
const PLUGIN_COLORS = {
  foundation: { bg: 'rgb(79 70 229 / 0.15)', color: '#818cf8' },
  'framework-specific': { bg: 'rgb(6 182 212 / 0.15)', color: '#22d3ee' },
  detection: { bg: 'rgb(16 185 129 / 0.15)', color: '#34d399' },
  optimization: { bg: 'rgb(245 158 11 / 0.15)', color: '#fbbf24' },
  custom: { bg: 'rgb(168 85 247 / 0.15)', color: '#c4b5fd' },
  unknown: { bg: 'rgb(120 120 120 / 0.15)', color: '#9ca3af' },
};

export async function renderPlugins(params) {
  const container = document.createElement('div');
  container.className = 'page page--plugins';
  container.innerHTML = `<div class="panel" aria-busy="true"><div class="loading"><span class="loading__cursor"></span><span>loading plugins …</span></div></div>`;

  try {
    // Parse URL parameters
    const urlParams = new URLSearchParams(window.location.hash.split('?')[1] || '');
    const initialPluginFilter = urlParams.get('plugin') || params?.get('plugin') || '';
    const tabParam = urlParams.get('tab') || params?.get('tab') || '';
    if (tabParam && ['overview', 'catalog', 'loaded', 'rules', 'performance'].includes(tabParam)) {
      _activeTab = tabParam;
    }

    const savedIndexId = localStorage.getItem('batho.activeIndexId');
    const indexData = await loadIndex();
    const activeIndexId = savedIndexId && indexData.indexes[savedIndexId]
      ? savedIndexId
      : indexData.currentIndexId;

    // Get index entry for rich rule stats
    const indexEntry = indexData.indexes[activeIndexId] || {};
    const indexRulesStats = indexEntry.stats?.rules || {};

    const bsgData = await loadBsg(activeIndexId).catch((err) => {
      if (err.name === 'MissingArtifactError') return null;
      throw err;
    });

    // Extract BSG stats as fallback for missing index rules stats
    const bsgStats = bsgData?.stats || {};

    // Extract plugin info from BSG nodes if not in index stats
    let extractedPluginVersions = indexRulesStats.pluginVersions || {};
    let extractedPluginHits = indexRulesStats.pluginHits || {};

    if (Object.keys(extractedPluginVersions).length === 0 && bsgData?.nodes) {
      // Find plugin files in nodes
      const pluginNodes = bsgData.nodes.filter(n =>
        n.file && n.file.includes('bsg/plugins/') && n.file.endsWith('.yaml')
      );

      const pluginMap = {};
      pluginNodes.forEach(n => {
        const match = n.file.match(/bsg\/plugins\/([^/]+)\/([^/]+)\.yaml$/);
        if (match) {
          const category = match[1]; // foundation, interceptors, etc.
          const pluginId = match[2];
          pluginMap[pluginId] = { category, version: '1.0.0' };
        }
      });

      // Convert to plugin versions format
      extractedPluginVersions = {};
      extractedPluginHits = {};
      Object.keys(pluginMap).forEach(pluginId => {
        extractedPluginVersions[pluginId] = pluginMap[pluginId].version;
        extractedPluginHits[pluginId] = 1; // At least 1 hit for each found plugin
      });
    }

    const mergedRulesStats = {
      enabled: indexRulesStats.enabled ?? (bsgStats.rules_loaded > 0),
      rulesLoaded: indexRulesStats.rulesLoaded ?? bsgStats.rules_loaded ?? 0,
      rulesApplied: indexRulesStats.rulesApplied ?? bsgStats.rules_applied ?? 0,
      builtinPluginsRequested: indexRulesStats.builtinPluginsRequested ?? bsgStats.rules_loaded ?? 0,
      builtinPluginsLoaded: indexRulesStats.builtinPluginsLoaded ?? Object.keys(extractedPluginVersions).length ?? bsgStats.rules_loaded ?? 0,
      customInlineCount: indexRulesStats.customInlineCount ?? 0,
      customFileCount: indexRulesStats.customFileCount ?? 0,
      entitiesUpdated: indexRulesStats.entitiesUpdated ?? bsgStats.autofilled_service_tags ?? 0,
      cacheHit: indexRulesStats.cacheHit ?? false,
      pluginVersions: extractedPluginVersions,
      pluginHits: extractedPluginHits,
      ruleHits: indexRulesStats.ruleHits ?? {},
      conflictWarnings: indexRulesStats.conflictWarnings ?? [],
    };

    // Extract rules from BSG data and merged stats
    const rules = extractRules(bsgData, mergedRulesStats);
    const warnings = extractWarnings(bsgData, rules);
    const pluginHits = mergedRulesStats.pluginHits;
    const ruleHits = mergedRulesStats.ruleHits;
    const conflicts = mergedRulesStats.conflictWarnings;

    // Debug logging
    console.log('[Rules] BSG data loaded:', !!bsgData);
    console.log('[Rules] BSG stats:', bsgStats);
    console.log('[Rules] Merged stats:', mergedRulesStats);
    console.log('[Rules] Extracted rules count:', rules.length);
    console.log('[Rules] Plugin versions:', Object.keys(extractedPluginVersions).length);
    console.log('[Rules] Warnings count:', warnings.length);

    // Compute plugin counts for filters
    const pluginCounts = {};
    rules.forEach(r => {
      const plugin = r.plugin || 'unknown';
      pluginCounts[plugin] = (pluginCounts[plugin] || 0) + 1;
    });
    const sortedPlugins = Object.entries(pluginCounts).sort((a, b) => b[1] - a[1]);

    // Active plugin filters
    const activePlugins = new Set(
      initialPluginFilter
        ? initialPluginFilter.split(',').filter(p => pluginCounts[p])
        : Object.keys(pluginCounts)
    );

    // Severity counts
    const severityCounts = { info: 0, warning: 0, block: 0 };
    rules.forEach(r => {
      if (severityCounts[r.severity] !== undefined) {
        severityCounts[r.severity]++;
      }
    });
    warnings.forEach(w => {
      if (severityCounts[w.severity] !== undefined) {
        severityCounts[w.severity]++;
      }
    });

    const totalRules = rules.length;
    const totalWarnings = warnings.length;
    const totalPlugins = Object.keys(mergedRulesStats.pluginVersions || {}).length || Math.round(mergedRulesStats.builtinPluginsLoaded / 6); // Estimate if no plugin data
    const rulesEnabled = mergedRulesStats.enabled ? 'ON' : 'OFF';
    const entitiesTagged = indexEntry.stats?.entitiesRuleTagged || mergedRulesStats.entitiesUpdated || 0;
    const rulesLoaded = mergedRulesStats.rulesLoaded || 0;
    const rulesApplied = mergedRulesStats.rulesApplied || 0;

    container.innerHTML = `
      <div class="rules">
        <div class="panel rules-panel--header">
          <div class="rules-header">
            <h1 class="panel__title">
              <svg class="plugins-title-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
              </svg>
              BSG Plugins
            </h1>
            <div class="rules-meta">
              <span class="meta-badge ${mergedRulesStats.enabled ? 'meta-badge--active' : 'meta-badge--inactive'}">
                ${rulesEnabled}
              </span>
              <span class="meta-sep">·</span>
              <span class="meta-item">${formatInt(totalPlugins)} plugins</span>
              ${totalWarnings > 0 ? `
                <span class="meta-sep">·</span>
                <span class="meta-item meta-item--warnings">${formatInt(totalWarnings)} warnings</span>
              ` : ''}
              ${conflicts.length > 0 ? `
                <span class="meta-sep">·</span>
                <span class="meta-item meta-item--conflicts">${formatInt(conflicts.length)} conflicts</span>
              ` : ''}
            </div>
          </div>
        </div>

        <!-- Executive Summary Cards -->
        <div class="rules-summary" id="rules-summary">
          ${renderExecutiveSummary(mergedRulesStats, indexEntry)}
        </div>

        <!-- Tab Navigation -->
        <div class="rules-tabs" id="rules-tabs">
          ${renderTabBar()}
        </div>

        <!-- Tab Content -->
        <div class="rules-tab-content" id="rules-tab-content"></div>
      </div>
    `;

    // Render initial tab content
    const tabContent = container.querySelector('#rules-tab-content');
    const tabData = { rules, warnings, pluginHits, ruleHits, conflicts, sortedPlugins, activePlugins, indexRulesStats: mergedRulesStats, indexEntry, bsgData };
    renderTabContent(tabContent, _activeTab, tabData);

    // Wire up tab navigation
    container.querySelectorAll('.rules-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        if (tab && tab !== _activeTab) {
          _activeTab = tab;
          updateTabButtons(container);
          renderTabContent(tabContent, _activeTab, tabData);
          updateUrl();
        }
      });
    });

    function updateTabButtons(container) {
      container.querySelectorAll('.rules-tab-btn').forEach(btn => {
        const isActive = btn.dataset.tab === _activeTab;
        btn.classList.toggle('rules-tab-btn--active', isActive);
      });
    }

    function updateUrl() {
      const params = new URLSearchParams();
      if (_activeTab !== 'overview') params.set('tab', _activeTab);
      const newHash = `#/plugins${params.toString() ? '?' + params.toString() : ''}`;
      if (window.location.hash !== newHash) {
        history.replaceState(null, '', newHash);
      }
    }

  } catch (err) {
    console.error('[Rules] Render error:', err);
    container.innerHTML = renderErrorPanel(err);
  }
  return container;
}

// ============================================================================
// Tab & Summary Rendering Functions
// ============================================================================

function renderExecutiveSummary(rulesStats, indexEntry) {
  const rulesLoaded = rulesStats.rulesLoaded || 0;
  const rulesApplied = rulesStats.rulesApplied || 0;
  const totalPlugins = Object.keys(rulesStats.pluginVersions || {}).length;
  const entitiesTagged = indexEntry.stats?.entitiesRuleTagged || 0;
  const cacheHit = rulesStats.cacheHit ? 'Yes' : 'No';
  const interceptionTotal = Object.values(rulesStats.interceptionTotals || {}).reduce((a, b) => a + b, 0);

  const tiles = [
    { label: 'RULES LOADED', value: formatInt(rulesLoaded), color: 'primary' },
    { label: 'RULES APPLIED', value: formatInt(rulesApplied), color: 'success' },
    { label: 'PLUGINS ACTIVE', value: formatInt(totalPlugins), color: 'info' },
    { label: 'ENTITIES TAGGED', value: formatInt(entitiesTagged), color: 'purple' },
    { label: 'INTERCEPTIONS', value: formatInt(interceptionTotal), color: 'amber' },
    { label: 'CACHE HIT', value: cacheHit, color: rulesStats.cacheHit ? 'success' : 'neutral' },
  ];

  return `
    <div class="rules-summary-grid">
      ${tiles.map(t => `
        <div class="rules-summary-card rules-summary-card--${t.color}">
          <div class="rules-summary-card__value">${t.value}</div>
          <div class="rules-summary-card__label">${t.label}</div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderTabBar() {
  const tabs = [
    { key: 'overview', label: 'Overview', icon: 'M3 3h18v18H3V3zm16 16V5H5v14h14z' },
    { key: 'catalog', label: 'Catalog', icon: 'M20.5 11H19V7c0-1.1-.9-2-2-2h-4V3.5C13 2.12 11.88 1 10.5 1S8 2.12 8 3.5V5H4c-1.1 0-1.99.9-1.99 2v3.8H3.5c1.49 0 2.7 1.21 2.7 2.7s-1.21 2.7-2.7 2.7H2V20c0 1.1.9 2 2 2h3.8v-1.5c0-1.49 1.21-2.7 2.7-2.7s2.7 1.21 2.7 2.7V22H17c1.1 0 2-.9 2-2v-4h1.5c1.38 0 2.5-1.12 2.5-2.5S21.88 11 20.5 11z' },
    { key: 'loaded', label: 'Loaded', icon: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5' },
    { key: 'rules', label: 'Rules', icon: 'M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z' },
    { key: 'performance', label: 'Performance', icon: 'M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z' },
  ];

  return `
    <div class="rules-tab-bar">
      ${tabs.map(t => `
        <button class="rules-tab-btn ${_activeTab === t.key ? 'rules-tab-btn--active' : ''}" data-tab="${t.key}">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="${t.icon}"/>
          </svg>
          ${t.label}
        </button>
      `).join('')}
    </div>
  `;
}

function renderTabContent(mount, tabKey, data) {
  if (!mount) return;
  mount.innerHTML = '';

  switch (tabKey) {
    case 'overview':
      mount.innerHTML = renderOverviewTab(data);
      break;
    case 'catalog':
      mount.innerHTML = renderCatalogTab(data);
      break;
    case 'loaded':
      mount.innerHTML = renderLoadedTab(data);
      break;
    case 'rules':
      mount.innerHTML = renderRulesTab(data);
      break;
    case 'performance':
      mount.innerHTML = renderPerformanceTab(data);
      break;
    default:
      mount.innerHTML = renderOverviewTab(data);
  }
}

function renderOverviewTab(data) {
  const { rules, warnings, pluginHits, indexRulesStats } = data;
  const mergedStats = indexRulesStats; // Already merged in main render function

  // Show empty state if no rules
  if (!rules || rules.length === 0) {
    return `
      <div class="rules-tab-panel">
        <div class="panel panel--empty">
          <div class="empty-state">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="12" r="10"/>
              <path d="M8 12h8M12 8v8"/>
            </svg>
            <p>No BSG rules data available.</p>
            <p class="empty-state__sub">Rules will appear after indexing with BSG plugins enabled.</p>
            <p class="empty-state__sub">Run: batho index --root . --verbose</p>
          </div>
        </div>
      </div>
    `;
  }

  // Calculate plugin category breakdown
  const categories = { foundation: 0, interceptor: 0, optimization: 0, detection: 0, other: 0 };
  Object.entries(pluginHits).forEach(([plugin, hits]) => {
    if (plugin.includes('foundation') || plugin.includes('detection')) categories.foundation += hits;
    else if (plugin.includes('catcher') || plugin.includes('guardian') || plugin.includes('shield') || plugin.includes('sentinel') || plugin.includes('preventer') || plugin.includes('blast')) categories.interceptor += hits;
    else if (plugin.includes('optimization') || plugin.includes('token')) categories.optimization += hits;
    else if (plugin.includes('detection')) categories.detection += hits;
    else categories.other += hits;
  });

  const totalHits = Object.values(categories).reduce((a, b) => a + b, 0);

  return `
    <div class="rules-tab-panel">
      <!-- Warnings Section -->
      ${warnings.length > 0 ? `
        <div class="panel panel--warnings">
          <div class="warnings-header">
            ${glowBadgeHtml({ variant: 'pulse', content: '!', pulse: true, size: 'md' })}
            <span class="warnings-title">Quality Warnings</span>
            <span class="warnings-count">${formatInt(warnings.length)}</span>
          </div>
          <div class="warnings-list">
            ${warnings.slice(0, 5).map(w => `
              <div class="warning-item warning-item--${w.severity}">
                ${severityBadge(w.severity, w.severity === 'block' ? '✕' : w.severity === 'error' ? '!' : '⚠', { size: 'sm' })}
                <span class="warning-rule">${escapeHtml(w.ruleName || w.plugin || 'Unknown')}:</span>
                <span class="warning-message">${escapeHtml(w.message)}</span>
              </div>
            `).join('')}
            ${warnings.length > 5 ? `<div class="warnings-more">+${formatInt(warnings.length - 5)} more warnings</div>` : ''}
          </div>
        </div>
      ` : ''}

      <!-- Plugin Categories Breakdown -->
      <div class="panel">
        <div class="panel__title">Plugin Activity by Category</div>
        <div class="category-breakdown">
          ${Object.entries(categories).filter(([_, hits]) => hits > 0).map(([cat, hits]) => {
            const pct = totalHits > 0 ? Math.round((hits / totalHits) * 100) : 0;
            const colors = {
              foundation: ['#818cf8', 'rgb(79 70 229 / 0.15)'],
              interceptor: ['#f59e0b', 'rgb(245 158 11 / 0.15)'],
              optimization: ['#34d399', 'rgb(16 185 129 / 0.15)'],
              detection: ['#22d3ee', 'rgb(6 182 212 / 0.15)'],
              other: ['#9ca3af', 'rgb(120 120 120 / 0.15)']
            }[cat];
            return `
              <div class="category-row">
                <span class="category-label">${cat.charAt(0).toUpperCase() + cat.slice(1)}</span>
                <div class="category-bar">
                  <div class="category-bar__fill" style="width: ${pct}%; background: ${colors[0]}"></div>
                </div>
                <span class="category-value" style="color: ${colors[0]}">${formatInt(hits)} (${pct}%)</span>
              </div>
            `;
          }).join('')}
        </div>
      </div>

      <!-- Top Plugins -->
      <div class="panel">
        <div class="panel__title">Top Active Plugins</div>
        <div class="top-plugins">
          ${Object.entries(pluginHits).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([plugin, hits]) => `
            <div class="top-plugin-row">
              <span class="top-plugin-name">${escapeHtml(plugin)}</span>
              <div class="top-plugin-bar">
                <div class="top-plugin-bar__fill" style="width: ${Math.min(100, (hits / (pluginHits[Object.keys(pluginHits)[0]] || 1)) * 100)}%"></div>
              </div>
              <span class="top-plugin-hits">${formatInt(hits)}</span>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;
}

function renderCatalogTab(data) {
  const { pluginHits, indexRulesStats, sortedPlugins, activePlugins } = data;
  const mergedStats = indexRulesStats;
  const pluginVersions = mergedStats.pluginVersions || {};
  const pluginSchemas = mergedStats.pluginSchemaVersions || {};

  const allPlugins = Object.keys(pluginVersions).map(pluginId => {
    const hits = pluginHits[pluginId] || 0;
    const version = pluginVersions[pluginId] || 'unknown';
    const schema = pluginSchemas[pluginId] || 'unknown';

    // Determine category from plugin ID
    let category = 'other';
    if (pluginId.includes('foundation') || pluginId.includes('detection') || pluginId.includes('framework') || pluginId.includes('graph') || pluginId.includes('file')) category = 'foundation';
    else if (pluginId.includes('catcher') || pluginId.includes('guardian') || pluginId.includes('shield') || pluginId.includes('sentinel') || pluginId.includes('preventer') || pluginId.includes('blast')) category = 'interceptor';
    else if (pluginId.includes('optimization') || pluginId.includes('token')) category = 'optimization';

    const colors = PLUGIN_COLORS[category] || PLUGIN_COLORS.unknown;

    return { pluginId, hits, version, schema, category, colors };
  }).sort((a, b) => b.hits - a.hits);

  const maxHits = allPlugins.length > 0 ? allPlugins[0].hits : 1;

  return `
    <div class="rules-tab-panel">
      <div class="panel">
        <div class="rules-filters">
          <div class="chip-filter-group">
            <div class="chip-filter-header">
              <span class="filter-label">Plugin Registry (${allPlugins.length} total)</span>
            </div>
          </div>
        </div>
        <div class="plugin-registry">
          ${allPlugins.map(p => `
            <div class="plugin-card" data-category="${p.category}">
              <div class="plugin-card__header">
                <span class="plugin-badge" style="background: ${p.colors.bg}; color: ${p.colors.color}">
                  ${getCategoryIcon(p.category)} ${p.category}
                </span>
                <span class="plugin-version">v${escapeHtml(p.version)}</span>
              </div>
              <div class="plugin-card__name">${escapeHtml(p.pluginId)}</div>
              <div class="plugin-card__schema">${escapeHtml(p.schema)}</div>
              <div class="plugin-card__hits">
                <div class="plugin-hits-bar">
                  <div class="plugin-hits-bar__fill" style="width: ${(p.hits / maxHits) * 100}%; background: ${p.colors.color}"></div>
                </div>
                <span class="plugin-hits-count">${formatInt(p.hits)} hits</span>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;
}

function getCategoryIcon(category) {
  const icons = {
    foundation: '🏗️',
    interceptor: '🛡️',
    optimization: '⚡',
    other: '📦'
  };
  return icons[category] || '📦';
}

function renderRulesTab(data) {
  const { ruleHits, indexRulesStats } = data;
  const mergedStats = indexRulesStats;
  const sortedRules = Object.entries(ruleHits).sort((a, b) => b[1] - a[1]);

  return `
    <div class="rules-tab-panel">
      <div class="panel">
        <div class="rules-registry-header">
          <span class="filter-label">Rule Registry (${sortedRules.length} rules)</span>
          <div class="rules-search">
            <input type="text" class="rules-search__input" placeholder="Search rules..." id="rule-search">
          </div>
        </div>
        <div class="rules-registry-table">
          <div class="rules-registry__header">
            <div class="th th--name">Rule Name</div>
            <div class="th th--hits">Hits</div>
            <div class="th th--bar">Activity</div>
          </div>
          <div class="rules-registry__body" id="rules-registry-body">
            ${sortedRules.map(([ruleName, hits]) => {
              const maxHits = sortedRules.length > 0 ? sortedRules[0][1] : 1;
              const pct = (hits / maxHits) * 100;
              return `
                <div class="rules-registry__row" data-rule="${escapeHtml(ruleName)}">
                  <div class="td td--name">${escapeHtml(ruleName)}</div>
                  <div class="td td--hits">${formatInt(hits)}</div>
                  <div class="td td--bar">
                    <div class="rule-activity-bar">
                      <div class="rule-activity-bar__fill" style="width: ${pct}%"></div>
                    </div>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderLoadedTab(data) {
  const { indexRulesStats } = data;
  const mergedStats = indexRulesStats;
  const pluginVersions = mergedStats.pluginVersions || {};
  const pluginHits = mergedStats.pluginHits || {};

  const loadedPlugins = Object.keys(pluginVersions);

  if (!loadedPlugins.length) {
    return `
      <div class="rules-tab-panel">
        <div class="panel panel--empty">
          <div class="empty-state">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="12" r="10"/>
              <path d="M12 8v4l3 3"/>
            </svg>
            <p>No plugins loaded.</p>
            <p class="empty-state__sub">Plugins will appear after indexing with BSG plugins enabled.</p>
            <p class="empty-state__sub">Run: batho index --root . --verbose</p>
          </div>
        </div>
      </div>
    `;
  }

  return `
    <div class="rules-tab-panel">
      <div class="panel">
        <div class="loaded-header">
          <span class="loaded-count">${formatInt(loadedPlugins.length)} plugins loaded</span>
          <span class="loaded-subtitle">BSG plugins active in current index</span>
        </div>

        <div class="loaded-list">
          ${loadedPlugins.map((pluginId, i) => {
            const version = pluginVersions[pluginId] || 'unknown';
            const hits = pluginHits[pluginId] || 0;

            // Determine category from plugin ID
            let category = 'other';
            let categoryColor = PLUGIN_COLORS.unknown;
            if (pluginId.includes('foundation') || pluginId.includes('detection') || pluginId.includes('framework') || pluginId.includes('graph') || pluginId.includes('file')) {
              category = 'foundation';
              categoryColor = PLUGIN_COLORS.foundation;
            } else if (pluginId.includes('catcher') || pluginId.includes('guardian') || pluginId.includes('shield') || pluginId.includes('sentinel') || pluginId.includes('preventer') || pluginId.includes('blast')) {
              category = 'interceptor';
              categoryColor = PLUGIN_COLORS['framework-specific'];
            } else if (pluginId.includes('optimization') || pluginId.includes('token')) {
              category = 'optimization';
              categoryColor = PLUGIN_COLORS.optimization;
            } else if (pluginId.includes('detection')) {
              category = 'detection';
              categoryColor = PLUGIN_COLORS.detection;
            }

            return `
              <div class="panel loaded-card">
                <div class="loaded-card__header">
                  <span class="loaded-card__name">${escapeHtml(pluginId)}</span>
                  <span class="loaded-card__version">v${escapeHtml(version)}</span>
                </div>
                <div class="loaded-card__meta">
                  <span class="loaded-card__category" style="background: ${categoryColor.bg}; color: ${categoryColor.color};">${category}</span>
                  <span class="loaded-card__hits">${formatInt(hits)} entities</span>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    </div>
  `;
}

function renderPerformanceTab(data) {
  const { indexRulesStats, indexEntry } = data;
  const mergedStats = indexRulesStats;
  const cacheHit = mergedStats.cacheHit;
  const cachePath = mergedStats.cachePath || 'N/A';
  const entitiesUpdated = mergedStats.entitiesUpdated || 0;
  const semanticTags = mergedStats.semanticTagsAdded || 0;
  const semanticEdges = mergedStats.semanticEdgesAdded || 0;

  return `
    <div class="rules-tab-panel">
      <div class="panel">
        <div class="panel__title">Execution Metrics</div>
        <div class="performance-grid">
          <div class="performance-card">
            <div class="performance-card__label">Cache Status</div>
            <div class="performance-card__value ${cacheHit ? 'performance-card__value--success' : 'performance-card__value--neutral'}">
              ${cacheHit ? 'HIT' : 'MISS'}
            </div>
            <div class="performance-card__detail">${escapeHtml(cachePath.split('/').pop() || 'N/A')}</div>
          </div>
          <div class="performance-card">
            <div class="performance-card__label">Entities Updated</div>
            <div class="performance-card__value">${formatInt(entitiesUpdated)}</div>
            <div class="performance-card__detail">during last scan</div>
          </div>
          <div class="performance-card">
            <div class="performance-card__label">Semantic Tags Added</div>
            <div class="performance-card__value">${formatInt(semanticTags)}</div>
            <div class="performance-card__detail">USN annotations</div>
          </div>
          <div class="performance-card">
            <div class="performance-card__label">Semantic Edges Added</div>
            <div class="performance-card__value">${formatInt(semanticEdges)}</div>
            <div class="performance-card__detail">derived relationships</div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel__title">Plugin Load Statistics</div>
        <div class="load-stats">
          <div class="load-stat">
            <span class="load-stat__label">Builtin Plugins Requested:</span>
            <span class="load-stat__value">${formatInt(mergedStats.builtinPluginsRequested || 0)}</span>
          </div>
          <div class="load-stat">
            <span class="load-stat__label">Builtin Plugins Loaded:</span>
            <span class="load-stat__value">${formatInt(mergedStats.builtinPluginsLoaded || 0)}</span>
          </div>
          <div class="load-stat">
            <span class="load-stat__label">Custom Rules (Inline):</span>
            <span class="load-stat__value">${formatInt(mergedStats.customInlineCount || 0)}</span>
          </div>
          <div class="load-stat">
            <span class="load-stat__label">Custom Rules (File):</span>
            <span class="load-stat__value">${formatInt(mergedStats.customFileCount || 0)}</span>
          </div>
        </div>
      </div>
    </div>
  `;
}

function extractRules(bsgData, indexRulesStats = {}) {
  if (!bsgData) return [];

  // Priority 1: ruleExecutions from BSG
  if (bsgData.ruleExecutions || bsgData.rule_executions) {
    const executions = bsgData.ruleExecutions || bsgData.rule_executions;
    return executions.map(re => ({
      ruleId: re.ruleId || re.rule_id || re.id || 'unknown',
      name: re.ruleName || re.name || re.rule_id || 'Unnamed Rule',
      description: re.description || '',
      plugin: re.pluginId || re.plugin_id || re.plugin || 'unknown',
      severity: (re.severity || 'info').toLowerCase(),
      enabled: re.enabled !== false,
      matchCount: re.matchedEntities?.length || re.matched_count || re.match_count || 0,
      matchedEntities: re.matchedEntities || re.matched_entities || [],
      warnings: re.warnings || [],
    }));
  }

  // Priority 2: Extract from plugins metadata
  if (bsgData.plugins || bsgData.pluginsApplied) {
    const plugins = bsgData.plugins || bsgData.pluginsApplied || [];
    const rules = [];
    plugins.forEach(plugin => {
      const pluginId = plugin.pluginId || plugin.id || 'unknown';
      const pluginRules = plugin.rules || [];
      pluginRules.forEach(rule => {
        rules.push({
          ruleId: rule.ruleId || rule.id || `${pluginId}-${Math.random().toString(36).slice(2)}`,
          name: rule.name || 'Unnamed Rule',
          description: rule.description || '',
          plugin: pluginId,
          severity: (rule.severity || 'info').toLowerCase(),
          enabled: rule.enabled !== false,
          matchCount: rule.matchCount || rule.matchedCount || 0,
          matchedEntities: [],
          warnings: rule.warnings || [],
        });
      });
    });
    return rules;
  }

  // Priority 3: Create synthetic rules from BSG stats
  const stats = bsgData.stats || {};
  const syntheticRules = [];

  // Add rules based on BSG stats
  if (stats.rules_loaded > 0) {
    syntheticRules.push({
      ruleId: 'bsg.rules.loaded',
      name: 'BSG Rules Loaded',
      description: `Total rules loaded from BSG plugins`,
      plugin: 'bsg_core',
      severity: 'info',
      enabled: true,
      matchCount: stats.rules_loaded,
      matchedEntities: [],
      warnings: [],
    });
  }

  if (stats.rules_applied > 0) {
    syntheticRules.push({
      ruleId: 'bsg.rules.applied',
      name: 'BSG Rules Applied',
      description: `Rules that matched and transformed entities`,
      plugin: 'bsg_core',
      severity: 'info',
      enabled: true,
      matchCount: stats.rules_applied,
      matchedEntities: [],
      warnings: [],
    });
  }

  if (stats.autofilled_service_tags > 0) {
    syntheticRules.push({
      ruleId: 'bsg.service_tags.derived',
      name: 'Service Tag Derivation',
      description: `Auto-derived service tags for entities`,
      plugin: 'bsg_foundation',
      severity: 'info',
      enabled: true,
      matchCount: stats.autofilled_service_tags,
      matchedEntities: [],
      warnings: [],
    });
  }

  if (stats.autofilled_index_ids > 0) {
    syntheticRules.push({
      ruleId: 'bsg.index_ids.derived',
      name: 'Index ID Derivation',
      description: `Auto-filled index IDs for entities`,
      plugin: 'bsg_foundation',
      severity: 'info',
      enabled: true,
      matchCount: stats.autofilled_index_ids,
      matchedEntities: [],
      warnings: [],
    });
  }

  // Priority 4: Derive from edges with derived flag (in metadata)
  if (bsgData.edges && syntheticRules.length === 0) {
    const derivedEdges = bsgData.edges.filter(e => {
      // Check for derived flag in multiple locations
      if (e.derived === true || e.is_derived === true || e.isDerived === true) return true;
      // Check in metadata (BSG v1 format)
      if (e.metadata?.derived === true) return true;
      return false;
    });

    if (derivedEdges.length > 0) {
      // Group by derivation source
      const bySource = {};
      derivedEdges.forEach(e => {
        // Get rule source from multiple possible locations
        const source = e.metadata?.derived_from ||
                       e.derivedFrom ||
                       e.metadata?.ruleId ||
                       e.ruleId ||
                       e.rule_id ||
                       'derived';
        if (!bySource[source]) {
          bySource[source] = { count: 0, types: new Set() };
        }
        bySource[source].count++;
        // Get relationship type from multiple locations
        const relType = e.metadata?.type || e.relationshipType || e.type || 'UNKNOWN';
        bySource[source].types.add(relType);
      });

      Object.entries(bySource).forEach(([source, data]) => {
        syntheticRules.push({
          ruleId: source,
          name: `Derived: ${source.slice(0, 16)}`,
          description: `BSG-derived ${Array.from(data.types).join(', ')} relationships`,
          plugin: 'derived',
          severity: 'info',
          enabled: true,
          matchCount: data.count,
          matchedEntities: [],
          warnings: [],
        });
      });
    }
  }

  return syntheticRules;
}

function extractWarnings(bsgData, rules) {
  const warnings = [];

  // Collect warnings from rules
  rules.forEach(rule => {
    if (rule.warnings?.length) {
      rule.warnings.forEach(w => {
        warnings.push({
          ruleId: rule.ruleId,
          ruleName: rule.name,
          plugin: rule.plugin,
          severity: (w.severity || 'warning').toLowerCase(),
          message: w.message || w,
          entityId: w.entityId || w.entity_id,
          file: w.file,
        });
      });
    }
  });

  // Collect from bsgData.warnings if present
  if (bsgData?.warnings?.length) {
    bsgData.warnings.forEach(w => {
      warnings.push({
        ruleId: w.ruleId || w.rule_id,
        ruleName: w.ruleName || w.rule,
        plugin: w.pluginId || w.plugin_id || 'unknown',
        severity: (w.severity || 'warning').toLowerCase(),
        message: w.message,
        entityId: w.entityId || w.entity_id,
        file: w.file,
      });
    });
  }

  // Collect from bsgData.quality?.warnings if present
  if (bsgData?.quality?.warnings?.length) {
    bsgData.quality.warnings.forEach(w => {
      warnings.push({
        ruleId: w.ruleId || w.rule,
        ruleName: w.ruleName || w.rule,
        plugin: w.plugin || 'quality',
        severity: (w.severity || 'warning').toLowerCase(),
        message: w.message,
        entityId: w.entityId,
        file: w.file,
      });
    });
  }

  // Collect from bsgData.quality_warnings (BSG v1 top-level)
  if (bsgData?.quality_warnings?.length) {
    bsgData.quality_warnings.forEach(w => {
      warnings.push({
        ruleId: 'quality-check',
        ruleName: 'Quality Check',
        plugin: 'quality',
        severity: 'warning',
        message: typeof w === 'string' ? w : w.message || JSON.stringify(w),
        entityId: null,
        file: null,
      });
    });
  }

  return warnings.sort((a, b) => {
    const sevOrder = { block: 0, error: 1, warning: 2, info: 3 };
    return (sevOrder[a.severity] || 4) - (sevOrder[b.severity] || 4);
  });
}

function renderRulesByPlugin(rules, activePlugins) {
  // Group rules by plugin
  const groups = {};
  rules.forEach(rule => {
    const plugin = rule.plugin || 'unknown';
    if (!groups[plugin]) {
      groups[plugin] = {
        plugin,
        rules: [],
        totalMatches: 0,
        warningCount: 0,
      };
    }
    groups[plugin].rules.push(rule);
    groups[plugin].totalMatches += rule.matchCount || 0;
    groups[plugin].warningCount += rule.warnings?.length || 0;
  });

  // Sort plugins by total matches
  const sortedGroups = Object.values(groups)
    .sort((a, b) => b.totalMatches - a.totalMatches);

  return sortedGroups.map(group => {
    const colors = PLUGIN_COLORS[group.plugin] || PLUGIN_COLORS.unknown;
    return `
      <div class="rules-group" data-plugin="${escapeHtml(group.plugin)}" style="display: ${activePlugins.has(group.plugin) ? 'block' : 'none'}">
        <div class="rules-group__header">
          <span class="plugin-badge" style="background: ${colors.bg}; color: ${colors.color}">
            ${escapeHtml(group.plugin)}
          </span>
          <span class="rules-group__stats">
            ${formatInt(group.rules.length)} rules
            <span class="stats-sep">·</span>
            ${formatInt(group.totalMatches)} matches
            ${group.warningCount > 0 ? `
              <span class="stats-sep">·</span>
              <span class="warning-stat">${formatInt(group.warningCount)} warnings</span>
            ` : ''}
          </span>
        </div>
        <div class="rules-group__table">
          ${renderRulesTable(group.rules)}
        </div>
      </div>
    `;
  }).join('');
}

function renderRulesTable(rules) {
  return `
    <div class="rules-table">
      <div class="rules-table__header">
        <div class="th th--severity">Severity</div>
        <div class="th th--name">Rule</div>
        <div class="th th--matches">Matches</div>
        <div class="th th--warnings">Status</div>
      </div>
      <div class="rules-table__body">
        ${rules.map(rule => `
          <div class="rules-table__row ${!rule.enabled ? 'rules-table__row--disabled' : ''}" data-rule-id="${escapeHtml(rule.ruleId)}">
            <div class="td td--severity">
              ${severityBadge(rule.severity, rule.severity.toUpperCase().slice(0, 4), { size: 'sm' })}
            </div>
            <div class="td td--name">
              <div class="rule-name-cell">
                <span class="rule-name">${escapeHtml(rule.name)}</span>
                <span class="rule-description" title="${escapeHtml(rule.description)}">
                  ${escapeHtml(rule.description?.slice(0, 60))}${rule.description?.length > 60 ? '…' : ''}
                </span>
              </div>
            </div>
            <div class="td td--matches">
              ${rule.matchCount > 0
                ? `<a href="#/relationships?rule=${encodeURIComponent(rule.ruleId)}" class="match-count" data-navigate>
                    ${formatInt(rule.matchCount)} entities
                   </a>`
                : '<span class="match-count match-count--zero">0</span>'
              }
            </div>
            <div class="td td--warnings">
              ${rule.warnings?.length > 0
                ? glowBadgeHtml({ variant: 'pulse', content: `${rule.warnings.length}`, pulse: true, size: 'sm' })
                : rule.enabled
                  ? '<span class="status-badge status-badge--ok">Active</span>'
                  : '<span class="status-badge status-badge--disabled">Disabled</span>'
              }
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function renderErrorPanel(err) {
  const isMissing = err && err.name === 'MissingArtifactError';
  let title = 'Error';
  let message = err?.message || 'An unknown error occurred';

  if (isMissing) {
    title = 'Missing Artifact';
    message = `Could not load \`${err.path}\`.`;
  }

  return `
    <div class="panel error-panel">
      <div class="error-panel__icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      </div>
      <div class="error-panel__title">${escapeHtml(title)}</div>
      <div class="error-panel__message">${escapeHtml(message)}</div>
      <div class="error-panel__actions">
        <button class="btn" data-action="retry">retry</button>
      </div>
    </div>
  `;
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

const rulesStyles = `
  .page--rules { height: 100%; overflow: hidden; }
  .rules { display: flex; flex-direction: column; gap: var(--space-gutter); height: 100%; padding: var(--space-gutter); overflow-y: auto; }

  /* Header Styles */
  .rules-panel--header {
    border-left: 3px solid var(--accent-cyan);
  }

  .rules-title-icon {
    vertical-align: middle;
    margin-right: 8px;
    color: var(--accent-cyan);
  }

  .rules-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-lg);
    flex-wrap: wrap;
  }

  .rules-meta {
    display: flex;
    align-items: center;
    gap: var(--space-tight);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
  }

  .meta-badge {
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    font-weight: 600;
    font-size: 10px;
  }

  .meta-badge--active {
    background: rgb(16 185 129 / 0.2);
    color: #34d399;
  }

  .meta-badge--inactive {
    background: var(--surface-container-highest);
    color: var(--on-surface-variant);
  }

  .meta-count {
    font-weight: 500;
    color: var(--on-surface);
  }

  .meta-sep { opacity: 0.4; }

  .meta-item--warnings {
    color: var(--accent-amber);
  }

  .meta-item--conflicts {
    color: #ef4444;
  }

  /* Executive Summary Cards */
  .rules-summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: var(--space-gutter);
  }

  .rules-summary-card {
    padding: var(--space-md);
    border: var(--hairline);
    border-radius: var(--radius-md);
    text-align: center;
    background: var(--surface-container);
  }

  .rules-summary-card--primary { border-color: var(--accent-cyan); }
  .rules-summary-card--success { border-color: #34d399; }
  .rules-summary-card--info { border-color: #22d3ee; }
  .rules-summary-card--purple { border-color: #818cf8; }
  .rules-summary-card--amber { border-color: var(--accent-amber); }
  .rules-summary-card--neutral { border-color: var(--outline-variant); }

  .rules-summary-card__value {
    font-family: var(--font-heading);
    font-size: 24px;
    font-weight: 700;
    color: var(--on-surface);
  }

  .rules-summary-card__label {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 4px;
  }

  /* Tab Navigation */
  .rules-tab-bar {
    display: flex;
    gap: var(--space-xs);
    padding: var(--space-sm);
    background: var(--surface-container);
    border-radius: var(--radius-md);
    border: var(--hairline);
  }

  .rules-tab-btn {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-sm) var(--space-md);
    background: transparent;
    border: none;
    border-radius: var(--radius-sm);
    color: var(--on-surface-variant);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .rules-tab-btn:hover {
    background: var(--surface-container-high);
    color: var(--on-surface);
  }

  .rules-tab-btn--active {
    background: var(--accent-cyan);
    color: #000;
  }

  .rules-tab-btn--active svg {
    color: #000;
  }

  /* Tab Panels */
  .rules-tab-panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-gutter);
  }

  /* Category Breakdown */
  .category-breakdown {
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
    padding: var(--space-md) 0;
  }

  .category-row {
    display: flex;
    align-items: center;
    gap: var(--space-md);
  }

  .category-label {
    width: 100px;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    text-transform: capitalize;
  }

  .category-bar {
    flex: 1;
    height: 8px;
    background: var(--surface-container-high);
    border-radius: 4px;
    overflow: hidden;
  }

  .category-bar__fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s ease;
  }

  .category-value {
    width: 100px;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    text-align: right;
  }

  /* Top Plugins */
  .top-plugins {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .top-plugin-row {
    display: flex;
    align-items: center;
    gap: var(--space-md);
  }

  .top-plugin-name {
    width: 250px;
    font-family: var(--font-mono);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .top-plugin-bar {
    flex: 1;
    height: 6px;
    background: var(--surface-container-high);
    border-radius: 3px;
    overflow: hidden;
  }

  .top-plugin-bar__fill {
    height: 100%;
    background: var(--accent-cyan);
    border-radius: 3px;
  }

  .top-plugin-hits {
    width: 60px;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--accent-cyan);
    text-align: right;
  }

  /* Plugin Registry */
  .plugin-registry {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: var(--space-gutter);
    padding: var(--space-md) 0;
  }

  .plugin-card {
    padding: var(--space-md);
    border: var(--hairline);
    border-radius: var(--radius-md);
    background: var(--surface-container);
  }

  .plugin-card__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-sm);
  }

  .plugin-card__name {
    font-family: var(--font-mono);
    font-size: var(--type-ui-label-size);
    font-weight: 500;
    color: var(--on-surface);
    margin-bottom: var(--space-xs);
  }

  .plugin-card__schema {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    margin-bottom: var(--space-sm);
  }

  .plugin-card__hits {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
  }

  .plugin-hits-bar {
    flex: 1;
    height: 4px;
    background: var(--surface-container-high);
    border-radius: 2px;
    overflow: hidden;
  }

  .plugin-hits-bar__fill {
    height: 100%;
    border-radius: 2px;
  }

  .plugin-hits-count {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--on-surface-variant);
  }

  .plugin-version {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    padding: 2px 6px;
    background: var(--surface-container-high);
    border-radius: var(--radius-sm);
  }

  /* Rules Registry */
  .rules-registry-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-md);
  }

  .rules-search {
    width: 200px;
  }

  .rules-search__input {
    width: 100%;
    padding: var(--space-sm);
    background: var(--surface-container-high);
    border: var(--hairline);
    border-radius: var(--radius-sm);
    color: var(--on-surface);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
  }

  .rules-search__input::placeholder {
    color: var(--on-surface-variant);
  }

  .rules-registry-table {
    display: flex;
    flex-direction: column;
  }

  .rules-registry__header {
    display: flex;
    padding: var(--space-sm) var(--space-gutter);
    background: var(--surface-container-high);
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }

  .rules-registry__row {
    display: flex;
    padding: var(--space-sm) var(--space-gutter);
    border-bottom: 1px solid var(--outline-variant);
    transition: background var(--transition-fast);
  }

  .rules-registry__row:hover {
    background: var(--surface-container-high);
  }

  .rules-registry__row .td--name {
    flex: 1;
    font-family: var(--font-mono);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface);
  }

  .rules-registry__row .td--hits {
    width: 80px;
    font-family: var(--font-mono);
    font-size: var(--type-ui-label-size);
    color: var(--accent-cyan);
    text-align: right;
  }

  .rules-registry__row .td--bar {
    width: 150px;
    padding-left: var(--space-md);
  }

  .rule-activity-bar {
    height: 4px;
    background: var(--surface-container-high);
    border-radius: 2px;
    overflow: hidden;
  }

  .rule-activity-bar__fill {
    height: 100%;
    background: var(--accent-cyan);
    border-radius: 2px;
    transition: width 0.3s ease;
  }

  /* Conflicts Panel */
  .panel--conflicts {
    background: linear-gradient(135deg, rgb(239 68 68 / 0.05), rgb(239 68 68 / 0.02));
    border-color: rgb(239 68 68 / 0.3);
  }

  .conflicts-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-sm);
  }

  .conflicts-title {
    font-family: var(--font-heading);
    font-size: var(--type-headline-sm-size);
    font-weight: var(--type-headline-sm-weight);
    color: var(--on-surface);
  }

  .conflicts-count {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    padding: 2px 8px;
    background: rgb(239 68 68 / 0.15);
    color: #ef4444;
    border-radius: var(--radius-sm);
  }

  .conflicts-subtitle {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
    margin-bottom: var(--space-md);
  }

  .conflicts-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-gutter);
  }

  .conflict-card {
    border-left: 3px solid #ef4444;
  }

  .conflict-card__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-sm);
  }

  .conflict-rules {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
  }

  .conflict-rule {
    font-family: var(--font-mono);
    font-size: var(--type-ui-label-size);
    padding: 2px 8px;
    border-radius: var(--radius-sm);
  }

  .conflict-rule--a {
    background: rgb(239 68 68 / 0.1);
    color: #ef4444;
  }

  .conflict-rule--b {
    background: var(--surface-container-high);
    color: var(--on-surface-variant);
  }

  .conflict-vs {
    color: var(--on-surface-variant);
  }

  .conflict-priority {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
  }

  .conflict-plugins {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-sm);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
  }

  .conflict-arrow {
    color: var(--accent-cyan);
  }

  .conflict-overlap,
  .conflict-resolution {
    display: flex;
    gap: var(--space-sm);
    font-family: var(--font-sans);
    font-size: 11px;
    margin-bottom: 4px;
  }

  .conflict-overlap__label,
  .conflict-resolution__label {
    color: var(--on-surface-variant);
    font-weight: 500;
  }

  .conflict-overlap__value {
    color: var(--accent-amber);
  }

  .conflict-resolution__value {
    color: #34d399;
  }

  /* Loaded Plugins Tab */
  .loaded-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-md);
    padding-bottom: var(--space-sm);
    border-bottom: var(--hairline);
  }

  .loaded-count {
    font-family: var(--font-heading);
    font-size: var(--type-headline-sm-size);
    font-weight: var(--type-headline-sm-weight);
    color: var(--on-surface);
  }

  .loaded-subtitle {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
  }

  .loaded-list {
    display: grid;
    gap: var(--space-sm);
  }

  .loaded-card {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
    padding: var(--space-sm);
    border: var(--hairline);
    border-radius: var(--radius-md);
    transition: box-shadow 0.2s ease;
  }

  .loaded-card:hover {
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.1);
  }

  .loaded-card__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .loaded-card__name {
    font-family: var(--font-mono);
    font-size: var(--type-ui-label-size);
    font-weight: 500;
    color: var(--on-surface);
  }

  .loaded-card__version {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
  }

  .loaded-card__meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .loaded-card__category {
    font-family: var(--font-mono);
    font-size: 10px;
    padding: 2px 8px;
    border-radius: var(--radius-sm);
  }

  .loaded-card__hits {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
  }

  /* Performance Panel */
  .performance-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: var(--space-gutter);
    padding: var(--space-md) 0;
  }

  .performance-card {
    padding: var(--space-md);
    border: var(--hairline);
    border-radius: var(--radius-md);
    background: var(--surface-container);
    text-align: center;
  }

  .performance-card__label {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: var(--space-sm);
  }

  .performance-card__value {
    font-family: var(--font-heading);
    font-size: 20px;
    font-weight: 700;
    color: var(--on-surface);
    margin-bottom: 4px;
  }

  .performance-card__value--success {
    color: #34d399;
  }

  .performance-card__value--neutral {
    color: var(--on-surface-variant);
  }

  .performance-card__detail {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
  }

  .load-stats {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
    padding: var(--space-md) 0;
  }

  .load-stat {
    display: flex;
    justify-content: space-between;
    padding: var(--space-sm);
    background: var(--surface-container-high);
    border-radius: var(--radius-sm);
  }

  .load-stat__label {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
  }

  .load-stat__value {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface);
  }

  /* Empty State */
  .panel--empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 200px;
  }

  .panel--empty .empty-state {
    text-align: center;
  }

  .panel--empty .empty-state svg {
    color: var(--on-surface-variant);
    margin-bottom: var(--space-md);
  }

  .panel--empty .empty-state p {
    color: var(--on-surface);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
  }

  .panel--empty .empty-state__sub {
    color: var(--on-surface-variant);
    font-size: var(--type-terminal-size);
  }

  /* Filters */
  .rules-filters {
    margin-top: var(--space-tight);
  }

  .chip-filter-group {
    display: flex;
    flex-direction: column;
    gap: var(--space-tight);
  }

  .chip-filter-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-sm);
  }

  .filter-label {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .filter-actions {
    display: flex;
    gap: var(--space-xs);
  }

  .chip-action {
    font-family: var(--font-mono);
    font-size: 10px;
    padding: 2px 8px;
    background: var(--surface-container-high);
    border: var(--hairline);
    border-radius: var(--radius-sm);
    color: var(--on-surface-variant);
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .chip-action:hover {
    background: var(--surface-container-highest);
    color: var(--on-surface);
  }

  .chip-filter-chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-tight);
  }

  /* Warnings panel */
  .panel--warnings {
    background: linear-gradient(135deg, rgb(245 158 11 / 0.05), rgb(245 158 11 / 0.02));
    border-color: rgb(245 158 11 / 0.2);
  }

  .warnings-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-bottom: var(--space-md);
    padding-bottom: var(--space-md);
    border-bottom: var(--hairline);
  }

  .warnings-title {
    font-family: var(--font-heading);
    font-size: var(--type-headline-sm-size);
    font-weight: var(--type-headline-sm-weight);
    color: var(--on-surface);
  }

  .warnings-count {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    padding: 2px 8px;
    background: rgb(245 158 11 / 0.15);
    color: var(--accent-amber);
    border-radius: var(--radius-sm);
  }

  .warnings-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .warning-item {
    display: flex;
    align-items: flex-start;
    gap: var(--space-sm);
    padding: var(--space-sm);
    border-radius: var(--radius-sm);
    background: var(--surface-container);
  }

  .warning-item--block,
  .warning-item--error {
    background: rgb(239 68 68 / 0.08);
    border-left: 2px solid var(--error);
  }

  .warning-item--warning {
    background: rgb(245 158 11 / 0.08);
    border-left: 2px solid var(--accent-amber);
  }

  .warning-rule {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    font-weight: 500;
    color: var(--accent-amber);
    white-space: nowrap;
    flex-shrink: 0;
  }

  .warning-message {
    flex: 1;
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface);
    line-height: 1.4;
  }

  .warning-link {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--accent-cyan);
    text-decoration: none;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .warning-link:hover {
    text-decoration: underline;
  }

  .warning-file {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    white-space: nowrap;
    flex-shrink: 0;
  }

  .warnings-more {
    text-align: center;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    padding: var(--space-sm);
  }

  /* Rules groups */
  .rules-content {
    display: flex;
    flex-direction: column;
    gap: var(--space-lg);
  }

  .rules-group {
    border: var(--hairline);
    border-radius: var(--radius-md);
    overflow: hidden;
  }

  .rules-group__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-md);
    padding: var(--space-md) var(--space-gutter);
    background: var(--surface-container-high);
    border-bottom: var(--hairline);
  }

  .plugin-badge {
    display: inline-flex;
    padding: 2px 10px;
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }

  .rules-group__stats {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
  }

  .stats-sep { opacity: 0.4; }

  .warning-stat {
    color: var(--accent-amber);
  }

  /* Rules table */
  .rules-group__table {
    padding: var(--space-tight);
  }

  .rules-table {
    display: flex;
    flex-direction: column;
  }

  .rules-table__header {
    display: flex;
    align-items: center;
    padding: var(--space-sm) var(--space-gutter);
    background: var(--surface-container);
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }

  .rules-table__row {
    display: flex;
    align-items: center;
    padding: var(--space-sm) var(--space-gutter);
    border-bottom: 1px solid var(--outline-variant);
    transition: background var(--transition-fast);
  }

  .rules-table__row:hover {
    background: var(--surface-container-high);
  }

  .rules-table__row--disabled {
    opacity: 0.6;
  }

  .th, .td {
    padding: 0 var(--space-xs);
  }

  .th--severity, .td--severity { width: 70px; }
  .th--name, .td--name { flex: 1; min-width: 200px; }
  .th--matches, .td--matches { width: 100px; text-align: right; }
  .th--warnings, .td--warnings { width: 80px; text-align: center; }

  .rule-name-cell {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .rule-name {
    font-weight: 500;
    color: var(--on-surface);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .rule-description {
    font-size: 11px;
    color: var(--on-surface-variant);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .match-count {
    color: var(--accent-cyan);
    text-decoration: none;
    font-weight: 500;
  }

  .match-count:hover {
    text-decoration: underline;
  }

  .match-count--zero {
    color: var(--on-surface-variant);
    opacity: 0.5;
  }

  .status-badge {
    display: inline-flex;
    padding: 1px 6px;
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 500;
  }

  .status-badge--ok {
    background: rgb(16 185 129 / 0.15);
    color: #34d399;
  }

  .status-badge--disabled {
    background: var(--surface-container-highest);
    color: var(--on-surface-variant);
  }

  /* Empty state */
  .empty-state {
    color: var(--on-surface-variant);
    font-family: var(--font-mono);
    font-size: var(--type-node-code-size);
    padding: var(--space-gutter);
    text-align: center;
  }

  .empty-state code {
    color: var(--accent-cyan);
  }

  /* Error panel */
  .error-panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: var(--space-2xl);
    text-align: center;
  }

  .error-panel__icon {
    color: var(--error);
    margin-bottom: var(--space-md);
  }

  .error-panel__title {
    font-family: var(--font-heading);
    font-size: var(--type-headline-md-size);
    font-weight: var(--type-headline-md-weight);
    color: var(--on-surface);
    margin-bottom: var(--space-sm);
  }

  .error-panel__message {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    color: var(--on-surface-variant);
    margin-bottom: var(--space-lg);
  }

  .error-panel__actions {
    display: flex;
    gap: var(--space-sm);
  }
`;

function injectStyles() {
  if (document.getElementById('rules-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'rules-styles';
  styleEl.textContent = rulesStyles;
  document.head.appendChild(styleEl);
}

injectStyles();
