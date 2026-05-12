export async function renderSnapshots(params) {
  const c = document.createElement('div');
  c.className = 'page page--snapshots';
  c.innerHTML = `<div class="panel panel--stub"><div class="panel__title">Snapshots</div><div class="panel__divider"></div><div class="panel__message">Coming in Phase 1.</div></div>`;
  return c;
}
