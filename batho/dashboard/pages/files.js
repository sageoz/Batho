export async function renderFiles(params) {
  const c = document.createElement('div');
  c.className = 'page page--files';
  c.innerHTML = `<div class="panel panel--stub"><div class="panel__title">Files</div><div class="panel__divider"></div><div class="panel__message">Coming in Phase 2.</div></div>`;
  return c;
}
