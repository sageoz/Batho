"""
C4 Model Generator from .ctn artifacts.

Transforms graph.json, repomap.json, and index.json into Structurizr-compatible
C4 models with LLM-friendly context extensions.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Optional

from batho_core.utils.logging import get_logger
from .c4_rules import C4RuleEngine
from .c4.detection.registry import get_registry, auto_register_detectors
from .c4.granularity import (
    RepositoryAnalyzer,
    GranularityDecisionEngine,
    ComponentGroupingManager,
    ViewFilteringEngine,
    GranularityLevel
)

logger = get_logger(__name__, component="c4_generator")


class C4Generator:
    """Generates C4 models from .ctn artifacts."""

    def __init__(self, ctn_dir: Path, index_id: str, rules_dir: Optional[Path] = None):
        self.ctn_dir = ctn_dir
        self.index_id = index_id
        self.versioned_dir = ctn_dir / index_id
        
        # Load artifacts
        self.graph = self._load_graph()
        self.repomap = self._load_repomap()
        self.index_metadata = self._load_index_metadata()
        
        # Initialize rule engine
        self.rule_engine = C4RuleEngine(rules_dir=rules_dir, enable_dynamic=True)
        
        # Initialize detection system
        auto_register_detectors()
        self.detector_registry = get_registry()
        
        # Initialize granularity system
        self.repository_analyzer = RepositoryAnalyzer()
        self.granularity_engine = GranularityDecisionEngine()
        self.grouping_manager = ComponentGroupingManager()
        self.filtering_engine = ViewFilteringEngine()
        
        # Analyze repository for granularity decisions
        self.repository_metrics = self.repository_analyzer.analyze(
            self.graph,
            self.repomap,
            self.index_metadata
        )
        
        # Make granularity decision
        self.granularity_decision = self.granularity_engine.decide_granularity(
            self.repository_metrics
        )
        
        # Detect primary language
        self.primary_language = self.rule_engine.detect_language(self.graph, self.repomap)
        
        # Generate dynamic rules
        self.rule_engine.generate_dynamic_rules(self.graph, self.repomap)
        
        # Run architectural pattern detection
        self._detection_results = self._run_pattern_detection()
        
        # Cache for analysis
        self._import_analysis: Dict[str, Any] | None = None
        self._entity_importance: Dict[str, float] | None = None
        
        logger.info("Initialized C4 generator", 
                   language=self.primary_language,
                   index_id=self.index_id,
                   granularity=self.granularity_decision.level.value,
                   entity_count=self.repository_metrics.entity_count)
        
    def _load_graph(self) -> Dict[str, Any]:
        """Load graph.json artifact."""
        graph_path = self.versioned_dir / "graph.json"
        if not graph_path.exists():
            raise FileNotFoundError(f"Graph not found: {graph_path}")
        return json.loads(graph_path.read_text(encoding="utf-8"))
    
    def _load_repomap(self) -> Dict[str, Any]:
        """Load repomap.json artifact."""
        repomap_path = self.versioned_dir / "repomap.json"
        if not repomap_path.exists():
            raise FileNotFoundError(f"Repomap not found: {repomap_path}")
        return json.loads(repomap_path.read_text(encoding="utf-8"))
    
    def _load_index_metadata(self) -> Dict[str, Any]:
        """Load index metadata."""
        index_path = self.ctn_dir / "index.json"
        if not index_path.exists():
            raise FileNotFoundError(f"Index not found: {index_path}")
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return data["indexes"].get(self.index_id, {})
    
    def generate_c4_model(self) -> Dict[str, Any]:
        """Generate complete C4 model."""
        logger.info("Generating C4 model", index_id=self.index_id)
        
        # Generate each level
        model = {
            "name": self.index_metadata.get("root", Path(self.index_metadata.get("root", "")).name),
            "description": f"C4 model generated from .ctn artifacts",
            "model": {
                "people": self._generate_people(),
                "softwareSystems": self._generate_software_systems(),
                "containers": self._generate_containers(),
                "components": self._generate_components(),
            },
            "views": self._generate_views(),
            "documentation": self._generate_documentation(),
            "llm_extensions": self._generate_llm_extensions(),
            "generation_metadata": {
                "generated_at": self.index_metadata.get("timestamp"),
                "entity_count": self.index_metadata.get("entity_count"),
                "relationship_count": self.index_metadata.get("relationship_count"),
                "stack": self.index_metadata.get("stack", {}),
                "language": self.primary_language,
                "rules_version": "1.0",
                "dynamic_rules_enabled": self.rule_engine.dynamic_generator is not None,
                "pattern_detection": self._detection_results,
                "granularity": {
                    "level": self.granularity_decision.level.value,
                    "reasoning": self.granularity_decision.reasoning,
                    "confidence": self.granularity_decision.confidence,
                    "settings": self.granularity_decision.settings,
                    "metrics": self.repository_metrics.to_dict()
                }
            }
        }
        
        logger.info("C4 model generated", 
                   systems=len(model["model"]["softwareSystems"]),
                   containers=len(model["model"]["containers"]),
                   components=len(model["model"]["components"]))
        
        return model
    
    def _run_pattern_detection(self) -> Dict[str, List[Dict[str, Any]]]:
        """Run all architectural pattern detectors."""
        logger.info("Running architectural pattern detection")
        
        # Get loaded rules for reference
        all_rules = self.rule_engine.rule_loader.load_all_rules()
        
        # Run all detectors
        detection_results = self.detector_registry.detect_all(
            self.graph,
            self.repomap,
            all_rules
        )
        
        # Get summary
        summary = self.detector_registry.get_summary(detection_results)
        logger.info("Pattern detection completed", 
                   total_patterns=summary["total_patterns"],
                   detectors_used=summary["detectors_used"],
                   average_confidence=f"{summary['average_confidence']:.2f}")
        
        # Convert results to serializable format
        serializable_results = {}
        for detector_name, results in detection_results.items():
            serializable_results[detector_name] = [
                result.to_dict() for result in results
            ]
        
        return serializable_results
    
    def _analyze_imports(self) -> Dict[str, Any]:
        """Analyze import patterns to detect external systems using rule engine."""
        if self._import_analysis is not None:
            return self._import_analysis
        
        # Collect all imports
        imports = []
        for rel in self.graph.get("relationships", []):
            if rel.get("type") == "IMPORTS":
                imports.append(rel.get("target", ""))
        
        # Apply external system rules
        detected_systems = self.rule_engine.apply_external_system_rules(
            imports, language=self.primary_language
        )
        
        # Analyze relationships
        import_analysis = {
            "external_systems": defaultdict(list),
            "external_actors": {},
            "internal_imports": defaultdict(set),
            "detected_systems": detected_systems
        }
        
        # Map imports to detected systems
        for rel in self.graph.get("relationships", []):
            if rel.get("type") == "IMPORTS":
                target = rel.get("target", "")
                source = rel.get("source", "")
                
                # Check against detected systems
                for system_type, system_info in detected_systems.items():
                    for pattern in system_info.get("matches", []):
                        if pattern in target:
                            import_analysis["external_systems"][system_type].append({
                                "source": source,
                                "target": target,
                                "pattern": pattern
                            })
                            break
        
        # Create actors for detected external systems
        for system_type, system_info in detected_systems.items():
            actor_id = f"actor-{system_type.lower().replace(' ', '-')}"
            import_analysis["external_actors"][system_type] = {
                "id": actor_id,
                "name": system_info.get("actor_name", system_type),
                "description": system_info.get("actor_description", f"External {system_type}"),
                "type": system_type,
                "import_count": len(system_info.get("matches", [])),
                "confidence": system_info.get("confidence", 1.0)
            }
        
        self._import_analysis = import_analysis
        return import_analysis
    
    def _calculate_entity_importance(self) -> Dict[str, float]:
        """Calculate importance scores for entities."""
        if self._entity_importance is not None:
            return self._entity_importance
        
        # Use repository metrics if available
        if self.repository_metrics.entity_importance:
            self._entity_importance = self.repository_metrics.entity_importance
            return self._entity_importance
        
        # Fallback to manual calculation
        importance = defaultdict(float)
        
        # Base importance from entity type
        type_weights = {
            "class": 1.0,
            "function": 0.5,
            "method": 0.3,
            "module": 0.8,
            "interface": 1.2,
            "entry_point": 1.5,
            "namespace": 0.6
        }
        
        # Score each entity
        for entity in self.graph.get("entities", []):
            entity_id = entity.get("id")
            entity_type = entity.get("type", "").lower()
            
            # Base score from type
            base_score = type_weights.get(entity_type, 0.1)
            importance[entity_id] = base_score
            
            # Bonus for cross-file relationships
            for rel in self.graph.get("relationships", []):
                if rel.get("source_id") == entity_id or rel.get("target_id") == entity_id:
                    # Check if relationship crosses file boundaries
                    source_entity = next((e for e in self.graph.get("entities", []) 
                                        if e.get("id") == rel.get("source_id")), {})
                    target_entity = next((e for e in self.graph.get("entities", []) 
                                        if e.get("id") == rel.get("target_id")), {})
                    
                    if source_entity.get("file") != target_entity.get("file"):
                        importance[entity_id] += 0.2
        
        # Normalize scores
        if importance:
            max_score = max(importance.values())
            if max_score > 0:
                importance = {k: v / max_score for k, v in importance.items()}
        
        self._entity_importance = dict(importance)
        return self._entity_importance
    
    def _generate_people(self) -> List[Dict[str, Any]]:
        """Generate people (external actors) for L1."""
        people = []
        import_analysis = self._analyze_imports()
        
        for actor_id, actor_info in import_analysis["external_actors"].items():
            people.append({
                "id": actor_id,
                "name": actor_info["name"],
                "description": actor_info["description"],
                "type": "Person",
                "properties": {
                    "systemType": actor_info["type"],
                    "importCount": actor_info["import_count"],
                    "usage": f"Used by {actor_info.get('unique_sources', 0)} internal components"
                }
            })
        
        # Add generic user if web framework detected
        stack = self.index_metadata.get("stack", {})
        web_frameworks = ["Flask", "Django", "FastAPI", "Starlette", "Tornado"]
        if any(fw in stack.get("frameworks", []) for fw in web_frameworks):
            people.append({
                "id": "user",
                "name": "User",
                "description": "System user interacting via web interface",
                "type": "Person",
                "properties": {
                    "systemType": "User",
                    "interaction": "HTTP/Web interface"
                }
            })
        
        return people
    
    def _generate_software_systems(self) -> List[Dict[str, Any]]:
        """Generate software systems for L1."""
        repo_root = Path(self.index_metadata.get("root", ""))
        system_name = repo_root.name
        
        # Determine system type from stack
        stack = self.index_metadata.get("stack", {})
        frameworks = stack.get("frameworks", [])
        
        system_type = "Application"
        description = f"Software system: {system_name}"
        
        if any(fw in frameworks for fw in ["Flask", "Django", "FastAPI"]):
            system_type = "Web Application"
            description = f"Web application: {system_name}"
        elif any(fw in frameworks for fw in ["Click", "Typer", "Argparse"]):
            system_type = "CLI Tool"
            description = f"Command-line tool: {system_name}"
        elif "pytest" in frameworks:
            system_type = "Test Framework"
            description = f"Test framework: {system_name}"
        
        return [{
            "id": "system",
            "name": system_name,
            "description": description,
            "type": system_type,
            "properties": {
                "language": stack.get("languages", ["Unknown"])[0].lower(),
                "frameworks": frameworks,
                "buildTool": stack.get("build_tools", ["Unknown"])[0],
                "entityCount": self.index_metadata.get("entity_count", 0),
                "relationshipCount": self.index_metadata.get("relationship_count", 0)
            }
        }]
    
    def _generate_containers(self) -> List[Dict[str, Any]]:
        """Generate containers for L2 using rule engine."""
        containers = []
        stack = self.index_metadata.get("stack", {})
        frameworks = stack.get("frameworks", [])
        
        # Extract directory structure
        directories = set()
        for file_path in self.repomap.get("files", {}).keys():
            parts = Path(file_path).parts
            for i in range(1, len(parts)):
                directories.add("/".join(parts[:i]))
        
        # Apply container rules
        detected_containers = self.rule_engine.apply_container_rules(
            frameworks, list(directories), language=self.primary_language
        )
        
        # Generate containers from detected rules
        for i, container_info in enumerate(detected_containers):
            container_id = f"container-{i+1}"
            containers.append({
                "id": container_id,
                "name": container_info.get("name"),
                "description": f"{container_info.get('type')} container",
                "type": container_info.get("type"),
                "technology": container_info.get("technology", []),
                "systemId": "system",
                "properties": {
                    "rule": container_info.get("rule"),
                    "framework_match": container_info.get("framework_match"),
                    "directory_match": container_info.get("directory_match"),
                    "file_match": container_info.get("file_match"),
                    "matched_frameworks": container_info.get("matched_frameworks", []),
                    "matched_directories": container_info.get("matched_directories", []),
                    "confidence": container_info.get("confidence", 1.0),
                    "language": self.primary_language
                }
            })
        
        return containers
    
    def _generate_components(self) -> List[Dict[str, Any]]:
        """Generate components for L3 using rule engine."""
        # Check if components should be included based on granularity
        settings = self.granularity_decision.settings
        if not settings.get("include_components", True):
            logger.info("Skipping component generation due to granularity settings")
            return []
        
        components = []
        importance = self._calculate_entity_importance()
        
        # Apply component rules
        detected_components = self.rule_engine.apply_component_rules(
            self.graph.get("entities", []), importance, language=self.primary_language
        )
        
        # Filter by importance if required
        importance_threshold = settings.get("importance_threshold", 0.0)
        if importance_threshold > 0:
            detected_components = [
                c for c in detected_components
                if c.get("importance", 0) >= importance_threshold
            ]
        
        # Apply max component limit
        max_components = settings.get("max_components")
        if max_components and len(detected_components) > max_components:
            # Sort by importance and keep top N
            detected_components.sort(
                key=lambda c: c.get("importance", 0),
                reverse=True
            )
            detected_components = detected_components[:max_components]
            logger.info(
                "Limited components by granularity",
                original=len(detected_components),
                limited=max_components
            )
        
        # Generate components from detected rules
        for i, component_info in enumerate(detected_components):
            entity = component_info.get("entity", {})
            component_id = f"component-{i+1}"
            
            # Determine container based on file path
            container_id = self._map_file_to_container(entity.get("file", ""))
            if not container_id:
                # Use first container as default
                containers = self._generate_containers()
                container_id = containers[0]["id"] if containers else "system"
            
            # Generate description
            entity_type = entity.get("type", "").lower()
            description = f"{component_info.get('type', entity_type.capitalize())}: {entity.get('name', 'Unknown')}"
            
            # Add signature for functions/methods
            if entity.get("signature"):
                description += f" - {entity.get('signature')}"
            
            components.append({
                "id": component_id,
                "name": entity.get("name", f"Component-{i+1}"),
                "description": description,
                "type": component_info.get("type", entity_type.capitalize()),
                "technology": [self._get_language_from_file(entity.get("file", ""))],
                "containerId": container_id,
                "properties": {
                    "file": entity.get("file"),
                    "lineRange": f"{entity.get('start_line')}-{entity.get('end_line')}",
                    "importance": component_info.get("importance", 0),
                    "entityId": entity.get("id"),
                    "rule": component_info.get("rule"),
                    "confidence": component_info.get("confidence", 1.0),
                    "language": self.primary_language
                }
            })
        
        logger.info(
            "Generated components",
            count=len(components),
            granularity=self.granularity_decision.level.value
        )
        
        return components
    
    def _map_file_to_container(self, file_path: str) -> str | None:
        """Map a file path to its container."""
        path_parts = Path(file_path).parts
        
        if "test" in path_parts:
            return "test-suite"
        elif any(part in ["docs", "doc"] for part in path_parts):
            return "documentation"
        elif any(part in ["batho_core", "src", "app"] for part in path_parts):
            # Determine specific container based on content
            if any(x in file_path.lower() for x in ["web", "api", "server"]):
                return "web-app" if "web-app" in [c["id"] for c in self._generate_containers()] else None
            elif "cli" in file_path.lower() or "main" in file_path:
                return "cli-tool" if "cli-tool" in [c["id"] for c in self._generate_containers()] else None
            else:
                return "web-app"  # Default to web app if exists
        
        return None
    
    def _get_language_from_file(self, file_path: str) -> str:
        """Extract language from file path."""
        suffix = Path(file_path).suffix.lower()
        lang_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".java": "Java",
            ".go": "Go",
            ".rs": "Rust",
            ".cpp": "C++",
            ".c": "C",
            ".rb": "Ruby",
            ".php": "PHP",
            ".cs": "C#",
        }
        return lang_map.get(suffix, "Unknown")
    
    def _generate_views(self) -> Dict[str, Any]:
        """Generate C4 views."""
        views = {
            "systemContext": [],
            "container": [],
            "component": []
        }
        
        # L1 System Context View
        if self._generate_people():
            views["systemContext"].append({
                "id": "system-context-view",
                "name": "System Context",
                "description": "System context diagram showing the system and external actors",
                "key": "system-context",
                "viewType": "SystemContext",
                "systemId": "system",
                "actors": [p["id"] for p in self._generate_people()]
            })
        
        # L2 Container View
        containers = self._generate_containers()
        if containers:
            views["container"].append({
                "id": "container-view",
                "name": "Container View",
                "description": "Container diagram showing the high-level technology building blocks",
                "key": "containers",
                "viewType": "Container",
                "systemId": "system",
                "containers": [c["id"] for c in containers]
            })
        
        # L3 Component Views (one per significant container)
        container_components = defaultdict(list)
        for comp in self._generate_components():
            container_components[comp.get("containerId")].append(comp["id"])
        
        for container_id, component_ids in container_components.items():
            if len(component_ids) > 1:  # Only create view if multiple components
                container = next((c for c in containers if c["id"] == container_id), {})
                views["component"].append({
                    "id": f"component-view-{container_id}",
                    "name": f"{container.get('name', container_id)} Components",
                    "description": f"Component diagram for {container.get('name', container_id)}",
                    "key": f"components-{container_id}",
                    "viewType": "Component",
                    "containerId": container_id,
                    "components": component_ids
                })
        
        return views
    
    def _generate_documentation(self) -> Dict[str, Any]:
        """Generate documentation sections."""
        return {
            "decisions": [],
            "standards": [],
            "principles": []
        }
    
    def _generate_llm_extensions(self) -> Dict[str, Any]:
        """Generate LLM-friendly context extensions."""
        import_analysis = self._analyze_imports()
        importance = self._calculate_entity_importance()
        
        # Entity summaries
        entity_summaries = []
        for entity in self.graph.get("entities", [])[:20]:  # Top 20 entities
            if importance.get(entity.get("id"), 0) > 0.5:
                entity_summaries.append({
                    "name": entity.get("name"),
                    "type": entity.get("type"),
                    "file": entity.get("file"),
                    "purpose": self._infer_entity_purpose(entity),
                    "complexity": self._estimate_complexity(entity)
                })
        
        # Interaction patterns
        interaction_patterns = []
        for system_type, imports in import_analysis["external_systems"].items():
            if imports:
                interaction_patterns.append({
                    "pattern": f"System interacts with {system_type}",
                    "frequency": len(imports),
                    "components": list(set(imp["source"] for imp in imports))[:5]
                })
        
        # Key algorithms (high importance entities)
        key_algorithms = []
        for entity_id, score in importance.items():
            if score > 0.8:
                entity = next((e for e in self.graph.get("entities", []) 
                             if e.get("id") == entity_id), {})
                if entity:
                    key_algorithms.append({
                        "name": entity.get("name"),
                        "location": f"{entity.get('file')}:{entity.get('start_line')}",
                        "reason": "High connectivity and importance score"
                    })
        
        return {
            "entity_summaries": entity_summaries,
            "interaction_patterns": interaction_patterns,
            "data_flow": self._analyze_data_flow(),
            "key_algorithms": key_algorithms[:10],
            "extension_points": self._identify_extension_points(),
            "complexity_metrics": self._calculate_complexity_metrics(),
            "business_capabilities": self._infer_business_capabilities(),
            "tech_debt_indicators": self._identify_tech_debt()
        }
    
    def _infer_entity_purpose(self, entity: Dict[str, Any]) -> str:
        """Infer the purpose of an entity from its context."""
        name = entity.get("name", "").lower()
        entity_type = entity.get("type", "").lower()
        
        # Common patterns
        if "test" in name or entity_type == "test":
            return "Testing functionality"
        elif "config" in name or "setting" in name:
            return "Configuration management"
        elif "util" in name or "helper" in name:
            return "Utility functionality"
        elif "model" in name or entity_type == "class":
            return "Data modeling"
        elif "service" in name:
            return "Business logic service"
        elif "controller" in name or "view" in name:
            return "Request handling"
        elif entity_type == "function":
            return "Functional operation"
        else:
            return f"{entity_type} implementation"
    
    def _estimate_complexity(self, entity: Dict[str, Any]) -> str:
        """Estimate complexity of an entity."""
        lines = entity.get("end_line", 0) - entity.get("start_line", 0)
        
        if lines < 10:
            return "Low"
        elif lines < 30:
            return "Medium"
        elif lines < 100:
            return "High"
        else:
            return "Very High"
    
    def _analyze_data_flow(self) -> List[Dict[str, Any]]:
        """Analyze data flow patterns."""
        flows = []
        
        # Look for common data flow patterns
        for rel in self.graph.get("relationships", []):
            if rel.get("type") == "CALLS":
                source = next((e for e in self.graph.get("entities", []) 
                             if e.get("id") == rel.get("source_id")), {})
                target = next((e for e in self.graph.get("entities", []) 
                             if e.get("id") == rel.get("target_id")), {})
                
                if source and target:
                    flows.append({
                        "from": source.get("name"),
                        "to": target.get("name"),
                        "type": "Function call",
                        "pattern": self._classify_data_flow(source, target)
                    })
        
        return flows[:10]  # Top 10 flows
    
    def _classify_data_flow(self, source: Dict[str, Any], target: Dict[str, Any]) -> str:
        """Classify the type of data flow."""
        source_name = source.get("name", "").lower()
        target_name = target.get("name", "").lower()
        
        if "db" in target_name or "database" in target_name:
            return "Database operation"
        elif "api" in target_name or "http" in target_name:
            return "API call"
        elif "render" in target_name or "template" in target_name:
            return "View rendering"
        elif "validate" in target_name or "check" in target_name:
            return "Validation"
        else:
            return "Data transformation"
    
    def _identify_extension_points(self) -> List[Dict[str, Any]]:
        """Identify potential extension points."""
        extensions = []
        
        # Look for plugin patterns, hooks, or abstract classes
        for entity in self.graph.get("entities", []):
            name = entity.get("name", "").lower()
            entity_type = entity.get("type", "").lower()
            
            if any(keyword in name for keyword in ["plugin", "hook", "extension", "adapter"]):
                extensions.append({
                    "name": entity.get("name"),
                    "location": f"{entity.get('file')}:{entity.get('start_line')}",
                    "type": "Extension point",
                    "description": "Potential plugin or extension hook"
                })
            elif entity_type == "interface" or "abstract" in name:
                extensions.append({
                    "name": entity.get("name"),
                    "location": f"{entity.get('file')}:{entity.get('start_line')}",
                    "type": "Interface",
                    "description": "Abstract interface for implementation"
                })
        
        return extensions[:5]
    
    def _calculate_complexity_metrics(self) -> Dict[str, Any]:
        """Calculate complexity metrics."""
        entities = self.graph.get("entities", [])
        relationships = self.graph.get("relationships", [])
        
        # Entity type distribution
        type_counts = Counter(e.get("type", "unknown") for e in entities)
        
        # Relationship type distribution
        rel_counts = Counter(r.get("type", "unknown") for r in relationships)
        
        # File distribution
        file_counts = Counter(e.get("file", "unknown") for e in entities)
        
        return {
            "entity_types": dict(type_counts.most_common(10)),
            "relationship_types": dict(rel_counts.most_common(10)),
            "files_with_most_entities": [
                {"file": Path(f).name, "count": count} 
                for f, count in file_counts.most_common(5)
            ],
            "average_entities_per_file": len(entities) / max(len(file_counts), 1),
            "relationship_density": len(relationships) / max(len(entities), 1)
        }
    
    def _infer_business_capabilities(self) -> List[str]:
        """Infer business capabilities from the codebase."""
        capabilities = []
        
        # Analyze file and directory names
        repo_root = Path(self.index_metadata.get("root", ""))
        
        # Common business capability indicators
        capability_patterns = {
            "User Management": ["user", "auth", "login", "register"],
            "Data Processing": ["process", "transform", "analyze", "compute"],
            "Reporting": ["report", "analytics", "dashboard", "metrics"],
            "Communication": ["email", "notification", "message", "chat"],
            "File Management": ["file", "upload", "download", "storage"],
            "API Management": ["api", "endpoint", "service", "rest"],
            "Configuration": ["config", "setting", "preference"],
            "Testing": ["test", "spec", "mock", "fixture"]
        }
        
        # Scan for patterns
        for capability, patterns in capability_patterns.items():
            for pattern in patterns:
                if any(pattern in str(p).lower() for p in repo_root.rglob("*")):
                    capabilities.append(capability)
                    break
        
        return list(set(capabilities))
    
    def _identify_tech_debt(self) -> List[Dict[str, Any]]:
        """Identify potential technical debt indicators."""
        tech_debt = []
        
        # Large files
        file_sizes = defaultdict(int)
        for entity in self.graph.get("entities", []):
            file_sizes[entity.get("file", "")] += 1
        
        for file_path, count in file_sizes.items():
            if count > 50:  # Too many entities in one file
                tech_debt.append({
                    "type": "Large File",
                    "location": file_path,
                    "description": f"File contains {count} entities (threshold: 50)",
                    "severity": "Medium"
                })
        
        # Deep nesting (from line numbers)
        for entity in self.graph.get("entities", []):
            line_span = entity.get("end_line", 0) - entity.get("start_line", 0)
            if line_span > 200:  # Very long entity
                tech_debt.append({
                    "type": "Complex Entity",
                    "location": f"{entity.get('file')}:{entity.get('start_line')}",
                    "description": f"Entity spans {line_span} lines (threshold: 200)",
                    "severity": "High"
                })
        
        return tech_debt[:10]  # Top 10 issues
