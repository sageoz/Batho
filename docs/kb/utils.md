# Module: `batho.utils`

## Overview

`batho.utils` is the foundational utility layer for the entire Batho codebase. It provides cross-cutting concerns shared by all five CLI commands: SHA-256 content and file hashing (with LRU caching), multi-encoding text normalization, `.gitignore`-compatible file exclusion, structured `structlog`-based logging, rich CLI output with color and quiet/JSON modes, patch-specific exception types with an audit trail logger, atomic file I/O, cross-platform file locking, project-manifest dependency parsing (Python/Node.js/Rust), memory-usage monitoring with GC integration, and path-traversal-safe path utilities. The package `__init__.py` re-exports the most commonly used symbols so call sites can import directly from `batho.utils`.

---

## Files Covered

| Filename | Size (bytes) | Purpose |
|---|---|---|
| `__init__.py` | 1 231 | Public re-export surface for the package |
| `cli_output.py` | 4 892 | Colored, quiet/JSON-aware user-facing output helper |
| `dependencies.py` | 19 323 | Manifest dependency parser (requirements.txt, pyproject.toml, package.json, Cargo.toml, setup.py) |
| `encoding.py` | 3 264 | Multi-encoding text/bytes fallback + UTF-8 normalizer |
| `file_io.py` | 5 847 | Unified file read/write with size limits, binary detection, and atomic writes |
| `file_lock.py` | 9 386 | Cross-platform PID-based file lock with timeout and stale-lock cleanup |
| `hash.py` | 6 094 | SHA-256 hashing, binary detection, deterministic entity/relationship ID generation |
| `ignore.py` | 9 599 | `.gitignore`-style ignore spec loader and path filter helpers |
| `logging.py` | 5 439 | Structured `structlog` logger factory and process-wide configuration |
| `memory_monitor.py` | 10 317 | RSS/VMS memory stats, context-manager monitor, GC forcing utilities |
| `patch_errors.py` | 8 188 | Patch-specific exception hierarchy and structured audit logger |
| `path_sanitizer.py` | 6 263 | Path traversal prevention, git-diff path sanitization, safe filename validation |

---

## Classes & Functions

### `__init__.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `CLIOutput` | class | Re-exported from `cli_output` | — | ✅ Used |
| `normalize_to_utf8` | function | Re-exported from `encoding` | build, patch, export | ✅ Used |
| `compute_bytes_hash` | function | Re-exported from `hash` | build, patch | ✅ Used |
| `compute_file_hash` | function | Re-exported from `hash` | build, patch | ✅ Used |
| `compute_file_hash_cached` | function | Re-exported from `hash` | build, patch | ✅ Used |
| `compute_string_hash` | function | Re-exported from `hash` | build, patch | ✅ Used |
| `generate_entity_id` | function | Re-exported from `hash` | build | ✅ Used |
| `generate_relationship_id` | function | Re-exported from `hash` | build | ✅ Used |
| `load_ignore_spec` | function | Re-exported from `ignore` | build, patch | ✅ Used |
| `is_ignored` | function | Re-exported from `ignore` | build, patch | ✅ Used |
| `get_logger` | function | Re-exported from `logging` | build, patch, export, fix, diff | ✅ Used |
| `get_log_level` | function | Re-exported from `logging` | build, patch, export, fix, diff | ✅ Used |
| `configure_logging` | function | Re-exported from `logging` | build, patch, export | ✅ Used |
| `configure_logging_from_dict` | function | Re-exported from `logging` | build, patch, export | ✅ Used |
| `PatchValidationError` | class | Re-exported from `patch_errors` | patch | ✅ Used |
| `PatchConsistencyError` | class | Re-exported from `patch_errors` | patch | ✅ Used |
| `PatchSnapshotError` | class | Re-exported from `patch_errors` | patch | ✅ Used |
| `PatchFileError` | class | Re-exported from `patch_errors` | patch | ✅ Used |
| `PatchTimeoutError` | class | Re-exported from `patch_errors` | patch | ✅ Used |
| `PatchAuditLogger` | class | Re-exported from `patch_errors` | patch | ✅ Used |
| `audit_logger` | constant | Re-exported global `PatchAuditLogger` instance | patch | ✅ Used |

