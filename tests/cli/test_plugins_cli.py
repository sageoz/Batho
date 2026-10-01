"""
tests/cli/test_plugins_cli.py

Tests for `batho plugins` verb group (T07/T08):
  - validate: exit codes, --json contract, edge cases
  - list: builtin + custom discovery output
  - apply: orchestration result plumbing (unit-level; heavy path tested
    via orchestrator tests)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from textwrap import dedent

import pytest

from batho.cli.plugins import _cmd_apply, _cmd_list, _cmd_validate

VALID_PLUGIN = """\
schema_version: bsg-plugin.v2
plugin_id: test_p
name: Test P
version: 1.0.0
enabled: true
rules:
  - rule_id: r-p
    name: r-p
    severity: warning
    matchers:
      file_patterns: ["**/x.txt"]
    actions:
      add_usn_tags: [T]
"""

INVALID_PLUGIN = """\
schema_version: bsg-plugin.v2
plugin_id: test_p
name: Test P
rules:
  - rule_id: r-p
    name: r-p
    severity: warning
    matchers: {}
    actions:
      add_usn_tags: [T]
"""

# Hits the _seed_multi_artifact fixture (app/f0.py::func0) so the always-on
# fixture gate can pass stage 2.
HITTING_PLUGIN = """\
schema_version: bsg-plugin.v2
plugin_id: test_p
name: Test P
version: 1.0.0
enabled: true
rules:
  - rule_id: tag-func0
    name: tag-func0
    severity: info
    matchers:
      file_patterns: ["**/f0.py"]
      name_patterns: ["func0"]
    actions:
      metadata:
        bsg.domain: demo
"""


def _ns(**kw) -> argparse.Namespace:
    kw.setdefault("json", False)
    kw.setdefault("entities_sample", 2000)
    kw.setdefault("selectivity", 10.0)
    kw.setdefault("path", None)
    kw.setdefault("root", Path("."))
    return argparse.Namespace(**kw)


@pytest.fixture(autouse=True)
def _quiet_logs():
    """Route structlog to stderr (like the real entrypoint) so the always-on
    fixture gate's log lines don't pollute stdout/--json assertions."""
    from batho.utils.logging import configure_logging

    configure_logging(quiet=True)


class TestValidate:
    def test_valid_plugin_exit_0(self, tmp_path, capsys):
        from tests.cli.test_enrich_modules import _seed_multi_artifact

        _seed_multi_artifact(tmp_path)
        p = tmp_path / "p.yaml"
        p.write_text(HITTING_PLUGIN, encoding="utf-8")
        code = _cmd_validate(_ns(path=p, root=tmp_path))
        assert code == 0
        out = capsys.readouterr().out
        assert "valid" in out
        assert "fixture gate: PASS" in out

    def test_invalid_plugin_exit_nonzero(self, tmp_path, capsys):
        p = tmp_path / "bad.yaml"
        p.write_text(INVALID_PLUGIN, encoding="utf-8")
        code = _cmd_validate(_ns(path=p, root=tmp_path))
        assert code == 1
        out = capsys.readouterr().out
        assert "error" in out or "invalid" in out

    def test_json_output_parses(self, tmp_path, capsys):
        from tests.cli.test_enrich_modules import _seed_multi_artifact

        _seed_multi_artifact(tmp_path)
        p = tmp_path / "p.yaml"
        p.write_text(HITTING_PLUGIN, encoding="utf-8")
        capsys.readouterr()
        code = _cmd_validate(_ns(path=p, json=True, root=tmp_path))
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["valid"] is True
        assert len(data["files"]) == 1
        entry = data["files"][0]
        assert entry["valid"] is True
        assert "errors" in entry and "warnings" in entry
        assert entry["rule_count"] == 1
        assert entry["gate"]["passed"] is True

    def test_missing_file(self, tmp_path, capsys):
        p = tmp_path / "nope.yaml"
        code = _cmd_validate(_ns(path=p, root=tmp_path))
        assert code == 1

    def test_directory_validates_all_files(self, tmp_path, capsys):
        from tests.cli.test_enrich_modules import _seed_multi_artifact

        _seed_multi_artifact(tmp_path)
        pdir = tmp_path / "plugins"
        pdir.mkdir()
        (pdir / "a.yaml").write_text(HITTING_PLUGIN, encoding="utf-8")
        (pdir / "b.yaml").write_text(HITTING_PLUGIN, encoding="utf-8")
        code = _cmd_validate(_ns(path=pdir, root=tmp_path))
        out = capsys.readouterr().out
        assert code == 0
        assert "plugins: 2/2 passed" in out

    def test_empty_directory_errors(self, tmp_path, capsys):
        pdir = tmp_path / "plugins"
        pdir.mkdir()
        code = _cmd_validate(_ns(path=pdir, root=tmp_path))
        assert code == 2
        assert "no plugin files" in capsys.readouterr().err

    def test_no_path_defaults_to_plugins_dir(self, tmp_path, capsys):
        from tests.cli.test_enrich_modules import _seed_multi_artifact

        _seed_multi_artifact(tmp_path)
        pdir = tmp_path / ".batho" / "plugins"
        pdir.mkdir(parents=True)
        (pdir / "p.yaml").write_text(HITTING_PLUGIN, encoding="utf-8")
        code = _cmd_validate(_ns(path=None, root=tmp_path))
        out = capsys.readouterr().out
        assert code == 0
        assert "fixture gate: PASS" in out

    def test_no_path_missing_dir_errors(self, tmp_path, capsys):
        code = _cmd_validate(_ns(path=None, root=tmp_path))
        assert code == 2
        assert "no plugin files" in capsys.readouterr().err

    def test_gate_no_artifact_fails(self, tmp_path, capsys):
        p = tmp_path / "p.yaml"
        p.write_text(VALID_PLUGIN, encoding="utf-8")
        code = _cmd_validate(_ns(path=p, root=tmp_path))
        out = capsys.readouterr().out
        assert code == 1
        assert "fixture gate: FAIL" in out or "no artifact" in out

    def test_warnings_are_strict_errors(self, tmp_path, capsys):
        from tests.cli.test_enrich_modules import _seed_multi_artifact

        _seed_multi_artifact(tmp_path)
        # Two rules overlapping on **/f0.py writing different bsg.domain
        # values -> intra-plugin conflict. Strict validation promotes
        # warnings/conflicts to errors (rules.py:4221), so the file is
        # invalid — strict mode leaves no warnings-only middle ground;
        # the gate also fails the conflicting rules.
        conflict = HITTING_PLUGIN + """\
  - rule_id: tag-func0-alt
    name: tag-func0-alt
    severity: warning
    matchers:
      file_patterns: ["**/f0.py"]
      name_patterns: ["func0"]
    actions:
      metadata:
        bsg.domain: demo-alt
