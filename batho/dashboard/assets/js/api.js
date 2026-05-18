/**
 * API client for the Batho MCP control plane.
 */

const API_BASE = '/api/v1';

async function request(method, path, body = null) {
  const options = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) options.body = JSON.stringify(body);

  const response = await fetch(`${API_BASE}${path}`, options);
  const json = await response.json();

  if (!json.ok) {
    const error = new Error(json.error?.message || 'API error');
    error.code = json.error?.code;
    error.detail = json.error?.detail;
    throw error;
  }

  return json.data;
}

export const api = {
  // Config
  getConfig: () => request('GET', '/config'),
  putConfig: (config) => request('PUT', '/config', config),

  // Server config
  getServerConfig: () => request('GET', '/config/server'),
  patchServerConfig: (patch) => request('PATCH', '/config/server', patch),

  // Residency config
  getResidencyConfig: () => request('GET', '/config/residency'),
  patchResidencyConfig: (patch) => request('PATCH', '/config/residency', patch),

  // Concurrency config
  getConcurrencyConfig: () => request('GET', '/config/concurrency'),
  patchConcurrencyConfig: (patch) => request('PATCH', '/config/concurrency', patch),

  // Discovery config
  getDiscoveryConfig: () => request('GET', '/config/discovery'),
  patchDiscoveryConfig: (patch) => request('PATCH', '/config/discovery', patch),

  // Workspaces
  listWorkspaces: () => request('GET', '/workspaces'),
  getWorkspace: (id) => request('GET', `/workspaces/${id}`),
  createWorkspace: (workspace) => request('POST', '/workspaces', workspace),
  updateWorkspace: (id, patch) => request('PATCH', `/workspaces/${id}`, patch),
  deleteWorkspace: (id) => request('DELETE', `/workspaces/${id}`),

  // Workspace actions
  mountWorkspace: (id) => request('POST', `/workspaces/${id}/mount`),
  unmountWorkspace: (id) => request('POST', `/workspaces/${id}/unmount`),
  refreshWorkspace: (id) => request('POST', `/workspaces/${id}/refresh`),
  reindexHintWorkspace: (id) => request('POST', `/workspaces/${id}/reindex-hint`),

  // Agent snippets
  getAgentSnippet: (agent) => request('GET', `/agents/snippets/${agent}`),

  // Admin
  adminDiscover: () => request('POST', '/admin/discover'),

  // FS browse
  browseDirectory: (path) => request('GET', `/fs/browse?at=${encodeURIComponent(path)}`),

  // Health
  healthz: () => request('GET', '/healthz'),
  readyz: () => request('GET', '/readyz'),
  metrics: () => request('GET', '/metrics'),
};

export default api;
