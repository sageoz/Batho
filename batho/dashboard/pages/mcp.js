/**
 * MCP Configuration Page - Tab-based UI for managing the MCP hub.
 */

import { api } from '../assets/js/api.js';
import { createDrawer, openDrawer, closeDrawer } from '../shared/components/drawer.js';

const TABS = [
  { id: 'workspaces', label: 'Workspaces', icon: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>' },
  { id: 'server', label: 'Server', icon: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>' },
  { id: 'scaling', label: 'Scaling', icon: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>' },
  { id: 'agents', label: 'Agents', icon: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V6.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z"/><circle cx="8" cy="14" r="2"/></svg>' },
];

let currentTab = 'workspaces';
let config = null;
let workspaces = [];
let loading = false;
let sortColumn = 'label';
let sortDirection = 'asc';
let filterText = '';
let selectedWorkspaces = new Set();
let drawer = null;
let lastRefresh = null;
let serverOnline = true;

export async function renderMcp(params, context) {
  const container = document.createElement('div');
  container.className = 'mcp-page';

  try {
    config = await api.getConfig();
    workspaces = await api.listWorkspaces();
    lastRefresh = new Date();
    serverOnline = true;
  } catch (err) {
    serverOnline = false;
    container.innerHTML = renderError(err);
    return container;
  }

  drawer = createDrawer();
  document.body.appendChild(drawer);

  container.innerHTML = renderHeader() + renderTabs() + renderTabContent();

  container.querySelectorAll('.tab-item').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  attachTabListeners(container);
  attachKeyboardShortcuts(container);

  return container;
}

function attachKeyboardShortcuts(container) {
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    
    if (e.key === '/') {
      e.preventDefault();
      container.querySelector('#workspace-filter')?.focus();
    } else if (e.key === 'n' && currentTab === 'workspaces') {
      e.preventDefault();
      container.querySelector('#add-workspace-btn')?.click();
    } else if (e.key === 'r') {
      e.preventDefault();
      refreshData();
    } else if (e.key === '?') {
      e.preventDefault();
      showShortcutsModal();
    } else if (e.key === 'Escape') {
      closeDrawer(drawer);
      closeShortcutsModal();
    }
  });
}

function showShortcutsModal() {
  const existing = document.querySelector('.shortcuts-modal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.className = 'shortcuts-modal';
  modal.innerHTML = `
    <div class="shortcuts-content">
      <div class="shortcuts-header">
        <h3>Keyboard Shortcuts</h3>
        <button class="dialog__close" onclick="this.closest('.shortcuts-modal').remove()">&times;</button>
      </div>
      <div class="shortcuts-list">
        <div class="shortcut-item">
          <span class="shortcut-item__label">Focus search</span>
          <div class="shortcut-item__key"><span class="shortcut-key">/</span></div>
        </div>
        <div class="shortcut-item">
          <span class="shortcut-item__label">Add workspace</span>
          <div class="shortcut-item__key"><span class="shortcut-key">n</span></div>
        </div>
        <div class="shortcut-item">
          <span class="shortcut-item__label">Refresh data</span>
          <div class="shortcut-item__key"><span class="shortcut-key">r</span></div>
        </div>
        <div class="shortcut-item">
          <span class="shortcut-item__label">Show shortcuts</span>
          <div class="shortcut-item__key"><span class="shortcut-key">?</span></div>
        </div>
        <div class="shortcut-item">
          <span class="shortcut-item__label">Close modal/drawer</span>
          <div class="shortcut-item__key"><span class="shortcut-key">Esc</span></div>
        </div>
      </div>
    </div>
  `;
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.remove();
  });
  document.body.appendChild(modal);
}

function closeShortcutsModal() {
  document.querySelector('.shortcuts-modal')?.remove();
}

async function refreshData() {
  const container = document.querySelector('.mcp-page');
  if (!container) return;

  try {
    config = await api.getConfig();
    workspaces = await api.listWorkspaces();
    lastRefresh = new Date();
    serverOnline = true;
    
    container.querySelector('.mcp-header').innerHTML = renderHeader();
    container.querySelector('.mcp-content').innerHTML = renderTabContent();
    attachTabListeners(container);
    showNotice('Data refreshed', 'success');
  } catch (err) {
    serverOnline = false;
    showNotice('Failed to refresh: ' + err.message, 'error');
  }
}

function renderHeader() {
  const refreshTime = lastRefresh ? lastRefresh.toLocaleTimeString() : 'Never';
  const statusClass = serverOnline ? '' : 'header-status--offline';
  const statusText = serverOnline ? 'Connected' : 'Offline';
  
  return `
    <header class="mcp-header">
      <div class="mcp-header__content">
        <div class="mcp-header__icon">
          <div class="mcp-header__icon-bg">
            <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
              <path d="M3 3v5h5"/>
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/>
              <path d="M16 21h5v-5"/>
            </svg>
          </div>
        </div>
        <div class="mcp-header__text">
          <div class="mcp-header__title-row">
            <h1 class="mcp-header__title">MCP Configuration</h1>
            <span class="version-badge">v1.1.0</span>
          </div>
          <p class="mcp-header__subtitle">Manage your multi-workspace MCP hub</p>
        </div>
      </div>
      <div class="mcp-header__actions">
        <div class="header-status ${statusClass}">
          <span class="header-status__dot"></span>
          <span>${statusText}</span>
        </div>
        <span class="last-refresh">Last refresh: ${refreshTime}</span>
        <button class="btn btn--secondary btn--sm btn--icon" onclick="refreshData()" title="Refresh (R)">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 21h5v-5"/></svg>
          <span>Refresh</span>
        </button>
        <button class="btn btn--ghost btn--sm btn--icon" onclick="showShortcutsModal()" title="Keyboard Shortcuts (?)">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>
          <span>Help</span>
        </button>
      </div>
    </header>
  `;
}

function renderTabs() {
  const getTabBadge = (id) => {
    if (id === 'workspaces') return workspaces.length;
    return '';
  };
  
  return `
    <nav class="tabs-container">
      <div class="tabs">
        ${TABS.map(tab => `
          <button class="tab-item ${tab.id === currentTab ? 'tab-item--active' : ''}" data-tab="${tab.id}" aria-selected="${tab.id === currentTab}">
            <span class="tab-item__icon">${tab.icon}</span>
            <span class="tab-item__label">${tab.label}</span>
            ${getTabBadge(tab.id) ? `<span class="tab-item__badge">${getTabBadge(tab.id)}</span>` : ''}
            ${tab.id === currentTab ? '<span class="tab-item__indicator"></span>' : ''}
          </button>
        `).join('')}
      </div>
    </nav>
  `;
}

function renderTabContent() {
  let content = '';
  if (currentTab === 'workspaces') {
    content = renderWorkspacesTab();
  } else if (currentTab === 'server') {
    content = renderServerTab();
  } else if (currentTab === 'scaling') {
    content = renderScalingTab();
  } else if (currentTab === 'agents') {
    content = renderAgentsTab();
  }
  return `
    <div class="mcp-content">
      ${content}
    </div>
  `;
}

function switchTab(tabId) {
  currentTab = tabId;
  const container = document.querySelector('.mcp-page');
  if (!container) return;

  container.querySelector('.tabs').innerHTML = renderTabs();
  container.querySelector('.mcp-content').innerHTML = renderTabContent();

  container.querySelectorAll('.tab-item').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  attachTabListeners(container);
}

function attachTabListeners(container) {
  if (currentTab === 'workspaces') {
    attachWorkspacesListeners(container);
  } else if (currentTab === 'server') {
    attachServerListeners(container);
  } else if (currentTab === 'scaling') {
    attachScalingListeners(container);
  } else if (currentTab === 'agents') {
    attachAgentsListeners(container);
  }
}

function getFilteredWorkspaces() {
  let filtered = [...workspaces];
  
  if (filterText) {
    const search = filterText.toLowerCase();
    filtered = filtered.filter(ws => 
      (ws.label || ws.id).toLowerCase().includes(search) ||
      ws.id.toLowerCase().includes(search) ||
      ws.ctn_dir.toLowerCase().includes(search) ||
      ws.tags.some(t => t.toLowerCase().includes(search))
    );
  }
  
  filtered.sort((a, b) => {
    let aVal = a[sortColumn] ?? '';
    let bVal = b[sortColumn] ?? '';
    if (typeof aVal === 'boolean') aVal = aVal ? 1 : 0;
    if (typeof bVal === 'boolean') bVal = bVal ? 1 : 0;
    if (sortDirection === 'asc') return aVal > bVal ? 1 : -1;
    return aVal < bVal ? 1 : -1;
  });
  
  return filtered;
}

function renderWorkspacesTab() {
  const filtered = getFilteredWorkspaces();
  const selectedCount = selectedWorkspaces.size;
  
  return `
    <div class="workspaces-tab" data-aos="fade-up">
      ${selectedCount > 0 ? `
        <div class="bulk-actions-bar">
          <div class="bulk-actions-bar__info">
            <span>${selectedCount} workspace${selectedCount !== 1 ? 's' : ''} selected</span>
            <button class="btn btn--ghost btn--sm" onclick="clearSelection()">Clear</button>
          </div>
          <div class="bulk-actions-bar__actions">
            <button class="btn btn--secondary btn--sm" onclick="bulkPin()">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4a1 1 0 0 1 1 1v2.586l1.707 1.707a1 1 0 0 1 .293.707v3a1 1 0 0 1-1 1h-4v5a1 1 0 0 1-2 0v-5H7a1 1 0 0 1-1-1v-3a1 1 0 0 1 .293-.707L7 7.586V5a1 1 0 0 1 1-1h8z"/></svg>
              Pin
            </button>
            <button class="btn btn--secondary btn--sm" onclick="bulkUnpin()">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4a1 1 0 0 1 1 1v2.586l1.707 1.707a1 1 0 0 1 .293.707v3a1 1 0 0 1-1 1h-4v5a1 1 0 0 1-2 0v-5H7a1 1 0 0 1-1-1v-3a1 1 0 0 1 .293-.707L7 7.586V5a1 1 0 0 1 1-1h8z"/></svg>
              Unpin
            </button>
            <button class="btn btn--secondary btn--sm" onclick="bulkEnable()">Enable</button>
            <button class="btn btn--secondary btn--sm" onclick="bulkDisable()">Disable</button>
            <button class="btn btn--primary btn--sm" onclick="bulkDelete()">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
              Delete
            </button>
          </div>
        </div>
      ` : ''}
      <div class="section-header">
        <div class="section-header__info">
          <h2 class="section-header__title">Workspaces</h2>
          <span class="section-header__count">${filtered.length} of ${workspaces.length}</span>
        </div>
        <div class="section-header__actions">
          <div class="search-input">
            <svg class="search-input__icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            <input type="text" class="search-input__field" placeholder="Filter workspaces... (Press /)" id="workspace-filter" value="${escapeAttr(filterText)}" />
          </div>
          <button class="btn btn--primary" id="add-workspace-btn">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
            Add Workspace
          </button>
        </div>
      </div>

      <div class="table-card">
        <table class="data-table">
          <thead>
            <tr>
              <th class="col-checkbox">
                <input type="checkbox" id="select-all" ${selectedWorkspaces.size === filtered.length && filtered.length > 0 ? 'checked' : ''} />
              </th>
              <th class="col-state sortable ${sortColumn === 'resident' ? (sortDirection === 'asc' ? 'sort-asc' : 'sort-desc') : ''}" data-sort="resident">State</th>
              <th class="col-resident sortable ${sortColumn === 'resident' ? (sortDirection === 'asc' ? 'sort-asc' : 'sort-desc') : ''}" data-sort="resident">Resident</th>
              <th class="col-pinned sortable ${sortColumn === 'pinned' ? (sortDirection === 'asc' ? 'sort-asc' : 'sort-desc') : ''}" data-sort="pinned">Pinned</th>
              <th class="col-label sortable ${sortColumn === 'label' ? (sortDirection === 'asc' ? 'sort-asc' : 'sort-desc') : ''}" data-sort="label">Label / ID</th>
              <th class="col-path sortable ${sortColumn === 'ctn_dir' ? (sortDirection === 'asc' ? 'sort-asc' : 'sort-desc') : ''}" data-sort="ctn_dir">Path</th>
              <th class="col-tags sortable ${sortColumn === 'tags' ? (sortDirection === 'asc' ? 'sort-asc' : 'sort-desc') : ''}" data-sort="tags">Tags</th>
              <th class="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody id="workspaces-tbody">
            ${filtered.length === 0 ? `
              <tr>
                <td colspan="8" class="empty-state">
                  <div class="empty-state__content">
                    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>
                    <p>${filterText ? 'No matching workspaces' : 'No workspaces configured'}</p>
                    <span>${filterText ? 'Try a different search term' : 'Add a workspace to get started'}</span>
                  </div>
                </td>
              </tr>
            ` : filtered.map(ws => renderWorkspaceRow(ws)).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderWorkspaceRow(ws) {
  const stateClass = ws.resident ? 'badge--success' : 'badge--secondary';
  const stateLabel = ws.resident ? 'ready' : 'registered';
  const isSelected = selectedWorkspaces.has(ws.id);
  const isEnabled = ws.enabled !== false;

  return `
    <tr data-workspace-id="${ws.id}" class="${isSelected ? 'selected' : ''}" onclick="openWorkspaceDrawer('${escapeAttr(ws.id)}')">
      <td class="checkbox-cell" onclick="event.stopPropagation()">
        <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleSelect('${escapeAttr(ws.id)}', this.checked)" />
      </td>
      <td><span class="badge ${stateClass}">${stateLabel}</span></td>
      <td>
        <span class="status-indicator ${ws.resident ? 'status-indicator--active' : ''}">
          <span class="status-indicator__dot"></span>
        </span>
      </td>
      <td>${ws.pinned ? '<svg class="pin-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M16 4a1 1 0 0 1 1 1v2.586l1.707 1.707a1 1 0 0 1 .293.707v3a1 1 0 0 1-1 1h-4v5a1 1 0 0 1-2 0v-5H7a1 1 0 0 1-1-1v-3a1 1 0 0 1 .293-.707L7 7.586V5a1 1 0 0 1 1-1h8z"/></svg>' : ''}</td>
      <td>
        <div class="workspace-label">
          <strong>${ws.label || ws.id}</strong>
          <span class="workspace-id">${ws.id}</span>
        </div>
      </td>
      <td><code class="path-cell" title="${ws.ctn_dir}">${truncatePath(ws.ctn_dir)}</code></td>
      <td>
        <div class="tags-cell">
          ${ws.tags.map(t => `<span class="tag">${t}</span>`).join('')}
        </div>
      </td>
      <td onclick="event.stopPropagation()">
        <div class="actions-menu">
          <button class="action-btn" data-action="mount" title="Mount">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m18 15-6-6-6 6"/></svg>
          </button>
          <button class="action-btn" data-action="unmount" title="Unmount">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
          </button>
          <button class="action-btn" data-action="refresh" title="Refresh">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 21h5v-5"/></svg>
          </button>
          <button class="action-btn ${ws.pinned ? 'action-btn--active' : ''}" data-action="pin" title="${ws.pinned ? 'Unpin' : 'Pin'}">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="${ws.pinned ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><path d="M16 4a1 1 0 0 1 1 1v2.586l1.707 1.707a1 1 0 0 1 .293.707v3a1 1 0 0 1-1 1h-4v5a1 1 0 0 1-2 0v-5H7a1 1 0 0 1-1-1v-3a1 1 0 0 1 .293-.707L7 7.586V5a1 1 0 0 1 1-1h8z"/></svg>
          </button>
          <button class="action-btn" data-action="edit" title="Edit">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
          </button>
          <button class="action-btn action-btn--danger" data-action="delete" title="Delete">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
          </button>
        </div>
      </td>
    </tr>
  `;
}

function openWorkspaceDrawer(wsId) {
  const ws = workspaces.find(w => w.id === wsId);
  if (!ws) return;
  
  const content = `
    <div class="workspace-detail">
      <div class="workspace-detail__header">
        <div class="workspace-detail__icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>
        </div>
        <div>
          <h3 class="workspace-detail__title">${ws.label || ws.id}</h3>
          <span class="workspace-detail__id">${ws.id}</span>
        </div>
      </div>
      
      <div class="workspace-detail__section">
        <div class="workspace-detail__section-title">Configuration</div>
        <div class="workspace-detail__stat">
          <span class="workspace-detail__stat-label">Path</span>
          <span class="workspace-detail__stat-value">${truncatePath(ws.ctn_dir, 30)}</span>
        </div>
        <div class="workspace-detail__stat">
          <span class="workspace-detail__stat-label">State</span>
          <span class="workspace-detail__stat-value">${ws.resident ? 'Ready' : 'Registered'}</span>
        </div>
        <div class="workspace-detail__stat">
          <span class="workspace-detail__stat-label">Pinned</span>
          <span class="workspace-detail__stat-value">${ws.pinned ? 'Yes' : 'No'}</span>
        </div>
        <div class="workspace-detail__stat">
          <span class="workspace-detail__stat-label">Enabled</span>
          <span class="workspace-detail__stat-value">${ws.enabled !== false ? 'Yes' : 'No'}</span>
        </div>
      </div>
      
      <div class="workspace-detail__section">
        <div class="workspace-detail__section-title">Tags</div>
        <div class="tags-cell" style="margin-top: var(--space-sm);">
          ${ws.tags.length > 0 ? ws.tags.map(t => `<span class="tag">${t}</span>`).join('') : '<span style="color: var(--on-surface-variant); font-size: 12px;">No tags</span>'}
        </div>
      </div>
      
      <div class="workspace-detail__section">
        <div class="workspace-detail__section-title">Quick Actions</div>
        <div class="workspace-detail__actions">
          <button class="btn btn--primary btn--sm" onclick="quickAction('${escapeAttr(ws.id)}', 'mount')">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m18 15-6-6-6 6"/></svg>
            Mount
          </button>
          <button class="btn btn--secondary btn--sm" onclick="quickAction('${escapeAttr(ws.id)}', 'refresh')">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 21h5v-5"/></svg>
            Refresh
          </button>
          <button class="btn btn--secondary btn--sm" onclick="closeDrawer(drawer); document.querySelector('#add-workspace-btn')?.click(); setTimeout(() => { const wsIdInput = document.querySelector('#ws-id'); if(wsIdInput) wsIdInput.value = '${escapeAttr(ws.id)}'; }, 100)">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
            Edit
          </button>
        </div>
      </div>
    </div>
  `;
  
  openDrawer(drawer, { title: 'Workspace Details', content });
}

async function quickAction(wsId, action) {
  try {
    if (action === 'mount') await api.mountWorkspace(wsId);
    else if (action === 'refresh') await api.refreshWorkspace(wsId);
    
    workspaces = await api.listWorkspaces();
    const container = document.querySelector('.mcp-page');
    if (container) {
      container.querySelector('.mcp-content').innerHTML = renderTabContent();
      attachTabListeners(container);
    }
    showNotice(`${action} completed for ${wsId}`, 'success');
  } catch (err) {
    showNotice(err.message, 'error');
  }
}

function toggleSelect(wsId, selected) {
  if (selected) selectedWorkspaces.add(wsId);
  else selectedWorkspaces.delete(wsId);
  
  const container = document.querySelector('.mcp-page');
  if (container) {
    container.querySelector('.mcp-content').innerHTML = renderTabContent();
    attachTabListeners(container);
  }
}

function clearSelection() {
  selectedWorkspaces.clear();
  const container = document.querySelector('.mcp-page');
  if (container) {
    container.querySelector('.mcp-content').innerHTML = renderTabContent();
    attachTabListeners(container);
  }
}

async function bulkPin() {
  for (const wsId of selectedWorkspaces) {
    const ws = workspaces.find(w => w.id === wsId);
    if (ws && !ws.pinned) await api.updateWorkspace(wsId, { pinned: true });
  }
  selectedWorkspaces.clear();
  await refreshWorkspaces();
  showNotice('Workspaces pinned', 'success');
}

async function bulkUnpin() {
  for (const wsId of selectedWorkspaces) {
    const ws = workspaces.find(w => w.id === wsId);
    if (ws && ws.pinned) await api.updateWorkspace(wsId, { pinned: false });
  }
  selectedWorkspaces.clear();
  await refreshWorkspaces();
  showNotice('Workspaces unpinned', 'success');
}

async function bulkEnable() {
  for (const wsId of selectedWorkspaces) {
    await api.updateWorkspace(wsId, { enabled: true });
  }
  selectedWorkspaces.clear();
  await refreshWorkspaces();
  showNotice('Workspaces enabled', 'success');
}

async function bulkDisable() {
  for (const wsId of selectedWorkspaces) {
    await api.updateWorkspace(wsId, { enabled: false });
  }
  selectedWorkspaces.clear();
  await refreshWorkspaces();
  showNotice('Workspaces disabled', 'success');
}

async function bulkDelete() {
  if (!confirm(`Delete ${selectedWorkspaces.size} workspace(s)?`)) return;
  
  for (const wsId of selectedWorkspaces) {
    await api.deleteWorkspace(wsId);
  }
  selectedWorkspaces.clear();
  await refreshWorkspaces();
  showNotice('Workspaces deleted', 'success');
}

async function refreshWorkspaces() {
  workspaces = await api.listWorkspaces();
  const container = document.querySelector('.mcp-page');
  if (container) {
    container.querySelector('.mcp-content').innerHTML = renderTabContent();
    attachTabListeners(container);
  }
}

function attachWorkspacesListeners(container) {
  const addBtn = container.querySelector('#add-workspace-btn');
  if (addBtn) {
    addBtn.addEventListener('click', () => showAddWorkspaceDialog(container));
  }

  const filterInput = container.querySelector('#workspace-filter');
  if (filterInput) {
    filterInput.addEventListener('input', (e) => {
      filterText = e.target.value;
      container.querySelector('#workspaces-tbody').innerHTML = getFilteredWorkspaces().map(renderWorkspaceRow).join('');
      attachWorkspacesListeners(container);
    });
  }

  const selectAll = container.querySelector('#select-all');
  if (selectAll) {
    selectAll.addEventListener('change', (e) => {
      const filtered = getFilteredWorkspaces();
      if (e.target.checked) {
        filtered.forEach(ws => selectedWorkspaces.add(ws.id));
      } else {
        selectedWorkspaces.clear();
      }
      container.querySelector('.mcp-content').innerHTML = renderTabContent();
      attachTabListeners(container);
    });
  }

  container.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (sortColumn === col) {
        sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
      } else {
        sortColumn = col;
        sortDirection = 'asc';
      }
      container.querySelector('#workspaces-tbody').innerHTML = getFilteredWorkspaces().map(renderWorkspaceRow).join('');
      attachWorkspacesListeners(container);
    });
  });

  container.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const action = e.currentTarget.dataset.action;
      const row = e.currentTarget.closest('tr');
      const wsId = row?.dataset.workspaceId;
      if (!wsId) return;

      try {
        if (action === 'mount') await api.mountWorkspace(wsId);
        else if (action === 'unmount') await api.unmountWorkspace(wsId);
        else if (action === 'refresh') await api.refreshWorkspace(wsId);
        else if (action === 'pin') {
          const ws = workspaces.find(w => w.id === wsId);
          await api.updateWorkspace(wsId, { pinned: !ws?.pinned });
        }
        else if (action === 'delete') {
          if (confirm(`Delete workspace "${wsId}"?`)) {
            await api.deleteWorkspace(wsId);
          }
        }
        else if (action === 'edit') {
          showEditWorkspaceDialog(container, wsId);
        }

        workspaces = await api.listWorkspaces();
        container.querySelector('#workspaces-tbody').innerHTML = getFilteredWorkspaces().map(renderWorkspaceRow).join('');
        attachWorkspacesListeners(container);
      } catch (err) {
        showNotice(err.message, 'error');
      }
    });
  });
}

async function showAddWorkspaceDialog(container) {
  const dialog = document.createElement('div');
  dialog.className = 'dialog-overlay';
  dialog.innerHTML = `
    <div class="dialog dialog--lg">
      <div class="dialog__header">
        <div class="dialog__header-content">
          <div class="dialog__icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>
          </div>
          <div>
            <h2>Add Workspace</h2>
            <p class="dialog__subtitle">Connect a new .ctn directory to the MCP hub</p>
          </div>
        </div>
        <button class="dialog__close">&times;</button>
      </div>
      <div class="dialog__body">
        <div class="form-group">
          <label class="label">
            <span class="label__icon">📁</span>
            Path to .ctn directory
          </label>
          <div class="path-input-wrapper">
            <div class="input-with-icon">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 22V4a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v18Z"/><path d="M4 10h16"/><path d="M10 10v4"/><path d="M14 10v4"/></svg>
              <input type="text" class="input" id="ws-path" placeholder="/path/to/project/.ctn" />
            </div>
            <button class="btn btn--secondary btn--icon" id="browse-btn">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 21-6-6m6 6-6-6m6 6 6 6"/></svg>
              Browse
            </button>
          </div>
          <small class="input-hint">Select a directory containing a .ctn folder</small>
        </div>
        
        <div class="form-row">
          <div class="form-group">
            <label class="label">
              <span class="label__icon">🏷️</span>
              ID
              <span class="label__optional">(auto)</span>
            </label>
            <input type="text" class="input" id="ws-id" placeholder="my-workspace" />
            <small class="input-hint">Derived from folder name if empty</small>
          </div>
          <div class="form-group">
            <label class="label">
              <span class="label__icon">📝</span>
              Label
              <span class="label__optional">(optional)</span>
            </label>
            <input type="text" class="input" id="ws-label" placeholder="My Workspace" />
          </div>
        </div>
        
        <div class="form-group">
          <label class="label">
            <span class="label__icon">🏷️</span>
            Tags
            <span class="label__optional">(optional)</span>
          </label>
          <div class="tags-input-wrapper">
            <input type="text" class="input" id="ws-tags" placeholder="production, api, backend" />
          </div>
          <small class="input-hint">Comma-separated tags for organization</small>
        </div>
        
        <div class="form-group">
          <label class="checkbox-label checkbox-label--interactive">
            <input type="checkbox" id="ws-pinned" />
            <span class="checkbox-custom"></span>
            <span class="checkbox-label__text">
              <strong>Pin workspace</strong>
              <small>Keep this workspace always resident in memory</small>
            </span>
          </label>
        </div>
      </div>
      <div class="dialog__footer">
        <button class="btn btn--ghost" id="cancel-btn">Cancel</button>
        <button class="btn btn--primary" id="save-btn">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
          Add Workspace
        </button>
      </div>
    </div>
  `;

  document.body.appendChild(dialog);

  dialog.querySelector('.dialog__close').addEventListener('click', () => dialog.remove());
  dialog.querySelector('#cancel-btn').addEventListener('click', () => dialog.remove());
  
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) dialog.remove();
  });

  const pathInput = dialog.querySelector('#ws-path');
  const idInput = dialog.querySelector('#ws-id');
  
  pathInput.addEventListener('input', () => {
    if (!idInput.dataset.manual) {
      const derivedId = pathInput.value.split('/').pop()?.toLowerCase().replace(/[^a-z0-9-]/g, '-') || '';
      idInput.value = derivedId;
    }
  });
  
  idInput.addEventListener('input', () => {
    idInput.dataset.manual = idInput.value ? 'true' : '';
  });

  dialog.querySelector('#browse-btn').addEventListener('click', async () => {
    const path = pathInput.value || '~';
    try {
      const result = await api.browseDirectory(path);
      if (result.error) {
        showNotice(result.error, 'error');
        return;
      }
      showDirectoryPicker(dialog, result);
    } catch (err) {
      showNotice(err.message, 'error');
    }
  });

  dialog.querySelector('#save-btn').addEventListener('click', async () => {
    const path = pathInput.value;
    if (!path) {
      showNotice('Path is required', 'error');
      pathInput.focus();
      return;
    }

    const id = idInput.value || path.split('/').pop().toLowerCase().replace(/[^a-z0-9-]/g, '-');
    const label = dialog.querySelector('#ws-label').value;
    const tags = dialog.querySelector('#ws-tags').value.split(',').map(t => t.trim()).filter(Boolean);
    const pinned = dialog.querySelector('#ws-pinned').checked;

    try {
      const result = await api.createWorkspace({ id, ctn_dir: path, label, tags, pinned });
      if (result.error) {
        showNotice(result.error, 'error');
        return;
      }
      const newWorkspace = {
        id: result.id,
        ctn_dir: result.ctn_dir,
        label: result.label || result.id,
        tags: result.tags || [],
        pinned: result.pinned || false,
        resident: result.resident || false,
        status: result.status || 'active'
      };
      workspaces.push(newWorkspace);
      container.querySelector('#workspaces-tbody').innerHTML = getFilteredWorkspaces().map(renderWorkspaceRow).join('');
      attachWorkspacesListeners(container);
      dialog.remove();
      showNotice('Workspace added', 'success');
    } catch (err) {
      showNotice(err.message, 'error');
    }
  });
  
  pathInput.focus();
}

function showDirectoryPicker(dialog, result) {
  const picker = document.createElement('div');
  picker.className = 'directory-picker';
  
  const hasError = result.error;
  const entries = result.entries || [];
  
  picker.innerHTML = `
    <div class="picker-header">
      <button class="btn btn--sm btn--secondary btn--icon" id="parent-btn">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m15 18-6-6 6-6"/></svg>
        Back
      </button>
      <span class="picker-path" title="${escapeAttr(result.path)}">${escapeHtml(result.path)}</span>
    </div>
    ${hasError ? `
      <div class="picker-error">
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>
        <span>${escapeHtml(result.error)}</span>
      </div>
    ` : `
    <div class="picker-list">
      ${entries.length === 0 ? `
        <div class="picker-empty">
          <span>No directories found</span>
        </div>
      ` : entries.map(entry => `
        <div class="picker-item ${entry.is_dir ? 'picker-item--dir' : ''}" data-path="${escapeAttr(entry.path)}">
          <span class="picker-icon">
            ${entry.is_dir 
              ? '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 22V4a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v18Z"/><path d="M4 10h16"/><path d="M10 10v4"/><path d="M14 10v4"/></svg>'
              : '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/></svg>'}
          </span>
          <span class="picker-name">${escapeHtml(entry.name)}</span>
          ${entry.is_ctn ? '<span class="badge badge--success">.ctn</span>' : ''}
        </div>
      `).join('')}
    </div>
    `}
  `;

  const existingPicker = dialog.querySelector('.directory-picker');
  if (existingPicker) existingPicker.remove();

  dialog.querySelector('.dialog__body').appendChild(picker);

  picker.querySelectorAll('.picker-item').forEach(item => {
    item.addEventListener('click', async () => {
      if (item.classList.contains('picker-item--dir')) {
        try {
          const newResult = await api.browseDirectory(item.dataset.path);
          if (newResult.error && !newResult.entries?.length) {
            showNotice(newResult.error, 'error');
            return;
          }
          showDirectoryPicker(dialog, newResult);
        } catch (err) {
          showNotice(err.message, 'error');
        }
      } else {
        dialog.querySelector('#ws-path').value = item.dataset.path;
        dialog.querySelector('#ws-id').value = item.dataset.path.split('/').pop()?.toLowerCase().replace(/[^a-z0-9-]/g, '-') || '';
        picker.remove();
      }
    });
  });

  const parentBtn = picker.querySelector('#parent-btn');
  if (parentBtn) {
    parentBtn.addEventListener('click', async () => {
      const parts = result.path.split('/');
      parts.pop();
      const parentPath = parts.join('/') || '/';
      if (parentPath === result.path) return;
      try {
        const newResult = await api.browseDirectory(parentPath);
        showDirectoryPicker(dialog, newResult);
      } catch (err) {
        showNotice(err.message, 'error');
      }
    });
  }
}

function showEditWorkspaceDialog(container, wsId) {
  const ws = workspaces.find(w => w.id === wsId);
  if (!ws) return;

  const dialog = document.createElement('div');
  dialog.className = 'dialog-overlay';
  dialog.innerHTML = `
    <div class="dialog">
      <div class="dialog__header">
        <h2>Edit Workspace</h2>
        <button class="dialog__close">&times;</button>
      </div>
      <div class="dialog__body">
        <div class="form-group">
          <label class="label">ID</label>
          <input type="text" class="input" id="ws-id" value="${ws.id}" disabled />
        </div>
        <div class="form-group">
          <label class="label">Label</label>
          <input type="text" class="input" id="ws-label" value="${ws.label || ''}" />
        </div>
        <div class="form-group">
          <label class="label">Path</label>
          <input type="text" class="input" value="${ws.ctn_dir}" disabled />
        </div>
        <div class="form-group">
          <label class="label">Tags (comma-separated)</label>
          <input type="text" class="input" id="ws-tags" value="${ws.tags.join(', ')}" />
        </div>
        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" id="ws-pinned" ${ws.pinned ? 'checked' : ''} />
            Pinned
          </label>
        </div>
        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" id="ws-enabled" ${ws.enabled !== false ? 'checked' : ''} />
            Enabled
          </label>
        </div>
      </div>
      <div class="dialog__footer">
        <button class="btn btn--ghost" id="cancel-btn">Cancel</button>
        <button class="btn btn--primary" id="save-btn">Save</button>
      </div>
    </div>
  `;

  document.body.appendChild(dialog);

  dialog.querySelector('.dialog__close').addEventListener('click', () => dialog.remove());
  dialog.querySelector('#cancel-btn').addEventListener('click', () => dialog.remove());

  dialog.querySelector('#save-btn').addEventListener('click', async () => {
    const label = dialog.querySelector('#ws-label').value;
    const tags = dialog.querySelector('#ws-tags').value.split(',').map(t => t.trim()).filter(Boolean);
    const pinned = dialog.querySelector('#ws-pinned').checked;
    const enabled = dialog.querySelector('#ws-enabled').checked;

    try {
      await api.updateWorkspace(wsId, { label, tags, pinned, enabled });
      workspaces = await api.listWorkspaces();
      container.querySelector('#workspaces-tbody').innerHTML = workspaces.map(renderWorkspaceRow).join('');
      attachWorkspacesListeners(container);
      dialog.remove();
      showNotice('Workspace updated', 'success');
    } catch (err) {
      showNotice(err.message, 'error');
    }
  });
}

function renderServerTab() {
  const server = config?.server || {};
  return `
    <div class="server-tab" data-aos="fade-up">
      <div class="server-sections">
        <div class="server-section">
          <div class="server-section__header">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
            <h4>Network</h4>
          </div>
          <div class="server-section__body">
            <div class="network-diagram">
              <div class="network-node">
                <div class="network-node__icon">
                  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
                </div>
                <span class="network-node__label">Server</span>
                <span class="network-node__value">${server.bind || '127.0.0.1'}</span>
              </div>
              <span class="network-arrow">→</span>
              <div class="network-node">
                <div class="network-node__icon">
                  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
                </div>
                <span class="network-node__label">Clients</span>
                <span class="network-node__value">${workspaces.length}</span>
              </div>
            </div>
            
            <div class="port-visualization">
              <div class="port-item port-item--used">
                <span class="port-item__label">HTTP</span>
                <span class="port-item__value">${server.http_port || 8770}</span>
              </div>
              <div class="port-item port-item--used">
                <span class="port-item__label">REST</span>
                <span class="port-item__value">${server.rest_port || 8771}</span>
              </div>
            </div>
            
            <div class="form-group">
              <label class="label">Bind Address</label>
              <input type="text" class="input" id="server-bind" value="${server.bind || '127.0.0.1'}" />
              <small class="input-hint input-hint--warning">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
                Warning: Changing from 127.0.0.1 may expose your server
              </small>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label class="label">HTTP Port</label>
                <input type="number" class="input" id="server-http-port" value="${server.http_port || 8770}" min="1024" max="65535" />
              </div>
              <div class="form-group">
                <label class="label">REST Port</label>
                <input type="number" class="input" id="server-rest-port" value="${server.rest_port || 8771}" min="1024" max="65535" />
              </div>
            </div>
          </div>
        </div>
        
        <div class="server-section">
          <div class="server-section__header">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
            <h4>Performance</h4>
          </div>
          <div class="server-section__body">
            <div class="form-group">
              <label class="label">Default Workspace</label>
              <select class="input" id="server-default-workspace">
                <option value="">None</option>
                ${workspaces.map(ws => `
                  <option value="${ws.id}" ${server.default_workspace === ws.id ? 'selected' : ''}>${ws.label || ws.id}</option>
                `).join('')}
              </select>
            </div>
            <div class="form-group">
              <div class="range-header">
                <label class="label">Worker Threads</label>
                <span class="range-value" id="worker-threads-value">${server.worker_threads || 8}</span>
              </div>
              <input type="range" class="range" id="server-worker-threads" min="1" max="32" value="${server.worker_threads || 8}" />
              <div style="display: flex; justify-content: space-between; margin-top: var(--space-xs);">
                <span style="font-size: 10px; color: var(--on-surface-variant);">1</span>
                <span style="font-size: 10px; color: var(--on-surface-variant);">32</span>
              </div>
            </div>
          </div>
        </div>
        
        <div class="server-section">
          <div class="server-section__header">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <h4>Advanced</h4>
          </div>
          <div class="server-section__body">
            <button class="btn btn--secondary" id="reset-server-btn">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
              Reset to Defaults
            </button>
            <button class="btn btn--ghost" id="export-server-btn" style="margin-left: var(--space-sm);">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
              Export Config
            </button>
          </div>
        </div>
      </div>
      
      <div class="config-card__footer" style="margin-top: var(--space-lg);">
        <button class="btn btn--primary" id="save-server-btn">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
          Save Server Config
        </button>
      </div>
    </div>
  `;
}

function attachServerListeners(container) {
  const workerSlider = container.querySelector('#server-worker-threads');
  if (workerSlider) {
    workerSlider.addEventListener('input', (e) => {
      container.querySelector('#worker-threads-value').textContent = e.target.value;
    });
  }

  const saveBtn = container.querySelector('#save-server-btn');
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const bind = container.querySelector('#server-bind').value;
      const http_port = parseInt(container.querySelector('#server-http-port').value);
      const rest_port = parseInt(container.querySelector('#server-rest-port').value);
      const default_workspace = container.querySelector('#server-default-workspace').value || null;
      const worker_threads = parseInt(container.querySelector('#server-worker-threads').value);

      if (http_port === rest_port) {
        showNotice('HTTP and REST ports cannot be the same', 'error');
        return;
      }

      try {
        await api.patchServerConfig({ bind, http_port, rest_port, default_workspace, worker_threads });
        showNotice('Server config saved', 'success');
      } catch (err) {
        showNotice(err.message, 'error');
      }
    });
  }

  const resetBtn = container.querySelector('#reset-server-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      if (!confirm('Reset server configuration to defaults?')) return;
      
      try {
        await api.patchServerConfig({ 
          bind: '127.0.0.1', 
          http_port: 8770, 
          rest_port: 8771, 
          default_workspace: null, 
          worker_threads: 8 
        });
        config = await api.getConfig();
        container.querySelector('.mcp-content').innerHTML = renderTabContent();
        attachTabListeners(container);
        showNotice('Server config reset to defaults', 'success');
      } catch (err) {
        showNotice(err.message, 'error');
      }
    });
  }

  const exportBtn = container.querySelector('#export-server-btn');
  if (exportBtn) {
    exportBtn.addEventListener('click', () => {
      const server = config?.server || {};
      const blob = new Blob([JSON.stringify(server, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'mcp-server-config.json';
      a.click();
      URL.revokeObjectURL(url);
      showNotice('Config exported', 'success');
    });
  }
}

function renderScalingTab() {
  const residency = config?.residency || {};
  const concurrency = config?.concurrency || {};
  const discovery = config?.discovery || {};
  
  const currentResident = workspaces.filter(w => w.resident).length;
  const maxResident = residency.max_resident_workspaces || 32;
  const residentPercent = Math.round((currentResident / maxResident) * 100);

  return `
    <div class="scaling-tab" data-aos="fade-up">
      <div class="config-card">
        <div class="config-card__header">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 22V4a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v18Z"/><path d="M4 10h16"/><path d="M10 10v4"/><path d="M14 10v4"/></svg>
          <h3>Residency</h3>
        </div>
        <div class="config-card__body">
          <div class="resource-bar">
            <div class="resource-bar__header">
              <span class="resource-bar__label">Active Workspaces</span>
              <span class="resource-bar__value">${currentResident} / ${maxResident}</span>
            </div>
            <div class="resource-bar__track">
              <div class="resource-bar__fill ${residentPercent > 80 ? 'resource-bar__fill--warning' : ''} ${residentPercent > 95 ? 'resource-bar__fill--danger' : ''}" style="width: ${residentPercent}%"></div>
            </div>
          </div>
          
          <div class="preset-buttons">
            <button class="preset-btn" onclick="applyResidencyPreset(8, 300)">Low</button>
            <button class="preset-btn preset-btn--active" onclick="applyResidencyPreset(32, 600)">Medium</button>
            <button class="preset-btn" onclick="applyResidencyPreset(128, 1800)">High</button>
          </div>
          
          <div class="form-group">
            <label class="label">Max Resident Workspaces</label>
            <input type="number" class="input" id="residency-max-resident" value="${residency.max_resident_workspaces || 32}" min="1" max="4096" />
          </div>
          <div class="form-group">
            <div class="range-header">
              <label class="label">Idle Evict Seconds</label>
              <span class="range-value" id="idle-evict-value">${residency.idle_evict_seconds || 600}</span>
            </div>
            <input type="range" class="range" id="residency-idle-evict" min="60" max="7200" value="${residency.idle_evict_seconds || 600}" />
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="label">Max Total Cache (bytes)</label>
              <input type="number" class="input" id="residency-max-total" value="${residency.max_total_cache_bytes || 1073741824}" />
            </div>
            <div class="form-group">
              <label class="label">Max Per-WS Cache (bytes)</label>
              <input type="number" class="input" id="residency-max-per-ws" value="${residency.max_per_workspace_cache_bytes || 134217728}" />
            </div>
          </div>
          <div class="form-group">
            <label class="checkbox-label">
              <input type="checkbox" id="residency-prefetch" ${residency.prefetch_default_workspace !== false ? 'checked' : ''} />
              <span class="checkbox-custom"></span>
              Prefetch Default Workspace
            </label>
          </div>
          <button class="btn btn--primary" id="save-residency-btn">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
            Save Residency
          </button>
        </div>
      </div>

      <div class="config-card">
        <div class="config-card__header">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          <h3>Concurrency</h3>
        </div>
        <div class="config-card__body">
          <div class="form-group">
            <label class="label">Global Inflight Limit</label>
            <input type="number" class="input" id="concurrency-global" value="${concurrency.global_inflight_limit || 256}" />
          </div>
          <div class="form-group">
            <label class="label">Per-Workspace Inflight Limit</label>
            <input type="number" class="input" id="concurrency-per-ws" value="${concurrency.per_workspace_inflight_limit || 16}" />
          </div>
          <div class="form-group">
            <label class="label">Request Timeout (seconds)</label>
            <input type="number" class="input" id="concurrency-timeout" value="${concurrency.request_timeout_seconds || 30}" />
          </div>
          <button class="btn btn--primary" id="save-concurrency-btn">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
            Save Concurrency
          </button>
        </div>
      </div>

      <div class="config-card">
        <div class="config-card__header">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
          <h3>Discovery</h3>
        </div>
        <div class="config-card__body">
          <div class="form-group">
            <label class="label">CTN Directory Globs (one per line)</label>
            <textarea class="input textarea" id="discovery-globs" rows="4">${(discovery.ctn_dir_globs || []).join('\n')}</textarea>
          </div>
          
          <div class="discovery-preview">
            <div class="discovery-preview__title">Current Configuration</div>
            <div class="discovery-preview__list">
              ${(discovery.ctn_dir_globs || []).slice(0, 3).map(g => `
                <div class="discovery-preview__item">
                  <span class="discovery-preview__item-icon">✓</span>
                  <span>${g}</span>
                </div>
              `).join('')}
              ${(discovery.ctn_dir_globs || []).length > 3 ? `<div class="discovery-preview__item"><span>+${(discovery.ctn_dir_globs || []).length - 3} more</span></div>` : ''}
            </div>
          </div>
          
          <div class="form-group">
            <label class="checkbox-label">
              <input type="checkbox" id="discovery-watch" ${discovery.watch !== false ? 'checked' : ''} />
              <span class="checkbox-custom"></span>
              Watch for Changes
            </label>
          </div>
          <div class="form-group">
            <label class="label">Ignore IDs (comma-separated)</label>
            <input type="text" class="input" id="discovery-ignore" value="${(discovery.ignore_ids || []).join(', ')}" />
          </div>
          <div class="form-row">
            <button class="btn btn--primary" id="save-discovery-btn">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              Save Discovery
            </button>
            <button class="btn btn--secondary" id="rescan-btn">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 21h5v-5"/></svg>
              Rescan Now
            </button>
          </div>
        </div>
      </div>
    </div>
  `;
}

function applyResidencyPreset(maxResident, idleEvict) {
  const container = document.querySelector('.mcp-page');
  if (!container) return;
  
  container.querySelector('#residency-max-resident').value = maxResident;
  container.querySelector('#residency-idle-evict').value = idleEvict;
  container.querySelector('#idle-evict-value').textContent = idleEvict;
  
  container.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('preset-btn--active'));
  event.target.classList.add('preset-btn--active');
}

function attachScalingListeners(container) {
  const idleSlider = container.querySelector('#residency-idle-evict');
  if (idleSlider) {
    idleSlider.addEventListener('input', (e) => {
      container.querySelector('#idle-evict-value').textContent = e.target.value;
    });
  }

  const saveResidency = container.querySelector('#save-residency-btn');
  if (saveResidency) {
    saveResidency.addEventListener('click', async () => {
      try {
        await api.patchResidencyConfig({
          max_resident_workspaces: parseInt(container.querySelector('#residency-max-resident').value),
          idle_evict_seconds: parseInt(container.querySelector('#residency-idle-evict').value),
          max_total_cache_bytes: parseInt(container.querySelector('#residency-max-total').value),
          max_per_workspace_cache_bytes: parseInt(container.querySelector('#residency-max-per-ws').value),
          prefetch_default_workspace: container.querySelector('#residency-prefetch').checked,
        });
        showNotice('Residency config saved', 'success');
      } catch (err) {
        showNotice(err.message, 'error');
      }
    });
  }

  const saveConcurrency = container.querySelector('#save-concurrency-btn');
  if (saveConcurrency) {
    saveConcurrency.addEventListener('click', async () => {
      try {
        await api.patchConcurrencyConfig({
          global_inflight_limit: parseInt(container.querySelector('#concurrency-global').value),
          per_workspace_inflight_limit: parseInt(container.querySelector('#concurrency-per-ws').value),
          request_timeout_seconds: parseInt(container.querySelector('#concurrency-timeout').value),
        });
        showNotice('Concurrency config saved', 'success');
      } catch (err) {
        showNotice(err.message, 'error');
      }
    });
  }

  const saveDiscovery = container.querySelector('#save-discovery-btn');
  if (saveDiscovery) {
    saveDiscovery.addEventListener('click', async () => {
      try {
        await api.patchDiscoveryConfig({
          ctn_dir_globs: container.querySelector('#discovery-globs').value.split('\n').map(s => s.trim()).filter(Boolean),
          watch: container.querySelector('#discovery-watch').checked,
          ignore_ids: container.querySelector('#discovery-ignore').value.split(',').map(s => s.trim()).filter(Boolean),
        });
        showNotice('Discovery config saved', 'success');
      } catch (err) {
        showNotice(err.message, 'error');
      }
    });
  }

  const rescanBtn = container.querySelector('#rescan-btn');
  if (rescanBtn) {
    rescanBtn.addEventListener('click', async () => {
      try {
        const result = await api.adminDiscover();
        showNotice(`Discovery complete: +${result.added.length} -${result.removed.length} ~${result.updated.length}`, 'success');
      } catch (err) {
        showNotice(err.message, 'error');
      }
    });
  }
}

const AGENTS = [
  { id: 'claude_desktop', name: 'Claude Desktop', logo: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>' },
  { id: 'cursor', name: 'Cursor', logo: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/><path d="M13 13l6 6"/></svg>' },
  { id: 'continue', name: 'Continue', logo: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>' },
  { id: 'cline', name: 'Cline', logo: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 9h6"/><path d="M9 13h6"/><path d="M9 17h4"/></svg>' },
  { id: 'windsurf', name: 'Windsurf', logo: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2.5 17.5c3-2 6-2 9 0"/><path d="M2.5 12.5c3-2 6-2 9 0"/><path d="M2.5 7.5c3-2 6-2 9 0"/><path d="M11.5 17.5c3-2 6-2 9 0"/><path d="M11.5 12.5c3-2 6-2 9 0"/><path d="M11.5 7.5c3-2 6-2 9 0"/></svg>' },
  { id: 'generic', name: 'Generic', logo: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>' },
];

function renderAgentsTab() {
  return `
    <div class="agents-tab" data-aos="fade-up">
      <div class="section-header">
        <div class="section-header__info">
          <h2 class="section-header__title">Agent Integrations</h2>
          <span class="section-header__subtitle">Copy the configuration snippet for your AI agent</span>
        </div>
      </div>
      <div class="agents-grid">
        ${AGENTS.map(agent => renderAgentCard(agent)).join('')}
      </div>
    </div>
  `;
}

async function renderAgentCard(agent) {
  let snippet = '';
  let lastUpdated = 'Unknown';
  try {
    const result = await api.getAgentSnippet(agent.id);
    snippet = result.snippet;
    lastUpdated = result.last_updated || 'Recently';
  } catch (err) {
    snippet = `// Error loading snippet: ${err.message}`;
  }

  const docsUrl = {
    claude_desktop: 'https://docs.anthropic.com/en/docs/claude-code',
    cursor: 'https://cursor.sh/docs',
    continue: 'https://continue.dev/docs',
    cline: 'https://github.com/saucelabs/cline',
    windsurf: 'https://docs.codeium.com/windsurf',
    generic: '#'
  }[agent.id] || '#';

  return `
    <div class="agent-card">
      <div class="agent-card__header">
        <div class="agent-card__logo">${agent.logo}</div>
        <div>
          <h3 class="agent-card__title">${agent.name}</h3>
          <div class="agent-card__status">
            <span class="agent-card__status-dot"></span>
            <span>Compatible</span>
          </div>
        </div>
      </div>
      <div class="agent-card__code">
        <pre><code>${escapeHtml(snippet)}</code></pre>
      </div>
      <div class="agent-card__footer">
        <span class="agent-card__timestamp">Updated: ${lastUpdated}</span>
        <a href="${docsUrl}" target="_blank" class="agent-card__link">
          Docs
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" x2="21" y1="14" y2="3"/></svg>
        </a>
      </div>
      <button class="btn btn--primary btn--block" data-agent="${agent.id}" data-snippet="${escapeAttr(snippet)}">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
        Copy Config
      </button>
    </div>
  `;
}

function attachAgentsListeners(container) {
  container.querySelectorAll('[data-agent]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const snippet = btn.dataset.snippet;
      try {
        await navigator.clipboard.writeText(snippet);
        showNotice('Copied to clipboard!', 'success');
      } catch (err) {
        showNotice('Failed to copy', 'error');
      }
    });
  });
}

function renderError(err) {
  return `
    <div class="error-panel">
      <div class="error-panel__icon">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>
      </div>
      <div class="error-panel__content">
        <h3>Failed to load MCP configuration</h3>
        <p>${escapeHtml(err.message)}</p>
      </div>
      <button class="btn btn--primary" data-action="retry">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 21h5v-5"/></svg>
        Retry
      </button>
    </div>
  `;
}

function truncatePath(path, maxLen = 40) {
  if (path.length <= maxLen) return path;
  return '...' + path.slice(-maxLen + 3);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function escapeAttr(text) {
  return text.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function showNotice(message, tone = 'info') {
  const slot = document.getElementById('notice-slot');
  if (!slot) return;
  const el = document.createElement('div');
  el.className = `notice notice--${tone}`;
  el.textContent = message;
  slot.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}
