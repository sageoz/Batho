"""
C4 Generation Rules and Heuristics.

Defines rule-based transformations for converting code artifacts into C4 model elements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple, Optional
from pathlib import Path
from collections import defaultdict

from batho_core.utils.logging import get_logger
from .c4.rules.loader import RuleLoader
from .c4.rules.dynamic.rule_generator import DynamicRuleGenerator


@dataclass
class C4Rule:
    """Base class for C4 generation rules."""
    name: str
    description: str
    priority: int = 0  # Higher priority rules run first


@dataclass
class ExternalSystemRule(C4Rule):
    """Rule for detecting external systems from import patterns."""
    patterns: List[str] = field(default_factory=list)
    system_type: str = ""
    actor_name: str = ""
    actor_description: str = ""


@dataclass
class ContainerRule(C4Rule):
    """Rule for identifying containers from framework and directory patterns."""
    framework_patterns: List[str] = field(default_factory=list)
    directory_patterns: List[str] = field(default_factory=list)
    container_type: str = ""
    container_name: str = ""
    technology: List[str] = field(default_factory=list)


@dataclass
class ComponentRule(C4Rule):
    """Rule for identifying components from entity patterns."""
    entity_types: List[str] = field(default_factory=list)
    importance_threshold: float = 0.0
    max_per_file: int = 5
    component_type: str = ""


class C4RuleEngine:
    """Engine for applying C4 generation rules."""
    
    def __init__(self, rules_dir: Optional[Path] = None, enable_dynamic: bool = True):
        """
        Initialize C4 rule engine.
        
        Args:
            rules_dir: Custom rules directory. Defaults to package rules directory.
            enable_dynamic: Enable dynamic rule generation.
        """
        self.logger = get_logger(__name__, component="c4_rule_engine")
        
        # Initialize rule loader
        self.rule_loader = RuleLoader(rules_dir=rules_dir)
        
        # Initialize dynamic rule generator
        self.dynamic_generator = None
        if enable_dynamic:
            dynamic_dir = rules_dir / "dynamic" if rules_dir else None
            if dynamic_dir:
                self.dynamic_generator = DynamicRuleGenerator(dynamic_dir)
        
        # Cache for loaded rules
        self._cached_rules: Optional[Dict[str, Any]] = None
        
        self.logger.debug("Initialized C4 rule engine", 
                         rules_dir=str(rules_dir),
                         dynamic_enabled=enable_dynamic)
    
    def _load_rules(self, force_reload: bool = False) -> Dict[str, Any]:
        """Load all rules from the rule loader."""
        if self._cached_rules is None or force_reload:
            self._cached_rules = self.rule_loader.load_all_rules(force_reload=force_reload)
        return self._cached_rules
    
    def detect_language(self, graph: Dict[str, Any], repomap: Dict[str, Any]) -> Optional[str]:
        """
        Detect the primary language of the repository.
        
        Args:
            graph: Code graph data.
            repomap: Repository map data.
            
        Returns:
            Detected language or None.
        """
        # Count file extensions
        extension_counts = defaultdict(int)
        
        for file_path in repomap.get("files", {}).keys():
            ext = Path(file_path).suffix.lower()
            if ext:
                extension_counts[ext] += 1
        
        # Map extensions to languages
        ext_to_lang = {
            ".py": "python",
            ".java": "java",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".kt": "java",  # Kotlin treated as Java
            ".scala": "java"  # Scala treated as Java
        }
        
        # Count languages
        lang_counts = defaultdict(int)
        for ext, count in extension_counts.items():
            lang = ext_to_lang.get(ext)
            if lang:
                lang_counts[lang] += count
        
        # Return the most common language
        if lang_counts:
            return max(lang_counts.items(), key=lambda x: x[1])[0]
        
        return None
    
    def generate_dynamic_rules(self, graph: Dict[str, Any], 
                              repomap: Dict[str, Any]) -> None:
        """
        Generate dynamic rules from repository analysis.
        
        Args:
            graph: Code graph data.
            repomap: Repository map data.
        """
        if not self.dynamic_generator:
            return
        
        language = self.detect_language(graph, repomap) or "unknown"
        
        try:
            self.dynamic_generator.analyze_repository(graph, repomap, language)
            # Invalidate cache to reload rules with dynamic ones
            self._cached_rules = None
        except Exception as e:
            self.logger.warning("Failed to generate dynamic rules", error=str(e))
    
    def apply_external_system_rules(self, imports: List[str], 
                                       language: Optional[str] = None) -> Dict[str, List[str]]:
        """
        Apply external system detection rules to import list.
        
        Args:
            imports: List of import strings.
            language: Optional language filter.
            
        Returns:
            Detected external systems.
        """
        rules = self.rule_loader.get_external_system_rules(language=language)
        detected = {}
        
        for rule in rules:
            matches = []
            for imp in imports:
                for pattern in rule.get("patterns", []):
                    if pattern.lower() in imp.lower():
                        matches.append(imp)
                        break
            
            if matches:
                system_type = rule.get("system_type")
                detected[system_type] = {
                    "rule": rule.get("name"),
                    "actor_name": rule.get("actor_name"),
                    "actor_description": rule.get("actor_description"),
                    "matches": matches,
                    "confidence": rule.get("confidence", 1.0)
                }
        
        return detected
    
    def apply_container_rules(self, frameworks: List[str], 
                               directories: List[str],
                               language: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Apply container detection rules to frameworks and directories.
        
        Args:
            frameworks: List of detected frameworks.
            directories: List of directory paths.
            language: Optional language filter.
            
        Returns:
            Detected containers.
        """
        rules = self.rule_loader.get_container_rules(language=language)
        containers = []
        
        for rule in rules:
            framework_match = any(fw in frameworks for fw in rule.get("framework_patterns", []))
            directory_match = any(pattern in "/".join(directories).lower() 
                                for pattern in rule.get("directory_patterns", []))
            file_match = any(pattern in "/".join(directories).lower()
                           for pattern in rule.get("file_patterns", []))
            
            if framework_match or directory_match or file_match:
                containers.append({
                    "rule": rule.get("name"),
                    "type": rule.get("container_type"),
                    "name": rule.get("container_name"),
                    "technology": rule.get("technology", []),
                    "framework_match": framework_match,
                    "directory_match": directory_match,
                    "file_match": file_match,
                    "matched_frameworks": [fw for fw in frameworks 
                                         if fw in rule.get("framework_patterns", [])],
                    "matched_directories": [d for d in directories 
                                           if any(p in d.lower() 
                                                for p in rule.get("directory_patterns", []))],
                    "confidence": rule.get("confidence", 1.0)
                })
        
        return containers
    
    def apply_component_rules(self, entities: List[Dict[str, Any]], 
                              importance_scores: Dict[str, float],
                              language: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Apply component detection rules to entities.
        
        Args:
            entities: List of entities from the code graph.
            importance_scores: Importance scores for entities.
            language: Optional language filter.
            
        Returns:
            Detected components.
        """
        rules = self.rule_loader.get_component_rules(language=language)
        components = []
        
        # Group entities by file
        file_entities = defaultdict(list)
        for entity in entities:
            file_entities[entity.get("file", "")].append(entity)
        
        for file_path, file_entity_list in file_entities.items():
            for rule in rules:
                # Filter entities by type and importance
                candidates = [
                    e for e in file_entity_list
                    if (e.get("type", "").lower() in rule.get("entity_types", []) and
                        importance_scores.get(e.get("id"), 0) >= rule.get("importance_threshold", 0))
                ]
                
                # Additional filtering by name patterns
                if rule.get("name_patterns"):
                    name_filtered = []
                    for entity in candidates:
                        name = entity.get("name", "")
                        if any(self._match_pattern(name, pattern) 
                               for pattern in rule.get("name_patterns", [])):
                            name_filtered.append(entity)
                    candidates = name_filtered
                
                # Additional filtering by file patterns
                if rule.get("file_patterns"):
                    file_filtered = []
                    for entity in candidates:
                        if any(pattern in file_path 
                               for pattern in rule.get("file_patterns", [])):
                            file_filtered.append(entity)
                    candidates = file_filtered
                
                # Sort by importance and take top N
                candidates.sort(key=lambda e: importance_scores.get(e.get("id"), 0), reverse=True)
                selected = candidates[:rule.get("max_per_file", 5)]
                
                for entity in selected:
                    components.append({
                        "rule": rule.get("name"),
                        "entity": entity,
                        "type": rule.get("component_type"),
                        "importance": importance_scores.get(entity.get("id"), 0),
                        "file": file_path,
                        "confidence": rule.get("confidence", 1.0)
                    })
        
        return components
    
    def _match_pattern(self, name: str, pattern: str) -> bool:
        """Match a name against a pattern with wildcards."""
        # Simple wildcard matching
        if '*' in pattern:
            # Convert to regex
            regex = pattern.replace('*', '.*')
            import re
            return bool(re.match(f"^{regex}$", name, re.IGNORECASE))
        else:
            return pattern.lower() in name.lower()
    
    def calculate_relationship_importance(self, relationship: Dict[str, Any],
                                        source_importance: float,
                                        target_importance: float) -> float:
        """Calculate importance score for a relationship."""
        base_score = (source_importance + target_importance) / 2
        
        # Boost certain relationship types
        type_boosts = {
            "CALLS": 1.2,
            "IMPORTS": 1.1,
            "INHERITS": 1.3,
            "IMPLEMENTS": 1.3,
            "USES": 1.0,
            "CONTAINS": 0.8,
            "REFERENCES": 1.0
        }
        
        boost = type_boosts.get(relationship.get("type", ""), 1.0)
        return base_score * boost
    
    def filter_relationships(self, relationships: List[Dict[str, Any]],
                           entity_importance: Dict[str, float],
                           max_relationships: int = 100) -> List[Dict[str, Any]]:
        """Filter relationships based on importance and count."""
        scored = []
        
        for rel in relationships:
            source_id = rel.get("source_id")
            target_id = rel.get("target_id")
            
            source_importance = entity_importance.get(source_id, 0)
            target_importance = entity_importance.get(target_id, 0)
            
            # Skip if both entities have low importance
            if source_importance < 0.2 and target_importance < 0.2:
                continue
            
            importance = self.calculate_relationship_importance(
                rel, source_importance, target_importance
            )
            
            scored.append({
                **rel,
                "importance": importance
            })
        
        # Sort by importance and return top N
        scored.sort(key=lambda r: r["importance"], reverse=True)
        return scored[:max_relationships]
    
    def infer_component_responsibility(self, entity: Dict[str, Any]) -> str:
        """Infer the responsibility of a component from its name and context."""
        name = entity.get("name", "").lower()
        entity_type = entity.get("type", "").lower()
        file_path = entity.get("file", "").lower()
        
        # Responsibility patterns
        responsibilities = {
            "User Management": ["user", "auth", "login", "register", "session"],
            "Data Access": ["repository", "dao", "storage", "persistence", "query"],
            "Business Logic": ["service", "business", "logic", "rule", "process"],
            "Data Validation": ["validator", "validation", "check", "verify"],
            "API Handling": ["controller", "handler", "endpoint", "route", "api"],
            "Data Transformation": ["transformer", "converter", "mapper", "adapter"],
            "Configuration": ["config", "setting", "property", "parameter"],
            "Logging": ["logger", "log", "audit", "trace"],
            "Caching": ["cache", "memo", "store"],
            "Security": ["security", "encrypt", "decrypt", "hash", "token"],
            "Notification": ["notification", "alert", "notify", "message"],
            "Scheduling": ["scheduler", "timer", "cron", "job", "task"],
            "File Operations": ["file", "document", "upload", "download", "export"]
        }
        
        # Check name patterns
        for responsibility, patterns in responsibilities.items():
            if any(pattern in name for pattern in patterns):
                return responsibility
        
        # Check file path patterns
        for responsibility, patterns in responsibilities.items():
            if any(pattern in file_path for pattern in patterns):
                return responsibility
        
        # Default based on entity type
        if entity_type == "class":
            return "Data Structure"
        elif entity_type == "function":
            return "Functional Operation"
        elif entity_type == "interface":
            return "Contract Definition"
        else:
            return "General Component"
    
    def suggest_view_filtering(self, components: List[Dict[str, Any]], 
                             max_components_per_view: int = 20) -> Dict[str, List[str]]:
        """Suggest which components to include in different views."""
        # Group by type and importance
        by_type = defaultdict(list)
        high_importance = []
        
        for comp in components:
            comp_type = comp.get("type", "Unknown")
            importance = comp.get("importance", 0)
            
            by_type[comp_type].append(comp)
            
            if importance > 0.7:
                high_importance.append(comp["entity"]["id"])
        
        # Suggest filtered views
        suggestions = {
            "overview": high_importance[:max_components_per_view],
            "by_type": {}
        }
        
        for comp_type, comps in by_type.items():
            # Sort by importance and take top N
            comps.sort(key=lambda c: c.get("importance", 0), reverse=True)
            suggestions["by_type"][comp_type] = [
                c["entity"]["id"] for c in comps[:max_components_per_view]
            ]
        
        return suggestions
