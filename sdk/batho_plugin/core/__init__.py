"""batho_plugin/core/__init__.py — foundation pack (class: core, MANDATORY).

Ships the engine's migrated knowledge as data and hook plugins:

- ``language_packs/*.yaml`` — per-language builtins, noise extensions,
  comment syntax, lang→manager (T07; source: extractor.py:163-236,
  pipeline.py:41-48)
- ``pruning_policy.yaml`` / ``resolution_policy.yaml`` — prunable method
  names and strategy→confidence map (T08)
- The five generic hooks (T06) — registered here so the host dispatches them

Plugin class: ``core`` — exempt from the fixture-gate selectivity cap
(intentionally broad), but version-pinned and covered by golden-output tests
(PLUGIN_ARCHITECTURE_SPEC §4.5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from batho_plugin.hooks import (
    CommentClassifyHook,
    LanguageDetectHook,
    PruneStubHook,
    PropertyClassifyHook,
    StampLanguageHook,
)
from batho_plugin.packs import load_pack_dir

PACK_ID = "batho_plugin.core"
PACK_VERSION = "0.1.0"
PLUGIN_CLASS = "core"


def get_plugins() -> list[Any]:
    """Every plugin this pack registers (deterministic order)."""
    pack_dir = Path(__file__).resolve().parent
    plugins: list[Any] = [
        LanguageDetectHook(),
        CommentClassifyHook(),
        PropertyClassifyHook(),
        PruneStubHook(),
        StampLanguageHook(),
    ]
    plugins.extend(load_pack_dir(pack_dir))
    return plugins
