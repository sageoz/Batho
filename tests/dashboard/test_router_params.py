"""Tests for the dashboard router's `:param` pattern support."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).parent / "_run_router.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node interpreter not available"
)


def test_router_resolves_param_routes() -> None:
    result = subprocess.run(
        ["node", str(HARNESS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"node harness failed: stderr={result.stderr!r} stdout={result.stdout!r}"
    )

    calls = json.loads(result.stdout)
    assert len(calls) == 4, calls

    assert calls[0]["route"] == "#/hypergraph"
    assert calls[0]["params"] == {}

    assert calls[1]["route"] == "#/hypergraph/file/:fileId"
    assert calls[1]["params"]["fileId"] == "src/auth/login.py"

    assert calls[2]["route"] == "#/hypergraph/node/:nodeId"
    assert calls[2]["params"]["nodeId"] == "some-id-123"

    # Unknown route falls back to the wildcard handler.
    assert calls[3]["route"] == "*"
    assert calls[3]["path"] == "#/does-not-exist"
