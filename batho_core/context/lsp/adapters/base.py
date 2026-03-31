"""
Base adapter interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List




class ProjectConfig:
    """Project-specific configuration dependencies."""
    def __init__(self, root: str, files: List[str]):
        self.root = root
        self.files = files


class LSPAdapter(ABC):
    """
    Language-specific adapter for LSP customization.
    """

    @abstractmethod
    def get_initialize_options(self, project_root: str) -> Dict[str, Any]:
        """
        Get language-specific initialization options.
        """
        pass

    @abstractmethod
    def parse_project_config(self, project_root: str) -> ProjectConfig:
        """
        Parse project-specific configuration files.
        """
        pass

    @abstractmethod
    def adapt_uri(self, uri: str) -> str:
        """
        Adapt URI between LSP and Batho conventions.
        """
        pass

    @abstractmethod
    def adapt_response(self, method: str, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adapt LSP response for Batho consumption.
        """
        pass

    @abstractmethod
    def get_file_patterns(self) -> List[str]:
        """
        Get file glob patterns for this language.
        """
        pass
