"""Prometheus telemetry for MCP Hub.

Metrics:
- batho_mcp_tool_calls_total{tool, workspace, status}
- batho_mcp_tool_latency_seconds_bucket{tool}
- batho_workspaces_total{state}
- batho_workspaces_resident
- batho_artifact_cache_bytes{workspace}
- batho_artifact_cache_hit_ratio{workspace}
- batho_mount_duration_seconds_bucket{workspace}
- batho_evictions_total{reason}
- batho_inflight{scope, workspace}
- batho_artifact_loads_total{workspace, type, status}
- batho_checksum_mismatch_total{workspace}
- batho_cross_index_bytes
- batho_cross_index_workspaces
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge.telemetry")


@dataclass
class TelemetryCollector:
    """Collects and exposes Prometheus metrics."""

    _lock = threading.Lock()

    _tool_calls: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    _tool_latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _workspace_states: dict[str, str] = field(default_factory=dict)
    _cache_bytes: dict[str, int] = field(default_factory=dict)
    _cache_hits: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _cache_misses: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _mount_durations: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _evictions: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _inflight: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _artifact_loads: dict[str, dict[tuple[str, str], int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    _checksum_mismatches: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _cross_index_bytes: int = 0
    _cross_index_workspaces: int = 0
    _start_time: float = field(default_factory=time.time)

    def record_tool_call(self, tool: str, workspace_id: str | None, status: str) -> None:
        """Record a tool call."""
        with self._lock:
            key = f"{tool}:{workspace_id or 'none'}:{status}"
            self._tool_calls[key][status] += 1

    def record_tool_latency(self, tool: str, latency_seconds: float) -> None:
        """Record tool latency."""
        with self._lock:
            self._tool_latencies[tool].append(latency_seconds)

    def set_workspace_state(self, workspace_id: str, state: str) -> None:
        """Set workspace state."""
        with self._lock:
            self._workspace_states[workspace_id] = state

    def set_cache_bytes(self, workspace_id: str, bytes: int) -> None:
        """Set cache bytes for workspace."""
        with self._lock:
            self._cache_bytes[workspace_id] = bytes

    def record_cache_hit(self, workspace_id: str) -> None:
        """Record cache hit."""
        with self._lock:
            self._cache_hits[workspace_id] += 1

    def record_cache_miss(self, workspace_id: str) -> None:
        """Record cache miss."""
        with self._lock:
            self._cache_misses[workspace_id] += 1

    def record_mount_duration(self, workspace_id: str, duration_seconds: float) -> None:
        """Record mount duration."""
        with self._lock:
            self._mount_durations[workspace_id].append(duration_seconds)

    def record_eviction(self, reason: str) -> None:
        """Record workspace eviction."""
        with self._lock:
            self._evictions[reason] += 1

    def set_inflight(self, scope: str, workspace_id: str | None, count: int) -> None:
        """Set inflight request count."""
        with self._lock:
            key = f"{scope}:{workspace_id or 'none'}"
            self._inflight[key] = count

    def record_artifact_load(self, workspace_id: str, artifact_type: str, status: str) -> None:
        """Record artifact load."""
        with self._lock:
            key = (workspace_id, artifact_type)
            self._artifact_loads[key][status] += 1

    def record_checksum_mismatch(self, workspace_id: str) -> None:
        """Record checksum mismatch."""
        with self._lock:
            self._checksum_mismatches[workspace_id] += 1

    def set_cross_index_stats(self, bytes: int, workspaces: int) -> None:
        """Set cross-index stats."""
        with self._lock:
            self._cross_index_bytes = bytes
            self._cross_index_workspaces = workspaces

    def generate_prometheus(self) -> str:
        """Generate Prometheus text format metrics."""
        lines = []
        uptime = time.time() - self._start_time

        lines.append(f"# HELP batho_uptime_seconds Hub uptime in seconds")
        lines.append(f"# TYPE batho_uptime_seconds gauge")
        lines.append(f"batho_uptime_seconds {uptime:.2f}")

        lines.append("")
        lines.append(f"# HELP batho_mcp_tool_calls_total Total MCP tool calls")
        lines.append(f"# TYPE batho_mcp_tool_calls_total counter")
        for key, statuses in self._tool_calls.items():
            tool, workspace, status = key.split(":")
            for s, count in statuses.items():
                labels = f'tool="{tool}",workspace="{workspace}",status="{s}"'
                lines.append(f"batho_mcp_tool_calls_total{{{labels}}} {count}")

        lines.append("")
        lines.append(f"# HELP batho_mcp_tool_latency_seconds MCP tool latency")
        lines.append(f"# TYPE batho_mcp_tool_latency_seconds histogram")
        for tool, latencies in self._tool_latencies.items():
            if latencies:
                latencies_sorted = sorted(latencies)
                buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
                bucket_counts = {}
                for b in buckets:
                    count = sum(1 for l in latencies_sorted if l <= b)
                    bucket_counts[b] = count

                lines.append(f"# TYPE batho_mcp_tool_latency_seconds bucket")
                for b in buckets:
                    lines.append(f'batho_mcp_tool_latency_seconds{{tool="{tool}",le="{b}"}} {bucket_counts[b]}')
                lines.append(f'batho_mcp_tool_latency_seconds{{tool="{tool}",le="+Inf"}} {len(latencies_sorted)}')
                lines.append(f"# TYPE batho_mcp_tool_latency_seconds_sum gauge")
                lines.append(f'batho_mcp_tool_latency_seconds_sum{{tool="{tool}"}} {sum(latencies):.6f}')
                lines.append(f"# TYPE batho_mcp_tool_latency_seconds_count gauge")
                lines.append(f'batho_mcp_tool_latency_seconds_count{{tool="{tool}"}} {len(latencies)}')

        lines.append("")
        lines.append(f"# HELP batho_workspaces_total Total workspaces by state")
        lines.append(f"# TYPE batho_workspaces_total gauge")
        state_counts: dict[str, int] = defaultdict(int)
        for state in self._workspace_states.values():
            state_counts[state] += 1
        for state, count in state_counts.items():
            lines.append(f'batho_workspaces_total{{state="{state}"}} {count}')

        lines.append("")
        lines.append(f"# HELP batho_workspaces_resident Current resident workspaces")
        lines.append(f"# TYPE batho_workspaces_resident gauge")
        resident_count = sum(1 for s in self._workspace_states.values() if s == "ready")
        lines.append(f"batho_workspaces_resident {resident_count}")

        lines.append("")
        lines.append(f"# HELP batho_artifact_cache_bytes Artifact cache size in bytes")
        lines.append(f"# TYPE batho_artifact_cache_bytes gauge")
        for ws, bytes in self._cache_bytes.items():
            lines.append(f'batho_artifact_cache_bytes{{workspace="{ws}"}} {bytes}')

        lines.append("")
        lines.append(f"# HELP batho_artifact_cache_hit_ratio Cache hit ratio")
        lines.append(f"# TYPE batho_artifact_cache_hit_ratio gauge")
        for ws in set(self._cache_hits.keys()) | set(self._cache_misses.keys()):
            hits = self._cache_hits.get(ws, 0)
            misses = self._cache_misses.get(ws, 0)
            total = hits + misses
            ratio = hits / total if total > 0 else 0
            lines.append(f'batho_artifact_cache_hit_ratio{{workspace="{ws}"}} {ratio:.4f}')

        lines.append("")
        lines.append(f"# HELP batho_mount_duration_seconds Workspace mount duration")
        lines.append(f"# TYPE batho_mount_duration_seconds histogram")
        for ws, durations in self._mount_durations.items():
            if durations:
                durations_sorted = sorted(durations)
                buckets = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
                bucket_counts = {}
                for b in buckets:
                    count = sum(1 for d in durations_sorted if d <= b)
                    bucket_counts[b] = count

                lines.append(f"# TYPE batho_mount_duration_seconds bucket")
                for b in buckets:
                    lines.append(f'batho_mount_duration_seconds{{workspace="{ws}",le="{b}"}} {bucket_counts[b]}')
                lines.append(f'batho_mount_duration_seconds{{workspace="{ws}",le="+Inf"}} {len(durations_sorted)}')
                lines.append(f"# TYPE batho_mount_duration_seconds_sum gauge")
                lines.append(f'batho_mount_duration_seconds_sum{{workspace="{ws}"}} {sum(durations):.6f}')
                lines.append(f"# TYPE batho_mount_duration_seconds_count gauge")
                lines.append(f'batho_mount_duration_seconds_count{{workspace="{ws}"}} {len(durations)}')

        lines.append("")
        lines.append(f"# HELP batho_evictions_total Total workspace evictions")
        lines.append(f"# TYPE batho_evictions_total counter")
        for reason, count in self._evictions.items():
            lines.append(f'reason="{reason}"}} {count}')

        lines.append("")
        lines.append(f"# HELP batho_inflight Current inflight requests")
        lines.append(f"# TYPE batho_inflight gauge")
        for key, count in self._inflight.items():
            scope, workspace = key.split(":")
            lines.append(f'scope="{scope}",workspace="{workspace}"}} {count}')

        lines.append("")
        lines.append(f"# HELP batho_artifact_loads_total Total artifact loads")
        lines.append(f"# TYPE batho_artifact_loads_total counter")
        for (ws, artifact_type), statuses in self._artifact_loads.items():
            for status, count in statuses.items():
                lines.append(f'workspace="{ws}",type="{artifact_type}",status="{status}"}} {count}')

        lines.append("")
        lines.append(f"# HELP batho_checksum_mismatch_total Total checksum mismatches")
        lines.append(f"# TYPE batho_checksum_mismatch_total counter")
        for ws, count in self._checksum_mismatches.items():
            lines.append(f'workspace="{ws}"}} {count}')

        lines.append("")
        lines.append(f"# HELP batho_cross_index_bytes Cross-repo index size in bytes")
        lines.append(f"# TYPE batho_cross_index_bytes gauge")
        lines.append(f"batho_cross_index_bytes {self._cross_index_bytes}")

        lines.append("")
        lines.append(f"# HELP batho_cross_index_workspaces Cross-repo index workspace count")
        lines.append(f"# TYPE batho_cross_index_workspaces gauge")
        lines.append(f"batho_cross_index_workspaces {self._cross_index_workspaces}")

        return "\n".join(lines)


_global_collector: TelemetryCollector | None = None


def get_collector() -> TelemetryCollector:
    """Get the global telemetry collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = TelemetryCollector()
    return _global_collector


def reset_collector() -> None:
    """Reset the global collector (for testing)."""
    global _global_collector
    _global_collector = TelemetryCollector()
