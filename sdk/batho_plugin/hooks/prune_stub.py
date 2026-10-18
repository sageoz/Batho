"""batho_plugin/hooks/prune_stub.py — ON_PRE_STUB_CREATE prune decision.

Migrates the extractor's unresolved-reference pruning decision
(``extractor.py:239-291`` ``_should_prune_unresolved``) into a hook backed by
core-pack data (language packs supply ``builtins`` and ``noise_symbols``;
``pruning_policy`` supplies nothing here — the graph-builder's
``_should_prune_stub`` consumes that separately, T18).

Performance contract (C4): the decision path is O(1) set lookups ONLY — no
regex, no rule matching, no per-call compilation. The engine invokes this
~100K+ times per build; the hook must stay at set-lookup speed.

This is a per-reference stage: the engine calls :meth:`PruneStubHook.decide`
directly (not via per-file ctx dispatch) to avoid ~100K context
constructions. The Stage enum still documents the stage; dispatch-based
invocation applies to per-file stages only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from batho_plugin.api import PruneDecision, Stage, StageResult
from batho_plugin.context import PluginContext

if TYPE_CHECKING:
    from batho_plugin.host import PluginHost

# Relationship types that always keep a stub (cross-file candidates).
# Engine parity: RelationshipType.{CALLS, IMPORTS, INHERITS, IMPLEMENTS}
# (extractor.py:287) — names only, the SDK never imports the engine enum.
_KEEP_RELATIONSHIPS = frozenset({"CALLS", "IMPORTS", "INHERITS", "IMPLEMENTS"})

# Engine parity: extractor.py:269 hardcoded noise set. Language packs may
# extend per language via the ``noise_symbols`` data key; this tuple is the
# cross-language floor that the engine applies unconditionally.
_NOISE_SYMBOLS_FLOOR = frozenset({
    "self", "cls", "this", "err", "error", "nil", "null", "undefined",
    "true", "false", "args", "kwargs", "ctx", "context",
})


def should_prune(
    ref_text: str,
    rel_type_name: str,
    language: str | None,
    filepath: str,
    prune_enabled: bool = True,
    imported_names: frozenset[str] | None = None,
    builtins: frozenset[str] | None = None,
    noise_symbols: frozenset[str] | None = None,
) -> PruneDecision:
    """Decide whether an unresolved reference must NOT become an entity.

    Byte-identical to ``extractor.py:239-291`` with the builtin/noise sets
    injected (pack data) instead of read from module constants.

    Args:
        ref_text: The unresolved reference text.
        rel_type_name: Relationship type NAME (``RelationshipType.X.name``).
        language: Parser language id (pack lookup key).
        filepath: Repo-relative file path (engine skips pruning for
            pseudo-files without separators, e.g. ``__external_symbols__``).
        prune_enabled: Config gate (cached by the engine, FIX pattern).
        imported_names: Pre-built O(1) import index (FIX 10); falls back to
            "not imported" when None (engine's file_imports scan is done
            engine-side before calling).
        builtins: Language builtins from the language pack.
        noise_symbols: Language noise symbols from the language pack
            (unioned with the cross-language floor).
    """
    # Engine parity (extractor.py:253): pseudo-files (no separators) keep.
    if "/" not in filepath and "\\" not in filepath:
        return PruneDecision(prune=False, reason="pseudo_file")

    if not prune_enabled:
        return PruneDecision(prune=False, reason="prune_disabled")

    name = ref_text.strip()
    if not name:
        return PruneDecision(prune=True, reason="empty_ref")

    # 1. Prune builtins (exact or case-insensitive).
    if builtins:
        if name in builtins or name.lower() in builtins:
            return PruneDecision(prune=True, reason="builtin")

    # 2. Prune common noise stubs (floor ∪ language pack).
    noise = _NOISE_SYMBOLS_FLOOR | (noise_symbols or frozenset())
    if name in noise:
        return PruneDecision(prune=True, reason="noise_symbol")

    # 3. Qualified names / paths → keep.
    if "." in name or "/" in name or ":" in name:
        return PruneDecision(prune=False, reason="qualified_name")

    # 4. Imported in this file → keep (O(1) set lookup, FIX 10).
    if imported_names is not None and name in imported_names:
        return PruneDecision(prune=False, reason="imported")

    # 5. Cross-file candidate relationship types → keep.
    if rel_type_name in _KEEP_RELATIONSHIPS:
        return PruneDecision(prune=False, reason="cross_file_rel")

    # 6. Otherwise (USES/REFERENCES/READS/WRITES, not imported, no dots) → prune.
    return PruneDecision(prune=True, reason="unimported_simple_name")


class PruneStubHook:
    """Hook plugin for ON_PRE_STUB_CREATE (per-reference direct calls).

    The engine wiring (T14) fetches the pack sets once per file via the host
    and calls :meth:`decide` per unresolved reference.
    """

    plugin_id = "batho_plugin.hooks.prune_stub"
    version = "0.1.0"
    stages = (Stage.ON_PRE_STUB_CREATE,)
    plugin_class = "core"  # class: core — SDK core pack (spec §4.5)
    requires = ("batho_plugin.core",)

    def decide(
        self,
        ref_text: str,
        rel_type_name: str,
        language: str | None,
        filepath: str,
        prune_enabled: bool = True,
        imported_names: frozenset[str] | None = None,
        host: "PluginHost | None" = None,
    ) -> PruneDecision:
        """Decision with pack data pulled from *host* when available."""
        builtins = (
            host.get_set("builtins", language=language) if host is not None else None
        )
        noise = (
            host.get_set("noise_symbols", language=language)
            if host is not None
            else None
        )
        return should_prune(
            ref_text=ref_text,
            rel_type_name=rel_type_name,
            language=language,
            filepath=filepath,
            prune_enabled=prune_enabled,
            imported_names=imported_names,
            builtins=builtins,
            noise_symbols=noise,
        )

    def on_pre_stub_create(self, ctx: PluginContext) -> StageResult:
        """Per-file dispatch form (unused by the engine hot path; provided so
        the hook validates against the stage contract)."""
        return StageResult(changed=False, detail={"per_reference": True})