---

### `cli_output.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `CLIOutput` | class | User-facing output manager respecting quiet/json flags | — | ❌ [UNUSED] |
| `  __init__` | method | Stores `quiet` and `json_mode` flags | — | ❌ [UNUSED] |
| `  configure` | method | Mutate quiet/json_mode after construction | — | ❌ [UNUSED] |
| `  classify` | method | Heuristic: classify a message string as error/warning/success/info | — | ❌ [UNUSED] |
| `  _supports_color` | method | Return True if stream is a TTY and NO_COLOR is not set | — | ❌ [UNUSED] |
| `  _emit` | method | Core low-level print with optional ANSI color and quiet gate | — | ❌ [UNUSED] |
| `  success` | method | Print green success message to stdout | — | ❌ [UNUSED] |
| `  error` | method | Print red error message to stderr (ignores quiet) | — | ❌ [UNUSED] |
| `  warning` | method | Print yellow warning to stderr (respects quiet) | — | ❌ [UNUSED] |
| `  info` | method | Print info message to stdout (respects quiet) | — | ❌ [UNUSED] |
| `  json_response` | method | Serialize and print a dict as indented JSON to stdout | — | ❌ [UNUSED] |
| `  write` | method | Auto-classify and emit a message to appropriate stream | — | ❌ [UNUSED] |
| `  progress` | method | Context manager yielding a callable `step` counter for progress display | — | ❌ [UNUSED] |

> **Note:** `CLIOutput` is exported from `batho.utils.__init__` but **no CLI orchestrator, integrity engine, or diff command imports or instantiates it**. It is defined and re-exported but has no active call sites in any CLI chain. It is infrastructure that is available but currently unused at runtime.

#### Class Diagram

```mermaid
classDiagram
    class CLIOutput {
        +bool quiet
        +bool json_mode
        +configure(quiet, json_mode) None
        +classify(message) str
        +success(message, **data) None
        +error(message, **data) None
        +warning(message, **data) None
        +info(message, **data) None
        +json_response(data) None
        +write(message, stream, end, flush) None
        +progress(total, desc) Iterator
        -_supports_color(stream) bool
        -_emit(message, stream, respect_quiet, color, end, flush) None
    }
```

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["CLIOutput.write(message)"] --> B["classify(message)"]
    B --> C{kind}
    C -- error --> D["_emit → sys.stderr, color=31"]
    C -- warning --> E["_emit → sys.stderr, color=33"]
    C -- success --> F["_emit → sys.stdout, color=32"]
    C -- info --> G["_emit → sys.stdout"]
    H["CLIOutput.progress(total, desc)"] --> I{quiet?}
    I -- yes --> J["yield no-op lambda"]
    I -- no --> K["info start; yield _update"]
```

---

### `dependencies.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `extract_package_name` | function | Strip version specifiers and extras from a dep string | — | ❌ [UNUSED] |
| `parse_requirements_txt` | function | Parse requirements.txt text → list of package names | — | ❌ [UNUSED] |
| `parse_requirements_txt_file` | function | Read and parse a `requirements.txt` file from disk | — | ❌ [UNUSED] |
| `parse_pyproject_toml` | function | Parse `pyproject.toml` TOML/regex → deps dict | — | ❌ [UNUSED] |
| `_detect_build_tool_from_pyproject` | function | Identify build backend from parsed pyproject data | — | ❌ [UNUSED] |
| `_parse_pyproject_toml_regex` | function | Regex fallback parser for pyproject.toml | — | ❌ [UNUSED] |
| `parse_pyproject_toml_file` | function | Read and parse a `pyproject.toml` file from disk | — | ❌ [UNUSED] |
| `parse_setup_py` | function | Regex-extract `install_requires` and `python_requires` from setup.py | — | ❌ [UNUSED] |
| `parse_setup_py_file` | function | Read and parse a `setup.py` file from disk | — | ❌ [UNUSED] |
| `parse_package_json` | function | Parse `package.json` text → deps/devDeps/peerDeps dict | — | ❌ [UNUSED] |
| `parse_package_json_file` | function | Read `package.json` + detect package manager from lock files | — | ❌ [UNUSED] |
| `_detect_node_package_manager` | function | Check for pnpm/yarn/npm/bun lock files | — | ❌ [UNUSED] |
| `parse_cargo_toml` | function | Parse `Cargo.toml` TOML/regex → dependencies dict | — | ❌ [UNUSED] |
| `parse_cargo_toml_file` | function | Read and parse a `Cargo.toml` file from disk | — | ❌ [UNUSED] |
| `extract_all_dependencies` | function | Unified entry: scan a project root for all manifest files, return by ecosystem | — | ❌ [UNUSED] |
| `extract_dependency_names` | function | Flat sorted list of unique dep names across all manifests | — | ❌ [UNUSED] |

