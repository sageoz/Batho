import { streamParseGraph } from './graph-stream.js';

/**
 * CTN loader - loads artifacts directly from the .ctn/ folder, with bridge
 * REST API as fallback for computed endpoints (diff, search, etc.).
 *
 * Behavior notes:
 * - JSON keys are normalized from snake_case to camelCase, EXCEPT when a key
 *   looks like an opaque identifier (contains digits, dashes, dots, slashes,
 *   colons or whitespace). This prevents corruption of index_ids, plugin
 *   names, rule names, etc. that happen to contain `_x` substrings.
 * - `MissingArtifactError.path` is the URL that 404'd, allowing callers
 *   to distinguish "no index" from "no overview for this index".
 * - All artifact loading prefers `/.ctn/` direct file access over the
 *   bridge API so the dashboard works even when the bridge is unavailable.
 */

class MissingArtifactError extends Error {
  constructor(path) {
    super(`Missing artifact: ${path}`);
    this.name = 'MissingArtifactError';
    this.path = path;
  }
}

class ParseError extends Error {
  constructor(path, message) {
    super(`Parse error in ${path}: ${message}`);
    this.name = 'ParseError';
    this.path = path;
  }
}

class SchemaMismatchError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SchemaMismatchError';
  }
}

class IndexEntryMissingError extends Error {
  constructor(id) {
    super(`Index entry not found: ${id}`);
    this.name = 'IndexEntryMissingError';
    this.id = id;
  }
}

class NotImplementedError extends Error {
  constructor(method) {
    super(`${method} is not implemented yet`);
    this.name = 'NotImplementedError';
  }
}

/**
 * Detect keys that should NOT be camelized: opaque identifiers, hashes,
 * timestamps, plugin/rule names containing dashes, dotted paths, etc.
 */
function isOpaqueKey(key) {
  if (typeof key !== 'string' || key.length === 0) return true;
  // Anything containing a digit, dash, dot, slash, colon or whitespace is
  // treated as an opaque ID and preserved verbatim.
  if (/[0-9\-./:\s]/.test(key)) return true;
  return false;
}

function camelize(str) {
  return str.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      const newKey = isOpaqueKey(k) ? k : camelize(k);
      out[newKey] = normalize(v);
    }
    return out;
  }
  return value;
}

const BRIDGE_BASE = '/api/v1/bridge';
const CTN_BASE = '/.ctn';

// Cache for the .ctn/index.json so we can resolve artifact output paths.
let _ctnIndexCache = null;
let _ctnIndexPromise = null;

async function fetchCtnJson(path) {
  const url = `${CTN_BASE}/${path}`;
  let response;
  try {
    response = await fetch(url);
  } catch (e) {
    throw new MissingArtifactError(url);
  }
  if (!response.ok) throw new MissingArtifactError(url);
  try {
    return await response.json();
  } catch (e) {
    throw new ParseError(url, e.message);
  }
}

async function fetchCtnText(path) {
  const url = `${CTN_BASE}/${path}`;
  let response;
  try {
    response = await fetch(url);
  } catch (e) {
    throw new MissingArtifactError(url);
  }
  if (!response.ok) throw new MissingArtifactError(url);
  return response.text();
}

async function loadCtnIndex() {
  if (_ctnIndexCache) return _ctnIndexCache;
  if (_ctnIndexPromise) return _ctnIndexPromise;
  _ctnIndexPromise = fetchCtnJson('index.json');
  try {
    _ctnIndexCache = await _ctnIndexPromise;
    return _ctnIndexCache;
  } catch (e) {
    _ctnIndexPromise = null;
    throw e;
  }
}

