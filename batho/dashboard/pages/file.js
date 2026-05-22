/**
 * File viewer page - displays source code with syntax highlighting and optional BSG mode.
 */

import { loadFileReconstruction, loadIndex, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { router } from '../assets/js/router.js';

export async function renderFile(params) {
  const filePath = params.get('filePath');
  let indexId = params.get('indexId');
  
  if (!indexId) {
    indexId = localStorage.getItem('batho.activeIndexId');
    // Fallback: if no active index, try to get current index from API
    if (!indexId) {
      try {
        const indexData = await loadIndex();
        indexId = indexData.currentIndexId;
        if (indexId) {
          localStorage.setItem('batho.activeIndexId', indexId);
          console.log('[file viewer] set active index from API:', indexId);
        }
      } catch (e) {
        console.warn('[file viewer] could not load index:', e);
      }
    }
  }

  const container = document.createElement('div');
  container.className = 'page page--file';
  container.innerHTML = `
    <div class="panel file-viewer file-viewer--loading" aria-busy="true">
      <div class="file-loading">
        <svg class="file-loading__spinner" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/>
        </svg>
        <span>Loading file…</span>
      </div>
    </div>
  `;

  if (!filePath) {
    container.innerHTML = renderErrorPanel(new Error('No file path specified'));
    return container;
  }

  try {
    console.log('[file viewer] loading reconstructed file:', { filePath, indexId });
    const fileData = await loadFileReconstruction(indexId, filePath);
    
    const content = fileData.content || '';
    const entities = fileData.entities || [];
    const metadata = fileData.metadata || {};
    
    // Debug: log what we received
    console.log('[file viewer] reconstructed data:', {
      entityCount: metadata.entityCount,
      hasSyntaxGlue: metadata.hasSyntaxGlue
    });

    // Build breadcrumb from file path
    const pathParts = filePath.split('/');
    const fileName = pathParts[pathParts.length - 1];
    const breadcrumb = buildBreadcrumb(pathParts);

    const fileExt = fileName.split('.').pop()?.toLowerCase() || '';
    const fileIcon = getFileIconForExt(fileExt);
    const language = fileExt || 'plaintext';
    
    container.innerHTML = `
      <div class="file-viewer">
        <div class="file-header">
          <div class="file-breadcrumb">${breadcrumb}</div>
          <div class="file-toolbar">
            <button class="file-btn file-btn--back" data-action="back" title="Back to files">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
              Files
            </button>
            <div class="file-actions">
              <button class="file-btn file-btn--copy" data-action="copy" title="Copy to clipboard">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                <span class="btn-label">Copy</span>
              </button>
              <button class="file-btn file-btn--raw" data-action="raw" title="View raw content">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
                <span class="btn-label">Raw</span>
              </button>
            </div>
          </div>
          <div class="file-meta">
            <span class="file-meta__icon">${fileIcon}</span>
            <span class="file-meta__item file-meta__filename">${escapeHtml(fileName)}</span>
            <span class="file-meta__sep">·</span>
            <span class="file-meta__item" style="color: var(--accent-cyan)">Reconstructed from BSG</span>
            <span class="file-meta__sep">·</span>
            <span class="file-meta__item">${content.split('\\n').length} lines</span>
            <span class="file-meta__sep">·</span>
            <span class="file-meta__item">${formatBytes(new TextEncoder().encode(content).length)}</span>
            <span class="file-meta__sep">·</span>
            <span class="file-meta__item">${metadata.entityCount || 0} entities</span>
            ${metadata.hasSyntaxGlue ? `
              <span class="file-meta__sep">·</span>
              <span class="file-meta__item" style="color: var(--primary-container)">${metadata.syntaxGlueCount} SYNTAX_GLUE</span>
            ` : ''}
          </div>
        </div>
        
        <div class="file-content-wrapper">
          <div class="file-entity-sidebar" id="entity-sidebar" style="display: flex;">
            <div class="entity-sidebar__header">
              <span>Entities</span>
              <span class="entity-sidebar__count" id="entity-count"></span>
            </div>
            <div class="entity-sidebar__filter" id="entity-filter"></div>
            <div class="entity-sidebar__list" id="entity-list"></div>
          </div>
          
          <div class="file-code-container">
            <pre class="file-code"><code class="language-${language}" id="code-block"></code></pre>
          </div>
        </div>
      </div>
    `;

    // Render code content
    const codeBlock = container.querySelector('#code-block');
    codeBlock.dataset.rawContent = content;
    codeBlock.dataset.language = language;
    
    // Wire up buttons
    const backBtn = container.querySelector('[data-action="back"]');
    if (backBtn) {
      backBtn.addEventListener('click', () => router.navigate('#/files'));
    }

    const copyBtn = container.querySelector('[data-action="copy"]');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => copyToClipboard(content, copyBtn));
    }

    const rawBtn = container.querySelector('[data-action="raw"]');
    if (rawBtn) {
      rawBtn.addEventListener('click', () => viewRaw(filePath, content));
    }

    // Always ON BSG Mode
    const sidebar = container.querySelector('#entity-sidebar');
    const entityList = container.querySelector('#entity-list');
    const entityCount = container.querySelector('#entity-count');
    const entityFilter = container.querySelector('#entity-filter');

    highlightEntities(codeBlock, entities);
    renderEntitySidebar(entityList, entities, entityCount);
    renderEntityFilter(entityFilter, entities, (filteredType) => {
      const filtered = filteredType 
        ? entities.filter(e => (e.type || 'unknown').toLowerCase() === filteredType)
        : entities;
      renderEntitySidebar(entityList, filtered, entityCount);
      highlightEntities(codeBlock, filtered);
    });

    // Wire up breadcrumb navigation
    container.querySelectorAll('.breadcrumb-part[data-nav="files"]').forEach((el) => {
      el.addEventListener('click', () => router.navigate('#/files'));
    });
    container.querySelectorAll('.breadcrumb-part[data-path]').forEach((el) => {
      el.addEventListener('click', () => {
        const path = el.dataset.path;
        if (path) router.navigate('#/files');  // Navigate to files list (could be enhanced to navigate to specific folder)
      });
    });

  } catch (err) {
    console.error('[batho] File viewer error:', err);
    container.innerHTML = renderErrorPanel(err);

    // Wire up error panel button handlers
    const errorBackBtn = container.querySelector('[data-action="back"]');
    if (errorBackBtn) {
      errorBackBtn.addEventListener('click', () => router.navigate('#/files'));
    }
    const errorRetryBtn = container.querySelector('[data-action="retry"]');
    if (errorRetryBtn) {
      errorRetryBtn.addEventListener('click', () => {
        // Retry by re-rendering with same params
        router.refresh();
      });
    }
  }

  return container;
}

