/**
 * BSG projections — pure data transforms used by the hierarchical hypergraph
 * viewer. All functions return plain JSON-shaped objects ready to be mapped
 * into Cytoscape elements by `pages/hypergraph.js`.
 *
 * Three projections are exposed:
 *
 *   - `buildFileGraph(bsg)`           → L1: one node per file, weighted edges.
 *   - `buildFileSubgraph(bsg, file)`  → L2: nodes inside `file` + intra-file edges.
 *   - `buildNeighborhood(bsg, id)`    → L3: center node + immediate neighbors.
 *
 * The shape of the `bsg` argument matches what `ctn-loader.loadBsg()` returns
 * after camelCase normalization (so `indexes.nodes_by_file` becomes
 * `indexes.nodesByFile`, etc.). When indexes are missing (older artifacts)
 * the projections fall back to scanning `bsg.edges` directly.
 *
 * L1 results are memoized on the bsg reference identity via a private
 * WeakMap so repeated drill-down navigation stays O(1).
 */

const _l1Cache = new WeakMap();

/**
 * Resolve the `nodes_by_file` index in either snake or camel form.
 * @param {object} bsg
 * @returns {Record<string,string[]>}
 */
function _nodesByFile(bsg) {
  if (!bsg || !bsg.indexes) return null;
  return bsg.indexes.nodesByFile || bsg.indexes.nodes_by_file || null;
}

/**
 * Resolve `inbound_edges` index in either form.
 * @param {object} bsg
 * @returns {Record<string,string[]> | null}
 */
function _inboundEdges(bsg) {
  if (!bsg || !bsg.indexes) return null;
  return bsg.indexes.inboundEdges || bsg.indexes.inbound_edges || null;
}

/**
 * Resolve `outbound_edges` index in either form.
 * @param {object} bsg
 * @returns {Record<string,string[]> | null}
 */
function _outboundEdges(bsg) {
  if (!bsg || !bsg.indexes) return null;
  return bsg.indexes.outboundEdges || bsg.indexes.outbound_edges || null;
}

/**
 * Resolve `source_id` / `target_id` / `type` across snake and camel variants.
 * @param {object} edge
 */
function _edgeFields(edge) {
  const source = edge.sourceId ?? edge.source_id ?? edge.from ?? edge.source ?? null;
  const target = edge.targetId ?? edge.target_id ?? edge.to ?? edge.target ?? null;
  const type = (edge.relationshipType ?? edge.relationship_type ?? edge.type ?? 'references') + '';
  const id = edge.id ?? `${source}->${target}:${type}`;
  return { source, target, type, id };
}

/**
 * Build a `nodeId → nodeRecord` map. Cached on the bsg object behind a
 * non-enumerable symbol so subsequent calls reuse it.
 * @param {object} bsg
 * @returns {Map<string, object>}
 */
function _nodeIndex(bsg) {
  if (bsg.__nodeIndex instanceof Map) return bsg.__nodeIndex;
  const map = new Map();
  for (const n of bsg.nodes || []) {
    if (n && n.id) map.set(n.id, n);
  }
  Object.defineProperty(bsg, '__nodeIndex', {
    value: map,
    enumerable: false,
    configurable: true,
  });
  return map;
}

/**
 * Build a `edgeId → edgeRecord` map. Cached on the bsg object.
 * @param {object} bsg
 * @returns {Map<string, object>}
 */
function _edgeIndex(bsg) {
  if (bsg.__edgeIndex instanceof Map) return bsg.__edgeIndex;
  const map = new Map();
  for (const e of bsg.edges || []) {
    if (!e) continue;
    const { id } = _edgeFields(e);
    if (id && !map.has(id)) map.set(id, e);
  }
  Object.defineProperty(bsg, '__edgeIndex', {
    value: map,
    enumerable: false,
    configurable: true,
  });
  return map;
}

/**
 * Build the Level 1 inter-file graph.
 *
 * Produces one node per file (with aggregated metadata) and one weighted
 * edge per ordered (sourceFile, targetFile) pair. Self-edges are dropped.
 *
 * @param {object} bsg - Normalised bsg.v1 payload.
 * @returns {{nodes: object[], edges: object[]}}
 */
