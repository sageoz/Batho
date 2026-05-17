/**
 * File viewer page - displays source code with syntax highlighting and optional BSG mode.
 */

import { loadFileContent, loadIndex, MissingArtifactError } from '../assets/js/ctn-loader.js';
import { router } from '../assets/js/router.js';

export async function renderFile(params) {
  const filePath = params.get('filePath');
  let indexId = localStorage.getItem('batho.activeIndexId');
  
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

  const container = document.createElement('div');
  container.className = 'page page--file';
  container.innerHTML = `
    <div class="panel file-viewer" aria-busy="true">
      <div class="loading">
        <span class="loading__cursor"></span>
        <span>loading file …</span>
      </div>
    </div>
  `;

  if (!filePath) {
    container.innerHTML = renderErrorPanel(new Error('No file path specified'));
    return container;
  }

  try {
    console.log('[file viewer] loading file:', { filePath, indexId });
    const fileData = await loadFileContent(filePath, indexId);
    
    // Debug: log what we received
    console.log('[file viewer] fileData:', {
      hasEntities: fileData.hasEntities,
      entityCount: fileData.entityCount,
      entitiesLength: fileData.entities?.length,
      language: fileData.language,
      path: fileData.path
    });

    // Build breadcrumb from file path
    const pathParts = filePath.split('/');
    const fileName = pathParts[pathParts.length - 1];
    const breadcrumb = buildBreadcrumb(pathParts);

    container.innerHTML = `
      <div class="file-viewer">
        <div class="file-header">
          <div class="file-breadcrumb">${breadcrumb}</div>
          <div class="file-toolbar">
            <button class="file-btn file-btn--back" data-action="back">← Files</button>
            <div class="file-actions">
              <button class="file-btn file-btn--toggle ${fileData.hasEntities ? '' : 'file-btn--disabled'}" 
                      data-action="toggle-bsg" 
                      ${fileData.hasEntities ? '' : 'disabled'}>
                BSG Mode: <span class="toggle-state">OFF</span>
              </button>
              <button class="file-btn file-btn--copy" data-action="copy">Copy</button>
              <button class="file-btn file-btn--raw" data-action="raw">Raw</button>
            </div>
          </div>
          <div class="file-meta">
            <span class="file-meta__item">${escapeHtml(fileName)}</span>
            <span class="file-meta__sep">·</span>
            <span class="file-meta__item">${fileData.totalLines || 0} lines</span>
            <span class="file-meta__sep">·</span>
            <span class="file-meta__item">${formatBytes(fileData.sizeBytes || 0)}</span>
            ${fileData.hasEntities ? `
              <span class="file-meta__sep">·</span>
              <span class="file-meta__item">${fileData.entityCount || 0} entities</span>
            ` : ''}
          </div>
        </div>
        
        <div class="file-content-wrapper">
          <div class="file-entity-sidebar" id="entity-sidebar" style="display: none;">
            <div class="entity-sidebar__header">Entities</div>
            <div class="entity-sidebar__list" id="entity-list"></div>
          </div>
          
          <div class="file-code-container">
            <pre class="file-code"><code class="language-${fileData.language || 'plaintext'}" id="code-block"></code></pre>
          </div>
        </div>
      </div>
    `;

    // Render code content
    const codeBlock = container.querySelector('#code-block');
    const content = fileData.content || '';
    
    // Store raw content for BSG mode and raw view
    codeBlock.dataset.rawContent = content;
    codeBlock.dataset.language = fileData.language || 'plaintext';
    if (fileData.entities && fileData.entities.length > 0) {
      // Limit entities to prevent dataset attribute overflow (browser limit ~1-2MB)
      // Keep only essential fields and cap at 1000 entities
      const MAX_ENTITIES = 1000;
      const limitedEntities = fileData.entities.slice(0, MAX_ENTITIES).map(e => ({
        id: e.id,
        name: e.name,
        type: e.type,
        startLine: e.startLine,
        endLine: e.endLine
      }));
      codeBlock.dataset.entities = JSON.stringify(limitedEntities);
      if (fileData.entities.length > MAX_ENTITIES) {
        console.warn(`[file viewer] Entity count capped from ${fileData.entities.length} to ${MAX_ENTITIES}`);
      }
    }
    
    // Render with line numbers and syntax highlighting
    renderCodeWithLineNumbers(codeBlock, content);

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

    const toggleBtn = container.querySelector('[data-action="toggle-bsg"]');
    if (toggleBtn && fileData.hasEntities) {
      toggleBtn.addEventListener('click', () => toggleBsgMode(container, toggleBtn));
    }

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
      return `<span class="breadcrumb-part" data-nav="files">${escapeHtml(part)}</span>`;
    }
    const partialPath = pathParts.slice(0, i).join('/');
    return `<span class="breadcrumb-sep">/</span><span class="breadcrumb-part" data-path="${escapeAttr(partialPath)}">${escapeHtml(part)}</span>`;
  }).join('');
}

