"""Rule fitness scorer — `enrich_score` run-artifact payload.

Reads persisted `run_artifacts.rule_stats` (rule-stats.v1) across the N most
recent runs and computes per-rule fitness: hit trend, selectivity, perf cost,
coverage, and delta-utility proxy (unique-tag coverage — rules tagging
entities nothing else tags).

Verdicts (reasons attached — the operator/agent decides):
  promote    — useful + stable: remove bsg.generated / optionally raise severity
  shadow     — keep generated state; watch another N runs
  regenerate — zero hits with <3 observed runs (insufficient evidence — maybe
               the repo drifted), or selectivity breach: rewrite matchers
  disable    — zero hits over >=3 observed runs: the rule is dead
  stale      — rule in telemetry but its plugin file is gone
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _trend(hits_series: list[int]) -> str:
    """hits_series ordered oldest→newest."""
    nonzero = [h for h in hits_series if h > 0]
    if not nonzero:
        return "zero"
    if len(hits_series) >= 2:
        first, last = hits_series[0], hits_series[-1]
        if last > first * 1.25:
            return "rising"
        if last < first * 0.75:
            return "falling"
    return "stable"


def build_score_report(
    db: Any,
    root: Path,
    runs_n: int = 5,
    perf_budget_ns: int = 5_000_000,
    extra_telemetry: dict | None = None,
    entity_count: int | None = None,
    preloaded: tuple | None = None,
) -> dict | None:
    """Score rules from run_artifacts.rule_stats history.

    ``extra_telemetry`` lets a build/patch include the current run's stats
    before the row is flushed (``{"run_uuid": …, "stats": payload}``).
    ``entity_count`` is the just-built entity count — the current run's
    artifact row isn't flushed yet when this is called from build/patch, so
    callers pass it explicitly; otherwise it falls back to the latest run's
    ``context_overview`` blob.
    ``preloaded`` optionally supplies ``(graph, file_views, tracking,
    eid_to_relfile)`` so callers can share one graph load across reports.
    Returns None when no rule telemetry exists (rules disabled) — callers
    treat None as "no score column this run".
    """
    from batho.orchestrator.plugins_apply import _load_graph_from_artifact

    run_rows = [
        r for r in (db._reader.get_all_runs() or [])
        if r.get("status") == "completed"
    ]
    if not run_rows and not extra_telemetry:
        return None

    recent = run_rows[-runs_n:]
    telemetry: list[dict] = []
    for r in recent:
        run_uuid = r.get("run_uuid")
        internal = db.get_run_internal_id(run_uuid)
        if internal is None:
            continue
        artifacts = db.get_run_artifacts(internal)
        rs = (artifacts or {}).get("rule_stats")
        # Patch-run rule_stats are computed over the changed-file subgraph
        # only — folding them into whole-repo trend history fabricates
        # "falling" trends and phantom regenerate/disable verdicts.
        if rs and rs.get("run_kind") != "patch":
            telemetry.append({"run_uuid": run_uuid, "stats": rs})
    if (
        extra_telemetry
        and extra_telemetry["stats"].get("run_kind") != "patch"
        and all(
            t["run_uuid"] != extra_telemetry["run_uuid"] for t in telemetry
        )
    ):
        telemetry.append(extra_telemetry)

    if not telemetry:
        return None

    # --- per-rule aggregation across runs ---
    # `rule_hits` only contains rules with >0 hits — a rule that was loaded
    # but hit nothing must still record a 0 for that run or zero-hit /
    # regressed rules are invisible (dead "regenerate"/"disable" verdicts).
    # `rules_loaded_names` (rule-stats.v1+) gives the loaded set; for legacy
    # payloads without it, previously-tracked rules are assumed still loaded.
    rules: dict[str, dict] = {}
    plugin_files: dict[str, str] = {}
    for t in telemetry:
        stats = t["stats"]
        plugin_files.update(stats.get("plugin_files") or {})
        hits = stats.get("rule_hits") or {}
        perf = stats.get("rule_perf") or {}
        per_rule_meta = {
            pr.get("rule"): pr for pr in (stats.get("per_rule") or [])
        }
        loaded_names = stats.get("rules_loaded_names")
        if isinstance(loaded_names, list) and loaded_names:
            seen_this_run = {str(n) for n in loaded_names} | set(hits)
        else:
            seen_this_run = set(hits) | set(rules)
        for name in sorted(seen_this_run):
            rec = rules.setdefault(name, {
                "rule": name,
                "plugin": (per_rule_meta.get(name) or {}).get("plugin", ""),
                "hits_per_run": [],
                "avg_ns_per_run": [],
                "runs_seen": 0,
            })
            rec["hits_per_run"].append(int(hits.get(name, 0)))
            rec["runs_seen"] += 1
            pr_perf = perf.get(name) or {}
            if pr_perf.get("avg_ns"):
                rec["avg_ns_per_run"].append(int(pr_perf["avg_ns"]))
            meta = per_rule_meta.get(name)
            if meta and meta.get("plugin"):
                rec["plugin"] = meta["plugin"]

    # --- delta-utility: unique-rule coverage from entity bsg.rules ---
    unique_by_rule: dict[str, int] = {}
    total_by_rule: dict[str, int] = {}
    try:
        if preloaded is not None:
            graph = preloaded[0]
        else:
            run_uuid = run_rows[-1].get("run_uuid") if run_rows else None
            internal = db.get_run_internal_id(run_uuid) if run_uuid else None
            if internal is not None:
                graph, _v, _t, _e = _load_graph_from_artifact(
                    db, internal, root, include_storage=False
                )
            else:
                graph = None
        if graph is not None:
            for ent in graph.entities.values():
                applied = (getattr(ent, "metadata", None) or {}).get("bsg.rules")
                if not isinstance(applied, list):
                    continue
                for name in applied:
                    total_by_rule[name] = total_by_rule.get(name, 0) + 1
                if len(applied) == 1:
                    only = applied[0]
                    unique_by_rule[only] = unique_by_rule.get(only, 0) + 1
    except Exception:
        pass  # delta-utility is a proxy — degrade gracefully

    latest_entities = int(entity_count) if entity_count else 0
    if not latest_entities:
        try:
            if run_rows:
                ov = (db.get_run_artifacts(
                    db.get_run_internal_id(run_rows[-1].get("run_uuid"))
                ) or {}).get("context_overview") or {}
                latest_entities = int(ov.get("total_entities") or 0)
        except Exception:
            pass

    # --- verdicts ---
    rule_rows = []
    for name, rec in sorted(rules.items()):
        hits_series = rec["hits_per_run"]
        total_hits = sum(hits_series)
        latest_hits = hits_series[-1] if hits_series else 0
        trend = _trend(hits_series)
        avg_ns = (
            int(sum(rec["avg_ns_per_run"]) / len(rec["avg_ns_per_run"]))
            if rec["avg_ns_per_run"] else 0
        )
        plugin = rec["plugin"]
        plugin_path = plugin_files.get(plugin)
        file_exists = Path(plugin_path).exists() if plugin_path else None
        unique = unique_by_rule.get(name, 0)
        total_tagged = total_by_rule.get(name, 0)
        delta_utility = round(unique / total_tagged, 3) if total_tagged else None
        coverage_pct = (
            round(100 * total_tagged / latest_entities, 2)
            if latest_entities else None
        )

        reasons = []
        verdict = "shadow"
        if file_exists is False:
            verdict = "stale"
            reasons.append(f"plugin file missing: {plugin_path}")
        elif total_hits == 0:
            verdict = "regenerate" if len(telemetry) < 3 else "disable"
            reasons.append(f"zero hits across {len(hits_series)} run(s)")
        elif coverage_pct is not None and coverage_pct > 25:
            verdict = "regenerate"
            reasons.append(f"selectivity breach: touches {coverage_pct}% of entities")
        elif avg_ns > perf_budget_ns:
            verdict = "shadow"
            reasons.append(f"perf: avg_ns {avg_ns} over budget {perf_budget_ns}")
        elif delta_utility is not None and delta_utility > 0.5 and trend != "zero":
            verdict = "promote"
            reasons.append(
                f"unique coverage {delta_utility} (tags {unique} entities no other rule reaches)"
            )
        else:
            if trend == "falling":
                reasons.append("hit count declining across runs")
            if delta_utility is not None and delta_utility < 0.2:
                reasons.append("low unique coverage — duplicates other rules")

        if file_exists is False and verdict != "stale":
            reasons.append(f"note: plugin file missing: {plugin_path}")

        rule_rows.append({
            "rule": name,
            "plugin": plugin,
            "plugin_file": plugin_path,
            "total_hits": total_hits,
            "latest_hits": latest_hits,
            "trend": trend,
            "avg_ns": avg_ns,
            "coverage_pct": coverage_pct,
            "delta_utility": delta_utility,
            "verdict": verdict,
            "reasons": reasons,
        })

    # --- per-plugin rollup ---
    plugins: dict[str, dict] = {}
    for rr in rule_rows:
        p = plugins.setdefault(rr["plugin"] or "(unknown)", {
            "plugin": rr["plugin"] or "(unknown)",
            "plugin_file": rr["plugin_file"],
            "rules": 0,
            "verdicts": {"promote": 0, "shadow": 0, "regenerate": 0,
                         "disable": 0, "stale": 0},
            "total_hits": 0,
        })
        p["rules"] += 1
        p["total_hits"] += rr["total_hits"]
        p["verdicts"][rr["verdict"]] += 1

    return {
        "schema_version": "enrich-score.v1",
        "root": str(root),
        "runs_analyzed": len(telemetry),
        "run_uuids": [t["run_uuid"] for t in telemetry],
        "insufficient_history": len(telemetry) < 2,
        "rules": rule_rows,
        "plugins": list(plugins.values()),
    }


def render_score_md(report: dict) -> str:
    """score.md — per-rule fitness table + plugin rollup."""
    lines = [
        "# Rule Fitness Score",
        "",
        f"_runs analyzed: {report['runs_analyzed']} "
        f"({', '.join(u[:20] for u in report['run_uuids'][-3:])})_",
        "",
    ]
    if report["insufficient_history"]:
        lines += [
            "> **note**: insufficient history (<2 runs) — trends unreliable",
            "",
        ]
    lines += [
        "| rule | verdict | hits | trend | avg_ns | coverage% | util |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report["rules"]:
        util = r["delta_utility"] if r["delta_utility"] is not None else "—"
        cov = r["coverage_pct"] if r["coverage_pct"] is not None else "—"
        lines.append(
            f"| `{r['rule']}` | {r['verdict']} | {r['total_hits']} "
            f"| {r['trend']} | {r['avg_ns']} | {cov} | {util} |"
        )
    lines.append("")

    reasons_any = [r for r in report["rules"] if r["reasons"]]
    if reasons_any:
        lines += ["## Verdict Reasons", ""]
        for r in reasons_any:
            for reason in r["reasons"][:3]:
                lines.append(f"- `{r['rule']}` — {reason}")
        lines.append("")

    lines += ["## Plugins", ""]
    for p in report["plugins"]:
        v = p["verdicts"]
        lines.append(
            f"- **{p['plugin']}** — rules={p['rules']} hits={p['total_hits']} "
            f"[promote={v['promote']} shadow={v['shadow']} "
            f"regen={v['regenerate']} disable={v['disable']} stale={v['stale']}]"
        )
    lines.append("")
    return "\n".join(lines)
