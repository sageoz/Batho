"""
Dynamic rule generation from repository analysis.

Analyzes repository patterns to generate new rules with confidence scores.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from batho_core.utils.logging import get_logger

logger = get_logger(__name__, component="dynamic_rule_generator")


class DynamicRuleGenerator:
    """Generates rules dynamically from repository analysis."""
    
    def __init__(self, dynamic_dir: Path):
        """
        Initialize dynamic rule generator.
        
        Args:
            dynamic_dir: Directory to store dynamic rules.
        """
        self.dynamic_dir = Path(dynamic_dir)
        self.dynamic_dir.mkdir(parents=True, exist_ok=True)
        self.patterns_file = self.dynamic_dir / "detected_patterns.json"
        
        # Load existing patterns
        self._load_patterns()
        
        # Pattern detection thresholds
        self.min_occurrences = 3  # Minimum occurrences to consider a pattern
        self.confidence_threshold = 0.6  # Minimum confidence to save a rule
        
    def analyze_repository(self, graph: Dict[str, Any], 
                          repomap: Dict[str, Any],
                          language: str) -> Dict[str, Any]:
        """
        Analyze repository to generate dynamic rules.
        
        Args:
            graph: Code graph data.
            repomap: Repository map data.
            language: Primary language of the repository.
            
        Returns:
            Generated dynamic rules.
        """
        logger.info("Analyzing repository for dynamic rules", language=language)
        
        # Analyze import patterns
        import_patterns = self._analyze_import_patterns(graph, language)
        
        # Analyze naming conventions
        naming_patterns = self._analyze_naming_conventions(graph, language)
        
        # Analyze directory structures
        structure_patterns = self._analyze_directory_structure(repomap, language)
        
        # Analyze framework usage
        framework_patterns = self._analyze_framework_usage(graph, language)
        
        # Combine all patterns
        dynamic_rules = {
            "external_systems": import_patterns.get("external_systems", []),
            "containers": structure_patterns.get("containers", []),
            "components": naming_patterns.get("components", []),
            "frameworks": framework_patterns,
            "generated_at": time.time(),
            "language": language
        }
        
        # Save patterns
        self._save_patterns(dynamic_rules)
        
        logger.info("Generated dynamic rules",
                   external_systems=len(dynamic_rules["external_systems"]),
                   containers=len(dynamic_rules["containers"]),
                   components=len(dynamic_rules["components"]))
        
        return dynamic_rules
    
    def _analyze_import_patterns(self, graph: Dict[str, Any], 
                               language: str) -> Dict[str, Any]:
        """Analyze import patterns to detect external systems."""
        external_systems = []
        
        # Collect all imports
        imports = []
        for rel in graph.get("relationships", []):
            if rel.get("type") == "IMPORTS":
                target = rel.get("target", "")
                if target:
                    imports.append(target)
        
        # Find frequent import patterns
        import_counter = Counter(imports)
        
        # Group imports by potential system
        system_groups = self._group_imports_by_system(imports, language)
        
        # Generate rules for detected systems
        for system_name, system_imports in system_groups.items():
            if len(system_imports) >= self.min_occurrences:
                # Calculate confidence based on frequency and consistency
                confidence = self._calculate_import_confidence(
                    system_imports, import_counter, len(imports)
                )
                
                if confidence >= self.confidence_threshold:
                    rule = {
                        "id": f"dynamic-{system_name.lower().replace(' ', '-')}",
                        "name": f"Dynamic {system_name} Detection",
                        "description": f"Auto-detected {system_name} usage",
                        "patterns": list(set(system_imports)),
                        "system_type": self._infer_system_type(system_name),
                        "actor_name": system_name,
                        "actor_description": f"Detected {system_name} system",
                        "confidence": confidence,
                        "created_at": time.time(),
                        "usage_count": len(system_imports)
                    }
                    external_systems.append(rule)
        
        return {"external_systems": external_systems}
    
    def _analyze_naming_conventions(self, graph: Dict[str, Any], 
                                  language: str) -> Dict[str, Any]:
        """Analyze naming conventions to detect component patterns."""
        components = []
        
        # Collect entity names by type
        entity_names = defaultdict(list)
        for entity in graph.get("entities", []):
            entity_type = entity.get("type", "").lower()
            name = entity.get("name", "")
            if name and entity_type in ["class", "function", "interface"]:
                entity_names[entity_type].append(name)
        
        # Find naming patterns
        for entity_type, names in entity_names.items():
            # Extract suffixes and prefixes
            suffixes = self._extract_suffixes(names)
            prefixes = self._extract_prefixes(names)
            
            # Generate component rules for common patterns
            for suffix, count in suffixes.items():
                if count >= self.min_occurrences:
                    component_type = self._infer_component_type_from_suffix(suffix)
                    if component_type:
                        confidence = min(count / len(names), 1.0)
                        
                        rule = {
                            "id": f"dynamic-{suffix.lower()}-component",
                            "name": f"Dynamic {suffix} Component Detection",
                            "description": f"Auto-detected {suffix} component pattern",
                            "entity_types": [entity_type],
                            "importance_threshold": 0.4,
                            "max_per_file": 5,
                            "component_type": component_type,
                            "name_patterns": [f"*{suffix}"],
                            "confidence": confidence,
                            "created_at": time.time(),
                            "usage_count": count
                        }
                        components.append(rule)
        
        return {"components": components}
    
    def _analyze_directory_structure(self, repomap: Dict[str, Any], 
                                    language: str) -> Dict[str, Any]:
        """Analyze directory structure to detect container patterns."""
        containers = []
        
        # Collect directory paths
        directories = set()
        for file_path in repomap.get("files", {}).keys():
            parts = Path(file_path).parts
            for i in range(1, len(parts)):
                directories.add("/".join(parts[:i]))
        
        # Find common directory patterns
        dir_counter = Counter(directories)
        
        # Group directories by purpose
        dir_groups = self._group_directories_by_purpose(directories, language)
        
        # Generate container rules
        for purpose, dirs in dir_groups.items():
            if len(dirs) >= self.min_occurrences:
                confidence = min(len(dirs) / len(directories), 1.0)
                
                rule = {
                    "id": f"dynamic-{purpose.lower().replace(' ', '-')}-container",
                    "name": f"Dynamic {purpose} Container Detection",
                    "description": f"Auto-detected {purpose} container pattern",
                    "directory_patterns": list(dirs),
                    "container_type": purpose,
                    "container_name": purpose,
                    "technology": [language],
                    "confidence": confidence,
                    "created_at": time.time(),
                    "usage_count": len(dirs)
                }
                containers.append(rule)
        
        return {"containers": containers}
    
    def _analyze_framework_usage(self, graph: Dict[str, Any], 
                                language: str) -> List[Dict[str, Any]]:
        """Analyze framework usage patterns."""
        frameworks = []
        
        # Look for framework-specific patterns
        framework_indicators = self._get_framework_indicators(language)
        
        for framework, patterns in framework_indicators.items():
            matches = []
            
            # Check imports
            for rel in graph.get("relationships", []):
                if rel.get("type") == "IMPORTS":
                    target = rel.get("target", "")
                    for pattern in patterns.get("imports", []):
                        if pattern in target:
                            matches.append(("import", pattern))
            
            # Check file names
            for entity in graph.get("entities", []):
                file_path = entity.get("file", "")
                for pattern in patterns.get("files", []):
                    if pattern in file_path:
                        matches.append(("file", pattern))
            
            # Check entity names
            for entity in graph.get("entities", []):
                name = entity.get("name", "")
                for pattern in patterns.get("names", []):
                    if pattern in name:
                        matches.append(("name", pattern))
            
            if len(matches) >= self.min_occurrences:
                confidence = min(len(matches) / 10, 1.0)  # Normalize to max 10 matches
                
                framework_info = {
                    "framework": framework,
                    "matches": matches,
                    "confidence": confidence,
                    "usage_count": len(matches)
                }
                frameworks.append(framework_info)
        
        return frameworks
    
    def _group_imports_by_system(self, imports: List[str], 
                                language: str) -> Dict[str, List[str]]:
        """Group imports by potential external system."""
        groups = defaultdict(list)
        
        # Known system prefixes
        system_prefixes = {
            "Database": ["sql", "db", "mongo", "redis", "postgres", "mysql", "oracle"],
            "Message Queue": ["kafka", "rabbit", "sqs", "pubsub", "nats", "queue", "celery"],
            "Cloud": ["aws", "azure", "gcp", "google.cloud", "boto", "cloudflare"],
            "HTTP Client": ["http", "request", "fetch", "axios", "urllib"],
            "Authentication": ["auth", "jwt", "oauth", "passport", "login"],
            "Email": ["mail", "smtp", "sendgrid", "mailgun", "ses"],
            "Cache": ["cache", "memcache", "redis"],
            "Search": ["elastic", "solr", "algolia", "search"],
            "Monitoring": ["prometheus", "datadog", "newrelic", "metric"]
        }
        
        for imp in imports:
            imp_lower = imp.lower()
            
            # Check against known prefixes
            for system, prefixes in system_prefixes.items():
                for prefix in prefixes:
                    if prefix in imp_lower:
                        groups[system].append(imp)
                        break
            
            # Try to extract from domain patterns
            domain_match = re.search(r'([a-z]+\.)+[a-z]+', imp_lower)
            if domain_match:
                domain = domain_match.group()
                # Group by top-level domain
                parts = domain.split('.')
                if len(parts) >= 2:
                    potential_system = parts[-2].title()
                    groups[potential_system].append(imp)
        
        return dict(groups)
    
    def _extract_suffixes(self, names: List[str]) -> Counter:
        """Extract common suffixes from names."""
        suffixes = Counter()
        
        for name in names:
            # Look for common suffix patterns
            words = re.findall(r'[A-Z][a-z]*|[a-z]+', name)
            if len(words) > 1:
                suffix = words[-1]
                if len(suffix) > 2:  # Ignore very short suffixes
                    suffixes[suffix] += 1
            elif len(words) == 1 and len(words[0]) > 2:
                # Single-word names count as both prefix and suffix
                suffixes[words[0]] += 1
        
        return suffixes
    
    def _extract_prefixes(self, names: List[str]) -> Counter:
        """Extract common prefixes from names."""
        prefixes = Counter()
        
        for name in names:
            # Look for common prefix patterns
            words = re.findall(r'[A-Z][a-z]*|[a-z]+', name)
            if len(words) > 1:
                prefix = words[0]
                if len(prefix) > 2:  # Ignore very short prefixes
                    prefixes[prefix] += 1
        
        return prefixes
    
    def _infer_component_type_from_suffix(self, suffix: str) -> Optional[str]:
        """Infer component type from suffix."""
        suffix_map = {
            "Controller": "Controller",
            "Service": "Service",
            "Repository": "Repository",
            "Manager": "Service",
            "Handler": "Controller",
            "Component": "Component",
            "Util": "Utility",
            "Helper": "Utility",
            "Config": "Configuration",
            "Model": "Model",
            "Entity": "Model",
            "Dto": "Model",
            "Validator": "Validator",
            "Middleware": "Middleware",
            "Filter": "Middleware",
            "Interceptor": "Middleware",
            "Listener": "Observer",
            "Observer": "Observer",
            "Client": "Client",
            "Factory": "Factory",
            "Builder": "Factory"
        }
        
        return suffix_map.get(suffix)
    
    def _infer_system_type(self, system_name: str) -> str:
        """Infer system type from system name."""
        if "db" in system_name.lower() or "database" in system_name.lower():
            return "Database"
        elif "queue" in system_name.lower() or "kafka" in system_name.lower():
            return "MessageQueue"
        elif "auth" in system_name.lower():
            return "Authentication"
        elif "mail" in system_name.lower():
            return "Email"
        elif "cloud" in system_name.lower():
            return "CloudPlatform"
        elif "cache" in system_name.lower():
            return "Cache"
        elif "search" in system_name.lower():
            return "SearchEngine"
        elif "http" in system_name.lower() or "api" in system_name.lower():
            return "ExternalAPI"
        else:
            return "ExternalSystem"
    
    def _group_directories_by_purpose(self, directories: Set[str], 
                                    language: str) -> Dict[str, Set[str]]:
        """Group directories by their likely purpose."""
        groups = defaultdict(set)
        
        purpose_patterns = {
            "API": ["api", "rest", "endpoint", "route"],
            "Service": ["service", "services", "business"],
            "Model": ["model", "models", "entity", "entities", "dto"],
            "Controller": ["controller", "controllers", "handler", "handlers"],
            "Repository": ["repository", "repositories", "dao", "persistence"],
            "Test": ["test", "tests", "spec", "specs"],
            "Config": ["config", "conf", "configuration"],
            "Util": ["util", "utils", "helper", "helpers", "common"],
            "Static": ["static", "assets", "public", "resource"],
            "View": ["view", "views", "template", "templates"],
            "Component": ["component", "components"]
        }
        
        for directory in directories:
            dir_lower = directory.lower()
            
            for purpose, patterns in purpose_patterns.items():
                for pattern in patterns:
                    if f"/{pattern}/" in f"/{dir_lower}/" or dir_lower.endswith(f"/{pattern}"):
                        groups[purpose].add(directory)
                        break
        
        return dict(groups)
    
    def _get_framework_indicators(self, language: str) -> Dict[str, Dict[str, List[str]]]:
        """Get framework-specific indicators for a language."""
        indicators = {
            "python": {
                "Django": {
                    "imports": ["django", "django.db", "django.contrib"],
                    "files": ["settings.py", "urls.py", "wsgi.py", "manage.py"],
                    "names": ["*View", "*Model", "*Form"]
                },
                "Flask": {
                    "imports": ["flask"],
                    "files": ["app.py", "wsgi.py"],
                    "names": ["*Blueprint", "*Route"]
                },
                "FastAPI": {
                    "imports": ["fastapi"],
                    "files": ["main.py"],
                    "names": ["*Router", "*APIRouter"]
                }
            },
            "java": {
                "Spring": {
                    "imports": ["org.springframework"],
                    "files": ["Application.java", "*Application.java"],
                    "names": ["*Controller", "*Service", "*Repository"]
                }
            },
            "javascript": {
                "Express": {
                    "imports": ["express"],
                    "files": ["app.js", "server.js"],
                    "names": ["router", "route"]
                },
                "React": {
                    "imports": ["react"],
                    "files": ["App.jsx", "index.jsx"],
                    "names": ["*Component", "*Container"]
                }
            },
            "typescript": {
                "NestJS": {
                    "imports": ["@nestjs"],
                    "files": ["main.ts", "app.module.ts"],
                    "names": ["*Controller", "*Service", "*Module"]
                },
                "Angular": {
                    "imports": ["@angular"],
                    "files": ["app.module.ts", "angular.json"],
                    "names": ["*Component", "*Service", "*Module"]
                }
            },
            "go": {
                "Gin": {
                    "imports": ["github.com/gin-gonic/gin"],
                    "files": ["main.go", "router.go"],
                    "names": ["*Handler", "*Middleware"]
                }
            }
        }
        
        return indicators.get(language, {})
    
    def _calculate_import_confidence(self, system_imports: List[str],
                                   import_counter: Counter,
                                   total_imports: int) -> float:
        """Calculate confidence score for import-based rule."""
        # Base confidence from frequency
        frequency = len(system_imports) / total_imports
        
        # Boost for consistency (same prefix)
        prefixes = [imp.split('.')[0] for imp in system_imports if '.' in imp]
        prefix_consistency = len(set(prefixes)) / max(len(prefixes), 1)
        consistency_score = 1 - (prefix_consistency - 1)  # Invert so lower is better
        
        # Combine scores
        confidence = (frequency * 0.6) + (consistency_score * 0.4)
        
        return min(confidence, 1.0)
    
    def _load_patterns(self) -> None:
        """Load existing dynamic patterns."""
        if self.patterns_file.exists():
            try:
                with open(self.patterns_file, 'r', encoding='utf-8') as f:
                    self.patterns = json.load(f)
            except Exception as e:
                logger.warning("Failed to load dynamic patterns", error=str(e))
                self.patterns = {}
        else:
            self.patterns = {}
    
    def _save_patterns(self, dynamic_rules: Dict[str, Any]) -> None:
        """Save generated patterns to the pattern store."""
        # Update usage counts for existing patterns
        for rule_type, rules in dynamic_rules.items():
            # Skip non-list values like generated_at and language
            if not isinstance(rules, list):
                continue
                
            if rule_type not in self.patterns:
                self.patterns[rule_type] = []
            
            for new_rule in rules:
                # Check if rule already exists
                existing = None
                for i, rule in enumerate(self.patterns[rule_type]):
                    if rule.get("id") == new_rule.get("id"):
                        existing = i
                        break
                
                if existing is not None:
                    # Update existing rule
                    self.patterns[rule_type][existing]["usage_count"] += new_rule.get("usage_count", 0)
                    self.patterns[rule_type][existing]["confidence"] = max(
                        self.patterns[rule_type][existing]["confidence"],
                        new_rule.get("confidence", 0)
                    )
                    self.patterns[rule_type][existing]["last_seen"] = time.time()
                else:
                    # Add new rule
                    self.patterns[rule_type].append(new_rule)
        
        # Save to file
        try:
            with open(self.patterns_file, 'w', encoding='utf-8') as f:
                json.dump(self.patterns, f, indent=2, sort_keys=True)
        except Exception as e:
            logger.error("Failed to save dynamic patterns", error=str(e))
    
    def get_dynamic_rules(self) -> Dict[str, Any]:
        """Get all dynamic rules."""
        return self.patterns
    
    def clear_patterns(self) -> None:
        """Clear all dynamic patterns."""
        self.patterns = {}
        if self.patterns_file.exists():
            self.patterns_file.unlink()
        logger.info("Cleared all dynamic patterns")
