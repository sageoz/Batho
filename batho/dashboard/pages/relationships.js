/**
 * Relationships page - Enterprise-grade relationship explorer with advanced filtering.
 * 
 * Enterprise Features:
 * - Executive summary cards with relationship metrics
 * - Advanced filtering by kind, source, target, file
 * - Real-time search across relationships
 * - Export to JSON/CSV
 * - Visual relationship graph preview
 * - Stacked bar chart distribution
 * - Enterprise icons and animations
 */

import { loadIndex, getSnapshotFileList, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { formatInt } from '../assets/js/format.js';
import { createDataTable, setRows } from '../shared/components/data-table.js';
import { createChipFilter, setChipActive } from '../shared/components/chip-filter.js';
import { router } from '../assets/js/router.js';

// Relationship kind colors (from design system)
const KIND_COLORS = {
  CALLS: { bg: 'rgb(79 70 229 / 0.15)', color: '#818cf8', border: '#4f46e5' },
  CALLS_ASYNC: { bg: 'rgb(79 70 229 / 0.1)', color: '#a5b4fc', border: '#6366f1' },
  IMPORTS: { bg: 'rgb(6 182 212 / 0.15)', color: '#22d3ee', border: '#06b6d4' },
  INHERITS: { bg: 'rgb(16 185 129 / 0.15)', color: '#34d399', border: '#10b981' },
  INHERITS_FROM: { bg: 'rgb(16 185 129 / 0.15)', color: '#34d399', border: '#10b981' },
  IMPLEMENTS: { bg: 'rgb(245 158 11 / 0.15)', color: '#fbbf24', border: '#f59e0b' },
  USES: { bg: 'rgb(168 85 247 / 0.15)', color: '#c4b5fd', border: '#8b5cf6' },
  CONTROLS: { bg: 'rgb(239 68 68 / 0.15)', color: '#f87171', border: '#ef4444' },
  READS: { bg: 'rgb(20 184 166 / 0.15)', color: '#2dd4bf', border: '#14b8a6' },
  WRITES: { bg: 'rgb(236 72 153 / 0.15)', color: '#f472b6', border: '#ec4899' },
  MUTATES: { bg: 'rgb(236 72 153 / 0.2)', color: '#ec4899', border: '#db2777' },
  RAISES: { bg: 'rgb(249 115 22 / 0.15)', color: '#fb923c', border: '#f97316' },
  CATCHES: { bg: 'rgb(34 197 94 / 0.15)', color: '#4ade80', border: '#22c55e' },
  REFERENCES: { bg: 'rgb(120 120 120 / 0.15)', color: '#9ca3af', border: '#6b7280' },
  UNKNOWN: { bg: 'rgb(120 120 120 / 0.15)', color: '#9ca3af', border: '#6b7280' },
};

// Enterprise SVG Icons
const ICONS = {
  gitBranch: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="6" y1="3" x2="6" y2="15"></line><circle cx="18" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><path d="M18 9a9 9 0 0 1-9 9"></path></svg>`,
  layers: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,
  code: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`,
  activity: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 6 12 2 12"/></svg>`,
};

// Render summary card for metrics
function renderSummaryCard({ label, value, subtitle, icon, color = 'primary' }) {
  const colorMap = {
    primary: { border: 'var(--accent-cyan)', icon: 'var(--accent-cyan)' },
    info: { border: '#818cf8', icon: '#818cf8' },
    success: { border: '#34d399', icon: '#34d399' },
    purple: { border: '#c4b5fd', icon: '#c4b5fd' },
  };
  const colors = colorMap[color] || colorMap.primary;
  
  return `
    <div class="summary-card summary-card--${color}" style="border-color: ${colors.border}">
      <div class="summary-card__icon" style="color: ${colors.icon}">${icon}</div>
      <div class="summary-card__value">${value}</div>
      ${subtitle ? `<div class="summary-card__subtitle">${subtitle}</div>` : ''}
      <div class="summary-card__label">${label}</div>
    </div>
  `;
}

export async function renderRelationships(params) {
  const container = document.createElement('div');
  container.className = 'page page--relationships';
  container.innerHTML = `<div class="panel" aria-busy="true"><div class="loading"><span class="loading__cursor"></span><span>loading relationships …</span></div></div>`;

  try {
    // Parse URL parameters
    const urlParams = new URLSearchParams(window.location.hash.split('?')[1] || '');
    const initialKindFilter = urlParams.get('kind') || params?.get('kind') || '';
    const initialFileFilter = urlParams.get('file') || params?.get('file') || '';

    const savedIndexId = localStorage.getItem('batho.activeIndexId');
    const indexData = await loadIndex();
    const activeIndexId = savedIndexId && indexData.indexes[savedIndexId]
      ? savedIndexId
      : indexData.currentIndexId;

    const snapshotId = indexData.indexes[activeIndexId]?.snapshotId || indexData.indexes[activeIndexId]?.snapshot_id;
    if (!snapshotId) {
      throw new Error(`No snapshot available for index ${activeIndexId}`);
    }

    const graphData = await getSnapshotFileList(snapshotId).catch((err) => {
      if (err.name === 'MissingArtifactError') return null;
      throw err;
    });

    if (!graphData || !graphData.relationships?.length) {
      container.innerHTML = `
        <div class="relationships">
          <div class="panel panel--header">
            <div class="relationships-header">
              <div class="header-title-section">
                <h1 class="panel__title">
                  <svg class="title-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="5" cy="12" r="3"/>
                    <circle cx="19" cy="5" r="3"/>
                    <circle cx="19" cy="19" r="3"/>
                    <path d="M8 10.5l8-4.5M8 13.5l8 4.5"/>
                  </svg>
                  Code Relationships
                </h1>
              </div>
            </div>
          </div>
          <div class="panel panel--empty">
            <div class="empty-state">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <circle cx="12" cy="12" r="10"/>
                <path d="M8 12h8M12 8v8"/>
              </svg>
              <p>No relationships found in current index.</p>
              <p class="empty-state__sub">Relationships will appear after indexing your codebase.</p>
              <p class="empty-state__sub">Run: <code>batho index --root . --verbose</code></p>
            </div>
          </div>
        </div>
      `;
      return container;
    }

    // Transform relationships for display
    const relationshipRows = graphData.relationships.map(r => {
      const source = graphData.entitiesById?.[r.sourceId || r.source_id || r.from];
      const target = graphData.entitiesById?.[r.targetId || r.target_id || r.to];
      const kind = (r.relationshipType || r.relationship_type || r.type || 'UNKNOWN').toUpperCase();
      const isDerived = r.derived === true || r.is_derived === true || r.isDerived === true;

      return {
        id: r.id || `${r.sourceId || r.source_id || r.from}->${r.targetId || r.target_id || r.to}`,
        kind,
        source,
        target,
        sourceId: r.sourceId || r.source_id || r.from,
        targetId: r.targetId || r.target_id || r.to,
        file: r.file || source?.file || '',
        isDerived,
        raw: r,
      };
    });

    // Compute kind counts for filters
    const kindCounts = {};
    relationshipRows.forEach(r => {
      kindCounts[r.kind] = (kindCounts[r.kind] || 0) + 1;
    });
    const sortedKinds = Object.entries(kindCounts).sort((a, b) => b[1] - a[1]);

    // Active kind filters (default all active unless URL specifies)
    const activeKinds = new Set(
      initialKindFilter
        ? initialKindFilter.split(',').filter(k => kindCounts[k.toUpperCase()])
        : Object.keys(kindCounts)
    );

    const totalRels = relationshipRows.length;
    const derivedCount = relationshipRows.filter(r => r.isDerived).length;
    const extractedCount = totalRels - derivedCount;

    // Calculate distribution for chart
    const kindPercentages = sortedKinds.map(([kind, count]) => ({
      kind,
      count,
      pct: (count / totalRels) * 100
    }));

    container.innerHTML = `
      <div class="relationships">
        <!-- Compact Header with Stats -->
        <div class="rel-header">
          <div class="rel-header-main">
            <div class="rel-title-section">
              <svg class="rel-title-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="5" cy="12" r="3"/>
                <circle cx="19" cy="5" r="3"/>
                <circle cx="19" cy="19" r="3"/>
                <path d="M8 10.5l8-4.5M8 13.5l8 4.5"/>
              </svg>
              <span class="rel-title">Relationships</span>
              <span class="rel-badge" title="Live index data">
                <span class="rel-badge-dot"></span>
                <span class="rel-badge-text">Live</span>
              </span>
            </div>
            <div class="rel-stats">
              <span class="rel-stat" title="Total relationships">${formatInt(totalRels)} total</span>
              <span class="rel-stat-sep">·</span>
              <span class="rel-stat" title="Extracted from AST">${formatInt(extractedCount)} extracted</span>
              <span class="rel-stat-sep">·</span>
              <span class="rel-stat" title="Derived by BSG">${formatInt(derivedCount)} derived</span>
            </div>
          </div>
          <div class="rel-header-actions">
            <div class="rel-search">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"/>
                <line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input type="text" id="rel-search" placeholder="Search..." class="rel-search-input">
            </div>
            <button class="rel-btn" id="export-json" title="Export JSON">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </button>
            <button class="rel-btn" id="export-csv" title="Export CSV">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Main Content: Sidebar + Table -->
        <div class="rel-content">
          <!-- Sidebar: Filters & Distribution -->
          <div class="rel-sidebar">
            <!-- Distribution Mini-Chart -->
            <div class="rel-panel">
              <div class="rel-panel-title">Distribution</div>
              <div class="rel-dist-list">
                ${kindPercentages.slice(0, 8).map(({kind, count, pct}) => {
                  const colors = KIND_COLORS[kind] || KIND_COLORS.UNKNOWN;
                  return `
                    <div class="rel-dist-item" title="${kind}: ${formatInt(count)} (${pct.toFixed(1)}%)">
                      <div class="rel-dist-bar-wrap">
                        <div class="rel-dist-bar" style="width: ${pct}%; background: ${colors.color}"></div>
                      </div>
                      <span class="rel-dist-kind">${kind}</span>
                      <span class="rel-dist-count">${formatInt(count)}</span>
                    </div>
                  `;
                }).join('')}
                ${kindPercentages.length > 8 ? `<div class="rel-dist-more">+${kindPercentages.length - 8} more</div>` : ''}
              </div>
            </div>

            <!-- Kind Filters -->
            <div class="rel-panel">
              <div class="rel-panel-header">
                <span class="rel-panel-title">Filter by Kind</span>
                <div class="rel-filter-actions">
                  <button class="rel-filter-action" data-action="all-kinds">All</button>
                  <button class="rel-filter-action" data-action="none-kinds">None</button>
                </div>
              </div>
              <div class="rel-kind-chips" id="kind-chips"></div>
            </div>
          </div>

          <!-- Table Area -->
          <div class="rel-table-area">
            <div class="rel-table-header">
              <span class="rel-table-count" id="rels-count">${formatInt(totalRels)} relationships</span>
            </div>
            <div class="relationships-table-mount" id="rels-table-mount"></div>
          </div>
        </div>
      </div>
    `;

    const tableMount = container.querySelector('#rels-table-mount');
    const kindChipsContainer = container.querySelector('#kind-chips');
    const countEl = container.querySelector('#rels-count');

    // Create kind filter chips
    const kindChipElements = [];
    sortedKinds.forEach(([kind, count]) => {
      const chip = createChipFilter({
        label: `${kind} (${formatInt(count)})`,
        count: 0, // Count is in label
        active: activeKinds.has(kind),
        onChange: (active) => {
          if (active) activeKinds.add(kind);
          else activeKinds.delete(kind);
          applyFilters();
          updateUrl();
        },
      });
      chip.dataset.kind = kind;
      chip.style.setProperty('--chip-color', KIND_COLORS[kind]?.color || '#9ca3af');
      kindChipsContainer.appendChild(chip);
      kindChipElements.push({ kind, chip });
    });

    // Bulk actions for kinds
    container.querySelector('[data-action="all-kinds"]')?.addEventListener('click', () => {
      sortedKinds.forEach(([kind]) => activeKinds.add(kind));
      kindChipElements.forEach(({ kind, chip }) => setChipActive(chip, activeKinds.has(kind)));
      applyFilters();
      updateUrl();
    });

    container.querySelector('[data-action="none-kinds"]')?.addEventListener('click', () => {
      activeKinds.clear();
      kindChipElements.forEach(({ chip }) => setChipActive(chip, false));
      applyFilters();
      updateUrl();
    });

    // Create table with optimized column widths
    const table = createDataTable({
      columns: [
        {
          key: 'kind',
          label: 'Kind',
          width: '90px',
          render: (row) => renderKindBadge(row.kind)
        },
        {
          key: 'source',
          label: 'Source',
          width: '280px',
          render: (row) => renderEntityRef(row.source, row.sourceId)
        },
        {
          key: 'arrow',
          label: '',
          width: '24px',
          render: () => `<span class="rel-arrow">→</span>`
        },
        {
          key: 'target',
          label: 'Target',
          width: '280px',
          render: (row) => renderEntityRef(row.target, row.targetId)
        },
        {
          key: 'file',
          label: 'File',
          width: '200px',
          render: (row) => {
            const f = row.file || '';
            if (!f) return '<span class="file-ref file-ref--empty">—</span>';
            // Show last 3 path segments for better context
            const parts = f.split('/');
            const short = parts.slice(-3).join('/');
            return `<span class="file-ref" title="${escapeHtml(f)}">${escapeHtml(short)}</span>`;
          }
        },
        {
          key: 'type',
          label: 'Type',
          width: '70px',
          render: (row) => renderEdgeType(row.isDerived)
        },
      ],
      rows: relationshipRows,
      rowHeight: 32,
      buffer: 10,
      onRowClick: (row) => {
        // Navigate to source entity in hypergraph
        if (row.sourceId) {
          router.navigate(`#/hypergraph/node/${encodeURIComponent(row.sourceId)}`);
        }
      },
      emptyMessage: 'No relationships match the filters',
    });
    table.style.height = '100%';
    tableMount.appendChild(table);

    // Search functionality
    const searchInput = container.querySelector('#rel-search');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        if (!query) {
          applyFilters();
          return;
        }
        
        let filtered = relationshipRows.filter(r => {
          const sourceMatch = r.source?.name?.toLowerCase().includes(query) || 
                          r.sourceId.toLowerCase().includes(query);
          const targetMatch = r.target?.name?.toLowerCase().includes(query) || 
                          r.targetId.toLowerCase().includes(query);
          const kindMatch = r.kind.toLowerCase().includes(query);
          const fileMatch = r.file?.toLowerCase().includes(query);
          return sourceMatch || targetMatch || kindMatch || fileMatch;
        });
        
        // Also apply kind filter
        if (activeKinds.size > 0 && activeKinds.size < sortedKinds.length) {
          filtered = filtered.filter(r => activeKinds.has(r.kind));
        }
        
        setRows(table, filtered);
        if (countEl) countEl.textContent = formatInt(filtered.length);
      });
    }

    // Export buttons
    container.querySelector('#export-json')?.addEventListener('click', () => {
      const data = {
        exported_at: new Date().toISOString(),
        total: relationshipRows.length,
        relationships: relationshipRows.map(r => ({
          id: r.id,
          kind: r.kind,
          source: r.source?.name || r.sourceId,
          target: r.target?.name || r.targetId,
          file: r.file,
          type: r.isDerived ? 'derived' : 'extracted'
        }))
      };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `relationships_${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    });

    container.querySelector('#export-csv')?.addEventListener('click', () => {
      const headers = ['ID', 'Kind', 'Source', 'Target', 'File', 'Type'];
      const rows = relationshipRows.map(r => [
        r.id,
        r.kind,
        r.source?.name || r.sourceId,
        r.target?.name || r.targetId,
        r.file,
        r.isDerived ? 'derived' : 'extracted'
      ]);
      const csv = [headers, ...rows].map(row => 
        row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')
      ).join('\n');
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `relationships_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    });

    function applyFilters() {
      let filtered = relationshipRows;
      // Apply kind filter if not all kinds are selected
      if (activeKinds.size === 0) {
        // No kinds selected - show empty (or could show all, but "None" suggests no filter)
        filtered = [];
      } else if (activeKinds.size < sortedKinds.length) {
        // Some kinds selected - filter to only those kinds
        filtered = filtered.filter(r => activeKinds.has(r.kind));
      }
      // If all kinds selected, show all rows (no filtering needed)
      setRows(table, filtered);
      if (countEl) countEl.textContent = formatInt(filtered.length);
    }

    function updateUrl() {
      const kindStr = activeKinds.size === sortedKinds.length
        ? ''
        : Array.from(activeKinds).join(',');
      const params = new URLSearchParams();
      if (kindStr) params.set('kind', kindStr);
      const newHash = `#/relationships${params.toString() ? '?' + params.toString() : ''}`;
      if (window.location.hash !== newHash) {
        history.replaceState(null, '', newHash);
      }
    }

    // Initial filter application
    if (activeKinds.size !== sortedKinds.length) {
      applyFilters();
    }

  } catch (err) {
    container.innerHTML = renderErrorPanel(err);
  }
  return container;
}

