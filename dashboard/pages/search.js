export async function renderSearch(params) {
  const c = document.createElement('div');
  c.className = 'page page--search';
  c.innerHTML = `<div class="panel panel--stub"><div class="panel__title">Search</div><div class="panel__divider"></div><div class="panel__message">Coming in Phase 5.</div></div>`;
  return c;
}
