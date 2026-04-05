from __future__ import annotations

import time
import queue as queue_std
from types import SimpleNamespace

import pytest

import batho_core.webhook.queue as queue_module
from batho_core.webhook.config import ProcessingConfig
from batho_core.webhook.queue import QueueItem, WebhookQueue


def test_queue_item_payload_roundtrip() -> None:
    item = QueueItem(event_id="e1", event={"a": 1}, priority=70, attempts=1, max_attempts=4, next_attempt=12.5)
    restored = QueueItem.from_payload(item.to_payload())
    assert restored.event_id == "e1"
    assert restored.priority == 70
    assert restored.attempts == 1


def test_put_queue_full_and_stats() -> None:
    q = WebhookQueue(config=ProcessingConfig(queue_backend="sync"), max_size=1)
    assert q.put(QueueItem(event_id="a", event={})) is True
    assert q.put(QueueItem(event_id="b", event={})) is False
    stats = q.get_stats()
    assert stats["queue_size"] >= 1


def test_start_stop_processing_success_path() -> None:
    q = WebhookQueue(config=ProcessingConfig(queue_backend="sync"), max_size=10)
    q.put(QueueItem(event_id="ok", event={}))

    q.start_processing(lambda _item: True)
    deadline = time.time() + 2.0
    while time.time() < deadline and q.get_stats()["processed"] == 0:
        time.sleep(0.02)
    q.stop_processing()

    assert q.get_stats()["processed"] >= 1


def test_retry_and_dead_letter_path() -> None:
    q = WebhookQueue(config=ProcessingConfig(queue_backend="sync"), max_size=10)
    q.put(QueueItem(event_id="fail", event={}, max_attempts=1))

    q.start_processing(lambda _item: False)
    deadline = time.time() + 2.0
    while time.time() < deadline and q.get_stats()["dead_letter_size"] == 0:
        time.sleep(0.02)
    q.stop_processing()

    stats = q.get_stats()
    assert stats["failed"] >= 1
    assert stats["dead_letter_size"] >= 1


def test_dispatch_celery_success_and_failure() -> None:
    q = WebhookQueue(config=ProcessingConfig(queue_backend="sync"))

    class _Result:
        def get(self, timeout):
            _ = timeout
            return True

    class _Task:
        def apply_async(self, args):
            _ = args
            return _Result()

    q._backend = "celery"
    q._celery_task = _Task()
    ok = q._dispatch(lambda _i: False, QueueItem(event_id="x", event={}))
    assert ok is True

    class _BadTask:
        def apply_async(self, args):
            _ = args
            raise RuntimeError("boom")

    q._celery_task = _BadTask()
    bad = q._dispatch(lambda _i: True, QueueItem(event_id="x", event={}))
    assert bad is False


def test_initialize_backend_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_module, "Celery", None)
    q = WebhookQueue(config=ProcessingConfig(queue_backend="celery", task_always_eager=True))
    assert q._backend == "sync"

    class _FakeCelery:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs
            self.conf = SimpleNamespace(update=lambda **_k: None)

        def task(self, name):
            _ = name

            def _wrap(fn):
                return fn

            return _wrap

    monkeypatch.setattr(queue_module, "Celery", _FakeCelery)
    q2 = WebhookQueue(config=ProcessingConfig(queue_backend="celery", task_always_eager=False))
    assert q2._backend == "sync"

    q3 = WebhookQueue(config=ProcessingConfig(queue_backend="celery", task_always_eager=True))
    assert q3._backend == "celery"


def test_start_processing_already_processing_and_queue_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    q = WebhookQueue(config=ProcessingConfig(queue_backend="sync"), max_size=10)
    q.start_processing(lambda _item: True)
    q.start_processing(lambda _item: True)

    def _explode(timeout):
        _ = timeout
        raise RuntimeError("bad")

    monkeypatch.setattr(q._queue, "get", _explode)
    time.sleep(0.05)
    q.stop_processing()