function renderKindBadge(kind) {
  const colors = KIND_COLORS[kind] || KIND_COLORS.UNKNOWN;
  return `<span class="kind-badge" style="background: ${colors.bg}; color: ${colors.color}; border-color: ${colors.border}">${escapeHtml(kind)}</span>`;
}

function renderEntityRef(entity, entityId) {
  if (!entity) {
    return `<span class="entity-ref entity-ref--missing" title="Entity ${escapeHtml(entityId)} not found"><code>${escapeHtml(entityId?.slice(-20) || 'unknown')}</code></span>`;
  }
  // Get better name - use entity.name or extract from ID
  let name = entity.name || '';
  if (!name || name === 'document' || name === 'DOCUMENT') {
    // Try to get a better name from the ID or file path
    const idParts = entityId?.split('/') || [];
    const lastPart = idParts[idParts.length - 1] || '';
    name = lastPart.replace(/^[a-f0-9]+_/, '').replace(/_/g, ' ') || 'unnamed';
  }
  const type = entity.type || 'UNKNOWN';
  // Show shorter type labels
  const shortType = type.replace(/^(CLASS|FUNCTION|METHOD|VARIABLE|CONSTANT)_/, '');
  return `
    <div class="entity-ref">
      <span class="entity-ref__name">${escapeHtml(name)}</span>
      <span class="entity-ref__type">${escapeHtml(shortType)}</span>
    </div>
  `;
}

