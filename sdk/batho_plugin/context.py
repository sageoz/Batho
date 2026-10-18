"""batho_plugin/context.py — PluginContext handed to stage hooks.

One context object flows through a file's worker stages (and a graph-scoped
variant through the post-build stages). Fields are read-mostly: hook plugins
mutate only the documented mutable buffers (``entities``); everything else is
treated as read-only so dispatch stays deterministic.

``tree_root`` and ``source_bytes`` are process-local (tree-sitter nodes are C
pointers — constraint C1): they are non-None only in AST-alive stages and must
never be pickled or serialized across process boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PluginContext:
    """Per-file (or per-graph) context for hook plugin dispatch.

    Attributes:
        file_path: Repo-relative POSIX path of the file being processed.
        root_path: Absolute repository root for this run.
        language: Parser language id; set after ON_FILE_DETECTED.
        source_bytes: Raw file bytes; worker stages only (never serialized).
        tree_root: tree-sitter root ``Node``; worker stages only (Any to keep
            the SDK import-time free of tree-sitter — C1).
        imported_names: Pre-built set of module paths and from-import symbols
            for O(1) membership checks in the prune hook (FIX 10 pattern).
        file_imports: ``(module_path, symbols, ...)`` tuples as built by the
            extractor's import index.
        entities: Mutable entity buffer for the file (ON_POST_ENTITIES).
        relationship_buffer: Relationship buffer; READ-ONLY in v1 — hooks may
            not create, delete, or retarget relationships (spec §6.4).
        run_id: Run nonce for this build/patch invocation.
        config: Read-only view of the effective ``plugins.*`` configuration.
        hook_marks: ``id(entity) → {plugin_ids}`` provenance map filled by
            hooks via :meth:`record_hook_mark`; the engine turns it into the
            ``bsg.hooks`` entity key when ``plugins.telemetry.hooks_metadata``
            is enabled (spec §6.2 E2 — debug-gated, absent by default).
    """

    file_path: str
    root_path: Path
    language: str | None = None
    source_bytes: bytes | None = None
    tree_root: Any = None
    imported_names: frozenset[str] = frozenset()
    file_imports: tuple[Any, ...] = ()
    entities: list[Any] = field(default_factory=list)
    relationship_buffer: list[Any] = field(default_factory=list)
    run_id: str = ""
    config: Mapping[str, Any] = field(default_factory=dict)
    hook_marks: dict[int, set[str]] = field(default_factory=dict)

    def record_hook_mark(self, plugin_id: str, entity: Any) -> None:
        """Mark *entity* as mutated by *plugin_id* for ``bsg.hooks``.

        The frozen contract still holds — this mutates the marks map's
        contents, never rebinds a field. Marks are dropped unless the run
        enabled ``plugins.telemetry.hooks_metadata``.
        """
        self.hook_marks.setdefault(id(entity), set()).add(plugin_id)

    def apply_hook_marks(self) -> int:
        """Stamp ``bsg.hooks`` onto every entity carrying recorded marks.

        The write lives in SDK code so the ``bsg.*`` namespace stays
        plugin-owned (engine code never writes ``bsg.*`` keys — E2,
        ``bsg.index_id`` excepted). Returns the number of entities stamped.
        """
        stamped = 0
        for ent in self.entities:
            marks = self.hook_marks.get(id(ent))
            meta = getattr(ent, "metadata", None)
            if marks and isinstance(meta, dict):
                meta["bsg.hooks"] = sorted(marks)
                stamped += 1
        return stamped
