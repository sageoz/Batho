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
        introspector = ThirdPartyIntrospector()
        assert introspector.mode == "shallow"
        assert introspector.timeout_seconds == 5

    def test_init_custom_values(self):
        introspector = ThirdPartyIntrospector(mode="deep", timeout_seconds=10)
        assert introspector.mode == "deep"
        assert introspector.timeout_seconds == 10

    def test_introspect_script_template_format(self):
        """Test that the script template formats correctly."""
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
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"requests": ["get", "post", "Session"]}'
        )
        
        introspector = ThirdPartyIntrospector()
        result = introspector.introspect_python("requests", None)
        
        assert result == {"requests": ["get", "post", "Session"]}
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_introspect_python_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Module not found"
        )
        
        introspector = ThirdPartyIntrospector()
        result = introspector.introspect_python("nonexistent", None)
        
        assert result == {}

    @patch('subprocess.run')
    def test_introspect_python_timeout(self, mock_run):
        mock_run.side_effect = Exception("Timeout")
        
        introspector = ThirdPartyIntrospector(timeout_seconds=1)
        result = introspector.introspect_python("slow_package", None)
        
        assert result == {}

    @patch('subprocess.run')
    def test_introspect_python_with_venv(self, mock_run):
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
            result = introspector.introspect_python("pkg", venv_path)
            
            # Should try venv python first
            first_call = mock_run.call_args_list[0]
            assert str(venv_python) in first_call[0][0]

    @patch('subprocess.run')
    def test_introspect_python_fallback_to_system(self, mock_run):
        with tempfile.TemporaryDirectory() as tmp:
            venv_path = Path(tmp)
            # No venv python exists
            
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"pkg": ["func"]}'
            )
            
            introspector = ThirdPartyIntrospector()
            result = introspector.introspect_python("pkg", venv_path)
            
            # Should fall back to system python
            assert mock_run.call_count == 1

    @patch('subprocess.run')
    def test_introspect_python_venv_fallback_on_error(self, mock_run):
        with tempfile.TemporaryDirectory() as tmp:
            venv_path = Path(tmp)
            venv_python = venv_path / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.touch()
            
            # First call (venv) fails, second call (system) succeeds
            mock_run.side_effect = [
                MagicMock(returncode=1, stderr="error"),
                MagicMock(returncode=0, stdout='{"pkg": ["func"]}')
            ]
            
            introspector = ThirdPartyIntrospector()
            result = introspector.introspect_python("pkg", venv_path)
            
            assert mock_run.call_count == 2
            assert result == {"pkg": ["func"]}

    def test_introspect_npm_placeholder(self):
        introspector = ThirdPartyIntrospector()
        result = introspector.introspect_npm("express", Path("/tmp/node_modules"))
        
        # Currently returns empty dict as placeholder
        assert result == {}


class TestIntrospectorScriptTemplate:
    """Tests for the introspection script template."""

    def test_template_valid_python(self):
        """Verify the template generates valid Python code."""
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
        """Test that special characters in package names are handled."""
        script = _INTROSPECT_SCRIPT_TEMPLATE.format(
            package_name="package-with-dashes",
            mode="shallow"
        )
        
        # Package name should appear literally
        assert "package-with-dashes" in script
