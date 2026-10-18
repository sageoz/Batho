"""batho_plugin/hooks/stamp_language.py — ON_POST_ENTITIES language stamping.

Batches language stamping to ONE call per file (not per entity —
performance contract, spec §4.4/T13). The engine still stamps the
engine-owned bare ``language`` key at entity construction
(``extractor.py:_collect_metadata_with_source`` and the fallback-path stamp),
so this hook's re-stamp of that key is an idempotent parity no-op whose real
payloads are (a) the plugin-owned ``bsg.language`` ecosystem display name —
stamped on EVERY entity in the buffer, including contextual stubs, because
the deleted per-extension detection rules matched ``entity.file``, which
stubs carry — and (b) the ``bsg.hooks`` provenance mark via ``on_stamped``.

Engine parity: the bare-key stamp is UNCONDITIONAL for every non-stub entity
in the file's buffer; stubs are never language-stamped on the bare key (the
engine never stamps them either). Hollow/external symbols never appear in
the per-file buffer, so they are untouched by construction.
"""

from __future__ import annotations

import logging
from typing import Any

from batho_plugin.api import Stage, StageResult
from batho_plugin.context import PluginContext

# stdlib logging — hooks/ is a contract module (§3.1): no batho.* objects may
# enter its namespace (test_no_engine_import_in_contract_modules enforces).
_LOGGER = logging.getLogger(__name__)


def stamp_entities(
    entities: list,
    language: str | None,
    ecosystem: str | None = None,
    on_stamped: Any = None,
) -> int:
    """Stamp ``language`` onto every AST entity's metadata dict, in place.

    Also stamps ``bsg.language`` (the ecosystem display name) onto EVERY
    entity in the buffer — including contextual stubs — when *ecosystem* is
    provided (T10): the deleted per-extension detection rules matched
    ``entity.file``, which stubs carry, so rule parity requires stubs to be
    stamped for the plugin-owned key while the engine-owned ``language`` key
    stays AST-only (engine parity — stubs are never language-stamped).

    Returns the number of entities stamped. Works on pre-construction
    metadata dicts and on frozen pydantic models whose ``metadata`` is a
    plain dict (contents mutate; the model binding does not).

    ``on_stamped`` is an optional per-entity callback (entity → None) used by
    the host-facing hook to record ``bsg.hooks`` provenance marks.
    """
    if language is None:
        return 0
    stamped = 0
    for entity in entities:
        meta = getattr(entity, "metadata", None)
        if not isinstance(meta, dict):
            continue
        is_stub = "stub_resolution_state" in meta or "reference_type" in meta
        if not is_stub:
            meta["language"] = language
            stamped += 1
        elif ecosystem is not None:
            meta["bsg.language"] = ecosystem
            stamped += 1
        else:
            continue
        if ecosystem is not None and not is_stub:
            meta["bsg.language"] = ecosystem
        if on_stamped is not None:
            on_stamped(entity)
    return stamped


class StampLanguageHook:
    """Hook plugin for ON_POST_ENTITIES (batch, per file)."""

    plugin_id = "batho_plugin.hooks.stamp_language"
    version = "0.1.0"
    stages = (Stage.ON_POST_ENTITIES,)
    plugin_class = "core"  # class: core — SDK core pack (spec §4.5)
    requires = ("batho_plugin.core",)

    def __init__(self) -> None:
        self._host = None

    def bind(self, host: "PluginHost") -> None:
        """Inject the host so pack data (language ecosystem map) is available."""
        self._host = host

    def _ecosystem(self, language: str | None) -> str | None:
        if self._host is None or not language:
            return None
        try:
            return self._host.get_map("language_ecosystem").get(language)
        except Exception as exc:
            _LOGGER.debug(
                "language_ecosystem_lookup_failed language=%s error=%s",
                language,
                str(exc),
            )
            return None

    def on_post_entities(self, ctx: PluginContext) -> StageResult:
        stamped = stamp_entities(
            ctx.entities,
            ctx.language,
            ecosystem=self._ecosystem(ctx.language),
            on_stamped=lambda e: ctx.record_hook_mark(self.plugin_id, e),
        )
        return StageResult(changed=stamped > 0, detail={"stamped": stamped})
