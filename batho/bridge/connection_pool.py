"""SQLite connection pool for read-only workspace access."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Iterator

from batho.bridge.constants import DEFAULT_CONNECTION_POOL_SIZE
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.pool")


class ConnectionPoolExhausted(Exception):
    """Raised when connection pool cannot acquire a connection within timeout."""
    pass


class ConnectionPool:
    """Bounded pool of read-only SQLite connections."""

    def __init__(
        self,
        db_path: Path,
        *,
        size: int = DEFAULT_CONNECTION_POOL_SIZE,
        read_only: bool = True,
        acquire_timeout: float = 5.0,
    ):
        self._db_path = db_path
        self._size = size
        self._read_only = read_only
        self._acquire_timeout = acquire_timeout
        self._pool: Queue = Queue(maxsize=size)
        self._created = 0
        self._lock = threading.Lock()
        self._closed = False
        self._init_pool()

    def _init_pool(self) -> None:
        """Pre-populate the pool with connections."""
        with self._lock:
            while self._created < self._size:
                try:
                    conn = self._create_connection()
                    self._pool.put_nowait(conn)
                    self._created += 1
                except Exception:
                    break

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new read-only SQLite connection with optimized pragmas."""
        uri = f"file:{self._db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=67108864")
        conn.execute("PRAGMA cache_size=-8000")
        conn.row_factory = sqlite3.Row
        return conn

    def acquire(self) -> sqlite3.Connection:
        """Acquire a connection from the pool."""
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        try:
            return self._pool.get(timeout=self._acquire_timeout)
        except Empty:
            with self._lock:
                if self._created < self._size:
                    try:
                        conn = self._create_connection()
                        self._created += 1
                        LOGGER.debug("connection_created", db_path=str(self._db_path), total=self._created)
                        return conn
                    except Exception:
                        raise ConnectionPoolExhausted(
                            f"Could not acquire connection to {self._db_path} within {self._acquire_timeout}s"
                        )

            raise ConnectionPoolExhausted(
                f"Could not acquire connection to {self._db_path} within {self._acquire_timeout}s"
            )

    def release(self, conn: sqlite3.Connection) -> None:
        """Return a connection to the pool."""
        if self._closed:
            conn.close()
            return
        try:
            self._pool.put_nowait(conn)
        except Full:
            try:
                conn.close()
            finally:
                with self._lock:
                    self._created -= 1

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for acquiring and releasing a connection."""
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def close(self) -> None:
        """Close all connections in the pool."""
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

    @property
    def in_use(self) -> int:
        return self._created - self._pool.qsize()


__all__ = [
    "ConnectionPool",
    "ConnectionPoolExhausted",
]
