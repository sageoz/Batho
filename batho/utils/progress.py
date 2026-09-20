"""batho/utils/progress.py — pytest-style progress rendering for long-running commands.

Single rendering seam for `batho build` / `batho patch` phase progress. tqdm-backed on a TTY
(transient `[ NN%]` bar on stderr, throttled by mininterval); one completion line per phase
when stderr is not a TTY (no animation in pipes/CI). Disabled outright for quiet/JSON modes.

The engine is parent-process-only by contract: worker processes never import this module.
tqdm itself is imported lazily so a disabled gate costs no imports and no I/O.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, TextIO

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="utils.progress")

_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "style": "progress",  # progress | classic (count-only, no percentage)
    "mininterval_s": 0.2,
    "show_after_s": 2.0,
    "keepalive_s": 60.0,
}

_DESC_WIDTH = 9  # phase labels are padded to this width: "  extract   [ 45%]"


def _env_no_progress() -> bool:
    """Strict parsing: only 1/true/yes disable. Unlike TQDM_DISABLE, "0" does NOT disable."""
    return os.getenv("BATHO_NO_PROGRESS", "").strip().lower() in {"1", "true", "yes"}


@dataclass
class ProgressGate:
    """Inputs that decide whether any progress is rendered."""

    quiet: bool = False
    json_mode: bool = False
    no_progress: bool = False
    is_tty: bool | None = None  # None → probe sys.stderr at engine construction


class PhaseHandle:
    """Update sink for one phase. Parent-process-only; one phase active at a time."""

    def __init__(
        self, engine: "ProgressEngine", desc: str, total: int | None, unit: str
    ):
        self._engine = engine
        self.desc = desc
        self.total = total
        self.unit = unit
        self._count = 0
        self._bar: Any = None
        self._closed = False
        self._redirect: Any = None
        self._lock = threading.RLock()
        self._start = time.monotonic()
        self._last_emit = self._start
        self._stop_keepalive = threading.Event()
        self._keepalive_thread: threading.Thread | None = None
        if engine._keepalive > 0:
            self._keepalive_thread = threading.Thread(
                target=self._keepalive_loop,
                name=f"batho-progress-{desc}",
                daemon=True,
            )
            self._keepalive_thread.start()

    @property
    def count(self) -> int:
        return self._count

    def update(self, n: int = 1) -> None:
        if n <= 0:
            return
        with self._lock:
            if self._closed:
                return
            self._count += n
            if self._bar is not None:
                self._bar.update(n)
            elif self._engine._is_tty():
                self._maybe_open_bar()

    def set_total(self, total: int) -> None:
        with self._lock:
            if self._closed:
                return
            self.total = total
            if self._bar is not None:
                self._bar.total = total
            elif self._engine._is_tty():
                self._maybe_open_bar()

    def _maybe_open_bar(self) -> None:
        """Caller must hold self._lock."""
        if self._bar is not None or not self.total or self.total <= 0:
            return
        elapsed = time.monotonic() - self._start
        if elapsed < self._engine._show_after:
            return
        from tqdm import tqdm

        stream = self._engine._stream or sys.stderr
        fmt = (
            "  {desc:<9.9} {n_fmt}/{total_fmt}"
            if self._engine._style == "classic"
            else f"  {{desc:<{_DESC_WIDTH}.{_DESC_WIDTH}}} [{{percentage:3.0f}}%] {{n_fmt}}/{{total_fmt}}"
        )
        self._bar = tqdm(
            total=self.total,
            initial=self._count,
            desc=self.desc,
            bar_format=fmt,
            file=stream,
            leave=False,
            mininterval=self._engine._mininterval,
        )
        self._bar.refresh()

    def _keepalive_loop(self) -> None:
        """Time-driven keep-alive for phases that never receive updates.

        Without this, a phase with no per-item callbacks (e.g. community
        detection) is silent for its whole duration in non-TTY mode —
        exactly the frozen-log failure mode keepalive_s exists to prevent.
        Skipped while a bar is rendering: the bar itself is the live indicator.
        """
        keepalive = self._engine._keepalive
        while not self._stop_keepalive.wait(keepalive):
            with self._lock:
                if self._closed or self._bar is not None:
                    continue
                now = time.monotonic()
                if now - self._start < keepalive or now - self._last_emit < keepalive:
                    continue
                self._last_emit = now
            self._emit_line(self._progress_text(running=True))

    def _progress_text(self, running: bool) -> str:
        dur = f"{time.monotonic() - self._start:.1f}s"
        if self.total:
            if running:
                return (
                    f"  {self.desc:<{_DESC_WIDTH}} ... "
                    f"{self._count}/{self.total} {self.unit} ({dur})"
                )
            if self._count >= self.total:
                return f"  {self.desc:<{_DESC_WIDTH}} [100%] {self.total} {self.unit} ({dur})"
            return (
                f"  {self.desc:<{_DESC_WIDTH}} "
                f"{self._count}/{self.total} {self.unit} ({dur})"
            )
        if running:
            return f"  {self.desc:<{_DESC_WIDTH}} ... {self._count} {self.unit} ({dur})"
        if self._count > 0:
            return (
                f"  {self.desc:<{_DESC_WIDTH}} done ({self._count} {self.unit}, {dur})"
            )
        return f"  {self.desc:<{_DESC_WIDTH}} done ({dur})"

    def _emit_line(self, text: str) -> None:
        stream = self._engine._stream or sys.stderr
        print(text, file=stream)

    def close(self, emit: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._stop_keepalive.set()
            bar = self._bar
            redirect = self._redirect
            self._bar = None
            self._redirect = None
        # Join before the completion emit so a in-flight keep-alive line can
        # never interleave with it (the timer checks _closed under the lock).
        thread = self._keepalive_thread
        if thread is not None:
            thread.join(timeout=2.0)
            self._keepalive_thread = None
        if redirect is not None:
            redirect.__exit__(None, None, None)
        if bar is not None:
            bar.close()
        if emit:
            self._emit_line(self._progress_text(running=False))
        if self._engine._active is self:
            self._engine._active = None


class _NullPhaseHandle:
    """No-op sink used when progress is disabled. Zero I/O, zero state."""

    def __init__(self) -> None:
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    def update(self, n: int = 1) -> None:
        return

    def set_total(self, total: int) -> None:
        return

    def close(self, emit: bool = True) -> None:
        return


_NULL = _NullPhaseHandle()


class ProgressEngine:
    """Owns gating, rendering, and phase lifecycle. Construct one per command run."""

    def __init__(
        self,
        gate: ProgressGate | None = None,
        config: dict[str, Any] | None = None,
        stream: TextIO | None = None,
    ):
        self.gate = gate or ProgressGate()
        if _env_no_progress():
            self.gate.no_progress = True
        self._stream = stream

        cfg = dict(_DEFAULTS)
        if config:
            for key in _DEFAULTS:
                if config.get(key) is not None:
                    cfg[key] = config[key]
        if cfg["style"] not in ("progress", "classic"):
            LOGGER.warning("progress_config_invalid", key="style", value=cfg["style"])
            cfg["style"] = _DEFAULTS["style"]
        try:
            cfg["mininterval_s"] = max(float(cfg["mininterval_s"]), 0.0)
            cfg["show_after_s"] = max(float(cfg["show_after_s"]), 0.0)
            cfg["keepalive_s"] = max(float(cfg["keepalive_s"]), 0.0)
        except (TypeError, ValueError):
            LOGGER.warning("progress_config_invalid", config=str(config))
            cfg.update(_DEFAULTS)
        self._style: str = cfg["style"]
        self._mininterval: float = cfg["mininterval_s"]
        self._show_after: float = cfg["show_after_s"]
        self._keepalive: float = cfg["keepalive_s"]
        self._config_enabled: bool = bool(cfg["enabled"])

        self._active: PhaseHandle | None = None
        self.enabled = self._resolve_enabled()

    def _resolve_enabled(self) -> bool:
        # Non-TTY stays enabled: it degrades to one line per phase, not silence.
        if not self._config_enabled:
            return False
        gate = self.gate
        return not (gate.quiet or gate.json_mode or gate.no_progress)

    def _is_tty(self) -> bool:
        if self.gate.is_tty is not None:
            return self.gate.is_tty
        try:
            stream = self._stream or sys.stderr
            if not stream.isatty():
                return False
            # Degenerate terminal (0x0 winsize, some CI ptys/dumb terminals):
            # tqdm would silently render nothing — fall back to line mode.
            import shutil

            size = shutil.get_terminal_size()
            return size.columns > 0 and size.lines > 0
        except Exception:
            return False

    def open_phase(
        self, desc: str, total: int | None = None, unit: str = "files"
    ) -> PhaseHandle:
        if not self.enabled:
            return _NULL
        if self._active is not None:
            self._active.close()
        handle = PhaseHandle(self, desc, total, unit)
        self._active = handle
        if self._is_tty():
            from tqdm.contrib.logging import logging_redirect_tqdm

            handle._redirect = logging_redirect_tqdm()
            handle._redirect.__enter__()
            with handle._lock:
                handle._maybe_open_bar()
        return handle

    @contextmanager
    def phase(
        self, desc: str, total: int | None = None, unit: str = "files"
    ) -> Iterator[PhaseHandle]:
        handle = self.open_phase(desc, total=total, unit=unit)
        try:
            yield handle
        except BaseException:
            handle.close(emit=False)
            raise
        else:
            handle.close(emit=True)

    def log(self, message: str) -> None:
        """Emit a message without corrupting an active bar (clears, prints, redraws)."""
        if self.gate.quiet or self.gate.json_mode:
            return
        stream = self._stream or sys.stderr
        active = self._active
        if active is not None and active._bar is not None:
            active._bar.write(message, file=stream)
        else:
            print(message, file=stream)

    def abort(self) -> None:
        """Force-close any dangling phase (exception paths). Emits nothing."""
        if self._active is not None:
            self._active.close(emit=False)
            self._active = None
