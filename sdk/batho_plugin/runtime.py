"""batho_plugin/runtime.py — process-local active PluginHost accessor.

The engine's hot paths (detector, extractor prune sites) need the host
without constructor threading: the worker initializer sets the active host
once per process (T22/T11), and engine call sites read it via
:func:`get_active_plugin_host`. Mirrors the engine's ``set_active_root``
ContextVar pattern (§15.7 read-once caching).
"""

from __future__ import annotations

from typing import Any

_active_host: Any = None


def set_active_plugin_host(host: Any) -> None:
    """Set the process-local active PluginHost (worker init / build main)."""
    global _active_host
    _active_host = host


def get_active_plugin_host() -> Any:
    """Return the active PluginHost for this process.

    An empty host (no registered plugins — the ``--no-plugins`` host) reads
    as absent, so engine call sites take their compiled-in fallbacks rather
    than dispatching against empty pack data.
    """
    if _active_host is not None and not getattr(
        _active_host, "plugin_ids", True
    ):
        return None
    return _active_host
