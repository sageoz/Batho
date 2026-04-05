"""
backend/utils/logging.py — Structured logging with structlog.

Unified logging entrypoints:
- ``get_logger``: returns a structured, context-bindable logger.
- ``configure_logging``: configures console vs JSON rendering and log level.

This module is the single source of truth for logging across Batho.
"""

from __future__ import annotations

import logging
import sys
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

    logger = structlog.get_logger(name)
    if context:
        logger = logger.bind(**context)
    return logger


def get_context_logger(**context: Any) -> BindableLogger:
    """Backward-compatible alias for get_logger."""

    return get_logger(**context)


def get_log_level(level_name: str = "INFO") -> int:
    """
    Convert a log level name string to its integer constant.

    Args:
        level_name: Log level name (e.g., "DEBUG", "INFO", "WARNING", "ERROR").

    Returns:
        Corresponding ``logging`` integer constant.
    """
    return getattr(logging, level_name.upper(), logging.INFO)


def configure_logging(level: int = logging.INFO, json_format: bool | None = None) -> None:
    """
    Configure structlog for the process (console for TTY, JSON otherwise by default).

    Args:
        level: Standard library logging level (e.g., ``logging.INFO``).
        json_format: Force JSON output when True, force console when False, auto-detect when None.
    """

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
    logging.basicConfig(level=level, format="%(message)s", force=True)
