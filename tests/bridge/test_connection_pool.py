"""Tests for ConnectionPool."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from batho.bridge.connection_pool import ConnectionPool, ConnectionPoolExhausted


class TestConnectionPool:
    """Test ConnectionPool functionality."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create a temporary SQLite database."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO test (id) VALUES (1)")
        conn.commit()
        conn.close()
        return db

    def test_acquire_release(self, db_path):
        """Acquiring and releasing a connection works."""
        pool = ConnectionPool(db_path, size=2)
        conn = pool.acquire()
        assert conn is not None
        pool.release(conn)
        pool.close()

    def test_connection_context_manager(self, db_path):
        """Using connection as context manager works."""
        pool = ConnectionPool(db_path, size=2)
        with pool.connection() as conn:
            result = conn.execute("SELECT * FROM test").fetchone()
            assert result[0] == 1
        pool.close()

    def test_pragmas_applied(self, db_path):
        """Connection pragmas are applied."""
        pool = ConnectionPool(db_path, size=1)
        with pool.connection() as conn:
            result = conn.execute("PRAGMA query_only").fetchone()
            assert result[0] == 1
        pool.close()

    def test_pool_size_limit(self, db_path):
        """Pool respects size limit."""
        pool = ConnectionPool(db_path, size=1)
        conn1 = pool.acquire()
        with pytest.raises(ConnectionPoolExhausted):
            pool.acquire()
        pool.release(conn1)
        pool.close()

    def test_concurrent_access(self, db_path):
        """Multiple threads can access pool."""
        import threading
        pool = ConnectionPool(db_path, size=2)
        results = []

        def worker():
            with pool.connection() as conn:
                result = conn.execute("SELECT * FROM test").fetchone()
                results.append(result[0])

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results == [1, 1]
        pool.close()

    def test_close_releases_all(self, db_path):
        """Close releases all connections."""
        pool = ConnectionPool(db_path, size=2)
        conn = pool.acquire()
        pool.close()
        assert pool.in_use == 0
