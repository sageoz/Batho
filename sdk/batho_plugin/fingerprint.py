"""batho_plugin/fingerprint.py — plugin-set fingerprint (PLUGIN_ARCHITECTURE_SPEC §9).

The fingerprint is a SHA-256 over the sorted
``plugin_id|version|sha256(canonical_compiled_data)`` entry set. It keys the
AST cache (constraint C6: cached entities embed hook-plugin outputs, so a
plugin/data change must invalidate affected entries) and lands in
``run_artifacts.plugin_fingerprint``.

Canonicalization rules (stable across processes — constraint: the same value
must be computed identically in the parent and in forked workers):

- frozensets/sets → sorted lists
- tuples/lists → lists
- dicts → string-keyed, key-sorted
- JSON primitives pass through; anything else → ``repr()`` (stable for the
  primitive-only payloads packs emit; opaque engine objects must not be
  placed in PluginData)

Granularity: v1 uses a single global fingerprint (spec §9). Per-language
fingerprints are a documented future optimization — the entry-building
helpers below are the seam for that split (hash per language-scoped
PluginData, then combine).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Iterable

from batho_plugin.api import PluginData

if TYPE_CHECKING:
    from batho_plugin.host import PluginHost


def canonicalize(value: Any) -> Any:
    """Recursively convert *value* to a JSON-serializable canonical form."""
    if isinstance(value, (frozenset, set)):
        return sorted((canonicalize(v) for v in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [canonicalize(v) for v in value]
    if isinstance(value, dict):
        return {
            str(k): canonicalize(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def data_hash(data: PluginData) -> str:
    """SHA-256 hex of the canonical serialization of a PluginData tree."""
    payload = {
        "sets": {
            key: sorted(canon) for key, canon in
            ((k, canonicalize(v)) for k, v in data.sets.items())
        },
        "maps": {key: canonicalize(v) for key, v in data.maps.items()},
        "per_language": {
            lang: data_hash(sub)
            for lang, sub in sorted(data.per_language.items())
        },
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def entry(plugin_id: str, version: str, dhash: str) -> str:
    """One canonical fingerprint line: ``plugin_id|version|data_hash``."""
    return f"{plugin_id}|{version}|{dhash}"


def compute_fingerprint(entries: Iterable[str]) -> str:
    """SHA-256 hex over the sorted, newline-joined entry set (spec §9)."""
    joined = "\n".join(sorted(entries))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def fingerprint_from_host(host: "PluginHost") -> str:
    """Fingerprint every plugin registered on *host*.

    Data plugins contribute their compiled-data hash; hook plugins contribute
    a hash over their stage set and dispatch priority (behavior-affecting
    configuration with no data payload). Rule plugins registered through
    pack ``get_plugins()`` exports contribute a hash of their rule ids — the
    rule engine's own ``rules_fingerprint_for_config`` remains the
    authoritative rule-set fingerprint; this covers the SDK-registered
    wrapper.
    """
    entries: list[str] = []
    for reg in host.data_registrations():
        entries.append(entry(reg.plugin_id, reg.version, data_hash(reg.data)))
    for reg in host.hook_registrations():
        stages = ",".join(s.value for s in sorted(reg.plugin.stages, key=lambda s: s.value))
        dhash = hashlib.sha256(
            f"hooks:{stages}|prio:{reg.priority}".encode("utf-8")
        ).hexdigest()
        entries.append(entry(reg.plugin.plugin_id, reg.plugin.version, dhash))
    for reg in host.rule_registrations():
        dhash = hashlib.sha256(
            "\n".join(sorted(reg.rule_ids)).encode("utf-8")
        ).hexdigest()
        entries.append(entry(reg.plugin_id, reg.version, dhash))
    return compute_fingerprint(entries)
