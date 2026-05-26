from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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

TRACKED_FIELDS = ("signature", "start_line", "end_line", "entity_type")

def _get_val(e: Any, key: str) -> Any:
    if isinstance(e, dict):
        return e.get(key)
    return getattr(e, key, None)

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
    5. Pure adds/removes: Emit remaining added_ids and removed_ids.
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
            old_val = _get_val(old_ent, f)
            new_val = _get_val(new_ent, f)
            if old_val != new_val:
                changed_fields[f] = [old_val, new_val]

        if changed_fields:
            name = _get_val(new_ent, "name") or ""
            type_str = _get_val(new_ent, "type") or _get_val(new_ent, "entity_type") or ""
            diffs.append(
                NodeDiff(
                    entity_id=eid,
                    entity_name=name,
                    entity_type=str(type_str),
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

            name = _get_val(new_ent, "name") or ""
            type_str = _get_val(new_ent, "type") or _get_val(new_ent, "entity_type") or ""
            diffs.append(
                NodeDiff(
                    entity_id=aid,
                    entity_name=name,
                    entity_type=str(type_str),
                    file_path=file_path,
                    change_kind="renamed",
                    changed_fields={"old_id": rid},
                    old_hash=ch[:8] if ch else None,
                    new_hash=ch[:8] if ch else None,
                )
            )

    # 3. Pure adds and removes
    remaining_added = added_ids - matched_added
    remaining_removed = removed_ids - matched_removed

    for aid in sorted(remaining_added):
        new_ent = new_map[aid]
        ch = _get_val(new_ent, "content_hash")
        name = _get_val(new_ent, "name") or ""
        type_str = _get_val(new_ent, "type") or _get_val(new_ent, "entity_type") or ""
        diffs.append(
            NodeDiff(
                entity_id=aid,
                entity_name=name,
                entity_type=str(type_str),
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
        name = _get_val(old_ent, "name") or ""
        type_str = _get_val(old_ent, "type") or _get_val(old_ent, "entity_type") or ""
        diffs.append(
            NodeDiff(
                entity_id=rid,
                entity_name=name,
                entity_type=str(type_str),
                file_path=file_path,
                change_kind="removed",
                changed_fields={},
                old_hash=ch[:8] if ch else None,
                new_hash=None,
            )
        )

    return diffs
