"""Orchestrator for `batho plugins apply` — retro-enrichment without re-extraction.

Loads the built artifact's entity/relation graph, runs the effective BSG rule
set (or a subset) over it via `apply_rule_plugins`, and re-serializes only the
files whose entities/relationships changed back through the bundle writer —
using the same `Entity.to_dict(view=...)` serialization and patch-merge path
as `batho patch`. No files are re-parsed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from batho.core.config import set_active_root
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="orchestrator.plugins_apply")


@dataclass
class PluginsApplyOptions:
    root: Path
    plugin: Path | None = None
    plugins_only: bool = False
    dry_run: bool = False


@dataclass
class PluginsApplyResult:
    success: bool
    message: str = ""
    dry_run: bool = False
    run_uuid: str | None = None
    entities_updated: int = 0
    rules_applied: int = 0
    files_rewritten: int = 0
    rule_hits: dict[str, int] = field(default_factory=dict)
    interception_totals: dict[str, int] = field(default_factory=dict)
    semantic_edges_added: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _load_graph_from_artifact(
    db: Any,
    run_internal_id: int,
    root: Path,
    include_storage: bool = True,
) -> tuple[Any, dict[str, dict[str, Any]], dict[str, Any], dict[str, str]]:
    """Rebuild the in-memory graph + per-file bookkeeping from run artifacts.

    Returns (graph, file_views, tracking, eid_to_relfile) where file_views maps
    repo-relative path -> {"entities": [Entity], "rels": [dict]} and
    eid_to_relfile maps entity_id -> repo-relative file path.

    ``include_storage=False`` skips raw_content/raw_bytes — use it for
    read-only consumers (gap profile, score, fixture gate) to avoid
    materializing every file's contents.
    """
    from batho.core.schemas import Entity, Relationship
    from batho.modules.graph.builder.codegraph import InMemoryGraph

    artifacts = db.get_file_artifacts(run_internal_id, include_storage=include_storage)
    tracking = db.get_all_file_tracking()

    entities_by_id: dict[str, Entity] = {}
    file_views: dict[str, dict[str, Any]] = {}
    eid_to_relfile: dict[str, str] = {}
    all_rels: list[Relationship] = []

    for artifact in artifacts:
        file_path = artifact["file_path"]
        abs_fp = str((root / file_path).resolve())
        g = artifact.get("graph") or {}
        ents: list[Entity] = []
        for e in g.get("entities") or []:
            e["file"] = abs_fp
            if e.get("leading_whitespace") is None:
                e["leading_whitespace"] = ""
            if e.get("trailing_whitespace") is None:
                e["trailing_whitespace"] = ""
            try:
                ent = Entity.from_dict(e)
            except Exception:
                continue
            entities_by_id[ent.id] = ent
            eid_to_relfile[ent.id] = file_path
            ents.append(ent)

        file_rels: list[dict] = []
        for r in g.get("relationships") or []:
            file_rels.append(r)
            try:
                all_rels.append(Relationship.from_dict(r))
            except Exception:
                continue

        file_views[file_path] = {"entities": ents, "rels": file_rels}

    graph = InMemoryGraph(entities=entities_by_id, relationships=all_rels)
    return graph, file_views, tracking, eid_to_relfile


# Extraction-metadata keys persisted in agent_views alongside bsg.* —
# mirrors writer._AGENT_METADATA_EXTRA_KEYS. Rule matchers/when-clauses
# referencing any other non-bsg key silently miss post-roundtrip.
_PERSISTED_MATCHER_META_KEYS = frozenset(
    {"decorators", "docstring", "invocation_snippet"}
)

# Rule-owned metadata is re-derived wholesale on every apply; stripping it
# first keeps `plugins apply` subtractive — removing/renaming a rule removes
# its stamps. `bsg.index_id` is the extraction run nonce, not rule-owned.
_RULE_OWNED_META_KEEP = frozenset({"bsg.index_id"})


def _strip_rule_owned_state(graph: Any) -> None:
    """Remove rule-owned `bsg.*` metadata and apply-layer derived edges so
    re-application re-derives them from the current rule set (subtractive
    semantics — deleted rules stop emitting their outputs)."""
    for eid, ent in graph.entities.items():
        meta = ent.metadata or {}
        stale = {
            k for k in meta
            if str(k).startswith("bsg.") and k not in _RULE_OWNED_META_KEEP
        }
        if stale:
            kept = {k: v for k, v in meta.items() if k not in stale}
            graph.update_entity(eid, ent._evolve(metadata=kept))

    def _apply_derived(rel: Any) -> bool:
        meta = getattr(rel, "metadata", None) or {}
        if meta.get("source") == "tag_postpass":
            return True
        # semantic-overlay edges carry `semantic` with no contract markers
        # (no edge_class, no derived) — apply re-mints them each run.
        # Build-time derivations carry `derived: True` (codegraph hierarchy/
        # doc-links) or the annotation contract (`edge_class`, extractor
        # rationale edges) — both are preserved.
        return (
            bool(meta.get("semantic"))
            and not meta.get("derived")
            and not meta.get("edge_class")
        )

    kept = [r for r in graph.relationships if not _apply_derived(r)]
    if len(kept) != len(graph.relationships):
        graph.update_relationships(kept)


def _unpersisted_metadata_keys(rules: list[Any]) -> dict[str, list[str]]:
    """Metadata keys the loaded rules read that agent_views does not
    persist — matching against the artifact projection silently diverges
    from a fresh build for these rules (ENR-05)."""
    out: dict[str, list[str]] = {}
    for rule in rules:
        keys: set[str] = set()
        match = getattr(rule, "match", None)
        if match is not None:
            for rm in getattr(match, "regex_patterns", ()) or ():
                if (
                    getattr(rm, "target", "") == "metadata"
                    and getattr(rm, "metadata_key", None)
                ):
                    keys.add(rm.metadata_key)
            for k, _v in getattr(match, "target_metadata_equals", ()) or ():
                keys.add(k)
            for cond in getattr(match, "metadata_conditions", ()) or ():
                keys.add(cond.key)
        when = getattr(getattr(rule, "actions", None), "when", None)
        if when is not None:
            for cond in (*getattr(when, "all_", ()), *getattr(when, "any_", ())):
                keys.add(cond.key)
        keys = {
            k for k in keys
            if not str(k).startswith("bsg.")
            and k not in _PERSISTED_MATCHER_META_KEYS
        }
        if keys:
            out[getattr(rule, "name", "?")] = sorted(keys)
    return out


def _rules_config_for_apply(cfg: dict[str, Any], options: PluginsApplyOptions) -> dict[str, Any]:
    """Effective rules config for apply — possibly narrowed to custom sources."""
    from batho.modules.compression.rules import effective_rules_config
    rules_cfg = dict(effective_rules_config(cfg))
    if options.plugins_only or options.plugin is not None:
        rules_cfg["auto_load_all_plugins"] = False
        rules_cfg["builtin_plugins"] = []
    if options.plugin is not None:
        plugin_path = options.plugin
        if not plugin_path.is_absolute():
            plugin_path = (options.root / plugin_path).resolve()
        rules_cfg["custom_rules_path"] = str(plugin_path)
        rules_cfg["custom_rules_dir"] = ""
        rules_cfg["custom_rules_inline"] = []
    return rules_cfg


def run_plugins_apply(options: PluginsApplyOptions) -> PluginsApplyResult:
    """Apply effective rules to the artifact graph and rewrite touched blobs."""
    root = options.root.resolve()
    if not root.exists() or not root.is_dir():
        return PluginsApplyResult(
            success=False, message=f"Repository root does not exist: {root}"
        )
    set_active_root(root)

    from batho.core.config.loader import get_config_cached
    from batho.modules.compression.rules import (
        apply_rule_plugins,
        build_rule_telemetry,
        load_effective_rules,
    )
    from batho.modules.graph.incremental import (
        get_current_branch,
        get_head_commit,
        is_git_repo,
    )
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle

    cfg = get_config_cached()
    # ENR-09: guard before BathoBundle construction — it eagerly mkdirs
    # .batho/artifact/; `plugins apply` on a bare checkout shouldn't create it.
    if not resolve_bundle_dir(root).exists():
        return PluginsApplyResult(
            success=False,
            message="No artifact run found — run `batho build` first.",
        )
    db = BathoBundle(root)
    run_uuid = db.get_latest_run_id()
    if run_uuid is None:
        return PluginsApplyResult(
            success=False,
            message="No artifact run found — run `batho build` first.",
        )
    run_internal_id = db.get_run_internal_id(run_uuid)
    if run_internal_id is None:
        return PluginsApplyResult(
            success=False, message=f"Could not resolve run id for run {run_uuid}."
        )

    base_run_internal_id = run_internal_id
    graph, file_views, tracking, eid_to_relfile = _load_graph_from_artifact(
        db, run_internal_id, root
    )
    if not graph.entities:
        return PluginsApplyResult(
            success=False, message="Artifact contains no entities."
        )

    rules_cfg = _rules_config_for_apply(cfg, options)
    if not rules_cfg.get("enabled", False):
        return PluginsApplyResult(
            success=False,
            message="rules.enabled is false — nothing to apply.",
        )

    # Snapshot ORIGINAL artifact state first — the strip below mutates the
    # graph, and the delta must compare post-apply output against what the
    # artifact actually contains (otherwise a removed rule's stale keys
    # would be stripped in memory but never rewritten to disk).
    before_state: dict[str, tuple] = {
        eid: (ent.name, ent.type, dict(ent.metadata or {}))
        for eid, ent in graph.entities.items()
    }
    before_rel_ids = {r.id for r in graph.relationships}
    before_rels_by_id = {r.id: r for r in graph.relationships}

    # Subtractive re-apply: strip rule-owned `bsg.*` writes and apply-layer
    # derived edges before re-matching so removed/renamed rules stop leaving
    # stale outputs in the artifact (ENR-04). Build-derived edges (marked
    # `derived: True`) and the `bsg.index_id` run nonce are preserved.
    _strip_rule_owned_state(graph)

    rules, load_stats = load_effective_rules(rules_cfg, root)

    # ENR-05: agent_views persists bsg.* plus the fixed extraction keys —
    # rules matching other metadata keys silently diverge from a fresh
    # build. Surface it instead of silently missing.
    unpersisted = _unpersisted_metadata_keys(rules)
    apply_warnings: list[str] = []
    if unpersisted:
        msg = (
            "rules read metadata keys not persisted in agent_views "
            f"({unpersisted}); matches may differ from `batho build` — "
            "re-extract to apply them reliably"
        )
        LOGGER.warning("plugins_apply_metadata_projection", rules=unpersisted)
        apply_warnings.append(msg)
    stats = apply_rule_plugins(
        graph=graph,
        root_path=root,
        rules_config=rules_cfg,
        profile=True,
    )
    if not stats.get("enabled", False):
        return PluginsApplyResult(
            success=False,
            message="Rules disabled or failed to load — nothing applied.",
        )

    changed_eids = [
        eid
        for eid, ent in graph.entities.items()
        if (ent.name, ent.type, dict(ent.metadata or {})) != before_state.get(eid)
    ]
    changed_files = {
        eid_to_relfile[eid] for eid in changed_eids if eid in eid_to_relfile
    }
    # Newly-added edges mark the source file dirty; apply-layer edges
    # REMOVED by the strip (stale rule outputs) dirty the source file too.
    after_rel_ids = {r.id for r in graph.relationships}
    for rel in graph.relationships:
        if rel.id not in before_rel_ids:
            src_file = eid_to_relfile.get(rel.source_id)
            if src_file:
                changed_files.add(src_file)
    for rid, rel in before_rels_by_id.items():
        if rid not in after_rel_ids:
            src_file = eid_to_relfile.get(rel.source_id)
            if src_file:
                changed_files.add(src_file)

    result = PluginsApplyResult(
        success=True,
        dry_run=options.dry_run,
        entities_updated=len(changed_eids),
        rules_applied=int(stats.get("rules_applied", 0)),
        files_rewritten=len(changed_files),
        rule_hits=dict(stats.get("rule_hits", {}) or {}),
        interception_totals=dict(stats.get("interception_totals", {}) or {}),
        semantic_edges_added=int(stats.get("semantic_edges_added", 0) or 0),
        warnings=apply_warnings,
    )

    if options.dry_run:
        result.message = "dry-run — no blobs written"
        return result

    # --- rule-stats.v1 payload (T05 contract) ---
    per_rule = build_rule_telemetry(graph.entities.values(), rules)
    rule_perf = (stats.get("rule_perf") or {}).get("rules", {}) or {}
    rule_stats_payload = {
        "schema_version": "rule-stats.v1",
        "run_kind": "plugins_apply",
        "rules_fingerprint": stats.get("rules_fingerprint", ""),
        "rules_loaded": int(stats.get("rules_loaded", 0) or 0),
        "rules_loaded_names": sorted(r.name for r in rules),
        "entities_updated": len(changed_eids),
        "rule_hits": dict(stats.get("rule_hits", {}) or {}),
        "plugin_hits": dict(stats.get("plugin_hits", {}) or {}),
        "rule_perf": rule_perf,
        "interception_totals": dict(stats.get("interception_totals", {}) or {}),
        "plugin_files": dict(load_stats.get("plugin_files") or {}),
        "per_rule": per_rule,
    }

    def _finalize_apply_run(
        new_run_uuid: str,
        new_internal_id: int,
        file_count: int = 0,
        entity_count: int = 0,
    ) -> None:
        """Complete an apply run: rule_stats + security_audit + enrich
        artifacts, then refresh `.batho/report/` so humans and the skill see
        post-apply graph state (not the stale pre-apply build view)."""
        from batho.modules.enrich import (
            collect_enrich_artifacts,
            write_enrich_reports,
        )

        _enrich = collect_enrich_artifacts(
            db,
            new_internal_id,
            new_run_uuid,
            root,
            rule_stats_payload=rule_stats_payload,
            entity_count=entity_count or len(graph.entities),
            # ENR-10: `graph` is already the post-apply in-memory view —
            # re-loading it inside collect_enrich_artifacts would decode the
            # whole artifact a second time.
            preloaded=(graph, file_views, tracking, eid_to_relfile),
        )
        base_overview = (
            (db.get_run_artifacts(base_run_internal_id) or {}).get(
                "context_overview"
            )
            or None
        )
        db.finalize_run_artifacts(
            new_internal_id,
            artifacts={
                "rule_stats": rule_stats_payload,
                "security_audit": stats.get("security_audit"),
                **_enrich,
            },
            blob_config=cfg.get("artifact_blobs", {}),
        )
        write_enrich_reports(
            root,
            profile=_enrich.get("enrich_profile"),
            score=_enrich.get("enrich_score"),
            context_overview=base_overview,
        )

    # --- Write back only touched files, through the patch-merge path ---
    if not changed_files:
        new_run_uuid = f"plugins_apply_{uuid.uuid4().hex[:12]}"
        git_commit = git_branch = None
        if is_git_repo(root):
            git_commit = get_head_commit(root)
            git_branch = get_current_branch(root)
        new_internal_id = db.create_run(
            new_run_uuid, root_path=str(root),
            git_commit=git_commit, git_branch=git_branch,
        )
        db.complete_run(new_run_uuid, is_patch=True, file_count=0)
        _finalize_apply_run(
            new_run_uuid, new_internal_id, entity_count=len(graph.entities)
        )
        result.run_uuid = new_run_uuid
        result.message = "no entities changed — artifact already enriched"
        return result

    new_run_uuid = f"plugins_apply_{uuid.uuid4().hex[:12]}"
    git_commit = git_branch = None
    if is_git_repo(root):
        git_commit = get_head_commit(root)
        git_branch = get_current_branch(root)
    new_internal_id = db.create_run(
        new_run_uuid, root_path=str(root),
        git_commit=git_commit, git_branch=git_branch,
    )
    writer = db._writers[new_internal_id]

    # Mark touched files as belonging to this run — the patch-merge replaces
    # base view rows only for files whose tracking.last_run_uuid == run_uuid.
    db.upsert_file_tracking([
        {**(tracking.get(rel_path) or {}),
         "file_path": rel_path,
         # upsert maps `last_run_id` -> the stored `last_run_uuid` column
         "last_run_id": new_run_uuid}
        for rel_path in sorted(changed_files)
        if (tracking.get(rel_path) or {}).get("file_id") is not None
    ])

    files_written = 0
    for rel_path in sorted(changed_files):
        tr = tracking.get(rel_path) or {}
        file_id = tr.get("file_id")
        if file_id is None:
            LOGGER.warning("plugins_apply_missing_file_id", file=rel_path)
            continue
        view = file_views.get(rel_path) or {}
        file_ents = [
            graph.entities[e.id] for e in view.get("entities", [])
            if e.id in graph.entities
        ]
        if not file_ents:
            continue
        file_eids = {e.id for e in file_ents}
        rels_out = [
            r.to_dict() for r in graph.relationships
            if r.source_id in file_eids
        ]
        writer.write_file_artifact(
            file_id,
            agent={"entities": [e.to_dict(view="agent") for e in file_ents]},
            storage={"entities": [e.to_dict(view="storage") for e in file_ents]},
            rels=rels_out,
            content_hash=tr.get("content_hash", ""),
        )
        files_written += 1

    db.complete_run(
        new_run_uuid,
        is_patch=True,
        entity_count=len(graph.entities),
        file_count=files_written,
    )
    _finalize_apply_run(
        new_run_uuid,
        new_internal_id,
        file_count=files_written,
        entity_count=len(graph.entities),
    )
    result.run_uuid = new_run_uuid
    result.files_rewritten = files_written
    result.message = f"enriched {files_written} file(s), {len(changed_eids)} entit(y/ies)"
    return result
