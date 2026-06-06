# Batho Utilities Module Specification

The `batho/utils/` package provides cross-cutting infrastructure used throughout the Batho codebase. It is the single source of truth for logging, content hashing, file I/O, ignore-pattern filtering, memory monitoring, path security, encoding normalization, and CLI output formatting.

---

## 1. File Structure

| File | Public Surface | Purpose |
|------|---------------|---------|
| `utils/__init__.py` | `__all__` re-exports | Package public API aggregation |
| `utils/logging.py` | `get_logger`, `configure_logging`, `configure_logging_from_dict`, `get_log_level` | Structured logging via structlog |
| `utils/hash.py` | `compute_bytes_hash`, `compute_string_hash`, `compute_file_hash`, `compute_file_hash_cached` | SHA-256 content and file hashing |
| `utils/file_io.py` | `read_file_bytes`, `read_file_text`, `write_atomically` | Unified file read/write with size limits and encoding normalization |
| `utils/ignore.py` | `load_ignore_spec`, `is_ignored`, `walk_ignored_filtered`, `rglob_ignored_filtered` | Gitignore-compatible path filtering |
| `utils/memory_monitor.py` | `MemoryMonitor`, `memory_monitor`, `force_garbage_collection`, `get_system_memory_info`, `check_memory_pressure` | Runtime memory monitoring |
| `utils/path_sanitizer.py` | `sanitize_path`, `safe_join`, `sanitize_diff_path`, `is_safe_filename`, `validate_path_list` | Path traversal prevention |
| `utils/encoding.py` | `decode_bytes_with_fallback`, `normalize_to_utf8` | Multi-encoding detection and normalization |
| `utils/cli_output.py` | `CLIOutput` | Terminal output with color, quiet mode, and progress tracking |

---

## 2. `utils/logging.py` — Structured Logging

**Import:** `from batho.utils.logging import get_logger, configure_logging, configure_logging_from_dict`

