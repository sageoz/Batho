"""Queue system for webhook processing."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from batho.utils.logging import get_logger

from .config import ProcessingConfig

try:
    from celery import Celery
except ImportError:
    Celery = None

logger = get_logger(__name__, component="webhook_queue")


@dataclass
class QueueItem:
    """Item in the webhook queue."""

    event_id: str
    event: dict[str, Any]
    priority: int = 50
    attempts: int = 0
    max_attempts: int = 3
    next_attempt: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event": self.event,
            "priority": self.priority,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "next_attempt": self.next_attempt,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "QueueItem":
        return cls(
            event_id=str(payload.get("event_id", "")),
            event=dict(payload.get("event", {})),
            priority=int(payload.get("priority", 50)),
            attempts=int(payload.get("attempts", 0)),
            max_attempts=int(payload.get("max_attempts", 3)),
            next_attempt=float(payload.get("next_attempt", 0.0)),
        )


_CELERY_HANDLER_REGISTRY: dict[str, Callable[[QueueItem], bool]] = {}


class WebhookQueue:
    """Queue for processing webhook events."""

    def __init__(self, config: Optional[ProcessingConfig] = None, max_size: int = 1000):
        self._config = config or ProcessingConfig()
        self._queue: queue.PriorityQueue[tuple[int, float, QueueItem]] = (
            queue.PriorityQueue(maxsize=max_size)
        )
        self._dead_letter = queue.Queue()
        self._processing = False
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._backend = self._config.queue_backend
        self._processed_count = 0
        self._failed_count = 0
        self._queue_id = f"webhook-queue-{uuid.uuid4().hex}"
        self._celery_app: Optional[Celery] = None
        self._celery_task = None

        self._initialize_backend()

    def _initialize_backend(self) -> None:
        if self._backend != "celery":
            return

        if Celery is None:
            logger.warning(
                "celery_not_installed_falling_back_to_sync",
                requested_backend=self._backend,
            )
            self._backend = "sync"
            return

        if not self._config.task_always_eager:
            logger.warning(
                "celery_non_eager_without_distributed_backend_falling_back_to_sync",
                requested_backend=self._backend,
            )
            self._backend = "sync"
            return

        self._celery_app = Celery(
            "batho_webhook_queue",
            broker=self._config.celery_broker_url,
            backend=self._config.celery_result_backend,
        )
        self._celery_app.conf.update(
            task_always_eager=self._config.task_always_eager,
            task_store_eager_result=self._config.task_store_eager_result,
            task_ignore_result=not self._config.task_store_eager_result,
        )

        @self._celery_app.task(name="batho.webhook.execute")
        def _execute(queue_id: str, item_payload: dict[str, Any]) -> bool:
            handler = _CELERY_HANDLER_REGISTRY.get(queue_id)
            if handler is None:
                return False
            return bool(handler(QueueItem.from_payload(item_payload)))

        self._celery_task = _execute
        logger.info(
            "celery_queue_initialized",
            backend=self._backend,
            broker=self._config.celery_broker_url,
        )

    def put(self, item: QueueItem) -> bool:
        """Add item to queue."""
        try:
            # Higher priority value should run first, then FIFO by timestamp.
            self._queue.put_nowait((-item.priority, time.time(), item))
            logger.debug("queue_item_added", event_id=item.event_id)
            return True
        except queue.Full:
            logger.error("queue_full", event_id=item.event_id)
            return False

    def start_processing(self, handler: Callable[[QueueItem], bool]) -> None:
        """Start background processing of queue items.

        Args:
            handler: Function that processes items, returns True on success
        """
        if self._processing:
            logger.warning("queue_already_processing")
            return

        if self._backend == "celery":
            _CELERY_HANDLER_REGISTRY[self._queue_id] = handler

        self._processing = True
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._process_items, args=(handler,), daemon=True
        )
        self._worker_thread.start()
        logger.info("queue_processing_started")

    def stop_processing(self) -> None:
        """Stop background processing."""
        if not self._processing:
            return

        self._processing = False
        self._stop_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)

        if self._backend == "celery":
            _CELERY_HANDLER_REGISTRY.pop(self._queue_id, None)

        logger.info("queue_processing_stopped")

    def _dispatch(self, handler: Callable[[QueueItem], bool], item: QueueItem) -> bool:
        if self._backend != "celery" or self._celery_task is None:
            return handler(item)

        try:
            async_result = self._celery_task.apply_async(
                args=[self._queue_id, item.to_payload()]
            )
            return bool(async_result.get(timeout=self._config.timeout_seconds))
        except Exception as exc:
            logger.error(
                "celery_dispatch_failed", event_id=item.event_id, error=str(exc)
            )
            return False

    def _process_items(self, handler: Callable[[QueueItem], bool]) -> None:
        """Background worker to process queue items."""
        while not self._stop_event.is_set():
            try:
                # Get item with timeout
                _, _, item = self._queue.get(timeout=1.0)

                # Check if it's time to retry
                if time.time() < item.next_attempt:
                    # Put back and wait
                    self._queue.put((-item.priority, time.time(), item))
                    time.sleep(0.1)
                    continue

                # Process item
                success = self._dispatch(handler, item)

                if success:
                    self._processed_count += 1
                    logger.info("queue_item_processed", event_id=item.event_id)
                else:
                    self._failed_count += 1
                    # Retry logic
                    item.attempts += 1
                    if item.attempts < item.max_attempts:
                        # Exponential backoff
                        delay = min(300, 2**item.attempts)  # Max 5 minutes
                        item.next_attempt = time.time() + delay
                        self._queue.put((-item.priority, time.time(), item))
                        logger.warning(
                            "queue_item_retry",
                            event_id=item.event_id,
                            attempt=item.attempts,
                            delay=delay,
                        )
                    else:
                        # Move to dead letter queue
                        self._dead_letter.put(item)
                        logger.error(
                            "queue_item_dead_letter",
                            event_id=item.event_id,
                            attempts=item.attempts,
                        )

                self._queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error("queue_processing_error", error=str(e))

    def get_stats(self) -> dict[str, int]:
        """Get queue statistics."""
        return {
            "queue_size": self._queue.qsize(),
            "dead_letter_size": self._dead_letter.qsize(),
            "processing": 1 if self._processing else 0,
            "processed": self._processed_count,
            "failed": self._failed_count,
            "backend": 1 if self._backend == "celery" else 0,
        }
