"""Batho MCP Watcher Engine — File system watching and automatic patch indexing.

Monitors watched repositories for file system events, debounces rapid changes,
and automatically triggers incremental patches via `batho.orchestrator.patch`.

Watcher v2: compound flush triggers (idle debounce, max-staleness bound,
pending-count threshold, git boundary) plus an optional git sentinel layer
watching the resolved git dir for logical change boundaries (stage, commit,
checkout, merge, rebase completion). Filesystem events are only *hints* —
``IncrementalEngine.scan_changes`` hash-diff remains the source of truth, so
lost events are recovered by the next patch rather than a poisoned state.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, TYPE_CHECKING

import structlog

from batho.mcp import git_sentinel
from batho.mcp.registry import RepoRegistry, RepoEntry
from batho.utils.ignore import load_ignore_spec, should_ignore_path
from batho.utils.hash import compute_file_hash

if TYPE_CHECKING:
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    from watchdog.observers import Observer

LOGGER = structlog.get_logger(__name__)

_PENDING_FILES_CAP = 10_000


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


def _repo_ignore_spec(repo_path: Path) -> Any:
    """Ignore spec for a repo, honoring its indexer config.

    Mirrors the build's spec construction (indexer.ignore_defaults,
    ignore_patterns, ignore_files, default_patterns_file from the repo's
    batho.yaml) so build, patch, and watch agree on which files are
    indexable. Falls back to defaults + .gitignore when config loading fails.
    """
    try:
        from batho.core.config import get_config_with_root

        indexer_cfg = get_config_with_root(repo_path).get("indexer", {})
        return load_ignore_spec(
            repo_path,
            extra_patterns=indexer_cfg.get("ignore_patterns"),
            ignore_files=indexer_cfg.get("ignore_files"),
            default_patterns_file=indexer_cfg.get("default_patterns_file"),
            use_defaults=indexer_cfg.get("ignore_defaults", True),
        )
    except Exception as exc:
        LOGGER.warning(
            "watcher_ignore_config_load_failed",
            path=str(repo_path),
            error=str(exc),
        )
        return load_ignore_spec(repo_path)


def _watch_cfg(repo_path: Path) -> dict[str, Any]:
    """Global ``watch:`` section from the repo's batho.yaml (empty on failure)."""
    try:
        from batho.core.config import get_config_with_root

        cfg = get_config_with_root(repo_path).get("watch", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception as exc:
        LOGGER.warning(
            "watcher_watch_config_load_failed",
            path=str(repo_path),
            error=str(exc),
        )
        return {}


def _is_hidden_path(rel_path: str) -> bool:
    """Cheap dot-component check — mirrors should_ignore_path(include_hidden=True)."""
    return any(
        p.startswith(".") and p not in (".", "..")
        for p in Path(rel_path).parts
    )


def _schedule_worktree_watches(
    observer: Any, handler: Any, repo_path: Path, ignore_spec: Any
) -> None:
    """Register worktree watches on the observer.

    On Linux, ``recursive=True`` registers one inotify descriptor per
    directory — including all of ``.git/objects/**`` and ignored trees like
    ``node_modules`` — pure descriptor waste since hidden/ignored events are
    filtered pre-lock anyway. So on Linux we walk the tree and schedule each
    visible, non-ignored directory individually. FSEvents (macOS) and
    ReadDirectoryChanges (Windows) apply recursion at the stream level and
    pay no per-directory cost, so ``recursive=True`` stays there.
    """
    if not sys.platform.startswith("linux"):
        observer.schedule(handler, str(repo_path), recursive=True)
        return

    stack = [repo_path]
    while stack:
        directory = stack.pop()
        observer.schedule(handler, str(directory), recursive=False)
        try:
            with os.scandir(directory) as it:
                children = [
                    Path(de.path)
                    for de in it
                    if de.is_dir(follow_symlinks=False)
                    and not de.name.startswith(".")
                ]
        except OSError:
            continue
        for child in children:
            # Dir-only spec patterns ("node_modules/") don't match the bare
            # dir path — probe with a trailing slash so ignored subtrees are
            # pruned whole, not just their contents.
            rel_child = child.relative_to(repo_path).as_posix()
            if hasattr(ignore_spec, "match_file"):
                if ignore_spec.match_file(rel_child + "/"):
                    continue
            elif should_ignore_path(
                child, repo_path, ignore_spec, include_hidden=True
            ):
                continue
            stack.append(child)


@dataclass
class WatchEntry:
    """Tracking state for a watched repository."""

    repo_name: str
    path: Path
    debounce_ms: int = 2000
    max_file_size_kb: int | None = None
    # Resolved watch knobs (per-repo registry field -> batho.yaml watch: -> default)
    mode: str = "fs"  # resolved: git | fs | off
    max_staleness_ms: int = 60_000
    flush_threshold: int = 300
    git_settle_ms: int = 300
    vcs_op_hold_ms: int = 30_000
    git_dir: Path | None = None
    common_dir: Path | None = None
    last_synced: float | None = None  # Unix timestamp
    sync_state: str = "idle"  # idle | pending | patching | error
    pending_files: set[str] = field(default_factory=set)
    inflight_files: set[str] = field(default_factory=set)
    first_pending_ts: float | None = None  # when pending went 0 -> non-empty
    boundary_pending: bool = False  # git boundary awaiting settle
    dirty: bool = False  # observer anomaly — assume events were lost
    hold_started_ts: float | None = None  # VCS-op hold entry time
    last_flush_reason: str | None = None
    patch_runs: int = 0  # successful patch completions — monotonic
    observer: Any | None = None  # watchdog Observer (worktree)
    git_observer: Any | None = None  # watchdog Observer (git dir sentinels)
    debounce_timer: threading.Timer | None = None
    staleness_timer: threading.Timer | None = None
    settle_timer: threading.Timer | None = None
    hold_timer: threading.Timer | None = None
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
            try:
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
            except Exception:
                # Events are hints, not truth — a failed event means the
                # tree may have changed without us seeing it. Re-scan.
                self.engine._on_anomaly(self.repo_name)

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
            entries = [e for e in self.registry.list_all() if e.watch]
        # watch() does slow work (git subprocess, observer joins) and must not
        # run under self._lock — that would stall event delivery for all repos.
        for entry in entries:
            self.watch(entry)

    def watch(self, entry: RepoEntry) -> None:
        """Register a watcher for `entry`. Requires ``self._running``.

        Called by ``start()`` for every ``watch=True`` registry entry and by
        ``add_repo`` (tools.py) when a repo is registered while the engine is
        already running. No-ops if ``stop()`` raced it.
        """
        # Lazy import: only require watchdog when actually starting a watch.
        FileSystemEventHandler, _FileSystemEvent, Observer = _require_watchdog()

        # Slow, side-effect-free work happens BEFORE self._lock: config load
        # and resolve_git_dir's `git rev-parse` subprocesses must not block
        # _on_change for every other watched repo.
        repo_path = Path(entry.path).resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            LOGGER.warning("watcher_path_not_found", repo=entry.name, path=str(repo_path))
            return

        watch_cfg = _watch_cfg(repo_path)
        # Precedence: explicit per-repo fs/off wins; "auto" (the registry
        # default) means "not explicitly overridden" and inherits the global
        # watch.mode (batho.yaml / BATHO_WATCH_MODE). Explicit per-repo "auto"
        # is indistinguishable from unset but equivalent anyway — auto is also
        # the global default.
        watch_mode = getattr(entry, "watch_mode", None) or ""
        if watch_mode not in ("fs", "off"):
            watch_mode = str(watch_cfg.get("mode", "auto"))
            if watch_mode not in ("auto", "fs", "off"):
                watch_mode = "auto"

        git_dir: Path | None = None
        common_dir: Path | None = None
        resolved_mode = watch_mode
        if watch_mode == "auto":
            from batho.modules.graph.incremental import resolve_git_dir

            resolved = resolve_git_dir(repo_path)
            if resolved is not None:
                git_dir, common_dir = resolved
                resolved_mode = "git"
            else:
                resolved_mode = "fs"

        ignore_spec = _repo_ignore_spec(repo_path)
        watch_entry = WatchEntry(
            repo_name=entry.name,
            path=repo_path,
            debounce_ms=entry.debounce_ms,
            max_file_size_kb=entry.max_file_size_kb,
            mode=resolved_mode,
            max_staleness_ms=(
                entry.max_staleness_ms
                if getattr(entry, "max_staleness_ms", None) is not None
                else int(watch_cfg.get("max_staleness_ms", 60_000))
            ),
            # Clamp to the queue cap — a larger threshold could never fire.
            flush_threshold=min(
                (
                    entry.flush_threshold
                    if getattr(entry, "flush_threshold", None) is not None
                    else int(watch_cfg.get("flush_threshold", 300))
                ),
                _PENDING_FILES_CAP,
            ),
            git_settle_ms=int(watch_cfg.get("git_settle_ms", 300)),
            vcs_op_hold_ms=int(watch_cfg.get("vcs_op_hold_ms", 30_000)),
            git_dir=git_dir,
            common_dir=common_dir,
            sync_state=entry.sync_state,
            ignore_spec=ignore_spec,
        )

        handler_cls = _make_event_handler_class(FileSystemEventHandler, _FileSystemEvent)
        handler = handler_cls(self, entry.name, repo_path)
        observer = Observer()
        _schedule_worktree_watches(observer, handler, repo_path, ignore_spec)
        observer.daemon = True
        watch_entry.observer = observer

        # Git sentinel layer: boundary events (index/HEAD/refs writes)
        # become flush triggers. Non-recursive on the gitdir roots catches
        # top-level sentinels and creation of in-progress dirs; recursive
        # on refs/ only — objects/, logs/, hooks/ are never watched.
        git_observer = None
        if resolved_mode == "git" and git_dir is not None:
            sent_cls = git_sentinel.make_sentinel_handler(FileSystemEventHandler)
            sent_handler = sent_cls(self, entry.name)
            git_observer = Observer()
            scheduled: set[tuple[str, bool]] = set()
            for base, recursive in (
                (git_dir, False),
                (common_dir, False),
                (git_dir / "refs", True),
                (common_dir / "refs", True),
            ):
                if base is None:
                    continue
                resolved_base = base.resolve()
                key = (str(resolved_base), recursive)
                if key in scheduled or not resolved_base.is_dir():
                    continue
                scheduled.add(key)
                git_observer.schedule(sent_handler, str(resolved_base), recursive=recursive)
            git_observer.daemon = True
            watch_entry.git_observer = git_observer

        # Register under the lock, then join a replaced watch's observers and
        # start the new ones outside it — dispatch threads block on self._lock,
        # so joining while holding it stalls event delivery engine-wide.
        with self._lock:
            if not self._running:
                # stop() raced watch() — don't install a zombie watch.
                LOGGER.debug("watcher_skip_not_running", repo=entry.name)
                return
            live = self.registry.get(entry.name)
            if live is None or not live.watch:
                # remove_repo raced us — the registry entry is gone (or
                # watch was flipped off) while we resolved outside the lock;
                # unwatch()'s pop already ran and would never see this watch.
                LOGGER.debug("watcher_skip_unregistered", repo=entry.name)
                return
            old = self._watches.pop(entry.name, None)
            if old is not None:
                for attr in ("debounce_timer", "staleness_timer", "settle_timer", "hold_timer"):
                    timer = getattr(old, attr)
                    if timer is not None:
                        timer.cancel()
            self._watches[entry.name] = watch_entry

        if old is not None:
            for obs in (old.observer, old.git_observer):
                if obs is not None:
                    try:
                        obs.stop()
                        obs.join(timeout=2.0)
                    except Exception as exc:
                        LOGGER.warning("watcher_stop_error", repo=entry.name, error=str(exc))

        try:
            observer.start()
            if git_observer is not None:
                git_observer.start()
        except Exception as exc:
            with self._lock:
                if self._watches.get(entry.name) is watch_entry:
                    self._watches.pop(entry.name)
            for obs in (observer, git_observer):
                if obs is not None:
                    try:
                        obs.stop()
                    except Exception:
                        pass
            LOGGER.warning("watcher_start_failed", repo=entry.name, error=str(exc))
            return

        # unwatch() may have raced the startup window — don't leave observer
        # threads running for a repo that is no longer registered.
        with self._lock:
            still_registered = self._watches.get(entry.name) is watch_entry
        if not still_registered:
            for obs in (observer, git_observer):
                if obs is not None:
                    try:
                        obs.stop()
                        obs.join(timeout=2.0)
                    except Exception:
                        pass
            return

        LOGGER.info(
            "watcher_started",
            repo=entry.name,
            path=str(repo_path),
            debounce_ms=entry.debounce_ms,
            mode=resolved_mode,
        )

    def unwatch(self, repo_name: str) -> None:
        """Stop watching a specific repo."""
        # Pop the watch entry and cancel its timers under the lock, but
        # stop/join the observers *outside* the lock.  The watchdog observer
        # thread calls _on_change which acquires self._lock; if we hold
        # self._lock while waiting for observer.stop()/join() we deadlock
        # with the observer thread.
        with self._lock:
            watch = self._watches.pop(repo_name, None)
            if not watch:
                return

            for attr in ("debounce_timer", "staleness_timer", "settle_timer", "hold_timer"):
                timer = getattr(watch, attr)
                if timer is not None:
                    timer.cancel()
                    setattr(watch, attr, None)

            observer = watch.observer
            watch.observer = None
            git_observer = watch.git_observer
            watch.git_observer = None

        # Stop and join the observers outside self._lock so the observer's
        # event-dispatch thread (which may be blocked in _on_change waiting
        # for self._lock) can drain and exit.
        for obs in (observer, git_observer):
            if obs is not None:
                try:
                    obs.stop()
                    obs.join(timeout=2.0)
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

    def _arm_timer(self, watch: WatchEntry, attr: str, delay_ms: int, reason: str) -> None:
        """(Re)arm a named daemon timer to fire _run_patch. Caller holds self._lock."""
        old = getattr(watch, attr)
        if old is not None:
            old.cancel()
        timer = threading.Timer(
            max(delay_ms, 0) / 1000.0,
            self._run_patch,
            args=(watch.repo_name,),
            kwargs={"reason": reason},
        )
        timer.daemon = True
        setattr(watch, attr, timer)
        timer.start()

    def _ensure_pending_timers_locked(self, watch: WatchEntry) -> None:
        """Guarantee live debounce + staleness timers while work remains.

        Caller holds self._lock. Used after a patch completes with a non-empty
        queue (events arrived mid-patch).
        """
        if watch.mode == "off":
            return
        if watch.first_pending_ts is None:
            watch.first_pending_ts = time.monotonic()
        if watch.staleness_timer is None or not watch.staleness_timer.is_alive():
            # Arm for the time REMAINING until first_pending_ts + bound, not a
            # fresh window — otherwise every patch cycle would stretch the
            # staleness guarantee by its own duration.
            elapsed_ms = (time.monotonic() - watch.first_pending_ts) * 1000.0
            remaining_ms = max(0.0, watch.max_staleness_ms - elapsed_ms)
            self._arm_timer(watch, "staleness_timer", int(remaining_ms), "staleness")
        if watch.debounce_timer is None or not watch.debounce_timer.is_alive():
            self._arm_timer(watch, "debounce_timer", watch.debounce_ms, "debounce")

    def _on_change(self, repo_name: str, rel_path: str, full_path: Path) -> None:
        """Callback from file watcher — adds to pending and schedules a flush."""
        # Hidden-path short-circuit BEFORE the engine lock: include_hidden=True
        # ignores any dot-prefixed component, so .git/.batho storm events never
        # need the lock or the full spec match.
        if _is_hidden_path(rel_path):
            return

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

            if len(watch.pending_files) < _PENDING_FILES_CAP:
                watch.pending_files.add(rel_path)
            else:
                # Queue saturated — flag dirty so the next flush still runs a
                # full scan; the dropped path is absent from status only.
                watch.dirty = True
            if watch.first_pending_ts is None:
                watch.first_pending_ts = time.monotonic()
                if watch.mode != "off":
                    self._arm_timer(watch, "staleness_timer", watch.max_staleness_ms, "staleness")
            if watch.sync_state != "pending":
                watch.sync_state = "pending"
                self.registry.update_sync_state(repo_name, "pending")

            if watch.mode == "off":
                return  # track state for banners/status; never auto-patch

            # Compound trigger: flush immediately when the queue crosses the
            # threshold; otherwise trailing-edge debounce.
            if len(watch.pending_files) >= watch.flush_threshold:
                self._arm_timer(watch, "debounce_timer", 0, "threshold")
                return
            self._arm_timer(watch, "debounce_timer", watch.debounce_ms, "debounce")

    def _on_git_event(self, repo_name: str, full_path: Path, is_dir: bool, event_type: str) -> None:
        """Callback from the git sentinel observer — boundary events flush the queue."""
        # Compute the VCS-op predicate BEFORE the engine-wide lock: it performs
        # filesystem stat() calls on .git that can stall on a slow/broken FS
        # and would block every repo's event delivery. Re-evaluated each
        # event, so a pre-lock read is equivalent.
        watch = self._watches.get(repo_name)
        vcs_clear = (
            watch is not None
            and watch.hold_started_ts is not None
            and watch.git_dir is not None
            and not git_sentinel.vcs_op_in_progress(watch.git_dir, watch.common_dir)
        )
        with self._lock:
            watch = self._watches.get(repo_name)
            if not watch or not self._running or watch.git_dir is None:
                return
            rel = None
            for base in (watch.git_dir, watch.common_dir):
                if base is None:
                    continue
                try:
                    rel = full_path.relative_to(base).as_posix()
                    break
                except ValueError:
                    continue
            if rel is None:
                return
            kind = git_sentinel.classify(rel, is_dir=is_dir, event_type=event_type)
            if kind == "boundary":
                watch.boundary_pending = True
                if watch.mode != "off":
                    self._arm_timer(watch, "settle_timer", watch.git_settle_ms, "boundary")
            elif (
                kind == "lock"
                and event_type == "deleted"
                and watch.hold_started_ts is not None
                and vcs_clear
            ):
                # A lock-file removal event while a hold is recorded — the
                # operation has ended; clear the hold so status and banners
                # stop reporting it before the next flush runs. In-progress
                # dir removals are already boundaries; other event kinds can't
                # end a hold, so they skip the predicate's stat() calls.
                watch.hold_started_ts = None

    def _on_anomaly(self, repo_name: str) -> None:
        """Observer/handler anomaly — schedule a patch; scan_changes reconciles truth."""
        with self._lock:
            watch = self._watches.get(repo_name)
            if not watch or not self._running:
                return
            watch.dirty = True
            if watch.sync_state == "idle":
                watch.sync_state = "pending"
                self.registry.update_sync_state(repo_name, "pending")
            if watch.mode == "off" or watch.sync_state == "patching":
                return
            self._arm_timer(watch, "debounce_timer", watch.debounce_ms, "anomaly")

    def _run_patch(self, repo_name: str, reason: str = "manual") -> None:
        """Run batho patch for the repo and clear pending files on success."""
        # Compute the VCS-op predicate BEFORE the engine-wide lock: it performs
        # filesystem stat() calls on .git that can stall on a slow/broken FS
        # and would block every repo's event delivery. The predicate is
        # re-evaluated on each firing, so a pre-lock read is equivalent.
        watch = self._watches.get(repo_name)
        vcs_hold = (
            watch is not None
            and watch.mode == "git"
            and watch.git_dir is not None
            and git_sentinel.vcs_op_in_progress(watch.git_dir, watch.common_dir)
        )
        with self._lock:
            watch = self._watches.get(repo_name)
            if not watch:
                return

            # VCS-op hold (git mode): defer flushes while a composite git op is
            # mid-flight (rebase writes the index dozens of times). Age-capped
            # so a stale index.lock after a crash can't starve the queue; lock
            # files are never deleted or touched.
            if (
                watch.mode == "git"
                and watch.git_dir is not None
                and vcs_hold
            ):
                now = time.monotonic()
                if watch.hold_started_ts is None:
                    watch.hold_started_ts = now
                    LOGGER.info("watcher_vcs_hold_start", repo=repo_name)
                if (now - watch.hold_started_ts) * 1000.0 < watch.vcs_op_hold_ms:
                    self._arm_timer(watch, "hold_timer", max(watch.git_settle_ms, 500), reason)
                    return
                LOGGER.warning(
                    "watcher_vcs_hold_expired",
                    repo=repo_name,
                    hold_ms=watch.vcs_op_hold_ms,
                )
            watch.hold_started_ts = None

            # Move the queue aside so events arriving mid-patch re-pend rather
            # than being silently cleared on success. first_pending_ts is kept
            # so the staleness bound still measures from the oldest unindexed
            # change (inflight + newly pending alike).
            watch.inflight_files = watch.pending_files
            watch.pending_files = set()
            had_boundary = watch.boundary_pending
            had_dirty = watch.dirty
            watch.boundary_pending = False
            watch.dirty = False
            for attr in ("staleness_timer", "debounce_timer", "settle_timer", "hold_timer"):
                timer = getattr(watch, attr)
                if timer is not None:
                    timer.cancel()
                    setattr(watch, attr, None)

            # A stale timer (e.g. a hold timer that outlived its flush) firing
            # with nothing queued must not trigger an O(repo) no-op scan.
            # manual/catchup always run — they carry their own reason to scan.
            if (
                reason not in ("manual", "catchup")
                and not (watch.inflight_files or had_boundary or had_dirty)
            ):
                # Only a pending run may be downgraded — a concurrent patch
                # or a previously recorded failure owns the state; a stale
                # timer must not clobber "patching"/"error" back to "idle".
                if watch.sync_state == "pending":
                    watch.sync_state = "idle"
                    watch.first_pending_ts = None
                    self.registry.update_sync_state(repo_name, "idle")
                return

            watch.sync_state = "patching"
            watch.last_flush_reason = reason
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
                res = patch_mod.run_patch(options)
                # run_patch reports failure through PatchResult, not by
                # raising — a clean failure (missing bundle, internal error)
                # must NOT take the success path and silently drop the queue.
                if not getattr(res, "success", False):
                    raise RuntimeError(
                        "; ".join(getattr(res, "warnings", None) or []) or "patch failed"
                    )

        except Exception as exc:
            with self._lock:
                # Skip state updates if the repo was unwatched mid-patch —
                # arming timers on a detached WatchEntry would leak them
                # (Timer stores only repo_name and re-resolves the watch).
                if self._watches.get(repo_name) is watch:
                    # Restore the consumed queue AND the consumed triggers —
                    # a boundary/dirty-only flush must not lose its reason
                    # to retry just because the file queue was empty.
                    watch.pending_files |= watch.inflight_files
                    watch.inflight_files = set()
                    watch.boundary_pending |= had_boundary
                    watch.dirty |= had_dirty
                    if (
                        watch.pending_files or watch.boundary_pending or watch.dirty
                    ) and watch.first_pending_ts is None:
                        watch.first_pending_ts = time.monotonic()
                    watch.sync_state = "error"
                    watch.error_message = str(exc)
                    self.registry.update_sync_state(repo_name, "error")
                    # Retry at the staleness cadence — transient failures (lock
                    # contention, mid-write reads) self-heal; persistent ones
                    # surface through the error banner between retries. Uses the
                    # remaining window so the bound still holds across retries.
                    if watch.mode != "off" and (
                        watch.pending_files or watch.boundary_pending or watch.dirty
                    ):
                        elapsed_ms = (time.monotonic() - watch.first_pending_ts) * 1000.0
                        remaining_ms = max(0.0, watch.max_staleness_ms - elapsed_ms)
                        self._arm_timer(watch, "staleness_timer", int(remaining_ms), "staleness")
            LOGGER.error("watcher_patch_failed", repo=repo_name, error=str(exc))
            return

        iso_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        now_ts = time.time()
        with self._lock:
            if self._watches.get(repo_name) is not watch:
                # Unwatched mid-patch — the artifact was still written, so
                # invalidate readers below but skip detached-watch updates.
                LOGGER.info("watcher_patch_detached", repo=repo_name, synced_at=iso_ts)
            else:
                watch.inflight_files = set()
                watch.error_message = None
                watch.patch_runs += 1
                if watch.pending_files or watch.boundary_pending or watch.dirty:
                    # Events landed while the patch ran — stay pending; their
                    # timers were already armed by _on_change/_on_git_event.
                    watch.sync_state = "pending"
                    self.registry.update_sync_state(repo_name, "pending", last_synced=iso_ts)
                    self._ensure_pending_timers_locked(watch)
                else:
                    watch.sync_state = "idle"
                    watch.last_synced = now_ts
                    watch.first_pending_ts = None
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
            return rel_path in watch.pending_files or rel_path in watch.inflight_files

    def get_staleness_banner(self, repo_name: str, file_path: str | None = None) -> str | None:
        """Return a staleness warning string if the repo or file is pending."""
        with self._lock:
            watch = self._watches.get(repo_name)
            if not watch:
                return None
            if watch.sync_state == "patching":
                return "⚠️ Artifact is currently being re-patched. Results may be stale."
            if watch.mode == "git" and watch.hold_started_ts is not None:
                return "⚠️ Git operation in progress — re-index deferred."
            if file_path and file_path in watch.pending_files:
                return f"⚠️ File `{file_path}` is pending re-index. Read it directly for the live content."
            if watch.sync_state == "pending":
                count = len(watch.pending_files)
                if count:
                    return f"⚠️ {count} file{'s' if count != 1 else ''} pending re-index. Results may be stale."
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
                    "mode": watch.mode,
                    "sync_state": watch.sync_state,
                    "pending_files": list(watch.pending_files),
                    "pending_count": len(watch.pending_files),
                    "inflight_count": len(watch.inflight_files),
                    "oldest_pending_age_s": (
                        round(time.monotonic() - watch.first_pending_ts, 1)
                        if watch.first_pending_ts is not None
                        else 0
                    ),
                    "last_synced": watch.last_synced,
                    "last_flush_reason": watch.last_flush_reason,
                    "patch_runs": watch.patch_runs,
                    "vcs_op_hold": watch.hold_started_ts is not None,
                    "error_message": watch.error_message,
                    "debounce_ms": watch.debounce_ms,
                }
            return res

    def catch_up(self, repo_name: str) -> None:
        """Patch-on-connect: check if files changed while server was down."""
        entry = self.registry.get(repo_name)
        if not entry:
            return
        with self._lock:
            watch = self._watches.get(repo_name)
        if watch is not None:
            mode = watch.mode
        else:
            # No watch registered (engine not started / watch skipped) —
            # fall back to the declared mode for the off check: per-repo
            # override → global watch.mode, same precedence as watch().
            repo_path = Path(entry.path).resolve()
            watch_cfg = _watch_cfg(repo_path)
            mode = getattr(entry, "watch_mode", None) or ""
            if mode not in ("fs", "off"):
                mode = str(watch_cfg.get("mode", "auto"))
                if mode not in ("auto", "fs", "off"):
                    mode = "auto"
        if mode == "off":
            # "off" means never auto-patch — patch-on-connect included.
            return
        artifact_dir = entry.artifact_dir
        if not artifact_dir.exists():
            return

        try:
            from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
            reader = BathoBundleReader(artifact_dir)
            ft_table = reader._get_table("file_tracking")

            repo_path = Path(entry.path).resolve()
            ignore_spec = _repo_ignore_spec(repo_path)
            
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
                self._run_patch(repo_name, reason="catchup")
        except Exception as exc:
            LOGGER.warning("watcher_catch_up_error", repo=repo_name, error=str(exc))
