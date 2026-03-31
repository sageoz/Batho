"""
Python LSP Adapter using Pyright.
"""

import json
import tomllib
from typing import Any, Dict, List, Optional
from pathlib import Path

from batho_core.utils.logging import get_logger
from batho_core.context.lsp.adapters.base import LSPAdapter, ProjectConfig

logger = get_logger(__name__, component="python_adapter")

class PythonAdapter(LSPAdapter):
    """Adapter for Python via Pyright."""

    def get_initialize_options(self, project_root: str) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "typeCheckingMode": "strict",
        }
        
        # Detect virtual environment
        venv_path = self._detect_venv(project_root)
        if venv_path:
            options["venvPath"] = str(Path(venv_path).parent)
            options["venv"] = Path(venv_path).name
            
        return options

    def _detect_venv(self, project_root: str) -> Optional[str]:
        """Detect virtual environment in common locations."""
        common_names = [".venv", "venv", "env"]
        root = Path(project_root)
        for name in common_names:
            v_dir = root / name
            if v_dir.is_dir():
                return str(v_dir)
        return None

    def parse_project_config(self, project_root: str) -> ProjectConfig:
        root = Path(project_root)
        files = []
        
        # Parse pyrightconfig.json
        pyright_config = root / "pyrightconfig.json"
        if pyright_config.exists():
            files.append("pyrightconfig.json")
            try:
                # Basic check to ensure valid JSON (ignore errors for simple implementation)
                with open(pyright_config, "r", encoding="utf-8") as f:
                    json.load(f)
            except Exception as e:
                logger.warning("invalid_pyrightconfig", error=str(e))
                
        # Parse pyproject.toml
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            files.append("pyproject.toml")
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                    # We just log it for now, in a real implementation we might merge them
                    if "tool" in data and "pyright" in data["tool"]:
                        logger.debug("found_pyright_in_pyproject")
            except Exception as e:
                logger.warning("invalid_pyproject_toml", error=str(e))
                
        return ProjectConfig(root=project_root, files=files)

    def adapt_uri(self, uri: str) -> str:
        return uri

    def adapt_response(self, method: str, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        """Adapt LSP response."""
        if method == "textDocument/hover" and "contents" in raw_response:
            contents = raw_response["contents"]
            if isinstance(contents, dict) and "value" in contents:
                raw_response["contents"]["value"] = self.extract_type_info(contents["value"]) or contents["value"]
            elif isinstance(contents, str):
                raw_response["contents"] = self.extract_type_info(contents) or contents
        return raw_response

    def extract_type_info(self, hover_content: str) -> Optional[str]:
        """Extract clean type signature from Pyright hover markdown."""
        lines = hover_content.splitlines()
        in_code_block = False
        code_lines = []
        for line in lines:
            if line.startswith("```"):
                if in_code_block:
                    break
                in_code_block = True
                continue
            if in_code_block:
                code_lines.append(line)
                
        if code_lines:
            return "\n".join(code_lines).strip()
        return None

    def extract_call_chain_info(self, refs_response: List[Dict[str, Any]]) -> List[str]:
        """Extract calling functions/methods."""
        calls = []
        for ref in refs_response:
            if "uri" in ref:
                calls.append(ref["uri"])
        # Return unique references
        return list(set(calls))

    def get_file_patterns(self) -> List[str]:
        return ["*.py", "*.pyi"]
