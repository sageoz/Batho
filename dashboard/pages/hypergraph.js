export async function renderHypergraph(params) {
  const c = document.createElement('div');
  c.className = 'page page--hypergraph';
  c.innerHTML = `<div class="panel panel--stub"><div class="panel__title">Hypergraph</div><div class="panel__divider"></div><div class="panel__message">Coming in Phase 3.</div></div>`;
  return c;
}