This module is the **single source of truth** for all Batho logging. It wraps [structlog](https://www.structlog.org/) to provide structured, context-bindable log entries with automatic TTY/JSON rendering selection.

### 2.1 `get_logger()`

```python
def get_logger(name: str | None = None, **context: Any) -> BindableLogger:
```

Returns a structured logger with optional bound context fields. Loggers are created lazily so that import-time module-level logger instances do not lock in structlog defaults before `configure_logging()` runs in CLI entrypoints.

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str \| None` | Module name (typically `__name__`). If `None`, structlog infers caller info. |
| `**context` | `Any` | Key/value pairs bound to every log entry emitted by this logger instance (e.g., `component="orchestrator.gc"`). |

**Usage pattern (module-level):**
```python
# At module top-level — safe because get_logger() is lazy
LOGGER = get_logger(__name__, component="orchestrator.gc")

# Later, in a function body:
LOGGER.info("gc_complete", deleted=5, generation=7)
```

**Bound context in log entries (JSON mode):**
```json
{
  "event": "gc_complete",
  "component": "orchestrator.gc",
  "logger": "batho.orchestrator.gc",
  "level": "info",
  "timestamp": "2025-01-15T10:23:45.123456Z",
  "deleted": 5,
  "generation": 7
}
```

---

### 2.2 `configure_logging()`

```python
def configure_logging(
    level: int | str | dict[str, Any] = logging.INFO,
    json_format: bool | None = None,
    quiet: bool = False,
    file: str | None = None,
    fmt: str = "%(message)s",
) -> None:
```

Configures structlog for the entire process. Called once at CLI entrypoint startup.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level` | `int \| str \| dict` | `logging.INFO` | Log level, level name string, or config dict (see below) |
| `json_format` | `bool \| None` | `None` | Force JSON (`True`), force console (`False`), or auto-detect (`None`) |
| `quiet` | `bool` | `False` | If `True`, suppress all output below `ERROR` level |
| `file` | `str \| None` | `None` | Optional file path to write logs to (parent dirs auto-created) |
| `fmt` | `str` | `"%(message)s"` | stdlib log format string |

**Renderer selection:**
- `json_format=None` (default): JSON if `stderr` is not a TTY; console with colors if TTY.
- `json_format=True`: Always JSON (`structlog.processors.JSONRenderer`).
- `json_format=False`: Always console (`structlog.dev.ConsoleRenderer(colors=True)`).

**Structlog processor chain (in order):**

| Processor | Effect |
|-----------|--------|
| `filter_by_level` | Drop events below effective log level |
| `add_logger_name` | Add `logger` field from `name` |
| `add_log_level` | Add `level` field |
| `PositionalArgumentsFormatter` | Format positional `%s`-style arguments |
| `TimeStamper(fmt="iso")` | Add ISO 8601 `timestamp` field |
| `StackInfoRenderer` | Format stack info if present |
| `format_exc_info` | Format exception info if present |
| `UnicodeDecoder` | Decode bytes in log values |
| `JSONRenderer` or `ConsoleRenderer` | Final serialization |

**Log output routing:**
- All log output goes to `stderr` (keeps `stdout` clean for user-facing output).
- A file handler is added to `root_logger` when `file` is specified.

**Dict-style configuration (for use with `get_config_cached()` result):**
```python
configure_logging({
    "level": "DEBUG",
    "json_format": True,
    "quiet": False,
    "file": "/tmp/batho.log",
    "format": "%(message)s",
})
```

When `level` is a `dict`, all other parameters are read from the dict's keys.

---

### 2.3 `configure_logging_from_dict()`

```python
def configure_logging_from_dict(config: dict[str, Any]) -> None:
```

Thin wrapper around `configure_logging()` for use with a config dict returned by `get_config_cached()`. Accepts the same keys as the dict-mode of `configure_logging()`.

---

### 2.4 `get_log_level()`

```python
def get_log_level(level_name: str = "INFO") -> int:
```

Converts a log level name string to its Python `logging` integer constant. Uses `getattr(logging, level_name.upper(), logging.INFO)` — unknown names default to `INFO`.

| Input | Output |
|-------|--------|
| `"DEBUG"` | `10` |
| `"INFO"` | `20` |
| `"WARNING"` | `30` |
| `"ERROR"` | `40` |
| `"CRITICAL"` | `50` |
| `"UNKNOWN"` | `20` (fallback to INFO) |

---

## 3. `utils/hash.py` — Content Hashing

**Import:** `from batho.utils.hash import compute_bytes_hash, compute_file_hash, compute_file_hash_cached`

All hash functions use **SHA-256** for consistency. The module also contains an internal binary detection implementation used by `file_io.py`.

### 3.1 `compute_bytes_hash()`

```python
def compute_bytes_hash(content: bytes, truncate: int | None = None) -> str:
```

Computes the SHA-256 hex digest of a bytes object.

| Parameter | Type | Description |
|-----------|------|-------------|
| `content` | `bytes` | Binary content to hash |
| `truncate` | `int \| None` | If provided, truncate the hex digest to this many characters |

**Returns:** Full 64-character hex digest, or a truncated prefix if `truncate` is set.

```python
compute_bytes_hash(b"hello world")
# → "b94d27b9934d3e08a52e52d7..."  (64 chars)

compute_bytes_hash(b"hello world", truncate=8)
# → "b94d27b9"
```

---

### 3.2 `compute_string_hash()`

```python
def compute_string_hash(content: str, encoding: str = "utf-8", truncate: int | None = None) -> str:
```

Convenience wrapper — encodes the string then calls `compute_bytes_hash()`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `content` | `str` | — | String content to hash |
| `encoding` | `str` | `"utf-8"` | Character encoding used for `str.encode()` |
| `truncate` | `int \| None` | `None` | Optional digest truncation |

---

### 3.3 `compute_file_hash()`

```python
def compute_file_hash(filepath: Path | str, chunk_size: int = 8192) -> str | None:
```

Computes the SHA-256 hash of a file using chunked reading for memory efficiency.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | `Path \| str` | — | Path to the file |
| `chunk_size` | `int` | `8192` | Read chunk size in bytes (8 KB default) |

**Returns:** SHA-256 hex digest string, or `None` if the file cannot be read (`IOError` / `OSError`).

Files are always read in binary mode (`"rb"`). No encoding normalization is applied.

---

### 3.4 `compute_file_hash_cached()`

```python
def compute_file_hash_cached(filepath: str, mtime: float) -> str | None:
```

Cached version of `compute_file_hash()` backed by `functools.lru_cache(maxsize=1024)`. The cache key is a 5-tuple of `(resolved_filepath, mtime, size, mtime_ns, inode)`, ensuring the cache is invalidated on any file modification, even within the same second.

| Parameter | Type | Description |
|-----------|------|-------------|
| `filepath` | `str` | File path (string, not `Path`, for cache key compatibility) |
| `mtime` | `float` | File modification time (from caller; refreshed internally via `stat()`) |

**Cache invalidation:** Before returning from cache, verifies the file still exists via `path.is_file()`. Returns `None` for deleted files rather than stale cached results.

> [!NOTE]
> The `filepath` parameter must be a `str` (not `Path`) because `lru_cache` keys must be hashable and `Path` objects have higher overhead in cache key comparisons.

### 3.5 Binary Detection (Internal)

`hash.py` contains an internal `_is_binary()` function (also used by `file_io.py`) that detects binary files using a layered strategy:

| Check | Detail |
|-------|--------|
| Magic bytes | Matches known binary format signatures (PNG, JPEG, PDF, ZIP, GZIP, etc.) against the first 16 bytes |
| Null-byte ratio | Returns `True` if null bytes exceed 1% of the first 4 KB |
| Shannon entropy | Returns `True` if entropy of first 4 KB exceeds 7.30 bits/byte |

---

## 4. `utils/file_io.py` — Unified File I/O

**Import:** `from batho.utils.file_io import read_file_bytes, read_file_text, write_atomically`

Provides consistent, safe file operations with size limiting, binary detection, encoding normalization, and atomic writes.

### 4.1 `read_file_bytes()`

```python
def read_file_bytes(
    filepath: str | Path,
    max_size_kb: int | None = None,
    normalize_encoding: bool = True,
    detect_binary: bool = False,
) -> bytes | None:
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | `str \| Path` | — | Path to read |
| `max_size_kb` | `int \| None` | Config default | Maximum file size in KB; reads config `indexer.max_file_size_kb` if `None` |
| `normalize_encoding` | `bool` | `True` | If `True`, normalizes raw bytes to valid UTF-8 via `normalize_to_utf8()` |
| `detect_binary` | `bool` | `False` | If `True`, returns `None` for binary files (detected by `_is_binary()`) |

**Returns `None` when:**
- File size exceeds `max_size_kb * 1024` bytes.
- File cannot be opened (`OSError`).
- `detect_binary=True` and the file is detected as binary.

**Encoding normalization chain** (when `normalize_encoding=True`):
```
raw bytes
  → decode_bytes_with_fallback()   # try utf-8 → ascii → latin-1 → cp1252
  → re-encode as UTF-8
  → return normalized bytes
```

---

### 4.2 `read_file_text()`

```python
def read_file_text(
    filepath: str | Path,
    max_size_kb: int | None = None,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> str | None:
```

Reads a file as a text string. Internally calls `read_file_bytes()` with `detect_binary=True`, then decodes:

1. Attempts `bytes.decode(encoding, errors="strict")`.
2. On `UnicodeDecodeError`, falls back to `decode_bytes_with_fallback()` using the configured `errors` strategy.

Returns `None` if the file is binary or cannot be read.

---

### 4.3 `write_atomically()`

```python
def write_atomically(
    path: str | Path,
    content: str | bytes | dict,
    *,
    is_json: bool = False,
    encoding: str = "utf-8",
    indent: int | None = 2,
    ensure_parent: bool = True,
) -> bool:
```

Writes content to a file atomically using a temp-file-then-rename strategy to prevent partial writes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str \| Path` | — | Target file path |
| `content` | `str \| bytes \| dict` | — | Content to write |
| `is_json` | `bool` | `False` | Serialize `content` as JSON if `True` |
| `encoding` | `str` | `"utf-8"` | Text encoding for string content |
| `indent` | `int \| None` | `2` | JSON indentation level |
| `ensure_parent` | `bool` | `True` | Create parent directories automatically |

**Atomic write sequence:**
```
1. Create temp file in path.parent via tempfile.mkstemp()
2. Write content to temp file
3. Preserve original file permissions (or apply umask-derived mode for new files)
4. tmp_path.replace(path)  ← atomic rename (POSIX guarantee)
5. Clean up temp file on any error
```

**Returns:** `True` on success, `False` on any error (`OSError`, `JSONDecodeError`, `TypeError`). Errors are logged at `WARNING` level; no exceptions are raised.

---

## 5. `utils/ignore.py` — Path Filtering

**Import:** `from batho.utils.ignore import load_ignore_spec, is_ignored, walk_ignored_filtered`

Provides gitignore-compatible path filtering using the [pathspec](https://pypi.org/project/pathspec/) library with a fallback to `fnmatch`.

### 5.1 `load_ignore_spec()`

```python
def load_ignore_spec(
    root: Path,
    extra_patterns: list[str] | None = None,
    ignore_files: list[str] | None = None,
    default_patterns_file: Path | str | None = None,
) -> Any:
```

Builds a combined ignore specification from multiple sources, in priority order:

1. **Default patterns:** Loaded from `batho/core/config/default-ignore-patterns.yaml` (common patterns for `.venv`, `node_modules`, `__pycache__`, etc.).
2. **Extra patterns:** Caller-supplied additional patterns.
3. **Ignore files:** Contents of `.gitignore` (or custom `ignore_files` list) at the repo root.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root` | `Path` | — | Workspace root path |
| `extra_patterns` | `list[str] \| None` | `None` | Additional gitignore-style patterns |
| `ignore_files` | `list[str] \| None` | `[".gitignore"]` | List of ignore filenames to load relative to `root` |
| `default_patterns_file` | `Path \| str \| None` | `None` | Custom default patterns YAML path; uses built-in if `None` |

**Returns:** A `pathspec.PathSpec` object (preferred), or a plain `list[str]` if `pathspec` is not installed.

> [!NOTE]
> `.bathoignore` support was removed in v2.0. Only `.gitignore` is loaded by default.

---

### 5.2 `is_ignored()`

```python
def is_ignored(file_path: Path, root: Path, spec: Any) -> bool:
```

Tests whether `file_path` matches the given ignore spec.

| Parameter | Type | Description |
|-----------|------|-------------|
| `file_path` | `Path` | Path to test (absolute or relative) |
| `root` | `Path` | Workspace root for computing the relative path |
| `spec` | `Any` | Spec from `load_ignore_spec()` |

**Matching strategy:**
- **pathspec mode:** Converts `file_path` to POSIX relative path, calls `spec.match_file(rel)`.
- **fnmatch fallback:** Checks each pattern against path parts and the full relative path string (with and without trailing slash).

Returns `False` for paths not relative to `root` and already-absolute paths outside the root.

---

### 5.3 `walk_ignored_filtered()`

```python
def walk_ignored_filtered(
    root: Path,
    spec: Any | None = None,
    skip_hidden: bool = True,
) -> Iterator[tuple[Path, list[str], list[str]]]:
```

Drop-in replacement for `os.walk()` that prunes ignored directories and files in-place.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root` | `Path` | — | Root directory to walk |
| `spec` | `Any \| None` | `None` | Pre-loaded ignore spec; auto-loaded if `None` |
| `skip_hidden` | `bool` | `True` | Also skip hidden files/directories (names starting with `.`) |

**Yields:** `(current_path: Path, dirnames: list[str], filenames: list[str])` — filtered tuples equivalent to `os.walk()` output.

**Key behaviour:** `dirnames` is modified in-place (`dirnames[:] = [...]`) to prevent `os.walk()` from descending into ignored subdirectories.

---

### 5.4 `rglob_ignored_filtered()`

```python
def rglob_ignored_filtered(
    root: Path,
    pattern: str,
    spec: Any | None = None,
    skip_hidden: bool = True,
) -> Iterator[Path]:
```

Glob-based alternative that filters out ignored paths from `Path.rglob()` results.

---

### 5.5 Helper: `should_ignore_path()`

```python
def should_ignore_path(path, root, spec=None, include_hidden=True) -> bool:
```

Convenience function combining hidden-file check and `is_ignored()`. Loads the ignore spec automatically if not provided. Used internally by `walk_ignored_filtered()`.

---

## 6. `utils/memory_monitor.py` — Memory Monitoring

**Import:** `from batho.utils.memory_monitor import MemoryMonitor, memory_monitor`

Provides runtime memory tracking for long-running indexing operations. Depends on [psutil](https://pypi.org/project/psutil/) (optional; degrades gracefully if unavailable).

### 6.1 `MemoryStats` Dataclass

```python
@dataclass
class MemoryStats:
    rss_mb: float       # Resident Set Size in MB
    vms_mb: float       # Virtual Memory Size in MB
    percent: float      # Process memory usage as % of total system RAM
    available_mb: float # System available memory in MB
    gc_objects: int     # Objects tracked by Python garbage collector
```

Returns `MemoryStats(0, 0, 0, 0, 0)` when psutil is unavailable.

---

### 6.2 `MemoryMonitor` Class

```python
class MemoryMonitor:
    def __init__(
        self,
        warning_threshold_mb: float = 500.0,
        critical_threshold_mb: float = 1000.0,
    ): ...
```

| Threshold | Default | Behaviour |
|-----------|---------|-----------|
| `warning_threshold_mb` | 500 MB | Logs `WARNING` and returns warning message |
| `critical_threshold_mb` | 1000 MB | Logs `ERROR` and returns critical message |

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `get_memory_stats()` | `MemoryStats` | Returns current memory stats (cached for 500 ms to reduce psutil overhead) |
| `check_memory_usage(operation)` | `str \| None` | Returns a warning/critical message if thresholds exceeded, `None` otherwise |
| `log_memory_stats(operation)` | `None` | Logs current stats at INFO level with operation context |

**Stats caching:** Results are cached for 500 ms (`_cache_ttl = 0.5`). Repeated calls within the cache window return the cached `MemoryStats` without querying psutil.

**GC object counting strategy:**
1. Try `gc.get_stats()` → sum `count` fields (efficient).
2. Fall back to `sum(gc.get_count())` if step 1 fails.
3. Fall back to `0` with a DEBUG log if both fail.

> [!NOTE]
> `gc.get_objects()` is intentionally avoided as it is extremely expensive and can cause memory pressure during large indexing operations.

---

### 6.3 `memory_monitor` Context Manager

```python
@contextmanager
def memory_monitor(
    operation: str,
    warning_threshold_mb: float = 500.0,
    critical_threshold_mb: float = 1000.0,
) -> Iterator[MemoryMonitor]:
```

Wraps a block of code with memory monitoring. Logs initial and final memory states, computes RSS delta, and suggests GC if memory grew by more than 100 MB.

**Usage:**
```python
with memory_monitor("indexing", warning_threshold_mb=300.0) as monitor:
    # Memory-intensive indexing work
    result = index_all_files(root)
    # Optionally inspect monitor.get_memory_stats() mid-operation
```

**Log events emitted:**
| Event | Level | Timing |
|-------|-------|--------|
| `memory_monitor_start` | INFO | Before operation |
| `memory_monitor_start_warning` | WARNING | If already over threshold at start |
| `memory_monitor_end` | INFO | After operation |
| `memory_monitor_end_warning` | WARNING | If over threshold at end |
| `suggest_gc` | INFO | If RSS increased > 100 MB |

---

### 6.4 Utility Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `force_garbage_collection()` | `dict` | Calls `gc.collect()`, returns `{collected_objects, objects_before, objects_after, objects_freed, collections_performed}` |
| `get_system_memory_info()` | `dict` | Returns system-wide `{total_mb, available_mb, used_mb, percent, swap_total_mb, swap_used_mb, swap_percent}` or `{}` if psutil unavailable |
| `check_memory_pressure(threshold_percent)` | `bool` | `True` if system RAM usage exceeds `threshold_percent` (default 90%) |

---

## 7. `utils/path_sanitizer.py` — Path Security

**Import:** `from batho.utils.path_sanitizer import sanitize_path, safe_join, sanitize_diff_path`

Prevents path traversal and injection attacks when handling user-supplied or externally-sourced paths.

### 7.1 `PathSecurityError`

```python
class PathSecurityError(Exception): ...
```

Raised by all path sanitization functions when an unsafe path is detected.

---

### 7.2 `sanitize_path()`

```python
def sanitize_path(
    path: str | Path,
    base_dir: str | Path | None = None,
    allow_absolute: bool = False,
) -> Path:
```

Sanitizes a path and optionally constrains it within a base directory.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str \| Path` | — | Path to sanitize |
| `base_dir` | `str \| Path \| None` | `None` | If provided, relative paths are resolved against this base and the result must remain inside it |
| `allow_absolute` | `bool` | `False` | If `False`, absolute paths are rejected when `base_dir` is provided |

**Returns:** Resolved absolute `Path` object.

**Raises:** `PathSecurityError` if the resolved path escapes `base_dir` (path traversal via `..` etc.) or if an absolute path is provided when `allow_absolute=False`.

---

### 7.3 `safe_join()`

```python
def safe_join(base_dir: str | Path, *paths: str | Path) -> Path:
```

Joins path components against a base directory, ensuring the result stays within the base. Equivalent to `os.path.join()` but with path traversal protection.

**Raises:** `PathSecurityError` if the joined path resolves outside `base_dir`.

---

### 7.4 `sanitize_diff_path()`

```python
def sanitize_diff_path(diff_path: str, base_dir: str | Path) -> Path:
```

Sanitizes a path extracted from `git diff` output. Handles git-specific concerns:

1. Strips `"a/"` and `"b/"` prefixes.
2. Rejects `/dev/null` (represents deleted files in diffs).
3. Rejects absolute paths in diff output (always should be relative).
4. Checks for null byte (`\0`) injection.
5. Calls `sanitize_path()` for path traversal validation.

**Raises:** `PathSecurityError` for any unsafe condition.

---

### 7.5 `is_safe_filename()`

```python
def is_safe_filename(filename: str) -> bool:
```

Validates that a filename is safe for use on all platforms. Returns `False` if the filename contains:

| Check | Detail |
|-------|--------|
| Null bytes | `\0` character |
| Path separators | `/`, `\`, or `..` |
| Windows reserved names | `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9` |
| Dangerous characters | `< > : " | ? *` |
| URL-encoded bypasses | Decodes `%2F` etc. via `urllib.parse.unquote` before checking |
| Unicode bypasses | Normalizes to NFKC (resolves U+FF0F fullwidth slash, U+FF3C fullwidth backslash) |

---

### 7.6 `validate_path_list()`

```python
def validate_path_list(paths: list[str | Path], base_dir: str | Path) -> list[Path]:
```

Validates and sanitizes a list of paths in bulk. Calls `sanitize_path()` for each path. Raises `PathSecurityError` on the first unsafe path encountered.

---

## 8. `utils/encoding.py` — Encoding Detection and Normalization

**Import:** `from batho.utils.encoding import decode_bytes_with_fallback, normalize_to_utf8`

Provides robust multi-encoding decoding with deterministic fallback chains.

### 8.1 Constants

```python
DEFAULT_ENCODING = "utf-8"
FALLBACK_ENCODINGS = ["utf-8", "ascii", "latin-1", "cp1252"]
```

### 8.2 `decode_bytes_with_fallback()`

```python
def decode_bytes_with_fallback(
    data: bytes,
    encodings: list[str] | None = None,
    errors: str = "replace",
) -> str:
```

Attempts to decode bytes using each encoding in `encodings` with `errors="strict"`. Falls back to `latin-1` (which maps all 256 byte values to Unicode without error) if all encodings fail.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data` | `bytes` | — | Binary data to decode |
| `encodings` | `list[str] \| None` | `FALLBACK_ENCODINGS` | Ordered list of encodings to try |
| `errors` | `str` | `"replace"` | Error handling for the final latin-1 fallback only |

**Fallback chain:**
```
utf-8 (strict) → ascii (strict) → latin-1 (strict) → cp1252 (strict)
    → latin-1 (with errors="replace")  ← guaranteed to succeed
```

---

### 8.3 `normalize_to_utf8()`

```python
def normalize_to_utf8(data: bytes, errors: str = "replace") -> bytes:
```

Normalizes any bytes object to valid UTF-8 by decoding with fallback then re-encoding as UTF-8. Used by `read_file_bytes()` when `normalize_encoding=True`.

```python
# Example: Windows-1252 encoded file → normalized UTF-8 bytes
raw = b"\x93Hello\x94"  # Windows "smart quotes"
utf8 = normalize_to_utf8(raw)
# → b"\xe2\x80\x9cHello\xe2\x80\x9d"  (proper UTF-8 curly quotes)
```

---

## 9. `utils/cli_output.py` — Terminal Output

**Import:** `from batho.utils.cli_output import CLIOutput`

Provides structured, styled CLI output with `stdout`/`stderr` separation, ANSI color support, quiet mode, and a simple progress tracker.

### 9.1 `CLIOutput` Class

```python
class CLIOutput:
    def __init__(self, quiet: bool = False, json_mode: bool = False): ...
```

| Attribute | Type | Description |
|-----------|------|-------------|
| `quiet` | `bool` | If `True`, suppress all non-error output |
| `json_mode` | `bool` | If `True`, disables ANSI color codes |

**Color support detection:** Colors are disabled when `json_mode=True`, when the `NO_COLOR` environment variable is set, or when the target stream is not a TTY.

---

### 9.2 Output Methods

| Method | Stream | Respects `quiet` | ANSI Color | Description |
|--------|--------|-----------------|------------|-------------|
| `success(message, **data)` | `stdout` | ✅ Yes | Green (32) | Success messages |
| `error(message, **data)` | `stderr` | ❌ No | Red (31) | Error messages (always shown) |
| `warning(message, **data)` | `stderr` | ✅ Yes | Yellow (33) | Warning messages |
| `info(message, **data)` | `stdout` | ✅ Yes | None | Informational output |
| `json_response(data)` | `stdout` | ✅ Yes | None | JSON-formatted dict output |

All methods accept `**data` keyword arguments that are serialized as a JSON object and appended to the message string when present.

```python
output = CLIOutput()
output.success("Build complete", files=42, duration_ms=1234)
# stdout: Build complete {"duration_ms": 1234, "files": 42}
```

---

### 9.3 `write()` — Auto-classified Output

```python
def write(self, message: str, *, stream=None, end="\n", flush=False) -> None:
```

Emits `message` to the appropriate stream based on automatic message classification:

**`classify()` rules (applied to stripped, lowercased message):**

| Prefix | Classification | Stream |
|--------|---------------|--------|
| `❌`, `error`, `fatal` | `error` | `stderr` (never quiet) |
| `⚠`, `warning` | `warning` | `stderr` |
| `✅`, `success` | `success` | `stdout` |
| *(anything else)* | `info` | `stdout` |

---

### 9.4 `progress()` Context Manager

```python
@contextmanager
def progress(self, total: int, desc: str) -> Iterator[Callable[[int], None]]:
```

Simple line-based progress tracker. Yields an `update(step=1)` callable.

```python
with output.progress(total=100, desc="Indexing files") as update:
    for file in files:
        process(file)
        update()   # increments counter by 1
```

- When `quiet=True`, yields a no-op lambda with no output.
- Automatically prints `desc: total/total` on context exit if the counter has not reached `total`.

---

## 10. Public API

The following symbols are exported from `batho.utils` (via `__init__.py`):

```python
from batho.utils import (
    # Hashing
    compute_bytes_hash,
    compute_string_hash,
    compute_file_hash,
    compute_file_hash_cached,

    # Encoding
    normalize_to_utf8,

    # CLI output
    CLIOutput,

    # Ignore filtering
    load_ignore_spec,
    is_ignored,

    # Logging
    get_logger,
    get_log_level,
    configure_logging,
    configure_logging_from_dict,
)
```

**Not in `__all__`** (must be imported directly from sub-module):

| Symbol | Import path |
|--------|------------|
| `read_file_bytes` | `batho.utils.file_io` |
| `read_file_text` | `batho.utils.file_io` |
| `write_atomically` | `batho.utils.file_io` |
| `walk_ignored_filtered` | `batho.utils.ignore` |
| `rglob_ignored_filtered` | `batho.utils.ignore` |
| `MemoryMonitor` | `batho.utils.memory_monitor` |
| `memory_monitor` | `batho.utils.memory_monitor` |
| `sanitize_path` | `batho.utils.path_sanitizer` |
| `safe_join` | `batho.utils.path_sanitizer` |
| `sanitize_diff_path` | `batho.utils.path_sanitizer` |
| `PathSecurityError` | `batho.utils.path_sanitizer` |
| `decode_bytes_with_fallback` | `batho.utils.encoding` |

---

*Generated for Batho v1.1.0*