function resolveCtnArtifactPath(indexId, artifactKey) {
  const idx = _ctnIndexCache?.indexes?.[indexId];
  if (!idx) return null;
  const rawPath = idx.outputs?.[artifactKey];
  if (!rawPath) return null;
  // Strip leading '.ctn/' so it becomes a relative path under CTN_BASE.
  return rawPath.replace(/^\.ctn\//, '');
}

function invalidateCtnIndex() {
  _ctnIndexCache = null;
  _ctnIndexPromise = null;
}

async function bridgeGet(path) {
  const url = `${BRIDGE_BASE}/${path}`;
  let response;
  try {
    response = await fetch(url);
  } catch (e) {
    throw new MissingArtifactError(url);
  }
  if (!response.ok) throw new MissingArtifactError(url);
  const envelope = await response.json();
  if (!envelope.ok) {
    const err = new MissingArtifactError(url);
    err.message = envelope.error?.message || err.message;
    throw err;
  }
  return envelope.data;
}

async function bridgeGetWithProgress(path, onProgress) {
  const url = `${BRIDGE_BASE}/${path}`;
  const envelope = await parseJsonWithProgress(url, onProgress);
  if (!envelope?.ok) {
    const err = new MissingArtifactError(url);
    err.message = envelope?.error?.message || err.message;
    throw err;
  }
  return envelope.data;
}

async function fetchWithProgress(url, onProgress) {
  let response;
  try {
    response = await fetch(url);
  } catch (e) {
    // Network failure / server down → surface as missing.
    throw new MissingArtifactError(url);
  }
  if (!response.ok) throw new MissingArtifactError(url);

  // Fast path when no progress callback is supplied or body streaming is
  // unavailable: return text directly to avoid a no-op encode-decode cycle.
  if (!onProgress || !response.body || !response.body.getReader) {
    return await response.text();
  }

  const contentLength = response.headers.get('content-length');
  const total = contentLength ? parseInt(contentLength, 10) : 0;
  const reader = response.body.getReader();
  const chunks = [];
  let loaded = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    if (onProgress && total > 0) {
      onProgress({ loaded, total, percent: Math.round((loaded / total) * 100) });
    }
  }
  const allChunks = new Uint8Array(loaded);
  let position = 0;
  for (const chunk of chunks) {
    allChunks.set(chunk, position);
    position += chunk.length;
  }
  return allChunks;
}

async function parseJsonWithProgress(url, onProgress) {
  const result = await fetchWithProgress(url, onProgress);
  const text = typeof result === 'string' ? result : new TextDecoder().decode(result);
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new ParseError(url, e.message);
  }
}

export async function loadIndex(onProgress) {
  // Try direct .ctn/index.json first for zero-dependency loading.
  try {
    const ctnData = await loadCtnIndex();
    const entries = Object.values(ctnData.indexes || {});
    let currentIndexId = ctnData.current_index_id || '';
    const persistenceModel = ctnData.persistence_model || null;
    const schemaVersion = ctnData.schema_version || null;

    const indexes = {};
    for (const entry of entries) {
      const id = entry.index_id || entry.id;
      if (!id) continue;
      indexes[id] = normalize(entry);
    }

    if (!currentIndexId && entries.length > 0) {
      let latestTimestamp = '';
      for (const entry of entries) {
        const ts = entry.timestamp || '';
        if (ts > latestTimestamp) {
          latestTimestamp = ts;
          currentIndexId = entry.index_id || entry.id;
        }
      }
    }

    return {
      currentIndexId: currentIndexId || (entries.length > 0 ? entries[0].index_id || entries[0].id : ''),
      indexes,
      persistenceModel,
      schemaVersion,
    };
  } catch (ctnErr) {
    // Fall back to bridge API if .ctn/index.json is unavailable.
  }

  const response = await bridgeGet('indexes');

  // The bridge now returns an object with data[], current_index_id,
  // persistence_model, and schema_version at the top level.
  const entries = Array.isArray(response) ? response : (response.data || []);
  let currentIndexId = response.current_index_id || '';
  const persistenceModel = response.persistence_model || null;
  const schemaVersion = response.schema_version || null;

  if (!Array.isArray(entries)) {
    throw new SchemaMismatchError('indexes must be an array');
  }

  // Preserve original index_id keys; camelize entry contents so callers can
  // use idiomatic JS field names like `entry.fileCount` / `entry.repoHash`.
  const indexes = {};

  for (const entry of entries) {
    const id = entry.index_id;
    if (!id) continue;
    indexes[id] = normalize(entry);
  }

  // Fallback: if no current_index_id from the API, pick the latest by timestamp.
  if (!currentIndexId && entries.length > 0) {
    let latestTimestamp = '';
    for (const entry of entries) {
      if (entry.timestamp && entry.timestamp > latestTimestamp) {
        latestTimestamp = entry.timestamp;
        currentIndexId = entry.index_id;
      }
    }
  }

  return {
    currentIndexId: currentIndexId || (entries.length > 0 ? entries[0].index_id : ''),
    indexes,
    persistenceModel,
    schemaVersion,
  };
}

