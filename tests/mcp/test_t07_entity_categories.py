"""T07: entity_categories filter in MCP tools.

Tests verify:
  - graph_query(entity_categories=["code"]) returns only CODE-category entities
  - graph_query(entity_categories=["infrastructure"]) returns only INFRASTRUCTURE entities
  - graph_query(entity_categories=["code", "markup"]) returns both code and markup entities
  - graph_query(entity_categories=["invalid"]) returns error with valid category list
  - graph_query(entity_categories=None) returns all entities (backward compat)
  - graph_query(entity_categories=["code"], entity_types=["FUNCTION"]) returns FUNCTION (OR)
  - search_entities(entity_categories=["code"]) filters by code category
  - applied_filters.entity_categories appears in structured output
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from batho.core.schemas import ENTITY_CATEGORIES, EntityCategory


def _call_graph_query(built_artifact: Path, tmp_path: Path, args: dict) -> dict:
    """Helper: call graph_query via MCP and return structured content."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")
    result = asyncio.run(app.call_tool("graph_query", args))
    assert len(result.content) > 0, "Expected content in result"
    text = result.content[0].text
    structured = result.structured_content or {}
    return {"text": text, "structured": structured}


def _call_search_entities(built_artifact: Path, tmp_path: Path, args: dict) -> dict:
    """Helper: call search_entities via MCP and return structured content."""
    from batho.mcp.server import create_app
    app = create_app(root=str(built_artifact), registry_path=tmp_path / "mcp-repos.json")
    result = asyncio.run(app.call_tool("search_entities", args))
    assert len(result.content) > 0, "Expected content in result"
    text = result.content[0].text
    structured = result.structured_content or {}
    return {"text": text, "structured": structured}


class TestGraphQueryEntityCategories:
    """graph_query entity_categories filter tests."""

    def test_code_category_returns_only_code_entities(self, built_artifact: Path, tmp_path: Path):
        """graph_query(entity_categories=['code']) returns only CODE-category entities."""
        code_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.CODE]}
        res = _call_graph_query(built_artifact, tmp_path, {"entity_categories": ["code"]})
        nodes = res["structured"].get("graph", {}).get("nodes", [])
        assert len(nodes) > 0, "Expected at least some code entities"
        for node in nodes:
            etype = node.get("type", "")
            assert etype in code_types, f"Entity {node.get('name')} has type {etype} which is not in CODE category"

    def test_infrastructure_category_returns_only_infra_entities(self, built_artifact: Path, tmp_path: Path):
        """graph_query(entity_categories=['infrastructure']) returns only INFRASTRUCTURE entities."""
        infra_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.INFRASTRUCTURE]}
        res = _call_graph_query(built_artifact, tmp_path, {"entity_categories": ["infrastructure"]})
        nodes = res["structured"].get("graph", {}).get("nodes", [])
        # The sample repo may or may not have infrastructure entities, but if any are returned,
        # they must be in the INFRASTRUCTURE category
        for node in nodes:
            etype = node.get("type", "")
            assert etype in infra_types, f"Entity {node.get('name')} has type {etype} which is not in INFRASTRUCTURE category"

    def test_multiple_categories_returns_union(self, built_artifact: Path, tmp_path: Path):
        """graph_query(entity_categories=['code', 'markup']) returns both code and markup entities."""
        code_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.CODE]}
        markup_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.MARKUP]}
        allowed = code_types | markup_types
        res = _call_graph_query(built_artifact, tmp_path, {"entity_categories": ["code", "markup"]})
        nodes = res["structured"].get("graph", {}).get("nodes", [])
        for node in nodes:
            etype = node.get("type", "")
            assert etype in allowed, f"Entity {node.get('name')} has type {etype} which is not in CODE or MARKUP"

    def test_invalid_category_returns_error(self, built_artifact: Path, tmp_path: Path):
        """graph_query(entity_categories=['invalid']) returns error with valid category list."""
        res = _call_graph_query(built_artifact, tmp_path, {"entity_categories": ["invalid"]})
        text = res["text"]
        assert "Invalid entity_category" in text or "error" in text.lower()
        # Should mention valid categories
        assert "code" in text.lower()

    def test_none_categories_returns_all(self, built_artifact: Path, tmp_path: Path):
        """graph_query(entity_categories=None) returns all entities (backward compat)."""
        res_no_filter = _call_graph_query(built_artifact, tmp_path, {})
        res_none = _call_graph_query(built_artifact, tmp_path, {"entity_categories": None})
        nodes_no_filter = res_no_filter["structured"].get("graph", {}).get("nodes", [])
        nodes_none = res_none["structured"].get("graph", {}).get("nodes", [])
        assert len(nodes_none) == len(nodes_no_filter), "entity_categories=None should not filter"

    def test_categories_with_entity_types_or_semantics(self, built_artifact: Path, tmp_path: Path):
        """graph_query(entity_categories=['code'], entity_types=['FUNCTION']) returns FUNCTION entities (OR)."""
        res = _call_graph_query(built_artifact, tmp_path, {
            "entity_categories": ["code"],
            "entity_types": ["FUNCTION"],
        })
        nodes = res["structured"].get("graph", {}).get("nodes", [])
        # OR semantics: should include all code entities (which includes FUNCTION anyway)
        code_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.CODE]}
        for node in nodes:
            etype = node.get("type", "")
            assert etype in code_types, f"Entity type {etype} should be in CODE category"

    def test_applied_filters_includes_entity_categories(self, built_artifact: Path, tmp_path: Path):
        """Response includes applied_filters.entity_categories in structured output."""
        res = _call_graph_query(built_artifact, tmp_path, {"entity_categories": ["code"]})
        applied = res["structured"].get("meta", {}).get("applied_filters", {})
        assert "entity_categories" in applied
        assert applied["entity_categories"] == ["code"]

    def test_case_insensitive_category(self, built_artifact: Path, tmp_path: Path):
        """Category names are case-insensitive."""
        code_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.CODE]}
        res = _call_graph_query(built_artifact, tmp_path, {"entity_categories": ["CODE"]})
        nodes = res["structured"].get("graph", {}).get("nodes", [])
        assert len(nodes) > 0, "Expected code entities with uppercase category name"
        for node in nodes:
            etype = node.get("type", "")
            assert etype in code_types


