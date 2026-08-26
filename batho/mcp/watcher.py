"""Batho MCP Watcher Engine — File system watching and automatic patch indexing.

Monitors watched repositories for file system events, debounces rapid changes,
and automatically triggers incremental patches via `batho.orchestrator.patch`.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
import threading
import time
from typing import Any, TYPE_CHECKING

import structlog

from batho.mcp.registry import RepoRegistry, RepoEntry
from batho.utils.ignore import load_ignore_spec, should_ignore_path
from batho.utils.hash import compute_file_hash

if TYPE_CHECKING:
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    from watchdog.observers import Observer

LOGGER = structlog.get_logger(__name__)


def _require_watchdog():
    """Lazily import watchdog and return the (EventHandler, Event, Observer) tuple.

    Raises ImportError with an actionable message if watchdog is not installed,
    so the MCP server can still start with ``--no-watch`` even when the
    optional watchdog dependency is absent.
    """
    try:
        from watchdog.events import FileSystemEventHandler, FileSystemEvent
        from watchdog.observers import Observer
    except ImportError as exc:
        raise ImportError(
            "watchdog is required for file watching. Install it with "
            "'pip install watchdog>=6.0.0' or start the server with --no-watch."
        ) from exc
    return FileSystemEventHandler, FileSystemEvent, Observer


@dataclass
class WatchEntry:
    """Tracking state for a watched repository."""

    repo_name: str
    path: Path
    debounce_ms: int = 2000
    max_file_size_kb: int | None = None
    last_synced: float | None = None  # Unix timestamp
    sync_state: str = "idle"  # idle | pending | patching | error
    pending_files: set[str] = field(default_factory=set)
    observer: Any | None = None  # watchdog Observer
    debounce_timer: threading.Timer | None = None
    error_message: str | None = None
    ignore_spec: Any | None = None


def _make_event_handler_class(base_handler_cls: Any, event_cls: Any) -> Any:
    """Build a _BathoEventHandler subclass bound to the lazily-imported watchdog base.

    Defined as a factory so the module can be imported without watchdog
    installed; the class is only constructed when watching actually starts.
    """

    class _BathoEventHandler(base_handler_cls):
        """Watchdog event handler routing non-ignored file changes to watcher engine."""

        def __init__(self, engine: Any, repo_name: str, root_path: Path) -> None:
            super().__init__()
            self.engine = engine
            self.repo_name = repo_name
            self.root_path = root_path

        def on_any_event(self, event: Any) -> None:
            if event.is_directory:
                return

            event_path = Path(event.src_path)
            try:
                rel_path = event_path.relative_to(self.root_path).as_posix()
            except ValueError:
                return

            self.engine._on_change(self.repo_name, rel_path, event_path)

            if hasattr(event, "dest_path") and event.dest_path and event.dest_path != event.src_path:
                dest_path = Path(event.dest_path)
                try:
                    dest_rel = dest_path.relative_to(self.root_path).as_posix()
                except ValueError:
                    return
                self.engine._on_change(self.repo_name, dest_rel, dest_path)

    return _BathoEventHandler


class BathoWatcherEngine:
    """Keeps watched repositories patched and fresh upon filesystem changes."""

    def __init__(self, registry: RepoRegistry) -> None:
        self.registry = registry
        self._watches: dict[str, WatchEntry] = {}
        self._repo_locks: dict[str, threading.Lock] = {}
        self._lock = threading.RLock()
        self._running = False

    def start(self) -> None:
        """Load watched repos from registry and start file watchers."""
        with self._lock:
            self._running = True
            for entry in self.registry.list_all():
                if entry.watch:
                    self.watch(entry)

    def watch(self, entry: RepoEntry) -> None:
        """Start a platform-native recursive watcher for `entry`."""
        # Lazy import: only require watchdog when actually starting a watch.
        FileSystemEventHandler, _FileSystemEvent, Observer = _require_watchdog()

        with self._lock:
            repo_path = Path(entry.path).resolve()
            if not repo_path.exists() or not repo_path.is_dir():
                LOGGER.warning("watcher_path_not_found", repo=entry.name, path=str(repo_path))
                return

            if entry.name in self._watches:
                self.unwatch(entry.name)

            ignore_spec = load_ignore_spec(repo_path)
            watch_entry = WatchEntry(
                repo_name=entry.name,
                path=repo_path,
                debounce_ms=entry.debounce_ms,
                max_file_size_kb=entry.max_file_size_kb,
                sync_state=entry.sync_state,
                ignore_spec=ignore_spec,
            )

            handler_cls = _make_event_handler_class(FileSystemEventHandler, _FileSystemEvent)
            handler = handler_cls(self, entry.name, repo_path)
            observer = Observer()
            observer.schedule(handler, str(repo_path), recursive=True)
            observer.daemon = True
            observer.start()

            watch_entry.observer = observer
            self._watches[entry.name] = watch_entry
            LOGGER.info("watcher_started", repo=entry.name, path=str(repo_path), debounce_ms=entry.debounce_ms)

    def unwatch(self, repo_name: str) -> None:
        """Stop watching a specific repo."""
        # Pop the watch entry and cancel its timer under the lock, but
        # stop/join the observer *outside* the lock.  The watchdog observer
        # thread calls _on_change which acquires self._lock; if we hold
        # self._lock while waiting for observer.stop()/join() we deadlock
        # with the observer thread.
        with self._lock:
            watch = self._watches.pop(repo_name, None)
            if not watch:
                return

            if watch.debounce_timer:
                watch.debounce_timer.cancel()
                watch.debounce_timer = None

            observer = watch.observer
            watch.observer = None

        # Stop and join the observer outside self._lock so the observer's
        # event-dispatch thread (which may be blocked in _on_change waiting
        # for self._lock) can drain and exit.
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=2.0)
            except Exception as exc:
                LOGGER.warning("watcher_stop_error", repo=repo_name, error=str(exc))

        LOGGER.info("watcher_stopped", repo=repo_name)

    def stop(self) -> None:
        """Stop all watchers and clean up."""
        with self._lock:
            self._running = False
            repo_names = list(self._watches.keys())
        # Unwatch each repo outside self._lock to avoid the observer-stop
        # deadlock described in unwatch().
        for repo_name in repo_names:
            self.unwatch(repo_name)

    def _on_change(self, repo_name: str, rel_path: str, full_path: Path) -> None:
        """Callback from file watcher — adds to pending and schedules debounced patch."""
        with self._lock:
            watch = self._watches.get(repo_name)
            if not watch or not self._running:
                return

            # Check if file should be ignored (default ignore spec already excludes .batho/)
            if should_ignore_path(full_path, watch.path, watch.ignore_spec, include_hidden=True):
                return

            # Check file size limit if configured
            if watch.max_file_size_kb and full_path.exists():
                try:
                    file_size_kb = full_path.stat().st_size / 1024.0
                    if file_size_kb > watch.max_file_size_kb:
                        LOGGER.debug("watcher_file_exceeds_max_size", repo=repo_name, file=rel_path, size_kb=file_size_kb)
                        return
                except OSError:
                    pass

            watch.pending_files.add(rel_path)
            if watch.sync_state != "pending":
                watch.sync_state = "pending"
                self.registry.update_sync_state(repo_name, "pending")

            if watch.debounce_timer:
                watch.debounce_timer.cancel()

            timer = threading.Timer(
                watch.debounce_ms / 1000.0,
                self._run_patch,
                args=(repo_name,),
            )
            timer.daemon = True
            watch.debounce_timer = timer
            timer.start()

    def _run_patch(self, repo_name: str) -> None:
        """Run batho patch for the repo and clear pending files on success."""
        with self._lock:
            watch = self._watches.get(repo_name)
            if not watch:
                return
            watch.sync_state = "patching"
            self.registry.update_sync_state(repo_name, "patching")

        # run_patch already acquires the cross-process InterProcessLock on
        # <root>/.batho/batho.lock internally, so auto-patches and manual
        # batho_patch/batho_build tool calls serialize against each other via
        # that lock. The in-memory lock here only guards same-process
        # re-entrancy from overlapping debounce timers.
        in_proc_lock = self._repo_locks.setdefault(repo_name, threading.Lock())
        try:
            with in_proc_lock:
                import batho.orchestrator.patch as patch_mod

                options = patch_mod.PatchOptions(
                    root=watch.path,
                    max_file_size_kb=watch.max_file_size_kb,
                )
                patch_mod.run_patch(options)

        except Exception as exc:
            with self._lock:
                watch.sync_state = "error"
                watch.error_message = str(exc)
                self.registry.update_sync_state(repo_name, "error")
            LOGGER.error("watcher_patch_failed", repo=repo_name, error=str(exc))
            return

        iso_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        now_ts = time.time()
        with self._lock:
            watch.pending_files.clear()
            watch.sync_state = "idle"
            watch.last_synced = now_ts
            watch.error_message = None
            self.registry.update_sync_state(repo_name, "idle", last_synced=iso_ts)

        # Invalidate reader pool for this repo
        import batho.mcp.tools as tools_mod
        tools_mod.invalidate_reader_pool(repo_name)
        LOGGER.info("watcher_patch_success", repo=repo_name, synced_at=iso_ts)


    def is_pending(self, repo_name: str, rel_path: str) -> bool:
        """Check if a file is pending re-index."""
        with self._lock:
            watch = self._watches.get(repo_name)
            if not watch:
                return False
            return rel_path in watch.pending_files

    def get_staleness_banner(self, repo_name: str, file_path: str | None = None) -> str | None:
        """Return a staleness warning string if the repo or file is pending."""
        with self._lock:
            watch = self._watches.get(repo_name)
            if not watch:
                return None
            if watch.sync_state == "patching":
                return "⚠️ Artifact is currently being re-patched. Results may be stale."
            if file_path and file_path in watch.pending_files:
                return f"⚠️ File `{file_path}` is pending re-index. Read it directly for the live content."
            if watch.sync_state == "pending":
                return "⚠️ Some files are pending re-index. Results may be stale."
            if watch.sync_state == "error":
                return f"⚠️ Auto-patch failed: {watch.error_message or 'Unknown error'}."
        return None

    def status(self) -> dict[str, Any]:
        """Return watcher status for all watched repos."""
        with self._lock:
            res: dict[str, Any] = {}
            for name, watch in self._watches.items():
                res[name] = {
                    "watching": True,
                    "sync_state": watch.sync_state,
                    "pending_files": list(watch.pending_files),
                    "pending_count": len(watch.pending_files),
                    "last_synced": watch.last_synced,
                    "error_message": watch.error_message,
                    "debounce_ms": watch.debounce_ms,
                }
            return res

    def catch_up(self, repo_name: str) -> None:
        """Patch-on-connect: check if files changed while server was down."""
        entry = self.registry.get(repo_name)
        if not entry:
            return
        artifact_dir = entry.artifact_dir
        if not artifact_dir.exists():
            return

        try:
            from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
            reader = BathoBundleReader(artifact_dir)
            ft_table = reader._get_table("file_tracking")

            repo_path = Path(entry.path).resolve()
            ignore_spec = load_ignore_spec(repo_path)
            
            stored_hashes: dict[str, str] = {}
            for row in ft_table.to_pylist():
                stored_hashes[row["file_path"]] = row["content_hash"]

            needs_patch = False
            # Check existing tracked files for changes
            for rel_path, expected_hash in stored_hashes.items():
                full_path = repo_path / rel_path
                if not full_path.exists():
                    needs_patch = True
                    break
                if entry.max_file_size_kb:
                    try:
                        if full_path.stat().st_size / 1024.0 > entry.max_file_size_kb:
                            continue
                    except OSError:
                        pass
                curr_hash = compute_file_hash(full_path)
                if curr_hash != expected_hash:
                    needs_patch = True
                    break

            if not needs_patch:
                # Check for untracked new files on disk
                from batho.utils.ignore import walk_ignored_filtered
                for dirpath, _, filenames in walk_ignored_filtered(repo_path, spec=ignore_spec, skip_hidden=True):
                    for filename in filenames:
                        full_f = dirpath / filename
                        try:
                            rel_f = full_f.relative_to(repo_path).as_posix()
                        except ValueError:
                            continue
                        if rel_f not in stored_hashes:
                            needs_patch = True
                            break
                    if needs_patch:
                        break

            if needs_patch:
                LOGGER.info("watcher_catch_up_triggered", repo=repo_name)
                self._run_patch(repo_name)
        except Exception as exc:
            LOGGER.warning("watcher_catch_up_error", repo=repo_name, error=str(exc))
