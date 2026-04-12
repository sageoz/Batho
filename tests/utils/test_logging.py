"""Tests for batho.utils.logging module."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
import structlog

from batho.utils.logging import (
    configure_logging,
    get_context_logger,
    get_logger,
)


class TestGetLogger:

    def test_returns_bindable_logger(self):
        logger = get_logger("test_module")
        assert logger is not None

    def test_with_context(self):
        logger = get_logger("test", component="indexer")
        # Should not raise
        assert logger is not None

    def test_without_name(self):
        logger = get_logger()
        assert logger is not None


class TestGetContextLogger:

    def test_alias_works(self):
        logger = get_context_logger(operation="test")
        assert logger is not None


class TestConfigureLogging:

    def test_default_level(self):
        """configure_logging should not raise."""
        configure_logging(logging.INFO)

    def test_json_format_true(self):
        configure_logging(logging.DEBUG, json_format=True)

    def test_json_format_false(self):
        configure_logging(logging.WARNING, json_format=False)

    def test_auto_detect(self):
        configure_logging(logging.INFO, json_format=None)

    def test_config_dict_sets_quiet_and_file_handler(self, tmp_path: Path):
        logfile = tmp_path / "batho.log"
        configure_logging(
            {
                "level": "DEBUG",
                "json_format": False,
                "quiet": True,
                "file": str(logfile),
                "format": "%(levelname)s %(message)s",
            }
        )
        root_logger = logging.getLogger()
        assert root_logger.level == logging.ERROR
        assert any(isinstance(handler, logging.FileHandler) for handler in root_logger.handlers)

    def test_logger_created_before_config_uses_later_threshold(self, capsys: pytest.CaptureFixture[str]):
        logger = get_logger("test_pre_config", component="pre")

        configure_logging(
            {
                "level": "ERROR",
                "json_format": False,
                "quiet": True,
                "file": None,
                "format": "%(message)s",
            }
        )

        logger.debug("debug_should_not_appear")
        logger.info("info_should_not_appear")
        logger.error("error_should_appear")

        captured = capsys.readouterr()
        combined = f"{captured.out}\n{captured.err}"
        assert "debug_should_not_appear" not in combined
        assert "info_should_not_appear" not in combined
        assert "error_should_appear" in combined
