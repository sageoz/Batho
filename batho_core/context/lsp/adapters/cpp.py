"""
C/C++ LSP Adapter using clangd.
"""

import json
from typing import Any, Dict, List, Optional
from pathlib import Path

from batho_core.utils.logging import get_logger
from batho_core.context.lsp.adapters.base import LSPAdapter, ProjectConfig

logger = get_logger(__name__, component="cpp_adapter")

class CppAdapter(LSPAdapter):
    """Adapter for C/C++ via clangd."""

    def get_initialize_options(self, project_root: str) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "clangd": {
                "compilationDatabasePath": project_root,
                "fallbackFlags": ["-std=c++17"]
            }
        }
        return options

    def parse_project_config(self, project_root: str) -> ProjectConfig:
        root = Path(project_root)
        files = []
        
        compile_cmds = root / "compile_commands.json"
        
        # In a real setup, we might search build/compile_commands.json as well
        if not compile_cmds.exists():
            build_dir_cmds = root / "build" / "compile_commands.json"
            if build_dir_cmds.exists():
                compile_cmds = build_dir_cmds
                
        if compile_cmds.exists():
            files.append(compile_cmds.name)
            try:
                with open(compile_cmds, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        logger.debug("found_compile_commands", entries=len(data))
            except Exception as e:
                logger.warning("invalid_compile_commands", error=str(e))
                
        cmake_lists = root / "CMakeLists.txt"
        if cmake_lists.exists():
            files.append("CMakeLists.txt")
            
        return ProjectConfig(root=project_root, files=files)

    def adapt_uri(self, uri: str) -> str:
        return uri

    def adapt_response(self, method: str, raw_response: Any) -> Any:
        """Adapt LSP response for C/C++."""
        if method == "textDocument/hover" and isinstance(raw_response, dict):
            contents = raw_response.get("contents")
            if isinstance(contents, dict) and "value" in contents:
                raw_response["contents"]["value"] = self.extract_type_info(contents["value"]) or contents["value"]
            elif isinstance(contents, str):
                raw_response["contents"] = self.extract_type_info(contents) or contents
        return raw_response

    def extract_type_info(self, hover_content: str) -> Optional[str]:
        """Extract type signature and templates from clangd hover."""
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
        return ["*.c", "*.cc", "*.cpp", "*.cxx", "*.h", "*.hpp", "*.hxx"]
