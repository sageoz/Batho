"""Tests for the file_connectivity MCP tool (T21).

Scenario:
    file_connectivity returns file-level dependencies in both directions,
    with cross-file stub references resolved to their defining files.

Execution Flow:
    1. Build the sample artifact (main.py imports utils/models).
    2. Query outgoing connectivity for main.py.
    3. Query incoming connectivity for utils.py.
    4. Verify direction filtering, external grouping, and error handling.

Expectations:
    - main.py depends_on contains utils.py and models.py.
    - utils.py depended_on_by contains main.py.
    - Unknown files return the standard "File not indexed" error.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from batho.mcp.tools import _get_reader


def _run_tool(built_artifact: Path, tmp_path: Path, tool: str, args: dict):
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")
    return asyncio.run(app.call_tool(tool, args))


def _structured(result) -> dict:
    if hasattr(result, "structured_content") and result.structured_content:
        return result.structured_content
    return {}


def _content(result) -> str:
    if hasattr(result, "content") and result.content:
        return result.content[0].text
    return str(result)


class TestFileConnectivity:
    def test_outgoing_dependencies(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
            "direction": "outgoing",
        })
        structured = _structured(result)
        assert "error" not in structured
        dep_files = {d["file"] for d in structured.get("depends_on", [])}
        assert "utils.py" in dep_files
        assert "models.py" in dep_files

    def test_incoming_dependencies(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "utils.py",
            "direction": "incoming",
        })
        structured = _structured(result)
        assert "error" not in structured
        by_files = {d["file"] for d in structured.get("depended_on_by", [])}
        assert "main.py" in by_files

    def test_direction_filter_excludes_other_side(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
            "direction": "outgoing",
        })
        structured = _structured(result)
        assert structured.get("depended_on_by") == []

    def test_markdown_lists_both_sections(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
        })
        content = _content(result)
        assert "### Depends on" in content
        assert "### Depended on by" in content

    def test_external_grouping(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
            "include_external": True,
        })
        structured = _structured(result)
        external = structured.get("external", {})
        assert "stdlib" in external
        assert "unresolved_count" in external

    def test_invalid_direction_rejected(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
            "direction": "sideways",
        })
        content = _content(result)
        assert "Invalid" in content or "error" in _structured(result)

    def test_file_not_indexed(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "nonexistent.py",
        })
        content = _content(result)
        assert "File not indexed" in content


class TestGetFileGraphDependencies:
    def test_structured_output_has_file_dependencies(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "get_file_graph", {
            "file_path": "main.py",
        })
        structured = _structured(result)
        deps = structured.get("file_dependencies")
        assert deps is not None
        out_files = {d["file"] for d in deps.get("outgoing", [])}
        assert "utils.py" in out_files
        assert "models.py" in out_files

    def test_graph_query_incoming_cross_file(self, built_artifact: Path, tmp_path: Path):
        """Regression: graph_query(incoming) on utils.py must now return the
        cross-file CALLS edge from main.py (stored as a stub under main.py)."""
        result = _run_tool(built_artifact, tmp_path, "graph_query", {
            "file_path": "utils.py",
            "relation_direction": "incoming",
            "limit": 100,
        })
        structured = _structured(result)
        graph = structured.get("graph", {})
        edges = graph.get("edges", [])
        cross = [
            e for e in edges
            if e.get("target_file") == "utils.py" and e.get("source_file") == "main.py"
        ]
        assert cross, f"Expected cross-file incoming edges for utils.py, got {len(edges)} edges"

    def test_edge_dicts_carry_resolved_files(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "graph_query", {
            "file_path": "main.py",
            "relation_direction": "outgoing",
            "limit": 100,
        })
        structured = _structured(result)
        edges = structured.get("graph", {}).get("edges", [])
        assert edges, "Expected edges for main.py"
        annotated = [e for e in edges if "target_file" in e]
        assert len(annotated) == len(edges)
        assert any(e["target_file"] == "utils.py" for e in edges)


class TestExternalStdlibRoots:
    """Round-4 fix: stdlib roots come from the resolver's stub_fqn parse.

    New-format stubs carry a dot-normalized ref key, so a Rust stdlib ref
    (``unresolved:scope::std.io.Write``) extracts root ``std`` instead of the
    bare last segment (``Write``). Legacy stubs (``::`` inside the ref key)
    keep their degraded behavior — pinned at the resolver level in
    test_entity_resolution.py (a rebuild normalizes the IDs).
    """

    @pytest.fixture
    def stdlib_artifact(self, tmp_path: Path) -> Path:
        from batho.orchestrator.build import run_build, BuildOptions

        root = tmp_path / "stdlib_repo"
        root.mkdir()
        (root / "main.py").write_text(
            "import os\n"
            "import sys\n"
            "\n"
            "def main():\n"
            "    return os.getcwd(), sys.argv\n",
            encoding="utf-8",
        )
        result = run_build(BuildOptions(root=root, force_full=True))
        assert result.success, f"Build failed: {result.warnings}"
        return root

    def test_python_stdlib_roots_reported(self, stdlib_artifact: Path, tmp_path: Path):
        result = _run_tool(stdlib_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
            "include_external": True,
        })
        structured = _structured(result)
        external = structured.get("external", {})
        assert "os" in external.get("stdlib", [])
        assert "sys" in external.get("stdlib", [])

    def test_stdlib_list_sorted_deduped(self, stdlib_artifact: Path, tmp_path: Path):
        result = _run_tool(stdlib_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
            "include_external": True,
        })
        structured = _structured(result)
        external = structured.get("external", {})
        stdlib = external.get("stdlib", [])
        assert stdlib == sorted(set(stdlib)), "stdlib roots must be sorted and deduped"
        assert isinstance(external.get("unresolved_count"), int)

    def test_markdown_renders_external_section(self, stdlib_artifact: Path, tmp_path: Path):
        result = _run_tool(stdlib_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
            "include_external": True,
        })
        content = _content(result)
        assert "### External" in content
        assert "os" in content

    def test_rust_root_extraction_composition(self):
        """The tool extracts the stdlib root via stub_fqn (single parse)."""
        from batho.mcp.entity_resolution import stub_fqn

        assert stub_fqn("unresolved:run().::std.io.Write").split(".")[0] == "std"
        assert stub_fqn("unresolved:scope::os.path.join").split(".")[0] == "os"
        # Degenerate IDs yield an empty root, which the tool must skip.
        assert stub_fqn("unresolved:scope::").split(".")[0] == ""


class TestViaDirectionAwareNaming:
    """Round-4 fix: the per-cell `via` list is direction-aware.

    Outgoing cells name the referenced (remote) symbol; incoming cells name
    the referencing (caller-side) symbol.
    """

    def test_outgoing_via_names_referenced_symbol(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
            "direction": "outgoing",
        })
        structured = _structured(result)
        by_file = {d["file"]: d for d in structured.get("depends_on", [])}
        calls = by_file["utils.py"]["relations"]["CALLS"]
        # The stub's name is the module-qualified ref (FIX 10 import
        # qualification): "utils.helper". It must name the remote symbol.
        assert calls["via"] and all("helper" in v for v in calls["via"]), (
            f"outgoing via must name the referenced symbol, got {calls['via']}"
        )

    def test_incoming_via_names_caller_symbol(self, built_artifact: Path, tmp_path: Path):
        """depended_on_by must name the caller-side symbol (main), not the
        referenced local symbol (helper)."""
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "utils.py",
            "direction": "incoming",
        })
        structured = _structured(result)
        by_file = {d["file"]: d for d in structured.get("depended_on_by", [])}
        calls = by_file["main.py"]["relations"]["CALLS"]
        assert "main" in calls["via"], (
            f"incoming via must name the caller-side symbol, got {calls['via']}"
        )
        assert "helper" not in calls["via"], (
            "incoming via must not name the referenced (local) symbol"
        )

    def test_markdown_incoming_via_renders_caller_name(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "utils.py",
        })
        content = _content(result)
        assert "(via main)" in content

    def test_no_empty_via_entries(self, built_artifact: Path, tmp_path: Path):
        result = _run_tool(built_artifact, tmp_path, "file_connectivity", {
            "file_path": "main.py",
        })
        structured = _structured(result)
        for section in ("depends_on", "depended_on_by"):
            for dep in structured.get(section, []):
                for cell in dep["relations"].values():
                    assert all(v for v in cell["via"]), (
                        f"empty via entry in {section}: {cell['via']}"
                    )
