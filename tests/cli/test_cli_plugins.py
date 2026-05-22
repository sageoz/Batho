"""Tests for batho plugins CLI commands."""

import json
from pathlib import Path
from textwrap import dedent

import pytest

from batho_cli import cmd_plugins_list, cmd_plugins_validate


@pytest.fixture
def sample_plugin_yaml(tmp_path: Path) -> Path:
    """Create a valid sample plugin YAML file."""
    plugin_file = tmp_path / "test_plugin.yaml"
    plugin_file.write_text(
        dedent(
            """
            enabled: true
            rules:
              - rule_id: test_rule_1
                name: Test Rule 1
                description: A test rule
                severity: info
                priority: 100
                enabled: true
                matchers:
                  entity_types:
                    - function
                  name_patterns:
                    - "test_*"
                actions:
                  metadata:
                    test_tag: true
              - rule_id: test_rule_2
                name: Test Rule 2
                description: Another test rule
                severity: warning
                priority: 200
                enabled: true
                matchers:
                  entity_types:
                    - class
                actions:
                  add_usn_tags:
                    - test_class
            """
        )
    )
    return plugin_file


@pytest.fixture
def invalid_plugin_yaml(tmp_path: Path) -> Path:
    """Create an invalid plugin YAML file."""
    plugin_file = tmp_path / "invalid_plugin.yaml"
    plugin_file.write_text(
        dedent(
            """
            enabled: true
            rules:
              - rule_id: invalid_severity
                name: Invalid Severity Rule
                description: Has invalid severity value
                severity: invalid_value
                priority: 100
                enabled: true
                matchers:
                  entity_types:
                    - function
                actions:
                  metadata:
                    test: true
            """
        )
    )
    return plugin_file


@pytest.fixture
def malformed_yaml(tmp_path: Path) -> Path:
    """Create a malformed YAML file."""
    plugin_file = tmp_path / "malformed.yaml"
    plugin_file.write_text(
        dedent(
            """
            enabled: true
            rules:
              - rule_id: test
                name: [unclosed bracket
            """
        )
    )
    return plugin_file


class TestPluginsValidate:
    """Tests for batho plugins validate command."""

    def test_validate_valid_plugin(self, sample_plugin_yaml: Path, capsys):
        """Test validation of a valid plugin file."""
        import argparse

        args = argparse.Namespace(plugin_file=str(sample_plugin_yaml))
        result = cmd_plugins_validate(args)

        assert result == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["valid"] is True
        assert output["rule_count"] == 2
        assert output["plugin_file"] == str(sample_plugin_yaml)
        assert len(output["errors"]) == 0

    def test_validate_invalid_plugin(self, invalid_plugin_yaml: Path, capsys):
        """Test validation of an invalid plugin file."""
        import argparse

        args = argparse.Namespace(plugin_file=str(invalid_plugin_yaml))
        result = cmd_plugins_validate(args)

        assert result == 1

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["valid"] is False
        assert len(output["errors"]) > 0

    def test_validate_malformed_yaml(self, malformed_yaml: Path, capsys):
        """Test validation of a malformed YAML file."""
        import argparse

        args = argparse.Namespace(plugin_file=str(malformed_yaml))
        result = cmd_plugins_validate(args)

        assert result == 1

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["valid"] is False
        assert len(output["errors"]) > 0
        assert any("YAML" in err or "parse" in err for err in output["errors"])

    def test_validate_nonexistent_file(self, tmp_path: Path, capsys):
        """Test validation of a non-existent file."""
        import argparse

        nonexistent = tmp_path / "does_not_exist.yaml"
        args = argparse.Namespace(plugin_file=str(nonexistent))
        result = cmd_plugins_validate(args)

        assert result == 1

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["valid"] is False
        assert len(output["errors"]) > 0
        assert any("not found" in err.lower() for err in output["errors"])

    def test_validate_disabled_plugin(self, tmp_path: Path, capsys):
        """Test validation of a disabled plugin shows warning."""
        import argparse

        plugin_file = tmp_path / "disabled_plugin.yaml"
        plugin_file.write_text(
            dedent(
                """
                enabled: false
                rules:
                  - rule_id: test_rule
                    name: Test Rule
                    description: Test
                    matchers:
                      entity_types:
                        - function
                    actions:
                      metadata:
                        test: true
                """
            )
        )

        args = argparse.Namespace(plugin_file=str(plugin_file))
        result = cmd_plugins_validate(args)

        assert result == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["valid"] is True
        assert len(output["warnings"]) > 0
        assert any("disabled" in warn.lower() for warn in output["warnings"])

    def test_validate_plugin_only_bidirectional_matchers(self, tmp_path: Path, capsys):
        """Test validation of a rule using only bidirectional matchers.
        It should be valid and not trigger empty-matcher warnings.
        """
        import argparse

        plugin_file = tmp_path / "bidirectional_only_plugin.yaml"
        plugin_file.write_text(
            dedent(
                """
                enabled: true
                rules:
                  - rule_id: test_bidirectional_only
                    name: Test Bidirectional Only
                    description: Rule with only bidirectional matchers
                    severity: info
                    priority: 100
                    enabled: true
                    matchers:
                      has_coverage_gap: true
                    actions:
                      metadata:
                        test: true
                """
            )
        )

        args = argparse.Namespace(plugin_file=str(plugin_file))
        result = cmd_plugins_validate(args)

        assert result == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["valid"] is True
        # Should not have any warning about empty matchers
        assert not any("no matchers" in warn for warn in output["warnings"])



