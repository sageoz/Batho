"""Tests for review-fix issues: c46e8dc5, 7cb5d304, 19f68a40.

- c46e8dc5: Parsing config propagation (registry + E2E build with extract_parameters)
- 7cb5d304: Schema resource includes entity_categories
- 19f68a40: ExtractionConfig defaults and overrides
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from batho.core.schemas import EntityCategory, ENTITY_CATEGORIES, EntityType


# ---------------------------------------------------------------------------
# c46e8dc5: Parsing config propagation
# ---------------------------------------------------------------------------


class TestParsingConfigPropagation:
    """Registry-level tests that get_extractor() respects set_parsing_config."""

    def test_set_parsing_config_exists_on_extractor(self):
        """ASTExtractor instances have set_parsing_config method."""
        from batho.modules.extraction.submodules.parser_factory.factory import create_extractor
        from batho.modules.extraction.submodules.parser_factory._queries import PYTHON_QUERY
        extractor = create_extractor("python", PYTHON_QUERY)
        assert hasattr(extractor, "set_parsing_config")

    def test_registry_propagates_config_to_new_extractor(self):
        """get_extractor() after set_parsing_config() returns extractor with config."""
        from batho.modules.extraction.submodules.parser_factory.registry import (
            set_parsing_config,
            get_extractor,
            _instances,
        )
        # Clear cache to force new instance creation
        _instances.clear()
        set_parsing_config({"extract_parameters": True})
        ext = get_extractor(".py")
        assert ext is not None
        assert ext._parsing_config.get("extract_parameters") is True

    def test_registry_updates_cached_extractor(self):
        """set_parsing_config() updates already-cached extractor instances."""
        from batho.modules.extraction.submodules.parser_factory.registry import (
            set_parsing_config,
            get_extractor,
            _instances,
        )
        # Get an extractor (caches it)
        ext = get_extractor(".py")
        assert ext is not None
        # Change config
        set_parsing_config({"extract_parameters": True, "extract_type_parameters": True})
        # Cached instance should be updated
        assert ext._parsing_config.get("extract_parameters") is True
        assert ext._parsing_config.get("extract_type_parameters") is True
        # Reset for other tests
        set_parsing_config({})

    def test_e2e_build_with_extract_parameters(self, tmp_path: Path):
        """Build with extraction.extract_parameters=true emits PARAMETER entities."""
        from batho.orchestrator.build import run_build, BuildOptions

        root = tmp_path / "test_repo"
        root.mkdir()
        (root / "main.py").write_text(
            "def foo(a, b):\n    return a + b\n",
            encoding="utf-8",
        )
        (root / "batho.yaml").write_text(
            "schema_version: batho-config.v1\nextraction:\n  extract_parameters: true\n",
            encoding="utf-8",
        )

        result = run_build(BuildOptions(root=root, force_full=True))
        assert result.success, f"Build failed: {result.warnings}"

        from batho.mcp.tools import _get_reader
        reader = _get_reader(str(root))
        table = reader._get_table("agent_views")
        types = set(table.column("entity_type").to_pylist())
        assert "PARAMETER" in types, f"Expected PARAMETER in entity types, got: {sorted(types)}"

    def test_e2e_build_without_extract_parameters(self, tmp_path: Path):
        """Build with default config (extract_parameters=false) does NOT emit PARAMETER entities."""
        from batho.orchestrator.build import run_build, BuildOptions

        root = tmp_path / "test_repo"
        root.mkdir()
        (root / "main.py").write_text(
            "def foo(a, b):\n    return a + b\n",
            encoding="utf-8",
        )

        result = run_build(BuildOptions(root=root, force_full=True))
        assert result.success, f"Build failed: {result.warnings}"

        from batho.mcp.tools import _get_reader
        reader = _get_reader(str(root))
        table = reader._get_table("agent_views")
        types = set(table.column("entity_type").to_pylist())
        assert "PARAMETER" not in types, f"PARAMETER should not be emitted by default, got: {sorted(types)}"


# ---------------------------------------------------------------------------
# 7cb5d304: Schema resource includes entity_categories
# ---------------------------------------------------------------------------


class TestSchemaResourceEntityCategories:
    """batho://schema resource returns entity_categories."""

    def test_schema_resource_includes_entity_categories(self, tmp_path: Path):
        """batho://schema resource includes entity_categories with all 5 categories."""
        from batho.mcp.server import create_app
        app = create_app(root=str(tmp_path), registry_path=tmp_path / "mcp-repos.json")

        result = asyncio.run(app.read_resource("batho://schema"))
        content = result.contents[0].content if hasattr(result, "contents") else str(result)
        schema = json.loads(content)
        assert "entity_categories" in schema, "Schema should include entity_categories"

        categories = schema["entity_categories"]
        expected_cats = {c.name.lower() for c in EntityCategory}
        assert set(categories.keys()) == expected_cats, (
            f"Expected categories {expected_cats}, got {set(categories.keys())}"
        )

    def test_schema_resource_entity_categories_have_member_types(self, tmp_path: Path):
        """Each entity_category in schema maps to a list of EntityType names."""
        from batho.mcp.server import create_app
        app = create_app(root=str(tmp_path), registry_path=tmp_path / "mcp-repos.json")

        result = asyncio.run(app.read_resource("batho://schema"))
        content = result.contents[0].content if hasattr(result, "contents") else str(result)
        schema = json.loads(content)
        categories = schema["entity_categories"]

        for cat_name, member_types in categories.items():
            assert isinstance(member_types, list), f"{cat_name} should map to a list"
            assert len(member_types) > 0, f"{cat_name} should have at least one member type"
            # Verify the member types match ENTITY_CATEGORIES
            cat = EntityCategory[cat_name.upper()]
            expected = {et.name for et in ENTITY_CATEGORIES[cat]}
            assert set(member_types) == expected, (
                f"{cat_name} members mismatch: expected {expected}, got {set(member_types)}"
            )

    def test_schema_resource_code_category_includes_new_types(self, tmp_path: Path):
        """CODE category in schema includes CONSTRUCTOR, ENUM_MEMBER, PARAMETER, TYPE_PARAMETER."""
        from batho.mcp.server import create_app
        app = create_app(root=str(tmp_path), registry_path=tmp_path / "mcp-repos.json")

        result = asyncio.run(app.read_resource("batho://schema"))
        content = result.contents[0].content if hasattr(result, "contents") else str(result)
        schema = json.loads(content)
        code_types = set(schema["entity_categories"]["code"])
        for new_type in ("CONSTRUCTOR", "ENUM_MEMBER", "PARAMETER", "TYPE_PARAMETER"):
            assert new_type in code_types, f"{new_type} should be in CODE category"


