# Batho Audit Results

## 1. Race condition: BathoDatabase shares connection across threads but transaction() is not serialized
- **Severity:** Critical
- **Category:** Concurrency
- **Location:** `batho/modules/storage/sqlite_registry/engine.py` (Lines 329-379)
- **Description:**  
  `_get_connection()` stores the SQLite connection in `threading.local()` and passes `check_same_thread=False`. However, `BathoDatabase` instances are cached and reused (via `_DB_CACHE`) and shared with multiprocessing worker pools and async pipelines. Two threads invoking `transaction()` will each call `_get_connection()`, which returns the thread-local connection — but `_DB_CACHE` and `_string_dict_cache` are shared mutable state without locking around `transaction()`. Worse, in the multiprocessing pipeline, child processes can inherit the cached connection but it's not valid post-fork; `_apply_pragmas`, `_initialize`, and `_string_dict_cache` access are not protected by `self._lock` at all. Note that `self._lock` is declared but never used anywhere in the file. This leads to "database is locked", silent corruption of string_dict IDs, or "Recursive use of cursors not allowed" errors in concurrent runs.
- **Code Evidence:**
  ```
  self._lock = threading.RLock()  # Declared but NEVER acquired anywhere
  self._local = threading.local()
  ...
  def _get_connection(self) -> sqlite3.Connection:
      if not hasattr(self._local, "conn") or self._local.conn is None:
          ...
          conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=30.0)
          ...
  @contextmanager
  def transaction(self) -> Iterator[sqlite3.Connection]:
      conn = self._get_connection()
      conn.execute("BEGIN IMMEDIATE")   # No lock — concurrent BEGIN IMMEDIATE from same conn raises
      try:
          yield conn
          conn.commit()
  ```
---

## 2. connection() context manager does not commit, leading to silent data loss on writes
- **Severity:** Critical
- **Category:** Logic Error
- **Location:** `batho/modules/storage/sqlite_registry/engine.py` (Lines 361-368)
- **Description:**  
  `BathoDatabase.connection()` is the documented "writer" context manager (used in dozens of write paths). Some callers add an explicit `conn.commit()`, but several do not — and the context manager itself never commits. Combined with the long-lived per-thread connection (which begins an implicit transaction on the first write), writes that omit `commit()` will be invisible until the next explicit commit on the same connection, or lost if the connection is closed/discarded.
- **Code Evidence:**
  ```
  @contextmanager
  def connection(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
      conn = self._get_connection()
      try:
          yield conn
      except Exception:
          conn.rollback()
          raise
      # NO COMMIT — writes that omit explicit commit() silently linger or vanish
  ```
---

## 3. SQL injection via unsanitized column name in repair_run_artifact (mitigated, but pattern is fragile)
- **Severity:** Medium
- **Category:** Security
- **Location:** `batho/modules/integrity/repairers/blob_repairer.py` (Lines 65-94)
- **Description:**  
  The fix uses an allowlist, which is correct. However, the format string is built with `f"UPDATE run_artifacts SET {column} = NULL ..."`, and the allowlist is duplicated logic from the schema. If a new blob column is added to schema and the allowlist isn't updated, repair silently fails. The pattern of "build SQL via f-string + allowlist" is repeated elsewhere, making future maintenance risky.
- **Code Evidence:**
  ```
  cursor = conn.execute(
      f"UPDATE run_artifacts SET {column} = NULL WHERE run_id = ?",
      (run_id,),
  )
  ```
---

## 4. Patch run: per-batch shared entity_ids_in_batch validation cross-contaminates files
- **Severity:** High
- **Category:** Logic Error
- **Location:** `batho/modules/storage/sqlite_registry/engine.py` (Lines 779-883)
- **Description:**  
  In `insert_file_artifacts_batch`, `entity_ids_in_batch = {e[0] for e in query_entities_rows}` is computed inside a per-item loop, but `query_entities_rows` accumulates across all items in the batch. For file 1, every cross-file reference is wrongly classified as dangling; for the last file, valid same-file references look fine but later-file refs are classified dangling. This causes inconsistent results depending on file processing order.
