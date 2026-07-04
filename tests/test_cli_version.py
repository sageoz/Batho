"""Tests for the batho --version CLI flag."""

import pytest

from batho import __version__
from batho_cli import _build_parser


def test_version_flag_prints_version_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    """batho --version prints 'batho <version>' and exits with code 0."""
    parser = _build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "batho" in captured.out
    assert __version__ in captured.out
