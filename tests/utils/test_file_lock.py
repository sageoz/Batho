"""Tests for batho_core.utils.file_lock."""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path

import pytest

from batho_core.utils.file_lock import FileLock, FileLockError, file_lock


class TestFileLockInternal:

    def test_read_lock_info_missing_and_invalid(self, tmp_path: Path):
        lock_path = tmp_path / "x.lock"
        lock = FileLock(lock_path)
        assert lock._read_lock_info() is None

        lock_path.write_text("invalid")
        assert lock._read_lock_info() is None

    def test_read_lock_info_valid(self, tmp_path: Path):
        lock_path = tmp_path / "x.lock"
        lock_path.write_text("123:456.0")
        lock = FileLock(lock_path)
        assert lock._read_lock_info() == (123, 456.0)

    def test_is_lock_stale_dead_process(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        lock = FileLock(tmp_path / "x.lock")
        monkeypatch.setattr(lock, "_is_process_alive", lambda _pid: False)
        assert lock._is_lock_stale(999999, time.time()) is True

    def test_is_lock_stale_old_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        lock = FileLock(tmp_path / "x.lock")
        monkeypatch.setattr(lock, "_is_process_alive", lambda _pid: True)
        assert lock._is_lock_stale(os.getpid(), time.time() - 301) is True

    def test_cleanup_stale_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        lock_path = tmp_path / "x.lock"
        lock_path.write_text("12345:0.0")
        lock = FileLock(lock_path)

        monkeypatch.setattr(lock, "_is_lock_stale", lambda _pid, _ts: True)
        assert lock._cleanup_stale_lock() is True
        assert not lock_path.exists()

    def test_is_process_alive_handles_psutil_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        lock = FileLock(tmp_path / "x.lock")

        monkeypatch.setattr(
            "batho_core.utils.file_lock.psutil.pid_exists",
            lambda _pid: (_ for _ in ()).throw(ValueError("bad pid")),
        )
        assert lock._is_process_alive(1) is False

    def test_cleanup_stale_lock_handles_unlink_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        lock_path = tmp_path / "stale.lock"
        lock_path.write_text("1:0.0")
        lock = FileLock(lock_path)

        monkeypatch.setattr(lock, "_is_lock_stale", lambda _pid, _ts: True)
        monkeypatch.setattr(
            Path,
            "unlink",
            lambda self: (_ for _ in ()).throw(OSError("unlink failed")),
        )

        assert lock._cleanup_stale_lock() is False


class TestFileLockAcquireRelease:

    def test_acquire_and_release(self, tmp_path: Path):
        lock_path = tmp_path / "x.lock"
        lock = FileLock(lock_path, timeout=0.2, poll_interval=0.01)

        assert lock.acquire() is True
        assert lock_path.exists()
        assert lock._locked is True

        lock.release()
        assert lock._locked is False
        assert not lock_path.exists()

    def test_acquire_when_already_locked(self, tmp_path: Path):
        lock = FileLock(tmp_path / "x.lock", timeout=0.2)
        assert lock.acquire() is True
        assert lock.acquire() is True
        lock.release()

    def test_timeout_when_lock_held(self, tmp_path: Path):
        lock_path = tmp_path / "x.lock"
        lock_path.write_text(f"{os.getpid()}:{time.time()}")
        lock = FileLock(lock_path, timeout=0.05, poll_interval=0.01)

        with pytest.raises(FileLockError):
            lock.acquire()

    def test_stale_lock_is_cleaned_and_acquired(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        lock_path = tmp_path / "x.lock"
        lock_path.write_text("999999:0.0")
        lock = FileLock(lock_path, timeout=0.2, poll_interval=0.01)

        monkeypatch.setattr(lock, "_is_process_alive", lambda _pid: False)
        assert lock.acquire() is True
        lock.release()

    def test_acquire_raises_on_non_eexist_oserror(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        lock = FileLock(tmp_path / "fail.lock", timeout=0.1, poll_interval=0.01)

        monkeypatch.setattr(
            "batho_core.utils.file_lock.os.open",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(errno.EPERM, "denied")),
        )

        with pytest.raises(FileLockError):
            lock.acquire()

    def test_acquire_retries_after_detecting_stale_existing_lock(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        lock = FileLock(tmp_path / "retry.lock", timeout=0.2, poll_interval=0.01)
        original_open = os.open
        calls = {"count": 0}

        def _open(path, flags, *args):
            if calls["count"] == 0:
                calls["count"] += 1
                raise OSError(errno.EEXIST, "exists")
            return original_open(path, flags, *args)

        monkeypatch.setattr(lock, "_read_lock_info", lambda: (os.getpid(), 0.0))
        monkeypatch.setattr(lock, "_is_lock_stale", lambda _pid, _ts: True)
        monkeypatch.setattr(lock, "_cleanup_stale_lock", lambda: True)
        monkeypatch.setattr("batho_core.utils.file_lock.os.open", _open)

        assert lock.acquire() is True
        lock.release()

    def test_release_paths_for_not_owned_missing_and_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        lock_path = tmp_path / "release.lock"
        lock = FileLock(lock_path)

        # Not owned path
        lock._locked = True
        lock_path.write_text("999999:0.0")
        lock.release()
        assert lock._locked is False

        # Lock file disappeared path
        lock._locked = True
        if lock_path.exists():
            lock_path.unlink()
        lock.release()
        assert lock._locked is False

        # Release error path
        lock._locked = True
        lock_path.write_text(f"{os.getpid()}:0.0")
        monkeypatch.setattr(
            Path,
            "unlink",
            lambda self: (_ for _ in ()).throw(OSError("cannot unlink")),
        )
        lock.release()
        assert lock._locked is False

    def test_filelock_magic_methods_and_destructor(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        lock_path = tmp_path / "magic.lock"
        with FileLock(lock_path, timeout=0.2, poll_interval=0.01) as active_lock:
            assert isinstance(active_lock, FileLock)
            assert lock_path.exists()
        assert not lock_path.exists()

        lock = FileLock(tmp_path / "del.lock")
        lock._locked = True
        calls = {"released": 0}
        monkeypatch.setattr(lock, "release", lambda: calls.__setitem__("released", calls["released"] + 1))
        lock.__del__()
        assert calls["released"] == 1

    def test_context_manager(self, tmp_path: Path):
        lock_path = tmp_path / "ctx.lock"
        with file_lock(lock_path, timeout=0.2):
            assert lock_path.exists()
        assert not lock_path.exists()
