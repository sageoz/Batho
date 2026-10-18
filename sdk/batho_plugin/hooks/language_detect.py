"""batho_plugin/hooks/language_detect.py — ON_FILE_DETECTED language decision.

Wraps the engine detector's strategy seam (``detector.py:405-470``): the hook
decides from pack data (``ext_to_language`` map supplied by the host); when it
cannot decide (unknown extension, no pack data) it returns ``None`` and the
engine falls back to its own strategy chain (extension → special_filename →
shebang → magic bytes → content heuristics — constraint C3: detection
precedes parsing, the engine receives the language as a constructor arg).

The hook NEVER replaces the engine registry (``_EXT_TO_LANG`` stays the
per-file truth — spec §5); packs may extend it.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Mapping

from batho_plugin.api import Stage, StageResult
from batho_plugin.context import PluginContext

if TYPE_CHECKING:
    from batho_plugin.host import PluginHost


def detect_language(
    file_path: str,
    ext_map: Mapping[str, str] | None = None,
    special_names: Mapping[str, str] | None = None,
) -> str | None:
    """Extension/special-filename language decision from pack data.

    Byte-compatible with the engine detector's first two strategies
    (``detect_by_extension``, ``detect_by_special_filename``) restricted to
    data the packs supply. Returns ``None`` when undecided — the engine then
    applies its full fallback chain (shebang, magic bytes, heuristics).

    Args:
        file_path: Repo-relative path.
        ext_map: ``".py" -> "python"`` style map (pack data).
        special_names: Exact-filename map (``"Dockerfile" -> "dockerfile"``).
    """
    path = PurePosixPath(file_path.replace("\\", "/"))
    name = path.name

    # Engine strategy order is extension → special_filename (detector.py:420):
    # e.g. docker-compose.yml is "yaml" engine-side because extension wins —
    # the hook must decide identically or it diverges on mirrored maps.
    suffix = path.suffix
    if ext_map:
        if suffix and suffix in ext_map:
            return ext_map[suffix]
        if suffix and suffix.lower() in ext_map:
            return ext_map[suffix.lower()]

    if special_names and name in special_names:
        return special_names[name]
    return None


class LanguageDetectHook:
    """Hook plugin for ON_FILE_DETECTED (per-file, worker stage)."""

    plugin_id = "batho_plugin.hooks.language_detect"
    version = "0.1.0"
    stages = (Stage.ON_FILE_DETECTED,)
    plugin_class = "core"  # class: core — SDK core pack (spec §4.5)
    requires = ("batho_plugin.core",)

    def __init__(self, host: "PluginHost | None" = None) -> None:
        self._host = host

    def bind(self, host: "PluginHost") -> None:
        """Late-bind the host (pack loader calls this after registration)."""
        self._host = host

    def on_file_detected(self, ctx: PluginContext) -> StageResult:
        ext_map = (
            self._host.get_map("ext_to_language") if self._host is not None else {}
        )
        special = (
            self._host.get_map("special_filenames") if self._host is not None else {}
        )
        language = detect_language(ctx.file_path, ext_map, special)
        return StageResult(
            changed=language is not None,
            detail={"language": language},
        )
