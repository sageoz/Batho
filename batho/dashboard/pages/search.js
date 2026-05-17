/**
 * Search page - full-text search across entities, files, and rules.
 * Features fuzzy matching, filters, recent searches, and keyboard navigation.
 */

import { loadIndex, loadGraph, loadBsg, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { formatInt } from '../assets/js/format.js';
import { router } from '../assets/js/router.js';

// Search index cache
let searchIndexCache = null;
let searchIndexPromise = null;

// Recent searches (localStorage)
const RECENT_SEARCHES_KEY = 'batho.recentSearches';
const MAX_RECENT_SEARCHES = 10;

// Current search state
let searchState = {
  query: '',
  filter: 'all', // all, entities, files, relationships, rules
  results: [],
  loading: false,
  selectedIndex: -1,
};

export async function renderSearch(params) {
  const container = document.createElement('div');
  container.className = 'page page--search';

  // Parse URL params
  const urlParams = new URLSearchParams(window.location.hash.split('?')[1] || '');
  const initialQuery = urlParams.get('q') || params?.get('q') || '';
  const initialFilter = urlParams.get('filter') || params?.get('filter') || 'all';

  searchState.query = initialQuery;
  searchState.filter = initialFilter;

  container.innerHTML = `
    <div class="search-page">
      <div class="panel search-panel">
        <div class="search-header">
          <h1 class="panel__title">
            <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"/>
              <path d="M21 21l-4.35-4.35"/>
            </svg>
            Search
          </h1>
          <div class="search-shortcut-hint">
            <kbd>Cmd</kbd>+<kbd>K</kbd> to focus
          </div>
        </div>

        <div class="search-input-wrapper">
          <input
            type="text"
            class="search-input"
            id="search-input"
            placeholder="Search entities, files, relationships, rules..."
            value="${escapeHtml(initialQuery)}"
            autocomplete="off"
            aria-label="Search"
            aria-autocomplete="list"
            aria-controls="search-results"
          />
          <button class="search-clear" id="search-clear" aria-label="Clear search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <div class="search-filters" role="radiogroup" aria-label="Search filter">
          ${renderFilterChips(initialFilter)}
        </div>
      </div>

      <div class="search-results-panel" id="search-results-panel">
        ${initialQuery ? renderLoadingState() : renderEmptyState()}
      </div>
    </div>
  `;

  // Wire up search input
  const searchInput = container.querySelector('#search-input');
  const searchClear = container.querySelector('#search-clear');
  const resultsPanel = container.querySelector('#search-results-panel');

  // Build search index in background
  buildSearchIndex().then(index => {
    if (initialQuery) {
      executeSearch(initialQuery, initialFilter, index, resultsPanel);
    }
  });

  // Input event handler with debounce
  let debounceTimer;
  searchInput.addEventListener('input', (e) => {
    const query = e.target.value.trim();
    searchState.query = query;

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      if (query) {
        searchIndexCache
          ? executeSearch(query, searchState.filter, searchIndexCache, resultsPanel)
          : buildSearchIndex().then(index => executeSearch(query, searchState.filter, index, resultsPanel));
      } else {
        resultsPanel.innerHTML = renderEmptyState();
      }
      updateUrl(query, searchState.filter);
    }, 150);
  });

  // Keyboard navigation
  searchInput.addEventListener('keydown', (e) => {
    const results = resultsPanel.querySelectorAll('.search-result-item');

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        searchState.selectedIndex = Math.min(searchState.selectedIndex + 1, results.length - 1);
        updateSelection(results);
        break;
      case 'ArrowUp':
        e.preventDefault();
        searchState.selectedIndex = Math.max(searchState.selectedIndex - 1, -1);
        updateSelection(results);
        break;
      case 'Enter':
        e.preventDefault();
        if (searchState.selectedIndex >= 0 && results[searchState.selectedIndex]) {
          results[searchState.selectedIndex].click();
        } else if (searchState.query) {
          // Save to recent searches
          saveRecentSearch(searchState.query, searchState.filter);
        }
        break;
      case 'Escape':
        searchInput.blur();
        searchState.selectedIndex = -1;
        updateSelection(results);
        break;
    }
  });

  // Clear button
  searchClear.addEventListener('click', () => {
    searchInput.value = '';
    searchInput.focus();
    searchState.query = '';
    resultsPanel.innerHTML = renderEmptyState();
    updateUrl('', searchState.filter);
  });

  // Filter chips
  container.querySelectorAll('.search-filter-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const filter = chip.dataset.filter;
      searchState.filter = filter;

      // Update UI
      container.querySelectorAll('.search-filter-chip').forEach(c => {
        c.classList.toggle('search-filter-chip--active', c.dataset.filter === filter);
        c.setAttribute('aria-checked', c.dataset.filter === filter);
      });

      // Re-execute search if query exists
      if (searchState.query) {
        searchIndexCache
          ? executeSearch(searchState.query, filter, searchIndexCache, resultsPanel)
          : buildSearchIndex().then(index => executeSearch(searchState.query, filter, index, resultsPanel));
      }
      updateUrl(searchState.query, filter);
    });
  });

  // Global keyboard shortcut (Cmd/Ctrl + K)
  const keydownHandler = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      searchInput.focus();
      searchInput.select();
    }
  };
  document.addEventListener('keydown', keydownHandler);

  // Cleanup on page unmount
  container.addEventListener('remove', () => {
    document.removeEventListener('keydown', keydownHandler);
  }, { once: true });

  // Focus input on load
  setTimeout(() => searchInput.focus(), 100);

  return container;
}

