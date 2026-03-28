#!/usr/bin/env python3
"""
Extract and transform .ctn graph data into a frontend-consumable JSON.

Reads .ctn/index.json → finds current snapshot → loads graph.json →
produces a trimmed, visualization-optimized JSON at frontend/src/data/graphData.json.

Usage:
    python3 extract_graph_data.py
    python3 extract_graph_data.py --index-id <specific_index_id>
"""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Entity types relevant for code visualization (skip config/doc noise)
CODE_ENTITY_TYPES = {
    "CLASS", "METHOD", "FUNCTION", "INTERFACE", "STRUCT",
    "ENUM", "TRAIT", "NAMESPACE", "ENTRY_POINT", "ATTRIBUTE",
    "FIELD",
}

# Relationship types to include
CODE_RELATIONSHIP_TYPES = {
    "IMPORTS", "CALLS", "USES", "REFERENCES", "CONTAINS", "HAS_ATTRIBUTE",
}

# Color mapping for entity types (used by frontend)
TYPE_COLORS = {
    "CLASS": "#5dd9d8",
    "METHOD": "#3b82f6",
    "FUNCTION": "#8b5cf6",
    "INTERFACE": "#f59e0b",
    "STRUCT": "#10b981",
    "ENUM": "#ec4899",
    "TRAIT": "#f97316",
    "NAMESPACE": "#6366f1",
    "ENTRY_POINT": "#ef4444",
    "ATTRIBUTE": "#64748b",
    "FIELD": "#94a3b8",
}

EDGE_COLORS = {
    "IMPORTS": "#5dd9d8",
    "CALLS": "#3b82f6",
    "CONTAINS": "rgba(139, 152, 171, 0.3)",
    "USES": "#f59e0b",
    "REFERENCES": "#8b5cf6",
    "HAS_ATTRIBUTE": "#64748b",
}


def find_workspace_root():
    """Find workspace root by locating .ctn folder."""
    current = Path.cwd()
    while current != current.parent:
        if (current / ".ctn").is_dir():
            return current
        current = current.parent
    # Fallback to cwd
    return Path.cwd()


def load_index(ctn_dir: Path):
    """Load .ctn/index.json and return current index metadata."""
    index_path = ctn_dir / "index.json"
    if not index_path.exists():
        print(f"ERROR: {index_path} not found. Run 'batho index' first.")
        sys.exit(1)

    with open(index_path) as f:
        index = json.load(f)

    return index


def normalize_path(file_path: str, root: str) -> str:
    """Normalize absolute path to workspace-relative path."""
    if file_path.startswith(root):
        rel = file_path[len(root):]
        if rel.startswith("/"):
            rel = rel[1:]
        return rel
    return file_path


