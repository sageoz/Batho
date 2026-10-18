"""Git sentinel watching — classify .git-dir events into boundary signals.

The watcher engine schedules a lightweight watchdog observer on the resolved
git dir (``git rev-parse --absolute-git-dir`` / ``--git-common-dir`` — see
``batho.modules.graph.incremental.resolve_git_dir``) and uses this module to
decide which events mark a *logical git boundary* (stage, commit, checkout,
merge, rebase step) worth flushing the pending change queue on.

Sentinel events are triggers, not data — they never enter ``pending_files``;
the patch's hash-diff against ``file_tracking`` remains the source of truth.

Watch shape (per resolved dir): non-recursive on the gitdir root (catches
top-level sentinels AND creation of the in-progress dirs), recursive on
``refs/`` only. ``objects/``, ``logs/``, ``hooks/`` are never watched — no
per-dir inotify cost on ``objects/`` fan-out and gc churn produces no events.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Root-level files whose writes mark a logical git boundary.
BOUNDARY_FILES = frozenset({
    "index",            # staging (git add/rm/commit/reset all write the index)
    "HEAD",             # commit / branch switch
    # NOTE: packed-refs is deliberately excluded — gc/repack rewrites it on a
    # schedule, not a boundary. Ref updates always land as loose refs/** first.
    # NOTE: FETCH_HEAD is excluded too — `git fetch` (incl. IDE auto-fetch)
    # writes it without touching the worktree; `git pull` still flushes via
    # the merge/rebase/index sentinels that follow the fetch.
    "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "AUTO_MERGE",
    "ORIG_HEAD",
    "COMMIT_EDITMSG", "MERGE_MSG",
})

# Directories whose presence means a composite operation is in progress.
IN_PROGRESS_DIRS = frozenset({"rebase-merge", "rebase-apply", "sequencer"})

# Presence of any of these under a git dir means a git mutation is mid-flight.
HOLD_SENTINELS = (
    "index.lock",
    "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
    "rebase-merge", "rebase-apply", "sequencer",
)

# Watcher-tooling noise and heavy internals — never a signal.
_DENY_SUBSTRINGS = (".watchman-cookie-",)
_DENY_PARTS = frozenset({
    "fsmonitor--daemon", "batho", "objects", "logs", "hooks", "info",
    "lfs", "worktrees", "modules",
})


def classify(rel_path: str, is_dir: bool = False, event_type: str = "") -> str:
    """Classify a git-dir-relative path event.

    Returns ``"boundary"`` (flush trigger), ``"lock"`` (VCS-op signal),
    ``"in_progress"`` (op-state dir activity), or ``"ignore"``.
    Deletion of an in-progress dir IS a boundary — the operation ended.
    """
    parts = Path(rel_path).parts
    if not parts:
        return "ignore"
    for p in parts:
        if p in _DENY_PARTS or any(s in p for s in _DENY_SUBSTRINGS):
            return "ignore"
    name = parts[-1]
    if name.endswith(".lock"):
        return "lock"
    if parts[0] in IN_PROGRESS_DIRS:
        if event_type == "deleted" and (is_dir or len(parts) == 1):
            return "boundary"
        return "in_progress"
    if parts[0] == "refs":
        # refs/remotes/** only changes on fetch — remote-tracking refs never
        # touch the worktree, so a boundary flush would scan for nothing.
        if len(parts) > 1 and parts[1] == "remotes":
            return "ignore"
        return "boundary"
    if len(parts) == 1 and parts[0] in BOUNDARY_FILES:
        return "boundary"
    return "ignore"


def vcs_op_in_progress(git_dir: Path | None, common_dir: Path | None) -> bool:
    """True while git holds ``index.lock`` or an in-progress op sentinel exists.

    Checks both the private git dir and the common dir (they differ for linked
    worktrees). Lock files carry no PID and may be stale after a crash — the
    caller is responsible for the age cap; this is a pure presence check.
    """
    for base in {git_dir, common_dir} - {None}:
        for name in HOLD_SENTINELS:
            try:
                if (base / name).exists():
                    return True
            except OSError:
                continue
    return False


def make_sentinel_handler(base_handler_cls: Any) -> Any:
    """Build a watchdog handler subclass routing git-dir events to the engine.

    Factory pattern mirrors ``_make_event_handler_class`` in watcher.py so the
    module imports without watchdog installed.
    """

    class _GitSentinelHandler(base_handler_cls):
        """Routes classified git-dir events to BathoWatcherEngine._on_git_event."""

        def __init__(self, engine: Any, repo_name: str) -> None:
            super().__init__()
            self.engine = engine
            self.repo_name = repo_name

        def on_any_event(self, event: Any) -> None:
            try:
                self.engine._on_git_event(
                    self.repo_name,
                    Path(event.src_path),
                    bool(getattr(event, "is_directory", False)),
                    str(getattr(event, "event_type", "")),
                )
                dest = getattr(event, "dest_path", None)
                if dest and dest != event.src_path:
                    self.engine._on_git_event(
                        self.repo_name,
                        Path(dest),
                        bool(getattr(event, "is_directory", False)),
                        "created",
                    )
            except Exception:
                self.engine._on_anomaly(self.repo_name)

    return _GitSentinelHandler
