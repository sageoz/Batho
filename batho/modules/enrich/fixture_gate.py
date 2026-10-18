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


_PINNED_VERSION_RE = None  # lazily compiled


def _candidate_plugin_meta(plugin_path: Path) -> dict:
    """Top-level plugin metadata the gate needs before rule evaluation.

    Reads only the header fields (``plugin_id``, ``version``, ``class``) —
    cheap yaml load; the full rule compile happens later via
    ``load_effective_rules``.
    """
    import yaml

    try:
        doc = yaml.safe_load(plugin_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(doc, dict):
        return {}
    return doc


def _pinned_version_ok(version: Any) -> bool:
    """``class: core`` requires a pinned semver (no latest/*/empty)."""
    global _PINNED_VERSION_RE
    if _PINNED_VERSION_RE is None:
        import re

        _PINNED_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
    return bool(_PINNED_VERSION_RE.match(str(version or "")))


def _golden_registry() -> dict:
    """Load the core-pack golden manifest (plugin_id → golden test entry)."""
    import json

    try:
        import batho_plugin.core as _core

        manifest = Path(_core.__file__).resolve().parent / "golden_manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return data.get("plugins", {}) or {}
    except Exception:
        pass
    return {}


def _core_class_errors(plugin_meta: dict) -> list:
    """``class: core`` gate (spec §4.5): pinned version + golden registration.

    Returns a list of error strings (empty when the plugin is not core-class
    or all requirements pass). Core plugins are selectivity-cap exempt but
    not verification-exempt.
    """
    if str(plugin_meta.get("class") or "standard") != "core":
        return []
    errors = []
    plugin_id = str(plugin_meta.get("plugin_id") or "")
    version = plugin_meta.get("version")
    if not _pinned_version_ok(version):
        errors.append(
            f"class:core requires a pinned semver version, got {version!r}"
        )
    if plugin_id not in _golden_registry():
        errors.append(
            f"class:core plugin '{plugin_id}' is not registered in the "
            "golden manifest (sdk/batho_plugin/core/golden_manifest.json)"
        )
    return errors


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
    from batho_plugin.rule_engine import load_effective_rules

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
    from batho_plugin.rule_engine import (
        _detect_rule_conflicts,
        apply_rule_plugins,
        load_effective_rules,
    )
    from batho.modules.graph.builder.codegraph import InMemoryGraph

    if sample_graph is None:
        sample_graph, load_err = load_gate_sample_graph(root, sample_size)
        if load_err is not None:
            return {"passed": False, "errors": [load_err]}

    # T20: plugin class gate (spec §4.5). class:core skips the selectivity
    # cap (load-bearing rules are intentionally broad) but must be version-
    # pinned and golden-test registered.
    plugin_meta = _candidate_plugin_meta(plugin_path)
    plugin_class = str(plugin_meta.get("class") or "standard")
    core_errors = _core_class_errors(plugin_meta)
    if core_errors:
        return {"passed": False, "errors": core_errors}

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
        # class:core plugins are load-bearing engine rules: the artifact
        # sample is not their fixture corpus, so sample-based verdicts
        # (zero hits / selectivity / no-op idempotency) don't apply —
        # golden tests carry the behavioral gate (T30).
        core_class = plugin_class == "core"
        if hits == 0:
            if core_class:
                reasons.append(
                    "zero hits on sampled entities (core class — covered by golden tests)"
                )
            else:
                verdict = "fail"
                reasons.append("zero hits on sampled entities")
        elif hit_pct >= selectivity_pct and not core_class:
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
            elif not core_class:
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
        "plugin_class": plugin_class,
        "sample_size": total_sampled,
        "selectivity_pct": selectivity_pct,
        "rules": rule_verdicts,
        "candidate_conflicts": candidate_conflicts,
        "errors": [],
    }
