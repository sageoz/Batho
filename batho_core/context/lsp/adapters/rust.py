"""
Rust LSP Adapter using rust-analyzer.
"""

import tomllib
from typing import Any, Dict, List, Optional
from pathlib import Path

from batho_core.utils.logging import get_logger
from batho_core.context.lsp.adapters.base import LSPAdapter, ProjectConfig

logger = get_logger(__name__, component="rust_adapter")

class RustAdapter(LSPAdapter):
    """Adapter for Rust via rust-analyzer."""

    def get_initialize_options(self, project_root: str) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "cargo": {
                "features": "all"
            },
            "checkOnSave": {
                "command": "clippy"
            },
            "procMacro": {
                "enable": True
            }
        }
        return options

    def parse_project_config(self, project_root: str) -> ProjectConfig:
        root = Path(project_root)
        files = []
        
        toml_file = root / "Cargo.toml"
        if toml_file.exists():
            files.append("Cargo.toml")
            try:
                # Basic validation
                with open(toml_file, "rb") as f:
                    tomllib.load(f)
            except Exception as e:
                logger.warning("invalid_cargo_toml", error=str(e))
                
        lock_file = root / "Cargo.lock"
        if lock_file.exists():
            files.append("Cargo.lock")
            
        return ProjectConfig(root=project_root, files=files)

    def adapt_uri(self, uri: str) -> str:
        return uri

    def adapt_response(self, method: str, raw_response: Any) -> Any:
        """Adapt LSP response for Rust."""
        if method == "textDocument/hover" and isinstance(raw_response, dict):
            contents = raw_response.get("contents")
            if isinstance(contents, dict) and "value" in contents:
                raw_response["contents"]["value"] = self.extract_type_info(contents["value"]) or contents["value"]
        return raw_response

    def extract_type_info(self, hover_content: str) -> Optional[str]:
        """Extract type signature and ownership hints from r-a hover content."""
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
        return ["*.rs"]
