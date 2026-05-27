"""
File locking utilities for atomic file operations.

Provides cross-platform file locking with timeout and stale lock detection.
"""

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

try:
    import psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False

from batho.utils.logging import get_logger

logger = get_logger(__name__, component="file_lock")


class FileLockError(Exception):
    """Raised when file locking fails."""

    pass  # Required for exception class definition


class FileLock:
    """
    Cross-platform file lock with timeout and stale lock detection.

    Uses lock files with PID and timestamp for robust locking.
    Automatically detects and cleans up stale locks from dead processes.
    """

    def __init__(
        self, lock_path: Path, timeout: float = 30.0, poll_interval: float = 0.1
    ):
        """
        Initialize file lock.

        Args:
            lock_path: Path to the lock file (usually .lock extension)
            timeout: Maximum time to wait for lock acquisition (seconds)
            poll_interval: Time between lock attempts (seconds)
        """
        self.lock_path = lock_path
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._locked = False

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process with given PID is still alive."""
        if _PSUTIL_AVAILABLE and psutil is not None:
            try:
                return psutil.pid_exists(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                return False

        if os.name == "posix":
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
        if os.name == "nt":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                process = kernel32.OpenProcess(0x00100000, 0, pid)  # SYNCHRONIZE
                if process != 0:
                    kernel32.CloseHandle(process)
                    return True
                return False
            except Exception:
                return True
        return True

    def _read_lock_info(self) -> Optional[tuple[int, float]]:
        """
        Read lock file information.

        Returns:
            Tuple of (pid, timestamp) if lock file exists and is valid, None otherwise
        """
        try:
            if not self.lock_path.exists():
                return None

            content = self.lock_path.read_text(encoding="utf-8").strip()
            if not content:
                return None

            parts = content.split(":")
            if len(parts) != 2:
                return None

            pid_str, timestamp_str = parts
            pid = int(pid_str)
            timestamp = float(timestamp_str)

            # Reject hostile/garbage payloads:
            #   - non-positive or unreasonably large PIDs
            #   - NaN / inf timestamps
            #   - timestamps in the far future or far past (>1 day skew)
            import math

            if pid <= 0 or pid > 2**31:
                return None
            if not math.isfinite(timestamp):
                return None
            if abs(timestamp - time.time()) > 86400.0:
                return None

            return pid, timestamp

        except (OSError, ValueError) as e:
            logger.debug(
                "invalid_lock_file", lock_path=str(self.lock_path), error=str(e)
            )
            return None

    def _is_lock_stale(self, pid: int, timestamp: float) -> bool:
        """
        Check if a lock is stale (process dead or too old).

        Args:
            pid: Process ID that created the lock
            timestamp: Lock creation timestamp

        Returns:
            True if lock is stale, False otherwise
        """
        if self._is_process_alive(pid):
            if _PSUTIL_AVAILABLE and psutil is not None:
                try:
                    proc = psutil.Process(pid)
                    # If process was created after the lock, it's a recycled PID
                    if proc.create_time() > timestamp:
                        logger.debug("stale_lock_pid_reused", pid=pid)
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                    return True

            # Fallback age threshold check to prevent deadlocks from PID reuse when psutil is not available
            # or if the process has been running/hung for an unreasonably long time (e.g. 10 minutes)
            if time.time() - timestamp > 600.0:
                logger.debug("stale_lock_timeout", pid=pid, age=time.time() - timestamp)
                return True

            return False

        logger.debug("stale_lock_dead_process", pid=pid)
        return True

    def _lock_file_descriptor(self, fd: int) -> bool:
        if os.name == "posix":
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False
        elif os.name == "nt":
            import msvcrt
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        return True

    def _unlock_file_descriptor(self, fd: int) -> None:
        if os.name == "posix":
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        elif os.name == "nt":
            import msvcrt
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

    def _cleanup_stale_lock(self) -> bool:
        """
        Clean up stale lock file if present.

        Uses advisory locking to prevent race conditions during cleanup.
        """
        try:
            fd = os.open(self.lock_path, os.O_RDWR)
        except FileNotFoundError:
            return False
        except OSError:
            return False

        try:
            if not self._lock_file_descriptor(fd):
                return False

            try:
                os.lseek(fd, 0, os.SEEK_SET)
                content_bytes = os.read(fd, 100)
                content = content_bytes.decode("utf-8").strip()
            except OSError:
                return False

            if not content:
                return False

            parts = content.split(":")
            if len(parts) != 2:
                return False

            try:
                pid = int(parts[0])
                timestamp = float(parts[1])
            except ValueError:
                return False

            if not self._is_lock_stale(pid, timestamp):
                return False

            try:
                self.lock_path.unlink()
                logger.info(
                    "cleaned_stale_lock", lock_path=str(self.lock_path), pid=pid
                )
                return True
            except FileNotFoundError:
                return True
            except OSError as e:
                logger.warning(
                    "failed_to_clean_stale_lock",
                    lock_path=str(self.lock_path),
                    error=str(e),
                )
                return False
        finally:
            self._unlock_file_descriptor(fd)
            try:
                os.close(fd)
            except OSError:
                pass

    def acquire(self) -> bool:
        """
        Acquire the file lock.

        Returns:
            True if lock acquired successfully, False otherwise
        """
        if self._locked:
            return True  # Already locked by this instance

        start_time = time.time()

        while time.time() - start_time < self.timeout:
            try:
                # Try to create lock file atomically
                pid = os.getpid()
                timestamp = time.time()
                lock_content = f"{pid}:{timestamp}"

                # Use O_CREAT | O_EXCL for atomic creation
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, lock_content.encode("utf-8"))
                finally:
                    os.close(fd)

                self._locked = True
                logger.debug("lock_acquired", lock_path=str(self.lock_path), pid=pid)
                return True

            except OSError as e:
                if e.errno != errno.EEXIST:  # File exists (lock held by someone else)
                    logger.error(
                        "lock_creation_failed",
                        lock_path=str(self.lock_path),
                        error=str(e),
                    )
                    raise FileLockError(f"Failed to create lock file: {e}")

                # Lock exists — try to clean up if it is stale. ``_cleanup_stale_lock``
                # is self-verifying: it re-reads the payload immediately before
                # ``unlink()`` and aborts if the contents changed, which prevents
                # racing processes from each deleting the other's fresh lock.
                if self._cleanup_stale_lock():
                    # Brief delay so the OS settles before re-trying the open
                    time.sleep(0.01)
                    continue

                # Lock exists and is not stale, wait and retry
                logger.debug("lock_busy", lock_path=str(self.lock_path))
                time.sleep(self.poll_interval)

        # Timeout reached
        lock_info = self._read_lock_info()
        if lock_info:
            pid, timestamp = lock_info
            logger.error(
                "lock_timeout",
                lock_path=str(self.lock_path),
                timeout=self.timeout,
                holding_pid=pid,
                lock_age=time.time() - timestamp,
            )
        else:
            logger.error(
                "lock_timeout", lock_path=str(self.lock_path), timeout=self.timeout
            )

        raise FileLockError(
            f"Failed to acquire lock {self.lock_path} within {self.timeout} seconds"
        )

    def release(self) -> None:
        """Release the file lock."""
        if not self._locked:
            return  # Not locked by this instance

        try:
            # Verify we own the lock
            lock_info = self._read_lock_info()
            if lock_info:
                pid, _ = lock_info
                if pid == os.getpid():
                    try:
                        self.lock_path.unlink()
                    except (PermissionError, OSError) as e:
                        logger.warning(
                            "lock_unlink_failed",
                            lock_path=str(self.lock_path),
                            error=str(e),
                        )
                    logger.debug(
                        "lock_released", lock_path=str(self.lock_path), pid=pid
                    )
                else:
                    logger.warning(
                        "lock_not_owned",
                        lock_path=str(self.lock_path),
                        owner_pid=pid,
                        our_pid=os.getpid(),
                    )
            else:
                logger.warning("lock_file_disappeared", lock_path=str(self.lock_path))

        except (PermissionError, OSError) as e:
            logger.error(
                "lock_release_failed", lock_path=str(self.lock_path), error=str(e)
            )
        finally:
            self._locked = False

    def __enter__(self):
        """Context manager entry."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()

    def __del__(self):
        """Destructor to ensure lock is released."""
        if self._locked:
            self.release()


@contextmanager
def file_lock(lock_path: Path, timeout: float = 30.0):
    """
    Context manager for file locking.

    Args:
        lock_path: Path to the lock file
        timeout: Maximum time to wait for lock acquisition

    Usage:
        with file_lock(Path("cache.json.lock")):
            # Atomic operations on cache.json
            pass
    """
    lock = FileLock(lock_path, timeout=timeout)
    try:
        lock.acquire()
        yield lock
    finally:
        lock.release()