class TestSearchEntitiesCategories:
    """search_entities entity_categories filter tests."""

    def test_search_with_code_category(self, built_artifact: Path, tmp_path: Path):
        """search_entities(entity_categories=['code']) filters by code category."""
        code_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.CODE]}
        res = _call_search_entities(built_artifact, tmp_path, {
            "query": ".*",
            "entity_categories": ["code"],
        })
        results = res["structured"].get("results", [])
        for r in results:
            etype = r.get("type", "")
            assert etype in code_types, f"Search result type {etype} should be in CODE category"

    def test_search_invalid_category_returns_error(self, built_artifact: Path, tmp_path: Path):
        """search_entities(entity_categories=['invalid']) returns error."""
        res = _call_search_entities(built_artifact, tmp_path, {
            "query": ".*",
            "entity_categories": ["invalid"],
        })
        text = res["text"]
        assert "Invalid entity_category" in text or "error" in text.lower()

    def test_search_applied_filters_includes_entity_categories(self, built_artifact: Path, tmp_path: Path):
        """T07: search_entities structured output includes applied_filters.entity_categories."""
        res = _call_search_entities(built_artifact, tmp_path, {
            "query": ".*",
            "entity_categories": ["code"],
        })
        meta = res["structured"].get("meta", {})
        assert "applied_filters" in meta, (
            "search_entities structured output should include applied_filters"
        )
        assert meta["applied_filters"].get("entity_categories") == ["code"]

    def test_search_applied_filters_includes_entity_types(self, built_artifact: Path, tmp_path: Path):
        """T04/T07 parity: search_entities reports entity_types in applied_filters."""
        res = _call_search_entities(built_artifact, tmp_path, {
            "query": ".*",
            "entity_types": ["FUNCTION"],
        })
        meta = res["structured"].get("meta", {})
        assert "applied_filters" in meta
        assert meta["applied_filters"].get("entity_types") == ["FUNCTION"]

    def test_search_no_applied_filters_when_none(self, built_artifact: Path, tmp_path: Path):
        """search_entities omits applied_filters when no filters are active."""
        res = _call_search_entities(built_artifact, tmp_path, {"query": ".*"})
        meta = res["structured"].get("meta", {})
        assert "applied_filters" not in meta


class TestCategoryExpansionHelper:
    """Unit tests for the _expand_entity_categories helper."""

    def test_expand_code_category(self):
        from batho.mcp.tools import _expand_entity_categories
        merged, err = _expand_entity_categories(["code"], None)
        assert err is None
        assert merged is not None
        code_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.CODE]}
        assert set(merged) == code_types

    def test_expand_multiple_categories(self):
        from batho.mcp.tools import _expand_entity_categories
        merged, err = _expand_entity_categories(["code", "markup"], None)
        assert err is None
        code_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.CODE]}
        markup_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.MARKUP]}
        assert set(merged) == code_types | markup_types

    def test_expand_with_entity_types_or(self):
        from batho.mcp.tools import _expand_entity_categories
        merged, err = _expand_entity_categories(["code"], ["EXTERNAL_SYMBOL"])
        assert err is None
        code_types = {et.name for et in ENTITY_CATEGORIES[EntityCategory.CODE]}
        assert set(merged) == code_types | {"EXTERNAL_SYMBOL"}

    def test_expand_invalid_category(self):
        from batho.mcp.tools import _expand_entity_categories
        merged, err = _expand_entity_categories(["invalid"], None)
        assert merged is None
        assert err is not None

    def test_expand_none_returns_entity_types(self):
        from batho.mcp.tools import _expand_entity_categories
        merged, err = _expand_entity_categories(None, ["FUNCTION", "CLASS"])
        assert err is None
        # 9b1e47c2: values are normalized to uppercase and sorted (matching
        # the category-merge path) so applied_filters output is consistent.
        assert merged == ["CLASS", "FUNCTION"]

    def test_expand_none_both(self):
        from batho.mcp.tools import _expand_entity_categories
        merged, err = _expand_entity_categories(None, None)
        assert err is None
        assert merged is None