function renderEdgeType(isDerived) {
  if (isDerived) {
    return `
      <span class="edge-type edge-type--derived" title="Derived by BSG rule">
        <svg class="edge-icon" width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="8" cy="8" r="5" stroke-dasharray="2 1"/>
        </svg>
        <span class="edge-type__label">Derived</span>
      </span>
    `;
  }
  return `
    <span class="edge-type edge-type--extracted" title="Extracted from AST">
      <svg class="edge-icon" width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="8" cy="8" r="5"/>
      </svg>
      <span class="edge-type__label">AST</span>
    </span>
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

const relationshipsStyles = `
  .page--relationships { height: 100%; overflow: hidden; }
  .relationships { display: flex; flex-direction: column; height: 100%; padding: var(--space-gutter); gap: var(--space-gutter); }

  /* Compact Header */
  .rel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-md);
    padding: var(--space-sm) var(--space-md);
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: var(--radius-md);
    flex-shrink: 0;
  }

  .rel-header-main {
    display: flex;
    align-items: center;
    gap: var(--space-md);
  }

  .rel-title-section {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
  }

  .rel-title-icon {
    color: var(--accent-cyan);
    flex-shrink: 0;
  }

  .rel-title {
    font-family: var(--font-heading);
    font-size: var(--type-headline-sm-size);
    font-weight: var(--type-headline-sm-weight);
    color: var(--on-surface);
  }

  .rel-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    background: rgb(34 197 94 / 0.15);
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: 10px;
    color: #4ade80;
    border: 1px solid rgb(34 197 94 / 0.3);
  }

  .rel-badge-dot {
    width: 6px;
    height: 6px;
    background: #4ade80;
    border-radius: 50%;
    animation: pulse-live 2s ease-in-out infinite;
  }

  @keyframes pulse-live {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
  }

  .rel-badge-text {
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .rel-stats {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--on-surface-variant);
  }

  .rel-stat {
    font-weight: 500;
  }

  .rel-stat-sep { opacity: 0.4; }

  .rel-header-actions {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
  }

  /* Search */
  .rel-search {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    background: var(--surface-container-highest);
    border: var(--hairline);
    border-radius: var(--radius-md);
    transition: border-color 0.2s ease;
  }

  .rel-search:focus-within {
    border-color: var(--accent-cyan);
  }

  .rel-search svg {
    color: var(--on-surface-variant);
    flex-shrink: 0;
  }

  .rel-search-input {
    border: none;
    background: transparent;
    color: var(--on-surface);
    font-family: var(--font-sans);
    font-size: 13px;
    outline: none;
    width: 140px;
  }

  .rel-search-input::placeholder {
    color: var(--on-surface-variant);
  }

  /* Icon Buttons */
  .rel-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    background: var(--surface-container-highest);
    border: var(--hairline);
    border-radius: var(--radius-md);
    color: var(--on-surface-variant);
    cursor: pointer;
    transition: all 0.2s ease;
  }

  .rel-btn:hover {
    background: var(--surface-container);
    color: var(--on-surface);
    border-color: var(--on-surface-variant);
  }

  /* Main Content Layout */
  .rel-content {
    display: flex;
    gap: var(--space-gutter);
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  /* Sidebar */
  .rel-sidebar {
    display: flex;
    flex-direction: column;
    gap: var(--space-gutter);
    width: 280px;
    flex-shrink: 0;
    overflow-y: auto;
  }

  .rel-panel {
    padding: var(--space-md);
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: var(--radius-md);
  }

  .rel-panel-title {
    font-family: var(--font-heading);
    font-size: var(--type-ui-label-size);
    font-weight: 600;
    color: var(--on-surface);
    margin-bottom: var(--space-sm);
  }

  .rel-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-sm);
  }

  /* Distribution Mini-Chart */
  .rel-dist-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .rel-dist-item {
    display: grid;
    grid-template-columns: 1fr 80px 40px;
    align-items: center;
    gap: var(--space-xs);
    font-size: 11px;
  }

  .rel-dist-bar-wrap {
    height: 16px;
    background: var(--surface-container-highest);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }

  .rel-dist-bar {
    height: 100%;
    border-radius: var(--radius-sm);
    transition: width 0.3s ease;
  }

  .rel-dist-kind {
    font-family: var(--font-mono);
    color: var(--on-surface-variant);
    text-transform: uppercase;
    font-size: 10px;
  }

  .rel-dist-count {
    font-family: var(--font-mono);
    color: var(--on-surface);
    text-align: right;
    font-weight: 500;
  }

  .rel-dist-more {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    text-align: center;
    padding: var(--space-xs);
    font-style: italic;
  }

  /* Filter Actions */
  .rel-filter-actions {
    display: flex;
    gap: 4px;
  }

  .rel-filter-action {
    padding: 2px 8px;
    background: transparent;
    border: var(--hairline);
    border-radius: var(--radius-sm);
    color: var(--on-surface-variant);
    font-family: var(--font-mono);
    font-size: 10px;
    cursor: pointer;
    transition: all 0.2s ease;
  }

  .rel-filter-action:hover {
    background: var(--surface-container-high);
    color: var(--on-surface);
  }

  .rel-kind-chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
  }

  /* Table Area */
  .rel-table-area {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: var(--radius-md);
    overflow: hidden;
  }

  .rel-table-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-sm) var(--space-md);
    border-bottom: var(--hairline);
    background: var(--surface-container-high);
  }

  .rel-table-count {
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--on-surface-variant);
  }

  .relationships-table-mount {
    flex: 1;
    min-height: 0;
    overflow: auto;
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
    gap: var(--space-xs);
    max-height: 200px;
    overflow-y: auto;
  }

  /* Arrow between source/target */
  .rel-arrow {
    color: var(--on-surface-variant);
    font-size: 14px;
    text-align: center;
  }

  /* Kind badge */
  .kind-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    border: 1px solid;
  }

  /* Entity reference */
  .entity-ref {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
    line-height: 1.3;
  }

  .entity-ref__name {
    font-family: var(--font-mono);
    font-size: 12px;
    font-weight: 500;
    color: var(--on-surface);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .entity-ref__type {
    font-family: var(--font-mono);
    font-size: 9px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.02em;
  }

  .entity-ref--missing {
    opacity: 0.6;
  }

  .entity-ref--missing code {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
  }

  /* File reference */
  .file-ref {
    font-family: var(--font-mono);
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--on-surface-variant);
    opacity: 0.8;
  }

  .file-ref:hover {
    opacity: 1;
    color: var(--on-surface);
  }

  .file-ref--empty {
    opacity: 0.4;
    font-style: italic;
  }

  /* Edge type badges */
  .edge-type {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: 9px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    border: 1px solid;
    white-space: nowrap;
  }

  .edge-type--extracted {
    background: rgb(6 182 212 / 0.1);
    color: var(--accent-cyan);
    border-color: rgb(6 182 212 / 0.3);
  }

  .edge-type--derived {
    background: rgb(168 85 247 / 0.1);
    color: #c4b5fd;
    border-color: rgb(168 85 247 / 0.3);
  }

  .edge-icon {
    flex-shrink: 0;
  }

  .edge-type__label {
    font-size: 9px;
  }

  /* Derived icon animation */
  .edge-type--derived .edge-icon {
    animation: dash-rotate 20s linear infinite;
  }

  @keyframes dash-rotate {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  /* Table container */
  .relationships-table-mount {
    flex: 1;
    min-height: 0;
    overflow: auto;
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

  /* Empty state */
  .panel--empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 200px;
  }

  .empty-state {
    text-align: center;
    padding: var(--space-2xl);
  }

  .empty-state svg {
    color: var(--on-surface-variant);
    margin-bottom: var(--space-md);
  }

  .empty-state p {
    color: var(--on-surface);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    margin: 0;
  }

  .empty-state__sub {
    color: var(--on-surface-variant);
    font-size: var(--type-terminal-size);
    margin-top: var(--space-sm);
  }

  .empty-state code {
    color: var(--accent-cyan);
    font-family: var(--font-mono);
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
  if (document.getElementById('relationships-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'relationships-styles';
  styleEl.textContent = relationshipsStyles;
  document.head.appendChild(styleEl);
}

injectStyles();
