"""Green Telemetry — Energy-efficient request tracking.

Tracks CPU time and memory usage per request to help users understand
and optimize the energy footprint of their code intelligence queries.

This is a USP feature for Batho Bridge Core, providing transparency
into the computational cost of AI-assisted development.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any
from collections import deque

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="green_telemetry")


@dataclass
class RequestMetrics:
    """Metrics for a single request.
    
    Attributes:
        endpoint: API endpoint or tool name
        duration_ms: Wall-clock time in milliseconds
        cpu_time_ms: CPU time in milliseconds
        memory_delta_mb: Memory change in MB
        timestamp: Unix timestamp
    """
    endpoint: str
    duration_ms: float
    cpu_time_ms: float
    memory_delta_mb: float
    timestamp: float = field(default_factory=time.time)


class GreenTelemetry:
    """Tracks request metrics with energy-conscious reporting.
    
    This class provides:
    - Per-request timing and memory tracking
    - Rolling window statistics
    - Carbon footprint estimation (proxy based on energy)
    
    Usage:
        telemetry = GreenTelemetry()
        
        with telemetry.track("hypergraph_l3"):
            result = handle_hypergraph_l3(deps, params)
    """
    
    def __init__(self, max_history: int = 1000):
        """Initialize telemetry.
        
        Args:
            max_history: Maximum number of metrics to keep in rolling window
        """
        self._history: deque[RequestMetrics] = deque(maxlen=max_history)
        self._lock = threading.Lock()
        self._total_requests = 0
        self._total_cpu_ms = 0.0
        self._peak_memory_mb = 0.0
    
    def track(self, endpoint: str):
        """Context manager for tracking a request.
        
        Usage:
            with telemetry.track("search"):
                results = handle_search(deps, params)
        
        Args:
            endpoint: Name of the endpoint being tracked
            
        Returns:
            _TrackerContext: Context manager that records metrics on exit
        """
        return _TrackerContext(self, endpoint)
    
    def record(self, metrics: RequestMetrics) -> None:
        """Record metrics for a completed request.
        
        Args:
            metrics: RequestMetrics to record
        """
        with self._lock:
            self._history.append(metrics)
            self._total_requests += 1
            self._total_cpu_ms += metrics.cpu_time_ms
            self._peak_memory_mb = max(
                self._peak_memory_mb,
                self._get_current_memory_mb()
            )
    
    def get_stats(self) -> dict[str, Any]:
        """Get current telemetry statistics.
        
        Returns:
            dict with keys:
                - total_requests: Total requests processed
                - avg_duration_ms: Average wall-clock time
                - avg_cpu_ms: Average CPU time
                - peak_memory_mb: Peak memory usage
                - recent_requests: List of recent RequestMetrics
                - carbon_estimate_grams: Estimated CO2 based on CPU time
        """
        with self._lock:
            if not self._history:
                return {
                    "total_requests": 0,
                    "avg_duration_ms": 0.0,
                    "avg_cpu_ms": 0.0,
                    "peak_memory_mb": 0.0,
                    "recent_requests": [],
                    "carbon_estimate_mg": 0.0,
                }
            
            recent = list(self._history)[-100:]  # Last 100 requests
            avg_duration = sum(m.duration_ms for m in recent) / len(recent)
            avg_cpu = sum(m.cpu_time_ms for m in recent) / len(recent)
            
            # Rough carbon estimate: 0.5g CO2 per hour of CPU
            # This is a simplified proxy - real measurement requires hardware data
            carbon_mg = (self._total_cpu_ms / 3600000) * 500
            
            return {
                "total_requests": self._total_requests,
                "avg_duration_ms": round(avg_duration, 2),
                "avg_cpu_ms": round(avg_cpu, 2),
                "peak_memory_mb": round(self._peak_memory_mb, 2),
                "recent_requests": [
                    {
                        "endpoint": m.endpoint,
                        "duration_ms": round(m.duration_ms, 2),
                        "cpu_time_ms": round(m.cpu_time_ms, 2),
                        "timestamp": m.timestamp,
                    }
                    for m in recent[-10:]  # Last 10 only in response
                ],
                "carbon_estimate_mg": round(carbon_mg, 2),
            }
    
    def _get_current_memory_mb(self) -> float:
        """Get current process memory usage in MB."""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0


class _TrackerContext:
    """Context manager for request tracking."""
    
    def __init__(self, telemetry: GreenTelemetry, endpoint: str):
        self.telemetry = telemetry
        self.endpoint = endpoint
        self.start_time = 0.0
        self.start_cpu = 0.0
        self.start_memory = 0.0
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        self.start_cpu = time.process_time()
        self.start_memory = self.telemetry._get_current_memory_mb()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time = time.perf_counter()
        end_cpu = time.process_time()
        end_memory = self.telemetry._get_current_memory_mb()
        
        duration_ms = (end_time - self.start_time) * 1000
        cpu_ms = (end_cpu - self.start_cpu) * 1000
        memory_delta = end_memory - self.start_memory
        
        metrics = RequestMetrics(
            endpoint=self.endpoint,
            duration_ms=duration_ms,
            cpu_time_ms=cpu_ms,
            memory_delta_mb=memory_delta,
        )
        
        self.telemetry.record(metrics)
        
        # Log slow requests
        if duration_ms > 1000:
            LOGGER.warning(
                "slow_request",
                endpoint=self.endpoint,
                duration_ms=round(duration_ms, 2),
            )
        
        return False  # Don't suppress exceptions


__all__ = ["GreenTelemetry", "RequestMetrics"]
