/**
 * Audit export component — triggers browser download of data as JSON or CSV.
 */

export function createAuditExportButton(data, filename, format = 'json') {
  const container = document.createElement('div');
  container.className = 'audit-export';

  const jsonBtn = document.createElement('button');
  jsonBtn.className = 'btn btn--ghost audit-export__btn';
  jsonBtn.textContent = 'Export JSON';
  jsonBtn.addEventListener('click', () => _download(data, filename, 'json'));

  const csvBtn = document.createElement('button');
  csvBtn.className = 'btn btn--ghost audit-export__btn';
  csvBtn.textContent = 'Export CSV';
  csvBtn.addEventListener('click', () => _download(data, filename, 'csv'));

  container.appendChild(jsonBtn);
  container.appendChild(csvBtn);

  return container;
}

function _download(data, filename, format) {
  let content, mime;

  if (format === 'csv') {
    content = _toCSV(data);
    mime = 'text/csv';
  } else {
    content = JSON.stringify(data, null, 2);
    mime = 'application/json';
  }

  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${filename}.${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function _toCSV(data) {
  if (Array.isArray(data)) {
    return _arrayToCSV(data);
  }
  // If data has a patches array, flatten it
  if (data && data.patches && Array.isArray(data.patches)) {
    const rows = [];
    data.patches.forEach((patch) => {
      const metrics = patch.metrics || {};
      rows.push({
        operation_id: patch.operationId || patch.operation_id || '',
        timestamp: patch.timestamp || '',
        operation_type: patch.operationType || patch.operation_type || '',
        base_snapshot_id: patch.baseSnapshotId || patch.base_snapshot_id || '',
        new_snapshot_id: patch.newSnapshotId || patch.new_snapshot_id || '',
        token_size: metrics.tokenSize || metrics.token_size || 0,
        affected_files: metrics.affectedFiles || metrics.affected_files || 0,
        elapsed_seconds: metrics.elapsedSeconds || metrics.elapsed_seconds || 0,
        added_files: metrics.addedFiles || metrics.added_files || 0,
        modified_files: metrics.modifiedFiles || metrics.modified_files || 0,
        deleted_files: metrics.deletedFiles || metrics.deleted_files || 0,
      });
    });
    return _arrayToCSV(rows);
  }
  // Fallback: serialize as single-row CSV
  const flat = _flatten(data);
  return _arrayToCSV([flat]);
}

function _arrayToCSV(arr) {
  if (!arr.length) return '';
  const keys = Object.keys(arr[0]);
  const header = keys.join(',');
  const rows = arr.map((obj) =>
    keys.map((k) => {
      const val = obj[k] ?? '';
      const str = String(val);
      return str.includes(',') || str.includes('"') || str.includes('\n')
        ? `"${str.replace(/"/g, '""')}"`
        : str;
    }).join(',')
  );
  return [header, ...rows].join('\n');
}

function _flatten(obj, prefix = '') {
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}_${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      Object.assign(out, _flatten(v, key));
    } else {
      out[key] = Array.isArray(v) ? v.length : v;
    }
  }
  return out;
}

const auditExportStyles = `
  .audit-export {
    display: flex;
    gap: var(--space-tight);
    margin-top: var(--space-gutter);
    padding-top: var(--space-gutter);
    border-top: var(--hairline);
  }
  .audit-export__btn {
    font-family: var(--font-mono);
    font-size: var(--type-terminal-size);
  }
`;

function injectStyles() {
  if (document.getElementById('audit-export-styles')) return;
  const styleEl = document.createElement('style');
  styleEl.id = 'audit-export-styles';
  styleEl.textContent = auditExportStyles;
  document.head.appendChild(styleEl);
}
injectStyles();
