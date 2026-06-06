"""Shared helpers for Arrow Bundle write path and JSON export rendering.

Migrated from batho/modules/storage/sqlite_registry/engine.py.
No SQLite dependency.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Key minification / expansion (msgpack-compact keys, v4)
# ---------------------------------------------------------------------------

def _minify_entity(e: dict[str, Any]) -> dict[str, Any]:
    mini = {}
    if "id" in e:
        mini["id"] = e["id"]

    key_map = {
        "entity_type": "ty",
        "type": "ty",
        "name": "n",
        "file": "f",
        "start_line": "sl",
        "end_line": "el",
        "signature": "s",
        "parent_id": "p",
        "content_hash": "h",
        "ast_node_type": "an",
        "start_byte": "sb",
        "end_byte": "eb",
        "raw_content": "rc",
        "raw_bytes": "rb",
        "children_order": "co",
        "metadata": "m",
    }
    for k, v in key_map.items():
        if k in e and e[k] is not None:
            mini[v] = e[k]

    if "syntax_glue" in e and e["syntax_glue"]:
        sg = e["syntax_glue"]
        mini_sg = {}
        if "leading_whitespace" in sg:
            mini_sg["lw"] = sg["leading_whitespace"]
        if "trailing_whitespace" in sg:
            mini_sg["tw"] = sg["trailing_whitespace"]
        mini["sg"] = mini_sg

    return mini


def _expand_entity(mini: dict[str, Any]) -> dict[str, Any]:
    e = {}
    if "id" in mini:
        e["id"] = mini["id"]

    rev_map = {
        "ty": "entity_type",
        "n": "name",
        "f": "file",
        "sl": "start_line",
        "el": "end_line",
        "s": "signature",
        "p": "parent_id",
        "h": "content_hash",
        "an": "ast_node_type",
        "sb": "start_byte",
        "eb": "end_byte",
        "rc": "raw_content",
        "rb": "raw_bytes",
        "co": "children_order",
        "m": "metadata",
    }
    for k, v in rev_map.items():
        if k in mini:
            e[v] = mini[k]
            if v == "entity_type":
                e["type"] = mini[k]

    if "sg" in mini and mini["sg"]:
        sg = mini["sg"]
        e["syntax_glue"] = {
            "leading_whitespace": sg.get("lw", ""),
            "trailing_whitespace": sg.get("tw", ""),
        }
        e["leading_whitespace"] = sg.get("lw", "")
        e["trailing_whitespace"] = sg.get("tw", "")

    mapped_keys = set(rev_map.keys()) | {"id", "sg"}
    for k, v in mini.items():
        if k not in mapped_keys and k not in e:
            e[k] = v

    return e


def _minify_relationship(r: dict[str, Any]) -> dict[str, Any]:
    mini = {}
    if "id" in r:
        mini["id"] = r["id"]
    elif "relationship_id" in r:
        mini["id"] = r["relationship_id"]

    key_map = {
        "type": "rt",
        "relationship_type": "rt",
        "source_id": "s",
        "target_id": "t",
        "roles": "ro",
        "reference_start_byte": "rs",
        "reference_end_byte": "re",
        "definition_start_byte": "ds",
        "definition_end_byte": "de",
        "metadata": "m",
    }
    for k, v in key_map.items():
        if k in r and r[k] is not None:
            mini[v] = r[k]
    return mini


def _expand_relationship(mini: dict[str, Any]) -> dict[str, Any]:
    r = {}
    if "id" in mini:
        r["id"] = mini["id"]
        r["relationship_id"] = mini["id"]
    elif "relationship_id" in mini:
        r["relationship_id"] = mini["relationship_id"]

    rev_map = {
        "rt": "type",
        "s": "source_id",
        "t": "target_id",
        "ro": "roles",
        "rs": "reference_start_byte",
        "re": "reference_end_byte",
        "ds": "definition_start_byte",
        "de": "definition_end_byte",
        "m": "metadata",
    }
    for k, v in rev_map.items():
        if k in mini:
            r[v] = mini[k]
    if "type" in r:
        r["relationship_type"] = r["type"]

    mapped_keys = set(rev_map.keys()) | {"id", "relationship_id"}
    for k, v in mini.items():
        if k not in mapped_keys and k not in r:
            r[k] = v

    return r


def _minify_graph_payload(graph_data: dict[str, Any]) -> dict[str, Any]:
    mini = {}
    if "entities" in graph_data:
        mini["e"] = [_minify_entity(e) for e in graph_data["entities"]]
    if "relationships" in graph_data:
        mini["r"] = [_minify_relationship(r) for r in graph_data["relationships"]]
    return mini


def _expand_graph_payload(minified: dict[str, Any]) -> dict[str, Any]:
    expanded = {}
    if "e" in minified:
        expanded["entities"] = [_expand_entity(e) for e in minified["e"]]
    else:
        expanded["entities"] = []
    if "r" in minified:
        expanded["relationships"] = [_expand_relationship(r) for r in minified["r"]]
    else:
        expanded["relationships"] = []
    return expanded


# ---------------------------------------------------------------------------
# Scratch-store helpers
# ---------------------------------------------------------------------------

def _extract_name_from_entity_id(entity_id: str) -> str:
    """Extract the human-readable symbol name from an opaque entity ID."""
    if "#" in entity_id:
        name = entity_id.rsplit("#", 1)[-1].rstrip("().")
        if name:
            return name
    if "/" in entity_id:
        return entity_id.rsplit("/", 1)[-1]
    return entity_id


_PSEUDO_TARGET_PREFIXES = (
    "external:", "file:", "anchor:", "unresolved:", "symbol:",
    "image:", "import:", "stylesheet:", "resource:", "variable:",
)


def _accumulate_scratch_rows(
    *,
    store: Any,
    run_internal_id: int,
    file_path: str,
    agent_view_data: dict,
    relationships_data: list,
    entity_ids_in_batch: set[str],
    delta_store: Any = None,
) -> None:
    """Resolve entity IDs via BSG store and append rows to BsgScratchStore buffers.

    If delta_store is provided (patch run), rows are also appended there.
    """
    import json as _json

    entities = agent_view_data.get("entities", [])

    all_ids: list[str] = []
    for e in entities:
        if e.get("id"):
            all_ids.append(e["id"])
    for r in relationships_data:
        if r.get("source_id"):
            all_ids.append(r["source_id"])
        if r.get("target_id"):
            all_ids.append(r["target_id"])

    entity_keys = store.bulk_get_or_create_entity_keys(all_ids)

    entity_rows: list[tuple] = []
    unresolved_ids: dict[str, str] = {}

    for e in entities:
        eid = e.get("id")
        ename = e.get("name")
        etype = e.get("type") or e.get("entity_type")
        if not eid or not ename or not etype:
            continue
        if isinstance(etype, str) and etype.upper() == "UNRESOLVED":
            unresolved_ids[eid] = ename
        ekey = entity_keys.get(eid)
        if ekey is not None:
            entity_rows.append((
                ekey,
                run_internal_id,
                ename,
                etype,
                e.get("fqn"),
                file_path,
                e.get("start_line") or e.get("line") or 1,
                e.get("signature"),
                bool(e.get("is_exported", False)),
            ))

    rel_rows: list[tuple] = []
    dangling_rows: list[tuple] = []

    for r in relationships_data:
        src_id = r.get("source_id")
        tgt_id = r.get("target_id")
        r_type = r.get("type") or r.get("relationship_type")
        if not src_id or not tgt_id or not r_type:
            continue
        src_key = entity_keys.get(src_id)
        if src_key is None:
            continue

        meta = _json.dumps(r.get("metadata") or {})
        is_pseudo = any(tgt_id.startswith(p) for p in _PSEUDO_TARGET_PREFIXES)

        if is_pseudo:
            tgt_key = entity_keys.get(tgt_id)
            if tgt_key is not None:
                rel_rows.append((src_key, tgt_key, r_type, run_internal_id, meta))
        elif tgt_id in unresolved_ids:
            dangling_rows.append((src_key, unresolved_ids[tgt_id], r_type, run_internal_id))
        elif tgt_id not in entity_ids_in_batch:
            target_name = _extract_name_from_entity_id(tgt_id)
            dangling_rows.append((src_key, target_name, r_type, run_internal_id))
        else:
            tgt_key = entity_keys.get(tgt_id)
            if tgt_key is not None:
                rel_rows.append((src_key, tgt_key, r_type, run_internal_id, meta))

    if entity_rows:
        store.append_entities(entity_rows)
    if rel_rows:
        store.append_relationships(rel_rows)
    if dangling_rows:
        store.append_dangling(dangling_rows)

    if delta_store is not None:
        if entity_rows:
            delta_store.append_entities(entity_rows)
        if rel_rows:
            delta_store.append_relationships(rel_rows)
        if dangling_rows:
            delta_store.append_dangling(dangling_rows)
