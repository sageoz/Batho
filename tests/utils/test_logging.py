"""Tests for batho_core.utils.logging module."""
from __future__ import annotations

import logging

import pytest
import structlog

from batho_core.utils.logging import (
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
