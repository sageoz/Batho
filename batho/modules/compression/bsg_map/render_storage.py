"""
batho/context/bsg_map/render_storage.py — Storage (JSON/Dict) rendering.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from pathlib import Path

from batho.core.config import SCHEMA_VERSIONS
from batho.core.schemas import EntityType, BSGViewType, build_relationship_id
from .relativizer import PathRelativizer

BSG_SCHEMA_VERSION = SCHEMA_VERSIONS["bsg"]

if TYPE_CHECKING:
    from . import BSGMap


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _sorted_index(index: dict[str, list[str]]) -> dict[str, list[str]]:
    """Sort the lists inside an index for determinism."""
    return {key: sorted(value) for key, value in sorted(index.items())}


def _build_render_components(
    bsg: BSGMap,
    build_ms: int | None = None,
    default_index_id: str | None = None,
    default_service_tag: str | None = None,
) -> dict[str, Any]:
    """Build reusable render components for JSON outputs."""
    resolved_default_index = (default_index_id or "").strip() or None
    resolved_default_service = (
        (default_service_tag or "").strip()
        if default_service_tag is not None
        else ""
    )
    if not resolved_default_service:
        resolved_default_service = Path(bsg._root).name or "root"
    resolved_build_ms = max(0, int(build_ms or 0))

    nodes: list[dict[str, Any]] = []
    node_by_id: dict[str, dict[str, Any]] = {}
    rule_names: set[str] = set()
    quality_warnings: list[str] = []
    autofilled_index_ids = 0
    missing_index_ids = 0
    autofilled_service_tags = 0
    missing_service_tags = 0
    normalized_categories = 0

    if resolved_build_ms == 0:
        quality_warnings.append(
            "build_ms is 0; verify build timing capture for this run"
        )

    for file_path in sorted(bsg._by_file.keys()):
        entities = bsg._by_file[file_path]
        for entity in sorted(entities, key=lambda item: (item.start_line, item.id)):
            metadata = dict(entity.metadata or {})
            scope_tier = str(
                metadata.get("bsg.scope_tier") or bsg._derive_scope_tier(entity)
            )
            raw_category = str(
                metadata.get("bsg.category") or bsg._derive_category(file_path)
            )
            category = bsg._normalize_category(raw_category)
            if raw_category.strip().upper() != category:
                normalized_categories += 1

            raw_service_tag = metadata.get("bsg.service_tag")
            service_tag = str(raw_service_tag or "").strip()
            if not service_tag:
                service_tag = str(
                    bsg._derive_service_tag(file_path) or resolved_default_service
                ).strip()
                if service_tag:
                    autofilled_service_tags += 1
            if not service_tag:
                missing_service_tags += 1

            language = bsg._derive_language(entity, file_path)
            raw_index_id = metadata.get("bsg.index_id")
            index_id_text = (
                str(raw_index_id).strip() if raw_index_id is not None else ""
            )
            if not index_id_text and resolved_default_index:
                index_id_text = resolved_default_index
                autofilled_index_ids += 1
            if not index_id_text:
                missing_index_ids += 1
            index_id = index_id_text or None

            rules = metadata.get("bsg.rules")
            if isinstance(rules, list):
                for rule_name in rules:
                    if isinstance(rule_name, str) and rule_name.strip():
                        rule_names.add(rule_name.strip())

            node = {
                "id": entity.id,
                "type": entity.type.name,
                "name": entity.name,
                "file": file_path,
                "start_line": entity.start_line,
                "end_line": entity.end_line,
                "signature": entity.signature,
                "language": language,
                "scope_tier": scope_tier,
                "category": category,
                "service_tag": service_tag,
                "dependency_weight": 0,
                "index_id": index_id,
                "metadata": metadata,
            }
            nodes.append(node)
            node_by_id[node["id"]] = node

    edges: list[dict[str, Any]] = []
    edge_key_seen: set[tuple[str, str, str]] = set()
    inbound_edge_map: dict[str, list[str]] = defaultdict(list)
    outbound_edge_map: dict[str, list[str]] = defaultdict(list)
    cross_boundaries: list[dict[str, Any]] = []

    def _add_edge(
        source_id: str,
        target_id: str,
        edge_type: str,
        metadata: dict[str, Any] | None = None,
        derived_from: str | None = None,
        *,
        roles: int | None = None,
        reference_start_byte: int | None = None,
        reference_end_byte: int | None = None,
        definition_start_byte: int | None = None,
        definition_end_byte: int | None = None,
    ) -> dict[str, Any] | None:
        if source_id not in node_by_id or target_id not in node_by_id:
            return None

        edge_key = (
            source_id,
            target_id,
            edge_type,
            reference_start_byte,
            reference_end_byte,
            definition_start_byte,
            definition_end_byte,
        )
        if edge_key in edge_key_seen:
            return None
        edge_key_seen.add(edge_key)

        edge_metadata = dict(metadata or {})
        if derived_from:
            edge_metadata.setdefault("derived_from", derived_from)

        edge_id = build_relationship_id(
            source_id,
            target_id,
            edge_type,
            reference_start_byte=reference_start_byte,
            reference_end_byte=reference_end_byte,
            definition_start_byte=definition_start_byte,
            definition_end_byte=definition_end_byte,
            line_number=edge_metadata.get("line_number") if edge_metadata else None,
            roles=roles,
        )
        edge = {
            "id": edge_id,
            "source_id": source_id,
            "target_id": target_id,
            "type": edge_type,
            "metadata": edge_metadata,
        }
        if roles is not None:
            edge["roles"] = roles
        if reference_start_byte is not None:
            edge["reference_start_byte"] = reference_start_byte
        if reference_end_byte is not None:
            edge["reference_end_byte"] = reference_end_byte
        if definition_start_byte is not None:
            edge["definition_start_byte"] = definition_start_byte
        if definition_end_byte is not None:
            edge["definition_end_byte"] = definition_end_byte
        edges.append(edge)
        outbound_edge_map[source_id].append(edge_id)
        inbound_edge_map[target_id].append(edge_id)
        return edge

    relationships = sorted(
        bsg._relationships,
        key=lambda rel: (
            str(getattr(rel, "source_id", "")),
            str(getattr(rel, "target_id", "")),
            str(
                getattr(
                    getattr(rel, "type", None), "name", getattr(rel, "type", "")
                )
            ),
        ),
    )

    for rel in relationships:
        source_id = str(getattr(rel, "source_id", ""))
        target_id = str(getattr(rel, "target_id", ""))
        rel_type_value = getattr(rel, "type", "")
        rel_type = (
            rel_type_value.name
            if hasattr(rel_type_value, "name")
            else str(rel_type_value)
        )
        rel_metadata = dict(getattr(rel, "metadata", {}) or {})
        rel_roles = getattr(rel, "roles", None)
        rel_ref_start = getattr(rel, "reference_start_byte", None)
        rel_ref_end = getattr(rel, "reference_end_byte", None)
        rel_def_start = getattr(rel, "definition_start_byte", None)
        rel_def_end = getattr(rel, "definition_end_byte", None)

        if not source_id or not target_id or not rel_type:
            continue

        edge = _add_edge(
            source_id,
            target_id,
            rel_type,
            rel_metadata,
            roles=int(rel_roles) if rel_roles is not None else None,
            reference_start_byte=rel_ref_start,
            reference_end_byte=rel_ref_end,
            definition_start_byte=rel_def_start,
            definition_end_byte=rel_def_end,
        )
        if edge is None:
            continue

        if rel_type == "CALLS":
            _add_edge(
                target_id,
                source_id,
                "CALLED_BY",
                {"derived": True},
                derived_from=edge["id"],
            )
        elif rel_type == "IMPORTS":
            _add_edge(
                target_id,
                source_id,
                "IMPORTED_BY",
                {"derived": True},
                derived_from=edge["id"],
            )

    for edge in list(edges):
        if edge["type"] == "STACK_BOUNDARY":
            continue

        source_node = node_by_id[edge["source_id"]]
        target_node = node_by_id[edge["target_id"]]
        source_service = str(source_node.get("service_tag") or "")
        target_service = str(target_node.get("service_tag") or "")

        if source_service and target_service and source_service != target_service:
            boundary_edge = _add_edge(
                edge["source_id"],
                edge["target_id"],
                "STACK_BOUNDARY",
                {
                    "source_service": source_service,
                    "target_service": target_service,
                    "derived": True,
                },
                derived_from=edge["id"],
            )
            if boundary_edge is not None:
                cross_boundaries.append(
                    {
                        "edge_id": boundary_edge["id"],
                        "source_id": boundary_edge["source_id"],
                        "target_id": boundary_edge["target_id"],
                        "source_service": source_service,
                        "target_service": target_service,
                    }
                )

    for node in nodes:
        node_id = node["id"]
        node["dependency_weight"] = len(inbound_edge_map.get(node_id, [])) + len(
            outbound_edge_map.get(node_id, [])
        )

    nodes_by_file: dict[str, list[str]] = defaultdict(list)
    nodes_by_type: dict[str, list[str]] = defaultdict(list)
    nodes_by_scope: dict[str, list[str]] = defaultdict(list)
    nodes_by_category: dict[str, list[str]] = defaultdict(list)
    nodes_by_service: dict[str, list[str]] = defaultdict(list)

    for node in nodes:
        node_id = node["id"]
        nodes_by_file[node["file"]].append(node_id)
        nodes_by_type[node["type"]].append(node_id)
        nodes_by_scope[node["scope_tier"]].append(node_id)
        nodes_by_category[node["category"]].append(node_id)
        service_key = node["service_tag"] or "UNASSIGNED"
        nodes_by_service[service_key].append(node_id)

    sorted_outbound_edges = {
        key: sorted(value) for key, value in sorted(outbound_edge_map.items())
    }
    sorted_inbound_edges = {
        key: sorted(value) for key, value in sorted(inbound_edge_map.items())
    }

    edges.sort(
        key=lambda edge: (edge["type"], edge["source_id"], edge["target_id"])
    )
    nodes.sort(key=lambda node: node["id"])
    cross_boundaries.sort(key=lambda item: item["edge_id"])

    files_ranked = sorted(
        (
            (file_path, len(node_ids))
            for file_path, node_ids in nodes_by_file.items()
        ),
        key=lambda item: (-item[1], item[0]),
    )
    rules_applied = sum(
        1
        for node in nodes
        if isinstance(node.get("metadata", {}).get("bsg.rules"), list)
        and len(node.get("metadata", {}).get("bsg.rules", [])) > 0
    )

    if autofilled_index_ids:
        quality_warnings.append(
            "auto-filled index_id for "
            f"{autofilled_index_ids} nodes from default_index_id"
        )
    if missing_index_ids:
        quality_warnings.append(
            f"{missing_index_ids} nodes missing index_id after fallback"
        )
    if autofilled_service_tags:
        quality_warnings.append(
            f"auto-derived service_tag for {autofilled_service_tags} nodes"
        )
    if missing_service_tags:
        quality_warnings.append(
            f"{missing_service_tags} nodes missing service_tag after fallback"
        )
    if normalized_categories:
        quality_warnings.append(
            "normalized bsg.category values for "
            f"{normalized_categories} nodes (e.g. DOCS -> DOC)"
        )

    stats_payload = {
        "total_files": len(nodes_by_file),
        "total_entities": len(nodes),
        "total_relationships": len(edges),
        "build_ms": resolved_build_ms,
        "rules_loaded": len(rule_names),
        "rules_applied": rules_applied,
        "quality_warnings": len(quality_warnings),
        "autofilled_index_ids": autofilled_index_ids,
        "missing_index_ids": missing_index_ids,
        "autofilled_service_tags": autofilled_service_tags,
        "missing_service_tags": missing_service_tags,
        "category_normalizations": normalized_categories,
    }

    indexes_payload = {
        "nodes_by_file": _sorted_index(nodes_by_file),
        "nodes_by_type": _sorted_index(nodes_by_type),
        "nodes_by_scope": _sorted_index(nodes_by_scope),
        "nodes_by_category": _sorted_index(nodes_by_category),
        "nodes_by_service": _sorted_index(nodes_by_service),
        "inbound_edges": sorted_inbound_edges,
        "outbound_edges": sorted_outbound_edges,
        "cross_boundaries": cross_boundaries,
    }
    views_payload = {
        "agent": {
            "top_files_by_node_count": [
                {"file": file_path, "count": count}
                for file_path, count in files_ranked[:25]
            ],
            "cross_boundary_count": len(cross_boundaries),
        },
        "human": {
            "categories": {
                key: len(value) for key, value in sorted(nodes_by_category.items())
            },
            "services": {
                key: len(value) for key, value in sorted(nodes_by_service.items())
            },
        },
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats_payload,
        "nodes": nodes,
        "edges": edges,
        "quality_warnings": quality_warnings,
        "indexes": indexes_payload,
        "views": views_payload,
    }


def render_json(
    bsg: BSGMap,
    build_ms: int | None = None,
    default_index_id: str | None = None,
    default_service_tag: str | None = None,
) -> dict[str, Any]:
    """
    Render the structural graph as a bsg.v1 dictionary.
    """
    # Check serialization config to determine method
    method = bsg._serialization_config.get("method", "streaming")
    _rel = PathRelativizer(bsg._root)
    opaque_files_data = [
        {
            "file_path": _rel(snap.file_path),
            "file_hash": snap.file_hash,
            "file_size": snap.file_size,
            "encoding": snap.encoding,
        }
        for snap in sorted(bsg._opaque_snapshots.values(), key=lambda s: s.file_path)
    ]

    if method == "streaming":
        components = _build_render_components(
            bsg=bsg,
            build_ms=build_ms,
            default_index_id=default_index_id,
            default_service_tag=default_service_tag,
        )
        return {
            "schema_version": BSG_SCHEMA_VERSION,
            "generated_at": components["generated_at"],
            "root": bsg._root,
            "stats": components["stats"],
            "nodes": components["nodes"],
            "edges": components["edges"],
            "quality_warnings": components["quality_warnings"],
            "indexes": components["indexes"],
            "views": components["views"],
            "opaque_files": opaque_files_data,
        }

    # Legacy mode - use original implementation
    import copy
    if (
        bsg._serialized_bsg is not None
        and build_ms is None
        and default_index_id is None
        and default_service_tag is None
    ):
        res = copy.deepcopy(bsg._serialized_bsg)
        res["opaque_files"] = opaque_files_data
        return res

    # Full rebuild if needed (legacy path)
    components = _build_render_components(
        bsg=bsg,
        build_ms=build_ms,
        default_index_id=default_index_id,
        default_service_tag=default_service_tag,
    )

    return {
        "schema_version": BSG_SCHEMA_VERSION,
        "generated_at": components["generated_at"],
        "root": bsg._root,
        "stats": components["stats"],
        "nodes": components["nodes"],
        "edges": components["edges"],
        "quality_warnings": components["quality_warnings"],
        "indexes": components["indexes"],
        "views": components["views"],
        "opaque_files": opaque_files_data,
    }



def render_overview_json(
    bsg: BSGMap,
    repo_name: str | None = None,
    timestamp: str | None = None,
    stack_info: dict[str, list[str]] | None = None,
    evolution_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Render a high-level summary of the codebase for dashboard overview.
    """
    components = _build_render_components(bsg=bsg)
    
    # 1. Summary totals
    total_rels = components["stats"]["total_relationships"]
    if total_rels == 0 and bsg._dependencies:
        total_rels = sum(len(deps) for deps in bsg._dependencies.values())
        
    summary = {
        "total_files": components["stats"]["total_files"],
        "total_entities": components["stats"]["total_entities"],
        "total_relationships": total_rels,
    }
    
    # 2. File distribution by category
    cat_counts = defaultdict(lambda: {"files": 0, "entities": 0})
    for node in components["nodes"]:
        cat = node["category"]
        # Map internal categories to human-readable ones for the UI
        display_cat = {
            "SOURCE": "Source",
            "DOC": "Docs",
            "CONFIG": "Config",
            "TEST": "Tests",
            "INFRA": "Infrastructure",
        }.get(cat, cat.capitalize())
        
        cat_counts[display_cat]["entities"] += 1
        
    # Count files per category
    file_cats = {}
    for file_path, entities in bsg._by_file.items():
        if entities:
            # Simple heuristic: use category of first entity
            cat = bsg._derive_category(file_path)
            display_cat = {
                "SOURCE": "Source",
                "DOC": "Docs",
                "CONFIG": "Config",
                "TEST": "Tests",
                "INFRA": "Infrastructure",
            }.get(cat, cat.capitalize())
            file_cats[file_path] = display_cat
            cat_counts[display_cat]["files"] += 1
            
    file_distribution = [
        {"category": cat, "files": data["files"], "entities": data["entities"]}
        for cat, data in sorted(cat_counts.items())
    ]
    
    # 3. Language breakdown
    lang_counts = defaultdict(lambda: {"files": 0, "entities": 0})
    for node in components["nodes"]:
        lang = node["language"]
        display_lang = lang.capitalize() if lang != "unknown" else "Unknown"
        lang_counts[display_lang]["entities"] += 1
        
    file_langs = defaultdict(set)
    for node in components["nodes"]:
        lang = node["language"]
        display_lang = lang.capitalize() if lang != "unknown" else "Unknown"
        file_langs[display_lang].add(node["file"])
        
    language_breakdown = []
    for lang, files in lang_counts.items():
        language_breakdown.append({
            "language": lang,
            "files": len(file_langs[lang]),
            "entities": files["entities"]
        })
    language_breakdown.sort(key=lambda x: x["entities"], reverse=True)
    
    primary_language = language_breakdown[0]["language"] if language_breakdown else "Unknown"
    
    # 4. Technology stack
    technology_stack = {
        "languages": [],
        "frameworks": [],
        "package_managers": [],
        "build_tools": [],
        "infra": [],
        "other": [],
    }
    if stack_info:
        technology_stack.update(stack_info)
        
    # 5. Directory structure (tree)
    def build_tree(paths: list[str]) -> dict[str, Any]:
        tree = {"name": "root", "type": "directory", "children": []}
        for path in sorted(paths):
            parts = path.split("/")
            current = tree
            for i, part in enumerate(parts):
                is_file = (i == len(parts) - 1)
                found = None
                for child in current["children"]:
                    if child["name"] == part:
                        found = child
                        break
                if not found:
                    new_node = {
                        "name": part,
                        "type": "file" if is_file else "directory",
                    }
                    if not is_file:
                        new_node["children"] = []
                        # Add label for directories
                        dir_path = "/".join(parts[:i+1])
                        label = bsg._get_directory_label(dir_path)
                        if label:
                            new_node["label"] = label
                    current["children"].append(new_node)
                    found = new_node
                current = found
        return tree
    
    directory_structure = build_tree(list(bsg._by_file.keys()))
    
    # 6. Entity statistics
    type_counts = Counter(node["type"].lower() for node in components["nodes"])
    entity_statistics = [
        {"type": t, "count": c} for t, c in sorted(type_counts.items())
    ]
    
    # 7. Top dependencies
    # Collect all dependencies across all files
    all_deps = Counter()
    for deps in bsg._dependencies.values():
        for dep in deps:
            all_deps[dep] += 1
            
    top_dependencies = [
        {"dependency": dep, "references": count}
        for dep, count in all_deps.most_common()
    ]
    
    # 8. Evolution rules
    payload = {
        "schema_version": "context-overview.v1",
        "repo": repo_name or Path(bsg._root).name or "unknown",
        "generated_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "file_distribution": file_distribution,
        "language_breakdown": language_breakdown,
        "primary_language": primary_language,
        "technology_stack": technology_stack,
        "directory_structure": directory_structure,
        "entity_statistics": entity_statistics,
        "top_dependencies": top_dependencies,
    }
    
    if evolution_rules:
        filtered_rules = []
        for r in evolution_rules:
            if r.get("dont_rule") and r.get("source"):
                filtered_rules.append({
                    "rule": r["dont_rule"],
                    "source": r["source"],
                    "timestamp": r.get("timestamp")
                })
        if filtered_rules:
            payload["evolution_rules"] = filtered_rules
            
    return payload


