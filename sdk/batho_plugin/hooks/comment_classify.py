"""batho_plugin/hooks/comment_classify.py — ON_COMMENT_CLASSIFY metadata.

Migrates the extractor's rationale-marker classification
(``extractor.py:2155-2179``) into a hook. The marker SCAN (line regex +
AST comment-node verification) stays in the engine — it is intertwined with
entity construction; the hook owns the CLASSIFICATION decision: marker text →
``rationale_kind`` / ``marker_comment`` / ``line_scan_fallback`` metadata
(E2 ownership class, spec §6.2).

Engine parity (extractor.py:2156-2157, 2173-2179)::

    kind = marker_text.rstrip(":").strip().lower() or "comment"
    metadata = {"rationale_kind": kind, "marker_comment": True, "language": lang}
    if root_node is None:
        metadata["line_scan_fallback"] = True
"""

from __future__ import annotations

from typing import Any

from batho_plugin.api import Stage, StageResult
from batho_plugin.context import PluginContext


def classify_marker(
    marker_text: str,
    language: str | None,
    has_parse_tree: bool,
) -> dict[str, Any]:
    """Classify one rationale marker hit into entity metadata.

    Byte-identical to the engine's classification (extractor.py:2156-2179).

    Args:
        marker_text: The captured marker word (e.g. ``"WHY:"``, ``"todo"``).
        language: Parser language id stamped into the metadata.
        has_parse_tree: False when the engine fell back to line scanning
            (no parse tree) — stamps ``line_scan_fallback``.
    """
    kind = marker_text.rstrip(":").strip().lower() or "comment"
    metadata: dict[str, Any] = {
        "rationale_kind": kind,
        "marker_comment": True,
        "language": language,
    }
    if not has_parse_tree:
        metadata["line_scan_fallback"] = True
    return metadata


class CommentClassifyHook:
    """Hook plugin for ON_COMMENT_CLASSIFY (per-file, AST-alive stage).

    Applies :func:`classify_marker` to comment entities in the context
    buffer. Entities are opaque; the hook mutates their ``metadata`` dict in
    place (E2 ownership — stripped only on re-extraction, never by
    ``plugins apply``).
    """

    plugin_id = "batho_plugin.hooks.comment_classify"
    version = "0.1.0"
    stages = (Stage.ON_COMMENT_CLASSIFY,)
    plugin_class = "core"  # class: core — SDK core pack (spec §4.5)
    requires = ("batho_plugin.core",)

    def on_comment_classify(self, ctx: PluginContext) -> StageResult:
        """Classify marker-comment entities already flagged by the engine scan.

        The engine's scan (T16 wiring) tags candidate comment entities with a
        transient ``_marker_text`` metadata hint; this hook converts the hint
        into the final E2 metadata and removes the transient key. Entities
        without the hint pass through untouched.
        """
        changed = 0
        for entity in ctx.entities:
            meta = getattr(entity, "metadata", None)
            if not isinstance(meta, dict):
                continue
            marker_text = meta.pop("_marker_text", None)
            if marker_text is None:
                continue
            meta.update(
                classify_marker(
                    str(marker_text), ctx.language, ctx.tree_root is not None
                )
            )
            ctx.record_hook_mark(self.plugin_id, entity)
            changed += 1
        return StageResult(changed=changed > 0, detail={"classified": changed})