def extract_graph(ctn_dir: Path, index_id: str, index_meta: dict, root: str):
    """Extract and transform graph data."""
    snapshot_dir = ctn_dir / index_id
    graph_path = snapshot_dir / "graph.json"

    if not graph_path.exists():
        print(f"ERROR: {graph_path} not found.")
        sys.exit(1)

    print(f"Loading graph from {graph_path}...")
    with open(graph_path) as f:
        graph = json.load(f)

    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])

    print(f"  Raw: {len(entities)} entities, {len(relationships)} relationships")

    # Filter to code-relevant entities
    code_entities = [e for e in entities if e["type"] in CODE_ENTITY_TYPES]
    code_entity_ids = {e["id"] for e in code_entities}

    print(f"  Filtered: {len(code_entities)} code entities")

    # Build nodes
    nodes = []
    for e in code_entities:
        node = {
            "id": e["id"],
            "name": e["name"],
            "type": e["type"],
            "file": normalize_path(e["file"], root),
            "lineRange": [e.get("start_line", 0), e.get("end_line", 0)],
            "color": TYPE_COLORS.get(e["type"], "#8b98ab"),
        }
        if e.get("signature"):
            node["signature"] = e["signature"]
        if e.get("parent_id"):
            node["parentId"] = e["parent_id"]
        nodes.append(node)

    # Filter relationships where both source and target are code entities
    # For CONTAINS, keep even if target is outside (shows structure)
    edges = []
    for r in relationships:
        if r["type"] not in CODE_RELATIONSHIP_TYPES:
            continue
        # Both endpoints must be in our filtered set
        if r["source_id"] in code_entity_ids and r["target_id"] in code_entity_ids:
            edges.append({
                "id": r["id"],
                "source": r["source_id"],
                "target": r["target_id"],
                "type": r["type"],
                "color": EDGE_COLORS.get(r["type"], "#8b98ab"),
            })

    print(f"  Filtered: {len(edges)} edges")

    # Compute degree metrics
    in_degree = Counter()
    out_degree = Counter()
    for e in edges:
        out_degree[e["source"]] += 1
        in_degree[e["target"]] += 1

    for node in nodes:
        node["inDegree"] = in_degree.get(node["id"], 0)
        node["outDegree"] = out_degree.get(node["id"], 0)
        node["degree"] = node["inDegree"] + node["outDegree"]

    # Build file tree
    files_map = defaultdict(list)
    for node in nodes:
        files_map[node["file"]].append({
            "id": node["id"],
            "name": node["name"],
            "type": node["type"],
        })

    files = []
    for path in sorted(files_map.keys()):
        files.append({
            "path": path,
            "entityCount": len(files_map[path]),
            "entities": files_map[path],
        })

    # Compute stats
    type_breakdown = dict(Counter(n["type"] for n in nodes).most_common())
    rel_breakdown = dict(Counter(e["type"] for e in edges).most_common())

    stats = {
        "totalNodes": len(nodes),
        "totalEdges": len(edges),
        "fileCount": len(files),
        "typeBreakdown": type_breakdown,
        "relationshipBreakdown": rel_breakdown,
    }

    # Metadata
    metadata = {
        "indexId": index_id,
        "timestamp": index_meta.get("timestamp", ""),
        "repoRoot": root,
        "entityCount": index_meta.get("entity_count", 0),
        "relationshipCount": index_meta.get("relationship_count", 0),
        "stalenessScore": index_meta.get("staleness_score", 0),
        "stack": index_meta.get("stack", {}),
    }

    # Type and edge color maps for frontend legend
    type_colors = {t: TYPE_COLORS[t] for t in type_breakdown.keys() if t in TYPE_COLORS}
    edge_colors = {t: EDGE_COLORS[t] for t in rel_breakdown.keys() if t in EDGE_COLORS}

    return {
        "nodes": nodes,
        "edges": edges,
        "files": files,
        "stats": stats,
        "metadata": metadata,
        "typeColors": type_colors,
        "edgeColors": edge_colors,
    }


def main():
    root = find_workspace_root()
    ctn_dir = root / ".ctn"

    index = load_index(ctn_dir)
    current_id = index.get("current_index_id")

    # Allow override via CLI
    if len(sys.argv) > 2 and sys.argv[1] == "--index-id":
        current_id = sys.argv[2]

    if not current_id:
        print("ERROR: No current_index_id found in index.json")
        sys.exit(1)

    index_meta = index.get("indexes", {}).get(current_id, {})
    repo_root = index_meta.get("root", str(root))

    print(f"Workspace root: {root}")
    print(f"Current index: {current_id}")

    data = extract_graph(ctn_dir, current_id, index_meta, repo_root)

    # Ensure output directory exists
    output_dir = root / "frontend" / "src" / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "graphData.json"

    with open(output_path, "w") as f:
        json.dump(data, f, separators=(",", ":"))

    size_kb = output_path.stat().st_size / 1024
    print(f"\nOutput: {output_path}")
    print(f"Size: {size_kb:.1f} KB")
    print(f"Nodes: {data['stats']['totalNodes']}")
    print(f"Edges: {data['stats']['totalEdges']}")
    print(f"Files: {data['stats']['fileCount']}")
    print(f"\nType breakdown: {data['stats']['typeBreakdown']}")
    print(f"Relationship breakdown: {data['stats']['relationshipBreakdown']}")


if __name__ == "__main__":
    main()
