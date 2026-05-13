"""Unit tests for BSGMap JSON renderers (render_overview_json, render_files_json)."""

from __future__ import annotations

import pytest

from batho.context.bsg_map import BSGMap
from batho.context.schema import Entity, EntityType


@pytest.fixture
def sample_bsg_map() -> BSGMap:
    """Build a BSGMap with a mix of source, doc, and config files."""
    return BSGMap(
        _root="/tmp/test-repo",
        _by_file={
            "src/app.py": [
                Entity(
                    type=EntityType.FUNCTION,
                    name="main",
                    file="src/app.py",
                    start_line=1,
                    end_line=10,
                    metadata={"bsg.category": "SOURCE", "language": "python"},
                ),
                Entity(
                    type=EntityType.CLASS,
                    name="App",
                    file="src/app.py",
                    start_line=12,
                    end_line=25,
                    metadata={"bsg.category": "SOURCE", "language": "python"},
                ),
            ],
            "src/utils.py": [
                Entity(
                    type=EntityType.FUNCTION,
                    name="helper",
                    file="src/utils.py",
                    start_line=1,
                    end_line=5,
                    metadata={"bsg.category": "SOURCE", "language": "python"},
                ),
            ],
            "README.md": [
                Entity(
                    type=EntityType.DOCUMENT,
                    name="README",
                    file="README.md",
                    start_line=1,
                    end_line=20,
                    metadata={"bsg.category": "DOC"},
                ),
                Entity(
                    type=EntityType.SECTION,
                    name="Installation",
                    file="README.md",
                    start_line=3,
                    end_line=8,
                    metadata={"bsg.category": "DOC"},
                ),
            ],
            "pyproject.toml": [
                Entity(
                    type=EntityType.SETTING,
                    name="project",
                    file="pyproject.toml",
                    start_line=1,
                    end_line=5,
                    metadata={"bsg.category": "CONFIG"},
                ),
            ],
        },
        _dependencies={
            "src/app.py": ["import:./utils.py"],
            "src/utils.py": ["import:os"],
        },
    )


