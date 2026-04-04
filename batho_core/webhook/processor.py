"""Main webhook processing logic."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from batho_core.synthesizer import record_failure_rule
from batho_core.time_machine import incremental_patch
from batho_core.utils.logging import get_logger
from .config import WebhookConfig
from .parser import WebhookEvent, parse_webhook_event
from .queue import QueueItem, WebhookQueue

logger = get_logger(__name__, component="webhook_processor")


class WebhookProcessor:
    """Processes webhook events and updates Batho graph."""
    
    def __init__(self, config: WebhookConfig, repo_path: Path):
        self.config = config
        self.repo_path = repo_path
        self.queue = WebhookQueue(config=self.config.processing)
        self._ctn_dir = repo_path / ".ctn"
        self._latest_snapshot_id: Optional[str] = None
    
    def process_webhook(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Process incoming webhook.
        
        Args:
            payload: Webhook payload
            headers: HTTP headers
            
        Returns:
            Response dict with status
        """
        try:
            # Parse event
            event = parse_webhook_event(payload, headers)
            
            validation = self._validate_event(event)
            if validation:
                return {
                    "status": validation["status"],
                    "message": validation["message"],
                }

            # Queue for processing
            event_id = str(uuid.uuid4())
            queue_item = QueueItem(
                event_id=event_id,
                event={"payload": payload, "headers": headers},
                priority=self._event_priority(event),
                max_attempts=max(1, self.config.processing.retry_attempts),
            )

            if not self.queue.put(queue_item):
                logger.warning(
                    "queue_unavailable_fallback_sync",
                    event_id=event_id,
                    repository=event.repository,
                )
                success = self._handle_queue_item(queue_item)
                if not success:
                    return {
                        "status": "error",
                        "message": "Queue unavailable and synchronous processing failed",
                    }
                return {
                    "status": "processed",
                    "event_id": event_id,
                    "message": "Webhook processed synchronously",
                }

            logger.info(
                "webhook_queued",
                event_id=event_id,
                platform=event.platform.value,
                event_type=event.event_type.value,
                repository=event.repository,
                branch=event.branch,
            )

            return {
                "status": "queued",
                "event_id": event_id,
                "message": "Webhook queued for processing",
            }

        except Exception as e:
            logger.error("webhook_processing_error", error=str(e))
            return {
                "status": "error",
                "message": f"Processing error: {str(e)}",
            }

    def process_webhook_sync(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Process a webhook immediately in the current thread.

        This is used by one-shot CLI webhook handling to exercise the same
        parser, validation, and patch application pipeline as server mode.
        """

        try:
            event = parse_webhook_event(payload, headers)
            validation = self._validate_event(event)
            if validation:
                return {
                    "status": validation["status"],
                    "message": validation["message"],
                }

            queue_item = QueueItem(
                event_id=str(uuid.uuid4()),
                event={"payload": payload, "headers": headers},
                priority=self._event_priority(event),
                max_attempts=1,
            )
            success = self._handle_queue_item(queue_item)
            if not success:
                return {
                    "status": "error",
                    "event_id": queue_item.event_id,
                    "message": "Synchronous webhook processing failed",
                }

            return {
                "status": "processed",
                "event_id": queue_item.event_id,
                "message": "Webhook processed synchronously",
            }

        except Exception as e:
            logger.error("webhook_sync_processing_error", error=str(e))
            return {
                "status": "error",
                "message": f"Processing error: {str(e)}",
            }
    
    def start(self) -> None:
        """Start background processing."""
        self.queue.start_processing(self._handle_queue_item)
        logger.info("webhook_processor_started")
    
    def stop(self) -> None:
        """Stop background processing."""
        self.queue.stop_processing()
        logger.info("webhook_processor_stopped")
    
    def _handle_queue_item(self, item: QueueItem) -> bool:
        """Handle a queue item.
        
        Returns:
            True if successful, False for retry
        """
        event: WebhookEvent | None = None
        try:
            event_data = item.event
            event = parse_webhook_event(event_data["payload"], event_data["headers"])
            
            logger.info(
                "processing_webhook",
                event_id=item.event_id,
                platform=event.platform.value,
                event_type=event.event_type.value,
            )

            # Get latest snapshot if not cached
            if not self._latest_snapshot_id:
                self._latest_snapshot_id = self._find_latest_snapshot()

            if not self._latest_snapshot_id:
                logger.error(
                    "webhook_processing_no_snapshot",
                    event_id=item.event_id,
                    ctn_dir=str(self._ctn_dir),
                )
                self._record_failure_entry(
                    source="webhook.processor",
                    error_message="No base snapshot available for webhook incremental patching",
                    changed_files=[change.path for change in event.changes],
                    context={
                        "event_id": item.event_id,
                        "event_type": event.event_type.value,
                        "repository": event.repository,
                        "branch": event.branch,
                    },
                )
                return False

            # Process changes
            if event.changes:
                result = incremental_patch(
                    self._ctn_dir,
                    self._latest_snapshot_id or "",
                    event.changes,
                )

                if result.get("success"):
                    self._latest_snapshot_id = result.get("new_snapshot_id")
                    logger.info(
                        "webhook_processed",
                        event_id=item.event_id,
                        new_snapshot_id=self._latest_snapshot_id,
                        changes_count=len(event.changes),
                    )
                    return True
                else:
                    logger.error(
                        "incremental_patch_failed",
                        event_id=item.event_id,
                        error=result.get("error"),
                    )
                    self._record_failure_entry(
                        source="webhook.processor",
                        error_message=str(result.get("error") or "incremental patch failed"),
                        changed_files=[change.path for change in event.changes],
                        context={
                            "event_id": item.event_id,
                            "event_type": event.event_type.value,
                            "repository": event.repository,
                            "branch": event.branch,
                            "commit": event.commit_hash,
                            "operation_id": result.get("operation_id"),
                        },
                    )
                    return False
            else:
                # No changes to process
                logger.info("webhook_no_changes", event_id=item.event_id)
                return True
                
        except Exception as e:
            logger.error(
                "queue_item_processing_error",
                event_id=item.event_id,
                error=str(e),
            )
            self._record_failure_entry(
                source="webhook.processor",
                error_message=str(e),
                changed_files=[change.path for change in event.changes] if event else [],
                context={
                    "event_id": item.event_id,
                    "event_type": event.event_type.value if event else "unknown",
                    "repository": event.repository if event else "unknown",
                    "branch": event.branch if event else "",
                    "commit": event.commit_hash if event else "",
                },
            )
            return False

    def _record_failure_entry(
        self,
        source: str,
        error_message: str,
        changed_files: list[str],
        context: dict[str, Any],
    ) -> None:
        try:
            record_failure_rule(
                ctn_dir=self._ctn_dir,
                source=source,
                error_message=error_message,
                changed_files=changed_files,
                context=context,
            )
        except Exception as exc:
            logger.warning("webhook_evolution_ledger_record_failed", error=str(exc))
    
    def _find_latest_snapshot(self) -> Optional[str]:
        """Find the latest snapshot ID."""
        from batho_core.time_machine import list_snapshots
        
        snapshots = list_snapshots(self._ctn_dir)
        if snapshots:
            # Return the most recent snapshot
            latest = max(snapshots, key=lambda s: s.get("created_at", ""))
            return latest.get("snapshot_id")
        return None

    def _validate_event(self, event: WebhookEvent) -> dict[str, str] | None:
        if self.config.repository and event.repository != self.config.repository.name:
            return {
                "status": "error",
                "message": (
                    f"Repository mismatch: expected {self.config.repository.name}, "
                    f"got {event.repository}"
                ),
            }

        if self.config.repository and event.branch:
            if event.branch not in self.config.repository.branches:
                return {
                    "status": "ignored",
                    "message": f"Branch {event.branch} not in watched branches",
                }

        return None

    @staticmethod
    def _event_priority(event: WebhookEvent) -> int:
        priority_map = {
            "pull_request_opened": 100,
            "pull_request_synchronized": 100,
            "pull_request_closed": 90,
            "merge_request_opened": 100,
            "merge_request_updated": 100,
            "merge_request_closed": 90,
            "push": 50,
        }
        return priority_map.get(event.event_type.value, 50)