function parseOverviewMd(raw) {
  const doc = {
    raw,
    generatedAt: undefined,
    summary: {},
    fileDistribution: [],
    languageBreakdown: [],
  };

  const generatedMatch = raw.match(/\*Generated:\s*([^\*]+)\*/);
  if (generatedMatch) doc.generatedAt = generatedMatch[1].trim();

  const summaryMatch = raw.match(
    /## Repository Summary\s*\|[\s\S]*?\|[-\s]+\|[\s\S]*?\| (\d+) \|[\s\S]*?\| (\d+) \|[\s\S]*?\| (\d+) \|/
  );
  if (summaryMatch) {
    doc.summary = {
      totalFiles: parseInt(summaryMatch[1].replace(/,/g, ''), 10),
      totalEntities: parseInt(summaryMatch[2].replace(/,/g, ''), 10),
      totalRelationships: parseInt(summaryMatch[3].replace(/,/g, ''), 10),
    };
  }

  const distMatch = raw.match(/## File Distribution\s*([\s\S]*?)(?=##|$)/);
  if (distMatch) {
    const lines = distMatch[1].split('\n').filter((l) => l.includes('**'));
    const categories = { Source: 'Source', Tests: 'Tests', Docs: 'Docs', Config: 'Config' };
    for (const line of lines) {
      for (const [cat, label] of Object.entries(categories)) {
        const m = line.match(
          new RegExp(`\\*\\*${cat}\\*\\*:\\s*(\\d+)\\s*files?\\s*\\(([\\d.]+)%`)
        );
        if (m) {
          const files = parseInt(m[1].replace(/,/g, ''), 10);
          doc.fileDistribution.push({ category: label, files, percent: parseFloat(m[2]) });
          break;
        }
      }
    }
  }

  const langMatch = raw.match(/## Language Breakdown\s*\|[\s\S]*?\|[-\s]+\|[\s\S]*?(?=##|$)/);
  if (langMatch) {
    const rows = langMatch[0].split('\n').filter((l) => l.match(/^\| [^|]/));
    for (const row of rows) {
      const cells = row.split('|').map((c) => c.trim()).filter(Boolean);
      if (cells.length >= 3 && cells[0] !== 'Language') {
        const lang = cells[0];
        const files = parseInt(cells[1].replace(/,/g, ''), 10);
        const pct = parseFloat(cells[2].replace('%', ''));
        if (!isNaN(files)) doc.languageBreakdown.push({ language: lang, files, percent: pct });
      }
    }
  }

  return doc;
}

export async function loadGraph(indexId, onProgress) {
  if (!indexId) throw new SchemaMismatchError('loadGraph requires an indexId');

  // Try direct .ctn/ file first.
  try {
    await loadCtnIndex();
    const ctnPath = resolveCtnArtifactPath(indexId, 'graph_json');
    if (ctnPath) {
      const data = await fetchCtnJson(ctnPath);
      const entities = (data.entities || []).map(normalize);
      const relationships = (data.relationships || []).map(normalize);
      const entitiesById = {};
      for (const e of entities) {
        if (e.id) entitiesById[e.id] = e;
      }
      return { entities, relationships, entitiesById };
    }
  } catch (ctnErr) {
    // Fall through to bridge API.
  }

  const path = `artifacts/graph_json?index_id=${encodeURIComponent(indexId)}`;
  let data;

  if (onProgress) {
    try {
      const url = `${BRIDGE_BASE}/${path}`;
      data = await streamParseGraph(url, onProgress);
    } catch (_) {
      data = await bridgeGetWithProgress(path, onProgress);
    }
  } else {
    data = await bridgeGet(path);
  }

  const entities = (data.entities || []).map(normalize);
  const relationships = (data.relationships || []).map(normalize);
  const entitiesById = {};
  for (const e of entities) {
    if (e.id) entitiesById[e.id] = e;
  }

  return { entities, relationships, entitiesById };
}

export async function loadBsg(indexId, onProgress) {
  if (!indexId) throw new SchemaMismatchError('loadBsg requires an indexId');

  try {
    await loadCtnIndex();
    const ctnPath = resolveCtnArtifactPath(indexId, 'bsg_json');
    if (ctnPath) {
      const data = await fetchCtnJson(ctnPath);
      return normalize(data);
    }
  } catch (ctnErr) {
    // Fall through to bridge API.
  }

  const path = `artifacts/bsg_json?index_id=${encodeURIComponent(indexId)}`;
  const data = onProgress
    ? await bridgeGetWithProgress(path, onProgress)
    : await bridgeGet(path);
  return normalize(data);
}

export async function loadSnapshotJson(snapshotId) {
  if (!snapshotId) throw new SchemaMismatchError('loadSnapshotJson requires a snapshotId');

  // The dashboard server serves /.ctn/* directly from the ctn directory.
  const url = `/.ctn/snapshots/${encodeURIComponent(snapshotId)}.json`;
  let response;
  try {
    response = await fetch(url);
  } catch (e) {
    throw new MissingArtifactError(url);
  }
  if (!response.ok) throw new MissingArtifactError(url);
  const data = await response.json();
  return normalize(data);
}

export async function loadOverview(indexId) {
  if (!indexId) throw new SchemaMismatchError('loadOverview requires an indexId');

  try {
    await loadCtnIndex();
    const ctnPath = resolveCtnArtifactPath(indexId, 'overview_json');
    if (ctnPath) {
      const data = await fetchCtnJson(ctnPath);
      const fileDistribution = (data.file_distribution || []).map((d) => ({
        category: d.category,
        files: d.files,
        percent: d.percentage,
      }));
      const languageBreakdown = (data.language_breakdown || []).map((d) => ({
        language: d.language,
        files: d.files,
        percent: d.percentage,
      }));
      return {
        raw: null,
        generatedAt: data.generated_at,
        summary: {
          totalFiles: data.summary?.total_files ?? 0,
          totalEntities: data.summary?.total_entities ?? 0,
          totalRelationships: data.summary?.total_relationships ?? 0,
        },
        fileDistribution,
        languageBreakdown,
      };
    }
  } catch (ctnErr) {
    // Fall through to bridge API.
  }

  const data = await bridgeGet(`artifacts/context_overview_json?index_id=${encodeURIComponent(indexId)}`);

  const fileDistribution = (data.file_distribution || []).map((d) => ({
    category: d.category,
    files: d.files,
    percent: d.percentage,
  }));

  const languageBreakdown = (data.language_breakdown || []).map((d) => ({
    language: d.language,
    files: d.files,
    percent: d.percentage,
  }));

  return {
    raw: null,
    generatedAt: data.generated_at,
    summary: {
      totalFiles: data.summary?.total_files ?? 0,
      totalEntities: data.summary?.total_entities ?? 0,
      totalRelationships: data.summary?.total_relationships ?? 0,
    },
    fileDistribution,
    languageBreakdown,
  };
}

export async function loadFiles(indexId) {
  if (!indexId) throw new SchemaMismatchError('loadFiles requires an indexId');

  try {
    await loadCtnIndex();
    const ctnPath = resolveCtnArtifactPath(indexId, 'files_json');
    if (ctnPath) {
      const data = await fetchCtnJson(ctnPath);
      const categories = (data.categories || []).map((cat) => ({
        name: cat.name,
        fileCount: cat.file_count,
        entityCount: cat.entity_count,
        directories: (cat.directories || []).map((dir) => ({
          path: dir.path,
          files: (dir.files || []).map((f) => ({
            name: f.name,
            relativePath: f.relative_path,
            entitySummary: f.entity_summary ? {
              total: f.entity_summary.total || 0,
              breakdown: f.entity_summary.breakdown || {},
            } : { total: 0, breakdown: {} },
            entities: (f.entities || []).map(normalize),
          })),
        })),
      }));
      return {
        schemaVersion: data.schema_version,
        generatedAt: data.generated_at,
        repo: data.repo,
        summary: {
          totalFiles: data.summary?.total_files ?? 0,
          totalEntities: data.summary?.total_entities ?? 0,
        },
        categories,
      };
    }
  } catch (ctnErr) {
    // Fall through to bridge API.
  }

  const data = await bridgeGet(`artifacts/context_files_json?index_id=${encodeURIComponent(indexId)}`);

  const categories = (data.categories || []).map((cat) => ({
    name: cat.name,
    fileCount: cat.file_count,
    entityCount: cat.entity_count,
    directories: (cat.directories || []).map((dir) => ({
      path: dir.path,
      files: (dir.files || []).map((f) => ({
        name: f.name,
        relativePath: f.relative_path,
        entitySummary: f.entity_summary ? {
          total: f.entity_summary.total || 0,
          breakdown: f.entity_summary.breakdown || {},
        } : { total: 0, breakdown: {} },
        entities: (f.entities || []).map(normalize),
      })),
    })),
  }));

  return {
    schemaVersion: data.schema_version,
    generatedAt: data.generated_at,
    repo: data.repo,
    summary: {
      totalFiles: data.summary?.total_files ?? 0,
      totalEntities: data.summary?.total_entities ?? 0,
    },
    categories,
  };
}

export async function loadPatchesIndex() {
  // Try direct .ctn/patches/index.json first.
  try {
    const data = await fetchCtnJson('patches/index.json');
    const patches = (data.patches || []).map(normalize);
    return {
      schemaVersion: data.schema_version,
      patches,
      totalPatches: data.total_patches ?? patches.length,
      lastUpdated: data.last_updated ?? null,
    };
  } catch (ctnErr) {
    // Fall through to bridge API.
  }

  const data = await bridgeGet('patches');
  const patches = (data.patches || []).map(normalize);
  return {
    schemaVersion: data.schema_version,
    patches,
    totalPatches: data.total_patches ?? patches.length,
    lastUpdated: data.last_updated ?? null,
  };
}

export async function loadPatchDetail(operationId) {
  if (!operationId) throw new SchemaMismatchError('loadPatchDetail requires an operationId');

  // Try direct .ctn/patches/{operationId}.json first.
  try {
    const data = await fetchCtnJson(`patches/${encodeURIComponent(operationId)}.json`);
    return normalize(data);
  } catch (ctnErr) {
    // Fall through to bridge API.
  }

  const data = await bridgeGet(`patches/${encodeURIComponent(operationId)}`);
  return normalize(data);
}

export async function loadSnapshotDiff(baseId, newId) {
  if (!baseId || !newId) throw new SchemaMismatchError('loadSnapshotDiff requires both baseId and newId');

  // Diff is a computed endpoint — try bridge first, then fallback if needed.
  try {
    const data = await bridgeGet(`snapshots/diff?base=${encodeURIComponent(baseId)}&new=${encodeURIComponent(newId)}`);
    return normalize(data);
  } catch (bridgeErr) {
    if (bridgeErr.name === 'MissingArtifactError') {
      // Attempt a client-side diff from raw snapshot files as last resort.
      try {
        const [base, next] = await Promise.all([
          loadSnapshotJson(baseId),
          loadSnapshotJson(newId),
        ]);
        return normalize(computeClientSideDiff(base, next));
      } catch (clientErr) {
        throw bridgeErr;
      }
    }
    throw bridgeErr;
  }
}

function computeClientSideDiff(base, next) {
  const baseEntities = new Map((base.entities || []).map((e) => [e.id, e]));
  const nextEntities = new Map((next.entities || []).map((e) => [e.id, e]));
  const added = [];
  const removed = [];
  const modified = [];
  for (const [id, e] of nextEntities) {
    if (!baseEntities.has(id)) added.push(id);
    else if (JSON.stringify(baseEntities.get(id)) !== JSON.stringify(e)) modified.push(id);
  }
  for (const id of baseEntities.keys()) {
    if (!nextEntities.has(id)) removed.push(id);
  }
  return {
    entities: {
      added: added.length,
      removed: removed.length,
      modified: modified.length,
      unchanged: baseEntities.size - removed.length - modified.length,
      addedIds: added,
      removedIds: removed,
      modifiedIds: modified,
    },
    files: { baseCount: 0, newCount: 0, delta: 0 },
    loc: {},
  };
}

export async function loadMetrics() {
  // Metrics are typically computed; try bridge first, then synthesize from index.
  try {
    const data = await bridgeGet('artifacts/metrics_json');
    return normalize(data);
  } catch (bridgeErr) {
    if (bridgeErr.name !== 'MissingArtifactError') throw bridgeErr;
  }

  // Synthesize basic metrics from .ctn/index.json so the dashboard always
  // has something to show.
  try {
    const ctnData = await loadCtnIndex();
    const indexes = Object.values(ctnData.indexes || {});
    if (indexes.length === 0) return null;
    const latest = indexes.reduce((a, b) => (a.timestamp > b.timestamp ? a : b), indexes[0]);
    const stats = latest.stats || {};
    return normalize({
      stats: {
        total_files: latest.file_count || 0,
        total_entities: latest.entity_count || 0,
        total_relationships: latest.relationship_count || 0,
        elapsed_seconds: stats.elapsed_seconds || 0,
        errors: stats.errors || 0,
        workers_used: stats.workers_used || 1,
        files_parsed: stats.files_parsed || latest.file_count || 0,
        files_candidates: stats.files_candidates || latest.file_count || 0,
        cache_hit_rate: stats.cache_hit_rate || 0,
        rules_loaded: stats.rules?.rules_loaded || 0,
        rules_applied: stats.rules?.rules_applied || 0,
      },
    });
  } catch (ctnErr) {
    return null;
  }
}

export async function loadInterceptStats() {
  throw new NotImplementedError('loadInterceptStats');
}

export async function loadFileHashes() {
  throw new NotImplementedError('loadFileHashes');
}

export async function loadGraphStreaming(indexId, onProgress) {
  if (!indexId) throw new SchemaMismatchError('loadGraphStreaming requires an indexId');

  // Try direct .ctn/ file first.
  try {
    await loadCtnIndex();
    const ctnPath = resolveCtnArtifactPath(indexId, 'graph_json');
    if (ctnPath) {
      const raw = await parseJsonWithProgress(`${CTN_BASE}/${ctnPath}`, onProgress);
      const entities = (raw.entities || []).map(normalize);
      const relationships = (raw.relationships || []).map(normalize);
      const entitiesById = {};
      for (const e of entities) {
        if (e.id) entitiesById[e.id] = e;
      }
      return { entities, relationships, entitiesById };
    }
  } catch (ctnErr) {
    // Fall through to bridge API.
  }

  const url = `${BRIDGE_BASE}/artifacts/graph_json?index_id=${encodeURIComponent(indexId)}`;

  try {
    const raw = await parseJsonWithProgress(url, onProgress);
    const entities = (raw.entities || []).map(normalize);
    const relationships = (raw.relationships || []).map(normalize);
    const entitiesById = {};
    for (const e of entities) {
      if (e.id) entitiesById[e.id] = e;
    }
    return { entities, relationships, entitiesById };
  } catch (e) {
    if (e.name === 'ParseError' || e.name === 'MissingArtifactError') {
      return loadGraph(indexId);
    }
    throw e;
  }
}

export function invalidate(indexId) {
  console.log(`[ctn-loader] invalidate(${indexId})`);
  invalidateCtnIndex();
}

export async function loadFileContent(filePath, indexId) {
  if (!filePath) throw new SchemaMismatchError('loadFileContent requires a filePath');

  // Try direct .ctn/ file access first (server serves workspace files at /.ctn/).
  try {
    const url = `${CTN_BASE}/${encodeURIComponent(filePath)}`;
    const response = await fetch(url);
    if (response.ok) {
      const text = await response.text();
      return { content: text, path: filePath, encoding: 'utf-8' };
    }
  } catch (ctnErr) {
    // Fall through to bridge API.
  }

  const encodedPath = encodeURIComponent(filePath);
  const indexParam = indexId ? `&index_id=${encodeURIComponent(indexId)}` : '';
  const url = `file-content?path=${encodedPath}${indexParam}`;
  console.log('[ctn-loader] loadFileContent URL:', url, 'indexId:', indexId);
  const data = await bridgeGet(url);
  return normalize(data);
}

export async function getSnapshotFileList(snapshotId) {
  const snapshot = await loadSnapshotJson(snapshotId);
  const filesMap = new Map();
  const entitiesById = {};
  
  for (const entity of snapshot.entities || []) {
    entitiesById[entity.id] = entity;
    const file = entity.file || '';
    if (!filesMap.has(file)) {
      filesMap.set(file, { path: file, entityCount: 0, entities: [] });
    }
    const fileEntry = filesMap.get(file);
    fileEntry.entities.push(entity);
    fileEntry.entityCount++;
  }
  
  return {
    files: Array.from(filesMap.values()),
    relationships: snapshot.graph?.relationships || snapshot.relationships || [],
    entitiesById
  };
}

export async function getBsgFileEntities(indexId, filePath) {
  const bsg = await loadBsg(indexId);
  return (bsg.nodes || bsg.entities || []).filter(n => n.file === filePath);
}

export async function loadFileReconstruction(indexId, filePath) {
  const encodedPath = encodeURIComponent(filePath);
  const url = `file-reconstruction?path=${encodedPath}&index_id=${encodeURIComponent(indexId)}`;
  const data = await bridgeGet(url);
  return normalize(data);
}

export {
  MissingArtifactError,
  ParseError,
  SchemaMismatchError,
  IndexEntryMissingError,
  NotImplementedError,
};
