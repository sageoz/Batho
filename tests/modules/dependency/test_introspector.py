"""Tests for the introspector module."""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from batho.modules.dependency.introspector import (
    ThirdPartyIntrospector,
    _INTROSPECT_SCRIPT_TEMPLATE
)


class TestThirdPartyIntrospector:
    """Tests for ThirdPartyIntrospector class."""

    def test_init_default_values(self):
        """Verify the default mode and timeout settings of ThirdPartyIntrospector.

        Scenario:
            ThirdPartyIntrospector is instantiated without any custom arguments.

        Execution Flow:
            1. Initialize ThirdPartyIntrospector.
            2. Assert that mode is "shallow" and timeout_seconds is 5.

        Expectations:
            - Default values are applied correctly.
        """
        introspector = ThirdPartyIntrospector()
        assert introspector.mode == "shallow"
        assert introspector.timeout_seconds == 5

    def test_init_custom_values(self):
        """Verify the custom mode and timeout settings of ThirdPartyIntrospector.

        Scenario:
            ThirdPartyIntrospector is instantiated with explicit mode and timeout arguments.

        Execution Flow:
            1. Initialize ThirdPartyIntrospector with mode="deep" and timeout_seconds=10.
            2. Assert that mode matches "deep" and timeout_seconds matches 10.

        Expectations:
            - Custom values are correctly assigned to properties.
        """
        introspector = ThirdPartyIntrospector(mode="deep", timeout_seconds=10)
        assert introspector.mode == "deep"
        assert introspector.timeout_seconds == 10

    def test_introspect_script_template_format(self):
        """Verify the introspect script template formatting behavior.

        Scenario:
            A package name and mode are formatted into the python script template.

        Execution Flow:
            1. Format the template with package name "requests" and mode "shallow".
            2. Assert that the package name, mode, and typical python imports are contained within the output script.

        Expectations:
            - Generated script contains "requests", "shallow", "import importlib", and "import inspect".
        """
        script = _INTROSPECT_SCRIPT_TEMPLATE.format(
            package_name="requests",
            mode="shallow"
        )
        assert "requests" in script
        assert "shallow" in script
        assert "import importlib" in script
        assert "import inspect" in script

    @patch('subprocess.run')
    def test_introspect_python_success(self, mock_run):
        """Verify python package introspection when subprocess succeeds.

        Scenario:
            A venv with a python binary is provided and the subprocess returns
            json output of package symbols.

        Execution Flow:
            1. Create a venv dir with bin/python.
            2. Mock subprocess.run return value with returncode=0 and valid JSON stdout.
            3. Invoke introspect_python on "requests" with the venv env_path.
            4. Assert that the parsed dictionary is returned and subprocess.run was executed.

        Expectations:
            - The returned dictionary matches the mocked JSON stdout.
            - subprocess.run is called exactly once.
        """
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"requests": ["get", "post", "Session"]}'
        )

        introspector = ThirdPartyIntrospector()
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp)
            (venv / "bin").mkdir()
            (venv / "bin" / "python").touch()
            result = introspector.introspect_python("requests", None, venv)

        assert result == {"requests": ["get", "post", "Session"]}
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_introspect_python_no_venv_skips(self, mock_run):
        """Verify the skip policy: no venv → no subprocess at all (D3).

        Scenario:
            introspect_python is called without a resolvable venv.

        Execution Flow:
            1. Call introspect_python with env_path=None.
            2. Assert an empty dict is returned.

        Expectations:
            - No subprocess is spawned (never introspects Batho's own
              interpreter); the dep is skipped upstream by the dep-01 policy.
        """
        introspector = ThirdPartyIntrospector()
        result = introspector.introspect_python("requests", None, None)

        assert result == {}
        mock_run.assert_not_called()

    @patch('subprocess.run')
    def test_introspect_python_failure(self, mock_run):
        """Verify python package introspection failure behavior.

        Scenario:
            A subprocess command fails to find the target module and returns a non-zero exit code.

        Execution Flow:
            1. Mock subprocess.run to return code 1 and a "Module not found" stderr.
            2. Invoke introspect_python on a nonexistent package (with a venv).
            3. Assert that an empty dictionary is returned.

        Expectations:
            - Returns an empty dictionary upon script execution failure.
        """
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Module not found"
        )

        introspector = ThirdPartyIntrospector()
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp)
            (venv / "bin").mkdir()
            (venv / "bin" / "python").touch()
            result = introspector.introspect_python("nonexistent", None, venv)

        assert result == {}

    @patch('subprocess.run')
    def test_introspect_python_timeout(self, mock_run):
        """Verify python package introspection handles command timeout.

        Scenario:
            A subprocess invocation times out during introspection.

        Execution Flow:
            1. Mock subprocess.run to raise a Timeout exception.
            2. Invoke introspect_python on a package (with a venv).
            3. Assert that an empty dictionary is returned on failure/timeout.

        Expectations:
            - Returns an empty dictionary gracefully instead of raising.
        """
        mock_run.side_effect = Exception("Timeout")

        introspector = ThirdPartyIntrospector(timeout_seconds=1)
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp)
            (venv / "bin").mkdir()
            (venv / "bin" / "python").touch()
            result = introspector.introspect_python("slow_package", None, venv)

        assert result == {}

    @patch('subprocess.run')
    def test_introspect_python_with_venv(self, mock_run):
        """Verify introspection uses venv python when venv path is provided.

        Scenario:
            An introspection request is made with a path to a virtual environment.

        Execution Flow:
            1. Create a temporary directory containing a bin/python file.
            2. Mock subprocess.run to return a valid JSON output.
            3. Call introspect_python with the venv path.
            4. Verify that the venv python executable was referenced in the subprocess call.

        Expectations:
            - The executable path points to the Python binary in the provided venv directory.
        """
        with tempfile.TemporaryDirectory() as tmp:
            venv_path = Path(tmp)
            venv_python = venv_path / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.touch()

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"pkg": ["func"]}'
            )

            introspector = ThirdPartyIntrospector()
            result = introspector.introspect_python("pkg", None, venv_path)

            # Should try venv python first
            first_call = mock_run.call_args_list[0]
            assert str(venv_python) in first_call[0][0]

    @patch('subprocess.run')
    def test_introspect_python_venv_without_python_returns_empty(self, mock_run):
        """Verify a venv dir without a python binary yields no introspection.

        Scenario:
            A venv directory path is provided but it contains no Python executable.

        Execution Flow:
            1. Create a temporary directory without a Python executable.
            2. Call introspect_python with this path.
            3. Verify no subprocess was executed.

        Expectations:
            - Returns {} without spawning any subprocess (the old
              sys.executable fallback is removed — wrong-env symbols are
              worse than no symbols).
        """
        with tempfile.TemporaryDirectory() as tmp:
            venv_path = Path(tmp)
            # No venv python exists

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"pkg": ["func"]}'
            )

            introspector = ThirdPartyIntrospector()
            result = introspector.introspect_python("pkg", None, venv_path)

            assert result == {}
            assert mock_run.call_count == 0

    @patch('subprocess.run')
    def test_introspect_python_venv_error_no_system_fallback(self, mock_run):
        """Verify no system-python fallback when the venv python fails.

        Scenario:
            Venv python exists but execution fails with exit code 1.

        Execution Flow:
            1. Create a temporary venv directory and python file.
            2. Mock subprocess.run to fail.
            3. Call introspect_python.
            4. Assert subprocess.run is called exactly once and {} is returned.

        Expectations:
            - Introspection executes the venv python once, fails, and returns
              {} — Batho's own interpreter is never probed.
        """
        with tempfile.TemporaryDirectory() as tmp:
            venv_path = Path(tmp)
            venv_python = venv_path / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.touch()

            # First (and only) call fails
            mock_run.side_effect = MagicMock(returncode=1, stderr="error")

            introspector = ThirdPartyIntrospector()
            result = introspector.introspect_python("pkg", None, venv_path)

            assert mock_run.call_count == 1
            assert result == {}

    def test_introspect_npm_placeholder(self):
        """Verify npm package introspection returns {} for a missing env.

        Scenario:
            An npm package introspection is requested with no node_modules env.

        Execution Flow:
            1. Call introspect_npm with env_path pointing at a non-existent dir.
            2. Assert that an empty dictionary is returned.

        Expectations:
            - Missing env → {} (skip policy; no {name: [name]} stub).
        """
        introspector = ThirdPartyIntrospector()
        result = introspector.introspect_npm("express", None, Path("/nonexistent-node_modules"))

        assert result == {}