function toggleBsgMode(container, btn) {
  const codeBlock = container.querySelector('#code-block');
  const sidebar = container.querySelector('#entity-sidebar');
  const entityList = container.querySelector('#entity-list');
  const toggleState = btn.querySelector('.toggle-state');
  
  const isCurrentlyOn = toggleState.textContent === 'ON';
  const newState = !isCurrentlyOn;
  
  toggleState.textContent = newState ? 'ON' : 'OFF';
  btn.classList.toggle('file-btn--active', newState);
  
  if (newState) {
    // Enable BSG mode
    let entities = [];
    try {
      entities = JSON.parse(codeBlock.dataset.entities || '[]');
    } catch (e) {
      console.error('[file viewer] Failed to parse entities:', e);
      entities = [];
    }
    highlightEntities(codeBlock, entities);
    renderEntitySidebar(entityList, entities);
    sidebar.style.display = 'block';
  } else {
    // Disable BSG mode
    const rawContent = codeBlock.dataset.rawContent;
    const language = codeBlock.dataset.language;
    sidebar.style.display = 'none';
    
    // Re-render with line numbers and syntax highlighting
    renderCodeWithLineNumbers(codeBlock, rawContent);
  }
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
      const entityType = (primaryEntity.type || 'unknown').toLowerCase();
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

function renderEntitySidebar(container, entities) {
  if (!entities || entities.length === 0) {
    container.innerHTML = '<div class="entity-sidebar__empty">No entities</div>';
    return;
  }
  
  const html = entities.map(entity => {
    const type = (entity.type || 'unknown').toLowerCase();
    const name = entity.name || 'unnamed';
    const startLine = entity.startLine || entity.start_line || 0;
    const endLine = entity.endLine || entity.end_line || startLine;
    const lines = startLine === endLine ? `L${startLine}` : `L${startLine}-${endLine}`;
    
    return `
      <div class="entity-item entity-item--${type}" data-entity-id="${escapeAttr(entity.id || '')}" data-start-line="${startLine}">
        <span class="entity-item__type">${entity.type || 'UNKNOWN'}</span>
        <span class="entity-item__name">${escapeHtml(name)}</span>
        <span class="entity-item__lines">${lines}</span>
      </div>
    `;
  }).join('');
  
  container.innerHTML = html;
  
  // Add click handlers to navigate to entity lines
  container.querySelectorAll('.entity-item').forEach(item => {
    item.addEventListener('click', () => {
      const startLine = item.dataset.startLine;
      const lineElement = document.querySelector(`[data-line="${startLine}"]`);
      if (lineElement) {
        lineElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
        lineElement.classList.add('line-highlight');
        setTimeout(() => lineElement.classList.remove('line-highlight'), 2000);
      }
    });
  });
}

async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const originalText = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = originalText, 1500);
  } catch (err) {
    console.error('Failed to copy:', err);
    btn.textContent = 'Failed';
    setTimeout(() => btn.textContent = 'Copy', 1500);
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

  if (isMissing) {
    title = 'File Not Found';
    message = 'Could not load the requested file.';
  }

  return `
    <div class="panel error-panel">
      <div class="error-panel__icon">⚠</div>
      <div class="error-panel__title">${escapeHtml(title)}</div>
      <div class="error-panel__message">${escapeHtml(message)}</div>
      <div class="error-panel__actions">
        <button class="btn" data-action="back">← Back to Files</button>
        <button class="btn" data-action="retry">Retry</button>
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
  return escapeHtml(text).replace(/"/g, '&quot;');
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Styles injection
const fileStyles = `
  .page--file { height: 100vh; display: flex; flex-direction: column; }
  .file-viewer { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  
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
  }
  
  .breadcrumb-part { cursor: pointer; }
  .breadcrumb-part:hover { color: var(--accent-cyan); }
  .breadcrumb-sep { margin: 0 4px; opacity: 0.5; }
  
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
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    padding: var(--space-tight) var(--space-gutter);
    background: var(--surface-container-high);
    border: var(--hairline);
    color: var(--on-surface);
    cursor: pointer;
    border-radius: 4px;
  }
  
  .file-btn:hover {
    background: var(--surface-container-highest);
    border-color: var(--accent-cyan);
  }
  
  .file-btn--active {
    background: var(--accent-cyan);
    color: var(--on-primary);
    border-color: var(--accent-cyan);
  }
  
  .file-btn--disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .file-meta {
    display: flex;
    align-items: center;
    gap: var(--space-tight);
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    color: var(--on-surface-variant);
  }
  
  .file-meta__sep { opacity: 0.5; }
  
  .file-content-wrapper {
    flex: 1;
    display: flex;
    overflow: hidden;
  }
  
  .file-entity-sidebar {
    width: 280px;
    flex-shrink: 0;
    border-right: var(--hairline);
    background: var(--surface-container);
    overflow-y: auto;
  }
  
  .entity-sidebar__header {
    padding: var(--space-gutter);
    font-family: var(--font-mono);
    font-size: var(--type-node-code-size);
    font-weight: var(--type-node-code-weight);
    color: var(--on-surface);
    border-bottom: var(--hairline);
    background: var(--surface-container-high);
  }
  
  .entity-sidebar__list { padding: var(--space-tight); }
  .entity-sidebar__empty {
    padding: var(--space-gutter);
    color: var(--on-surface-variant);
    font-style: italic;
  }
  
  .entity-item {
    padding: var(--space-tight);
    margin-bottom: 2px;
    border-radius: 4px;
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  
  .entity-item:hover {
    background: var(--surface-container-high);
  }
  
  .entity-item__type {
    font-size: 10px;
    text-transform: uppercase;
    color: var(--accent-cyan);
    opacity: 0.8;
  }
  
  .entity-item__name {
    color: var(--on-surface);
    font-weight: 500;
  }
  
  .entity-item__lines {
    font-size: 10px;
    color: var(--on-surface-variant);
  }
  
  .entity-item--function .entity-item__type { color: #60a5fa; }
  .entity-item--class .entity-item__type { color: #c084fc; }
  .entity-item--method .entity-item__type { color: #22d3ee; }
  .entity-item--variable .entity-item__type { color: #9ca3af; }
  
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
    background: rgba(96, 165, 250, 0.1);
    border-left: 2px solid #60a5fa;
  }
  
  .line-entity--function { background: rgba(96, 165, 250, 0.1); border-left-color: #60a5fa; }
  .line-entity--class { background: rgba(192, 132, 252, 0.1); border-left-color: #c084fc; }
  .line-entity--method { background: rgba(34, 211, 238, 0.1); border-left-color: #22d3ee; }
  .line-entity--variable { background: rgba(156, 163, 175, 0.1); border-left-color: #9ca3af; }
  .line-entity--module { background: rgba(74, 222, 128, 0.1); border-left-color: #4ade80; }
  
  .line-highlight {
    animation: line-pulse 2s ease-out;
  }
  
  @keyframes line-pulse {
    0% { background: rgba(34, 211, 238, 0.4); }
    100% { background: transparent; }
  }
  
  /* Prism.js theme overrides */
  .file-code code[class*="language-"] {
    background: transparent;
    text-shadow: none;
  }
  
  .loading {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-gutter);
    padding: var(--space-gutter);
    color: var(--on-surface-variant);
    font-family: var(--font-mono);
  }
  
  .loading__cursor {
    display: inline-block;
    width: 8px;
    height: 16px;
    background: var(--accent-cyan);
    animation: blink 1s step-end infinite;
  }
  
  @keyframes blink {
    50% { opacity: 0; }
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
