"""Enrichment gap profiler — `enrich_profile` run-artifact payload.

Reads the built artifact (no re-analysis) and emits a structured gap report
mapping observed deficiencies to rule shapes a generator can write
deterministically. Runs automatically at the end of `batho build`/`batho
patch` and is also rendered into `.batho/report/overview.md` (merged with
`context_overview` so one document serves humans and the skill).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

_NOISE_FILE_PATTERNS = (
    ".batho/", "graphify-out/", "node_modules/", "dist/", "build/",
    "vendor/", ".venv/", "venv/", "__pycache__/", ".tox/",
    "package-lock.json", "yarn.lock", "pipfile.lock", "poetry.lock",
    "cargo.lock", "go.sum", "gemfile.lock", ".tsbuildinfo",
)
_MANIFEST_NAMES = {
    "package.json": "npm/nodejs",
    "requirements.txt": "pip",
    "pyproject.toml": "python",
    "setup.py": "python-setuptools",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle-kotlin",
    "cargo.toml": "cargo",
    "go.mod": "go-modules",
    "gemfile": "bundler",
    "composer.json": "composer",
    "pubspec.yaml": "dart-pub",
    "dockerfile": "docker",
    "docker-compose.yml": "docker-compose",
    ".github/workflows/": "github-actions",
}
_RATIONALE_PREFIXES = ("WHY:", "NOTE:", "FIXME:", "TODO:", "HACK:", "XXX:")


def _is_noise_path(rel_path: str) -> bool:
    p = rel_path.lower().replace("\\", "/")
    if p.endswith((".lock", ".tsbuildinfo", ".min.js", ".map")):
        return True
    return any(marker in p for marker in _NOISE_FILE_PATTERNS)


def _pctiles(sorted_vals: list[int], pcts=(50, 95, 99)) -> dict[str, int]:
    out = {}
    n = len(sorted_vals)
    for p in pcts:
        idx = min(n - 1, int(n * p / 100)) if n else 0
        out[f"p{p}"] = sorted_vals[idx] if n else 0
    return out


def build_gap_report(
    db: Any,
    run_internal_id: int | None = None,
    run_uuid: str | None = None,
    root: Path | None = None,
    top_n: int = 15,
    sample_k: int = 8,
    preloaded: tuple | None = None,
) -> dict:
    """Assemble the gap report from a built artifact (db must be open on root).

    `run_internal_id`/`run_uuid` default to the latest run when omitted.
    ``preloaded`` optionally supplies ``(graph, file_views, tracking,
    eid_to_relfile)`` from :func:`plugins_apply._load_graph_from_artifact`
    so callers can share one graph load across reports.
    """
    from batho.orchestrator.plugins_apply import _load_graph_from_artifact

    if run_uuid is None:
        run_uuid = db.get_latest_run_id()
        if run_uuid is None:
            raise RuntimeError(
                "No artifact run found — run `batho build` first."
            )
    if run_internal_id is None:
        run_internal_id = db.get_run_internal_id(run_uuid)
    if root is None:
        root = Path(getattr(db, "repo_root", "."))

    if preloaded is not None:
        graph, file_views, tracking, eid_to_relfile = preloaded
    else:
        graph, file_views, tracking, eid_to_relfile = _load_graph_from_artifact(
            db, run_internal_id, root, include_storage=False
        )

    entities = list(graph.entities.values())
    total = len(entities)

    # --- entity-type distribution + ghost ratio ---
    def _is_stub(e) -> bool:
        if str(e.id).startswith("unresolved:"):
            return True
        md = getattr(e, "metadata", None) or {}
        return md.get("stub_resolution_state") == "pending"

    type_dist = Counter(str(getattr(e, "type", "?")).split(".")[-1] for e in entities)
    unresolved = [e for e in entities if _is_stub(e)]
    unresolved_names = Counter(e.name for e in unresolved)
    external = [e for e in entities if "external" in str(getattr(e, "type", "")).lower()]

    # --- noise-path entities ---
    noise_ents = [
        e for e in entities
        if _is_noise_path(eid_to_relfile.get(e.id, ""))
    ]
    noise_by_dir = Counter(
        eid_to_relfile[e.id].split("/")[0]
        for e in noise_ents
        if e.id in eid_to_relfile
    )

    # --- coverage stats ---
    def _meta(e, key):
        m = getattr(e, "metadata", None) or {}
        return m.get(key)

    categorized = sum(1 for e in entities if _meta(e, "bsg.category"))
    tagged_rules = sum(1 for e in entities if _meta(e, "bsg.rules"))
    domain_tagged = sum(1 for e in entities if _meta(e, "bsg.domain"))
    service_tagged = sum(1 for e in entities if _meta(e, "bsg.service_tag"))
    quarantined = sum(
        1 for e in entities
        if _meta(e, "bsg.noise") or _meta(e, "bsg.quarantined")
    )

    # vendor/generated-looking files categorized as SOURCE — count ALL
    # matches (magnitude matters); samples stay capped for readability.
    miscat_count = 0
    miscat_samples = []
    for e in entities:
        rel = eid_to_relfile.get(e.id, "")
        if _is_noise_path(rel) and str(_meta(e, "bsg.category") or "").upper() == "SOURCE":
            miscat_count += 1
            if len(miscat_samples) < sample_k:
                miscat_samples.append(e.id)

    # --- degree distribution (fan-in, including zero-inbound entities) ---
    inbound = Counter(r.target_id for r in graph.relationships)
    degrees = sorted(inbound.get(e.id, 0) for e in entities)
    degree_hist = {
        "max": degrees[-1] if degrees else 0,
        "mean": round(sum(degrees) / len(degrees), 2) if degrees else 0,
        **_pctiles(degrees),
    }
    top_inbound = [
        {"entity_id": eid, "inbound": c}
        for eid, c in inbound.most_common(top_n)
    ]

    # --- comment-block density + rationale patterns ---
    comment_ents = [
        e for e in entities
        if "comment" in str(getattr(e, "type", "")).lower()
    ]
    rationale = Counter()
    for e in comment_ents:
        name = str(getattr(e, "name", "") or "").upper()
        for prefix in _RATIONALE_PREFIXES:
            if name.startswith(prefix):
                rationale[prefix.rstrip(":")] += 1

    # --- manifest fingerprints ---
    tracked_paths = list(tracking.keys())
    manifests_found = {}
    for fp in tracked_paths:
        lp = fp.lower()
        base = lp.split("/")[-1]
        for marker, eco in _MANIFEST_NAMES.items():
            if marker.endswith("/"):
                # Directory marker (e.g. ".github/workflows/") — match any
                # file living under that directory, at any depth.
                if lp.startswith(marker) or f"/{marker}" in lp:
                    manifests_found[fp] = eco
            elif base == marker or lp.endswith(marker):
                manifests_found[fp] = eco

    top_level_dirs = sorted(
        {fp.split("/")[0] for fp in tracked_paths if "/" in fp}
    )

    # --- communities ---
    communities = []
    try:
        from batho.modules.storage.arrow_bundle.writer import read_ipc_table
        communities = read_ipc_table(
            db._active_or_empty("communities")
        ).to_pylist()
    except Exception:
        communities = []
    comm_singletons = sum(
        1 for c in communities
        if (c.get("entity_count") or 0) <= 1 or c.get("is_singleton")
    )

    # --- gap synthesis ---
    gaps = []

    def _samples(ents, k=sample_k):
        return [e.id for e in ents[:k]]

    noise_unquarantined = [
        e for e in noise_ents
        if not (_meta(e, "bsg.noise") or _meta(e, "bsg.quarantined"))
    ]
    if noise_unquarantined:
        gaps.append({
            "gap": "noise_path_entities_not_quarantined",
            "count": len(noise_unquarantined),
            "samples": _samples(noise_unquarantined),
            "by_top_dir": dict(noise_by_dir.most_common(10)),
            "suggested_rule_shape": "file_patterns -> bsg.noise + bsg.quarantined",
        })
    if unresolved and total:
        ratio = len(unresolved) / total
        gaps.append({
            "gap": "unresolved_stub_density",
            "count": len(unresolved),
            "ratio": round(ratio, 4),
            "top_targets": dict(unresolved_names.most_common(top_n)),
            "samples": _samples(unresolved),
            "suggested_rule_shape": (
                "entity_types:[external_symbol] + name_patterns:['unresolved:*'] "
                "-> bsg.quarantined (or targeted name_patterns per top target)"
            ),
        })
    uncategorized = total - categorized
    if total and uncategorized / total > 0.5:
        gaps.append({
            "gap": "low_category_coverage",
            "count": uncategorized,
            "uncategorized_pct": round(100 * uncategorized / total, 1),
            "suggested_rule_shape": "file_patterns -> assign_category (TEST/DOCS/CONFIG/GENERATED/VENDOR)",
        })
    if miscat_samples:
        gaps.append({
            "gap": "generated_or_vendor_files_marked_source",
            "count": miscat_count,
            "samples": miscat_samples,
            "suggested_rule_shape": "file_patterns -> assign_category:GENERATED/VENDOR",
        })
    if total and domain_tagged / total < 0.5 and len(top_level_dirs) >= 3:
        gaps.append({
            "gap": "domain_taxonomy_missing",
            "count": total - domain_tagged,
            "domain_coverage_pct": round(100 * domain_tagged / max(total, 1), 1),
            "top_level_dirs": top_level_dirs[:20],
            "suggested_rule_shape": "file_patterns per top-level dir -> metadata:{bsg.domain: <name>} (feeds L0 community tier)",
        })

    return {
        "schema_version": "enrich-profile.v1",
        "root": str(root),
        "run_uuid": run_uuid,
        "totals": {
            "entities": total,
            "relationships": len(graph.relationships),
            "files": len(tracking),
            "unresolved_stubs": len(unresolved),
            "external_symbols": len(external),
            "quarantined": quarantined,
            "rule_tagged_entities": tagged_rules,
        },
        "entity_type_distribution": dict(type_dist.most_common()),
        "noise": {
            "entities_in_noise_paths": len(noise_ents),
            "unquarantined_noise": len(noise_unquarantined),
            "by_top_dir": dict(noise_by_dir.most_common(15)),
        },
        "coverage": {
            "category_pct": round(100 * categorized / max(total, 1), 1),
            "domain_pct": round(100 * domain_tagged / max(total, 1), 1),
            "service_tag_pct": round(100 * service_tagged / max(total, 1), 1),
            "miscategorized_source_samples": miscat_samples,
        },
        "degree": {
            "inbound_histogram": degree_hist,
            "top_inbound": top_inbound,
        },
        "comments": {
            "comment_entities": len(comment_ents),
            "comment_density": round(len(comment_ents) / max(total, 1), 4),
            "rationale_patterns": dict(rationale),
        },
        "manifests": {
            "detected": manifests_found,
            "top_level_dirs": top_level_dirs,
        },
        "communities": {
            "count": len(communities),
            "singletons": comm_singletons,
            "singleton_ratio": round(comm_singletons / len(communities), 3) if communities else None,
        },
        "gaps": gaps,
    }


def render_overview_md(report: dict, context_overview: dict | None = None) -> str:
    """Merged overview.md — context_overview counts + enrich gap profile."""
    t = report["totals"]
    lines = [
        "# Graph Overview",
        "",
        f"_run `{report['run_uuid']}` — {report['root']}_",
        "",
        "## Totals",
        "",
        f"| entities | relationships | files | unresolved stubs | quarantined |",
        f"|---|---|---|---|---|",
        f"| {t['entities']} | {t['relationships']} | {t['files']} | {t['unresolved_stubs']} | {t['quarantined']} |",
        "",
    ]
    if context_overview:
        cats = context_overview.get("categories") or {}
        if isinstance(cats, dict):
            cats_items = sorted(cats.items(), key=lambda kv: -kv[1])
        elif isinstance(cats, list):
            # metrics.py emits [{extension, files, count}, ...] — render
            # extension + count, not the raw dict.
            cats_items = [
                (str(c.get("extension") or "?"), c.get("count"))
                for c in cats if isinstance(c, dict)
            ]
            cats_items.sort(key=lambda kv: -(kv[1] or 0))
        else:
            cats_items = []
        if cats_items:
            lines += ["## File Categories", ""]
            for k, v in cats_items[:12]:
                lines.append(f"- **{k}**{f': {v}' if v is not None else ''}")
            lines.append("")

    lines.append("## Entity Types")
    for k, v in list(report["entity_type_distribution"].items())[:15]:
        lines.append(f"- `{k}`: {v}")
    lines.append("")

    cov = report["coverage"]
    lines += [
        "## Tag Coverage",
        "",
        f"- category: {cov['category_pct']}%",
        f"- domain (bsg.domain): {cov['domain_pct']}%",
        f"- service tag: {cov['service_tag_pct']}%",
        "",
    ]

    d = report["degree"]["inbound_histogram"]
    comm = report["communities"]
    lines += [
        "## Degree & Communities",
        "",
        f"- fan-in p50/p95/p99/max: {d['p50']}/{d['p95']}/{d['p99']}/{d['max']}",
        f"- communities: {comm['count']} (singletons: {comm['singletons']})",
        "",
    ]

    noise = report["noise"]
    lines += [
        "## Noise & Ghosts",
        "",
        f"- entities in noise paths: {noise['entities_in_noise_paths']} "
        f"(unquarantined: {noise['unquarantined_noise']})",
        f"- unresolved stubs: {t['unresolved_stubs']} "
        f"({round(100 * t['unresolved_stubs'] / max(t['entities'], 1), 1)}%)",
        "",
    ]

    lines.append("## Gaps")
    lines.append("")
    if not report["gaps"]:
        lines.append("None — graph looks clean.")
    for g in report["gaps"]:
        lines.append(f"### {g['gap']} ({g['count']})")
        lines.append("")
        lines.append(f"- suggested rule shape: `{g.get('suggested_rule_shape', '')}`")
        if g.get("by_top_dir"):
            lines.append(f"- by dir: {g['by_top_dir']}")
        for s in g.get("samples", [])[:5]:
            lines.append(f"- e.g. `{s}`")
        lines.append("")

    return "\n".join(lines) + "\n"
