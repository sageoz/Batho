"""
Rule validation schemas for C4 rule system.

Defines validation schemas for all rule types using Pydantic for runtime validation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pathlib import Path

try:
    from pydantic import BaseModel, Field, validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    # Fallback when Pydantic is not available
    PYDANTIC_AVAILABLE = False
    BaseModel = object
    
    class Field:
        def __init__(self, default=None, description=None, **kwargs):
            self.default = default
            self.description = description


class ExternalSystemRuleSchema(BaseModel if PYDANTIC_AVAILABLE else object):
    """Schema for external system detection rules."""
    
    name: str = Field(..., description="Unique rule name")
    description: str = Field(..., description="Rule description")
    priority: int = Field(0, description="Rule priority (higher runs first)")
    patterns: List[str] = Field(..., description="Import patterns to match")
    system_type: str = Field(..., description="Type of external system")
    actor_name: str = Field(..., description="Name of the actor in C4 model")
    actor_description: str = Field(..., description="Description of the actor")
    
    if PYDANTIC_AVAILABLE:
        from pydantic import field_validator
        
        @field_validator('patterns')
        @classmethod
        def patterns_not_empty(cls, v):
            if not v:
                raise ValueError("Patterns list cannot be empty")
            return v


class ContainerRuleSchema(BaseModel if PYDANTIC_AVAILABLE else object):
    """Schema for container detection rules."""
    
    name: str = Field(..., description="Unique rule name")
    description: str = Field(..., description="Rule description")
    priority: int = Field(0, description="Rule priority (higher runs first)")
    framework_patterns: List[str] = Field(default_factory=list, description="Framework patterns to match")
    directory_patterns: List[str] = Field(default_factory=list, description="Directory patterns to match")
    file_patterns: List[str] = Field(default_factory=list, description="File patterns to match")
    container_type: str = Field(..., description="Type of container")
    container_name: str = Field(..., description="Name of the container")
    technology: List[str] = Field(default_factory=list, description="Technology stack")
    
    if PYDANTIC_AVAILABLE:
        from pydantic import field_validator
        
        @field_validator('framework_patterns', 'directory_patterns', 'file_patterns')
        @classmethod
        def at_least_one_pattern(cls, v, info):
            # Check if at least one pattern list has items
            if isinstance(v, list) and not v:
                # Get all values from the model
                all_values = info.data if hasattr(info, 'data') else {}
                all_patterns = [
                    all_values.get('framework_patterns', []),
                    all_values.get('directory_patterns', []),
                    all_values.get('file_patterns', [])
                ]
                if all(not p for p in all_patterns):
                    raise ValueError(f"At least one pattern list must have items for {info.field_name}")
            return v


class ComponentRuleSchema(BaseModel if PYDANTIC_AVAILABLE else object):
    """Schema for component detection rules."""
    
    name: str = Field(..., description="Unique rule name")
    description: str = Field(..., description="Rule description")
    priority: int = Field(0, description="Rule priority (higher runs first)")
    entity_types: List[str] = Field(..., description="Entity types to match")
    importance_threshold: float = Field(0.0, description="Minimum importance score")
    max_per_file: int = Field(5, description="Maximum components per file")
    component_type: str = Field(..., description="Type of component")
    name_patterns: Optional[List[str]] = Field(None, description="Name patterns to match")
    file_patterns: Optional[List[str]] = Field(None, description="File patterns to match")
    
    if PYDANTIC_AVAILABLE:
        from pydantic import field_validator
        
        @field_validator('entity_types')
        @classmethod
        def entity_types_not_empty(cls, v):
            if not v:
                raise ValueError("Entity types list cannot be empty")
            return v
        
        @field_validator('importance_threshold')
        @classmethod
        def importance_range(cls, v):
            if not 0 <= v <= 1:
                raise ValueError("Importance threshold must be between 0 and 1")
            return v


class LanguageRuleSchema(BaseModel if PYDANTIC_AVAILABLE else object):
    """Schema for language-specific rule collections."""
    
    language: str = Field(..., description="Language name (e.g., 'python', 'java')")
    description: str = Field(..., description="Language description")
    file_extensions: List[str] = Field(..., description="File extensions for this language")
    external_systems: List[ExternalSystemRuleSchema] = Field(default_factory=list)
    containers: List[ContainerRuleSchema] = Field(default_factory=list)
    components: List[ComponentRuleSchema] = Field(default_factory=list)
    inherits: Optional[List[str]] = Field(None, description="Parent rules to inherit from")
    
    if PYDANTIC_AVAILABLE:
        from pydantic import field_validator
        
        @field_validator('file_extensions')
        @classmethod
        def valid_extensions(cls, v):
            if not v:
                raise ValueError("File extensions list cannot be empty")
            # Ensure all extensions start with '.'
            for ext in v:
                if not ext.startswith('.'):
                    raise ValueError(f"File extension must start with '.': {ext}")
            return v


class RuleCollectionSchema(BaseModel if PYDANTIC_AVAILABLE else object):
    """Schema for a complete rule collection."""
    
    version: str = Field("1.0", description="Rule format version")
    description: str = Field(..., description="Collection description")
    external_systems: List[ExternalSystemRuleSchema] = Field(default_factory=list)
    containers: List[ContainerRuleSchema] = Field(default_factory=list)
    components: List[ComponentRuleSchema] = Field(default_factory=list)
    languages: Optional[Dict[str, LanguageRuleSchema]] = Field(None, description="Language-specific rules")


class DynamicRuleSchema(BaseModel if PYDANTIC_AVAILABLE else object):
    """Schema for dynamically generated rules."""
    
    id: str = Field(..., description="Unique rule identifier")
    pattern: str = Field(..., description="Detected pattern")
    confidence: float = Field(..., description="Confidence score (0-1)")
    rule_type: str = Field(..., description="Type of rule (external_system, container, component)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: str = Field(..., description="Creation timestamp")
    usage_count: int = Field(0, description="Number of times this rule was used")
    
    if PYDANTIC_AVAILABLE:
        from pydantic import field_validator
        
        @field_validator('confidence')
        @classmethod
        def confidence_range(cls, v):
            if not 0 <= v <= 1:
                raise ValueError("Confidence must be between 0 and 1")
            return v


class RuleValidator:
    """Validates rules against schemas."""
    
    def __init__(self):
        self.pydantic_available = PYDANTIC_AVAILABLE
        if not self.pydantic_available:
            print("Warning: Pydantic not available, using basic validation")
    
    def validate_external_system_rule(self, rule: Dict[str, Any]) -> bool:
        """Validate an external system rule."""
        if not self.pydantic_available:
            return self._basic_validate_external_system(rule)
        
        try:
            ExternalSystemRuleSchema(**rule)
            return True
        except Exception as e:
            print(f"Invalid external system rule: {e}")
            return False
    
    def validate_container_rule(self, rule: Dict[str, Any]) -> bool:
        """Validate a container rule."""
        if not self.pydantic_available:
            return self._basic_validate_container(rule)
        
        try:
            ContainerRuleSchema(**rule)
            return True
        except Exception as e:
            print(f"Invalid container rule: {e}")
            return False
    
    def validate_component_rule(self, rule: Dict[str, Any]) -> bool:
        """Validate a component rule."""
        if not self.pydantic_available:
            return self._basic_validate_component(rule)
        
        try:
            ComponentRuleSchema(**rule)
            return True
        except Exception as e:
            print(f"Invalid component rule: {e}")
            return False
    
    def validate_language_rules(self, rules: Dict[str, Any]) -> bool:
        """Validate language-specific rules."""
        if not self.pydantic_available:
            return self._basic_validate_language(rules)
        
        try:
            LanguageRuleSchema(**rules)
            return True
        except Exception as e:
            print(f"Invalid language rule: {e}")
            return False
    
    def validate_rule_collection(self, collection: Dict[str, Any]) -> bool:
        """Validate a complete rule collection."""
        if not self.pydantic_available:
            return self._basic_validate_collection(collection)
        
        try:
            RuleCollectionSchema(**collection)
            return True
        except Exception as e:
            print(f"Invalid rule collection: {e}")
            return False
    
    def _basic_validate_external_system(self, rule: Dict[str, Any]) -> bool:
        """Basic validation without Pydantic."""
        required = ['name', 'description', 'patterns', 'system_type', 'actor_name', 'actor_description']
        return all(field in rule for field in required) and isinstance(rule.get('patterns'), list)
    
    def _basic_validate_container(self, rule: Dict[str, Any]) -> bool:
        """Basic validation without Pydantic."""
        required = ['name', 'description', 'container_type', 'container_name']
        if not all(field in rule for field in required):
            return False
        
        # Check at least one pattern list exists and has items
        patterns = [
            rule.get('framework_patterns', []),
            rule.get('directory_patterns', []),
            rule.get('file_patterns', [])
        ]
        return any(isinstance(p, list) and p for p in patterns)
    
    def _basic_validate_component(self, rule: Dict[str, Any]) -> bool:
        """Basic validation without Pydantic."""
        required = ['name', 'description', 'entity_types', 'component_type']
        if not all(field in rule for field in required):
            return False
        
        if not isinstance(rule.get('entity_types'), list) or not rule['entity_types']:
            return False
        
        importance = rule.get('importance_threshold', 0)
        return isinstance(importance, (int, float)) and 0 <= importance <= 1
    
    def _basic_validate_language(self, rules: Dict[str, Any]) -> bool:
        """Basic validation without Pydantic."""
        required = ['language', 'description', 'file_extensions']
        return all(field in rules for field in required) and isinstance(rules.get('file_extensions'), list)
    
    def _basic_validate_collection(self, collection: Dict[str, Any]) -> bool:
        """Basic validation without Pydantic."""
        return 'description' in collection
