"""Queue system for webhook processing."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from batho_core.utils.logging import get_logger

logger = get_logger(__name__, component="webhook_queue")


@dataclass
class QueueItem:
    """Item in the webhook queue."""
    event_id: str
    event: dict[str, Any]
    attempts: int = 0
    max_attempts: int = 3
    next_attempt: float = 0.0


class WebhookQueue:
    """Queue for processing webhook events."""
    
    def __init__(self, max_size: int = 1000):
        self._queue = queue.Queue(maxsize=max_size)
        self._dead_letter = queue.Queue()
        self._processing = False
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def put(self, item: QueueItem) -> bool:
        """Add item to queue."""
        try:
            self._queue.put_nowait(item)
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
        
        self._processing = True
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._process_items,
            args=(handler,),
            daemon=True
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
        
        logger.info("queue_processing_stopped")
    
    def _process_items(self, handler: Callable[[QueueItem], bool]) -> None:
        """Background worker to process queue items."""
        while not self._stop_event.is_set():
            try:
                # Get item with timeout
                item = self._queue.get(timeout=1.0)
                
                # Check if it's time to retry
                if time.time() < item.next_attempt:
                    # Put back and wait
                    self._queue.put(item)
                    time.sleep(0.1)
                    continue
                
                # Process item
                success = handler(item)
                
                if success:
                    logger.info("queue_item_processed", event_id=item.event_id)
                else:
                    # Retry logic
                    item.attempts += 1
                    if item.attempts < item.max_attempts:
                        # Exponential backoff
                        delay = min(300, 2 ** item.attempts)  # Max 5 minutes
                        item.next_attempt = time.time() + delay
                        self._queue.put(item)
                        logger.warning(
                            "queue_item_retry",
                            event_id=item.event_id,
                            attempt=item.attempts,
                            delay=delay
                        )
                    else:
                        # Move to dead letter queue
                        self._dead_letter.put(item)
                        logger.error(
                            "queue_item_dead_letter",
                            event_id=item.event_id,
                            attempts=item.attempts
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
        }
