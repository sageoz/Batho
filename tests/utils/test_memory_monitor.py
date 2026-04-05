from __future__ import annotations

from types import SimpleNamespace

import pytest

import batho_core.utils.memory_monitor as memory_monitor_module


class _FakeProcess:
    def __init__(self, rss: int = 128 * 1024 * 1024, vms: int = 512 * 1024 * 1024, percent: float = 12.5):
        self.rss = rss
        self.vms = vms
        self.percent = percent
        self.info_calls = 0

    def memory_info(self):
        self.info_calls += 1
        return SimpleNamespace(rss=self.rss, vms=self.vms)

    def memory_percent(self):
        return self.percent


def _virtual_memory(
    *,
    available: int = 2 * 1024 * 1024 * 1024,
    total: int = 8 * 1024 * 1024 * 1024,
    used: int = 3 * 1024 * 1024 * 1024,
    percent: float = 42.0,
):
    return SimpleNamespace(
        available=available,
        total=total,
        used=used,
        percent=percent,
    )


def test_get_memory_stats_uses_cache(monkeypatch) -> None:
    fake_process = _FakeProcess()
    time_values = iter([1000.0, 1000.1])

    monkeypatch.setattr(memory_monitor_module.psutil, "Process", lambda _pid: fake_process)
    monkeypatch.setattr(memory_monitor_module.psutil, "virtual_memory", lambda: _virtual_memory())
    monkeypatch.setattr(memory_monitor_module.gc, "get_stats", lambda: [{"count": 1}, {"count": 2}])
    monkeypatch.setattr(memory_monitor_module.time, "time", lambda: next(time_values))

    monitor = memory_monitor_module.MemoryMonitor()
    first = monitor.get_memory_stats()
    second = monitor.get_memory_stats()

    assert fake_process.info_calls == 1
    assert first is second


def test_get_memory_stats_uses_gc_fallback_estimate(monkeypatch) -> None:
    fake_process = _FakeProcess()

    monkeypatch.setattr(memory_monitor_module.psutil, "Process", lambda _pid: fake_process)
    monkeypatch.setattr(memory_monitor_module.psutil, "virtual_memory", lambda: _virtual_memory())
    monkeypatch.setattr(
        memory_monitor_module.gc,
        "get_stats",
        lambda: (_ for _ in ()).throw(RuntimeError("stats failed")),
    )
    monkeypatch.setattr(memory_monitor_module.gc, "get_objects", lambda generation: [0] * (generation + 1))

    monitor = memory_monitor_module.MemoryMonitor()
    stats = monitor.get_memory_stats()

    assert stats.gc_objects == 6


def test_get_memory_stats_falls_back_to_zero_gc_objects(monkeypatch) -> None:
    fake_process = _FakeProcess()

    monkeypatch.setattr(memory_monitor_module.psutil, "Process", lambda _pid: fake_process)
    monkeypatch.setattr(memory_monitor_module.psutil, "virtual_memory", lambda: _virtual_memory())
    monkeypatch.setattr(
        memory_monitor_module.gc,
        "get_stats",
        lambda: (_ for _ in ()).throw(RuntimeError("stats failed")),
    )
    monkeypatch.setattr(
        memory_monitor_module.gc,
        "get_objects",
        lambda _generation: (_ for _ in ()).throw(RuntimeError("objects failed")),
    )

    monitor = memory_monitor_module.MemoryMonitor()
    stats = monitor.get_memory_stats()

    assert stats.gc_objects == 0


def test_get_memory_stats_handles_psutil_errors(monkeypatch) -> None:
    class _BrokenProcess:
        @staticmethod
        def memory_info():
            raise memory_monitor_module.psutil.NoSuchProcess(pid=123)

        @staticmethod
        def memory_percent():
            return 0.0

    monkeypatch.setattr(memory_monitor_module.psutil, "Process", lambda _pid: _BrokenProcess())

    monitor = memory_monitor_module.MemoryMonitor()
    stats = monitor.get_memory_stats()

    assert stats == memory_monitor_module.MemoryStats(0, 0, 0, 0, 0)