- **Code Evidence:**
  ```
  for item in batch_items:
      ...
      entity_ids_in_batch = {e[0] for e in query_entities_rows}  # GROWS across items
      ...
      for r in relationships_data:
          ...
          elif tgt_id not in entity_ids_in_batch:    # Decision depends on iteration order
              dangling_references_rows.append((src_id, tgt_id, r_type, run_internal_id))
  ```
---

## 5. delete_ast_by_path ignores variant when called by patch — broken cache invalidation
- **Severity:** High
- **Category:** Caching
- **Location:**  
  - `batho/modules/storage/cache/unified_cache.py` (Lines 81-89, 131-146)
  - `batho/orchestrator/patch.py` (no AST-cache invalidation call)
- **Description:**  
  `BathoCache._normalize_ast_path` calls `path.resolve()` on a possibly-relative input, which resolves symlinks and `..` against the current working directory, not against `self._db.repo_root`. After resolution, only the path-component of the key is checked in `delete_ast_by_path`, ignoring the (hash, variant) tuple components. The in-memory AST cache is never invalidated during incremental patches if `run_patch` never calls `delete_ast_by_path`.
- **Code Evidence:**
  ```
  def _normalize_ast_path(self, file_path: str) -> str:
      path = Path(file_path)
      if not path.is_absolute() and self._db is not None:
          path = self._db.repo_root / path
      try:
          return str(path.resolve())   # Resolves against PWD if base join didn't happen
      except OSError:
          return str(path)
  ```
---

## 6. BathoDatabase.__init__ opens a transient connection but never closes it on error
- **Severity:** Medium
- **Category:** Resource Management
- **Location:** `batho/modules/storage/sqlite_registry/engine.py` (Lines 289-313)
- **Description:**  
  In the schema-version guard, `conn = sqlite3.connect(...)` is opened, but if any exception other than `OperationalError` is raised, `conn.close()` is never called. This leaks the file descriptor.
- **Code Evidence:**
  ```
  if self._db_path.exists() and self._db_path.stat().st_size > 0:
      try:
          conn = sqlite3.connect(str(self._db_path), timeout=5.0)
          conn.row_factory = sqlite3.Row
          row = conn.execute(...).fetchone()
          conn.close()            # only closed on the happy path
          if row: ...
      except sqlite3.OperationalError:   # other exceptions leak the conn
          raise RuntimeError(...)
  ```
---

## 7. _DB_CACHE retains closed databases when _closed flag is set externally
- **Severity:** High
- **Category:** Resource Management / State
- **Location:**  
  - `batho/modules/storage/sqlite_registry/engine.py` (Lines 39-263, 1544-1550)
  - `batho/modules/integrity/repairers/sqlite_repairer.py` (Lines 58-61)
- **Description:**  
  `repair_dump_and_restore` directly mutates `_DB_CACHE[key]._closed = True` and deletes the entry, but never calls `.close()` on the underlying connection. The thread-local `_local.conn` for that instance is now orphaned, holding an open FD against a file that's about to be renamed.
- **Code Evidence:**
  ```
  # sqlite_repairer.py:58-61
  if key in _DB_CACHE:
      _DB_CACHE[key]._closed = True   # flag set, but local thread conns still open
      del _DB_CACHE[key]
  # engine.py:1544-1550
  def close(self) -> None:
      with _DB_CACHE_LOCK:
          with self._lock:
              self._closed = True
              if hasattr(self._local, "conn") and self._local.conn is not None:
                  self._local.conn.close()   # ONLY closes the calling thread's connection
                  self._local.conn = None
  ```
---

## 8. Schema mismatch guard raises but leaves cached DB in _DB_CACHE for subsequent retries
- **Severity:** Medium
- **Category:** State / Logic Error
- **Location:** `batho/modules/storage/sqlite_registry/engine.py` (Lines 257-263, 289-313)
- **Description:**  
  `get_database()` populates `_DB_CACHE[key] = db` only after `BathoDatabase(...)` returns. If `__init__` raises, the next `get_database()` call retries the same construction (and re-raises) — but a partially-constructed instance from an `__init__` that raised may still leak file descriptors.
