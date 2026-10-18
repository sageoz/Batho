"""batho_plugin/hooks/property_classify.py — ON_PROPERTY_CLASSIFY access_type.

Migrates the extractor's property read/write inference
(``extractor.py:1101-1141``) into a hook operating on the live tree
(AST-alive stage, C1). Engine parity, in priority order:

1. Python ``@x.setter`` decorator on the enclosing ``decorated_definition``
   → ``write`` (extractor.py:1102-1109)
2. TypeScript ``accessor`` capture text ``"set"`` → ``write`` (T03 fix,
   extractor.py:1113-1118 — accessor text supplied by the engine's query
   capture, passed through here)
3. C# ``accessor_list`` child ``accessor_declaration`` starting with
   ``"set"`` → ``write`` (extractor.py:1121-1130)
4. Kotlin ``binding_pattern_kind`` text ``"var"`` → ``write`` (T03,
   extractor.py:1134-1139)
5. Default → ``read`` (extractor.py:1140-1141)
"""

from __future__ import annotations

from typing import Any

from batho_plugin.api import Stage, StageResult
from batho_plugin.context import PluginContext


def _node_text(node: Any, source: bytes | None) -> str:
    """Engine parity: slice raw bytes and decode (extractor.py:300-306)."""
    if source is None:
        return ""
    return source[node.start_byte : node.end_byte].decode(
        "utf-8", errors="replace"
    ).strip()


def infer_access_type(
    decl_node: Any,
    source: bytes | None,
    language: str | None,
    accessor_text: str | None = None,
) -> str:
    """Infer ``access_type`` for a PROPERTY declaration node.

    Byte-identical to ``extractor.py:1101-1141``. ``accessor_text`` carries
    the engine's TS ``accessor`` capture (auxiliary node text) when available.
    """
    parent = decl_node.parent

    # 1. Python: @x.setter decorator on the enclosing decorated_definition.
    if parent is not None and parent.type == "decorated_definition":
        for child in parent.children:
            if child.type == "decorator":
                decorator_text = _node_text(child, source)
                if ".setter" in decorator_text:
                    return "write"

    # 2. TypeScript: captured get/set accessor keyword.
    if accessor_text is not None and accessor_text.strip() == "set":
        return "write"

    # 3. C#: accessor_list with a "set" accessor_declaration.
    if language == "csharp" and parent is not None:
        for child in parent.children:
            if child.type == "accessor_list":
                for acc in child.children:
                    if acc.type == "accessor_declaration":
                        if _node_text(acc, source).startswith("set"):
                            return "write"
                break

    # 4. Kotlin: binding_pattern_kind "var" is mutable.
    if language == "kotlin" and parent is not None:
        for child in parent.children:
            if child.type == "binding_pattern_kind":
                if _node_text(child, source).strip() == "var":
                    return "write"
                break

    # 5. Default: read.
    return "read"


class PropertyClassifyHook:
    """Hook plugin for ON_PROPERTY_CLASSIFY (per-file, AST-alive stage).

    The engine wiring (T17) calls :func:`infer_access_type` per PROPERTY
    entity with the live node; the dispatch form stamps PROPERTY entities in
    the context buffer that carry a transient ``_decl_node`` hint.
    """

    plugin_id = "batho_plugin.hooks.property_classify"
    version = "0.1.0"
    stages = (Stage.ON_PROPERTY_CLASSIFY,)
    plugin_class = "core"  # class: core — SDK core pack (spec §4.5)
    requires = ("batho_plugin.core",)

    def on_property_classify(self, ctx: PluginContext) -> StageResult:
        """Stamp ``access_type`` on PROPERTY entities in the buffer.

        Entities carry a transient ``_decl_node`` hint (engine wiring);
        entities without the hint pass through untouched.
        """
        changed = 0
        for entity in ctx.entities:
            meta = getattr(entity, "metadata", None)
            if not isinstance(meta, dict):
                continue
            decl_node = meta.pop("_decl_node", None)
            if decl_node is None:
                continue
            meta["access_type"] = infer_access_type(
                decl_node,
                ctx.source_bytes,
                ctx.language,
                accessor_text=meta.pop("_accessor_text", None),
            )
            ctx.record_hook_mark(self.plugin_id, entity)
            changed += 1
        return StageResult(changed=changed > 0, detail={"classified": changed})
