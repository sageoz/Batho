"""CLI subcommand group: batho plugins

Verb group for BSG rule plugins:
  validate — strict schema check + fixture gate for plugin YAML files
  list     — show discovered builtin + custom plugin files
  apply    — re-enrich the built artifact's graph with rules (no re-extraction)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from batho.cli._utils import create_base_parser
from batho.utils.logging import get_logger

LOGGER = get_logger("cli.plugins")


def register_plugins_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `plugins` subcommand group on the given subparsers action."""
    parser = subparsers.add_parser(
        "plugins",
        help="Manage BSG rule plugins (validate/list/apply)",
        description=(
            "Work with BSG rule plugins (schema: bsg-plugin.v2 — see "
            "batho_plugin/rule_engine.py _validate_plugin_document). "
            "`validate` schema-checks plugin files and gates them against "
            "a deterministic entity sample from the built artifact; "
            "`apply` re-enriches an existing artifact's graph without "
            "re-extracting files."
        ),
    )
    plugins_sub = parser.add_subparsers(dest="plugins_command", required=True)

    validate = plugins_sub.add_parser(
        "validate",
        help="Validate plugin YAML files (schema + fixture gate)",
        parents=[create_base_parser()],
        description=(
            "Two-stage acceptance for BSG plugin files. Stage 1 validates "
            "against the bsg-plugin.v2 schema: document fields, "
            "matchers/actions structure, regex compilation, duplicate "
            "rule_ids, empty matchers, and intra-plugin conflicts. Stage 2 "
            "applies the candidate rules to a deterministic entity sample "
            "from the built artifact and verifies each rule hits ≥1 entity "
            "with a non-empty metadata delta. With no PATH, every "
            "*.yaml/*.yml file in the plugins dir (rules.custom_rules_dir, "
            "default .batho/plugins) is validated; PATH may also be a "
            "single file or a directory of plugin files."
        ),
    )
    validate.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "Plugin YAML file or directory to validate (default: every "
            "*.yaml/*.yml in the plugins dir, .batho/plugins)"
        ),
    )
    validate.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit machine-readable JSON result",
    )
    validate.add_argument(
        "--entities-sample",
        type=int,
        default=2000,
        help="Fixture-gate entity sample size (default 2000)",
    )
    validate.add_argument(
        "--selectivity",
        type=float,
        default=10.0,
        help="Max allowed hit %% of sampled entities (default 10)",
    )

    plugins_sub.add_parser(
        "list",
        help="List discovered builtin + custom plugin files",
        parents=[create_base_parser()],
    )

    plugins_sub.add_parser(
        "fingerprint",
        help="Print the current plugin-set fingerprint (host data + hooks + rules)",
        parents=[create_base_parser()],
    )

    plugins_sub.add_parser(
        "doctor",
        help="Report plugin-host status, worker preload health, and drift vs the artifact",
        parents=[create_base_parser()],
    )

    apply = plugins_sub.add_parser(
        "apply",
        help="Re-enrich the built artifact's graph with rules (no re-extraction)",
        parents=[create_base_parser()],
        description=(
            "Load the artifact's entity graph, apply the effective BSG rule "
            "set, and write back only the changed per-file views — enabling "
            "plugin enrichment on an existing build without re-parsing files."
        ),
    )
    apply.add_argument(
        "--plugin",
        type=Path,
        default=None,
        help=(
            "Apply only rules from this plugin file (implies --plugins-only); "
            "omit to apply every plugin in the plugins dir (.batho/plugins)"
        ),
    )
    apply.add_argument(
        "--plugins-only",
        action="store_true",
        default=False,
        help="Skip builtin plugins — apply custom rules only",
    )
    apply.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report the delta without writing blobs",
    )
    apply.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit machine-readable JSON result",
    )

    parser.set_defaults(func=cmd_plugins)


def register_doctor_parser(subparsers) -> None:
    """Top-level ``batho doctor`` mount (spec §8.1 names it at the root).
    ``batho plugins doctor`` remains; both run the same check."""
    doctor = subparsers.add_parser(
        "doctor",
        help="Report plugin-host status, worker preload health, and drift vs the artifact",
        parents=[create_base_parser()],
    )
    doctor.set_defaults(func=_cmd_doctor)


