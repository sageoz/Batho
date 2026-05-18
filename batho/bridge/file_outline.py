"""File outline builder using BSG data."""

from __future__ import annotations

from typing import Any


def build_file_outline(bsg_data: dict[str, Any], file_path: str) -> dict[str, Any]:
    """Build a nested outline for a file based on line-range containment."""
    normalized = _normalize_path(file_path)
    if not normalized:
        return {"file": file_path, "nodes": [], "node_count": 0}

    nodes = _collect_nodes(bsg_data, normalized)
    outline_nodes = [_to_outline_node(n) for n in nodes]

    # Sort by start asc, end desc to support containment stack.
    outline_nodes.sort(key=lambda n: (n["start_line"], -(n["end_line"] or n["start_line"])) )

    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []

    for node in outline_nodes:
        start = node.get("start_line", 0)
        end = node.get("end_line", 0) or start
        node["children"] = []

        while stack:
            parent = stack[-1]
            parent_end = parent.get("end_line", 0) or parent.get("start_line", 0)
            if start > parent_end:
                stack.pop()
                continue
            break

        if stack:
            parent = stack[-1]
            parent_start = parent.get("start_line", 0)
            parent_end = parent.get("end_line", 0) or parent_start
            if start >= parent_start and end <= parent_end:
                parent["children"].append(node)
            else:
                roots.append(node)
        else:
            roots.append(node)

        stack.append(node)

    return {
        "file": normalized,
        "nodes": roots,
        "node_count": len(outline_nodes),
    }


def _collect_nodes(bsg_data: dict[str, Any], file_path: str) -> list[dict[str, Any]]:
    if not bsg_data or not isinstance(bsg_data, dict):
        return []

    indexes = bsg_data.get("indexes") or {}
    nodes_by_file = indexes.get("nodes_by_file") if isinstance(indexes, dict) else None

    nodes = bsg_data.get("nodes") if isinstance(bsg_data.get("nodes"), list) else []
    if nodes_by_file and isinstance(nodes_by_file, dict):
        node_ids = nodes_by_file.get(file_path) or nodes_by_file.get(file_path.lstrip("./"))
        if isinstance(node_ids, list) and nodes:
            by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}
            return [by_id[nid] for nid in node_ids if nid in by_id]

    # Fallback to scanning nodes for matching file.
    out = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_file = _normalize_path(str(node.get("file") or ""))
        if node_file == file_path:
            out.append(node)
    return out


def _normalize_path(path: str) -> str:
    if not path:
        return ""
    return path.lstrip("./").lstrip("/")


def _to_outline_node(node: dict[str, Any]) -> dict[str, Any]:
    start = _coerce_line(node.get("start_line") or node.get("startLine"))
    end = _coerce_line(node.get("end_line") or node.get("endLine"))
    if end and start and end < start:
        end = start

    return {
        "id": node.get("id"),
        "name": node.get("name"),
        "type": node.get("type") or node.get("kind"),
        "file": node.get("file"),
        "start_line": start,
        "end_line": end,
        "signature": node.get("signature"),
        "language": node.get("language"),
        "scope_tier": node.get("scope_tier") or node.get("scopeTier"),
        "category": node.get("category"),
        "children": [],
    }


def _coerce_line(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "build_file_outline",
]
