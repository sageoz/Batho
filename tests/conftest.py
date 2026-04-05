"""
Shared pytest fixtures for Batho test suite.

Provides reusable fixtures for temporary repos, sample data,
config cache management, and pre-built graph objects.
"""
from __future__ import annotations

# Prevent pytest from collecting test files inside testdata sample repos
collect_ignore_glob = ["testdata/*"]

import json
import os
import shutil
import textwrap
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TESTS_DIR = Path(__file__).parent
TESTDATA_DIR = TESTS_DIR / "testdata"
REPOSITORIES_DIR = TESTDATA_DIR / "repositories"
FILES_DIR = TESTDATA_DIR / "files"


# ---------------------------------------------------------------------------
# Config cache cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_config_cache():
    """Clear the LRU config cache before and after every test."""
    from batho.config import get_config_cached

    get_config_cached.cache_clear()
    yield
    get_config_cached.cache_clear()


# ---------------------------------------------------------------------------
# Temporary repository fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_repo(tmp_path: Path):
    """
    Provide a temporary directory pre-seeded as a minimal repo.

    Returns a factory that accepts a dict of {relative_path: content} and
    writes them, then returns the root Path.
    """

    def _make(files: dict[str, str] | None = None) -> Path:
        root = tmp_path / "repo"
        root.mkdir()
        if files:
            for rel, content in files.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
        return root

    return _make


# ---------------------------------------------------------------------------
# Sample repository fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_python_repo() -> Path:
    """Return path to the simple_python sample repository."""
    return REPOSITORIES_DIR / "simple_python"


@pytest.fixture
def multi_lang_repo() -> Path:
    """Return path to the multi_language sample repository."""
    return REPOSITORIES_DIR / "multi_language"


@pytest.fixture
def edge_case_repo() -> Path:
    """Return path to the edge_cases sample repository."""
    return REPOSITORIES_DIR / "edge_cases"


@pytest.fixture
def flask_repo() -> Path:
    """Return path to the Flask sample repository."""
    return REPOSITORIES_DIR / "flask"


@pytest.fixture
def flask_repo_metadata():
    """Load Flask repository metadata."""
    flask_path = REPOSITORIES_DIR / "flask"
    metadata_file = flask_path / "repository_metadata.json"
    if metadata_file.exists():
        import json
        return json.loads(metadata_file.read_text(encoding="utf-8"))
    return None


# ---------------------------------------------------------------------------
# Graph fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_graph():
    """Build a small InMemoryGraph with some entities and relationships."""
    from batho.context.codegraph import InMemoryGraph
    from batho.context.schema import Entity, EntityType, Relationship, RelationshipType

    graph = InMemoryGraph()

    e1 = Entity(
        type=EntityType.FUNCTION,
        name="add",
        file="src/calculator.py",
        start_line=1,
        end_line=3,
        start_byte=0,
        end_byte=50,
        signature="add(a, b)",
        metadata={"language": "python"},
    )
    e2 = Entity(
        type=EntityType.FUNCTION,
        name="subtract",
        file="src/calculator.py",
        start_line=5,
        end_line=7,
        start_byte=52,
        end_byte=110,
        signature="subtract(a, b)",
        metadata={"language": "python"},
    )
    e3 = Entity(
        type=EntityType.CLASS,
        name="Calculator",
        file="src/calculator.py",
        start_line=10,
        end_line=30,
        start_byte=120,
        end_byte=500,
        signature=None,
        metadata={"language": "python"},
    )
    e4 = Entity(
        type=EntityType.FUNCTION,
        name="helper",
        file="src/utils.py",
        start_line=1,
        end_line=5,
        start_byte=0,
        end_byte=60,
        signature="helper(x)",
        metadata={"language": "python"},
    )

    for e in (e1, e2, e3, e4):
        graph.add_entity(e)

    graph.add_relationship(
        Relationship(
            source_id=e4.id,
            target_id=e1.id,
            type=RelationshipType.CALLS,
            metadata={"line_number": 3},
        )
    )
    graph.add_relationship(
        Relationship(
            source_id=e3.id,
            target_id=e1.id,
            type=RelationshipType.CONTAINS,
            metadata={"line_number": 12},
        )
    )

    return graph
