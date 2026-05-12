export async function renderRules(params) {
  const c = document.createElement('div');
  c.className = 'page page--rules';
  c.innerHTML = `<div class="panel panel--stub"><div class="panel__title">Rules</div><div class="panel__divider"></div><div class="panel__message">Coming in Phase 4.</div></div>`;
  return c;
}