def test_check_memory_usage_returns_critical_warning_and_none(monkeypatch) -> None:
    monitor = memory_monitor_module.MemoryMonitor(warning_threshold_mb=100.0, critical_threshold_mb=200.0)

    monkeypatch.setattr(
        monitor,
        "get_memory_stats",
        lambda: memory_monitor_module.MemoryStats(250.0, 0.0, 0.0, 0.0, 0),
    )
    critical_message = monitor.check_memory_usage("build")
    assert critical_message is not None
    assert critical_message.startswith("CRITICAL")

    monkeypatch.setattr(
        monitor,
        "get_memory_stats",
        lambda: memory_monitor_module.MemoryStats(150.0, 0.0, 0.0, 0.0, 0),
    )
    warning_message = monitor.check_memory_usage("build")
    assert warning_message is not None
    assert warning_message.startswith("WARNING")

    monkeypatch.setattr(
        monitor,
        "get_memory_stats",
        lambda: memory_monitor_module.MemoryStats(50.0, 0.0, 0.0, 0.0, 0),
    )
    assert monitor.check_memory_usage("build") is None


def test_log_memory_stats_uses_current_stats(monkeypatch) -> None:
    monitor = memory_monitor_module.MemoryMonitor()
    monkeypatch.setattr(
        monitor,
        "get_memory_stats",
        lambda: memory_monitor_module.MemoryStats(10.0, 20.0, 3.0, 400.0, 5),
    )
    monitor.log_memory_stats("index")


def test_memory_monitor_context_logs_warnings_and_gc_suggestion(monkeypatch) -> None:
    class _ContextMonitor:
        def __init__(self, warning_threshold_mb: float, critical_threshold_mb: float):
            _ = warning_threshold_mb, critical_threshold_mb
            self.calls = 0

        def get_memory_stats(self):
            self.calls += 1
            if self.calls == 1:
                return memory_monitor_module.MemoryStats(100.0, 0.0, 1.0, 500.0, 10)
            return memory_monitor_module.MemoryStats(250.0, 0.0, 1.0, 500.0, 35)

        @staticmethod
        def check_memory_usage(operation: str):
            if operation.endswith("_start") or operation.endswith("_end"):
                return "warning"
            return None

    monkeypatch.setattr(memory_monitor_module, "MemoryMonitor", _ContextMonitor)

    with memory_monitor_module.memory_monitor("sync") as monitor:
        assert isinstance(monitor, _ContextMonitor)


def test_memory_monitor_context_reraises_errors(monkeypatch) -> None:
    class _ContextMonitor:
        def __init__(self, warning_threshold_mb: float, critical_threshold_mb: float):
            _ = warning_threshold_mb, critical_threshold_mb

        @staticmethod
        def get_memory_stats():
            return memory_monitor_module.MemoryStats(100.0, 0.0, 1.0, 500.0, 10)

        @staticmethod
        def check_memory_usage(_operation: str):
            return None

    monkeypatch.setattr(memory_monitor_module, "MemoryMonitor", _ContextMonitor)

    with pytest.raises(RuntimeError, match="boom"):
        with memory_monitor_module.memory_monitor("sync"):
            raise RuntimeError("boom")


def test_force_garbage_collection_returns_summary(monkeypatch) -> None:
    stats_values = iter([[{"count": 12}, {"count": 3}], [{"count": 10}, {"count": 2}]])
    monkeypatch.setattr(memory_monitor_module.gc, "get_stats", lambda: next(stats_values))
    monkeypatch.setattr(memory_monitor_module.gc, "collect", lambda: 5)

    result = memory_monitor_module.force_garbage_collection()

    assert result["collected_objects"] == 5
    assert result["objects_before"] == 15
    assert result["objects_after"] == 12
    assert result["objects_freed"] == 3


def test_get_system_memory_info_success_and_failure(monkeypatch) -> None:
    monkeypatch.setattr(memory_monitor_module.psutil, "virtual_memory", lambda: _virtual_memory(percent=50.0))
    monkeypatch.setattr(
        memory_monitor_module.psutil,
        "swap_memory",
        lambda: SimpleNamespace(total=1024, used=256, percent=25.0),
    )

    info = memory_monitor_module.get_system_memory_info()
    assert info["percent"] == 50.0
    assert info["swap_percent"] == 25.0

    monkeypatch.setattr(
        memory_monitor_module.psutil,
        "virtual_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("no vm")),
    )

    assert memory_monitor_module.get_system_memory_info() == {}


def test_check_memory_pressure_success_and_failure(monkeypatch) -> None:
    monkeypatch.setattr(memory_monitor_module.psutil, "virtual_memory", lambda: _virtual_memory(percent=95.0))
    assert memory_monitor_module.check_memory_pressure(threshold_percent=90.0) is True

    monkeypatch.setattr(memory_monitor_module.psutil, "virtual_memory", lambda: _virtual_memory(percent=20.0))
    assert memory_monitor_module.check_memory_pressure(threshold_percent=90.0) is False

    monkeypatch.setattr(
        memory_monitor_module.psutil,
        "virtual_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("no vm")),
    )
    assert memory_monitor_module.check_memory_pressure() is False
