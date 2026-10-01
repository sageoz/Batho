"""Plugin fixture gate — stage-2 acceptance for `batho plugins validate`.

Loads a deterministic sample of real entities from the built artifact, applies
the candidate rules via `apply_rule_plugins(trace=True)`, and verifies each
rule:
  - ≥1 intended hit
  - selectivity: hits < selectivity% of sampled entities
  - non-empty metadata delta (beyond the bsg.rules stamp)
Plus: no conflicts against the effective builtin rule set.

`load_gate_sample_graph` and `load_gate_builtins` are exposed so callers
validating many plugin files (e.g. `batho plugins validate` over a directory)
can build the expensive inputs once and share them via `fixture_gate`'s
`sample_graph`/`builtin_rules` parameters.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path


def _candidate_rules_config(plugin_path: Path) -> dict:
    return {
        "enabled": True,
        "auto_load_all_plugins": False,
        "builtin_plugins": [],
        "custom_rules_path": str(plugin_path),
        "custom_rules_dir": "",
        "custom_rules_inline": [],
    }


def load_gate_sample_graph(root: Path, sample_size: int = 2000):
    """Load the deterministic entity sample the fixture gate runs against.

    Returns ``(graph, error)`` — ``graph`` is an ``InMemoryGraph`` containing
    the evenly-strided entity/relationship sample, or ``None`` with a
    human-readable ``error`` string on failure. Artifact-load exceptions are
    converted into error strings so `plugins validate` exits cleanly instead
    of crashing on a corrupt or unreadable bundle.
    """
    from batho.modules.graph.builder.codegraph import InMemoryGraph
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle
    from batho.orchestrator.plugins_apply import _load_graph_from_artifact

    # Guard before BathoBundle construction — it eagerly mkdirs the artifact
    # dir; `plugins validate` shouldn't create .batho/ on a bare checkout.
    if not resolve_bundle_dir(root).exists():
        return None, "no artifact — run `batho build` first"

    db = BathoBundle(root)
    run_uuid = db.get_latest_run_id()
    if run_uuid is None:
        return None, "no artifact — run `batho build` first"
    run_internal_id = db.get_run_internal_id(run_uuid)
    try:
        graph, _views, _tracking, _eid_map = _load_graph_from_artifact(
            db, run_internal_id, root, include_storage=False
        )
    except Exception as exc:
        return None, f"artifact load failed: {exc}"
    if not graph.entities:
        return None, "artifact contains no entities"

    # Deterministic sample: sorted ids, evenly strided.
    sorted_ids = sorted(graph.entities.keys())
    step = max(1, len(sorted_ids) // max(sample_size, 1))
    sample_ids = set(sorted_ids[::step][:sample_size])
    sample_entities = {
        eid: graph.entities[eid] for eid in sample_ids
    }
    sample_rels = [
        r for r in graph.relationships
        if r.source_id in sample_ids and r.target_id in sample_ids
    ]
    return (
        InMemoryGraph(
            entities=dict(sample_entities), relationships=list(sample_rels)
        ),
        None,
    )


def _rule_writes_satisfied(rule, hit_eids: list[str], before_meta: dict) -> bool:
    """True when every hit entity already carries the rule's writes.

    Distinguishes "previously applied plugin" (idempotent re-apply — the
    metadata/tags are already present) from a genuine no-op on a clean
    artifact. Only ``actions.metadata`` and ``actions.add_usn_tags`` can be
    pre-verified this way; derivation actions can't be precomputed.
    """
    meta_writes = dict(rule.actions.metadata or {})
    tags = set(rule.actions.add_usn_tags or ())
    if not meta_writes and not tags:
        return False
    for eid in hit_eids:
        before = before_meta.get(eid) or {}
        if any(before.get(key) != value for key, value in meta_writes.items()):
            return False
        if tags and not tags.issubset(set(before.get("bsg.usn") or [])):
            return False
    return True


def load_gate_builtins(root: Path) -> list:
    """Load the effective builtin rule set for the candidate conflict check."""
    from batho.modules.compression.rules import load_effective_rules

    builtin_cfg = {
        "enabled": True,
        "auto_load_all_plugins": True,
        "builtin_plugins": [],
        "custom_rules_path": None,
        "custom_rules_dir": "",
        "custom_rules_inline": [],
    }
    rules, _load_stats = load_effective_rules(builtin_cfg, root)
    return list(rules)


def fixture_gate(
    plugin_path: Path,
    root: Path,
    sample_size: int = 2000,
    selectivity_pct: float = 10.0,
    *,
    sample_graph=None,
    builtin_rules=None,
    extra_candidate_rules=None,
) -> dict:
    """Apply candidate rules to a deterministic entity sample; per-rule verdicts.

    ``sample_graph``/``builtin_rules`` may be precomputed via
    ``load_gate_sample_graph``/``load_gate_builtins`` so directory-wide
    validation loads the artifact and builtin rules once instead of per file.
    ``extra_candidate_rules`` carries the *other* candidate files' compiled
    rules in directory mode so the conflict stage also checks cross-file
    overlaps (ENR-06), not just builtin-vs-candidate.
    """
    from batho.modules.compression.rules import (
        _detect_rule_conflicts,
        apply_rule_plugins,
        load_effective_rules,
    )
    from batho.modules.graph.builder.codegraph import InMemoryGraph

    if sample_graph is None:
        sample_graph, load_err = load_gate_sample_graph(root, sample_size)
        if load_err is not None:
            return {"passed": False, "errors": [load_err]}

    # Work on a private copy — apply_rule_plugins mutates entity metadata
    # (and may append derived relationships) in place. Callers sharing one
    # sample across plugin files must still gate each file against the
    # pristine pre-apply state.
    sample_graph = InMemoryGraph(
        entities={
            eid: deepcopy(ent) for eid, ent in sample_graph.entities.items()
        },
        relationships=[deepcopy(r) for r in sample_graph.relationships],
    )

    rules_cfg = _candidate_rules_config(plugin_path)
    rules, load_stats = load_effective_rules(rules_cfg, root)
    if not rules:
        return {
            "passed": False,
            "errors": ["no rules compiled from plugin"],
            "load_errors": list(load_stats.get("errors") or []),
        }
    candidate_names = {r.name for r in rules}

    # Conflict check: builtin set + this file's rules + any sibling
    # candidates (directory mode). Intra-file overlaps are already surfaced
    # by stage-1 strict validation; here they dedupe harmlessly.
    if builtin_rules is None:
        builtin_rules = load_gate_builtins(root)
    conflicts_all = _detect_rule_conflicts(
        list(builtin_rules) + list(rules) + list(extra_candidate_rules or [])
    )
    candidate_conflicts = [
        w for w in conflicts_all
        if w.get("rule_a") in candidate_names or w.get("rule_b") in candidate_names
    ]

    before_meta = {
        eid: dict(ent.metadata or {})
        for eid, ent in sample_graph.entities.items()
    }
    stats = apply_rule_plugins(
        graph=sample_graph,
        root_path=root,
        rules_config=rules_cfg,
        trace=True,
    )

    rule_hits = stats.get("rule_hits") or {}
    total_sampled = max(len(sample_graph.entities), 1)
    rule_verdicts = []
    gate_pass = True

    for rule in rules:
        name = rule.name
        hits = int(rule_hits.get(name, 0))
        hit_pct = round(100 * hits / total_sampled, 2)

        # entities that gained this rule in bsg.rules
        hit_eids = [
            eid for eid, ent in sample_graph.entities.items()
            if name in ((ent.metadata or {}).get("bsg.rules") or [])
        ]
        # metadata delta beyond the bsg.rules stamp
        delta_nonempty = any(
            {
                k: v for k, v in (sample_graph.entities[eid].metadata or {}).items()
                if k != "bsg.rules"
            } != {
                k: v for k, v in before_meta.get(eid, {}).items()
                if k != "bsg.rules"
            }
            for eid in hit_eids
        ) if hit_eids else False

        reasons = []
        verdict = "pass"
        if hits == 0:
            verdict = "fail"
            reasons.append("zero hits on sampled entities")
        elif hit_pct >= selectivity_pct:
            verdict = "fail"
            reasons.append(
                f"selectivity breach: {hit_pct}% ≥ {selectivity_pct}% of sample"
            )
        if hits > 0 and not delta_nonempty:
            if hit_eids and _rule_writes_satisfied(rule, hit_eids, before_meta):
                reasons.append(
                    "idempotent: writes already present on sampled entities "
                    "(plugin previously applied)"
                )
            else:
                verdict = "fail"
                reasons.append("no-op: hits produced no metadata/tag delta")
        if candidate_conflicts:
            for w in candidate_conflicts:
                if w.get("rule_a") == name or w.get("rule_b") == name:
                    verdict = "fail"
                    reasons.append(f"conflict: {w.get('overlap', w)}")
        if verdict == "fail":
            gate_pass = False

        rule_verdicts.append({
            "rule": name,
            "rule_id": rule.rule_id,
            "hits": hits,
            "hit_pct": hit_pct,
            "entities_matched": len(hit_eids),
            "delta_nonempty": delta_nonempty,
            "verdict": verdict,
            "reasons": reasons,
            "evidence": sorted(hit_eids)[:5],
        })

    return {
        "passed": gate_pass,
        "sample_size": total_sampled,
        "selectivity_pct": selectivity_pct,
        "rules": rule_verdicts,
        "candidate_conflicts": candidate_conflicts,
        "errors": [],
    }
