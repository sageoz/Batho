from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Reference-site ids embed a line anchor (`unresolved:…@74::target`) —
# normalize it away for changelog pairing so a line shift doesn't re-id
# every reference site. Parameter-hash suffixes (`helper_[ef2e96]`) are
# stripped from display names for the same reason.
_LINE_ANCHOR = re.compile(r"@\d+::")
_PARAM_HASH = re.compile(r"_\[[0-9a-fA-F]+\]")

TRACKED_FIELDS = ("signature", "start_line", "end_line", "entity_type")


def _get_val(e: Any, key: str) -> Any:
    if isinstance(e, dict):
        return e.get(key)
    return getattr(e, key, None)


@dataclass
class NodeDiff:
    entity_id: str          # stable string ID (type:name:file hash)
    entity_name: str
    entity_type: str
    file_path: str
    change_kind: str        # "added" | "removed" | "modified" | "renamed"
    changed_fields: dict    # {"signature": [old, new], "start_line": [10, 12]}
    old_hash: str | None    # 8-char prefix
    new_hash: str | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for blob storage in file_changelog."""
        return {
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "change_kind": self.change_kind,
            "changed_fields": self.changed_fields,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
        }


def _get_type(e: Any) -> str:
    """Type as a plain string, from either shape.

    dicts carry ``entity_type``; Entity objects carry a ``type`` enum —
    comparing one against the other reported every node as
    modified[entity_type] (phantom diffs against plugins_apply bases).
    Enum values unwrap via ``.name``; dict-shaped values via ``["name"]``.
    """
    v = _get_val(e, "entity_type")
    if v is None:
        v = _get_val(e, "type")
    if v is None:
        return ""
    if isinstance(v, dict):
        v = v.get("name") or ""
    return str(getattr(v, "name", v))


def _display_name(e: Any) -> str:
    return _get_val(e, "name") or ""


def diff_file_nodes(
    old_entities: list[Any],
    new_entities: list[Any],
    file_path: str,
) -> list[NodeDiff]:
    """Diff entities within a file across two indexing runs.

    Algorithm:
    1. Build maps: old_map = {e["id"]: e}, new_map = {e["id"]: e}
    2. Fast-path hash check: For IDs in both maps, skip deep diff if content_hash matches.
    3. Deep diff on hash mismatch: Compare TRACKED_FIELDS only; emit NodeDiff(kind="modified").
    4. Rename heuristic: Match removed_ids ↔ added_ids by exact content_hash. If matched:
       emit kind="renamed" with changed_fields={"old_id": old_id}.
    5. Line-stable pairing: contextual-stub ids embed `@<line>`; pair
       remaining removed↔added by the line-stripped id so pure line shifts
       surface as modified, not as remove+add churn.
    6. Same-name pairing: remaining removed↔added with equal raw (hash-stripped)
       names are the same symbol with a new id (signature/param-hash change) —
       emit kind="modified" with the id swap instead of add+remove pairs.
    7. Pure adds/removes: Emit remaining added_ids and removed_ids.
    """
    old_map = {_get_val(e, "id"): e for e in old_entities if _get_val(e, "id") is not None}
    new_map = {_get_val(e, "id"): e for e in new_entities if _get_val(e, "id") is not None}

    diffs: list[NodeDiff] = []

    # 1. Fast-path check & deep diff for matching IDs
    common_ids = set(old_map.keys()) & set(new_map.keys())
    for eid in common_ids:
        old_ent = old_map[eid]
        new_ent = new_map[eid]

        old_ch = _get_val(old_ent, "content_hash") or ""
        new_ch = _get_val(new_ent, "content_hash") or ""

        if old_ch and new_ch and old_ch == new_ch:
            continue

        changed_fields = {}
        for f in TRACKED_FIELDS:
            old_val = _get_type(old_ent) if f == "entity_type" else _get_val(old_ent, f)
            new_val = _get_type(new_ent) if f == "entity_type" else _get_val(new_ent, f)
            if old_val != new_val:
                changed_fields[f] = [old_val, new_val]

        if not changed_fields and old_ch and new_ch and old_ch != new_ch:
            # Body-only edit: no tracked field moved, but the entity's own
            # source bytes changed — record it so history isn't silent.
            changed_fields["content_hash"] = [old_ch[:8], new_ch[:8]]

        if changed_fields:
            diffs.append(
                NodeDiff(
                    entity_id=eid,
                    entity_name=_display_name(new_ent),
                    entity_type=_get_type(new_ent),
                    file_path=file_path,
                    change_kind="modified",
                    changed_fields=changed_fields,
                    old_hash=old_ch[:8] if old_ch else None,
                    new_hash=new_ch[:8] if new_ch else None,
                )
            )

    # 2. Identify candidates for rename heuristic
    removed_ids = set(old_map.keys()) - set(new_map.keys())
    added_ids = set(new_map.keys()) - set(old_map.keys())

    removed_by_hash: dict[str, list[str]] = {}
    for rid in removed_ids:
        ch = _get_val(old_map[rid], "content_hash")
        if ch:
            removed_by_hash.setdefault(ch, []).append(rid)

    matched_added: set[str] = set()
    matched_removed: set[str] = set()

    # Apply rename heuristic
    for aid in sorted(added_ids):
        new_ent = new_map[aid]
        ch = _get_val(new_ent, "content_hash")
        if ch and ch in removed_by_hash and removed_by_hash[ch]:
            # Match found
            rid = removed_by_hash[ch].pop(0)
            matched_added.add(aid)
            matched_removed.add(rid)

            diffs.append(
                NodeDiff(
                    entity_id=aid,
                    entity_name=_display_name(new_ent),
                    entity_type=_get_type(new_ent),
                    file_path=file_path,
                    change_kind="renamed",
                    changed_fields={"old_id": rid},
                    old_hash=ch[:8] if ch else None,
                    new_hash=ch[:8] if ch else None,
                )
            )

    remaining_added = added_ids - matched_added
    remaining_removed = removed_ids - matched_removed

    # 2b. Line-stable pairing for anchored reference-site ids: pair the
    # k-th removed occurrence of a line-stripped id with the k-th added
    # occurrence — deterministic (sorted) and immune to line shifts.
    def _anchorless(eid: str) -> str:
        return _LINE_ANCHOR.sub("@::", eid)

    def _anchor_line(eid: str) -> int | None:
        m = re.search(r"@(\d+)::", eid)
        return int(m.group(1)) if m else None

    rem_by_anchor: dict[str, list[str]] = {}
    for rid in sorted(remaining_removed, key=lambda r: (_anchorless(r), _anchor_line(r) or 0)):
        rem_by_anchor.setdefault(_anchorless(rid), []).append(rid)
    add_by_anchor: dict[str, list[str]] = {}
    for aid in sorted(remaining_added, key=lambda a: (_anchorless(a), _anchor_line(a) or 0)):
        add_by_anchor.setdefault(_anchorless(aid), []).append(aid)

    for key in sorted(set(rem_by_anchor) & set(add_by_anchor)):
        pairs = min(len(rem_by_anchor[key]), len(add_by_anchor[key]))
        for _ in range(pairs):
            rid = rem_by_anchor[key].pop(0)
            aid = add_by_anchor[key].pop(0)
            matched_added.add(aid)
            matched_removed.add(rid)
            old_ent, new_ent = old_map[rid], new_map[aid]
            changed_fields: dict[str, Any] = {"id": [rid, aid]}
            old_line, new_line = _anchor_line(rid), _anchor_line(aid)
            if old_line is not None and new_line is not None and old_line != new_line:
                changed_fields["line"] = [old_line, new_line]
            diffs.append(
                NodeDiff(
                    entity_id=aid,
                    entity_name=_display_name(new_ent),
                    entity_type=_get_type(new_ent),
                    file_path=file_path,
                    change_kind="modified",
                    changed_fields=changed_fields,
                    old_hash=None,
                    new_hash=None,
                )
            )

    remaining_added = added_ids - matched_added
    remaining_removed = removed_ids - matched_removed

    # 2c. Same-name pairing: equal raw (hash-stripped) display names in the
    # same file are the same symbol under a new id (param-hash/signature
    # change) — emit modified with the id swap rather than add+remove pairs.
    def _raw_name(e: Any) -> str:
        return _PARAM_HASH.sub("", _display_name(e))

    rem_by_name: dict[str, list[str]] = {}
    for rid in sorted(remaining_removed, key=lambda r: _raw_name(old_map[r])):
        rem_by_name.setdefault(_raw_name(old_map[rid]), []).append(rid)

    for aid in sorted(remaining_added, key=lambda a: _raw_name(new_map[a])):
        name_key = _raw_name(new_map[aid])
        bucket = rem_by_name.get(name_key)
        if not bucket:
            continue
        rid = bucket.pop(0)
        matched_added.add(aid)
        matched_removed.add(rid)
        old_ent, new_ent = old_map[rid], new_map[aid]
        changed_fields = {"id": [rid, aid]}
        for f in TRACKED_FIELDS:
            old_val = _get_type(old_ent) if f == "entity_type" else _get_val(old_ent, f)
            new_val = _get_type(new_ent) if f == "entity_type" else _get_val(new_ent, f)
            if old_val != new_val:
                changed_fields[f] = [old_val, new_val]
        old_ch = _get_val(old_ent, "content_hash") or ""
        new_ch = _get_val(new_ent, "content_hash") or ""
        diffs.append(
            NodeDiff(
                entity_id=aid,
                entity_name=_display_name(new_ent),
                entity_type=_get_type(new_ent),
                file_path=file_path,
                change_kind="modified",
                changed_fields=changed_fields,
                old_hash=old_ch[:8] if old_ch else None,
                new_hash=new_ch[:8] if new_ch else None,
            )
        )

    remaining_added = added_ids - matched_added
    remaining_removed = removed_ids - matched_removed

    # 3. Pure adds and removes
    for aid in sorted(remaining_added):
        new_ent = new_map[aid]
        ch = _get_val(new_ent, "content_hash")
        diffs.append(
            NodeDiff(
                entity_id=aid,
                entity_name=_display_name(new_ent),
                entity_type=_get_type(new_ent),
                file_path=file_path,
                change_kind="added",
                changed_fields={},
                old_hash=None,
                new_hash=ch[:8] if ch else None,
            )
        )

    for rid in sorted(remaining_removed):
        old_ent = old_map[rid]
        ch = _get_val(old_ent, "content_hash")
        diffs.append(
            NodeDiff(
                entity_id=rid,
                entity_name=_display_name(old_ent),
                entity_type=_get_type(old_ent),
                file_path=file_path,
                change_kind="removed",
                changed_fields={},
                old_hash=ch[:8] if ch else None,
                new_hash=None,
            )
        )

    return diffs