export function buildFileGraph(bsg) {
  if (!bsg || !Array.isArray(bsg.nodes)) return { nodes: [], edges: [] };

  const cached = _l1Cache.get(bsg);
  if (cached) return cached;

  // ---------------------------------------------------------- file nodes
  // Pre-aggregate file stats by walking nodes once. If indexes.nodesByFile
  // is available we use it for the canonical file list, otherwise we
  // derive it from node.file values.
  const fileStats = new Map(); // file → { nodeCount, languages, services, categories, primaryLanguage }
  const ensure = (file) => {
    let s = fileStats.get(file);
    if (!s) {
      s = {
        nodeCount: 0,
        languages: Object.create(null),
        services: Object.create(null),
        categories: Object.create(null),
        types: Object.create(null),
      };
      fileStats.set(file, s);
    }
    return s;
  };

  const nodesByFileIdx = _nodesByFile(bsg);
  if (nodesByFileIdx) {
    for (const file of Object.keys(nodesByFileIdx)) ensure(file);
  }

  const nodeIdx = _nodeIndex(bsg);
  for (const n of bsg.nodes) {
    if (!n || !n.file) continue;
    const s = ensure(n.file);
    s.nodeCount += 1;
    const lang = (n.language || 'unknown') + '';
    s.languages[lang] = (s.languages[lang] || 0) + 1;
    const svc = (n.serviceTag || n.service_tag || '') + '';
    if (svc) s.services[svc] = (s.services[svc] || 0) + 1;
    const cat = (n.category || '') + '';
    if (cat) s.categories[cat] = (s.categories[cat] || 0) + 1;
    const type = ((n.type || 'unknown') + '').toUpperCase();
    s.types[type] = (s.types[type] || 0) + 1;
  }

  const pickDominant = (bag) => {
    let best = '';
    let bestCount = -1;
    for (const [k, v] of Object.entries(bag)) {
      if (v > bestCount) {
        best = k;
        bestCount = v;
      }
    }
    return best;
  };

  const fileNodes = [];
  for (const [file, s] of fileStats) {
    fileNodes.push({
      id: file,
      file,
      nodeCount: s.nodeCount,
      language: pickDominant(s.languages),
      serviceTag: pickDominant(s.services),
      category: pickDominant(s.categories),
      languages: { ...s.languages },
      services: { ...s.services },
      categories: { ...s.categories },
      types: { ...s.types },
    });
  }
  fileNodes.sort((a, b) => (a.file < b.file ? -1 : a.file > b.file ? 1 : 0));

  // ---------------------------------------------------------- file edges
  // Aggregate every symbol-level edge into a (srcFile, tgtFile) bucket.
  const edgeBuckets = new Map(); // "src\0tgt" → { source, target, weight, types: Record<type,count> }

  for (const e of bsg.edges || []) {
    if (!e) continue;
    const { source, target, type } = _edgeFields(e);
    if (!source || !target) continue;
    const sNode = nodeIdx.get(source);
    const tNode = nodeIdx.get(target);
    if (!sNode || !tNode) continue;
    const sf = sNode.file;
    const tf = tNode.file;
    if (!sf || !tf || sf === tf) continue;

    const key = `${sf}\u0000${tf}`;
    let bucket = edgeBuckets.get(key);
    if (!bucket) {
      bucket = { source: sf, target: tf, weight: 0, types: Object.create(null) };
      edgeBuckets.set(key, bucket);
    }
    bucket.weight += 1;
    const upper = (type || 'references').toUpperCase();
    bucket.types[upper] = (bucket.types[upper] || 0) + 1;
  }

  const fileEdges = [];
  for (const bucket of edgeBuckets.values()) {
    fileEdges.push({
      id: `${bucket.source}->${bucket.target}`,
      source: bucket.source,
      target: bucket.target,
      weight: bucket.weight,
      types: bucket.types,
    });
  }
  fileEdges.sort((a, b) => {
    if (a.source !== b.source) return a.source < b.source ? -1 : 1;
    if (a.target !== b.target) return a.target < b.target ? -1 : 1;
    return 0;
  });

  const result = { nodes: fileNodes, edges: fileEdges };
  _l1Cache.set(bsg, result);
  return result;
}

/**
 * Normalize a file path for fuzzy comparison: strip leading `./` or `/`,
 * replace backslashes with forward slashes, and collapse repeated slashes.
 * @param {string} p
 * @returns {string}
 */
function _normalizePath(p) {
  if (!p) return '';
  return p.replace(/^\.?\/+/, '').replace(/\\/g, '/').replace(/\/+/g, '/');
}

/**
 * Try to resolve a file path against the BSG node set using progressive
 * matching: exact → normalized → suffix.
 *
 * @param {object} bsg
 * @param {string} filePath
 * @returns {{ canonicalPath: string, matchType: 'exact'|'normalized'|'suffix'|'none' }}
 */
function _resolveFilePath(bsg, filePath) {
  const idx = _nodesByFile(bsg);

  // 1. Exact match via index
  if (idx && Array.isArray(idx[filePath])) {
    return { canonicalPath: filePath, matchType: 'exact' };
  }

  // 2. Exact match via scan
  for (const n of bsg.nodes || []) {
    if (n && n.file === filePath) return { canonicalPath: filePath, matchType: 'exact' };
  }

  // 3. Normalized match
  const normalized = _normalizePath(filePath);
  if (idx) {
    for (const file of Object.keys(idx)) {
      if (_normalizePath(file) === normalized) return { canonicalPath: file, matchType: 'normalized' };
    }
  }
  for (const n of bsg.nodes || []) {
    if (n && n.file && _normalizePath(n.file) === normalized) {
      return { canonicalPath: n.file, matchType: 'normalized' };
    }
  }

  // 4. Suffix match (target ends with candidate or vice versa)
  const allFiles = idx ? Object.keys(idx) : [];
  if (!allFiles.length) {
    const seen = new Set();
    for (const n of bsg.nodes || []) {
      if (n && n.file && !seen.has(n.file)) { seen.add(n.file); allFiles.push(n.file); }
    }
  }
  for (const file of allFiles) {
    const nf = _normalizePath(file);
    if (nf.endsWith(normalized) || normalized.endsWith(nf)) {
      return { canonicalPath: file, matchType: 'suffix' };
    }
  }

  return { canonicalPath: filePath, matchType: 'none' };
}

