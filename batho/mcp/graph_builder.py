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
                in_parts = [
                    f"{_rel_arrow(r.get('relation_type', ''))}: {name_by_id.get(r.get('source_id', ''), r.get('source_id', ''))}"
                    for r in incoming
                ]
                prefix += " ← " + ", ".join(in_parts)
            lines.append(prefix)
            lines.append(f"  `{eid}`")
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
            lines.append(f"`{eid}`")
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
    indexed_files = sum(1 for f in stats.get("files", []) if f.get("indexed", False))
    lines.append(f"- {total_entities} entities across {total_files} files ({indexed_files} indexed)")
    lines.append(f"- {total_rels} relationships")

    # Scale classification
    if total_entities > 50000:
        scale = "very large"
    elif total_entities > 10000:
        scale = "large"
    elif total_entities > 1000:
        scale = "medium"
    elif total_entities > 100:
        scale = "small"
    else:
        scale = "minimal"
    lines.append(f"- Scale: {scale} codebase")

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

    # Entity type breakdown
    entity_breakdown = stats.get("entity_breakdown", {})
    if entity_breakdown:
        lines.append("### Entity Types")
        parts = [f"{k}: {v}" for k, v in sorted(entity_breakdown.items(), key=lambda x: -x[1])]
        lines.append(" | ".join(parts))
        lines.append("")

    # Relationship type distribution
    rel_breakdown = stats.get("relationship_breakdown", {})
    if rel_breakdown:
        lines.append("### Relationships")
        parts = [f"{k}: {v}" for k, v in sorted(rel_breakdown.items(), key=lambda x: -x[1])]
        lines.append(" | ".join(parts))
        lines.append("")

    # Top files by entity count
    files_list = stats.get("files", [])
    if files_list:
        top_files = sorted(files_list, key=lambda f: f.get("entities", 0), reverse=True)
        top_files = [f for f in top_files if f.get("entities", 0) > 0][:10]
        if top_files:
            lines.append("### Top Files")
            file_parts = [f"{f['path']}: {f['entities']} entities" for f in top_files]
            lines.append(" | ".join(file_parts))
            lines.append("")

    # Top-level directory structure
    if files_list:
        dir_counts: dict[str, int] = {}
        dir_file_counts: dict[str, int] = {}
        for f in files_list:
            path = f.get("path", "")
            parts = path.split("/")
            top_dir = parts[0] if len(parts) > 1 else "(root)"
            ent = f.get("entities", 0)
            dir_counts[top_dir] = dir_counts.get(top_dir, 0) + ent
            dir_file_counts[top_dir] = dir_file_counts.get(top_dir, 0) + 1
        # Only show directories with entities, or top 5 by file count if none have entities
        sorted_dirs = sorted(dir_counts.items(), key=lambda x: -x[1])
        dirs_with_entities = [(d, c) for d, c in sorted_dirs if c > 0]
        if dirs_with_entities:
            sorted_dirs = dirs_with_entities[:8]
            lines.append("### Module Structure")
            dir_parts = [f"{d}/: {c} entities ({dir_file_counts[d]} files)" for d, c in sorted_dirs]
            lines.append(" | ".join(dir_parts))
            lines.append("")
        elif total_files > 0:
            # No entities in any directory — show top dirs by file count
            sorted_by_files = sorted(dir_file_counts.items(), key=lambda x: -x[1])[:5]
            lines.append("### Module Structure")
            dir_parts = [f"{d}/: {fc} files" for d, fc in sorted_by_files]
            lines.append(" | ".join(dir_parts))
            lines.append("")

    # Density metrics
    if total_files > 0 and total_entities > 0:
        avg_ent_per_file = total_entities / total_files
        avg_rel_per_ent = total_rels / total_entities if total_entities else 0
        files_with_entities = sum(1 for f in files_list if f.get("entities", 0) > 0) if files_list else 0
        lines.append("### Density")
        lines.append(f"Avg {avg_ent_per_file:.1f} entities/file | Avg {avg_rel_per_ent:.1f} relationships/entity")
        if files_with_entities > 0:
            lines.append(f"{files_with_entities} files with entities | {total_files - files_with_entities} files without")
        lines.append("")

    # Connectivity assessment
    if total_entities > 0 and total_rels > 0:
        connectivity_ratio = total_rels / total_entities
        if connectivity_ratio > 3.0:
            connectivity = "highly connected"
        elif connectivity_ratio > 1.5:
            connectivity = "moderately connected"
        elif connectivity_ratio > 0.5:
            connectivity = "loosely connected"
        else:
            connectivity = "sparse"
        lines.append("### Connectivity")
        lines.append(f"{connectivity_ratio:.1f} rels/entity — {connectivity}")
        lines.append("")

    # Architectural patterns (heuristic-based)
    patterns: list[str] = []
    if entity_breakdown:
        unresolved_count = entity_breakdown.get("UNRESOLVED", 0)
        if total_entities > 0 and unresolved_count / total_entities > 0.20:
            pct = int(unresolved_count / total_entities * 100)
            patterns.append(f"External dependencies significant ({pct}% unresolved)")
        function_count = entity_breakdown.get("FUNCTION", 0) + entity_breakdown.get("METHOD", 0)
        class_count = entity_breakdown.get("CLASS", 0)
        if class_count > 0 and function_count > class_count * 3:
            patterns.append("Function-centric codebase")
        elif class_count > 0:
            patterns.append("Class-oriented architecture")
    if rel_breakdown:
        imports_count = rel_breakdown.get("IMPORTS", 0)
        inherits_count = rel_breakdown.get("INHERITS", 0)
        calls_count = rel_breakdown.get("CALLS", 0)
        contains_count = rel_breakdown.get("CONTAINS", 0)
        if imports_count > 0 and total_entities > 0 and imports_count / total_entities > 0.15:
            patterns.append("Modular architecture with explicit imports")
        if inherits_count > 0:
            patterns.append("OOP with class inheritance")
        if calls_count > 0 and contains_count > 0 and calls_count > contains_count:
            patterns.append("Call-heavy interaction graph")
        if contains_count > 0 and total_entities > 0 and contains_count / total_entities > 0.3:
            patterns.append("Nested entity structure")
    if patterns:
        lines.append("### Patterns")
        lines.append(" | ".join(patterns))
        lines.append("")

    # Key observations — descriptive summary for orientation
    observations: list[str] = []
    if entity_breakdown and total_entities > 0:
        top_type = max(entity_breakdown.items(), key=lambda x: x[1])
        pct = int(top_type[1] / total_entities * 100)
        observations.append(f"Dominant entity type: {top_type[0]} ({pct}% of all entities)")
    if rel_breakdown and total_rels > 0:
        top_rel = max(rel_breakdown.items(), key=lambda x: x[1])
        pct = int(top_rel[1] / total_rels * 100)
        observations.append(f"Dominant relationship: {top_rel[0]} ({pct}% of all relationships)")
    if files_list and total_files > 0:
        files_with_ent = sum(1 for f in files_list if f.get("entities", 0) > 0)
        if files_with_ent > 0:
            max_file = max(files_list, key=lambda f: f.get("entities", 0))
            observations.append(f"Largest file: {max_file['path']} ({max_file['entities']} entities)")
            coverage = int(files_with_ent / total_files * 100)
            observations.append(f"Entity coverage: {files_with_ent}/{total_files} files ({coverage}%)")
    if total_entities > 0 and total_rels > 0:
        ratio = total_rels / total_entities
        if ratio > 2.0:
            observations.append("High relationship density suggests complex interdependencies")
        elif ratio < 0.5:
            observations.append("Low relationship density suggests isolated components")
    if observations:
        lines.append("### Key Observations")
        for obs in observations:
            lines.append(f"- {obs}")
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
