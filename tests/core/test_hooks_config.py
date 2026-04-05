"""Tests for hooks config loading and pointer behavior."""
from __future__ import annotations

from pathlib import Path

import pytest

from batho.hooks.loader import HooksConfigError, load_hooks_file, resolve_hooks_settings


class TestHooksConfigLoading:
    def test_load_valid_hooks_file(self, tmp_path: Path):
        cfg = tmp_path / ".batho" / "hooks.yaml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            (
                "version: hooks.v1\n"
                "hooks:\n"
                "  pre-commit:\n"
                "    enabled: true\n"
                "    stages:\n"
                "      - run: echo ok\n"
            ),
            encoding="utf-8",
        )

        hooks_file = load_hooks_file(cfg)
        assert "pre-commit" in hooks_file.hooks
        assert hooks_file.hooks["pre-commit"].enabled is True

    def test_load_invalid_schema_version(self, tmp_path: Path):
        cfg = tmp_path / ".batho" / "hooks.yaml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            (
                "version: hooks.v0\n"
                "hooks:\n"
                "  pre-commit:\n"
                "    enabled: true\n"
                "    stages:\n"
                "      - run: echo ok\n"
            ),
            encoding="utf-8",
        )

        with pytest.raises(HooksConfigError):
            load_hooks_file(cfg)

    def test_load_stage_without_template_or_run_fails(self, tmp_path: Path):
        cfg = tmp_path / ".batho" / "hooks.yaml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            (
                "version: hooks.v1\n"
                "hooks:\n"
                "  pre-commit:\n"
                "    enabled: true\n"
                "    stages:\n"
                "      - name: stage-only\n"
            ),
            encoding="utf-8",
        )

        with pytest.raises(HooksConfigError):
            load_hooks_file(cfg)


class TestHooksPointerResolution:
    def test_default_pointer_enabled(self, tmp_path: Path):
        config_path, enabled = resolve_hooks_settings(tmp_path)
        assert enabled is True
        assert config_path == (tmp_path / ".batho" / "hooks.yaml").resolve()

    def test_root_pointer_can_disable(self, tmp_path: Path):
        (tmp_path / "batho.yaml").write_text(
            "hooks:\n  enabled: false\n  include: false\n",
            encoding="utf-8",
        )

        _config_path, enabled = resolve_hooks_settings(tmp_path)
        assert enabled is False
