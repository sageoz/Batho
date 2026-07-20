"""Tests for memory monitoring utilities."""

import pytest

from batho.utils.memory_monitor import cap_workers_by_ram


class _FakeMemory:
    def __init__(self, available: int):
        self.available = available


class _FakePsutil:
    def __init__(self, available: int):
        self._available = available

    def virtual_memory(self):
        return _FakeMemory(self._available)


def test_cap_workers_by_ram_limits_by_available_memory(monkeypatch):
    """Worker count is capped by available RAM divided by per-worker footprint."""
    # 10 GB available, 200 MB per worker -> 51 workers allowed, ceiling is 100
    monkeypatch.setattr(
        "batho.utils.memory_monitor._psutil", _FakePsutil(10 * 1024**3)
    )
    monkeypatch.setattr("batho.utils.memory_monitor._PSUTIL_AVAILABLE", True)

    assert cap_workers_by_ram(100, 200.0) == 51


def test_cap_workers_by_ram_respects_configured_ceiling(monkeypatch):
    """RAM-based cap never exceeds the configured max_workers ceiling."""
    # 8 GB available, 1 GB per worker -> 8 workers allowed, ceiling is 4
    monkeypatch.setattr(
        "batho.utils.memory_monitor._psutil", _FakePsutil(8 * 1024**3)
    )
    monkeypatch.setattr("batho.utils.memory_monitor._PSUTIL_AVAILABLE", True)

    assert cap_workers_by_ram(4, 1024.0) == 4


def test_cap_workers_by_ram_returns_at_least_one(monkeypatch):
    """Even with tiny RAM the helper returns 1 worker."""
    monkeypatch.setattr(
        "batho.utils.memory_monitor._psutil", _FakePsutil(100 * 1024**2)
    )
    monkeypatch.setattr("batho.utils.memory_monitor._PSUTIL_AVAILABLE", True)

    assert cap_workers_by_ram(16, 200.0) == 1


def test_cap_workers_by_ram_returns_one_for_one(monkeypatch):
    """If configured workers is 1, return 1 without querying RAM."""
    assert cap_workers_by_ram(1, 150.0) == 1


def test_cap_workers_by_ram_fallback_when_psutil_unavailable():
    """When psutil is unavailable, the configured ceiling is preserved."""
    assert cap_workers_by_ram(8, 150.0) == 8
