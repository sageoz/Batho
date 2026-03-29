"""
File locking utilities for atomic file operations.

Provides cross-platform file locking with timeout and stale lock detection.
"""

import os
import time
import errno
import psutil
from pathlib import Path
from contextlib import contextmanager
from typing import Optional
from batho_core.utils.logging import get_logger

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
    
    def __init__(self, lock_path: Path, timeout: float = 30.0, poll_interval: float = 0.1):
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
        try:
            return psutil.pid_exists(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            return False
    
    def _read_lock_info(self) -> Optional[tuple[int, float]]:
        """
        Read lock file information.
        
        Returns:
            Tuple of (pid, timestamp) if lock file exists and is valid, None otherwise
        """
        try:
            if not self.lock_path.exists():
                return None
                
            content = self.lock_path.read_text(encoding='utf-8').strip()
            if not content:
                return None
                
            parts = content.split(':')
            if len(parts) != 2:
                return None
                
            pid_str, timestamp_str = parts
            return int(pid_str), float(timestamp_str)
            
        except (OSError, ValueError) as e:
            logger.debug("invalid_lock_file", lock_path=str(self.lock_path), error=str(e))
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
        # Check if process is still alive
        if not self._is_process_alive(pid):
            logger.debug("stale_lock_dead_process", pid=pid)
            return True
            
        # Check if lock is too old (more than 5 minutes)
        age = time.time() - timestamp
        if age > 300:  # 5 minutes
            logger.debug("stale_lock_too_old", pid=pid, age_seconds=age)
            return True
            
        return False
    
    def _cleanup_stale_lock(self) -> bool:
        """
        Clean up stale lock file if present.
        
        Returns:
            True if stale lock was cleaned up, False otherwise
        """
        lock_info = self._read_lock_info()
        if lock_info is None:
            return False
            
        pid, timestamp = lock_info
        if self._is_lock_stale(pid, timestamp):
            try:
                self.lock_path.unlink()
                logger.info("cleaned_stale_lock", lock_path=str(self.lock_path), pid=pid)
                return True
            except OSError as e:
                logger.warning("failed_to_clean_stale_lock", lock_path=str(self.lock_path), error=str(e))
                return False
                
        return False
    
    def acquire(self) -> bool:
        """
        Acquire the file lock.
        
        Returns:
            True if lock acquired successfully, False otherwise
        """
        if self._locked:
            return True  # Already locked by this instance
            
        start_time = time.time()
        cleanup_attempted = False
        
        while time.time() - start_time < self.timeout:
            # Only attempt cleanup once per acquisition attempt to avoid infinite recursion
            if not cleanup_attempted:
                was_cleaned = self._cleanup_stale_lock()
                cleanup_attempted = True
                if was_cleaned:
                    # Give a brief moment after cleanup before attempting acquisition
                    time.sleep(0.01)
            
            try:
                # Try to create lock file atomically
                pid = os.getpid()
                timestamp = time.time()
                lock_content = f"{pid}:{timestamp}"
                
                # Use O_CREAT | O_EXCL for atomic creation
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, lock_content.encode('utf-8'))
                finally:
                    os.close(fd)
                
                self._locked = True
                logger.debug("lock_acquired", lock_path=str(self.lock_path), pid=pid)
                return True
                
            except OSError as e:
                if e.errno != errno.EEXIST:  # File exists (lock held by someone else)
                    logger.error("lock_creation_failed", lock_path=str(self.lock_path), error=str(e))
                    raise FileLockError(f"Failed to create lock file: {e}")
                
                # Lock exists, check if it's stale before waiting
                lock_info = self._read_lock_info()
                if lock_info:
                    pid, timestamp = lock_info
                    if self._is_lock_stale(pid, timestamp):
                        # Try to clean up the stale lock immediately
                        if self._cleanup_stale_lock():
                            time.sleep(0.01)  # Brief delay before retry
                            continue  # Retry immediately after cleanup
                
                # Lock exists and is not stale, wait and retry
                logger.debug("lock_busy", lock_path=str(self.lock_path))
                time.sleep(self.poll_interval)
                
        # Timeout reached
        lock_info = self._read_lock_info()
        if lock_info:
            pid, timestamp = lock_info
            logger.error("lock_timeout", lock_path=str(self.lock_path), timeout=self.timeout, 
                        holding_pid=pid, lock_age=time.time() - timestamp)
        else:
            logger.error("lock_timeout", lock_path=str(self.lock_path), timeout=self.timeout)
            
        raise FileLockError(f"Failed to acquire lock {self.lock_path} within {self.timeout} seconds")
    
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
                    self.lock_path.unlink()
                    logger.debug("lock_released", lock_path=str(self.lock_path), pid=pid)
                else:
                    logger.warning("lock_not_owned", lock_path=str(self.lock_path), 
                                 owner_pid=pid, our_pid=os.getpid())
            else:
                logger.warning("lock_file_disappeared", lock_path=str(self.lock_path))
                
        except OSError as e:
            logger.error("lock_release_failed", lock_path=str(self.lock_path), error=str(e))
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
