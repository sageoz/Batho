"""
Base interface for all C4 model formatters.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass


class ViewType(Enum):
    """C4 model view types."""
    CONTEXT = "context"
    CONTAINER = "container"
    COMPONENT = "component"
    DEPLOYMENT = "deployment"
    DYNAMIC = "dynamic"


@dataclass
class FormatCapabilities:
    """Describes the capabilities of a formatter."""
    supported_views: Set[ViewType]
    supports_splitting: bool
    supports_themes: bool
    supports_interactivity: bool
    supports_export: bool
    max_recommended_size: Optional[int] = None


@dataclass
class FormatConfig:
    """Configuration for a formatter."""
    theme: Optional[str] = None
    split_threshold: Optional[int] = None
    include_relationships: bool = True
    include_descriptions: bool = True
    custom_options: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.custom_options is None:
            self.custom_options = {}


class BaseFormatter(ABC):
    """Base class for all C4 model formatters."""
    
    def __init__(self, config: Optional[FormatConfig] = None):
        self.config = config or FormatConfig()
        self.capabilities = self.get_capabilities()
    
    @abstractmethod
    def format_model(self, c4_model: Dict[str, Any]) -> str:
        """
        Format a C4 model into the target format.
        
        Args:
            c4_model: Complete C4 model dictionary
            
        Returns:
            Formatted output as string
        """
        pass
    
    @abstractmethod
    def get_capabilities(self) -> FormatCapabilities:
        """Get the capabilities of this formatter."""
        pass
    
    def validate_config(self, config: FormatConfig) -> bool:
        """
        Validate formatter configuration.
        
        Args:
            config: Configuration to validate
            
        Returns:
            True if valid, False otherwise
        """
        return True
    
    def get_supported_views(self) -> List[ViewType]:
        """Get list of supported view types."""
        return list(self.capabilities.supported_views)
    
    def supports_view(self, view_type: ViewType) -> bool:
        """Check if a specific view type is supported."""
        return view_type in self.capabilities.supported_views
    
    def should_split(self, c4_model: Dict[str, Any]) -> bool:
        """
        Determine if the model should be split into multiple diagrams.
        
        Args:
            c4_model: C4 model to check
            
        Returns:
            True if splitting is recommended
        """
        if not self.capabilities.supports_splitting:
            return False
        
        # Count total elements
        total_elements = (
            len(c4_model.get("model", {}).get("softwareSystems", [])) +
            len(c4_model.get("model", {}).get("containers", [])) +
            len(c4_model.get("model", {}).get("components", []))
        )
        
        threshold = self.config.split_threshold or self.capabilities.max_recommended_size
        return threshold is not None and total_elements > threshold
    
    def get_theme(self) -> str:
        """Get the current theme."""
        return self.config.theme or "default"
    
    def set_theme(self, theme: str) -> None:
        """Set the theme for the formatter."""
        if self.capabilities.supports_themes:
            self.config.theme = theme
