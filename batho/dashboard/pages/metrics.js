export async function renderMetrics(params) {
  const c = document.createElement('div');
  c.className = 'page page--metrics';
  c.innerHTML = `<div class="panel panel--stub"><div class="panel__title">Metrics</div><div class="panel__divider"></div><div class="panel__message">Coming in Phase 5.</div></div>`;
  return c;
}
