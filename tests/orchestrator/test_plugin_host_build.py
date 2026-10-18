"""tests/orchestrator/test_plugin_host_build.py — T22: orchestrator integration.

Build with/without the plugin host; artifacts carry the plugin fingerprint,
metadata schema, and hook telemetry (spec §6.5). Uses a tiny fixture repo so
builds stay fast.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.orchestrator.build import BuildOptions, run_build


@pytest.fixture()
def tiny_repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "mod.py").write_text(
        '"""Tiny module."""\n\n'
        "def greet(name: str) -> str:\n"
        '    """Say hello."""\n'
        '    return f"hello {name}"\n'
        "\n"
        "# WHY: keep the builtin references — they exercise the stub-prune path\n"
        "alias_print = print\n"
        "size_of = len\n"
    )
    return tmp_path


def _latest_artifacts(root: Path) -> dict:
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle

    bundle = BathoBundle(root)
    # get_run_artifacts falls back to the latest run for unresolvable ids.
    return bundle.get_run_artifacts(0) or {}


def test_build_carries_plugin_fingerprint(tiny_repo: Path) -> None:
    """Default build: host loads, telemetry carries plugin provenance."""
    result = run_build(BuildOptions(root=tiny_repo, force_full=True))
    assert result.success, result.warnings

    artifacts = _latest_artifacts(tiny_repo)
    telemetry = artifacts.get("telemetry_metrics") or {}
    fingerprint = telemetry.get("plugin_fingerprint")
    assert fingerprint, "plugin_fingerprint missing from run artifacts"
    assert len(fingerprint) == 64  # sha256 hex
    assert telemetry.get("metadata_schema") == "batho-meta.v2"
    hook_telemetry = telemetry.get("hook_telemetry")
    assert isinstance(hook_telemetry, dict)
    assert hook_telemetry.get("schema_version") == "plugin-telemetry.v1"


def test_build_no_plugins_fallback(tiny_repo: Path) -> None:
    """--no-plugins: build succeeds with fallbacks; fingerprint is None."""
    result = run_build(BuildOptions(root=tiny_repo, force_full=True, no_plugins=True))
    assert result.success, result.warnings

    artifacts = _latest_artifacts(tiny_repo)
    telemetry = artifacts.get("telemetry_metrics") or {}
    assert telemetry.get("plugin_fingerprint") is None
    assert telemetry.get("hook_telemetry") is None
    assert telemetry.get("metadata_schema") == "batho-meta.v2"


def test_build_fingerprint_changes_with_pack_state(tiny_repo: Path) -> None:
    """Plugins-enabled and no-plugins builds produce different fingerprints."""
    with_plugins = run_build(BuildOptions(root=tiny_repo, force_full=True))
    assert with_plugins.success
    fp_with = _latest_artifacts(tiny_repo)["telemetry_metrics"]["plugin_fingerprint"]

    without = run_build(BuildOptions(root=tiny_repo, force_full=True, no_plugins=True))
    assert without.success
    fp_without = _latest_artifacts(tiny_repo)["telemetry_metrics"]["plugin_fingerprint"]

    assert fp_with != fp_without


def test_empty_host_reads_as_absent() -> None:
    """The --no-plugins empty host must read as 'no host' so engine call
    sites take their compiled-in fallbacks instead of empty pack data."""
    from batho_plugin import load_host
    from batho_plugin.runtime import get_active_plugin_host, set_active_plugin_host

    try:
        set_active_plugin_host(load_host(no_plugins=True))
        assert get_active_plugin_host() is None
    finally:
        set_active_plugin_host(None)


def test_no_plugins_entity_set_parity(tiny_repo: Path) -> None:
    """Plugins-on and --no-plugins builds produce the same entity/rel sets —
    plugin stamps may differ, but the extraction population must not."""
    from batho.modules.storage.arrow_bundle import get_bundle

    def _entity_keyset(root: Path, run_id: str) -> set[tuple]:
        db = get_bundle(root)
        arts = db.get_file_artifacts(db.get_run_internal_id(run_id))
        return {
            (e.get("name"), e.get("type"), e.get("file"))
            for a in arts
            for e in (a.get("graph") or {}).get("entities") or []
        }

    with_plugins = run_build(BuildOptions(root=tiny_repo, force_full=True))
    assert with_plugins.success, with_plugins.warnings
    keyset_with = _entity_keyset(tiny_repo, with_plugins.run_id)

    without = run_build(
        BuildOptions(root=tiny_repo, force_full=True, no_plugins=True)
    )
    assert without.success, without.warnings
    keyset_without = _entity_keyset(tiny_repo, without.run_id)

    assert keyset_without == keyset_with
    assert without.entity_count == with_plugins.entity_count
    assert without.relationship_count == with_plugins.relationship_count


def test_host_init_overhead_is_small(tiny_repo: Path) -> None:
    """Host init < 100 ms (T22 perf gate)."""
    import time

    from batho_plugin import load_host

    t0 = time.perf_counter()
    host = load_host()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert host is not None
    assert elapsed_ms < 100.0, f"host init took {elapsed_ms:.1f} ms"