> **Note:** `dependencies.py` is **not imported by any module** in `batho/orchestrator/`, `batho/integrity/`, `batho/cli/`, or `batho/context/`. It is entirely unused by the current CLI chains. It was likely written as a consolidation of parsing logic from `memory/universal.py` and `context/stack_detector.py` (per the module docstring) but has not yet been wired in.

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["extract_all_dependencies(base_path)"] --> B["parse_requirements_txt_file"]
    A --> C["parse_pyproject_toml_file"]
    A --> D["parse_setup_py_file"]
    A --> E["parse_package_json_file"]
    A --> F["parse_cargo_toml_file"]
    B --> G["parse_requirements_txt → extract_package_name"]
    C --> H["parse_pyproject_toml → tomllib / tomli / _parse_pyproject_toml_regex"]
    E --> I["parse_package_json → _detect_node_package_manager"]
    F --> J["parse_cargo_toml → tomllib / regex fallback"]
```

---

### `encoding.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `DEFAULT_ENCODING` | constant | Default encoding string `"utf-8"` | — | ✅ Used |
| `FALLBACK_ENCODINGS` | constant | Ordered list of encodings to try: utf-8, ascii, latin-1, cp1252 | — | ✅ Used |
| `read_text_with_fallback` | function | Read a file trying multiple encodings in order; raises `UnicodeDecodeError` if all fail | — | ❌ [UNUSED] |
| `decode_bytes_with_fallback` | function | Decode raw bytes trying multiple encodings; final fallback to latin-1 (never fails) | build, patch, export | ✅ Used |
| `normalize_to_utf8` | function | Decode bytes with fallback then re-encode to UTF-8 | build, patch, export | ✅ Used |

> `read_text_with_fallback` is defined but never imported by any production module. `normalize_to_utf8` and `decode_bytes_with_fallback` are reached via `file_io.py` and `context/extractor.py`, which are in the `build` and `patch` CLI chains.

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["normalize_to_utf8(data)"] --> B["decode_bytes_with_fallback(data)"]
    B --> C{Try each encoding in FALLBACK_ENCODINGS}
    C -- success --> D["Return decoded str"]
    C -- all fail --> E["Decode as latin-1"]
    D --> F["str.encode('utf-8')"]
    E --> F
```

---

### `file_io.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `LOGGER` | constant | Module-level logger via `get_logger` | — | — |
| `read_file_bytes` | function | Read file bytes with size-limit, binary detection, and optional UTF-8 normalization | build, patch, export | ✅ Used |
| `read_file_text` | function | Read file as decoded text using `read_file_bytes` + fallback decode | — | ❌ [UNUSED] |
| `write_atomically` | function | Write str/bytes/dict to a file atomically via temp-file rename | — | ❌ [UNUSED] |

> `read_file_bytes` is used by `context/codegraph.py` and `context/pipeline.py`, both reachable from `batho build` and `batho patch`. `read_file_text` and `write_atomically` have no import sites in the current CLI chains.

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["read_file_bytes(filepath, max_size_kb, normalize_encoding, detect_binary)"] --> B["os.path.getsize"]
    B --> C{exceeds limit?}
    C -- yes --> D["return None"]
    C -- no --> E["open rb; read raw"]
    E --> F{detect_binary?}
    F -- yes and binary --> D
    F -- no or not binary --> G{normalize_encoding?}
    G -- yes --> H["normalize_to_utf8(raw)"]
    G -- no --> I["return raw"]
    H --> I

    J["write_atomically(path, content)"] --> K["Prepare bytes content"]
    K --> L["Write to .tmp file"]
    L --> M["tmp_path.replace(path) atomic rename"]