function renderFilterChips(activeFilter) {
  const filters = [
    { key: 'all', label: 'All', icon: 'M4 6h16M4 12h16M4 18h16' },
    { key: 'entities', label: 'Entities', icon: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4' },
    { key: 'files', label: 'Files', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8' },
    { key: 'relationships', label: 'Relationships', icon: 'M7 17L17 7M17 7H7M17 7V17' },
    { key: 'rules', label: 'Rules', icon: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5' },
  ];

  return filters.map(f => `
    <button
      class="search-filter-chip ${activeFilter === f.key ? 'search-filter-chip--active' : ''}"
      data-filter="${f.key}"
      role="radio"
      aria-checked="${activeFilter === f.key}"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="${f.icon}"/>
      </svg>
      <span>${f.label}</span>
    </button>
  `).join('');
}

function renderLoadingState() {
  return `
    <div class="search-loading">
      <span class="loading__cursor"></span>
      <span>Searching...</span>
    </div>
  `;
}

function renderEmptyState() {
  const recentSearches = getRecentSearches();

  return `
    <div class="search-empty">
      ${recentSearches.length > 0 ? `
        <div class="search-recent">
          <div class="search-recent__title">Recent Searches</div>
          <div class="search-recent__list">
            ${recentSearches.map(s => `
              <button class="search-recent__item" data-query="${escapeHtml(s.query)}" data-filter="${s.filter}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="11" cy="11" r="8"/>
                  <path d="M21 21l-4.35-4.35"/>
                </svg>
                <span>${escapeHtml(s.query)}</span>
                <span class="search-recent__filter">${s.filter}</span>
              </button>
            `).join('')}
          </div>
        </div>
      ` : ''}
      <div class="search-hints">
        <div class="search-hint">
          <kbd>↑</kbd><kbd>↓</kbd> to navigate
        </div>
        <div class="search-hint">
          <kbd>↵</kbd> to select
        </div>
        <div class="search-hint">
          <kbd>esc</kbd> to close
        </div>
      </div>
    </div>
  `;
}

function renderResults(results, query) {
  if (results.length === 0) {
    return `
      <div class="search-no-results">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="11" cy="11" r="8"/>
          <path d="M21 21l-4.35-4.35"/>
          <line x1="8" y1="8" x2="14" y2="14"/>
          <line x1="14" y1="8" x2="8" y2="14"/>
        </svg>
        <p>No results for "<strong>${escapeHtml(query)}</strong>"</p>
        <p class="search-no-results__hint">Try different keywords or filters</p>
      </div>
    `;
  }

  // Group by type
  const grouped = results.reduce((acc, r) => {
    if (!acc[r.type]) acc[r.type] = [];
    acc[r.type].push(r);
    return acc;
  }, {});

  const typeOrder = ['entities', 'files', 'relationships', 'rules'];
  const typeLabels = {
    entities: 'Entities',
    files: 'Files',
    relationships: 'Relationships',
    rules: 'Rules',
  };

  return `
    <div class="search-results" id="search-results" role="listbox">
      <div class="search-results__summary">
        ${formatInt(results.length)} result${results.length !== 1 ? 's' : ''}
      </div>
      ${typeOrder.filter(t => grouped[t]?.length > 0).map(type => `
        <div class="search-results__group">
          <div class="search-results__group-header">
            <span class="search-results__group-icon">${getTypeIcon(type)}</span>
            <span class="search-results__group-label">${typeLabels[type]}</span>
            <span class="search-results__group-count">${formatInt(grouped[type].length)}</span>
          </div>
          <div class="search-results__group-items">
            ${grouped[type].slice(0, 10).map((r, i) => renderResultItem(r, query)).join('')}
            ${grouped[type].length > 10 ? `
              <div class="search-results__more">+${formatInt(grouped[type].length - 10)} more</div>
            ` : ''}
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderResultItem(result, query) {
  const highlightedText = highlightMatch(result.name || result.title || result.path || result.ruleName, query);
  const subtitle = getResultSubtitle(result);
  const href = getResultHref(result);
  const typeColor = getTypeColor(result.type);

  return `
    <a
      href="${href}"
      class="search-result-item"
      data-type="${result.type}"
      data-id="${result.id || ''}"
      role="option"
      tabindex="-1"
    >
      <span class="search-result__icon" style="color: ${typeColor}">${getTypeIcon(result.type)}</span>
      <div class="search-result__content">
        <div class="search-result__title">${highlightedText}</div>
        ${subtitle ? `<div class="search-result__subtitle">${subtitle}</div>` : ''}
      </div>
      <svg class="search-result__arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M9 18l6-6-6-6"/>
      </svg>
    </a>
  `;
}

function getTypeColor(type) {
  const colors = {
    entities: '#818cf8',
    files: '#22d3ee',
    relationships: '#34d399',
    rules: '#fbbf24',
  };
  return colors[type] || '#9ca3af';
}

function getTypeIcon(type) {
  const icons = {
    entities: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/></svg>`,
    files: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`,
    relationships: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="5" cy="12" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="19" cy="19" r="3"/><path d="M8 10.5l8-4.5M8 13.5l8 4.5"/></svg>`,
    rules: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>`,
  };
  return icons[type] || `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>`;
}

function getResultSubtitle(result) {
  switch (result.type) {
    case 'entities':
      return `${result.entityType || 'entity'} · ${result.file || 'unknown file'}${result.line ? ':' + result.line : ''}`;
    case 'files':
      return `${result.language || 'unknown'} · ${formatInt(result.size || 0)} bytes`;
    case 'relationships':
      return `${result.relationshipType || 'rel'} · ${result.sourceName || 'source'} → ${result.targetName || 'target'}`;
    case 'rules':
      return `${result.plugin || 'unknown plugin'}`;
    default:
      return '';
  }
}

function getResultHref(result) {
  switch (result.type) {
    case 'entities':
      return `#/hypergraph/node/${encodeURIComponent(result.id)}`;
    case 'files':
      return `#/file/${encodeURIComponent(result.path)}`;
    case 'relationships':
      return `#/relationships?source=${encodeURIComponent(result.sourceId)}`;
    case 'rules':
      return `#/plugins?tab=rules&rule=${encodeURIComponent(result.ruleName)}`;
    default:
      return '#';
  }
}

function highlightMatch(text, query) {
  if (!query || !text) return escapeHtml(text);
  const regex = new RegExp(`(${escapeRegex(query)})`, 'gi');
  return escapeHtml(text).replace(regex, '<mark>$1</mark>');
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function updateSelection(results) {
  results.forEach((el, i) => {
    el.classList.toggle('search-result-item--selected', i === searchState.selectedIndex);
    el.setAttribute('aria-selected', i === searchState.selectedIndex);
  });

  // Scroll into view
  if (searchState.selectedIndex >= 0 && results[searchState.selectedIndex]) {
    results[searchState.selectedIndex].scrollIntoView({ block: 'nearest' });
  }
}

async function buildSearchIndex() {
  if (searchIndexCache) return searchIndexCache;
  if (searchIndexPromise) return searchIndexPromise;

  searchIndexPromise = (async () => {
    try {
      const savedIndexId = localStorage.getItem('batho.activeIndexId');
      const indexData = await loadIndex();
      const activeIndexId = savedIndexId && indexData.indexes[savedIndexId]
        ? savedIndexId
        : indexData.currentIndexId;

      const [graphData, bsgData] = await Promise.all([
        loadGraph(activeIndexId).catch(() => null),
        loadBsg(activeIndexId).catch(() => null),
      ]);

      const index = {
        entities: [],
        files: [],
        relationships: [],
        rules: [],
      };

      // Index entities
      if (graphData?.entities) {
        const entitiesById = graphData.entitiesById || {};
        index.entities = graphData.entities.map(e => ({
          type: 'entities',
          id: e.id,
          name: e.name,
          entityType: e.entityType,
          file: e.file,
          line: e.line,
          searchText: `${e.name} ${e.entityType} ${e.file || ''}`.toLowerCase(),
        }));

        // Index relationships
        if (graphData.relationships) {
          index.relationships = graphData.relationships.map(r => {
            const source = entitiesById[r.sourceId];
            const target = entitiesById[r.targetId];
            return {
              type: 'relationships',
              id: r.id || `${r.sourceId}-${r.targetId}`,
              relationshipType: r.relationshipType || r.type,
              sourceId: r.sourceId,
              targetId: r.targetId,
              sourceName: source?.name,
              targetName: target?.name,
              searchText: `${r.relationshipType || r.type} ${source?.name || ''} ${target?.name || ''}`.toLowerCase(),
            };
          });
        }
      }

      // Index rules
      if (bsgData?.ruleExecutions) {
        index.rules = bsgData.ruleExecutions.map(r => ({
          type: 'rules',
          id: r.ruleId || r.rule_id,
          ruleName: r.ruleName || r.rule_id,
          plugin: r.pluginId || r.plugin_id,
          description: r.description,
          searchText: `${r.ruleName || ''} ${r.pluginId || ''} ${r.description || ''}`.toLowerCase(),
        }));
      }

      // Index files from index metadata
      const indexEntry = indexData.indexes[activeIndexId];
      if (indexEntry) {
        // We'll get file data from the graph entities' files
        const fileSet = new Set();
        index.entities.forEach(e => {
          if (e.file) fileSet.add(e.file);
        });
        index.files = Array.from(fileSet).map(path => ({
          type: 'files',
          path,
          name: path.split('/').pop(),
          language: detectLanguage(path),
          searchText: `${path} ${path.split('/').pop()}`.toLowerCase(),
        }));
      }

      searchIndexCache = index;
      return index;
    } catch (err) {
      console.error('[search] Failed to build index:', err);
      return { entities: [], files: [], relationships: [], rules: [] };
    }
  })();

  return searchIndexPromise;
}

function detectLanguage(path) {
  const ext = path.split('.').pop()?.toLowerCase();
  const langMap = {
    py: 'Python',
    js: 'JavaScript',
    ts: 'TypeScript',
    jsx: 'React',
    tsx: 'React TS',
    json: 'JSON',
    yaml: 'YAML',
    yml: 'YAML',
    md: 'Markdown',
    css: 'CSS',
    scss: 'SCSS',
    html: 'HTML',
    rs: 'Rust',
    go: 'Go',
    java: 'Java',
    kt: 'Kotlin',
    swift: 'Swift',
    cpp: 'C++',
    c: 'C',
    h: 'C Header',
    rb: 'Ruby',
    php: 'PHP',
    sh: 'Shell',
    dockerfile: 'Dockerfile',
  };
  return langMap[ext] || ext?.toUpperCase() || 'Unknown';
}

function executeSearch(query, filter, index, resultsPanel) {
  if (!query || !index) return;

  const normalizedQuery = query.toLowerCase().trim();
  if (!normalizedQuery) return;

  // Determine which indices to search
  const indicesToSearch = filter === 'all'
    ? ['entities', 'files', 'relationships', 'rules']
    : [filter];

  // Score and filter results
  const results = [];
  indicesToSearch.forEach(type => {
    if (!index[type]) return;

    index[type].forEach(item => {
      const score = calculateRelevanceScore(item.searchText, normalizedQuery);
      if (score > 0) {
        results.push({ ...item, score });
      }
    });
  });

  // Sort by score (descending)
  results.sort((a, b) => b.score - a.score);

  // Limit total results
  const limitedResults = results.slice(0, 50);

  // Update state
  searchState.results = limitedResults;
  searchState.selectedIndex = -1;

  // Render
  resultsPanel.innerHTML = renderResults(limitedResults, query);

  // Wire up result clicks
  resultsPanel.querySelectorAll('.search-result-item').forEach(el => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      const href = el.getAttribute('href');
      if (href && href !== '#') {
        // Save to recent searches
        saveRecentSearch(searchState.query, searchState.filter);
        router.navigate(href);
      }
    });
  });
}

function calculateRelevanceScore(text, query) {
  if (!text || !query) return 0;

  const normalizedText = text.toLowerCase();
  const normalizedQuery = query.toLowerCase();

  // Exact match gets highest score
  if (normalizedText === normalizedQuery) return 100;

  // Starts with query
  if (normalizedText.startsWith(normalizedQuery)) return 80;

  // Contains query as whole word
  if (new RegExp(`\\b${escapeRegex(normalizedQuery)}\\b`).test(normalizedText)) return 60;

  // Contains query anywhere
  if (normalizedText.includes(normalizedQuery)) return 40;

  // Fuzzy match (all characters present in order)
  let queryIndex = 0;
  for (let i = 0; i < normalizedText.length && queryIndex < normalizedQuery.length; i++) {
    if (normalizedText[i] === normalizedQuery[queryIndex]) {
      queryIndex++;
    }
  }
  if (queryIndex === normalizedQuery.length) return 20;

  return 0;
}

function getRecentSearches() {
  try {
    const stored = localStorage.getItem(RECENT_SEARCHES_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveRecentSearch(query, filter) {
  if (!query) return;

  const recent = getRecentSearches();
  const newEntry = { query, filter, timestamp: Date.now() };

  // Remove duplicates
  const filtered = recent.filter(r => r.query !== query);

  // Add to beginning
  filtered.unshift(newEntry);

  // Keep only max
  const limited = filtered.slice(0, MAX_RECENT_SEARCHES);

  localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(limited));
}

function updateUrl(query, filter) {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (filter && filter !== 'all') params.set('filter', filter);

  const newHash = `#/search${params.toString() ? '?' + params.toString() : ''}`;
  if (window.location.hash !== newHash) {
    history.replaceState(null, '', newHash);
  }
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

// Inject styles
const searchStyles = `
  .page--search { height: 100%; overflow: hidden; }
  .search-page { display: flex; flex-direction: column; height: 100%; padding: var(--space-gutter); gap: var(--space-gutter); }

  .search-panel {
    flex-shrink: 0;
  }

  .search-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-md);
  }

  .search-icon {
    vertical-align: middle;
    margin-right: 8px;
    color: var(--accent-cyan);
  }

  .search-shortcut-hint {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--on-surface-variant);
  }

  .search-shortcut-hint kbd {
    background: var(--surface-container-high);
    padding: 2px 6px;
    border-radius: 4px;
    border: var(--hairline);
    font-family: inherit;
  }

  .search-input-wrapper {
    position: relative;
    margin-bottom: var(--space-md);
  }

  .search-input {
    width: 100%;
    padding: var(--space-md) var(--space-xl) var(--space-md) var(--space-md);
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: var(--radius-md);
    color: var(--on-surface);
    font-family: var(--font-sans);
    font-size: var(--type-body-md-size);
    outline: none;
    transition: border-color var(--transition-fast);
  }

  .search-input:focus {
    border-color: var(--accent-cyan);
  }

  .search-input::placeholder {
    color: var(--on-surface-variant);
  }

  .search-clear {
    position: absolute;
    right: var(--space-sm);
    top: 50%;
    transform: translateY(-50%);
    background: none;
    border: none;
    color: var(--on-surface-variant);
    cursor: pointer;
    padding: var(--space-xs);
    border-radius: var(--radius-sm);
    opacity: 0;
    transition: opacity var(--transition-fast), background var(--transition-fast);
  }

  .search-input:not(:placeholder-shown) + .search-clear {
    opacity: 1;
  }

  .search-clear:hover {
    background: var(--surface-container-high);
    color: var(--on-surface);
  }

  .search-filters {
    display: flex;
    gap: var(--space-sm);
    flex-wrap: wrap;
  }

  .search-filter-chip {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-sm) var(--space-md);
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: var(--radius-md);
    color: var(--on-surface-variant);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .search-filter-chip:hover {
    background: var(--surface-container-high);
    color: var(--on-surface);
  }

  .search-filter-chip--active {
    background: var(--accent-cyan);
    border-color: var(--accent-cyan);
    color: #000;
  }

  .search-filter-chip--active svg {
    color: #000;
  }

  .search-results-panel {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }

  .search-loading {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-xl);
    color: var(--on-surface-variant);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
  }

  .search-empty {
    padding: var(--space-xl);
  }

  .search-recent {
    margin-bottom: var(--space-xl);
  }

  .search-recent__title {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: var(--space-md);
  }

  .search-recent__list {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .search-recent__item {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    background: var(--surface-container);
    border: var(--hairline);
    border-radius: var(--radius-md);
    color: var(--on-surface);
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    cursor: pointer;
    text-align: left;
    transition: all var(--transition-fast);
  }

  .search-recent__item:hover {
    background: var(--surface-container-high);
    border-color: var(--accent-cyan);
  }

  .search-recent__item svg {
    color: var(--on-surface-variant);
    flex-shrink: 0;
  }

  .search-recent__filter {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: 10px;
    padding: 2px 6px;
    background: var(--surface-container-high);
    border-radius: var(--radius-sm);
    color: var(--on-surface-variant);
  }

  .search-hints {
    display: flex;
    gap: var(--space-lg);
    color: var(--on-surface-variant);
    font-family: var(--font-mono);
    font-size: 11px;
  }

  .search-hint kbd {
    background: var(--surface-container-high);
    padding: 2px 6px;
    border-radius: 4px;
    border: var(--hairline);
    font-family: inherit;
  }

  .search-no-results {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--space-3xl);
    text-align: center;
  }

  .search-no-results svg {
    color: var(--on-surface-variant);
    margin-bottom: var(--space-md);
  }

  .search-no-results p {
    color: var(--on-surface);
    font-family: var(--font-sans);
    font-size: var(--type-body-md-size);
  }

  .search-no-results__hint {
    color: var(--on-surface-variant) !important;
    font-size: var(--type-ui-label-size) !important;
  }

  .search-results {
    padding: var(--space-md) 0;
  }

  .search-results__summary {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    margin-bottom: var(--space-md);
    padding: 0 var(--space-md);
  }

  .search-results__group {
    margin-bottom: var(--space-lg);
  }

  .search-results__group-header {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    border-bottom: var(--hairline);
    margin-bottom: var(--space-sm);
  }

  .search-results__group-icon {
    font-size: 12px;
  }

  .search-results__group-label {
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .search-results__group-count {
    margin-left: auto;
    padding: 2px 6px;
    background: var(--surface-container);
    border-radius: var(--radius-sm);
  }

  .search-results__group-items {
    display: flex;
    flex-direction: column;
  }

  .search-result-item {
    display: flex;
    align-items: center;
    gap: var(--space-md);
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-md);
    text-decoration: none;
    color: inherit;
    transition: all var(--transition-fast);
    border: 1px solid transparent;
  }

  .search-result-item:hover {
    background: var(--surface-container);
    border-color: var(--surface-container-high);
    transform: translateX(2px);
  }

  .search-result-item--selected {
    background: var(--surface-container);
    border-color: var(--accent-cyan);
    outline: none;
  }

  .search-result__icon {
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    background: var(--surface-container-high);
    border-radius: var(--radius-sm);
    padding: 4px;
  }

  .search-result__content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .search-result__title {
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 500;
    color: var(--on-surface);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .search-result__title mark {
    background: rgb(34 211 238 / 0.25);
    color: var(--accent-cyan);
    border-radius: 2px;
    padding: 0 2px;
    font-weight: 600;
  }

  .search-result__subtitle {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .search-result__arrow {
    color: var(--on-surface-variant);
    flex-shrink: 0;
    opacity: 0;
    transition: opacity var(--transition-fast);
  }

  .search-result-item:hover .search-result__arrow,
  .search-result-item--selected .search-result__arrow {
    opacity: 1;
  }

  .search-results__more {
    padding: var(--space-sm) var(--space-md);
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--on-surface-variant);
    text-align: center;
  }
`;

function injectStyles() {
  if (document.getElementById('search-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'search-styles';
  styleEl.textContent = searchStyles;
  document.head.appendChild(styleEl);
}

injectStyles();

