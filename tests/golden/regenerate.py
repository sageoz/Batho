"""Regenerate the golden metadata fixture (run from repo root):
    uv run python -m tests.golden.regenerate
"""
import shutil, tempfile, sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, "tests")
    from golden.harness import build_fixture, capture_distribution, save_golden
    src = Path("tests/fixtures/language_packs")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "fixture"
        shutil.copytree(src, root)
        ok = build_fixture(root)
        print("build:", ok)
        dist = capture_distribution(root)
        save_golden(dist, Path("tests/golden/golden/metadata_golden.json"))
        print("entities:", dist["entity_count"], "keys:", len(dist["metadata_keys"]))
        print("cats:", dist["bsg.category"])