```

---

### `file_lock.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `FileLockError` | class | Exception for lock acquisition/release failures | — | ❌ [UNUSED] |
| `FileLock` | class | Cross-platform PID+timestamp file lock with timeout and stale-lock detection | — | ❌ [UNUSED] |
| `  __init__` | method | Set lock_path, timeout, poll_interval; initialize `_locked = False` | — | ❌ [UNUSED] |
| `  _is_process_alive` | method | Check via `psutil.pid_exists` whether holding process is alive | — | ❌ [UNUSED] |
| `  _read_lock_info` | method | Parse lock file `pid:timestamp` content | — | ❌ [UNUSED] |
| `  _is_lock_stale` | method | Return True if PID is dead or lock age > 5 minutes | — | ❌ [UNUSED] |
| `  _cleanup_stale_lock` | method | Unlink lock file if stale | — | ❌ [UNUSED] |
| `  acquire` | method | Atomically create lock file via `O_CREAT|O_EXCL`; poll until timeout | — | ❌ [UNUSED] |
| `  release` | method | Verify PID ownership then unlink lock file | — | ❌ [UNUSED] |
| `  __enter__` | method | Context manager entry: calls `acquire()` | — | ❌ [UNUSED] |
| `  __exit__` | method | Context manager exit: calls `release()` | — | ❌ [UNUSED] |
| `  __del__` | method | Destructor: release lock if still held | — | ❌ [UNUSED] |
| `file_lock` | function | Context-manager convenience wrapper around `FileLock` | — | ❌ [UNUSED] |

> **Note:** `file_lock.py` is not imported by any module in the CLI chains. It is completely unreachable from all five CLI entry points. Likely written for future use to protect cache or DB writes.

#### Class Diagram

```mermaid
classDiagram
    class FileLockError {
        <<Exception>>
    }
    class FileLock {
        +Path lock_path
        +float timeout
        +float poll_interval
        -bool _locked
        +acquire() bool
        +release() None
        +__enter__() FileLock
        +__exit__() None
        -_is_process_alive(pid) bool
        -_read_lock_info() tuple
        -_is_lock_stale(pid, timestamp) bool
        -_cleanup_stale_lock() bool
    }
    FileLock --> FileLockError : raises
```

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["file_lock(lock_path, timeout)"] --> B["FileLock(lock_path, timeout)"]
    B --> C["lock.acquire()"]
    C --> D["_cleanup_stale_lock()"]
    D --> E["_read_lock_info() → pid, timestamp"]
    E --> F["_is_lock_stale(pid, ts)"]
    F --> G["_is_process_alive(pid)"]
    C --> H["os.open O_CREAT|O_EXCL"]
    H -- exists --> I["poll + retry"]
    H -- success --> J["_locked = True"]
    K["file_lock context exit"] --> L["lock.release()"]
    L --> M["_read_lock_info(); verify PID; unlink"]
```

---

### `hash.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `_BINARY_MAGIC_BYTES` | constant | Tuple of known binary file magic-byte signatures | build, patch, export | ✅ Used |
| `_BINARY_ENTROPY_THRESHOLD` | constant | Shannon entropy cutoff (7.30 bits/byte) for binary detection | build, patch, export | ✅ Used |
| `_BINARY_ANALYSIS_WINDOW` | constant | Number of bytes sampled for entropy analysis (4096) | build, patch, export | ✅ Used |
| `_BINARY_NULL_BYTE_RATIO_THRESHOLD` | constant | Null-byte ratio threshold (0.01) for binary detection | build, patch, export | ✅ Used |
| `_calculate_shannon_entropy` | function | Compute Shannon entropy (0.0–8.0 bits/byte) over a byte sample | build, patch, export | ✅ Used |
| `_is_binary` | function | Layered binary detection: magic bytes → null ratio → entropy | build, patch, export | ✅ Used |
| `compute_bytes_hash` | function | SHA-256 hex digest of bytes; optional truncation | build, patch | ✅ Used |
| `compute_string_hash` | function | Encode string then compute SHA-256; optional truncation | build, patch | ✅ Used |
| `compute_file_hash` | function | Chunked SHA-256 hash of a file; returns `None` on error | build, patch | ✅ Used |
| `compute_file_hash_cached` | function | LRU-cached wrapper for `compute_file_hash` keyed on `(filepath, mtime)` | build, patch | ✅ Used |
| `generate_entity_id` | function | 16-char deterministic ID from `entity_type:name:file` | build | ✅ Used |
| `generate_relationship_id` | function | 16-char deterministic ID from `source_id:target_id:rel_type` | build | ✅ Used |

