"""Arrow → Node/Edge + markdown builder + token budget.

Converts IPC row dicts into dual output:
  - content: compact markdown (model-facing, 34-38% fewer tokens than JSON)
  - structuredContent: full JSON {nodes, edges} (machine-facing)
"""

from __future__ import annotations

from typing import Any

TOKEN_HEURISTIC_DIVISOR = 4


def estimate_tokens(text: str) -> int:
    return len(text) // TOKEN_HEURISTIC_DIVISOR


def truncate_to_budget(markdown: str, max_tokens: int) -> tuple[str, bool]:
    est = estimate_tokens(markdown)
    if est <= max_tokens:
        return markdown, False
    max_chars = max_tokens * TOKEN_HEURISTIC_DIVISOR
    truncated = markdown[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > 0:
        truncated = truncated[:last_nl]
    return truncated, True


def _abbrev_type(entity_type: str) -> str:
    mapping = {
        "FUNCTION": "FUNC", "METHOD": "METH", "CLASS": "CLASS",
        "MODULE": "MOD", "STRUCT": "STRUCT", "INTERFACE": "IFACE",
        "FIELD": "FIELD", "ENUM": "ENUM", "TRAIT": "TRAIT",
        "TYPE_ALIAS": "TYPE", "CONSTANT": "CONST", "NAMESPACE": "NS",
        "VARIABLE": "VAR", "PROPERTY": "PROP", "ENTRY_POINT": "ENTRY",
        "EXTERNAL_SYMBOL": "EXT", "GLOBAL_STATEMENT": "STMT",
        "IMPORT_BLOCK": "IMPORT", "COMMENT_BLOCK": "COMMENT",
    }
    return mapping.get(entity_type.upper(), entity_type[:8])


def _rel_arrow(relation_type: str) -> str:
    mapping = {
        "CALLS": "calls", "IMPORTS": "imports", "INHERITS": "inherits",
        "IMPLEMENTS": "implements", "USES": "uses", "CONTAINS": "contains",
        "REFERENCES": "references", "DEFINES": "defines",
        "CALLED_BY": "called by", "IMPORTED_BY": "imported by",
        "OVERRIDES": "overrides", "WRAPPED_BY": "wrapped by",
        "DEPENDS_ON_API": "depends on", "REFERENCED_IN": "referenced in",
        "CONTAINED_WITHIN": "contained in", "HAS_ATTRIBUTE": "has attr",
        "LINKS_TO": "links to", "IMPORTS_STYLE": "imports style",
    }
    return mapping.get(relation_type.upper(), relation_type.lower())


def _line_range(start_line: int | None, end_line: int | None) -> str:
    if start_line is None:
        return ""
    if end_line is None or end_line == start_line:
        return f"L{start_line}"
    return f"L{start_line}-{end_line}"


def build_node_dict(agent_row: dict, storage_row: dict | None = None) -> dict:
    node = {
        "id": agent_row.get("entity_id", ""),
        "type": agent_row.get("entity_type", ""),
        "name": agent_row.get("name", ""),
        "file": "",
        "start_line": agent_row.get("start_line"),
        "end_line": agent_row.get("end_line"),
        "signature": agent_row.get("signature"),
        "is_exported": agent_row.get("is_exported", False),
        "fqn": agent_row.get("fqn"),
        "parent_id": None,
        "metadata": {},
    }
    if storage_row:
        node["parent_id"] = storage_row.get("parent_id")
        node["start_byte"] = storage_row.get("start_byte")
        node["end_byte"] = storage_row.get("end_byte")
    return node


def build_edge_dict(rel_row: dict) -> dict:
    edge = {
        "id": "",
        "source": rel_row.get("source_id", ""),
        "target": rel_row.get("target_id", ""),
        "relation_type": rel_row.get("relation_type", ""),
        "metadata": {},
    }
    meta_json = rel_row.get("metadata_json")
    if meta_json:
        import json
        try:
            edge["metadata"] = json.loads(meta_json)
        except Exception:
            pass
    return edge


def build_meta(
    total_nodes: int, total_edges: int,
    returned_nodes: int, returned_edges: int,
    offset: int, limit: int, truncated: bool,
    generation: int, tokens_used: int, token_budget: int,
) -> dict:
    return {
        "total_nodes": total_nodes, "total_edges": total_edges,
        "returned_nodes": returned_nodes, "returned_edges": returned_edges,
        "offset": offset, "limit": limit, "truncated": truncated,
        "artifact_generation": generation,
        "tokens_used": tokens_used, "token_budget": token_budget,
    }


def format_concise(
    agent_rows: list[dict],
    rels_rows: list[dict],
    file_paths: dict[int, str],
) -> str:
    lines: list[str] = []
    by_file: dict[str, list[dict]] = {}
    for row in agent_rows:
        fp = file_paths.get(row.get("file_id", -1), "unknown")
        by_file.setdefault(fp, []).append(row)

    rels_by_source: dict[str, list[dict]] = {}
    rels_by_target: dict[str, list[dict]] = {}
    name_by_id: dict[str, str] = {r.get("entity_id", ""): r.get("name", "") for r in agent_rows}
    for rel in rels_rows:
        sid = rel.get("source_id", "")
        tid = rel.get("target_id", "")
        rels_by_source.setdefault(sid, []).append(rel)
        rels_by_target.setdefault(tid, []).append(rel)

    for fp, rows in sorted(by_file.items()):
        lines.append(f"## {fp} ({len(rows)} entities)")
        for row in rows:
            eid = row.get("entity_id", "")
            etype = _abbrev_type(row.get("entity_type", ""))
            lr = _line_range(row.get("start_line"), row.get("end_line"))
            name = row.get("name", "")
            prefix = f"- {name} [{etype} {lr}]"
            outgoing = rels_by_source.get(eid, [])
            if outgoing:
                targets = [name_by_id.get(r.get("target_id", ""), r.get("target_id", "")) for r in outgoing]
                rel_types = [_rel_arrow(r.get("relation_type", "")) for r in outgoing]
                parts = [f"{rt}: {t}" for rt, t in zip(rel_types, targets)]
                prefix += " → " + ", ".join(parts)
            incoming = rels_by_target.get(eid, [])
            if incoming:
                sources = [name_by_id.get(r.get("source_id", ""), r.get("source_id", "")) for r in incoming]
                prefix += f" ← called by: {', '.join(sources)}"
            lines.append(prefix)
        lines.append("")

    footer = f"{len(agent_rows)} entities · {len(rels_rows)} relationships · {len(by_file)} files"
    lines.append(footer)
    return "\n".join(lines)


def format_detailed(
    agent_rows: list[dict],
    rels_rows: list[dict],
    storage_rows: list[dict] | None,
    file_paths: dict[int, str],
) -> str:
    lines: list[str] = []
    storage_by_id: dict[str, dict] = {}
    if storage_rows:
        for sr in storage_rows:
            sid = sr.get("entity_id", "")
            if sid:
                storage_by_id[sid] = sr

    by_file: dict[str, list[dict]] = {}
    for row in agent_rows:
        fp = file_paths.get(row.get("file_id", -1), "unknown")
        by_file.setdefault(fp, []).append(row)

    rels_by_source: dict[str, list[dict]] = {}
    rels_by_target: dict[str, list[dict]] = {}
    name_by_id: dict[str, str] = {r.get("entity_id", ""): r.get("name", "") for r in agent_rows}
    file_by_id: dict[str, str] = {}
    for row in agent_rows:
        fp = file_paths.get(row.get("file_id", -1), "")
        file_by_id[row.get("entity_id", "")] = fp

    for rel in rels_rows:
        rels_by_source.setdefault(rel.get("source_id", ""), []).append(rel)
        rels_by_target.setdefault(rel.get("target_id", ""), []).append(rel)

    for fp, rows in sorted(by_file.items()):
        lines.append(f"## {fp} ({len(rows)} entities)")
        lines.append("")
        for row in rows:
            eid = row.get("entity_id", "")
            etype = row.get("entity_type", "")
            name = row.get("name", "")
            lr = _line_range(row.get("start_line"), row.get("end_line"))
            lines.append(f"### {name} [{etype} {lr}]")
            sig = row.get("signature")
            if sig:
                lines.append(f"Signature: {sig}")
            exported = row.get("is_exported", False)
            fqn = row.get("fqn")
            extra = []
            if exported:
                extra.append("Exported: yes")
            if fqn:
                extra.append(f"FQN: {fqn}")
            if extra:
                lines.append(" · ".join(extra))

            outgoing = rels_by_source.get(eid, [])
            if outgoing:
                lines.append("### Outgoing")
                for rel in outgoing:
                    rt = _rel_arrow(rel.get("relation_type", ""))
                    tid = rel.get("target_id", "")
                    tname = name_by_id.get(tid, tid)
                    tfile = file_by_id.get(tid, "")
                    lines.append(f"  → {rt}: {tname} ({tfile})")

            incoming = rels_by_target.get(eid, [])
            if incoming:
                lines.append("### Incoming")
                for rel in incoming:
                    rt = _rel_arrow(rel.get("relation_type", ""))
                    sid = rel.get("source_id", "")
                    sname = name_by_id.get(sid, sid)
                    sfile = file_by_id.get(sid, "")
                    lines.append(f"  ← {rt}: {sname} ({sfile})")
            lines.append("")

    footer = f"{len(agent_rows)} entities · {len(rels_rows)} relationships · {len(by_file)} files"
    lines.append(footer)
    return "\n".join(lines)


def format_summary(
    stats: dict,
    communities: list[dict] | None = None,
) -> str:
    lines: list[str] = []
    lines.append("## Codebase Overview")
    total_entities = stats.get("total_entities", 0)
    total_rels = stats.get("total_relationships", 0)
    total_files = stats.get("total_files", 0)
    lines.append(f"- {total_entities} entities across {total_files} files")
    lines.append(f"- {total_rels} relationships")

    rel_breakdown = stats.get("relationship_breakdown", {})
    if rel_breakdown:
        parts = [f"{k}: {v}" for k, v in sorted(rel_breakdown.items(), key=lambda x: -x[1])]
        lines.append(f"  ({', '.join(parts)})")

    gen = stats.get("artifact_generation")
    if gen is not None:
        lines.append(f"- Artifact gen {gen}")
    run_id = stats.get("run_id")
    if run_id:
        lines.append(f"  · run {run_id}")
    git_commit = stats.get("git_commit")
    if git_commit:
        lines.append(f"  · git {git_commit}")
    lines.append("")

    if communities:
        for comm in communities:
            cname = comm.get("name", "Unnamed")
            centity = comm.get("entity_count", 0)
            cfiles = comm.get("file_count", 0)
            lines.append(f"## Community: {cname} ({centity} entities, {cfiles} files)")
            desc = comm.get("description")
            if desc:
                lines.append(desc)
            top = comm.get("top_entities", [])
            if top:
                lines.append(f"Key entities: {', '.join(top[:5])}")
            lines.append("")

    files_list = stats.get("files", [])
    if files_list:
        lines.append("## Files")
        file_parts = [f"{f['path']}: {f['entities']} entities" for f in files_list[:20]]
        lines.append(" · ".join(file_parts))
        if len(files_list) > 20:
            lines.append(f"  ... and {len(files_list) - 20} more")

    return "\n".join(lines)


def build_dual_output(
    agent_rows: list[dict],
    rels_rows: list[dict],
    file_paths: dict[int, str],
    storage_rows: list[dict] | None = None,
    response_format: str = "concise",
    max_tokens: int = 25000,
    offset: int = 0,
    limit: int = 50,
    total_nodes: int | None = None,
    total_edges: int | None = None,
    artifact_generation: int = 0,
) -> tuple[str, dict]:
    if response_format == "detailed":
        markdown = format_detailed(agent_rows, rels_rows, storage_rows, file_paths)
    else:
        markdown = format_concise(agent_rows, rels_rows, file_paths)

    truncated_md, was_truncated = truncate_to_budget(markdown, max_tokens)
    if was_truncated:
        est_tokens = estimate_tokens(truncated_md)
        truncated_md += f"\n\n---\nTruncated to fit {max_tokens} token budget. "
        truncated_md += f"More: graph_query(offset={offset + limit}, limit={limit})"

    nodes = [build_node_dict(r) for r in agent_rows]
    edges = [build_edge_dict(r) for r in rels_rows]

    tn = total_nodes if total_nodes is not None else len(agent_rows)
    te = total_edges if total_edges is not None else len(rels_rows)

    meta = build_meta(
        total_nodes=tn, total_edges=te,
        returned_nodes=len(nodes), returned_edges=len(edges),
        offset=offset, limit=limit, truncated=was_truncated,
        generation=artifact_generation,
        tokens_used=estimate_tokens(truncated_md), token_budget=max_tokens,
    )

    structured = {"graph": {"nodes": nodes, "edges": edges}, "meta": meta}
    return truncated_md, structured
