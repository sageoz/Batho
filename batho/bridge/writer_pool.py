"""
batho/bridge/writer_pool.py — Bounded SQLite writer connection pool.

Provides a small pool (default 1-2) of write-capable connections that
reuse pragmas applied at creation time. This prevents the per-call
PRAGMA overhead and reduces "database is locked" contention under
concurrent writers (CI parallel jobs, webhook bursts, multiprocessing).

Design notes:
- WAL is bootstrapped once at DB creation (idempotent on subsequent opens).
- Default size is 1 because SQLite serializes writers anyway; larger pools
  are useful only when the same process has multiple writer threads.
- Connections are checked out exclusively; release returns them to the pool.
- Feature-flag friendly: callers can disable the pool with size=0 to fall
  back to per-call connection opening (matches legacy behavior).
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Iterator

from batho.bridge.connection_profile import (
    DurabilityMode,
    apply_writer_pragmas,
    bootstrap_wal,
)
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.writer_pool")


class WriterPoolExhausted(Exception):
    """Raised when writer pool cannot acquire a connection within timeout."""


class WriterPool:
    """
    Bounded pool of write-capable SQLite connections.

    Args:
        db_path: Path to the SQLite database file.
        size: Maximum number of connections in the pool (default 1).
              SQLite serializes writers, so pools >2 are rarely useful.
        durability: "full" for crash-safe artifacts, "normal" for indexes.
        acquire_timeout: Seconds to wait when acquiring (default 5.0).
        bootstrap: When True (default), apply WAL journaling on first connection.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        size: int = 1,
        durability: DurabilityMode = "normal",
        acquire_timeout: float = 5.0,
        bootstrap: bool = True,
        prepopulate: bool = False,
    ) -> None:
        self._db_path = db_path
        self._size = max(1, int(size))
        self._durability = durability
        self._acquire_timeout = acquire_timeout
        self._bootstrap = bootstrap
        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=self._size)
        self._created = 0
        self._lock = threading.Lock()
        self._closed = False
        self._wal_bootstrapped = False
        if prepopulate:
            self._init_pool()

    def _init_pool(self) -> None:
        with self._lock:
            while self._created < self._size:
                try:
                    conn = self._create_connection()
                    self._pool.put_nowait(conn)
                    self._created += 1
                except Exception as exc:
                    LOGGER.warning(
                        "writer_pool_init_failed",
                        db_path=str(self._db_path),
                        error=str(exc),
                    )
                    break

    def _create_connection(self) -> sqlite3.Connection:
        """Create a write-capable connection with shared writer pragmas."""
        conn = sqlite3.connect(
            str(self._db_path), timeout=5, check_same_thread=False
        )
        # Bootstrap WAL once per pool lifetime (idempotent on subsequent opens)
        if self._bootstrap and not self._wal_bootstrapped:
            bootstrap_wal(conn)
            self._wal_bootstrapped = True
        apply_writer_pragmas(conn, durability=self._durability)
        return conn

    def acquire(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("Writer pool is closed")
        try:
            return self._pool.get(timeout=self._acquire_timeout)
        except Empty:
            with self._lock:
                if self._created < self._size:
                    try:
                        conn = self._create_connection()
                        self._created += 1
                        return conn
                    except Exception as exc:
                        raise WriterPoolExhausted(
                            f"Could not acquire writer connection to "
                            f"{self._db_path} within {self._acquire_timeout}s: {exc}"
                        ) from exc
            raise WriterPoolExhausted(
                f"Could not acquire writer connection to {self._db_path} "
                f"within {self._acquire_timeout}s"
            )

    def release(self, conn: sqlite3.Connection) -> None:
        if self._closed:
            try:
                conn.close()
            finally:
                with self._lock:
                    self._created = max(0, self._created - 1)
            return
        
        # Ensure any open transaction is rolled back before returning to pool
        # to prevent leaking locks into other users of the pooled connection.
        try:
            conn.rollback()
        except sqlite3.Error:
            pass

        try:
            self._pool.put_nowait(conn)
        except Full:
            try:
                conn.close()
            finally:
                with self._lock:
                    self._created = max(0, self._created - 1)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for acquiring and releasing a writer connection."""
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def close(self) -> None:
        self._closed = True
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Exception:
                pass
        with self._lock:
            self._created = 0

    @property
    def size(self) -> int:
        return self._size

    @property
    def available(self) -> int:
        return self._pool.qsize()


__all__ = [
    "WriterPool",
    "WriterPoolExhausted",
]