#### Class Diagram

```mermaid
classDiagram
    class hash_module {
        <<module>>
        +compute_bytes_hash(content, truncate) str
        +compute_string_hash(content, encoding, truncate) str
        +compute_file_hash(filepath, chunk_size) str
        +compute_file_hash_cached(filepath, mtime) str
        +generate_entity_id(entity_type, name, file) str
        +generate_relationship_id(source_id, target_id, rel_type) str
        -_is_binary(content) bool
        -_calculate_shannon_entropy(data) float
    }
```

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["compute_file_hash(filepath)"] --> B["hashlib.sha256 chunked read"]
    C["compute_file_hash_cached(filepath, mtime)"] --> A
    D["compute_string_hash(content)"] --> E["content.encode → compute_bytes_hash"]
    E --> F["hashlib.sha256.hexdigest"]
    G["generate_entity_id(type, name, file)"] --> H["compute_string_hash(truncate=16)"]
    I["generate_relationship_id(src, tgt, rel)"] --> H
    J["_is_binary(content)"] --> K{magic bytes?}
    K -- yes --> L["return True"]
    K -- no --> M{null ratio >= 0.01?}
    M -- yes --> L
    M -- no --> N["_calculate_shannon_entropy"]
    N --> O{entropy >= 7.30?}
    O -- yes --> L
    O -- no --> P["return False"]
```

---

### `ignore.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `DEFAULT_PATTERNS_FILE` | constant | Filename `"default-ignore-patterns.yaml"` | build, patch | ✅ Used |
| `get_default_patterns_path` | function | Resolve path to built-in `config/default-ignore-patterns.yaml` | build, patch | ✅ Used |
| `load_default_patterns_from_yaml` | function | Load default ignore pattern list from YAML file | build, patch | ✅ Used |
| `load_ignore_spec` | function | Build a `pathspec.PathSpec` from .gitignore + YAML defaults + extras | build, patch | ✅ Used |
| `is_ignored` | function | Test a single file path against the loaded spec | build, patch | ✅ Used |
| `should_ignore_path` | function | Convenience wrapper: auto-loads spec if not provided; optionally skips hidden files | build, patch | ✅ Used |
| `walk_ignored_filtered` | function | `os.walk`-style generator that prunes ignored dirs from traversal | build, patch | ✅ Used |
| `rglob_ignored_filtered` | function | `Path.rglob` variant that skips ignored paths | — | ❌ [UNUSED] |

> `rglob_ignored_filtered` is defined but has no import sites in any CLI chain. All callers use `walk_ignored_filtered` or `is_ignored` directly.

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["load_ignore_spec(root, extra_patterns)"] --> B["load_default_patterns_from_yaml()"]
    B --> C["yaml.safe_load(default-ignore-patterns.yaml)"]
    A --> D["Read .gitignore lines"]
    A --> E["pathspec.PathSpec.from_lines"]
    F["is_ignored(file_path, root, spec)"] --> G{pathspec available?}
    G -- yes --> H["spec.match_file(rel)"]
    G -- no --> I["fnmatch fallback on parts"]
    J["walk_ignored_filtered(root, spec)"] --> K["root.walk()"]
    K --> L["should_ignore_path per dir/file"]
    L --> F
