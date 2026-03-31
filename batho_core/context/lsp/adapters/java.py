"""
Java LSP Adapter using Eclipse JDT LS.
"""

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from pathlib import Path

from batho_core.utils.logging import get_logger
from batho_core.context.lsp.adapters.base import LSPAdapter, ProjectConfig

logger = get_logger(__name__, component="java_adapter")

class JavaAdapter(LSPAdapter):
    """Adapter for Java via Eclipse JDT LS."""

    def get_initialize_options(self, project_root: str) -> Dict[str, Any]:
        options: Dict[str, Any] = {
            "settings": {
                "java": {
                    "home": "/opt/java/generated",  # This would be dynamic based on hermetic jdk
                    "configuration": {
                        "updateBuildConfiguration": "automatic"
                    },
                    "compile": {
                        "nullAnalysis": {
                            "mode": "automatic"
                        }
                    }
                }
            }
        }
        return options

    def parse_project_config(self, project_root: str) -> ProjectConfig:
        root = Path(project_root)
        files = []
        
        # Maven
        pom_xml = root / "pom.xml"
        if pom_xml.exists():
            files.append("pom.xml")
            try:
                tree = ET.parse(pom_xml)
                # Basic validation, just check root tag
                if tree.getroot().tag.endswith("project"):
                    logger.debug("valid_pom_xml_found")
            except Exception as e:
                logger.warning("invalid_pom_xml", error=str(e))
                
        # Gradle
        build_gradle = root / "build.gradle"
        if build_gradle.exists():
            files.append("build.gradle")
            
        return ProjectConfig(root=project_root, files=files)

    def adapt_uri(self, uri: str) -> str:
        return uri

    def adapt_response(self, method: str, raw_response: Any) -> Any:
        """Adapt LSP response for Java."""
        if method == "textDocument/hover" and isinstance(raw_response, dict):
            contents = raw_response.get("contents")
            if isinstance(contents, dict) and "value" in contents:
                raw_response["contents"]["value"] = self.extract_type_info(contents["value"]) or contents["value"]
            elif isinstance(contents, str):
                raw_response["contents"] = self.extract_type_info(contents) or contents
        return raw_response

    def extract_type_info(self, hover_content: str) -> Optional[str]:
        """Extract type signature from Java hover."""
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
        return ["*.java"]
