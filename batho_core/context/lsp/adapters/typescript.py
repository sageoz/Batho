"""
TypeScript LSP Adapter using TSServer.
"""

import json
import re
from typing import Any, Dict, List
from pathlib import Path

from batho_core.utils.logging import get_logger
from batho_core.context.lsp.adapters.base import LSPAdapter, ProjectConfig

logger = get_logger(__name__, component="typescript_adapter")

class TypeScriptAdapter(LSPAdapter):
    """Adapter for TypeScript/JS via TSServer."""

    def get_initialize_options(self, project_root: str) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "preferences": {
                "importModuleSpecifier": "non-relative"
            }
        }
        return options

    def _strip_json_comments(self, content: str) -> str:
        """Strip // and /* */ comments from JSON."""
        # Simple regex to strip comments, doesn't handle comments inside strings perfectly
        content = re.sub(r'//.*', '', content)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        return content

    def parse_project_config(self, project_root: str) -> ProjectConfig:
        root = Path(project_root)
        files = []
        
        # Parse tsconfig.json
        tsconfig = root / "tsconfig.json"
        if tsconfig.exists():
            files.append("tsconfig.json")
            try:
                with open(tsconfig, "r", encoding="utf-8") as f:
                    content = self._strip_json_comments(f.read())
                    data = json.loads(content)
                    if "compilerOptions" in data and "paths" in data["compilerOptions"]:
                        logger.debug("found_path_aliases", count=len(data["compilerOptions"]["paths"]))
            except Exception as e:
                logger.warning("invalid_tsconfig", error=str(e))
                
        # Parse package.json
        package_json = root / "package.json"
        if package_json.exists():
            files.append("package.json")
            
        return ProjectConfig(root=project_root, files=files)

    def adapt_uri(self, uri: str) -> str:
        return uri

    def adapt_response(self, method: str, raw_response: Any) -> Any:
        """Adapt LSP response."""
        if method == "textDocument/definition":
            # Normalize LocationLink to Location if present
            if isinstance(raw_response, list):
                for item in raw_response:
                    if "targetUri" in item and "uri" not in item:
                        item["uri"] = item.pop("targetUri")
                    if "targetRange" in item and "range" not in item:
                        item["range"] = item.pop("targetRange")
            # If it's a dict
            elif isinstance(raw_response, dict):
                if "targetUri" in raw_response and "uri" not in raw_response:
                    raw_response["uri"] = raw_response.pop("targetUri")
                if "targetRange" in raw_response and "range" not in raw_response:
                    raw_response["range"] = raw_response.pop("targetRange")
        return raw_response

    def get_file_patterns(self) -> List[str]:
        return ["*.ts", "*.tsx", "*.js", "*.jsx", "*.mts", "*.cts", "*.mjs", "*.cjs"]