"""
        p = tmp_path / "conflict.yaml"
        p.write_text(conflict, encoding="utf-8")
        code = _cmd_validate(_ns(path=p, root=tmp_path))
        out = capsys.readouterr().out
        assert code == 1
        assert "conflict" in out or "invalid" in out


class TestList:
    def test_lists_builtin_and_custom(self, tmp_path, capsys):
        plugin_dir = tmp_path / ".batho" / "plugins"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "g.yaml").write_text(VALID_PLUGIN, encoding="utf-8")
        # minimal config so get_config_cached resolves with the dir
        (tmp_path / "batho.yaml").write_text(
            "rules:\n  custom_rules_dir: .batho/plugins\n", encoding="utf-8"
        )
        capsys.readouterr()
        code = _cmd_list(_ns(root=tmp_path))
        assert code == 0
        out = capsys.readouterr().out
        assert "builtin plugins:" in out
        assert "custom plugins:" in out
        assert "custom_dir:g.yaml" in out


class TestApplyCli:
    def test_missing_artifact_reports_error(self, tmp_path, capsys):
        code = _cmd_apply(
            _ns(
                root=tmp_path,
                plugin=None,
                plugins_only=False,
                dry_run=False,
                json=False,
            )
        )
        assert code == 1
        assert "build" in capsys.readouterr().err


class TestCrossFileConflicts:
    """ENR-06: directory-mode validate must detect candidate-vs-candidate
    write conflicts, not just candidate-vs-builtin."""

    CONFLICT_A = """\
schema_version: bsg-plugin.v2
plugin_id: conf_a
name: Conf A
version: 1.0.0
enabled: true
rules:
  - rule_id: dom-a
    name: dom-a
    severity: warning
    matchers:
      file_patterns: ["**/f0.py"]
      name_patterns: ["func0"]
    actions:
      metadata:
        bsg.domain: demo
