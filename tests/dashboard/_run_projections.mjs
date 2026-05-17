// Node test harness for bsg-projections.js.
// Reads a JSON fixture from argv[2], runs all three projections, and
// emits the structured result to stdout as JSON for the pytest wrapper.

import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const fixturePath = process.argv[2];
if (!fixturePath) {
  process.stderr.write('usage: _run_projections.mjs <fixture.json>\n');
  process.exit(2);
}

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');
const modulePath = path.join(repoRoot, 'batho', 'dashboard', 'assets', 'js', 'bsg-projections.js');
const mod = await import(pathToFileURL(modulePath).href);

const fixture = JSON.parse(await readFile(fixturePath, 'utf8'));
const bsg = fixture.bsg;
const calls = fixture.calls || [];

const out = [];
for (const call of calls) {
  let result;
  if (call.fn === 'buildFileGraph') {
    result = mod.buildFileGraph(bsg);
  } else if (call.fn === 'buildFileSubgraph') {
    result = mod.buildFileSubgraph(bsg, call.file);
  } else if (call.fn === 'buildNeighborhood') {
    result = mod.buildNeighborhood(bsg, call.nodeId);
  } else if (call.fn === 'invalidateProjections') {
    mod.invalidateProjections(bsg);
    result = { invalidated: true };
  } else {
    result = { error: `unknown fn: ${call.fn}` };
  }
  // Strip cytoscape-style cycles by stringifying minimal fields.
  out.push({ call, result: trim(result) });
}

function trim(value) {
  return JSON.parse(JSON.stringify(value, (k, v) => {
    if (k === '__nodeIndex' || k === '__edgeIndex') return undefined;
    return v;
  }));
}

process.stdout.write(JSON.stringify(out));
