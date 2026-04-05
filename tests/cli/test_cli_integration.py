"""End-to-end CLI integration tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho_cli import main


# ---------------------------------------------------------------------------
# Full workflows via main()
# ---------------------------------------------------------------------------

class TestCLIIntegration:

    def test_index_and_stats(self, simple_python_repo: Path):
        """Index → Stats workflow."""
        rc = main(["index", "--root", str(simple_python_repo), "--verbose"])
        assert rc == 0

        rc = main(["stats", "--root", str(simple_python_repo)])
        assert rc == 0

    def test_index_and_invalidate(self, simple_python_repo: Path):
        """Index → Invalidate workflow."""
        rc = main(["index", "--root", str(simple_python_repo)])
        assert rc == 0

        rc = main(["invalidate", "--root", str(simple_python_repo)])
        assert rc == 0

    def test_index_creates_output_files(self, simple_python_repo: Path):
        """Verify that index creates the expected output files."""
        main(["index", "--root", str(simple_python_repo), "--force"])

        ctn_dir = simple_python_repo / ".ctn"
        assert ctn_dir.exists()

        index_meta = ctn_dir / "index.json"
        assert index_meta.exists()

        meta = json.loads(index_meta.read_text())
        current_id = meta.get("current_index_id")
        assert current_id

        versioned_dir = ctn_dir / current_id
        assert versioned_dir.exists()
        assert (versioned_dir / "graph.json").exists()
        assert (versioned_dir / "bsg.json").exists()

        bsg_payload = json.loads((versioned_dir / "bsg.json").read_text(encoding="utf-8"))
        assert isinstance(bsg_payload.get("quality_warnings"), list)
        assert bsg_payload.get("stats", {}).get("quality_warnings") == len(
            bsg_payload.get("quality_warnings", [])
        )

        # Multi-file context outputs
        context_dir = versioned_dir / "context"
        assert context_dir.exists()
        assert (context_dir / "overview.md").exists()
        assert (context_dir / "architecture.md").exists()
        assert (context_dir / "tests.md").exists()
        assert (context_dir / "docs.md").exists()
        assert (context_dir / "config.md").exists()

    def test_snapshots_empty(self, tmp_path: Path):
        root = tmp_path / "repo"
        root.mkdir()
        rc = main(["snapshots", "--root", str(root)])
        assert rc == 0

    def test_webhook_via_main(self):
        rc = main([
            "webhook",
            "--payload",
            (
                '{"event":"push","ref":"refs/heads/main","after":"abc123",'
                '"repository":{"full_name":"u/r"},"commits":[]}'
            ),
        ])
        assert rc == 0
