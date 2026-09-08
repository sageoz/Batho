"""Tests for batho.core.schemas Entity/Relationship deserialization."""

from __future__ import annotations

import pytest

from batho.core.schemas import (
    ENTITY_CATEGORIES,
    Entity,
    EntityCategory,
    EntityType,
)


class TestEntityFromDict:
    """BUG-08: Serialized ID must be preserved unconditionally when non-None."""

    def test_from_dict_preserves_regular_id(self):
        """Verify that a regular serialized entity ID is preserved during deserialization.

        Scenario:
            A valid entity dict with a standard compound ID string is passed to Entity.from_dict.
            The resulting entity must retain that exact ID.

        Execution Flow:
            1. Construct an entity dict with a standard compound ID.
            2. Call Entity.from_dict.
            3. Assert both id_override and id match the original serialized value.

        Expectations:
            - Non-None serialized IDs are unconditionally preserved.
        """
        data = {
            "id": "ent|FUNCTION|foo.py|0|10|1|1|bar",
            "type": "function",
            "name": "bar",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override == "ent|FUNCTION|foo.py|0|10|1|1|bar"
        assert entity.id == "ent|FUNCTION|foo.py|0|10|1|1|bar"

    def test_from_dict_preserves_empty_string_id(self):
        """Empty-string IDs are non-None and must be preserved."""
        data = {
            "id": "",
            "type": "function",
            "name": "bar",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override == ""
        assert entity.id == ""

    def test_from_dict_preserves_unresolved_stub_id(self):
        """Unresolved stubs often have opaque IDs like 'unresolved:...'."""
        data = {
            "id": "unresolved:some_symbol",
            "type": "unresolved",
            "name": "some_symbol",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override == "unresolved:some_symbol"
        assert entity.id == "unresolved:some_symbol"

    def test_from_dict_existing_id_override_takes_precedence(self):
        """If id_override is already present in the dict, it wins."""
        data = {
            "id": "from_id_field",
            "id_override": "from_override_field",
            "type": "function",
            "name": "bar",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override == "from_override_field"

    def test_from_dict_none_id_ignored(self):
        """If the serialized id is explicitly None, don't set id_override."""
        data = {
            "id": None,
            "type": "function",
            "name": "bar",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override is None
        assert entity.id == "ent|FUNCTION|foo.py|0|10|1|1|bar"


class TestEntityCategory:
    """T01: EntityCategory enum and EntityType.category property."""

    # Excluded types (deprecated/dead — removed in T13/T14)
    _EXCLUDED_TYPES = frozenset({
        EntityType.UNRESOLVED,
        EntityType.ATTRIBUTE,
        EntityType.GLOBAL_STATEMENT,
        EntityType.IMPORT_BLOCK,
    })

    def test_every_non_excluded_type_has_a_category(self):
        """Every EntityType except deprecated/dead types maps to exactly one category."""
        categorized = set()
        for types in ENTITY_CATEGORIES.values():
            categorized |= types
        all_types = set(EntityType)
        uncategorized = all_types - categorized - self._EXCLUDED_TYPES
        assert not uncategorized, f"Uncategorized types: {uncategorized}"

    def test_no_type_in_multiple_categories(self):
        """No EntityType appears in more than one category."""
        all_types: list[EntityType] = []
        for types in ENTITY_CATEGORIES.values():
            all_types.extend(types)
        assert len(all_types) == len(set(all_types)), "Duplicate type across categories"

    def test_excluded_types_not_in_any_category(self):
        """Deprecated/dead types are not in any category."""
        categorized = set()
        for types in ENTITY_CATEGORIES.values():
            categorized |= types
        for excluded in self._EXCLUDED_TYPES:
            assert excluded not in categorized, f"{excluded} should be excluded"

    def test_function_category_is_code(self):
        assert EntityType.FUNCTION.category == EntityCategory.CODE

    def test_method_category_is_code(self):
        assert EntityType.METHOD.category == EntityCategory.CODE

    def test_class_category_is_code(self):
        assert EntityType.CLASS.category == EntityCategory.CODE

    def test_property_category_is_code(self):
        assert EntityType.PROPERTY.category == EntityCategory.CODE

    def test_external_symbol_category_is_external(self):
        assert EntityType.EXTERNAL_SYMBOL.category == EntityCategory.EXTERNAL

    def test_infrastructure_config_category_is_infrastructure(self):
        assert EntityType.INFRASTRUCTURE_CONFIG.category == EntityCategory.INFRASTRUCTURE

    def test_environment_variable_category_is_infrastructure(self):
        assert EntityType.ENVIRONMENT_VARIABLE.category == EntityCategory.INFRASTRUCTURE

    def test_setting_category_is_markup(self):
        assert EntityType.SETTING.category == EntityCategory.MARKUP

    def test_section_category_is_markup(self):
        assert EntityType.SECTION.category == EntityCategory.MARKUP

    def test_element_category_is_markup(self):
        assert EntityType.ELEMENT.category == EntityCategory.MARKUP

    def test_document_category_is_markup(self):
        assert EntityType.DOCUMENT.category == EntityCategory.MARKUP

    def test_syntax_glue_category_is_structural(self):
        assert EntityType.SYNTAX_GLUE.category == EntityCategory.STRUCTURAL

    def test_comment_block_category_is_structural(self):
        assert EntityType.COMMENT_BLOCK.category == EntityCategory.STRUCTURAL

    def test_category_str_is_lowercase(self):
        assert str(EntityCategory.CODE) == "code"
        assert str(EntityCategory.EXTERNAL) == "external"
        assert str(EntityCategory.INFRASTRUCTURE) == "infrastructure"
        assert str(EntityCategory.MARKUP) == "markup"
        assert str(EntityCategory.STRUCTURAL) == "structural"

    def test_category_has_five_values(self):
        assert len(EntityCategory) == 5

    def test_round_trip_function(self):
        """EntityType.FUNCTION.category → EntityCategory.CODE."""
        assert EntityType.FUNCTION.category == EntityCategory.CODE
        assert EntityType.FUNCTION in ENTITY_CATEGORIES[EntityCategory.CODE]


class TestDeprecatedEntityTypes:
    """T13/T14: Deprecated entity types stay loadable but are reserved-as-unused."""

    def test_unresolved_from_dict_maps_to_external_symbol(self):
        """T13: legacy ``unresolved`` entities load as EXTERNAL_SYMBOL."""
        data = {
            "id": "unresolved:scope::sym",
            "type": "unresolved",
            "name": "sym",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
        }
        entity = Entity.from_dict(data)
        assert entity.type == EntityType.EXTERNAL_SYMBOL
        assert entity.id == "unresolved:scope::sym"

    def test_unresolved_uppercase_from_dict_maps_to_external_symbol(self):
        """Legacy serialized name may be uppercase."""
        entity = Entity.from_dict({
            "id": "unresolved:scope::sym",
            "type": "UNRESOLVED",
            "name": "sym",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
        })
        assert entity.type == EntityType.EXTERNAL_SYMBOL

    def test_is_contextual_stub_true_for_external_symbol_stub(self):
        """T13: EXTERNAL_SYMBOL entities with the unresolved: ID prefix are stubs."""
        entity = Entity(
            type=EntityType.EXTERNAL_SYMBOL,
            name="sym",
            file="foo.py",
            start_line=1,
            end_line=1,
            id_override="unresolved:scope::sym",
        )
        assert entity.is_contextual_stub is True

    def test_is_contextual_stub_true_for_legacy_unresolved(self):
        """Legacy artifacts with UNRESOLVED stubs remain recognizable."""
        entity = Entity(
            type=EntityType.UNRESOLVED,
            name="sym",
            file="foo.py",
            start_line=1,
            end_line=1,
            id_override="unresolved:scope::sym",
        )
        assert entity.is_contextual_stub is True

    def test_is_contextual_stub_false_for_materialized_external(self):
        """Scope-manager EXTERNAL_SYMBOL entities (no unresolved: prefix) are not stubs."""
        entity = Entity(
            type=EntityType.EXTERNAL_SYMBOL,
            name="os",
            file="",
            start_line=1,
            end_line=1,
            id_override="ext|os",
        )
        assert entity.is_contextual_stub is False

    def test_is_contextual_stub_false_for_regular_entity(self):
        entity = Entity(
            type=EntityType.FUNCTION,
            name="f",
            file="foo.py",
            start_line=1,
            end_line=1,
            id_override="ent|FUNCTION|foo.py|0|10|1|1|f",
        )
        assert entity.is_contextual_stub is False

    def test_from_dict_dead_types_load_gracefully(self):
        """T14: reserved-as-unused types still deserialize (kept for legacy artifacts)."""
        for type_name in ("attribute", "global_statement", "import_block"):
            entity = Entity.from_dict({
                "id": f"legacy-{type_name}",
                "type": type_name,
                "name": "x",
                "file": "foo.py",
                "start_line": 1,
                "end_line": 1,
            })
            assert entity.type.name == type_name.upper()

    def test_deprecated_entity_types_constant(self):
        """T14: DEPRECATED_ENTITY_TYPES matches the four reserved types."""
        from batho.core.schemas import DEPRECATED_ENTITY_TYPES
        assert DEPRECATED_ENTITY_TYPES == frozenset({
            EntityType.UNRESOLVED,
            EntityType.ATTRIBUTE,
            EntityType.GLOBAL_STATEMENT,
            EntityType.IMPORT_BLOCK,
        })

    def test_deprecated_types_have_no_category(self):
        """T14: deprecated types are excluded from ENTITY_CATEGORIES."""
        from batho.core.schemas import DEPRECATED_ENTITY_TYPES
        for etype in DEPRECATED_ENTITY_TYPES:
            assert etype.category is None


class TestInverseRelationshipDeprecation:
    """T15: inverse relationship types re-classify to forward types on load."""

    @pytest.mark.parametrize(
        ("legacy_type", "forward_type"),
        [
            ("called_by", "CALLS"),
            ("imported_by", "IMPORTS"),
            ("referenced_in", "READS"),
            ("contained_within", "CONTAINS"),
        ],
    )
    def test_from_dict_maps_inverse_to_forward(self, legacy_type, forward_type):
        """from_dict maps legacy inverse types to the forward type with swapped endpoints."""
        from batho.core.schemas import Relationship, RelationshipType
        rel = Relationship.from_dict({
            "source_id": "A",
            "target_id": "B",
            "type": legacy_type,
        })
        assert rel.type == RelationshipType[forward_type]
        # Endpoints swapped: A --CALLED_BY--> B means B --CALLS--> A.
        assert rel.source_id == "B"
        assert rel.target_id == "A"
        assert rel.metadata.get("reversed") is True

    def test_direct_init_inverse_type_reclassified(self):
        """The model validator runs on direct construction too (all paths behave identically)."""
        from batho.core.schemas import Relationship, RelationshipType
        rel = Relationship(
            source_id="A",
            target_id="B",
            type=RelationshipType.CALLED_BY,
        )
        assert rel.type == RelationshipType.CALLS
        assert rel.source_id == "B"
        assert rel.target_id == "A"
        assert rel.metadata.get("reversed") is True

    def test_inverse_reclassification_preserves_metadata(self):
        """Existing metadata is kept and only the reversed flag is added."""
        from batho.core.schemas import Relationship
        rel = Relationship.from_dict({
            "source_id": "A",
            "target_id": "B",
            "type": "CONTAINED_WITHIN",
            "metadata": {"line_number": 7},
        })
        assert rel.metadata.get("line_number") == 7
        assert rel.metadata.get("reversed") is True

    def test_forward_types_not_reclassified(self):
        """Forward edges pass through unchanged (no regression)."""
        from batho.core.schemas import Relationship, RelationshipType
        for type_name in ("CALLS", "IMPORTS", "READS", "WRITES", "CONTAINS"):
            rel = Relationship.from_dict({
                "source_id": "A",
                "target_id": "B",
                "type": type_name,
            })
            assert rel.type == RelationshipType[type_name]
            assert rel.source_id == "A"
            assert rel.target_id == "B"
            assert "reversed" not in rel.metadata

    def test_deprecated_relationship_types_constant(self):
        """T15: DEPRECATED_RELATIONSHIP_TYPES lists the four inverse types."""
        from batho.core.schemas import DEPRECATED_RELATIONSHIP_TYPES
        assert DEPRECATED_RELATIONSHIP_TYPES == frozenset({
            "CALLED_BY", "IMPORTED_BY", "REFERENCED_IN", "CONTAINED_WITHIN",
        })

    def test_references_reclassification_still_works(self):
        """T09 behavior is preserved alongside the T15 mapping."""
        from batho.core.schemas import Relationship, RelationshipType, SymbolRole
        rel = Relationship.from_dict({
            "source_id": "A",
            "target_id": "B",
            "type": "REFERENCES",
            "roles": int(SymbolRole.WriteAccess),
        })
        assert rel.type == RelationshipType.WRITES
        assert rel.source_id == "A"
        assert rel.target_id == "B"