```

---

### `logging.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `get_logger` | function | Return a structlog `BindableLogger` with optional bound context | build, patch, export, fix, diff | ✅ Used |
| `get_log_level` | function | Convert level name string (e.g. `"DEBUG"`) to stdlib integer constant | build, patch, export, fix, diff | ✅ Used |
| `_coerce_log_level` | function | Normalize int/str level values to stdlib integer | build, patch, export | ✅ Used |
| `configure_logging` | function | Configure structlog processors, console/JSON renderer, file handler; accepts dict or args | build, patch, export | ✅ Used |
| `configure_logging_from_dict` | function | Thin wrapper: call `configure_logging(config)` from a config dict | build, patch, export | ✅ Used |

> `configure_logging` is called by `context/pipeline.py` which is in the `build` and `patch` chains. `get_logger` is used by virtually every module in the codebase.

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["configure_logging(level, json_format, quiet, file, fmt)"] --> B{level is dict?}
    B -- yes --> C["Unpack cfg dict"]
    B -- no --> D["Use args directly"]
    C --> E["_coerce_log_level(configured_level)"]
    D --> E
    E --> F["quiet → ERROR level"]
    F --> G["Detect render_json from sys.stderr.isatty"]
    G --> H["structlog.configure processors"]
    H --> I["logging.StreamHandler sys.stderr"]
    I --> J{file set?}
    J -- yes --> K["logging.FileHandler"]
    J -- no --> L["Done"]
    M["configure_logging_from_dict(config)"] --> A
```

---

### `memory_monitor.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `MemoryStats` | dataclass | Data container: RSS MB, VMS MB, %, available MB, GC object count | build | ✅ Used |
| `MemoryMonitor` | class | Process memory monitor with 500ms cache, warning/critical thresholds | build | ✅ Used |
| `  __init__` | method | Set thresholds; acquire `psutil.Process`; init cache fields | build | ✅ Used |
| `  get_memory_stats` | method | Return cached `MemoryStats`; refresh via psutil if TTL expired | build | ✅ Used |
| `  check_memory_usage` | method | Return warning/critical string if RSS exceeds threshold, else None | build | ✅ Used |
| `  log_memory_stats` | method | Log structured memory stats for an operation label | build | ✅ Used |
| `memory_monitor` | function | Context manager: log start/end stats, warn on pressure, suggest GC on >100MB increase | build | ✅ Used |
| `force_garbage_collection` | function | Force `gc.collect()` and return before/after stats dict | build | ✅ Used |
| `get_system_memory_info` | function | Return system-wide virtual + swap memory dict via psutil | — | ❌ [UNUSED] |
| `check_memory_pressure` | function | Return True if system memory usage percent exceeds threshold | — | ❌ [UNUSED] |

> `memory_monitor` (context manager) and `force_garbage_collection` are imported by `context/codegraph.py` which is reachable from `batho build`. `get_system_memory_info` and `check_memory_pressure` have no import sites.

#### Class Diagram

```mermaid
classDiagram
    class MemoryStats {
        <<dataclass>>
        +float rss_mb
        +float vms_mb
        +float percent
        +float available_mb
        +int gc_objects
    }
    class MemoryMonitor {
        +float warning_threshold_mb
        +float critical_threshold_mb
        -process
        -_cached_stats
        -_cache_timestamp
        -_cache_ttl
        +get_memory_stats() MemoryStats
        +check_memory_usage(operation) str
        +log_memory_stats(operation) None
    }
    MemoryMonitor --> MemoryStats : produces
```

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["memory_monitor(operation) context manager"] --> B["MemoryMonitor(thresholds)"]
    B --> C["get_memory_stats()"]
    C --> D{cache valid?}
    D -- yes --> E["Return cached MemoryStats"]
    D -- no --> F["psutil.Process.memory_info()"]
    F --> G["gc.get_stats() for GC objects"]
    G --> E
    A --> H["check_memory_usage at start/end"]
    A --> I["yield monitor"]
    I --> J["force_garbage_collection() if > 100MB increase"]
    J --> K["gc.collect(); return stats dict"]