def test_celery_task_dispatch_and_registry_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeCelery:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs
            self.conf = SimpleNamespace(update=lambda **_k: None)

        def task(self, name):
            _ = name

            def _decorator(fn):
                return fn

            return _decorator

    monkeypatch.setattr(queue_module, "Celery", _FakeCelery)
    q = WebhookQueue(config=ProcessingConfig(queue_backend="celery", task_always_eager=True))

    payload = QueueItem(event_id="evt-1", event={"x": 1}).to_payload()
    assert q._celery_task is not None
    assert q._celery_task("unknown-queue", payload) is False

    queue_module._CELERY_HANDLER_REGISTRY[q._queue_id] = lambda item: item.event_id == "evt-1"
    try:
        assert q._celery_task(q._queue_id, payload) is True
    finally:
        queue_module._CELERY_HANDLER_REGISTRY.pop(q._queue_id, None)

    class _Thread:
        def __init__(self, target, args, daemon):
            _ = target, args
            self.daemon = daemon

        def start(self):
            return None

        @staticmethod
        def is_alive():
            return False

        def join(self, timeout=None):
            _ = timeout
            return None

    monkeypatch.setattr(queue_module.threading, "Thread", _Thread)

    q.start_processing(lambda _item: True)
    assert q._queue_id in queue_module._CELERY_HANDLER_REGISTRY
    q.stop_processing()
    assert q._queue_id not in queue_module._CELERY_HANDLER_REGISTRY

    q2 = WebhookQueue(config=ProcessingConfig(queue_backend="sync"), max_size=1)
    q2.stop_processing()


def test_process_items_requeue_not_ready_and_retry_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    q = WebhookQueue(config=ProcessingConfig(queue_backend="sync"), max_size=10)
    q._stop_event.clear()

    delayed_item = QueueItem(event_id="later", event={}, next_attempt=time.time() + 60)
    get_calls = {"count": 0}
    queued: list[tuple[int, float, QueueItem]] = []

    def _get(timeout=None):
        _ = timeout
        if get_calls["count"] == 0:
            get_calls["count"] += 1
            return (-delayed_item.priority, time.time(), delayed_item)
        raise queue_std.Empty

    def _put(item):
        queued.append(item)

    monkeypatch.setattr(q._queue, "get", _get)
    monkeypatch.setattr(q._queue, "put", _put)
    monkeypatch.setattr(queue_module.time, "sleep", lambda _delay: q._stop_event.set())

    q._process_items(lambda _item: True)
    assert queued

    retry_queue = WebhookQueue(config=ProcessingConfig(queue_backend="sync"), max_size=10)
    retry_queue._stop_event.clear()

    retry_item = QueueItem(event_id="retry", event={}, max_attempts=3)

    def _retry_get(timeout=None):
        _ = timeout
        return (-retry_item.priority, time.time(), retry_item)

    requeued: list[tuple[int, float, QueueItem]] = []

    def _retry_put(item):
        requeued.append(item)
        retry_queue._stop_event.set()

    monkeypatch.setattr(retry_queue._queue, "get", _retry_get)
    monkeypatch.setattr(retry_queue._queue, "put", _retry_put)
    monkeypatch.setattr(retry_queue._queue, "task_done", lambda: None)
    monkeypatch.setattr(retry_queue, "_dispatch", lambda _handler, _item: False)

    retry_queue._process_items(lambda _item: False)
    assert retry_item.attempts == 1
    assert retry_item.next_attempt > 0
    assert requeued

    error_queue = WebhookQueue(config=ProcessingConfig(queue_backend="sync"), max_size=10)
    error_queue._stop_event.clear()

    def _explode(timeout=None):
        _ = timeout
        error_queue._stop_event.set()
        raise RuntimeError("queue blew up")

    monkeypatch.setattr(error_queue._queue, "get", _explode)
    error_queue._process_items(lambda _item: True)
