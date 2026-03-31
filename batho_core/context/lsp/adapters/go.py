"""
Go LSP Adapter using gopls.
"""

import re
from typing import Any, Dict, List, Optional
from pathlib import Path

from batho_core.utils.logging import get_logger
from batho_core.context.lsp.adapters.base import LSPAdapter, ProjectConfig

logger = get_logger(__name__, component="go_adapter")

class GoAdapter(LSPAdapter):
    """Adapter for Go via gopls."""

    def get_initialize_options(self, project_root: str) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "analyses": {
                "unusedparams": True,
            },
            "staticcheck": True,
            "vulncheck": "Imports",
        }
        
        # Determine module name for "local" import path config
        mod_name = self._get_module_name(project_root)
        if mod_name:
            options["local"] = mod_name
            
        return options

    def _get_module_name(self, project_root: str) -> Optional[str]:
        root = Path(project_root)
        mod_file = root / "go.mod"
        if mod_file.exists():
            try:
                content = mod_file.read_text(encoding="utf-8")
                match = re.search(r"^module\s+([^\s]+)", content, re.MULTILINE)
                if match:
                    return match.group(1)
            except Exception:
                pass
        return None

    def parse_project_config(self, project_root: str) -> ProjectConfig:
        root = Path(project_root)
        files = []
        
        if (root / "go.mod").exists():
            files.append("go.mod")
        if (root / "go.sum").exists():
            files.append("go.sum")
            
        return ProjectConfig(root=project_root, files=files)

    def adapt_uri(self, uri: str) -> str:
        return uri

    def adapt_response(self, method: str, raw_response: Any) -> Any:
        """Adapt LSP response for Go."""
        if method == "textDocument/hover" and isinstance(raw_response, dict):
            contents = raw_response.get("contents")
            if isinstance(contents, dict) and "value" in contents:
                raw_response["contents"]["value"] = self.extract_type_info(contents["value"]) or contents["value"]
            elif isinstance(contents, str):
                raw_response["contents"] = self.extract_type_info(contents) or contents
        return raw_response

    def extract_type_info(self, hover_content: str) -> Optional[str]:
        """Extract type signature from gopls hover content."""
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

    def get_file_patterns(self) -> List[str]:
        return ["*.go"]
