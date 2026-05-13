/**
 * Hash-based router with register/navigate/on('change') API.
 */

const router = {
  routes: new Map(),
  listeners: new Map(),
  defaultRoute: '#/overview',

  register(path, handler) { this.routes.set(path, handler); },

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

  async handle() {
    const { path, params } = this.parseHash(location.hash || this.defaultRoute);
    this.emit('change', { path, params });
    const handler = this.routes.get(path);

    if (!handler) {
      const wildcard = this.routes.get('*');
      if (wildcard) {
        try { this.mount(await wildcard({ path, params })); }
        catch (err) { this.emit('error', err); this.mount(this.renderError(err)); }
      } else { this.mount(this.render404(path)); }
      return;
    }

    try { this.mount(await handler(params)); }
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
      <div class="not-found__message">Route ${path} is not part of the cockpit.</div>
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

export { router };
