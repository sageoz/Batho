/**
 * CTN loader - loads artifacts via the Batho bridge REST API.
 *
 * Behavior notes:
 * - JSON keys are normalized from snake_case to camelCase, EXCEPT when a key
 *   looks like an opaque identifier (contains digits, dashes, dots, slashes,
 *   colons or whitespace). This prevents corruption of index_ids, plugin
 *   names, rule names, etc. that happen to contain `_x` substrings.
 * - `MissingArtifactError.path` is the bridge URL that 404'd, allowing callers
 *   to distinguish "no index" from "no overview for this index".
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
  // unavailable: use response.text() / response.json() directly.
  if (!onProgress || !response.body || !response.body.getReader) {
    return new TextEncoder().encode(await response.text());
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
  const bytes = await fetchWithProgress(url, onProgress);
  const text = new TextDecoder().decode(bytes);
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new ParseError(url, e.message);
  }
}

export async function loadIndex(onProgress) {
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

export async function loadGraph(indexId) {
  if (!indexId) throw new SchemaMismatchError('loadGraph requires an indexId');
  const data = await bridgeGet(`artifacts/graph_json?index_id=${encodeURIComponent(indexId)}`);

  const entities = (data.entities || []).map(normalize);
  const relationships = (data.relationships || []).map(normalize);
  const entitiesById = {};
  for (const e of entities) {
    if (e.id) entitiesById[e.id] = e;
  }

  return { entities, relationships, entitiesById };
}

export async function loadBsg(indexId) {
  if (!indexId) throw new SchemaMismatchError('loadBsg requires an indexId');
  const data = await bridgeGet(`artifacts/bsg_json?index_id=${encodeURIComponent(indexId)}`);
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
  const data = await bridgeGet(`artifacts/context_overview_json?index_id=${encodeURIComponent(indexId)}`);

  // Map snake_case JSON from the bridge to the shape the dashboard expects.
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
  const data = await bridgeGet(`artifacts/context_files_json?index_id=${encodeURIComponent(indexId)}`);

  // Map snake_case JSON to camelCase for dashboard consumption.
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
  const data = await bridgeGet('patches');
  // Normalize patch entries from snake_case to camelCase
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
  const data = await bridgeGet(`patches/${encodeURIComponent(operationId)}`);
  return normalize(data);
}

export async function loadSnapshotDiff(baseId, newId) {
  if (!baseId || !newId) throw new SchemaMismatchError('loadSnapshotDiff requires both baseId and newId');
  const data = await bridgeGet(`snapshots/diff?base=${encodeURIComponent(baseId)}&new=${encodeURIComponent(newId)}`);
  return normalize(data);
}

export async function loadMetrics() {
  try {
    const data = await bridgeGet('artifacts/metrics_json');
    return normalize(data);
  } catch (e) {
    if (e.name === 'MissingArtifactError') return null;
    throw e;
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
}

export {
  MissingArtifactError,
  ParseError,
  SchemaMismatchError,
  IndexEntryMissingError,
  NotImplementedError,
};
