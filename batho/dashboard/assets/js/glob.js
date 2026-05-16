/**
 * Glob pattern matching for file path filtering.
 *
 * Supports:
 *   `*`     — matches any sequence of characters except /
 *   `**`    — matches any sequence including /
 *   `?`     — matches exactly one character except /
 *   `{a,b}` — matches a or b (comma-separated alternatives)
 *
 * All matching is case-insensitive on the path segment level.
 */

/**
 * Convert a glob pattern to a RegExp.
 */
function globToRegex(pattern) {
  let i = 0;
  const len = pattern.length;
  let result = '^';

  while (i < len) {
    const ch = pattern[i];

    if (ch === '*') {
      // Peek ahead for **
      if (i + 1 < len && pattern[i + 1] === '*') {
        // ** matches any path including separators
        result += '.*';
        i += 2;
        // Skip trailing /
        if (i < len && pattern[i] === '/') i++;
      } else {
        // * matches any characters except /
        result += '[^/]*';
        i++;
      }
    } else if (ch === '?') {
      result += '[^/]';
      i++;
    } else if (ch === '{') {
      // Find closing brace
      const closeIdx = pattern.indexOf('}', i);
      if (closeIdx === -1) {
        result += '\\{';
        i++;
      } else {
        const inner = pattern.slice(i + 1, closeIdx);
        const alternatives = inner.split(',').map(escapeRegex).join('|');
        result += `(?:${alternatives})`;
        i = closeIdx + 1;
      }
    } else if (ch === '[') {
      // Pass through character classes
      const closeIdx = pattern.indexOf(']', i);
      if (closeIdx === -1) {
        result += '\\[';
        i++;
      } else {
        result += pattern.slice(i, closeIdx + 1);
        i = closeIdx + 1;
      }
    } else {
      result += escapeRegex(ch);
      i++;
    }
  }

  result += '$';
  return new RegExp(result, 'i');
}

function escapeRegex(ch) {
  if ('.+^$|()[]{}\\'.includes(ch)) return '\\' + ch;
  return ch;
}

/**
 * Test whether path matches pattern.
 */
export function matchGlob(pattern, path) {
  if (!pattern || pattern === '*' || pattern === '**') return true;
  const re = globToRegex(pattern);
  return re.test(path);
}

/**
 * Filter an array of items by a glob pattern applied to a path field.
 */
export function filterByGlob(items, pattern, pathField) {
  if (!pattern || pattern === '*' || pattern === '**') return items;
  const accessor = typeof pathField === 'function' ? pathField : (item) => item[pathField];
  const re = globToRegex(pattern);
  return items.filter((item) => re.test(accessor(item)));
}
