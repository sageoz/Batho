"""
Registry for managing output formatters with plugin support.
"""

import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Type, Any
from dataclasses import dataclass

from batho_core.utils.logging import get_logger
from .base import BaseFormatter, FormatCapabilities, ViewType

logger = get_logger(__name__, component="format_registry")


@dataclass
class FormatInfo:
    """Information about a registered formatter."""
    name: str
    description: str
    file_extension: str
    mime_type: str
    capabilities: FormatCapabilities
    formatter_class: Type[BaseFormatter]


class FormatRegistry:
    """Registry for managing output formatters."""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__, component="format_registry")
        self._formatters: Dict[str, FormatInfo] = {}
        self._instances: Dict[str, BaseFormatter] = {}
    
    def register_formatter(
        self,
        name: str,
        formatter_class: Type[BaseFormatter],
        description: str = "",
        file_extension: str = "",
        mime_type: str = ""
    ) -> None:
        """
        Register a formatter class.
        
        Args:
            name: Unique name for the formatter
            formatter_class: Class implementing BaseFormatter
            description: Human-readable description
            file_extension: Default file extension
            mime_type: MIME type for the format
        """
        if name in self._formatters:
            self.logger.warning("Formatter already registered, overwriting", name=name)
        
        # Create temporary instance to get capabilities
        temp_instance = formatter_class()
        capabilities = temp_instance.get_capabilities()
        
        self._formatters[name] = FormatInfo(
            name=name,
            description=description or f"{name} formatter",
            file_extension=file_extension or name,
            mime_type=mime_type or f"text/{name}",
            capabilities=capabilities,
            formatter_class=formatter_class
        )
        
        self.logger.info("Registered formatter", name=name)
    
    def get_formatter(self, name: str, config: Optional[Dict[str, Any]] = None) -> BaseFormatter:
        """
        Get a formatter instance.
        
        Args:
            name: Name of the formatter
            config: Optional configuration
            
        Returns:
            Formatter instance
            
        Raises:
            ValueError: If formatter is not found
        """
        if name not in self._formatters:
            raise ValueError(f"Unknown formatter: {name}")
        
        # Create or get cached instance
        cache_key = f"{name}:{hash(str(config))}"
        if cache_key not in self._instances:
            from .base import FormatConfig
            formatter_config = FormatConfig(**config) if config else FormatConfig()
            
            formatter_class = self._formatters[name].formatter_class
            self._instances[cache_key] = formatter_class(formatter_config)
        
        return self._instances[cache_key]
    
    def list_formats(self) -> List[FormatInfo]:
        """List all registered formatters."""
        return list(self._formatters.values())
    
    def get_format_info(self, name: str) -> Optional[FormatInfo]:
        """Get information about a specific formatter."""
        return self._formatters.get(name)
    
    def load_plugin(self, plugin_path: str) -> None:
        """
        Load a formatter plugin from a Python file.
        
        Args:
            plugin_path: Path to the plugin file
        """
        plugin_path = Path(plugin_path)
        
        if not plugin_path.exists():
            raise FileNotFoundError(f"Plugin not found: {plugin_path}")
        
        # Load the module
        spec = importlib.util.spec_from_file_location("plugin", plugin_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Find formatter classes in the module
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (issubclass(obj, BaseFormatter) and 
                obj != BaseFormatter and 
                not obj.__name__.startswith('_')):
                
                # Register the formatter
                formatter_name = getattr(obj, 'FORMATTER_NAME', name.lower())
                description = getattr(obj, 'FORMATTER_DESCRIPTION', f"{formatter_name} plugin")
                file_extension = getattr(obj, 'FILE_EXTENSION', formatter_name)
                mime_type = getattr(obj, 'MIME_TYPE', f"text/{formatter_name}")
                
                self.register_formatter(
                    formatter_name,
                    obj,
                    description,
                    file_extension,
                    mime_type
                )
                
                self.logger.info(
                    "Loaded plugin formatter",
                    plugin=str(plugin_path),
                    formatter=formatter_name
                )
    
    def load_plugins_from_directory(self, plugin_dir: str) -> None:
        """
        Load all plugins from a directory.
        
        Args:
            plugin_dir: Directory containing plugin files
        """
        plugin_path = Path(plugin_dir)
        
        if not plugin_path.exists():
            self.logger.debug("Plugin directory does not exist", dir=plugin_dir)
            return
        
        for py_file in plugin_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            
            try:
                self.load_plugin(str(py_file))
            except Exception as e:
                self.logger.error(
                    "Failed to load plugin",
                    file=str(py_file),
                    error=str(e)
                )
    
    def unregister_formatter(self, name: str) -> None:
        """Unregister a formatter."""
        if name in self._formatters:
            del self._formatters[name]
            
            # Remove cached instances
            keys_to_remove = [k for k in self._instances.keys() if k.startswith(f"{name}:")]
            for key in keys_to_remove:
                del self._instances[key]
            
            self.logger.info("Unregistered formatter", name=name)
    
    def clear(self) -> None:
        """Clear all registered formatters."""
        self._formatters.clear()
        self._instances.clear()
        self.logger.info("Cleared all formatters")


# Global registry instance
_registry: Optional[FormatRegistry] = None


def get_format_registry() -> FormatRegistry:
    """Get the global format registry instance."""
    global _registry
    if _registry is None:
        _registry = FormatRegistry()
        _register_builtin_formatters(_registry)
    return _registry


def _register_builtin_formatters(registry: FormatRegistry) -> None:
    """Register built-in formatters."""
    # Import here to avoid circular imports
    from .plantuml import PlantUMLFormatter
    from .mermaid import MermaidFormatter
    from .interactive import InteractiveHTMLFormatter
    from .d2 import D2Formatter
    
    # Register PlantUML
    registry.register_formatter(
        "plantuml",
        PlantUMLFormatter,
        "PlantUML diagram format",
        "puml",
        "text/plain"
    )
    
    # Register Mermaid
    registry.register_formatter(
        "mermaid",
        MermaidFormatter,
        "Mermaid diagram format for Markdown",
        "mmd",
        "text/plain"
    )
    
    # Register Interactive HTML
    registry.register_formatter(
        "interactive",
        InteractiveHTMLFormatter,
        "Interactive HTML visualization",
        "html",
        "text/html"
    )
    
    # Register D2
    registry.register_formatter(
        "d2",
        D2Formatter,
        "D2 declarative diagrams",
        "d2",
        "text/plain"
    )