/**
 * Build the Level 2 intra-file graph for a single file.
 *
 * Uses progressive fuzzy matching when an exact path match fails:
 * exact → normalized (strip `./`, `\` → `/`) → suffix match.
 *
 * @param {object} bsg
 * @param {string} filePath - relative file path matching `node.file`.
 * @returns {{nodes: object[], edges: object[], file: string, matchType: string}}
 */
export function buildFileSubgraph(bsg, filePath) {
  if (!bsg || !filePath) return { nodes: [], edges: [], file: filePath || '', matchType: 'none' };

  const { canonicalPath, matchType } = _resolveFilePath(bsg, filePath);

  if (matchType === 'none') {
    return { nodes: [], edges: [], file: filePath, matchType };
  }

  // Use index when available; otherwise scan.
  const idx = _nodesByFile(bsg);
  let nodeIds;
  if (idx && Array.isArray(idx[canonicalPath])) {
    nodeIds = new Set(idx[canonicalPath]);
  } else {
    nodeIds = new Set();
    for (const n of bsg.nodes || []) {
      if (n && n.file === canonicalPath) nodeIds.add(n.id);
    }
  }

  const nodeIdx = _nodeIndex(bsg);
  const nodes = [];
  for (const id of nodeIds) {
    const n = nodeIdx.get(id);
    if (n) nodes.push(n);
  }

  const edges = [];
  for (const e of bsg.edges || []) {
    if (!e) continue;
    const { source, target } = _edgeFields(e);
    if (nodeIds.has(source) && nodeIds.has(target)) edges.push(e);
  }

  return { nodes, edges, file: canonicalPath, matchType };
}

/**
 * Get all unique file paths present in the BSG.
 * @param {object} bsg
 * @returns {string[]}
 */
export function listBsgFiles(bsg) {
  if (!bsg) return [];
  const idx = _nodesByFile(bsg);
  if (idx) return Object.keys(idx);
  const seen = new Set();
  for (const n of bsg.nodes || []) {
    if (n && n.file) seen.add(n.file);
  }
  return [...seen];
}

/**
 * Build the Level 3 neighborhood for a single node.
 *
 * Includes the center node and every direct neighbor reachable via inbound
 * or outbound edges. Uses `indexes.inbound_edges` / `outbound_edges` when
 * available, with a brute-scan fallback.
 *
 * @param {object} bsg
 * @param {string} nodeId
 * @returns {{nodes: object[], edges: object[], center: string}}
 */
export function buildNeighborhood(bsg, nodeId) {
  if (!bsg || !nodeId) return { nodes: [], edges: [], center: nodeId || '' };

  const nodeIdx = _nodeIndex(bsg);
  const center = nodeIdx.get(nodeId);
  if (!center) return { nodes: [], edges: [], center: nodeId };

  const inboundIdx = _inboundEdges(bsg);
  const outboundIdx = _outboundEdges(bsg);

  const nodeIds = new Set([nodeId]);
  const edges = [];
  const edgeIdsSeen = new Set();

  const addEdge = (e) => {
    if (!e) return;
    const { source, target, id } = _edgeFields(e);
    if (!source || !target) return;
    if (edgeIdsSeen.has(id)) return;
    edgeIdsSeen.add(id);
    edges.push(e);
    if (source !== nodeId) nodeIds.add(source);
    if (target !== nodeId) nodeIds.add(target);
  };

  if (inboundIdx && outboundIdx) {
    const edgeIdx = _edgeIndex(bsg);
    const relevantIds = new Set([
      ...(Array.isArray(inboundIdx[nodeId]) ? inboundIdx[nodeId] : []),
      ...(Array.isArray(outboundIdx[nodeId]) ? outboundIdx[nodeId] : []),
    ]);
    for (const eid of relevantIds) {
      const e = edgeIdx.get(eid);
      if (e) addEdge(e);
    }
  } else {
    // Fallback: scan all edges
    for (const e of bsg.edges || []) {
      if (!e) continue;
      const { source, target } = _edgeFields(e);
      if (source === nodeId || target === nodeId) addEdge(e);
    }
  }

  const nodes = [];
  for (const id of nodeIds) {
    const n = nodeIdx.get(id);
    if (n) nodes.push(n);
  }

  return { nodes, edges, center: nodeId };
}

/**
 * Clear cached projections for a given bsg payload. Call this when you have
 * mutated `bsg.nodes` / `bsg.edges` in place; otherwise the WeakMap entry
 * is collected automatically when the bsg payload is released.
 *
 * @param {object} bsg
 */
export function invalidateProjections(bsg) {
  if (!bsg) return;
  _l1Cache.delete(bsg);
  try {
    delete bsg.__nodeIndex;
    delete bsg.__edgeIndex;
  } catch (_) {
    // Properties were defined non-configurable in older paths; ignore.
  }
}
