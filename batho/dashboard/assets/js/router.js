/**
 * Hash-based router with register/navigate/on('change') API.
 *
 * Supports a single style of dynamic segment: any path component of the form
 * `:name` matches an arbitrary URL-encoded value and is exposed back to
 * handlers via `params.get('name')`. Exact routes are tried first, then
 * patterned routes in registration order, then the `*` wildcard fallback.
 */

const router = {
  routes: new Map(),
  // Patterned routes that contain `:param` segments. Keyed by the original
  // pattern string to keep them deduped; values include a compiled regex
  // and the ordered list of param names so we can populate URLSearchParams.
  patternedRoutes: new Map(),
  listeners: new Map(),
  defaultRoute: '#/overview',

  register(path, handler) {
    if (path.includes(':')) {
      this.patternedRoutes.set(path, {
        handler,
        ...compilePattern(path),
      });
    } else {
      this.routes.set(path, handler);
    }
  },

  navigate(path, params = {}) {
    const queryString = Object.keys(params).length > 0
      ? '?' + new URLSearchParams(params).toString() : '';
    const hash = path.startsWith('#') ? path : `#${path}`;
    location.hash = hash + queryString;
  },

  on(event, listener) {
    if (!this.listeners.has(event)) this.listeners.set(event, []);
    this.listeners.get(event).push(listener);
  },

  emit(event, data) {
    const listeners = this.listeners.get(event) || [];
    listeners.forEach(listener => listener(data));
  },

  parseHash(hash) {
    if (!hash || hash === '#') return { path: this.defaultRoute, params: new URLSearchParams() };
    const cleanHash = hash.startsWith('#') ? hash.slice(1) : hash;
    const [pathPart, queryPart] = cleanHash.split('?');
    const path = pathPart.startsWith('/') ? pathPart : '/' + pathPart;
    const params = new URLSearchParams(queryPart || '');
    return { path: '#' + path, params };
  },

  async refresh() {
    // Re-handle the current route without changing the URL
    return this.handle();
  },

  async handle() {
    const { path, params } = this.parseHash(location.hash || this.defaultRoute);
    this.emit('change', { path, params });

    let handler = this.routes.get(path);
    let matchedRoute = path;

    if (!handler) {
      for (const [pattern, entry] of this.patternedRoutes) {
        const match = entry.regex.exec(path);
        if (!match) continue;
        for (let i = 0; i < entry.paramNames.length; i += 1) {
          params.set(entry.paramNames[i], decodeURIComponent(match[i + 1] || ''));
        }
        handler = entry.handler;
        matchedRoute = pattern;
        break;
      }
    }

    if (!handler) {
      const wildcard = this.routes.get('*');
      if (wildcard) {
        try { this.mount(await wildcard({ path, params })); }
        catch (err) { this.emit('error', err); this.mount(this.renderError(err)); }
      } else { this.mount(this.render404(path)); }
      return;
    }

    try { this.mount(await handler(params, { path, matchedRoute })); }
    catch (err) { this.emit('error', err); this.mount(this.renderError(err)); }
  },

  mount(element) {
    const mountPoint = document.getElementById('page-mount');
    if (mountPoint) { mountPoint.innerHTML = ''; mountPoint.appendChild(element); }
  },

  render404(path) {
    const container = document.createElement('div');
    container.className = 'panel panel--stub not-found';
    container.innerHTML = `
      <div class="not-found__code">404</div>
      <div class="not-found__divider"></div>
      <div class="not-found__message">Route ${path} is not part of the app.</div>
      <button class="btn" data-navigate="#/overview">return to overview</button>
    `;
    container.querySelector('[data-navigate]').addEventListener('click', () => this.navigate('#/overview'));
    return container;
  },

  renderError(err) {
    const container = document.createElement('div');
    container.className = 'panel error-panel';
    container.innerHTML = `
      <div class="error-panel__icon">⚠</div>
      <div class="error-panel__title">Structural Fault</div>
      <div class="error-panel__message">${this.escapeHtml(err.message || 'An unknown error occurred')}</div>
      <div class="error-panel__actions">
        <button class="btn" data-action="retry">retry</button>
        <button class="btn" data-action="snapshots">open snapshots</button>
      </div>
    `;
    container.querySelector('[data-action="retry"]').addEventListener('click', () => this.handle());
    container.querySelector('[data-action="snapshots"]').addEventListener('click', () => this.navigate('#/snapshots'));
    return container;
  },

  escapeHtml(text) { const d = document.createElement('div'); d.textContent = text; return d.innerHTML; },

  start() {
    const savedRoute = localStorage.getItem('batho.lastRoute');
    if (savedRoute && !location.hash) location.hash = savedRoute;
    window.addEventListener('hashchange', () => this.handle());
    this.handle();
  }
};

/**
 * Compile a route pattern containing `:name` segments into a regex and an
 * ordered list of param names. Each `:name` greedily matches a single
 * (URL-encoded) path component but allows encoded slashes (`%2F`).
 *
 * Example: `'#/hypergraph/file/:fileId'` →
 *   { regex: /^#\/hypergraph\/file\/([^/]+)$/, paramNames: ['fileId'] }
 */
function compilePattern(pattern) {
  const paramNames = [];
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
  const regexSrc = escaped.replace(/:([A-Za-z_][A-Za-z0-9_]*)/g, (_, name) => {
    paramNames.push(name);
    return '([^/]+)';
  });
  return { regex: new RegExp('^' + regexSrc + '$'), paramNames };
}

export { router };