- **Code Evidence:**
  ```
  with _DB_CACHE_LOCK:
      existing = _DB_CACHE.get(key)
      if existing is not None and not getattr(existing, "_closed", False):
          return existing
      db = BathoDatabase(resolved_path, repo_root=root)   # may raise; leaves no cache entry
      _DB_CACHE[key] = db
      return db
  ```
---

## 9. Per-row insert/update in insert_file_artifact non-batch path uses two separate transactions that can de-sync
- **Severity:** High
- **Category:** Logic / Atomicity
- **Location:** `batho/modules/storage/sqlite_registry/engine.py` (Lines 623-755)
- **Description:**  
  `insert_file_artifact` writes `file_artifacts` in one `self.connection()` block (commits at the end), then writes `query_entities` and `query_relationships` in separate `self.transaction()` blocks. If a crash or exception happens between blocks, the database is left half-applied.
- **Code Evidence:**
  ```
  def insert_file_artifact(self, ...):
      ...
      with self.connection() as conn:
          conn.execute("INSERT OR REPLACE INTO file_artifacts...")
          conn.commit()               # commit 1

      with self.transaction() as conn:        # transaction 2
          conn.execute("DELETE FROM query_entities ...")
          conn.executemany("INSERT OR REPLACE INTO query_entities...")
          conn.commit()

      with self.transaction() as conn:        # transaction 3
          conn.execute("DELETE FROM query_relationships ...")
          ...
  ```
---

## 10. resolve_dangling_references SQL: incorrect JOIN clause may produce wrong resolutions
- **Severity:** High
- **Category:** Logic Error
- **Location:** `batho/modules/storage/sqlite_registry/engine.py` (Lines 757-777)
- **Description:**  
  The JOIN condition `JOIN query_entities e ON (d.unresolved_target_name = e.entity_name OR d.unresolved_target_name = e.entity_id) AND d.run_id = e.run_id` has incorrect operator precedence, so matching via entity_name ignores the run_id filter, creating cross-run relationship pollution.
- **Code Evidence:**
  ```
  """INSERT OR IGNORE INTO query_relationships (source_id, target_id, relation_type, run_id)
     SELECT d.source_id, e.entity_id, d.relation_type, d.run_id
     FROM dangling_references d
     JOIN query_entities e ON (d.unresolved_target_name = e.entity_name OR d.unresolved_target_name = e.entity_id)
     AND d.run_id = e.run_id      -- precedence bug: name match bypasses run_id
     WHERE d.run_id = ? AND e.entity_type != 'UNRESOLVED'""",
  ```
---

## 11. compute_file_hash_cached LRU cache returns stale results because mtime is the only invalidator
- **Severity:** High
- **Category:** Caching / Logic Error
- **Location:** `batho/utils/hash.py` (Lines 156-168)
- **Description:**  
  The `@functools.lru_cache` keyed on `(filepath, mtime)` does not detect content-only mutations that preserve mtime. The cache is also unbounded and does not invalidate on file deletion.
- **Code Evidence:**
  ```
  @functools.lru_cache(maxsize=1024)
  def compute_file_hash_cached(filepath: str, mtime: float) -> str | None:
      # mtime-only key; doesn't detect content changes with preserved mtime
      return compute_file_hash(filepath)
  ```
---

## 12. is_safe_filename accepts traversal via Unicode/encoded variants
- **Severity:** Medium
- **Category:** Security
- **Location:** `batho/utils/path_sanitizer.py` (Lines 164-215)
- **Description:**  
  `is_safe_filename` checks for literal "..", "/", "\\" substrings and a fixed dangerous-char set. It does not normalize the input (no `unicodedata.normalize("NFKC", filename)`), so fullwidth slash "／" (U+FF0F), backslash "＼", or `%2F` (URL-encoded slash) pass the check.
- **Code Evidence:**
  ```
  def is_safe_filename(filename: str) -> bool:
      if "\0" in filename:
          return False
      # No NFKC normalization — fullwidth U+FF0F slipping past
      if ".." in filename or "/" in filename or "\\" in filename:
          return False
      ...
  ```