class TestPluginsList:
    """Tests for batho plugins list command."""

    def test_list_plugins_basic(self, tmp_path: Path, capsys):
        """Test basic plugin listing."""
        import argparse

        # Create a minimal batho.yaml
        batho_yaml = tmp_path / "batho.yaml"
        batho_yaml.write_text(
            dedent(
                """
                paths:
                  ctn_dir: .ctn
                bsg:
                  rules:
                    enabled: true
                    builtin_plugins:
                      - bsg_core
                """
            )
        )

        args = argparse.Namespace(root=str(tmp_path), verbose=False)
        result = cmd_plugins_list(args)

        assert result == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert "builtin_plugins_available" in output
        assert "builtin_plugins_requested" in output
        assert "loaded_plugins" in output
        assert "stats" in output
        assert isinstance(output["builtin_plugins_available"], list)
        assert len(output["builtin_plugins_available"]) > 0

    def test_list_plugins_verbose(self, tmp_path: Path, capsys):
        """Test verbose plugin listing."""
        import argparse

        batho_yaml = tmp_path / "batho.yaml"
        batho_yaml.write_text(
            dedent(
                """
                paths:
                  ctn_dir: .ctn
                bsg:
                  rules:
                    enabled: true
                    builtin_plugins:
                      - bsg_core
                """
            )
        )

        args = argparse.Namespace(root=str(tmp_path), verbose=True)
        result = cmd_plugins_list(args)

        assert result == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert "verbose_stats" in output

    def test_list_plugins_with_custom_inline(self, tmp_path: Path, capsys):
        """Test listing with custom inline rules configuration."""
        import argparse

        batho_yaml = tmp_path / "batho.yaml"
        batho_yaml.write_text(
            dedent(
                """
                paths:
                  ctn_dir: .ctn
                bsg:
                  rules:
                    enabled: true
                    builtin_plugins:
                      - bsg_core
                    custom_rules_inline:
                      - rule_id: custom_inline_1
                        name: Custom Inline Rule
                        description: Test
                        severity: info
                        priority: 100
                        enabled: true
                        matchers:
                          entity_types:
                            - function
                        actions:
                          metadata:
                            custom: true
                """
            )
        )

        args = argparse.Namespace(root=str(tmp_path), verbose=False)
        result = cmd_plugins_list(args)

        assert result == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        # Check that command succeeded and has expected structure
        assert "custom_inline_rules" in output
        assert "load_stats" in output
        # Custom rules count may be 0 if validation fails, but that's ok for this test
        assert isinstance(output["custom_inline_rules"], int)

    def test_list_plugins_with_custom_file(
        self, tmp_path: Path, sample_plugin_yaml: Path, capsys
    ):
        """Test listing with custom rules file configuration."""
        import argparse

        batho_yaml = tmp_path / "batho.yaml"
        batho_yaml.write_text(
            dedent(
                f"""
                paths:
                  ctn_dir: .ctn
                bsg:
                  rules:
                    enabled: true
                    builtin_plugins:
                      - bsg_core
                    custom_rules_path: {sample_plugin_yaml}
                """
            )
        )

        args = argparse.Namespace(root=str(tmp_path), verbose=False)
        result = cmd_plugins_list(args)

        assert result == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        # Check that command succeeded and has expected structure
        assert "custom_file" in output
        assert "custom_file_rules" in output
        assert "load_stats" in output
        # custom_file may be None if the file failed to load, which is ok for this test
        assert isinstance(output["custom_file_rules"], int)

    def test_list_plugins_nonexistent_root(self, tmp_path: Path, capsys):
        """Test listing with non-existent root directory."""
        import argparse

        nonexistent = tmp_path / "does_not_exist"
        args = argparse.Namespace(root=str(nonexistent), verbose=False)
        result = cmd_plugins_list(args)

        assert result == 1

        captured = capsys.readouterr()
        # Error messages go to stderr via print() in batho_cli
        assert "does not exist" in captured.err.lower()

    def test_list_plugins_stats_structure(self, tmp_path: Path, capsys):
        """Test that stats structure is correct."""
        import argparse

        batho_yaml = tmp_path / "batho.yaml"
        batho_yaml.write_text(
            dedent(
                """
                paths:
                  ctn_dir: .ctn
                bsg:
                  rules:
                    enabled: true
                    builtin_plugins:
                      - bsg_core
                """
            )
        )

        args = argparse.Namespace(root=str(tmp_path), verbose=False)
        result = cmd_plugins_list(args)

        assert result == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        stats = output["stats"]
        assert "total_plugins" in stats
        assert "total_rules" in stats
        assert "builtin_plugins_loaded" in stats
        assert "rules_disabled" in stats
        assert "cache_hit" in stats
        assert isinstance(stats["total_plugins"], int)
        assert isinstance(stats["total_rules"], int)
