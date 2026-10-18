"""batho_plugin/telemetry.py — per-plugin/stage counters for run stats.

Reuses the ``rule_perf`` plumbing shape (match_calls / total_ns / avg_ns) so
the orchestrator can persist plugin telemetry alongside rule telemetry
(PLUGIN_ARCHITECTURE_SPEC §4.4). All timing uses ``time.perf_counter_ns``;
aggregation is deterministic (sorted keys) per the coding practices (§15.7).
"""

from __future__ import annotations

from typing import Any


class PluginTelemetry:
    """Accumulates per-plugin/per-stage call counts and nanoseconds."""

    def __init__(self) -> None:
        self._calls: dict[str, int] = {}
        self._ns: dict[str, int] = {}
        self._changed: dict[str, int] = {}
        self._errors: dict[str, int] = {}

    @staticmethod
    def _key(plugin_id: str, stage: str) -> str:
        return f"{plugin_id}@{stage}"

    def record(
        self, plugin_id: str, stage: str, ns: int, changed: bool, error: bool = False
    ) -> None:
        """Record one hook invocation."""
        key = self._key(plugin_id, stage)
        self._calls[key] = self._calls.get(key, 0) + 1
        self._ns[key] = self._ns.get(key, 0) + int(ns)
        if changed:
            self._changed[key] = self._changed.get(key, 0) + 1
        if error:
            self._errors[key] = self._errors.get(key, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        """Deterministic stats payload for run_artifacts / score.md."""
        plugins: dict[str, dict[str, int]] = {}
        for key in sorted(self._calls):
            plugin_id, stage = key.split("@", 1)
            calls = self._calls[key]
            total_ns = self._ns.get(key, 0)
            entry = plugins.setdefault(
                plugin_id,
                {"calls": 0, "total_ns": 0, "changed": 0, "errors": 0},
            )
            entry["calls"] += calls
            entry["total_ns"] += total_ns
            entry["changed"] += self._changed.get(key, 0)
            entry["errors"] += self._errors.get(key, 0)
        for entry in plugins.values():
            entry["avg_ns"] = (
                int(entry["total_ns"] / entry["calls"]) if entry["calls"] else 0
            )
        return {"schema_version": "plugin-telemetry.v1", "plugins": plugins}

    def __bool__(self) -> bool:
        return bool(self._calls)