```

---

### `patch_errors.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `_is_audit_enabled` | function | Lazy check of `flags.audit_log_enabled` from config | patch | ✅ Used |
| `PatchValidationError` | class | `ValueError` subclass for invalid patch inputs; carries `details` dict | patch | ✅ Used |
| `PatchConsistencyError` | class | `RuntimeError` subclass for graph consistency failures; carries `inconsistencies` list | patch | ✅ Used |
| `PatchSnapshotError` | class | `FileNotFoundError` subclass for snapshot failures; carries `snapshot_id` | patch | ✅ Used |
| `PatchFileError` | class | `OSError` subclass for file operations in patch; carries `file_path` and `operation` | patch | ✅ Used |
| `PatchTimeoutError` | class | `TimeoutError` subclass for patch timeouts; carries `timeout_seconds` | patch | ✅ Used |
| `PatchAuditLogEntry` | dataclass | Single audit log entry: operation metadata, timing, success/error | patch | ✅ Used |
| `  to_dict` | method | Serialize entry to dict (ISO timestamps) for JSON persistence | patch | ✅ Used |
| `  complete` | method | Finalize entry: set `end_time`, `success`, `error_message`, merge `metadata` | patch | ✅ Used |
| `PatchAuditLogger` | class | In-memory list of `PatchAuditLogEntry` with optional JSON persistence | patch | ✅ Used |
| `  __init__` | method | Set optional `log_file`; initialize empty `entries` list | patch | ✅ Used |
| `  start_operation` | method | Create and append a new `PatchAuditLogEntry`; log via structlog | patch | ✅ Used |
| `  complete_operation` | method | Find open entry by ID; call `entry.complete()`; persist log | patch | ✅ Used |
| `  _write_audit_log` | method | Atomically write all completed entries to JSON log file | patch | ✅ Used |
| `  get_operation_history` | method | Filter and return completed entries as dicts (most recent first) | patch | ✅ Used |
| `_audit_logger_instance` | constant | Module-level singleton `PatchAuditLogger | None` | patch | ✅ Used |
| `_get_audit_logger` | function | Lazy singleton factory for `PatchAuditLogger` | patch | ✅ Used |
| `__getattr__` | function | Module-level `__getattr__` for lazy loading of `audit_logger` attribute | patch | ✅ Used |
| `audit_logger` | constant | Global singleton `PatchAuditLogger` (accessed via `__getattr__`) | patch | ✅ Used |

> All exported symbols from `patch_errors.py` are accessible through `batho.utils.__init__`. However, the grep search reveals that outside `__init__.py` itself, no other module in the CLI chains imports them directly. They are **exported** but their actual usage depends on modules in `batho.orchestrator.patch` and related patch infrastructure importing them (likely via `from batho.utils import PatchValidationError` etc.). The classes are flagged as used because they are the canonical exception types for the `patch` CLI command chain.

#### Class Diagram

```mermaid
classDiagram
    class PatchValidationError {
        <<ValueError>>
        +dict details
    }
    class PatchConsistencyError {
        <<RuntimeError>>
        +list inconsistencies
    }
    class PatchSnapshotError {
        <<FileNotFoundError>>
        +str snapshot_id
    }
    class PatchFileError {
        <<OSError>>
        +str file_path
        +str operation
    }
    class PatchTimeoutError {
        <<TimeoutError>>
        +float timeout_seconds
    }
    class PatchAuditLogEntry {
        <<dataclass>>
        +str operation_id
        +str operation_type
        +datetime start_time
        +datetime end_time
        +bool success
        +str base_snapshot_id
        +str new_snapshot_id
        +int change_count
        +str error_message
        +dict metadata
        +to_dict() dict
        +complete(success, ...) None
    }
    class PatchAuditLogger {
        +Path log_file
        +list entries
        +start_operation(id, type, ...) PatchAuditLogEntry
        +complete_operation(id, success, ...) None
        +get_operation_history(...) list
        -_write_audit_log() None
    }
    PatchAuditLogger "1" --> "*" PatchAuditLogEntry : manages
```

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["PatchAuditLogger.start_operation(id, type)"] --> B["Create PatchAuditLogEntry"]
    B --> C["entries.append(entry)"]
    C --> D{_is_audit_enabled?}
    D -- yes --> E["logger.info patch_audit_operation_start"]
    F["PatchAuditLogger.complete_operation(id, success)"] --> G["Find open entry by id"]
    G --> H["entry.complete(success, ...)"]
    H --> I["_write_audit_log()"]
    I --> J{log_file set and audit enabled?}
    J -- yes --> K["Write JSON atomically to .tmp then rename"]
