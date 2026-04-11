"""Append-only iteration/run state ledger."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


class Ledger:
    """Append-only JSONL ledger for iteration state, metrics, and decisions."""

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir
        self._state_dir.mkdir(parents=True, exist_ok=True)

        self._loop_state_path = state_dir / "loop_state.json"
        self._metrics_path = state_dir / "metrics_history.jsonl"
        self._decisions_path = state_dir / "decisions.jsonl"

    # -- Loop state (read/write) --

    def read_loop_state(self) -> dict[str, Any]:
        if not self._loop_state_path.exists():
            return {"iteration": 0, "best_score": 0.0, "status": "initialized"}
        try:
            return json.loads(self._loop_state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"iteration": 0, "best_score": 0.0, "status": "initialized"}

    def write_loop_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp = self._loop_state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._loop_state_path)

    def increment_iteration(self) -> int:
        state = self.read_loop_state()
        state["iteration"] = int(state.get("iteration", 0)) + 1
        state["status"] = "running"
        self.write_loop_state(state)
        return state["iteration"]

    def get_best_score(self) -> float:
        state = self.read_loop_state()
        return float(state.get("best_score", 0.0))

    def update_best_score(self, score: float) -> None:
        state = self.read_loop_state()
        state["best_score"] = score
        self.write_loop_state(state)

    # -- Metrics history (append-only JSONL) --

    def append_metrics(self, iteration: int, metrics: dict[str, Any]) -> None:
        record = {
            "iteration": iteration,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **metrics,
        }
        with self._metrics_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    # -- Decisions history (append-only JSONL) --

    def append_decision(self, decision: dict[str, Any]) -> None:
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **decision,
        }
        with self._decisions_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    # -- Paths --

    @property
    def state_dir(self) -> Path:
        return self._state_dir

    @property
    def loop_state_path(self) -> Path:
        return self._loop_state_path

    @property
    def metrics_path(self) -> Path:
        return self._metrics_path

    @property
    def decisions_path(self) -> Path:
        return self._decisions_path
