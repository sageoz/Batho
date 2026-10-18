"""tests/golden/test_golden_metadata.py — T27: byte-identical golden gates.

Builds the tiny fixture repo end-to-end and compares the full metadata
distribution against a stored golden. To regenerate after an intentional
metadata change:

    uv run python -m tests.golden.regenerate

then review the diff (per-file attribution is in the failure output).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from .harness import (
    build_fixture,
    capture_distribution,
    compare_golden,
    load_golden,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "language_packs"
GOLDEN = Path(__file__).resolve().parent / "golden" / "metadata_golden.json"


@pytest.fixture()
def built_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    shutil.copytree(FIXTURE, root)
    assert build_fixture(root), "fixture build failed"
    return root


def test_metadata_distribution_matches_golden(built_fixture: Path):
    actual = capture_distribution(built_fixture)
    golden = load_golden(GOLDEN)
    diffs = compare_golden(golden, actual)
    assert not diffs, "metadata distribution drifted:\n" + "\n".join(diffs[:40])


def test_golden_determinism(built_fixture: Path):
    """Two captures of the same artifact are identical (harness sanity)."""
    a = capture_distribution(built_fixture)
    b = capture_distribution(built_fixture)
    assert a == b
