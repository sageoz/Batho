"""tests/sdk/test_contracts.py — T02: SDK core contracts.

Protocol structural checks, PluginContext edge cases, and the
no-AST-types-in-post-build-stages constraint (spec §4.1/§4.2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from batho_plugin import (
    DataPlugin,
    HookPlugin,
    PluginContext,
    PluginData,
    PruneDecision,
    RulePlugin,
    Stage,
    StageResult,
)


class _ValidData:
    plugin_id = "d"
    version = "1.0"

    def compile(self) -> PluginData:
        return PluginData(sets={"k": frozenset({"a"})})


class _ValidHook:
    plugin_id = "h"
    version = "1.0"
    stages = (Stage.ON_POST_ENTITIES,)

    def on_post_entities(self, ctx: PluginContext) -> StageResult:
        return StageResult()


def test_protocols_structural() -> None:
    assert isinstance(_ValidData(), DataPlugin)
    assert isinstance(_ValidHook(), HookPlugin)

    class _Rule:
        plugin_id = "r"
        version = "1.0"

    assert isinstance(_Rule(), RulePlugin)


def test_prune_decision_and_stage_result_frozen() -> None:
    d = PruneDecision(prune=True, reason="builtin")
    with pytest.raises(Exception):
        d.prune = False  # type: ignore[misc]
    r = StageResult(changed=True)
    with pytest.raises(Exception):
        r.changed = False  # type: ignore[misc]


def test_context_post_build_stage_has_no_ast() -> None:
    """Post-build contexts carry no AST (constraint C1 / §4.1)."""
    ctx = PluginContext(file_path="x", root_path=Path("."))
    assert ctx.tree_root is None
    assert ctx.source_bytes is None
    for stage in (Stage.ON_POST_RESOLVE, Stage.ON_POST_BUILD):
        assert not stage.ast_alive


def test_context_frozen_with_mutable_buffers() -> None:
    """Frozen binding, mutable entity buffer (spec §4.2)."""
    ctx = PluginContext(file_path="a.py", root_path=Path("."))
    with pytest.raises(Exception):
        ctx.file_path = "b.py"  # type: ignore[misc]
    ctx.entities.append(object())
    assert len(ctx.entities) == 1


def test_context_spec_fields_present() -> None:
    """All §4.2 fields exist (+ hook_marks provenance map, T33/§6.2 E2)."""
    fields = set(PluginContext.__dataclass_fields__)
    assert fields == {
        "file_path",
        "root_path",
        "language",
        "source_bytes",
        "tree_root",
        "imported_names",
        "file_imports",
        "entities",
        "relationship_buffer",
        "run_id",
        "config",
        "hook_marks",
    }


def test_stage_values_are_hook_method_names() -> None:
    for stage in Stage:
        assert stage.hook_method == stage.value
        assert stage.value.startswith("on_")
