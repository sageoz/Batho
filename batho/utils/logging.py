"""
batho/utils/logging.py — Structured logging with structlog.

Unified logging entrypoints:
- ``get_logger``: returns a structured, context-bindable logger.
- ``configure_logging``: configures console vs JSON rendering and log level.

This module is the single source of truth for logging across Batho.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import BindableLogger


def get_logger(name: str | None = None, **context: Any) -> BindableLogger:
    """
    Return a structured logger with optional bound context.

    Args:
        name: Module name (typically ``__name__``). If None, structlog uses caller info.
        **context: Key/value context bound to every log entry (e.g., component="index").

    Returns:
        BindableLogger configured via :func:`configure_logging`.
    """

    # Keep logger creation lazy so import-time module loggers don't lock in
    # structlog defaults before configure_logging() runs in CLI entrypoints.
    return structlog.get_logger(name, **context)


# get_context_logger removed in v2.0 - use get_logger directly


def get_log_level(level_name: str = "INFO") -> int:
    """
    Convert a log level name string to its integer constant.

    Args:
        level_name: Log level name (e.g., "DEBUG", "INFO", "WARNING", "ERROR").

    Returns:
        Corresponding ``logging`` integer constant.
    """
    return getattr(logging, level_name.upper(), logging.INFO)


def _coerce_log_level(level: Any) -> int:
    """Normalize string/int log level values to stdlib integer constants."""

    if isinstance(level, int):
        return level
    if isinstance(level, str):
        return get_log_level(level)
    return logging.INFO


def configure_logging(
    level: int | str | dict[str, Any] = logging.INFO,
    json_format: bool | None = None,
    quiet: bool = False,
    file: str | None = None,
    fmt: str = "%(message)s",
) -> None:
    """
    Configure structlog for the process (console for TTY, JSON otherwise by default).

    Accepts either explicit parameters or a config dict as ``level`` with keys:
    ``level``, ``json_format``, ``quiet``, ``file``, and ``format``.

    Args:
        level: Standard library logging level (e.g., ``logging.INFO``) or config dict.
        json_format: Force JSON output when True, force console when False, auto-detect when None.
        quiet: If True, suppress all non-error output (sets level to ERROR).
        file: Optional file path to write logs to.
        fmt: Log format string for stdlib logging.
    """

    if isinstance(level, dict):
        cfg = level
        configured_level = cfg.get("level", logging.INFO)
        json_format = cfg.get("json_format", json_format)
        quiet = bool(cfg.get("quiet", quiet))
        file = cfg.get("file", file)
        fmt = cfg.get("format", fmt)
    else:
        configured_level = level

    normalized_level = _coerce_log_level(configured_level)
    effective_level = logging.ERROR if quiet else normalized_level

    render_json = json_format if json_format is not None else not sys.stderr.isatty()
    renderer = (
        structlog.processors.JSONRenderer()
        if render_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Align stdlib logging with structlog pipeline.
    # All log output goes to stderr to keep stdout clean for user output.
    root_logger = logging.getLogger()
    root_logger.setLevel(effective_level)

    # Remove existing handlers to avoid duplicates on re-configuration
    root_logger.handlers.clear()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter(fmt))
    stderr_handler.setLevel(effective_level)
    root_logger.addHandler(stderr_handler)

    if file:
        file_path = Path(file)
        if file_path.parent and not file_path.parent.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file)
        file_handler.setFormatter(logging.Formatter(fmt))
        file_handler.setLevel(effective_level)
        root_logger.addHandler(file_handler)

    # Keep named stdlib loggers aligned with the chosen process-wide threshold.
    for logger in logging.root.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.setLevel(effective_level)


def configure_logging_from_dict(config: dict[str, Any]) -> None:
    """
    Configure logging from a config dict (as returned by get_config_cached).

    Args:
        config: Dict with keys: level (int), json_format (bool|None),
                quiet (bool), file (str|None), format (str).
    """
    configure_logging(config)
