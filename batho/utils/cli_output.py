"""CLI-facing output helpers with stdout/stderr separation."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from typing import Any, Callable, Iterator


class CLIOutput:
    """Emit user-facing CLI messages while honoring quiet/json modes."""

    def __init__(self, quiet: bool = False, json_mode: bool = False):
        self.quiet = quiet
        self.json_mode = json_mode

    def configure(
        self, *, quiet: bool | None = None, json_mode: bool | None = None
    ) -> None:
        if quiet is not None:
            self.quiet = quiet
        if json_mode is not None:
            self.json_mode = json_mode

    def classify(self, message: str) -> str:
        text = message.strip().lower()
        if not text:
            return "info"
        if (
            text.startswith("❌")
            or text.startswith("error")
            or text.startswith("fatal")
        ):
            return "error"
        if text.startswith("⚠") or text.startswith("warning"):
            return "warning"
        if text.startswith("✅") or text.startswith("success"):
            return "success"
        return "info"

    def _supports_color(self, stream: Any) -> bool:
        if self.json_mode:
            return False
        if os.getenv("NO_COLOR"):
            return False
        return hasattr(stream, "isatty") and stream.isatty()

    def _emit(
        self,
        message: str,
        *,
        stream: Any,
        respect_quiet: bool,
        color: str | None = None,
        end: str = "\n",
        flush: bool = False,
    ) -> None:
        if respect_quiet and self.quiet:
            return

        rendered = message
        if color and self._supports_color(stream):
            rendered = f"\x1b[{color}m{message}\x1b[0m"

        print(rendered, file=stream, end=end, flush=flush)

    def success(self, message: str, **data: Any) -> None:
        payload = (
            message if not data else f"{message} {json.dumps(data, sort_keys=True)}"
        )
        self._emit(payload, stream=sys.stdout, respect_quiet=True, color="32")

    def error(self, message: str, **data: Any) -> None:
        payload = (
            message if not data else f"{message} {json.dumps(data, sort_keys=True)}"
        )
        self._emit(payload, stream=sys.stderr, respect_quiet=False, color="31")

    def warning(self, message: str, **data: Any) -> None:
        payload = (
            message if not data else f"{message} {json.dumps(data, sort_keys=True)}"
        )
        self._emit(payload, stream=sys.stderr, respect_quiet=True, color="33")

    def info(self, message: str, **data: Any) -> None:
        payload = (
            message if not data else f"{message} {json.dumps(data, sort_keys=True)}"
        )
        self._emit(payload, stream=sys.stdout, respect_quiet=True)

    def json_response(self, data: dict[str, Any]) -> None:
        self._emit(
            json.dumps(data, indent=2),
            stream=sys.stdout,
            respect_quiet=True,
        )

    def write(
        self,
        message: str,
        *,
        stream: Any | None = None,
        end: str = "\n",
        flush: bool = False,
    ) -> None:
        if stream is not None:
            self._emit(
                message, stream=stream, respect_quiet=False, end=end, flush=flush
            )
            return

        kind = self.classify(message)
        if kind == "error":
            self._emit(
                message,
                stream=sys.stderr,
                respect_quiet=False,
                color="31",
                end=end,
                flush=flush,
            )
        elif kind == "warning":
            self._emit(
                message,
                stream=sys.stderr,
                respect_quiet=True,
                color="33",
                end=end,
                flush=flush,
            )
        elif kind == "success":
            self._emit(
                message,
                stream=sys.stdout,
                respect_quiet=True,
                color="32",
                end=end,
                flush=flush,
            )
        else:
            self._emit(
                message, stream=sys.stdout, respect_quiet=True, end=end, flush=flush
            )

    @contextmanager
    def progress(self, total: int, desc: str) -> Iterator[Callable[[int], None]]:
        if self.quiet:
            yield lambda _step=1: None
            return

        current = 0
        self.info(f"{desc}: 0/{total}")

        def _update(step: int = 1) -> None:
            nonlocal current
            current = min(total, current + step)
            self.info(f"{desc}: {current}/{total}")

        try:
            yield _update
        finally:
            if current < total:
                self.info(f"{desc}: {total}/{total}")