class TestRenderOverviewJson:
    def test_schema_version(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json(
            repo_name="test-repo",
            timestamp="2026-05-06T15:40:29Z",
        )
        assert result["schema_version"] == "context-overview.v1"
        assert result["repo"] == "test-repo"
        assert result["generated_at"] == "2026-05-06T15:40:29Z"

    def test_summary_totals(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json()
        summary = result["summary"]
        assert summary["total_files"] == 4
        assert summary["total_entities"] == 6
        assert summary["total_relationships"] == 2  # 1 dep for app.py + 1 for utils.py

    def test_file_distribution(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json()
        fd = result["file_distribution"]
        assert len(fd) == 3

        source = next((c for c in fd if c["category"] == "Source"), None)
        assert source is not None
        assert source["files"] == 2
        assert source["entities"] == 3

        docs = next((c for c in fd if c["category"] == "Docs"), None)
        assert docs is not None
        assert docs["files"] == 1
        assert docs["entities"] == 2

        config = next((c for c in fd if c["category"] == "Config"), None)
        assert config is not None
        assert config["files"] == 1
        assert config["entities"] == 1

    def test_language_breakdown(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json()
        lb = result["language_breakdown"]
        assert len(lb) >= 1
        python = next((l for l in lb if l["language"] == "Python"), None)
        assert python is not None
        assert python["files"] == 2
        assert result["primary_language"] == "Python"

    def test_technology_stack(self, sample_bsg_map: BSGMap):
        stack_info = {
            "languages": ["Python"],
            "frameworks": ["FastAPI"],
            "package_managers": ["pip"],
            "build_tools": ["setuptools"],
            "infra": ["Docker"],
            "other": ["pytest"],
        }
        result = sample_bsg_map.render_overview_json(stack_info=stack_info)
        ts = result["technology_stack"]
        assert ts["languages"] == ["Python"]
        assert ts["frameworks"] == ["FastAPI"]
        assert ts["package_managers"] == ["pip"]
        assert ts["build_tools"] == ["setuptools"]
        assert ts["infra"] == ["Docker"]
        assert ts["other"] == ["pytest"]

    def test_technology_stack_empty_when_no_stack_info(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json()
        ts = result["technology_stack"]
        assert all(len(v) == 0 for v in ts.values())

    def test_directory_structure(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json()
        tree = result["directory_structure"]
        assert tree["name"] == "root"
        assert tree["type"] == "directory"

        src = next((c for c in tree["children"] if c["name"] == "src"), None)
        assert src is not None
        assert src["type"] == "directory"
        assert src.get("label") == "Source Code"

        app_py = next((c for c in src["children"] if c["name"] == "app.py"), None)
        assert app_py is not None
        assert app_py["type"] == "file"

        readme = next((c for c in tree["children"] if c["name"] == "README.md"), None)
        assert readme is not None
        assert readme["type"] == "file"

    def test_entity_statistics(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json()
        stats = result["entity_statistics"]
        by_type = {s["type"]: s["count"] for s in stats}
        assert by_type["function"] == 2
        assert by_type["class"] == 1
        assert by_type["document"] == 1
        assert by_type["section"] == 1
        assert by_type["setting"] == 1

    def test_top_dependencies(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json()
        deps = result["top_dependencies"]
        assert len(deps) == 2
        by_dep = {d["dependency"]: d["references"] for d in deps}
        assert by_dep["import:./utils.py"] == 1
        assert by_dep["import:os"] == 1

    def test_evolution_rules(self, sample_bsg_map: BSGMap):
        rules = [
            {"dont_rule": "skip_legacy_parser", "source": "cli", "timestamp": "2026-01-01"},
            {"dont_rule": "", "source": "test"},  # should be filtered out
            {"source": "no_rule"},  # should be filtered out
        ]
        result = sample_bsg_map.render_overview_json(evolution_rules=rules)
        assert "evolution_rules" in result
        assert len(result["evolution_rules"]) == 1
        assert result["evolution_rules"][0]["rule"] == "skip_legacy_parser"
        assert result["evolution_rules"][0]["source"] == "cli"

    def test_evolution_rules_absent_when_empty(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json(evolution_rules=[])
        assert "evolution_rules" not in result

    def test_no_evolution_rules_without_param(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_overview_json()
        assert "evolution_rules" not in result


class TestRenderFilesJson:
    def test_schema_version(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_files_json(
            repo_name="test-repo",
            timestamp="2026-05-06T15:40:29Z",
        )
        assert result["schema_version"] == "context-files.v1"
        assert result["repo"] == "test-repo"
        assert result["generated_at"] == "2026-05-06T15:40:29Z"

    def test_summary_totals(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_files_json()
        assert result["summary"]["total_files"] == 4
        assert result["summary"]["total_entities"] == 6

    def test_categories_structure(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_files_json()
        cats = result["categories"]
        assert len(cats) == 3
        names = {c["name"] for c in cats}
        assert names == {"Source", "Docs", "Config"}

        source = next((c for c in cats if c["name"] == "Source"), None)
        assert source["file_count"] == 2
        assert source["entity_count"] == 3
        assert len(source["directories"]) >= 1

    def test_entity_breakdown_uses_full_names(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_files_json()
        source = next((c for c in result["categories"] if c["name"] == "Source"), None)
        app_py_dir = next(
            (d for d in source["directories"] if d["path"] == "src/"), None
        )
        app_py = next(
            (f for f in app_py_dir["files"] if f["name"] == "app.py"), None
        )
        breakdown = app_py["entity_summary"]["breakdown"]
        assert "function" in breakdown
        assert "class" in breakdown
        assert "func" not in breakdown
        assert "cls" not in breakdown

    def test_entity_line_ranges_are_integers(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_files_json()
        source = next((c for c in result["categories"] if c["name"] == "Source"), None)
        app_py_dir = next(
            (d for d in source["directories"] if d["path"] == "src/"), None
        )
        app_py = next(
            (f for f in app_py_dir["files"] if f["name"] == "app.py"), None
        )
        for ent in app_py["entities"]:
            assert isinstance(ent["start_line"], int)
            assert isinstance(ent["end_line"], int)
            assert "line_range" not in ent

    def test_dependencies_for_source_files(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_files_json()
        source = next((c for c in result["categories"] if c["name"] == "Source"), None)
        app_py_dir = next(
            (d for d in source["directories"] if d["path"] == "src/"), None
        )
        app_py = next(
            (f for f in app_py_dir["files"] if f["name"] == "app.py"), None
        )
        assert "dependencies" in app_py
        assert app_py["dependencies"] == ["import:./utils.py"]

    def test_no_dependencies_for_non_source_files(self, sample_bsg_map: BSGMap):
        result = sample_bsg_map.render_files_json()
        docs = next((c for c in result["categories"] if c["name"] == "Docs"), None)
        readme_dir = next(
            (d for d in docs["directories"] if d["path"] == "(root)/"), None
        )
        readme = next(
            (f for f in readme_dir["files"] if f["name"] == "README.md"), None
        )
        assert "dependencies" not in readme

    def test_source_file_without_dependencies_omits_key(self, sample_bsg_map: BSGMap):
        """A source file with no recorded deps should not have the dependencies key."""
        bsg = BSGMap(
            _root="/tmp/test-repo",
            _by_file={
                "src/orphan.py": [
                    Entity(
                        type=EntityType.FUNCTION,
                        name="orphan",
                        file="src/orphan.py",
                        start_line=1,
                        end_line=2,
                        metadata={"bsg.category": "SOURCE"},
                    ),
                ],
            },
            _dependencies={},
        )
        result = bsg.render_files_json()
        source = next((c for c in result["categories"] if c["name"] == "Source"), None)
        orphan_dir = next(
            (d for d in source["directories"] if d["path"] == "src/"), None
        )
        orphan = next(
            (f for f in orphan_dir["files"] if f["name"] == "orphan.py"), None
        )
        assert "dependencies" not in orphan