def render_files_json(
    bsg: BSGMap,
    repo_name: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """
    Render detailed file-level statistics and dependencies for dashboard navigation.
    """
    components = _build_render_components(bsg=bsg)
    
    # Group nodes by file
    file_nodes = defaultdict(list)
    for node in components["nodes"]:
        file_nodes[node["file"]].append(node)
        
    # Categorize by human-readable names
    categories_map = defaultdict(lambda: {"files": []})
    
    for file_path in sorted(file_nodes.keys()):
        nodes = file_nodes[file_path]
        cat = bsg._derive_category(file_path)
        display_cat = {
            "SOURCE": "Source",
            "DOC": "Docs",
            "CONFIG": "Config",
            "TEST": "Tests",
            "INFRA": "Infrastructure",
        }.get(cat, cat.capitalize())
        
        # Build file entry
        # breakdown of entity types
        type_counts = Counter(n["type"].lower() for n in nodes)
        
        file_entry = {
            "name": Path(file_path).name,
            "path": file_path,
            "entities": nodes,
            "entity_summary": {
                "total": len(nodes),
                "breakdown": dict(type_counts)
            }
        }
        
        # Add dependencies only if it's a SOURCE file and has deps
        if cat == "SOURCE":
            deps = bsg._dependencies.get(file_path, [])
            if deps:
                file_entry["dependencies"] = deps
        
        categories_map[display_cat]["files"].append(file_entry)
        
    # Final categories payload
    categories_payload = []
    for cat_name, data in sorted(categories_map.items()):
        # Group files into directories for this category
        dirs_map = defaultdict(list)
        total_entities = 0
        for f in data["files"]:
            rel_path = f["path"]
            dir_path = str(Path(rel_path).parent)
            if dir_path == ".":
                dir_path = "(root)"
            dirs_map[dir_path].append(f)
            total_entities += f["entity_summary"]["total"]
            
        directories = []
        for d_path, d_files in sorted(dirs_map.items()):
            # Path should end with / as per tests
            path_fixed = d_path if d_path.endswith("/") else f"{d_path}/"
            directories.append({
                "path": path_fixed,
                "files": d_files
            })
            
        categories_payload.append({
            "name": cat_name,
            "file_count": len(data["files"]),
            "entity_count": total_entities,
            "directories": directories
        })
        
    return {
        "schema_version": "context-files.v1",
        "repo": repo_name or Path(bsg._root).name or "unknown",
        "generated_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_files": components["stats"]["total_files"],
            "total_entities": components["stats"]["total_entities"],
        },
        "categories": categories_payload
    }