function buildBreadcrumb(pathParts) {
  const parts = ['Files', ...pathParts];
  return parts.map((part, i) => {
    if (i === 0) {
      return `
        <span class="breadcrumb-part breadcrumb-root" data-nav="files">
          <svg class="breadcrumb-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          <span class="breadcrumb-label">${escapeHtml(part)}</span>
        </span>
      `;
    }
    const isLast = i === parts.length - 1;
    const partialPath = pathParts.slice(0, i).join('/');
    const icon = isLast 
      ? `<svg class="breadcrumb-icon breadcrumb-icon--file" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`
      : `<svg class="breadcrumb-icon breadcrumb-icon--folder" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
    
    return `
      <span class="breadcrumb-sep">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" opacity="0.4"><polyline points="9 18 15 12 9 6"/></svg>
      </span>
      <span class="breadcrumb-part ${isLast ? 'breadcrumb-current' : ''}" data-path="${isLast ? '' : escapeAttr(partialPath)}">
        ${!isLast ? icon : ''}
        <span class="breadcrumb-label">${escapeHtml(part)}</span>
      </span>
    `;
  }).join('');
}

function renderEntityFilter(container, entities, onFilter) {
  if (!entities || entities.length === 0) {
    container.innerHTML = '';
    return;
  }
  
  // Count entities by type
  const typeCounts = {};
  entities.forEach(e => {
    const type = (e.type || 'unknown').toLowerCase();
    typeCounts[type] = (typeCounts[type] || 0) + 1;
  });
  
  const types = Object.keys(typeCounts).sort();
  const typeColors = {
    function: '#4f46e5',   /* Indigo primary */
    class: '#06b6d4',      /* Cyan secondary */
    method: '#6366f1',     /* Indigo light */
    variable: '#8b5cf6',   /* Violet */
    module: '#10b981',     /* Emerald success */
    import: '#f59e0b',     /* Amber warning */
    export: '#ef4444'      /* Red error */
  };
  
  container.innerHTML = `
    <div class="entity-filter__label">Filter:</div>
    <button class="entity-filter__chip entity-filter__chip--active" data-type="">All (${entities.length})</button>
    ${types.map(type => `
      <button class="entity-filter__chip" data-type="${escapeAttr(type)}" style="--chip-color: ${escapeAttr(typeColors[type] || '#9ca3af')}">
        ${escapeHtml(type)} (${typeCounts[type]})
      </button>
    `).join('')}
  `;
  
  // Add click handlers
  container.querySelectorAll('.entity-filter__chip').forEach(chip => {
    chip.addEventListener('click', () => {
      container.querySelectorAll('.entity-filter__chip').forEach(c => c.classList.remove('entity-filter__chip--active'));
      chip.classList.add('entity-filter__chip--active');
      onFilter(chip.dataset.type || null);
    });
  });
}

function highlightEntities(codeBlock, entities) {
  const rawContent = codeBlock.dataset.rawContent;
  const lines = rawContent.split('\n');
  
  // Build a map of line -> entities
  const lineMap = new Map();
  for (const entity of entities) {
    const startLine = entity.startLine || entity.start_line || 0;
    const endLine = entity.endLine || entity.end_line || startLine;
    
    for (let i = startLine; i <= endLine; i++) {
      if (!lineMap.has(i)) lineMap.set(i, []);
      lineMap.get(i).push(entity);
    }
  }
  
  // Build HTML with entity highlighting
  const highlightedLines = lines.map((line, i) => {
    const lineNum = i + 1;
    const lineEntities = lineMap.get(lineNum) || [];
    
    if (lineEntities.length > 0) {
      const primaryEntity = lineEntities[0];
      const entityType = escapeHtml((primaryEntity.type || 'unknown').toLowerCase());
      const entityId = primaryEntity.id || '';
      
      return `<span class="line-content line-entity line-entity--${entityType}" data-entity-id="${escapeAttr(entityId)}" data-line="${lineNum}">${escapeHtml(line) || ' '}</span>`;
    }
    
    return `<span class="line-content" data-line="${lineNum}">${escapeHtml(line) || ' '}</span>`;
  });
  
  codeBlock.innerHTML = highlightedLines.join('\n');
}

function renderCodeWithLineNumbers(codeBlock, content) {
  const language = codeBlock.dataset.language || 'plaintext';
  const lines = content.split('\n');
  
  // Build HTML with line numbers as data-line attributes
  const codeLines = lines.map((line, i) => {
    const lineNum = i + 1;
    // Use data-line for CSS ::before to show line number
    // Escape HTML to prevent XSS but preserve for Prism to tokenize
    return `<span class="line-content" data-line="${lineNum}">${escapeHtml(line) || ' '}</span>`;
  });
  
  codeBlock.innerHTML = codeLines.join('\n');
  codeBlock.className = `language-${language}`;
  
  // Apply syntax highlighting with Prism if available
  if (window.Prism) {
    // Use Prism's highlightElement which handles the DOM properly
    window.Prism.highlightElement(codeBlock);
  }
}

function renderEntitySidebar(container, entities, countEl) {
  if (countEl) {
    countEl.textContent = entities.length;
  }
  
  if (!entities || entities.length === 0) {
    container.innerHTML = `
      <div class="entity-sidebar__empty">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.5; margin-bottom: 8px;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
        <div>No entities</div>
      </div>
    `;
    return;
  }
  
  const typeIcons = {
    function: '⚡',
    class: '◆',
    method: '●',
    variable: '○',
    module: '□',
    import: '←',
    export: '→'
  };
  
  const html = entities.map(entity => {
    const type = (entity.type || 'unknown').toLowerCase();
    const name = entity.name || 'unnamed';
    const startLine = entity.startLine || entity.start_line || 0;
    const endLine = entity.endLine || entity.end_line || startLine;
    const lines = startLine === endLine ? `L${startLine}` : `L${startLine}-${endLine}`;
    const icon = typeIcons[type] || '●';
    
    return `
      <div class="entity-item entity-item--${escapeHtml(type)}" data-entity-id="${escapeAttr(entity.id || '')}" data-start-line="${startLine}" data-end-line="${endLine}">
        <div class="entity-item__row">
          <span class="entity-item__icon">${icon}</span>
          <span class="entity-item__name">${escapeHtml(name)}</span>
          <span class="entity-item__lines">${lines}</span>
        </div>
        <div class="entity-item__type">${entity.type || 'UNKNOWN'}</div>
      </div>
    `;
  }).join('');
  
  container.innerHTML = html;
  
  // Add click handlers to navigate to entity lines and highlight full range
  container.querySelectorAll('.entity-item').forEach(item => {
    item.addEventListener('click', () => {
      const startLine = parseInt(item.dataset.startLine, 10);
      const endLine = parseInt(item.dataset.endLine, 10) || startLine;
      
      // Scroll to start line
      const startElement = document.querySelector(`[data-line="${startLine}"]`);
      if (startElement) {
        startElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      
      // Highlight all lines from start to end
      for (let i = startLine; i <= endLine; i++) {
        const lineEl = document.querySelector(`[data-line="${i}"]`);
        if (lineEl) {
          lineEl.classList.add('line-highlight');
          setTimeout(() => lineEl.classList.remove('line-highlight'), 2000);
        }
      }
    });
  });
}

async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const originalHtml = btn.innerHTML;
    const labelSpan = btn.querySelector('.btn-label');
    if (labelSpan) {
      labelSpan.textContent = 'Copied!';
      setTimeout(() => labelSpan.textContent = 'Copy', 1500);
    } else {
      btn.innerHTML = 'Copied!';
      setTimeout(() => btn.innerHTML = originalHtml, 1500);
    }
  } catch (err) {
    console.error('Failed to copy:', err);
    const originalHtml = btn.innerHTML;
    btn.innerHTML = 'Failed';
    setTimeout(() => btn.innerHTML = originalHtml, 1500);
  }
}

function viewRaw(filePath, content) {
  const blob = new Blob([content], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const newWindow = window.open(url, '_blank');
  if (newWindow) {
    newWindow.document.title = filePath;
  }
  // Clean up URL after a delay
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

function renderErrorPanel(err) {
  const isMissing = err && err.name === 'MissingArtifactError';
  let title = 'Error';
  let message = err?.message || 'An unknown error occurred';
  let icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';

  if (isMissing) {
    title = 'File Not Found';
    message = 'Could not load the requested file.';
    icon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="18"/></svg>';
  }

  return `
    <div class="panel error-panel">
      <div class="error-panel__icon">${icon}</div>
      <div class="error-panel__title">${escapeHtml(title)}</div>
      <div class="error-panel__message">${escapeHtml(message)}</div>
      <div class="error-panel__actions">
        <button class="btn" data-action="back">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
          Back to Files
        </button>
        <button class="btn" data-action="retry">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          Retry
        </button>
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

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function getFileIconForExt(ext) {
  const icons = {
    py: { color: '#60a5fa', path: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z' },
    js: { color: '#fbbf24', path: 'M3 3h18v18H3V3zm4.73 15.04c.4.85 1.27 1.33 2.18 1.33.91 0 1.77-.41 2.18-1.33.22-.42.33-.91.33-1.41v-5.5h-1.5v5.43c0 .45-.14.68-.4.68-.25 0-.4-.15-.57-.45l-1.21.75zm5.54.04c.77 1.35 2.07 1.33 2.62 1.33.91 0 2.04-.41 2.62-1.33.37-.57.56-1.28.56-2.04v-5.47h-1.5v5.39c0 .61-.1 1.02-.32 1.33-.26.37-.68.56-1.2.56-.68 0-1.05-.33-1.37-.95l-1.41.78z' },
    ts: { color: '#60a5fa', path: 'M3 3h18v18H3V3zm10.71 11.29c.4.85 1.27 1.33 2.18 1.33.91 0 1.77-.41 2.18-1.33.22-.42.33-.91.33-1.41v-1.17h-1.5v1.1c0 .45-.14.68-.4.68-.25 0-.4-.15-.57-.45l-1.21.75.04.08v.02zm-2.5-4.29v1.5h2.5v5h1.5v-5h2.5v-1.5h-6.5z' },
    json: { color: '#9ca3af', path: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8 12h2v2H8v-2zm0 4h2v2H8v-2zm4-4h2v2h-2v-2zm0 4h2v2h-2v-2z' },
    yaml: { color: '#f87171', path: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8 12l2 3 2-3h-4zm4 5l-2 3-2-3h4z' },
    md: { color: '#fff', path: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8 12h2v6H8v-6zm4 0h2v6h-2v-6z' },
    html: { color: '#f97316', path: 'M12 2l-8 4 8 4 8-4-8-4zm0 6.5L4.5 5 12 2l7.5 3L12 8.5zM3 9l9 4.5L21 9v6l-9 4.5L3 15V9z' },
    css: { color: '#60a5fa', path: 'M3 3h18v18H3V3zm13.5 13.5L12 18l-4.5-1.5L6.75 6h10.5l-1.5 10.5h-1.5l.75-6H9.75l-.75 6H12l.75-3h-3l.75-3h7.5l-1.5 10.5h-1.5z' },
    rs: { color: '#f97316', path: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z' },
    go: { color: '#22d3ee', path: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z' },
    java: { color: '#ef4444', path: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z' },
  };
  const { color = '#9ca3af', path = 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z' } = icons[ext] || {};
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="${color}"><path d="${path}"/></svg>`;
}

// Styles injection
const fileStyles = `
  .page--file { height: 100vh; display: flex; flex-direction: column; }
  .file-viewer { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .file-viewer--loading { display: flex; align-items: center; justify-content: center; }
  
  /* Loading state */
  .file-loading { display: flex; align-items: center; gap: var(--space-gutter); color: var(--on-surface-variant); font-family: var(--font-mono); font-size: var(--type-node-code-size); }
  .file-loading__spinner { animation: file-loading-spin 1s linear infinite; color: var(--accent-cyan); }
  @keyframes file-loading-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  
  .file-header {
    padding: var(--space-gutter);
    border-bottom: var(--hairline);
    background: var(--surface-container);
  }
  
  .file-breadcrumb {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    margin-bottom: var(--space-tight);
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 2px;
  }
  
  .breadcrumb-part { 
    cursor: pointer; 
    transition: all 0.15s ease; 
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 6px;
    border-radius: 4px;
  }
  .breadcrumb-part:hover:not(.breadcrumb-current) { 
    color: var(--accent-cyan);
    background: var(--surface-container-high);
  }
  .breadcrumb-root {
    font-weight: 500;
  }
  .breadcrumb-current {
    color: var(--on-surface);
    font-weight: 500;
    background: var(--surface-container-high);
  }
  .breadcrumb-sep { 
    display: inline-flex;
    align-items: center;
    color: var(--on-surface-variant);
    opacity: 0.6;
  }
  .breadcrumb-icon {
    opacity: 0.7;
  }
  .breadcrumb-icon--folder {
    color: var(--accent-cyan);
    opacity: 0.6;
  }
  .breadcrumb-icon--file {
    color: var(--accent-cyan);
    opacity: 0.8;
  }
  .breadcrumb-label {
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .file-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-gutter);
    margin-bottom: var(--space-tight);
  }
  
  .file-actions {
    display: flex;
    gap: var(--space-tight);
  }
  
  .file-btn {
    font-family: var(--font-sans);
    font-size: var(--type-ui-label-size);
    padding: var(--space-sm) var(--space-md);
    background: var(--surface-container-high);
    border: var(--hairline);
    border-radius: var(--radius-md);
    color: var(--on-surface);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: var(--space-xs);
    transition: all var(--transition-base);
  }

  .file-btn:hover {
    background: var(--surface-container-highest);
    border-color: var(--outline);
  }

  .file-btn--active {
    background: var(--primary-container);
    color: var(--on-primary-container);
    border-color: transparent;
  }
  
  .file-btn--disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .file-btn--active .toggle-state {
    background: rgba(255,255,255,0.2);
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    margin-left: 4px;
  }
  
  .file-meta {
    display: flex;
    align-items: center;
    gap: var(--space-tight);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
  }
  
  .file-meta__icon { display: flex; align-items: center; }
  .file-meta__filename { color: var(--on-surface); font-weight: 500; }
  .file-meta__sep { opacity: 0.5; }
  
  .file-content-wrapper {
    flex: 1;
    display: flex;
    overflow: hidden;
  }
  
  .file-entity-sidebar {
    width: 300px;
    flex-shrink: 0;
    border-right: var(--hairline);
    background: var(--surface-container);
    display: none;
    flex-direction: column;
    overflow: hidden;
  }
  
  .entity-sidebar__header {
    padding: var(--space-gutter);
    font-family: var(--font-mono);
    font-size: var(--type-node-code-size);
    font-weight: var(--type-node-code-weight);
    color: var(--on-surface);
    border-bottom: var(--hairline);
    background: var(--surface-container-high);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  
  .entity-sidebar__count {
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
    background: var(--surface-container);
    padding: 2px 8px;
    border-radius: 10px;
  }
  
  .entity-sidebar__filter {
    padding: var(--space-tight) var(--space-gutter);
    border-bottom: var(--hairline);
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    background: var(--surface-container);
  }
  
  .entity-filter__label {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--on-surface-variant);
    text-transform: uppercase;
  }
  
  .entity-filter__chip {
    font-family: var(--font-mono);
    font-size: 10px;
    padding: 3px 8px;
    background: var(--surface-container-high);
    border: var(--hairline);
    border-color: var(--chip-color, var(--outline-variant));
    color: var(--chip-color, var(--on-surface-variant));
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  
  .entity-filter__chip:hover {
    background: var(--surface-container-highest);
  }
  
  .entity-filter__chip--active {
    background: var(--chip-color, var(--accent-cyan)) !important;
    color: #fff !important;
    border-color: var(--chip-color, var(--accent-cyan)) !important;
  }
  
  .entity-sidebar__list { 
    flex: 1;
    overflow-y: auto;
    padding: var(--space-tight);
  }
  
  .entity-sidebar__empty {
    padding: var(--space-gutter);
    color: var(--on-surface-variant);
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  
  .entity-item {
    padding: 8px var(--space-tight);
    margin-bottom: 2px;
    border-radius: 4px;
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    transition: background 0.15s ease;
    border-left: 2px solid transparent;
  }
  
  .entity-item:hover {
    background: var(--surface-container-high);
  }
  
  .entity-item--function { border-left-color: #4f46e5; }
  .entity-item--class { border-left-color: #06b6d4; }
  .entity-item--method { border-left-color: #6366f1; }
  .entity-item--variable { border-left-color: #8b5cf6; }
  .entity-item--module { border-left-color: #10b981; }
  .entity-item--import { border-left-color: #f59e0b; }
  .entity-item--export { border-left-color: #ef4444; }
  
  .entity-item__row {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  
  .entity-item__icon {
    font-size: 10px;
    opacity: 0.7;
  }
  
  .entity-item__type {
    font-size: 9px;
    text-transform: uppercase;
    color: var(--on-surface-variant);
    opacity: 0.8;
    margin-top: 2px;
  }
  
  .entity-item__name {
    color: var(--on-surface);
    font-weight: 500;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .entity-item__lines {
    font-size: 9px;
    color: var(--on-surface-variant);
    opacity: 0.7;
  }
  
  .file-code-container {
    flex: 1;
    overflow: auto;
    background: var(--surface);
  }
  
  .file-code {
    margin: 0;
    padding: var(--space-gutter);
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.6;
    tab-size: 2;
    min-height: 100%;
  }
  
  .line-content {
    display: block;
    padding-left: 60px;
    position: relative;
    min-height: 1.6em;
  }
  
  .line-content::before {
    content: attr(data-line);
    position: absolute;
    left: 0;
    width: 45px;
    text-align: right;
    color: var(--on-surface-variant);
    opacity: 0.5;
    user-select: none;
  }
  
  .line-entity {
    background: rgba(79, 70, 229, 0.08);
    border-left: 3px solid #4f46e5;
    margin-left: -3px;
  }

  .line-entity--function { background: rgba(79, 70, 229, 0.1); border-left-color: #4f46e5; }
  .line-entity--class { background: rgba(6, 182, 212, 0.1); border-left-color: #06b6d4; }
  .line-entity--method { background: rgba(99, 102, 241, 0.1); border-left-color: #6366f1; }
  .line-entity--variable { background: rgba(139, 92, 246, 0.1); border-left-color: #8b5cf6; }
  .line-entity--module { background: rgba(16, 185, 129, 0.1); border-left-color: #10b981; }
  .line-entity--import { background: rgba(245, 158, 11, 0.1); border-left-color: #f59e0b; }
  .line-entity--export { background: rgba(239, 68, 68, 0.1); border-left-color: #ef4444; }
  
  .line-highlight {
    animation: line-pulse 2s ease-out;
  }
  
  @keyframes line-pulse {
    0% { background: rgba(6, 182, 212, 0.4); }
    100% { background: transparent; }
  }
  
  /* Prism.js theme overrides */
  .file-code code[class*="language-"] {
    background: transparent;
    text-shadow: none;
  }
  
  /* Error panel */
  .error-panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: calc(var(--space-gutter) * 4);
    text-align: center;
    min-height: 400px;
  }
  
  .error-panel__icon {
    color: var(--tertiary);
    margin-bottom: var(--space-gutter);
    opacity: 0.8;
  }
  
  .error-panel__title {
    font-size: var(--type-section-header-size);
    font-weight: var(--type-section-header-weight);
    color: var(--on-surface);
    margin-bottom: var(--space-tight);
  }
  
  .error-panel__message {
    color: var(--on-surface-variant);
    margin-bottom: var(--space-gutter);
    max-width: 400px;
  }
  
  .error-panel__actions {
    display: flex;
    gap: var(--space-tight);
  }
  
  .error-panel__actions .btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  
  @media (max-width: 768px) {
    .file-entity-sidebar { width: 100%; position: absolute; z-index: 10; height: 100%; }
    .file-toolbar { flex-wrap: wrap; }
    .file-actions { order: -1; width: 100%; justify-content: flex-end; }
  }
`;

function injectStyles() {
  if (document.getElementById('file-viewer-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'file-viewer-styles';
  styleEl.textContent = fileStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