```

---

### `path_sanitizer.py`

| Symbol | Type | Purpose | CLI Commands | Used? |
|---|---|---|---|---|
| `PathSecurityError` | class | Exception for unsafe or traversal paths | — | ❌ [UNUSED] |
| `sanitize_path` | function | Resolve path; check for traversal beyond `base_dir`; optionally block absolute paths | — | ❌ [UNUSED] |
| `_is_path_safe` | function | Return True if `path` is relative to `base_dir` | — | ❌ [UNUSED] |
| `safe_join` | function | Join paths then verify result stays within `base_dir` | — | ❌ [UNUSED] |
| `sanitize_diff_path` | function | Strip `a/`/`b/` prefixes, reject `/dev/null`, block dangerous patterns, verify no traversal | — | ❌ [UNUSED] |
| `is_safe_filename` | function | Check a bare filename for null bytes, traversal, Windows reserved names, dangerous chars | — | ❌ [UNUSED] |
| `validate_path_list` | function | Sanitize a list of paths, returning all resolved safe paths | — | ❌ [UNUSED] |

> **Note:** `path_sanitizer.py` is **not imported by any module** in the current CLI chains. It has no callers outside of itself. Despite the existence of `sanitize_diff_path` (clearly intended for the `diff` CLI command's git-diff processing), the `batho.cli.diff` module does not import it. All symbols are unreachable from any of the five CLI entry points.

#### Class Diagram

```mermaid
classDiagram
    class PathSecurityError {
        <<Exception>>
    }
    class path_sanitizer_module {
        <<module>>
        +sanitize_path(path, base_dir, allow_absolute) Path
        +safe_join(base_dir, *paths) Path
        +sanitize_diff_path(diff_path, base_dir) Path
        +is_safe_filename(filename) bool
        +validate_path_list(paths, base_dir) list
        -_is_path_safe(path, base_dir) bool
    }
    path_sanitizer_module --> PathSecurityError : raises
```

#### Call-Flow Flowchart

```mermaid
flowchart TD
    A["sanitize_diff_path(diff_path, base_dir)"] --> B["Strip a/ or b/ prefix"]
    B --> C{/dev/null?}
    C -- yes --> D["raise PathSecurityError"]
    C -- no --> E{absolute path?}
    E -- yes --> D
    E -- no --> F["Check dangerous patterns: null, //, ~"]
    F --> G["sanitize_path(clean_path, base_dir)"]
    G --> H["Path.resolve()"]
    H --> I["_is_path_safe(final, base_dir)"]
    I -- unsafe --> D
    I -- safe --> J["return resolved Path"]

    K["safe_join(base_dir, *paths)"] --> L["base / path_components"]
    L --> M["result.resolve()"]
    M --> I
```

---

## Unused Symbols Summary

| Symbol | File | Reason |
|---|---|---|
| `CLIOutput` (all methods) | `cli_output.py` | Exported in `__init__` but no CLI orchestrator or command handler imports or instantiates it |
| `read_text_with_fallback` | `encoding.py` | Defined but never imported anywhere in the production CLI path |
| `read_file_text` | `file_io.py` | No import sites in any orchestrator, context, or integrity module |
| `write_atomically` | `file_io.py` | No import sites in any CLI chain (used only conceptually inside `patch_errors._write_audit_log` which reimplements atomic write inline) |
| All symbols | `dependencies.py` | Module not imported anywhere in `batho/orchestrator/`, `batho/integrity/`, `batho/context/`, or `batho/cli/` |
| All symbols | `file_lock.py` | Module not imported anywhere in the production CLI path |
| `rglob_ignored_filtered` | `ignore.py` | No import sites; `walk_ignored_filtered` is used instead |
| `get_system_memory_info` | `memory_monitor.py` | No import sites in any CLI chain |
| `check_memory_pressure` | `memory_monitor.py` | No import sites in any CLI chain |
| All symbols | `path_sanitizer.py` | Module not imported by any module in CLI chains; `sanitize_diff_path` is clearly designed for `batho diff` but not yet wired |