def cmd_plugins(args: argparse.Namespace) -> int:
    """Dispatch plugins subcommands."""
    cmd = args.plugins_command
    if cmd == "validate":
        return _cmd_validate(args)
    if cmd == "list":
        return _cmd_list(args)
    if cmd == "apply":
        return _cmd_apply(args)
    if cmd == "fingerprint":
        return _cmd_fingerprint(args)
    if cmd == "doctor":
        return _cmd_doctor(args)
    return 1


def _cmd_fingerprint(args: argparse.Namespace) -> int:
    """Print the current plugin-set fingerprint (T25)."""
    from batho_plugin import load_host
    from batho_plugin.fingerprint import fingerprint_from_host

    root = getattr(args, "root", None) or Path(".")
    from batho.core.config.loader import get_config_cached, set_active_root

    set_active_root(root)
    cfg = get_config_cached()
    plugins_cfg = cfg.get("plugins", {}) or {}
    try:
        host = load_host(config={"plugins": plugins_cfg})
    except Exception as exc:
        print(f"error: plugin host failed to load: {exc}")
        return 1
    fp = fingerprint_from_host(host)
    print(fp or "(empty plugin set)")
    print(f"plugins: {len(host.plugin_ids)} loaded")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Report plugin-host health: pack status, counts, artifact drift (T25)."""
    import json as _json

    from batho_plugin import load_host
    from batho_plugin.fingerprint import fingerprint_from_host

    root = getattr(args, "root", None) or Path(".")
    from batho.core.config.loader import get_config_cached, set_active_root

    set_active_root(root)
    cfg = get_config_cached()
    plugins_cfg = cfg.get("plugins", {}) or {}

    report: dict = {"root": str(Path(root).resolve())}
    try:
        host = load_host(config={"plugins": plugins_cfg})
        report["host"] = "ok"
        report["plugins_loaded"] = len(host.plugin_ids)
        report["plugin_ids"] = sorted(host.plugin_ids)
        report["fingerprint"] = fingerprint_from_host(host)
    except Exception as exc:
        report["host"] = f"failed: {exc}"
        print(_json.dumps(report, indent=2, default=str))
        return 1

    report["external_enabled"] = bool(
        (plugins_cfg.get("external") or {}).get("enabled", False)
    )
    report["fingerprint_in_cache"] = bool(
        plugins_cfg.get("fingerprint_in_cache", True)
    )

    # Drift vs the last recorded fingerprint (T23 contract): scan runs
    # newest→oldest — patch runs may lack a fingerprint; use the most recent
    # that has one. Integer ids resolve positionally oldest-first through
    # _resolve_run_uuid, so iterate the run table by started_at instead.
    artifact_fp = None
    try:
        from batho.modules.storage.arrow_bundle.bundle import BathoBundle

        db = BathoBundle(Path(root))
        runs = db._reader.get_all_runs()
        runs.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
        for run in runs[:16]:
            try:
                artifacts = db.get_run_artifacts(run.get("run_uuid")) or {}
            except Exception as exc:
                LOGGER.debug(
                    "doctor_run_artifacts_failed",
                    run=run.get("run_uuid"),
                    error=str(exc),
                )
                continue
            fp = (artifacts.get("telemetry_metrics") or {}).get(
                "plugin_fingerprint"
            )
            if fp:
                artifact_fp = fp
                report["artifact_run"] = run.get("run_uuid")
                break
    except Exception as exc:
        LOGGER.debug("doctor_artifact_scan_failed", error=str(exc))
    report["artifact_fingerprint"] = artifact_fp
    current = report["fingerprint"]
    if artifact_fp is None:
        report["drift"] = "unknown (no artifact fingerprint recorded)"
    elif artifact_fp != current:
        report["drift"] = (
            f"drift: artifact={artifact_fp} current={current} — "
            "AST cache entries keyed by the old fingerprint will miss"
        )
    else:
        report["drift"] = "none"

    print(_json.dumps(report, indent=2, default=str))
    return 0


def _default_plugins_dir(root: Path) -> Path:
    """Configured plugins dir (rules.custom_rules_dir; default .batho/plugins)."""
    from batho.core.config.loader import get_config_cached, set_active_root
    from batho_plugin.rule_engine import _resolve_custom_rules_path

    set_active_root(root)
    cfg = get_config_cached()
    dir_value = (cfg.get("rules", {}) or {}).get("custom_rules_dir")
    if dir_value:
        try:
            return _resolve_custom_rules_path(str(dir_value), root)
        except Exception as exc:
            LOGGER.warning(
                "invalid rules.custom_rules_dir",
                value=str(dir_value),
                error=str(exc),
                fallback=str(root / ".batho" / "plugins"),
            )
    return root / ".batho" / "plugins"


def _plugin_files_in_dir(directory: Path) -> list[Path]:
    return sorted(
        p
        for p in list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
        if p.is_file()
    )


def _validate_schema(path: Path) -> tuple[dict, bool]:
    """Stage 1: strict schema validation for one plugin file.

    Returns ``(result, gate_eligible)``. Gate eligibility is lenient
    validity, not strict validity — warnings (e.g. intra-plugin overlap
    hints) shouldn't block fixture testing; the gate's own checks decide
    acceptance. Re-validate non-strictly only when strict already failed.
    """
    from batho_plugin.rule_engine import validate_plugin_file

    result = validate_plugin_file(path, strict=True)
    lenient = (
        result
        if result.get("valid")
        else validate_plugin_file(path, strict=False)
    )
    return result, bool(lenient.get("valid"))


def _run_fixture_gates(
    pending: list[tuple[Path, dict]],
    root: Path,
    sample_size: int,
    selectivity_pct: float,
) -> None:
    """Stage 2: run the fixture gate for each gate-eligible result.

    The entity sample and builtin rule set are built once and shared across
    files — loading the artifact is the expensive step. Loader failures and
    per-file gate exceptions become gate errors instead of crashing the CLI.
    """
    from batho.modules.enrich import fixture_gate
    from batho.modules.enrich.fixture_gate import (
        load_gate_builtins,
        load_gate_sample_graph,
    )

    try:
        sample_graph, load_err = load_gate_sample_graph(root, sample_size)
    except Exception as exc:
        sample_graph, load_err = None, f"artifact load failed: {exc}"
    gate_builtins = load_gate_builtins(root) if load_err is None else None

    # ENR-06: compile every candidate's rules once so each file's gate also
    # checks conflicts against sibling candidates — not just builtins/self.
    sibling_rules: dict[Path, list] = {}
    if len(pending) > 1 and load_err is None:
        from batho.modules.enrich.fixture_gate import _candidate_rules_config
        from batho_plugin.rule_engine import load_effective_rules

        for path, _result in pending:
            try:
                cand_rules, _ = load_effective_rules(
                    _candidate_rules_config(path), root
                )
                sibling_rules[path] = cand_rules
            except Exception:
                sibling_rules[path] = []

    for path, result in pending:
        if load_err is not None:
            result["gate"] = {"passed": False, "errors": [load_err]}
            continue
        try:
            others = [
                r for p, rs in sibling_rules.items() if p != path for r in rs
            ]
            result["gate"] = fixture_gate(
                path,
                root,
                sample_size=sample_size,
                selectivity_pct=selectivity_pct,
                sample_graph=sample_graph,
                builtin_rules=gate_builtins,
                extra_candidate_rules=others,
            )
        except Exception as exc:
            result["gate"] = {
                "passed": False,
                "errors": [f"fixture gate error: {exc}"],
            }


def _print_validate_result(result: dict) -> None:
    status = "valid" if result.get("valid") else "invalid"
    print(f"{status}: {result.get('plugin_file')}")
    if result.get("schema_version"):
        print(f"schema_version: {result['schema_version']}")
    print(f"rules: {result.get('rule_count', 0)}")
    for warn in result.get("warnings", []):
        print(f"warning: {warn}")
    for err in result.get("errors", []):
        print(f"error: {err}")
    for conflict in result.get("conflict_warnings", []):
        print(f"conflict: {conflict}")
    if result.get("gate") is not None:
        _print_gate(result["gate"])


def _validate_result_ok(result: dict) -> bool:
    if not result.get("valid"):
        return False
    gate = result.get("gate")
    if gate is not None and not gate.get("passed"):
        return False
    return True


def _cmd_validate(args: argparse.Namespace) -> int:
    raw_root = getattr(args, "root", None) or Path(".")
    root = Path(raw_root).resolve()
    raw_path = getattr(args, "path", None)

    if raw_path is None:
        plugin_dir = _default_plugins_dir(root)
        targets = (
            _plugin_files_in_dir(plugin_dir) if plugin_dir.is_dir() else []
        )
        err = (
            None
            if targets
            else f"error: no plugin files (*.yaml/*.yml) in {plugin_dir}"
        )
    else:
        path = Path(raw_path).resolve()
        if path.is_dir():
            targets = _plugin_files_in_dir(path)
            err = (
                None
                if targets
                else f"error: no plugin files (*.yaml/*.yml) in directory: {path}"
            )
        else:
            targets = [path]
            err = None
    if err is not None:
        if getattr(args, "json", False):
            print(json.dumps({"valid": False, "errors": [err]}))
        else:
            print(err, file=sys.stderr)
        return 2

    sample_size = getattr(args, "entities_sample", 2000)
    selectivity = getattr(args, "selectivity", 10.0)

    # Stage 1 — strict schema validation for every file up front.
    # (`strict=True` already promotes warnings/conflicts to errors, so there
    # is no separate warnings-tolerant mode to gate behind a flag.)
    results: list[dict] = []
    pending_gate: list[tuple[Path, dict]] = []
    for target in targets:
        result, gate_eligible = _validate_schema(target)
        results.append(result)
        if gate_eligible:
            pending_gate.append((target, result))

    # Stage 2 — fixture gate, sharing one entity sample + builtin rule set.
    if pending_gate:
        _run_fixture_gates(pending_gate, root, sample_size, selectivity)

    all_ok = all(_validate_result_ok(r) for r in results)

    if getattr(args, "json", False):
        print(
            json.dumps(
                {"valid": all_ok, "files": results},
                indent=2,
                default=str,
            )
        )
    else:
        for result in results:
            _print_validate_result(result)
        if len(results) > 1:
            passed = sum(1 for r in results if _validate_result_ok(r))
            print(f"plugins: {passed}/{len(results)} passed")

    return 0 if all_ok else 1


def _print_gate(gate: dict) -> None:
    status = "PASS" if gate.get("passed") else "FAIL"
    print(
        f"fixture gate: {status}  (sample={gate.get('sample_size', '?')}, "
        f"selectivity<{gate.get('selectivity_pct', '?')}%)"
    )
    for r in gate.get("rules", []):
        mark = "ok" if r["verdict"] == "pass" else "FAIL"
        print(
            f"  [{mark}] {r['rule']}  hits={r['hits']} "
            f"({r['hit_pct']}%)  delta={r['delta_nonempty']}"
        )
        for reason in r.get("reasons", []):
            print(f"        - {reason}")
        for e in r.get("evidence", [])[:3]:
            print(f"        e.g. {e}")
    for e in gate.get("errors", []):
        print(f"  error: {e}")


def _yaml_head_meta(path: Path) -> dict[str, str]:
    """Cheap header scan of a rule YAML for list display (no full parse)."""
    meta: dict[str, str] = {}
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:2048]
    except OSError:
        return meta
    for key in ("plugin_id", "version", "class"):
        m = re.search(rf"^{key}:\s*([^\s#]+)", head, re.MULTILINE)
        if m:
            meta[key] = m.group(1).strip().strip("'\"")
    return meta


def _cmd_list(args: argparse.Namespace) -> int:
    """§8.1: show plugin class, type, stages, and version."""
    from batho.core.config.loader import get_config_cached, set_active_root
    from batho_plugin.rule_engine import (
        _discover_packaged_plugins,
        _plugin_alias,
        _resolve_custom_rules_path,
    )

    root = Path(args.root).resolve()
    set_active_root(root)
    cfg = get_config_cached()
    rules_cfg = cfg.get("rules", {}) or {}
    plugins_cfg = cfg.get("plugins", {}) or {}
    external_cfg = rules_cfg.get("plugins_external") or plugins_cfg.get(
        "external"
    ) or {}
    auto = rules_cfg.get("auto_load_all_plugins", True)
    builtins_cfg = {
        _plugin_alias(str(n).strip())
        for n in (rules_cfg.get("builtin_plugins", []) or [])
        if str(n).strip()
    }

    # Host-registered plugins (data + hooks + enabled external rule packs).
    print("host plugins:")
    try:
        from batho_plugin import load_host

        host = load_host(config=cfg)
        for reg in host.data_registrations():
            print(
                f"  {reg.plugin_id:<32} class={reg.plugin_class:<12} "
                f"type=data  stages=-  version={reg.version}"
            )
        for reg in host.hook_registrations():
            stages = ",".join(s.value for s in reg.plugin.stages)
            print(
                f"  {reg.plugin.plugin_id:<32} class={reg.plugin_class:<12} "
                f"type=hook  stages={stages}  version={reg.plugin.version}"
            )
        for reg in host.rule_registrations():
            print(
                f"  {reg.plugin_id:<32} class={reg.plugin_class:<12} "
                f"type=rule  stages=-  version={reg.version}"
            )
    except Exception as exc:
        print(f"  [host load failed: {exc}]")

    print("builtin plugins:")
    for plugin_name, path in sorted(
        _discover_packaged_plugins(external_cfg).items()
    ):
        loaded = auto or plugin_name in builtins_cfg
        meta = _yaml_head_meta(path)
        cls = meta.get("class", "standard")
        ver = meta.get("version", "?")
        print(
            f"  {plugin_name:<28} class={cls:<12} type=rule  "
            f"version={ver:<8} {path.as_posix()}  "
            f"[{'loaded' if loaded else 'off'}]"
        )

    print("custom plugins:")
    custom_path_value = rules_cfg.get("custom_rules_path")
    if custom_path_value:
        try:
            custom_path = _resolve_custom_rules_path(str(custom_path_value), root)
            print(f"  custom_file              {custom_path.as_posix()}")
        except Exception as exc:
            print(f"  custom_file              {custom_path_value}  [unresolvable: {exc}]")
    custom_dir_value = rules_cfg.get("custom_rules_dir")
    if custom_dir_value:
        try:
            custom_dir = _resolve_custom_rules_path(str(custom_dir_value), root)
        except Exception as exc:
            print(f"  custom_dir               {custom_dir_value}  [unresolvable: {exc}]")
        else:
            if custom_dir.is_dir():
                for p in sorted(custom_dir.glob("*.yaml")) + sorted(
                    custom_dir.glob("*.yml")
                ):
                    if p.is_file():
                        print(f"  custom_dir:{p.name:<18} {p.as_posix()}")
            else:
                print(f"  custom_dir               {custom_dir_value}  [missing]")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    from batho.orchestrator.plugins_apply import (
        PluginsApplyOptions,
        run_plugins_apply,
    )

    result = run_plugins_apply(
        PluginsApplyOptions(
            root=Path(args.root),
            plugin=args.plugin,
            plugins_only=args.plugins_only,
            dry_run=args.dry_run,
        )
    )

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "success": result.success,
                    "message": result.message,
                    "dry_run": result.dry_run,
                    "run_uuid": result.run_uuid,
                    "entities_updated": result.entities_updated,
                    "rules_applied": result.rules_applied,
                    "files_rewritten": result.files_rewritten,
                    "rule_hits": result.rule_hits,
                    "interception_totals": result.interception_totals,
                    "semantic_edges_added": result.semantic_edges_added,
                    "errors": result.errors,
                },
                indent=2,
                default=str,
            )
        )
        return 0 if result.success else 1

    if not result.success:
        print(f"error: {result.message}", file=sys.stderr)
        return 1

    prefix = "[dry-run] " if result.dry_run else ""
    print(f"{prefix}entities updated:  {result.entities_updated}")
    print(f"{prefix}rules applied:     {result.rules_applied}")
    print(f"{prefix}files rewritten:   {result.files_rewritten}")
    if result.semantic_edges_added:
        print(f"{prefix}edges derived:     {result.semantic_edges_added}")
    if result.rule_hits:
        top = sorted(result.rule_hits.items(), key=lambda kv: -kv[1])[:10]
        print(f"{prefix}rule hits:         {', '.join(f'{n}={c}' for n, c in top)}")
    if result.run_uuid:
        print(f"run: {result.run_uuid}")
    if result.message:
        print(result.message)
    return 0


__all__ = ["register_plugins_parser", "cmd_plugins"]
