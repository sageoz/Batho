"""AgentEventBus — Real-time agent action publisher for SSE clients.

Maintains a bounded ring buffer of events that SSE clients can subscribe
to. Events are pushed by MCP tool handlers (read/write/error) and consumed
by the /api/v2/events/stream endpoint.

Thread-safe: all mutations use a threading.Lock.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable


@dataclass
class AgentEvent:
    """A single agent action event."""
    type: str          # 'agent_read' | 'agent_write' | 'agent_error'
    node_id: str       # entity/file node that was touched
    tool: str = ""     # MCP tool name
    detail: str = ""   # optional human-readable detail
    ts: float = field(default_factory=time.time)

    def to_sse_line(self) -> bytes:
        """Encode as SSE data frame."""
        payload = json.dumps({
            "type":    self.type,
            "node_id": self.node_id,
            "tool":    self.tool,
            "detail":  self.detail,
            "ts":      self.ts,
        })
        return f"data: {payload}\n\n".encode("utf-8")


class AgentEventBus:
    """Thread-safe pub/sub event bus for agent SSE stream.

    Usage::

        bus = AgentEventBus()

        # Publisher side (MCP handlers)
        bus.publish(AgentEvent(type='agent_read', node_id='...', tool='batho_get_entity'))

        # Consumer side (HTTP SSE handler) — blocking iterator
        for event in bus.subscribe(timeout=30):
            self.wfile.write(event.to_sse_line())
    """

    MAX_HISTORY = 500
    MAX_SUBSCRIBERS = 64

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: list[AgentEvent] = []
        self._queues: list[queue.SimpleQueue] = []

    def publish(self, event: AgentEvent) -> None:
        """Publish an event to all active subscribers."""
        with self._lock:
            self._history.append(event)
            if len(self._history) > self.MAX_HISTORY:
                self._history = self._history[-self.MAX_HISTORY :]
            for q in list(self._queues):
                try:
                    q.put_nowait(event)
                except Exception:
                    pass

    def subscribe(self, timeout: float = 60.0):
        """Generator that yields events until timeout or client disconnect.

        Replays last 10 events on connect so new clients see recent activity.
        """
        q: queue.SimpleQueue = queue.SimpleQueue()
        with self._lock:
            recent = self._history[-10:]
            if len(self._queues) >= self.MAX_SUBSCRIBERS:
                # Drop oldest subscriber queue
                self._queues.pop(0)
            self._queues.append(q)

        try:
            for event in recent:
                yield event

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    event = q.get(timeout=min(remaining, 10.0))
                    yield event
                    deadline = time.monotonic() + timeout  # reset on activity
                except queue.Empty:
                    # Yield keep-alive comment
                    yield None
        finally:
            with self._lock:
                try:
                    self._queues.remove(q)
                except ValueError:
                    pass

    def recent_events(self, n: int = 50) -> list[AgentEvent]:
        """Return the most recent n events."""
        with self._lock:
            return list(self._history[-n:])


# Module-level singleton — shared across HTTP and MCP transports
_global_bus: AgentEventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> AgentEventBus:
    """Return (or lazily create) the global singleton event bus."""
    global _global_bus
    if _global_bus is None:
        with _bus_lock:
            if _global_bus is None:
                _global_bus = AgentEventBus()
    return _global_bus


__all__ = ["AgentEvent", "AgentEventBus", "get_event_bus"]
