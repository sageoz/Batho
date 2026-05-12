/**
 * CTN loader - loads artifacts from .ctn/ directory.
 */

class MissingArtifactError extends Error {
  constructor(path) { super(`Missing artifact: ${path}`); this.name = 'MissingArtifactError'; this.path = path; }
}

class ParseError extends Error {
  constructor(path, message) { super(`Parse error in ${path}: ${message}`); this.name = 'ParseError'; this.path = path; }
}

class SchemaMismatchError extends Error {
  constructor(message) { super(message); this.name = 'SchemaMismatchError'; }
}

class NotImplementedError extends Error {
  constructor(method) { super(`${method} is not implemented yet`); this.name = 'NotImplementedError'; }
}

function camelize(str) { return str.replace(/_([a-z])/g, (_, c) => c.toUpperCase()); }

function normalize(obj) {
  if (Array.isArray(obj)) return obj.map(normalize);
  if (obj && typeof obj === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(obj)) out[camelize(k)] = normalize(v);
    return out;
  }
  return obj;
}

async function fetchWithProgress(url, onProgress) {
  const response = await fetch(url);
  if (!response.ok) throw new MissingArtifactError(url);
  const contentLength = response.headers.get('content-length');
  const total = contentLength ? parseInt(contentLength, 10) : 0;
  const reader = response.body.getReader();
  const chunks = []; let loaded = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value); loaded += value.length;
    if (onProgress && total > 0) onProgress({ loaded, total, percent: Math.round((loaded / total) * 100) });
  }
  const allChunks = new Uint8Array(loaded);
  let position = 0;
  for (const chunk of chunks) { allChunks.set(chunk, position); position += chunk.length; }
  return allChunks;
}

async function parseJsonWithProgress(url, onProgress) {
  const bytes = await fetchWithProgress(url, onProgress);
  const text = new TextDecoder().decode(bytes);
  try { return JSON.parse(text); }
  catch (e) { throw new ParseError(url, e.message); }
}

export async function loadIndex(onProgress) {
  const url = '/.ctn/index.json';
  const data = await parseJsonWithProgress(url, onProgress);
  if (typeof data.current_index_id !== 'string') throw new SchemaMismatchError('current_index_id must be a string');
  if (typeof data.indexes !== 'object' || data.indexes === null) throw new SchemaMismatchError('indexes must be an object');
  return normalize(data);
}

export async function loadGraph(indexId) { throw new NotImplementedError('loadGraph'); }
export async function loadBsg(indexId) { throw new NotImplementedError('loadBsg'); }
export async function loadOverview(indexId) { throw new NotImplementedError('loadOverview'); }
export async function loadFilesMd(indexId) { throw new NotImplementedError('loadFilesMd'); }
export async function loadMetrics() { throw new NotImplementedError('loadMetrics'); }
export async function loadInterceptStats() { throw new NotImplementedError('loadInterceptStats'); }
export async function loadFileHashes() { throw new NotImplementedError('loadFileHashes'); }
export async function loadGraphStreaming(id, onProgress) { throw new NotImplementedError('loadGraphStreaming'); }
export function invalidate(indexId) { console.log(`[ctn-loader] invalidate(${indexId})`); }

export { MissingArtifactError, ParseError, SchemaMismatchError, NotImplementedError };
