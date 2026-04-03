"""
Rule loader for rule system.

Loads and merges rules from YAML and JSON files with inheritance support.
"""

from __future__ import annotations

import json
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from batho_core.utils.logging import get_logger
from .cache import RuleCache
from .schema import RuleValidator

logger = get_logger(__name__, component="rule_loader")


class RuleMerger:
    """Handles rule inheritance and merging."""
    
    @staticmethod
    def merge_rules(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge two rule dictionaries, with override taking precedence.
        
        Args:
            base: Base rule dictionary.
            override: Override rule dictionary.
            
        Returns:
            Merged rule dictionary.
        """
        merged = base.copy()
        
        for key, value in override.items():
            if key in merged and isinstance(merged[key], list) and isinstance(value, list):
                # Merge lists, removing duplicates
                merged[key] = list(dict.fromkeys(merged[key] + value))
            elif key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                # Recursively merge dictionaries
                merged[key] = RuleMerger.merge_rules(merged[key], value)
            else:
                # Override with new value
                merged[key] = value
        
        return merged
    
    @staticmethod
    def merge_rule_lists(base_rules: List[Dict[str, Any]], 
                        override_rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Merge two lists of rules, replacing rules with the same name.
        
        Args:
            base_rules: Base rule list.
            override_rules: Override rule list.
            
        Returns:
            Merged rule list.
        """
        # Create lookup of base rules by name
        rule_lookup = {rule.get('name'): rule for rule in base_rules}
        
        # Apply overrides
        for rule in override_rules:
            rule_name = rule.get('name')
            if rule_name:
                rule_lookup[rule_name] = rule
        
        # Return rules sorted by priority (descending)
        return sorted(rule_lookup.values(), key=lambda r: r.get('priority', 0), reverse=True)


class RuleLoader:
    """Loads rules from YAML and JSON files with caching and inheritance."""
    
    def __init__(self, rules_dir: Optional[Path] = None, cache_ttl: int = 3600):
        """
        Initialize rule loader.
        
        Args:
            rules_dir: Directory containing rule files. Defaults to package rules directory.
            cache_ttl: Cache time-to-live in seconds.
        """
        if rules_dir is None:
            rules_dir = Path(__file__).parent
        
        self.rules_dir = Path(rules_dir)
        self.base_dir = self.rules_dir / "base"
        self.languages_dir = self.rules_dir / "languages"
        self.dynamic_dir = self.rules_dir / "dynamic"
        self.enhanced_dir = self.rules_dir / "enhanced"
        
        # Initialize components
        self.cache = RuleCache(cache_dir=self.rules_dir / ".cache", default_ttl=cache_ttl)
        self.validator = RuleValidator()
        self.merger = RuleMerger()
        
        # Loaded rules cache
        self._loaded_rules: Optional[Dict[str, Any]] = None
        
        logger.debug("Initialized rule loader", rules_dir=str(self.rules_dir))
    
    def load_all_rules(self, force_reload: bool = False) -> Dict[str, Any]:
        """
        Load all rules from files.
        
        Args:
            force_reload: Force reload even if cached.
            
        Returns:
            Dictionary containing all loaded rules.
        """
        if not force_reload and self._loaded_rules:
            return self._loaded_rules
        
        # Check cache
        cache_key = "all_rules"
        cached = self.cache.get(cache_key)
        if cached and not force_reload:
            self._loaded_rules = cached
            return cached
        
        # Load base rules
        base_rules = self._load_base_rules()
        
        # Load language-specific rules
        language_rules = self._load_language_rules(base_rules)
        
        # Load enhanced rules
        enhanced_rules = self._load_enhanced_rules()
        
        # Load dynamic rules
        dynamic_rules = self._load_dynamic_rules()
        
        # Combine all rules
        all_rules = {
            "version": "1.0",
            "base": base_rules,
            "languages": language_rules,
            "enhanced": enhanced_rules,
            "dynamic": dynamic_rules,
            "loaded_at": self.cache._get_file_hash(self.rules_dir)  # Use as timestamp
        }
        
        # Cache the result
        self.cache.set(cache_key, all_rules, ttl=self.cache.default_ttl)
        self._loaded_rules = all_rules
        
        logger.info("Loaded all rules", 
                   languages=len(language_rules),
                   external_systems=len(base_rules.get('external_systems', [])),
                   containers=len(base_rules.get('containers', [])),
                   components=len(base_rules.get('components', [])))
        
        return all_rules
    
    def get_language_rules(self, language: str, force_reload: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get rules for a specific language.
        
        Args:
            language: Language name (e.g., 'python', 'java').
            force_reload: Force reload even if cached.
            
        Returns:
            Language-specific rules or None if not found.
        """
        all_rules = self.load_all_rules(force_reload=force_reload)
        return all_rules.get('languages', {}).get(language)
    
    def get_external_system_rules(self, language: Optional[str] = None, 
                                 force_reload: bool = False) -> List[Dict[str, Any]]:
        """
        Get external system detection rules.
        
        Args:
            language: Optional language filter.
            force_reload: Force reload even if cached.
            
        Returns:
            List of external system rules.
        """
        all_rules = self.load_all_rules(force_reload=force_reload)
        
        # Start with base rules
        rules = all_rules.get('base', {}).get('external_systems', []).copy()
        
        # Add language-specific rules
        if language:
            lang_rules = all_rules.get('languages', {}).get(language, {})
            if lang_rules and 'external_systems' in lang_rules:
                rules = self.merger.merge_rule_lists(rules, lang_rules['external_systems'])
        
        # Add dynamic rules
        dynamic_rules = all_rules.get('dynamic', {}).get('external_systems', [])
        if dynamic_rules:
            rules = self.merger.merge_rule_lists(rules, dynamic_rules)
        
        return rules
    
    def get_container_rules(self, language: Optional[str] = None, 
                           force_reload: bool = False) -> List[Dict[str, Any]]:
        """
        Get container detection rules.
        
        Args:
            language: Optional language filter.
            force_reload: Force reload even if cached.
            
        Returns:
            List of container rules.
        """
        all_rules = self.load_all_rules(force_reload=force_reload)
        
        # Start with base rules
        rules = all_rules.get('base', {}).get('containers', []).copy()
        
        # Add language-specific rules
        if language:
            lang_rules = all_rules.get('languages', {}).get(language, {})
            if lang_rules and 'containers' in lang_rules:
                rules = self.merger.merge_rule_lists(rules, lang_rules['containers'])
        
        # Add dynamic rules
        dynamic_rules = all_rules.get('dynamic', {}).get('containers', [])
        if dynamic_rules:
            rules = self.merger.merge_rule_lists(rules, dynamic_rules)
        
        return rules
    
    def get_component_rules(self, language: Optional[str] = None, 
                           force_reload: bool = False) -> List[Dict[str, Any]]:
        """
        Get component detection rules.
        
        Args:
            language: Optional language filter.
            force_reload: Force reload even if cached.
            
        Returns:
            List of component rules.
        """
        all_rules = self.load_all_rules(force_reload=force_reload)
        
        # Start with base rules
        rules = all_rules.get('base', {}).get('components', []).copy()
        
        # Add language-specific rules
        if language:
            lang_rules = all_rules.get('languages', {}).get(language, {})
            if lang_rules and 'components' in lang_rules:
                rules = self.merger.merge_rule_lists(rules, lang_rules['components'])
        
        # Add dynamic rules
        dynamic_rules = all_rules.get('dynamic', {}).get('components', [])
        if dynamic_rules:
            rules = self.merger.merge_rule_lists(rules, dynamic_rules)
        
        return rules
    
    def _load_base_rules(self) -> Dict[str, Any]:
        """Load base rules from the base directory."""
        rules = {
            "external_systems": [],
            "containers": [],
            "components": []
        }
        
        # Load external systems
        external_file = self.base_dir / "external_systems.yaml"
        if external_file.exists():
            loaded = self._load_rule_file(external_file)
            if loaded and 'external_systems' in loaded:
                rules['external_systems'] = loaded['external_systems']
        
        # Load containers
        containers_file = self.base_dir / "containers.yaml"
        if containers_file.exists():
            loaded = self._load_rule_file(containers_file)
            if loaded and 'containers' in loaded:
                rules['containers'] = loaded['containers']
        
        # Load components
        components_file = self.base_dir / "components.yaml"
        if components_file.exists():
            loaded = self._load_rule_file(components_file)
            if loaded and 'components' in loaded:
                rules['components'] = loaded['components']
        
        return rules
    
    def _load_language_rules(self, base_rules: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Load language-specific rules with inheritance from base rules."""
        languages = {}
        
        if not self.languages_dir.exists():
            return languages
        
        for lang_file in self.languages_dir.glob("*.yaml"):
            language = lang_file.stem
            loaded = self._load_rule_file(lang_file)
            
            if loaded:
                # Apply inheritance
                if loaded.get('inherits'):
                    for parent in loaded['inherits']:
                        if parent in languages:
                            loaded = self._apply_inheritance(loaded, languages[parent])
                
                # Merge with base rules
                lang_rules = {
                    "external_systems": self.merger.merge_rule_lists(
                        base_rules.get('external_systems', []),
                        loaded.get('external_systems', [])
                    ),
                    "containers": self.merger.merge_rule_lists(
                        base_rules.get('containers', []),
                        loaded.get('containers', [])
                    ),
                    "components": self.merger.merge_rule_lists(
                        base_rules.get('components', []),
                        loaded.get('components', [])
                    )
                }
                
                # Add language-specific metadata
                lang_rules.update({
                    k: v for k, v in loaded.items() 
                    if k not in ['external_systems', 'containers', 'components', 'inherits']
                })
                
                languages[language] = lang_rules
                logger.debug("Loaded language rules", language=language)
        
        return languages
    
    def _load_enhanced_rules(self) -> Dict[str, Any]:
        """Load enhanced architectural pattern rules."""
        rules = {
            "microservices": {},
            "event_driven": {},
            "cloud_native": {},
            "data_patterns": {}
        }
        
        if not self.enhanced_dir.exists():
            logger.debug("Enhanced rules directory not found", dir=str(self.enhanced_dir))
            return rules
        
        # Load each enhanced rule file
        rule_files = {
            "microservices": "microservices.yaml",
            "event_driven": "event_driven.yaml",
            "cloud_native": "cloud_native.yaml",
            "data_patterns": "data_patterns.yaml"
        }
        
        for rule_type, filename in rule_files.items():
            file_path = self.enhanced_dir / filename
            if file_path.exists():
                loaded = self._load_rule_file(file_path)
                if loaded:
                    # Validate and store
                    if self.validator.validate_rule_set(loaded, rule_type):
                        rules[rule_type] = loaded
                        logger.debug("Loaded enhanced rules", type=rule_type)
                    else:
                        logger.warning("Invalid enhanced rules", type=rule_type, file=str(file_path))
        
        return rules
    
    def _load_dynamic_rules(self) -> Dict[str, Any]:
        """Load dynamically generated rules."""
        rules = {
            "external_systems": [],
            "containers": [],
            "components": []
        }
        
        dynamic_file = self.dynamic_dir / "detected_patterns.json"
        if dynamic_file.exists():
            loaded = self._load_rule_file(dynamic_file)
            if loaded:
                rules.update(loaded)
                logger.debug("Loaded dynamic rules", count=len(loaded))
        
        return rules
    
    def _load_rule_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Load a single rule file (YAML or JSON).
        
        Args:
            file_path: Path to rule file.
            
        Returns:
            Loaded rules or None if failed.
        """
        # Check cache first
        cache_key = f"file:{file_path}"
        cached = self.cache.get(cache_key, file_path=file_path)
        if cached:
            return cached
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.suffix.lower() in ['.yaml', '.yml']:
                    data = yaml.safe_load(f)
                elif file_path.suffix.lower() == '.json':
                    data = json.load(f)
                else:
                    logger.warning("Unsupported file format", file=str(file_path))
                    return None
            
            # Validate the loaded data
            if not self._validate_rules(data, file_path):
                return None
            
            # Cache the result
            self.cache.set(cache_key, data, file_path=file_path)
            
            return data
            
        except Exception as e:
            logger.error("Failed to load rule file", file=str(file_path), error=str(e))
            return None
    
    def _validate_rules(self, rules: Dict[str, Any], file_path: Path) -> bool:
        """Validate loaded rules."""
        if not isinstance(rules, dict):
            logger.error("Invalid rule file format", file=str(file_path))
            return False
        
        # Validate each rule type
        valid = True
        
        for rule_type in ['external_systems', 'containers', 'components']:
            if rule_type in rules:
                for rule in rules[rule_type]:
                    if rule_type == 'external_systems':
                        if not self.validator.validate_external_system_rule(rule):
                            valid = False
                    elif rule_type == 'containers':
                        if not self.validator.validate_container_rule(rule):
                            valid = False
                    elif rule_type == 'components':
                        if not self.validator.validate_component_rule(rule):
                            valid = False
        
        return valid
    
    def _apply_inheritance(self, child: Dict[str, Any], parent: Dict[str, Any]) -> Dict[str, Any]:
        """Apply rule inheritance from parent to child."""
        inherited = parent.copy()
        
        for key, value in child.items():
            if key in ['external_systems', 'containers', 'components']:
                # Merge rule lists
                inherited[key] = self.merger.merge_rule_lists(
                    inherited.get(key, []),
                    value
                )
            else:
                # Override other fields
                inherited[key] = value
        
        return inherited
