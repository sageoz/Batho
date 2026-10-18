"""batho_plugin/stages.py — Pipeline stage enum and stage contracts.

The stage enum is FIXED in v1: no dynamic stage registration. AST availability
(PLUGIN_ARCHITECTURE_SPEC §4.1, constraint C1): stages marked AST-alive execute
inside the extraction worker while the tree-sitter tree is alive; the
post-build stages execute in the parent process with graph access only.

Contracts per stage:

- ON_FILE_DETECTED     ctx: file_path, source_bytes → language decision
- ON_PRE_PARSE         ctx: file_path, source_bytes, language
- ON_POST_PARSE        ctx: + tree_root (AST ALIVE)
- ON_COMMENT_CLASSIFY  ctx: + comment nodes (AST ALIVE)
- ON_PROPERTY_CLASSIFY ctx: + property nodes (AST ALIVE)
- ON_PRE_STUB_CREATE   ctx: + ref text, imported_names → keep/prune verdict
- ON_POST_ENTITIES     ctx: + entity buffer (batch, per file) (AST ALIVE)
- ON_POST_RESOLVE      ctx: graph (no AST)
- ON_POST_BUILD        ctx: graph (no AST); semantic overlay
"""

from __future__ import annotations

from enum import Enum


class Stage(Enum):
    """Pipeline stages at which plugins may be invoked.

    Ordering here is the canonical pipeline order; the PluginHost dispatches
    hooks per stage, never across stages.
    """

    ON_FILE_DETECTED = "on_file_detected"
    ON_PRE_PARSE = "on_pre_parse"
    ON_POST_PARSE = "on_post_parse"
    ON_COMMENT_CLASSIFY = "on_comment_classify"
    ON_PROPERTY_CLASSIFY = "on_property_classify"
    ON_PRE_STUB_CREATE = "on_pre_stub_create"
    ON_POST_ENTITIES = "on_post_entities"
    ON_POST_RESOLVE = "on_post_resolve"
    ON_POST_BUILD = "on_post_build"

    @property
    def ast_alive(self) -> bool:
        """True when this stage executes in the worker with a live tree."""
        return self in _AST_ALIVE_STAGES

    @property
    def hook_method(self) -> str:
        """Name of the ``on_<stage>`` method a HookPlugin implements."""
        return self.value


# Stages that run inside the extraction worker while tree.root_node is alive.
# tree-sitter Nodes are process-local C pointers: contexts carrying tree_root
# or source_bytes must never be pickled or serialized across processes.
_AST_ALIVE_STAGES = frozenset({
    Stage.ON_POST_PARSE,
    Stage.ON_COMMENT_CLASSIFY,
    Stage.ON_PROPERTY_CLASSIFY,
    Stage.ON_PRE_STUB_CREATE,
    Stage.ON_POST_ENTITIES,
})