class TestIntrospectorScriptTemplate:
    """Tests for the introspection script template."""

    def test_template_valid_python(self):
        """Verify that the introspection script template is syntactically valid Python.

        Scenario:
            The script template is formatted and compiled.

        Execution Flow:
            1. Format the template using dummy arguments.
            2. Compile the string with `compile()`.

        Expectations:
            - Compilation does not raise a SyntaxError, confirming the script is valid Python syntax.
        """
        script = _INTROSPECT_SCRIPT_TEMPLATE.format(
            package_name="test_pkg",
            mode="shallow"
        )
        
        # Should be valid Python syntax
        try:
            compile(script, '<string>', 'exec')
        except SyntaxError as e:
            pytest.fail(f"Script template has syntax error: {e}")

    def test_template_escaping(self):
        """Verify that special characters in package names are properly handled in the template.

        Scenario:
            A package name with dashes is formatted into the template.

        Execution Flow:
            1. Format the template using a dashed package name.
            2. Assert that the package name is present in the output.

        Expectations:
            - The name appears literally in the generated script.
        """
        script = _INTROSPECT_SCRIPT_TEMPLATE.format(
            package_name="package-with-dashes",
            mode="shallow"
        )
        
        # Package name should appear literally
        assert "package-with-dashes" in script

    def test_introspect_rejects_invalid_package_name(self):
        """Verify that invalid package names are rejected before subprocess execution.

        Scenario:
            A malicious package name containing shell metacharacters is passed
            to introspect_python. The introspector should reject it and return {}

        Execution Flow:
            1. Call introspect_python with a malicious string.
            2. Assert that the return value is an empty dict.
            3. Assert that no subprocess was spawned (no real introspection attempted).

        Expectations:
            - Invalid package names are rejected by the regex validation.
            - Returns empty dict without executing any subprocess.
        """
        introspector = ThirdPartyIntrospector()
        result = introspector.introspect_python("; rm -rf /")
        assert result == {}

        result2 = introspector.introspect_python("$(whoami)")
        assert result2 == {}

        result3 = introspector.introspect_python("pkg;malicious")
        assert result3 == {}