# ---------------------------------------------------------------------------
# 19f68a40: ExtractionConfig defaults and overrides
# ---------------------------------------------------------------------------


class TestExtractionConfigFlags:
    """ExtractionConfig model defaults and user overrides."""

    def test_default_extract_parameters_is_false(self):
        """ExtractionConfig.extract_parameters defaults to False."""
        from batho.core.config.models import ExtractionConfig
        cfg = ExtractionConfig()
        assert cfg.extract_parameters is False

    def test_default_extract_type_parameters_is_false(self):
        """ExtractionConfig.extract_type_parameters defaults to False."""
        from batho.core.config.models import ExtractionConfig
        cfg = ExtractionConfig()
        assert cfg.extract_type_parameters is False

    def test_extract_parameters_override(self):
        """ExtractionConfig accepts extract_parameters=True override."""
        from batho.core.config.models import ExtractionConfig
        cfg = ExtractionConfig(extract_parameters=True)
        assert cfg.extract_parameters is True

    def test_extract_type_parameters_override(self):
        """ExtractionConfig accepts extract_type_parameters=True override."""
        from batho.core.config.models import ExtractionConfig
        cfg = ExtractionConfig(extract_type_parameters=True)
        assert cfg.extract_type_parameters is True

    def test_config_model_dump_includes_flags(self):
        """Config.model_dump() includes extraction.extract_parameters and extract_type_parameters."""
        from batho.core.config.models import Config
        cfg_dict = Config().model_dump()
        extraction = cfg_dict.get("extraction", {})
        assert "extract_parameters" in extraction
        assert "extract_type_parameters" in extraction
        assert extraction["extract_parameters"] is False
        assert extraction["extract_type_parameters"] is False
