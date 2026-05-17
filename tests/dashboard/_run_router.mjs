// Smoke test for router `:param` pattern matching.
// The dashboard router pulls `compilePattern` into a private helper; we
// exercise it indirectly by registering patterned routes against a stub
// of `location` and `window` and calling `handle()`.

import path from 'node:path';
import { pathToFileURL } from 'node:url';

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');

// Minimal DOM stubs so router.js can import without browser globals.
globalThis.window = {
  addEventListener: () => {},
};
globalThis.location = { hash: '' };
globalThis.document = {
  getElementById: () => null,
  createElement: () => ({
    set textContent(_v) {},
    get innerHTML() { return ''; },
    set innerHTML(_v) {},
  }),
};
globalThis.localStorage = {
  _data: Object.create(null),
  getItem(k) { return this._data[k] ?? null; },
  setItem(k, v) { this._data[k] = String(v); },
};

const modulePath = path.join(repoRoot, 'batho', 'dashboard', 'assets', 'js', 'router.js');
const { router } = await import(pathToFileURL(modulePath).href);

// Patch mount to capture handler invocations.
const calls = [];
router.mount = (_) => {};

router.register('#/hypergraph', async (params) => {
  calls.push({ route: '#/hypergraph', params: serialize(params) });
  return null;
});
router.register('#/hypergraph/file/:fileId', async (params) => {
  calls.push({ route: '#/hypergraph/file/:fileId', params: serialize(params) });
  return null;
});
router.register('#/hypergraph/node/:nodeId', async (params) => {
  calls.push({ route: '#/hypergraph/node/:nodeId', params: serialize(params) });
  return null;
});
// Wildcard so 404 path doesn't touch the DOM.
router.register('*', async ({ path: p }) => {
  calls.push({ route: '*', path: p });
  return null;
});

function serialize(params) {
  const out = {};
  for (const [k, v] of params.entries()) out[k] = v;
  return out;
}

async function visit(hash) {
  globalThis.location.hash = hash;
  await router.handle();
}

await visit('#/hypergraph');
await visit('#/hypergraph/file/src%2Fauth%2Flogin.py');
await visit('#/hypergraph/node/some-id-123');
// Unknown route, no patterned match: falls through to 404 (no wildcard registered).
await visit('#/does-not-exist');

process.stdout.write(JSON.stringify(calls, null, 2));