"""

    CONFLICT_B = """\
schema_version: bsg-plugin.v2
plugin_id: conf_b
name: Conf B
version: 1.0.0
enabled: true
rules:
  - rule_id: dom-b
    name: dom-b
    severity: warning
    matchers:
      file_patterns: ["**/f0.py"]
      name_patterns: ["func0"]
    actions:
      metadata:
        bsg.domain: prod
"""

    def test_sibling_conflicts_fail_gate(self, tmp_path, capsys):
        """Two candidates writing different values to the same bsg.* key on
        the same scope must conflict — previously each only saw builtins."""
        from tests.cli.test_enrich_modules import _seed_multi_artifact

        _seed_multi_artifact(tmp_path)
        pdir = tmp_path / "plugins"
        pdir.mkdir()
        (pdir / "a.yaml").write_text(self.CONFLICT_A, encoding="utf-8")
        (pdir / "b.yaml").write_text(self.CONFLICT_B, encoding="utf-8")
        code = _cmd_validate(_ns(path=pdir, root=tmp_path))
        out = capsys.readouterr().out
        assert code != 0
        assert "conflict" in out

    def test_single_file_no_cross_noise(self, tmp_path, capsys):
        """A lone conflicting-pair member validates normally — the cross
        check only runs when siblings exist."""
        from tests.cli.test_enrich_modules import _seed_multi_artifact

        _seed_multi_artifact(tmp_path)
        p = tmp_path / "a.yaml"
        p.write_text(self.CONFLICT_A, encoding="utf-8")
        code = _cmd_validate(_ns(path=p, root=tmp_path))
        assert code == 0


class TestValidateCrossFileConflicts:
    """ENR-06: directory validation must catch conflicts between candidate
    files — the same metadata key written with different values under
    overlapping matchers must surface as a gate conflict on both files."""

    def _write(self, d: Path, name: str, rule_name: str, key: str, value):
        (d / f"{name}.yaml").write_text(dedent(f"""\
            schema_version: bsg-plugin.v2
            plugin_id: {name}
            name: {name}
            version: 1.0.0
            enabled: true
            rules:
              - rule_id: {rule_name}
                name: {rule_name}
                severity: info
                matchers:
                  file_patterns: ["**/*.tsx"]
                actions:
                  metadata:
                    {key}: "{value}"
            """))

    def test_same_key_different_value_conflicts(self, tmp_path):
        from batho.cli.plugins import _run_fixture_gates
        from tests.cli.test_enrich_modules import _seed_multi_artifact

        _seed_multi_artifact(tmp_path)
        d = tmp_path / "plugins"
        d.mkdir()
        self._write(d, "a", "rule_a", "bsg.domain", "checkout")
        self._write(d, "b", "rule_b", "bsg.domain", "auth")

        pending = [(d / "a.yaml", {"name": "a"}), (d / "b.yaml", {"name": "b"})]
        _run_fixture_gates(pending, tmp_path, 15, 30.0)
        # both files carry the cross-file conflict record + a per-rule reason
        for _path, result in pending:
            gate = result["gate"]
            conflicts = gate.get("candidate_conflicts", [])
            assert any(
                {c["rule_a"], c["rule_b"]} == {"rule_a", "rule_b"}
                and "bsg.domain" in c["overlap"]
                and "assigned different values" in c["overlap"]
                for c in conflicts
            ), f"expected cross-file conflict, got {gate}"
            assert any(
                "conflict" in reason and "bsg.domain" in reason
                for rule in gate["rules"] for reason in rule["reasons"]
            )

    def test_different_keys_no_conflict(self, tmp_path):
        from batho.cli.plugins import _run_fixture_gates
        from tests.cli.test_enrich_modules import _seed_multi_artifact

        _seed_multi_artifact(tmp_path)
        d = tmp_path / "plugins"
        d.mkdir()
        self._write(d, "a", "rule_a", "bsg.domain", "checkout")
        self._write(d, "b", "rule_b", "bsg.noise", "true")

        pending = [(d / "a.yaml", {}), (d / "b.yaml", {})]
        _run_fixture_gates(pending, tmp_path, 15, 30.0)
        for _path, result in pending:
            assert not result["gate"].get("candidate_conflicts"), (
                result["gate"]["candidate_conflicts"]
            )