def render_json_streaming(
    bsg: BSGMap,
    build_ms: int | None = None,
    default_index_id: str | None = None,
    default_service_tag: str | None = None,
    extra_fields: dict[str, Any] | None = None,
):
    """Yield JSON chunks without allocating a full top-level payload dict."""
    if (
        bsg._serialized_bsg is not None
        and build_ms is None
        and default_index_id is None
        and default_service_tag is None
        and not extra_fields
    ):
        encoder = json.JSONEncoder(ensure_ascii=False)
        for chunk in encoder.iterencode(bsg._serialized_bsg):
            yield chunk
        return

    components = _build_render_components(
        bsg=bsg,
        build_ms=build_ms,
        default_index_id=default_index_id,
        default_service_tag=default_service_tag,
    )

    base_items: list[tuple[str, Any]] = [
        ("schema_version", BSG_SCHEMA_VERSION),
        ("generated_at", components["generated_at"]),
        ("root", bsg._root),
        ("stats", components["stats"]),
        ("nodes", components["nodes"]),
        ("edges", components["edges"]),
        ("quality_warnings", components["quality_warnings"]),
        ("indexes", components["indexes"]),
        ("views", components["views"]),
        ("opaque_files", [
            {
                "file_path": PathRelativizer(bsg._root)(snap.file_path),
                "file_hash": snap.file_hash,
                "file_size": snap.file_size,
                "encoding": snap.encoding,
            }
            for snap in sorted(bsg._opaque_snapshots.values(), key=lambda s: s.file_path)
        ]),
    ]

    overrides: dict[str, Any] = {}
    additions: list[tuple[str, Any]] = []
    if extra_fields:
        base_keys = {key for key, _ in base_items}
        for key, value in extra_fields.items():
            if key in base_keys:
                overrides[key] = value
            else:
                additions.append((key, value))

    encoder = json.JSONEncoder(ensure_ascii=False)
    first = True
    yield "{"

    for key, value in base_items:
        resolved_value = overrides[key] if key in overrides else value
        if not first:
            yield ","
        first = False
        yield encoder.encode(key)
        yield ":"
        for chunk in encoder.iterencode(resolved_value):
            yield chunk

    for key, value in additions:
        if not first:
            yield ","
        first = False
        yield encoder.encode(key)
        yield ":"
        for chunk in encoder.iterencode(value):
            yield chunk

    yield "}"


def to_dict(bsg: BSGMap, *, view: str = "storage") -> dict[str, Any]:
    """
    Serialize the graph to a nested dictionary for JSON persistence.
    """
    # This matches the legacy to_dict behavior
    if view == "bsg":
        return bsg.render_json()

    # Storage view rendering logic
    nodes = []
    for file_path, entities in bsg._by_file.items():
        for entity in entities:
            nodes.append(entity.to_dict(view=view))

    edges = []
    for rel in bsg._relationships:
        if hasattr(rel, "to_dict"):
            edges.append(rel.to_dict())
        else:
            edges.append(dict(rel))

    return {
        "schema_version": BSG_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": bsg._root,
        "entities": nodes,
        "relationships": edges,
    }
