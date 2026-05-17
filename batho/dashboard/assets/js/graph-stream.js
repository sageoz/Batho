/**
 * Streaming JSON parser for large graph files.
 * Uses a bracket-depth state machine to yield batches of entities/relationships
 * from a streamed JSON response without holding the full parse in memory.
 */

const BATCH_SIZE = 500;

/**
 * Stream-parse graph JSON and invoke progress callbacks with batches.
 * Falls back to standard JSON.parse on any error.
 *
 * @param {string} url - The bridge URL to fetch
 * @param {function} onProgress - Called with {entities, relationships, percent}
 * @returns {Promise<{entities: Array, relationships: Array}>}
 */
export async function streamParseGraph(url, onProgress) {
  let response;
  try {
    response = await fetch(url);
  } catch (_) {
    throw new Error('Network failure fetching graph data');
  }

  if (!response.ok) throw new Error(`HTTP ${response.status} fetching graph data`);

  const contentType = response.headers.get('content-type') || '';
  const contentLength = parseInt(response.headers.get('content-length') || '0', 10);

  if (!response.body || !response.body.getReader || contentLength < 50000) {
    return fallbackParse(response, onProgress);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let loaded = 0;

  const state = {
    entities: [],
    relationships: [],
    currentArray: null,
    depth: 0,
    arrayDepth: -1,
    inString: false,
    escape: false,
    braceDepth: 0,
    bracketDepth: 0,
    objectStart: -1,
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    loaded += value.length;
    buffer += decoder.decode(value, { stream: true });

    try {
      processChunk(buffer, state, onProgress, contentLength, loaded);
      buffer = '';
    } catch (_) {
      return fallbackParse(response, onProgress);
    }
  }

  if (state.entities.length === 0 && state.relationships.length === 0) {
    return fallbackParse(response, onProgress);
  }

  if (onProgress) {
    onProgress({
      entities: state.entities,
      relationships: state.relationships,
      percent: 100,
    });
  }

  return { entities: state.entities, relationships: state.relationships };
}

function processChunk(chunk, state, onProgress, total, loaded) {
  for (let i = 0; i < chunk.length; i++) {
    const ch = chunk[i];

    if (state.escape) {
      state.escape = false;
      continue;
    }

    if (ch === '\\' && state.inString) {
      state.escape = true;
      continue;
    }

    if (ch === '"') {
      state.inString = !state.inString;
      continue;
    }

    if (state.inString) continue;

    if (ch === '{') state.braceDepth++;
    if (ch === '}') state.braceDepth--;
    if (ch === '[') state.bracketDepth++;
    if (ch === ']') state.bracketDepth--;

    if (ch === '[' && !state.currentArray) {
      const lookback = chunk.substring(Math.max(0, i - 20), i + 1);
      if (lookback.match(/"entities"\s*:\s*\[/)) {
        state.currentArray = 'entities';
        state.arrayDepth = state.bracketDepth;
        state.objectStart = i + 1;
      } else if (lookback.match(/"relationships"\s*:\s*\[/)) {
        state.currentArray = 'relationships';
        state.arrayDepth = state.bracketDepth;
        state.objectStart = i + 1;
      }
    }

    if (state.currentArray && ch === '}' && state.braceDepth < state.arrayDepth) {
      try {
        const objStr = chunk.substring(state.objectStart, i + 1);
        const obj = JSON.parse(objStr);
        state[state.currentArray].push(obj);
      } catch (_) { /* skip malformed object */ }
      state.objectStart = i + 1;

      if (state[state.currentArray].length % BATCH_SIZE === 0 && onProgress) {
        onProgress({
          entities: state.entities,
          relationships: state.relationships,
          percent: total > 0 ? Math.round((loaded / total) * 100) : 50,
        });
      }
    }

    if (ch === ']' && state.bracketDepth < state.arrayDepth) {
      state.currentArray = null;
      state.arrayDepth = -1;
    }
  }
}

async function fallbackParse(response, onProgress) {
  const text = await response.text();
  try {
    const data = JSON.parse(text);
    if (data && typeof data === 'object' && Object.prototype.hasOwnProperty.call(data, 'ok')) {
      if (!data.ok) {
        const message = data.error?.message || 'Missing artifact';
        throw new Error(message);
      }
      const payload = data.data || {};
      const entities = payload.entities || [];
      const relationships = payload.relationships || [];
      if (onProgress) {
        onProgress({ entities, relationships, percent: 100 });
      }
      return { entities, relationships };
    }
    const entities = data.entities || [];
    const relationships = data.relationships || [];
    if (onProgress) {
      onProgress({ entities, relationships, percent: 100 });
    }
    return { entities, relationships };
  } catch (e) {
    throw new Error(`Failed to parse graph JSON: ${e.message}`);
  }
}
