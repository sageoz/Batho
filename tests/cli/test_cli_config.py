"""Tests for CLI config loading and --root resolution."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load batho_cli.py from the project root so tests exercise source changes
# without requiring a reinstall of the top-level script.
_ProjectRoot = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_batho_cli_source", _ProjectRoot / "batho_cli.py")
_batho_cli_module = importlib.util.module_from_spec(_spec)
sys.modules["_batho_cli_source"] = _batho_cli_module
_spec.loader.exec_module(_batho_cli_module)  # type: ignore[union-attr]
main = _batho_cli_module.main


def test_main_uses_target_dir_for_config_not_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """main() resolves --root and loads config from the target directory, not CWD.

    Regression for: batho.yaml should be created inside the targeted dir, not the
    directory from which batho is invoked.
    """
    target_dir = tmp_path / "repo"
    target_dir.mkdir()
    invocation_dir = tmp_path / "cwd"
    invocation_dir.mkdir()

    monkeypatch.chdir(invocation_dir)

    mock_func = MagicMock(return_value=0)
    parser_mock = MagicMock()
    parser_mock.parse_args.return_value = MagicMock(
        command="dummy",
        root=target_dir,
        func=mock_func,
    )

    monkeypatch.setattr(sys, "argv", ["batho", "dummy"])

    with patch("_batho_cli_source._build_parser", return_value=parser_mock):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 0

    from batho.core.config import get_active_root
    assert get_active_root() == target_dir.resolve()

    # No batho.yaml should have been created in the invocation directory.
    assert not (invocation_dir / "batho.yaml").exists()