---

## 13. FileLock._is_lock_stale ignores wraparound PID reuse — different process gets falsely deemed alive
- **Severity:** Medium
- **Category:** Logic Error
- **Location:** `batho/utils/file_lock.py` (Lines 113-129)
- **Description:**  
  When the original lock holder dies and its PID is recycled, `_is_process_alive(pid)` returns True for the new process, so the stale-lock cleanup never triggers. The lock file records a timestamp but `_is_lock_stale` never consults it.
- **Code Evidence:**
  ```
  def _is_lock_stale(self, pid: int, timestamp: float) -> bool:
      # If the owning process is alive, the lock is not stale regardless of age.
      if self._is_process_alive(pid):     # False positive on PID reuse
          return False
      logger.debug("stale_lock_dead_process", pid=pid)
      return True
  ```
---

## 14. _run_git in incremental.py inherits parent env and PATH — command injection-adjacent attack surface
- **Severity:** Medium
- **Category:** Security
- **Location:** `batho/modules/graph/incremental.py` (Lines 14-26)
- **Description:**  
  `subprocess.run(["git", *args], cwd=str(repo_root), ...)` does not pass `env=` and does not pin a git binary path. If `PATH` includes a directory under attacker control, a malicious git executable could be run.
- **Code Evidence:**
  ```
  def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
      try:
          return subprocess.run(
              ["git", *args],          # PATH-resolved at call time
              cwd=str(repo_root),      # user-controlled CWD
              capture_output=True,
              text=True,
              check=True,
          )
      except (FileNotFoundError, subprocess.CalledProcessError):
          return None
  ```
---

## 15. run_patch does not call db.fail_run when failure occurs before run_uuid assignment
- **Severity:** Medium
- **Category:** State
- **Location:** `batho/orchestrator/patch.py` (Lines 162-225, 608-621)
- **Description:**  
  If a failure occurs before `run_uuid` assignment, `db.fail_run` is not called. If a failure occurs after, a running-status row is left in `index_runs` if `db.create_run` itself raises after writing a row but before returning.
- **Code Evidence:**
  ```
  run_uuid = ""
  base_run_uuid = ""
  try:
      base_run_uuid = db.get_latest_run_id() or ""
      ...
      run_uuid = _generate_run_id()
      ...
  except Exception as e:
      LOGGER.error("patch_unhandled_exception", error=str(e))
      if run_uuid:
          try: db.fail_run(run_uuid, error_message=str(e))
          ...
  db = get_database(root)   # outside try block — exception escapes uncaught
  ```
---

## 16. run_patch SQL query may exceed SQLite SQLITE_MAX_VARIABLE_NUMBER limit on large changesets
- **Severity:** High
- **Category:** Logic Error / Resource
- **Location:** `batho/orchestrator/patch.py` (Lines 248-295)
- **Description:**  
  Parameterized queries pass a potentially unbounded number of placeholders directly; SQLite's default `SQLITE_MAX_VARIABLE_NUMBER` is 999 (pre-3.32). A patch touching ≥ 1000 files raises `OperationalError: too many SQL variables`.
- **Code Evidence:**
  ```
  placeholders = ",".join("?" * len(changed_file_ids))
  conn.execute(
      f"""INSERT INTO file_artifacts(...) SELECT ... FROM file_artifacts
          WHERE run_id = ? AND file_id NOT IN ({placeholders})""",
      [run_internal_id, base_run_internal_id] + list(changed_file_ids),
  )
  ```
---

## 17. Patch orchestrator: query_relationships copy filter drops cross-file rels involving changed targets
- **Severity:** High
- **Category:** Logic Error
- **Location:** `batho/orchestrator/patch.py` (Lines 275-284)
- **Description:**  
  When copying `query_relationships` for unchanged files, the `WHERE` clause filters only by `source_id IN (... where file_path NOT IN changed)`. It does not constrain the target, so relationships from unchanged to changed files are copied forward with the old `entity_id`, breaking cross-file relationships.
- **Code Evidence:**
  