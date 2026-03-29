"""
LLM-friendly Context Extensions for C4 Models.

Generates additional context and summaries optimized for LLM consumption.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Set, Tuple
from pathlib import Path

from batho_core.config import get_config_cached
from batho_core.utils.logging import get_logger


class LLMExtensionGenerator:
    """Generates LLM-friendly extensions for C4 models."""
    
    def __init__(self, graph: Dict[str, Any], repomap: Dict[str, Any], 
                 index_metadata: Dict[str, Any], enable_llm: bool | None = None):
        self.graph = graph
        self.repomap = repomap
        self.index_metadata = index_metadata
        
        # Get LLM flag from config if not explicitly provided
        if enable_llm is None:
            enable_llm = get_config_cached().get("flags", {}).get("enable_llm", False)
        
        self.enable_llm = enable_llm
        self.logger = get_logger(__name__, component="llm_extensions")
        
        if not self.enable_llm:
            self.logger.info("llm_extensions_disabled", 
                           reason="enable_llm flag is False")
        
        # Caches for analysis
        self._entity_clusters: Dict[str, List[str]] | None = None
        self._business_domains: Dict[str, List[str]] | None = None
        self._api_endpoints: List[Dict[str, Any]] | None = None
        self._data_models: List[Dict[str, Any]] | None = None
    
    def generate_extensions(self) -> Dict[str, Any]:
        """Generate all LLM extensions."""
        return {
            "executive_summary": self._generate_executive_summary(),
            "architecture_overview": self._generate_architecture_overview(),
            "key_workflows": self._analyze_key_workflows(),
            "data_architecture": self._analyze_data_architecture(),
            "api_catalog": self._generate_api_catalog(),
            "business_domains": self._identify_business_domains(),
            "technical_risks": self._assess_technical_risks(),
            "scalability_considerations": self._analyze_scalability(),
            "security_posture": self._assess_security_posture(),
            "development_guidelines": self._generate_dev_guidelines(),
            "onboarding_guide": self._generate_onboarding_guide(),
            "change_impact_analysis": self._generate_change_impact_analysis(),
            "performance_hotspots": self._identify_performance_hotspots(),
            "integration_points": self._map_integration_points(),
            "glossary": self._generate_glossary()
        }
    
    def _generate_executive_summary(self) -> Dict[str, Any]:
        """Generate executive summary for business stakeholders."""
        stack = self.index_metadata.get("stack", {})
        frameworks = stack.get("frameworks", [])
        languages = stack.get("languages", [])
        
        # Determine system type
        system_type = "Application"
        if any(fw in frameworks for fw in ["Flask", "Django", "FastAPI"]):
            system_type = "Web Application"
        elif any(fw in frameworks for fw in ["Click", "Typer", "Argparse"]):
            system_type = "CLI Tool"
        
        # Count key metrics
        entity_count = self.index_metadata.get("entity_count", 0)
        file_count = self.index_metadata.get("file_count", 0)
        
        return {
            "system_name": Path(self.index_metadata.get("root", "")).name,
            "system_type": system_type,
            "primary_language": languages[0] if languages else "Unknown",
            "key_frameworks": frameworks[:5],
            "size": {
                "entities": entity_count,
                "files": file_count,
                "lines_of_code": self.index_metadata.get("metrics", {}).get("loc_total", 0)
            },
            "purpose": self._infer_system_purpose(),
            "complexity": self._assess_complexity_level(),
            "team_size_estimate": self._estimate_team_size(),
            "business_value": self._infer_business_value()
        }
    
    def _generate_architecture_overview(self) -> Dict[str, Any]:
        """Generate high-level architecture overview."""
        # Analyze architectural patterns
        patterns = self._detect_architectural_patterns()
        
        # Identify main layers
        layers = self._identify_architectural_layers()
        
        # Analyze dependencies
        dependencies = self._analyze_dependencies()
        
        return {
            "architectural_style": patterns["style"],
            "patterns_used": patterns["patterns"],
            "layers": layers,
            "key_principles": self._extract_design_principles(),
            "major_dependencies": dependencies["external"],
            "internal_coupling": dependencies["internal"],
            "technology_stack": {
                "presentation": self._get_presentation_tech(),
                "business": self._get_business_tech(),
                "data": self._get_data_tech(),
                "infrastructure": self._get_infrastructure_tech()
            }
        }
    
    def _analyze_key_workflows(self) -> List[Dict[str, Any]]:
        """Analyze key user workflows through the system."""
        workflows = []
        
        # Look for common workflow patterns
        entry_points = [e for e in self.graph.get("entities", []) 
                       if e.get("type") == "entry_point"]
        
        for entry in entry_points[:5]:  # Top 5 entry points
            workflow = self._trace_workflow(entry)
            if workflow:
                workflows.append(workflow)
        
        return workflows
    
    def _analyze_data_architecture(self) -> Dict[str, Any]:
        """Analyze data architecture patterns."""
        # Find data models
        data_models = self._find_data_models()
        
        # Analyze data flow
        data_flow = self._trace_data_flow()
        
        # Identify persistence mechanisms
        persistence = self._identify_persistence_mechanisms()
        
        return {
            "data_models": {
                "count": len(data_models),
                "examples": data_models[:5],
                "patterns": self._identify_data_patterns(data_models)
            },
            "data_flow": data_flow,
            "persistence": persistence,
            "data_integrity": self._assess_data_integrity(),
            "caching_strategy": self._identify_caching_strategy()
        }
    
    def _generate_api_catalog(self) -> List[Dict[str, Any]]:
        """Generate catalog of API endpoints."""
        if self._api_endpoints is None:
            self._api_endpoints = self._extract_api_endpoints()
        
        return self._api_endpoints
    
    def _identify_business_domains(self) -> Dict[str, Any]:
        """Identify business domains in the codebase."""
        if self._business_domains is None:
            self._business_domains = self._cluster_by_business_domain()
        
        return {
            "domains": self._business_domains,
            "domain_relationships": self._map_domain_relationships(),
            "bounded_contexts": self._identify_bounded_contexts()
        }
    
    def _assess_technical_risks(self) -> List[Dict[str, Any]]:
        """Assess technical risks in the codebase."""
        risks = []
        
        # Check for outdated dependencies
        outdated = self._check_outdated_dependencies()
        if outdated:
            risks.append({
                "type": "Outdated Dependencies",
                "severity": "Medium",
                "description": f"Found {len(outdated)} potentially outdated dependencies",
                "examples": outdated[:3],
                "mitigation": "Regular dependency updates and security scanning"
            })
        
        # Check for complex components
        complex = self._find_complex_components()
        if complex:
            risks.append({
                "type": "High Complexity",
                "severity": "High",
                "description": f"Found {len(complex)} highly complex components",
                "examples": complex[:3],
                "mitigation": "Refactoring into smaller, focused components"
            })
        
        # Check for security anti-patterns
        security_issues = self._check_security_patterns()
        if security_issues:
            risks.append({
                "type": "Security Concerns",
                "severity": "Critical",
                "description": f"Found {len(security_issues)} potential security issues",
                "examples": security_issues,
                "mitigation": "Security review and implementation of best practices"
            })
        
        return risks
    
    def _analyze_scalability(self) -> Dict[str, Any]:
        """Analyze scalability considerations."""
        return {
            "current_limitations": self._identify_scalability_limitations(),
            "scaling_factors": self._identify_scaling_factors(),
            "bottlenecks": self._identify_bottlenecks(),
            "recommendations": self._generate_scalability_recommendations(),
            "horizontal_scaling": self._assess_horizontal_scaling(),
            "vertical_scaling": self._assess_vertical_scaling()
        }
    
    def _assess_security_posture(self) -> Dict[str, Any]:
        """Assess security posture of the system."""
        return {
            "authentication": self._check_authentication(),
            "authorization": self._check_authorization(),
            "data_protection": self._check_data_protection(),
            "input_validation": self._check_input_validation(),
            "dependencies": self._check_dependency_security(),
            "compliance": self._check_compliance(),
            "recommendations": self._generate_security_recommendations()
        }
    
    def _generate_dev_guidelines(self) -> Dict[str, Any]:
        """Generate development guidelines."""
        return {
            "coding_standards": self._extract_coding_standards(),
            "testing_practices": self._analyze_testing_practices(),
            "code_review_checklist": self._generate_review_checklist(),
            "common_patterns": self._document_common_patterns(),
            "anti_patterns": self._document_anti_patterns(),
            "tooling": self._list_development_tooling()
        }
    
    def _generate_onboarding_guide(self) -> Dict[str, Any]:
        """Generate developer onboarding guide."""
        return {
            "quick_start": self._create_quick_start(),
            "development_setup": self._document_dev_setup(),
            "key_concepts": self._extract_key_concepts(),
            "common_tasks": self._list_common_tasks(),
            "resources": self._list_learning_resources(),
            "contacts": self._identify_domain_experts()
        }
    
    def _generate_change_impact_analysis(self) -> Dict[str, Any]:
        """Generate change impact analysis framework."""
        # Analyze coupling and cohesion
        coupling = self._analyze_coupling()
        cohesion = self._analyze_cohesion()
        
        return {
            "high_impact_areas": self._identify_high_impact_areas(),
            "coupling_analysis": coupling,
            "cohesion_analysis": cohesion,
            "change_propagation": self._map_change_propagation(),
            "testing_strategy": self._recommend_testing_strategy()
        }
    
    def _identify_performance_hotspots(self) -> List[Dict[str, Any]]:
        """Identify potential performance hotspots."""
        hotspots = []
        
        # Look for database queries in loops
        db_in_loops = self._find_database_in_loops()
        if db_in_loops:
            hotspots.append({
                "type": "N+1 Query Problem",
                "locations": db_in_loops,
                "impact": "High",
                "recommendation": "Use batch queries or eager loading"
            })
        
        # Look for large file processing
        file_processing = self._find_large_file_processing()
        if file_processing:
            hotspots.append({
                "type": "Large File Processing",
                "locations": file_processing,
                "impact": "Medium",
                "recommendation": "Implement streaming or chunked processing"
            })
        
        # Look for synchronous I/O
        sync_io = self._find_synchronous_io()
        if sync_io:
            hotspots.append({
                "type": "Synchronous I/O",
                "locations": sync_io,
                "impact": "Medium",
                "recommendation": "Use async/await patterns"
            })
        
        return hotspots
    
    def _map_integration_points(self) -> List[Dict[str, Any]]:
        """Map external integration points."""
        integrations = []
        
        # Analyze import relationships
        for rel in self.graph.get("relationships", []):
            if rel.get("type") == "IMPORTS":
                target = rel.get("target", "")
                
                # Categorize integration type
                if any(pattern in target.lower() for pattern in ["http", "api", "rest"]):
                    integration_type = "REST API"
                elif any(pattern in target.lower() for pattern in ["sql", "db", "database"]):
                    integration_type = "Database"
                elif any(pattern in target.lower() for pattern in ["message", "queue", "kafka"]):
                    integration_type = "Message Queue"
                elif any(pattern in target.lower() for pattern in ["file", "path", "os"]):
                    integration_type = "File System"
                else:
                    integration_type = "Library"
                
                integrations.append({
                    "type": integration_type,
                    "target": target,
                    "source": rel.get("source", ""),
                    "criticality": self._assess_integration_criticality(target)
                })
        
        # Group by type and deduplicate
        grouped = defaultdict(list)
        for integration in integrations:
            key = f"{integration['type']}:{integration['target']}"
            if key not in [f"{i['type']}:{i['target']}" for i in grouped[integration['type']]]:
                grouped[integration['type']].append(integration)
        
        return [{"type": k, "integrations": v} for k, v in grouped.items()]
    
    def _generate_glossary(self) -> Dict[str, str]:
        """Generate glossary of technical terms."""
        glossary = {}
        
        # Extract from entity names
        for entity in self.graph.get("entities", [])[:100]:
            name = entity.get("name", "")
            if len(name) > 3 and name.isalnum():
                # Try to infer meaning from context
                meaning = self._infer_term_meaning(name, entity)
                if meaning and name not in glossary:
                    glossary[name] = meaning
        
        # Add common architectural terms
        architectural_terms = {
            "API": "Application Programming Interface - Contract for software communication",
            "ORM": "Object-Relational Mapping - Technique for converting data between incompatible systems",
            "CLI": "Command Line Interface - Text-based interface for computer programs",
            "REST": "Representational State Transfer - Architectural style for distributed systems",
            "JSON": "JavaScript Object Notation - Lightweight data interchange format",
            "Async": "Asynchronous - Non-blocking execution model",
            "DTO": "Data Transfer Object - Object that carries data between processes"
        }
        
        glossary.update(architectural_terms)
        
        return glossary
    
    # Helper methods
    
    def _infer_system_purpose(self) -> str:
        """Infer the system's purpose from its structure."""
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        if any(fw in frameworks for fw in ["Flask", "Django", "FastAPI"]):
            return "Web-based application serving users via HTTP"
        elif any(fw in frameworks for fw in ["Click", "Typer", "Argparse"]):
            return "Command-line tool for task automation"
        elif "pytest" in frameworks:
            return "Testing framework or test utilities"
        else:
            return "Software application for specific business needs"
    
    def _assess_complexity_level(self) -> str:
        """Assess the complexity level of the system."""
        entity_count = self.index_metadata.get("entity_count", 0)
        relationship_count = self.index_metadata.get("relationship_count", 0)
        
        if entity_count < 100:
            return "Low"
        elif entity_count < 500:
            return "Medium"
        elif entity_count < 2000:
            return "High"
        else:
            return "Very High"
    
    def _estimate_team_size(self) -> str:
        """Estimate optimal team size."""
        entity_count = self.index_metadata.get("entity_count", 0)
        
        if entity_count < 100:
            return "1-2 developers"
        elif entity_count < 500:
            return "2-5 developers"
        elif entity_count < 2000:
            return "5-10 developers"
        else:
            return "10+ developers"
    
    def _infer_business_value(self) -> str:
        """Infer the business value category."""
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        if any(fw in frameworks for fw in ["Flask", "Django", "FastAPI"]):
            return "Customer-facing product"
        elif any(fw in frameworks for fw in ["Click", "Typer", "Argparse"]):
            return "Internal productivity tool"
        elif "pytest" in frameworks:
            return "Development infrastructure"
        else:
            return "Business support system"
    
    def _detect_architectural_patterns(self) -> Dict[str, Any]:
        """Detect architectural patterns used."""
        patterns = []
        
        # Check for MVC
        if self._has_mvc_pattern():
            patterns.append("Model-View-Controller (MVC)")
        
        # Check for layered architecture
        if self._has_layered_architecture():
            patterns.append("Layered Architecture")
        
        # Check for microservices
        if self._has_microservice_patterns():
            patterns.append("Microservices")
        
        # Check for event-driven
        if self._has_event_driven_patterns():
            patterns.append("Event-Driven Architecture")
        
        return {
            "style": patterns[0] if patterns else "Monolithic",
            "patterns": patterns
        }
    
    def _has_mvc_pattern(self) -> bool:
        """Check for MVC pattern."""
        # Look for model, view, controller patterns
        has_models = any("model" in e.get("name", "").lower() 
                        for e in self.graph.get("entities", []))
        has_views = any("view" in e.get("name", "").lower() 
                       for e in self.graph.get("entities", []))
        has_controllers = any("controller" in e.get("name", "").lower() 
                             for e in self.graph.get("entities", []))
        
        return has_models and has_views and has_controllers
    
    def _has_layered_architecture(self) -> bool:
        """Check for layered architecture."""
        # Look for distinct layers in directory structure
        layers = ["controller", "service", "repository", "model"]
        found_layers = sum(1 for layer in layers 
                          if any(layer in f for f in self.repomap.get("files", {})))
        
        return found_layers >= 3
    
    def _has_microservice_patterns(self) -> bool:
        """Check for microservice patterns."""
        # Look for service boundaries
        service_files = [f for f in self.repomap.get("files", {}) 
                        if "service" in f.lower()]
        
        return len(service_files) > 1
    
    def _has_event_driven_patterns(self) -> bool:
        """Check for event-driven patterns."""
        # Look for event-related patterns
        event_patterns = ["event", "listener", "handler", "emit", "publish"]
        
        return any(pattern in e.get("name", "").lower() 
                  for e in self.graph.get("entities", [])
                  for pattern in event_patterns)
    
    def _trace_workflow(self, entry_point: Dict[str, Any]) -> Dict[str, Any] | None:
        """Trace a workflow from an entry point."""
        # This is a simplified implementation
        # In practice, you'd follow the call graph
        
        return {
            "name": entry_point.get("name", "Unknown Workflow"),
            "entry_point": f"{entry_point.get('file')}:{entry_point.get('start_line')}",
            "description": f"Workflow starting from {entry_point.get('name')}",
            "steps": [
                "Initialize system",
                "Process input",
                "Execute business logic",
                "Return results"
            ],
            "data_flow": "Input → Processing → Output"
        }
    
    def _find_data_models(self) -> List[Dict[str, Any]]:
        """Find data model entities."""
        if self._data_models is None:
            self._data_models = []
            
            for entity in self.graph.get("entities", []):
                name = entity.get("name", "").lower()
                entity_type = entity.get("type", "").lower()
                
                # Look for model-like entities
                if (entity_type == "class" and 
                    any(pattern in name for pattern in ["model", "entity", "dto", "domain"])):
                    self._data_models.append({
                        "name": entity.get("name"),
                        "file": entity.get("file"),
                        "type": "Data Model",
                        "properties": entity.get("metadata", {})
                    })
        
        return self._data_models
    
    def _extract_api_endpoints(self) -> List[Dict[str, Any]]:
        """Extract API endpoints from the codebase."""
        endpoints = []
        
        # Look for common API patterns
        for entity in self.graph.get("entities", []):
            name = entity.get("name", "").lower()
            
            # REST endpoint patterns
            if any(method in name for method in ["get_", "post_", "put_", "delete_", "patch_"]):
                endpoints.append({
                    "name": entity.get("name"),
                    "method": name.split("_")[0].upper() if "_" in name else "GET",
                    "path": f"/{name.replace('_', '/')}",
                    "file": entity.get("file"),
                    "description": f"REST endpoint: {entity.get('name')}"
                })
        
        return endpoints[:20]  # Limit to 20 endpoints
    
    def _cluster_by_business_domain(self) -> Dict[str, List[str]]:
        """Cluster entities by business domain."""
        if self._business_domains is None:
            self._business_domains = defaultdict(list)
            
            # Simple clustering based on file paths and names
            domain_keywords = {
                "User Management": ["user", "auth", "login", "account"],
                "Data Management": ["data", "storage", "persistence", "database"],
                "Business Logic": ["business", "service", "logic", "rule"],
                "Reporting": ["report", "analytics", "metric", "dashboard"],
                "Integration": ["api", "integration", "external", "client"],
                "Configuration": ["config", "setting", "parameter"],
                "Utilities": ["util", "helper", "common", "shared"]
            }
            
            for entity in self.graph.get("entities", []):
                name = entity.get("name", "").lower()
                file_path = entity.get("file", "").lower()
                
                assigned = False
                for domain, keywords in domain_keywords.items():
                    if any(keyword in name or keyword in file_path for keyword in keywords):
                        self._business_domains[domain].append(entity.get("name"))
                        assigned = True
                        break
                
                if not assigned:
                    self._business_domains["Other"].append(entity.get("name"))
        
        return dict(self._business_domains)
    
    def _infer_term_meaning(self, term: str, entity: Dict[str, Any]) -> str | None:
        """Infer the meaning of a term from its context."""
        name_lower = term.lower()
        file_path = entity.get("file", "").lower()
        
        # Common patterns
        if "service" in name_lower:
            return "Service layer component handling business logic"
        elif "repository" in name_lower:
            return "Data access layer for persistence operations"
        elif "controller" in name_lower:
            return "Request handler managing user interactions"
        elif "model" in name_lower:
            return "Data structure representing business entity"
        elif "config" in name_lower:
            return "Configuration setting or parameter"
        elif "util" in name_lower:
            return "Utility function providing common functionality"
        else:
            return None
    
    def _identify_architectural_layers(self) -> List[Dict[str, str]]:
        """Identify architectural layers in the system."""
        layers = []
        
        # Common layer patterns
        layer_patterns = {
            "Presentation": ["controller", "view", "api", "handler"],
            "Business": ["service", "business", "logic", "rule"],
            "Data Access": ["repository", "dao", "storage", "persistence"],
            "Data Model": ["model", "entity", "domain", "dto"],
            "Infrastructure": ["config", "util", "helper", "common"]
        }
        
        for layer_name, patterns in layer_patterns.items():
            entities = [e for e in self.graph.get("entities", [])
                       if any(pattern in e.get("name", "").lower() 
                             for pattern in patterns)]
            
            if entities:
                layers.append({
                    "name": layer_name,
                    "description": f"{layer_name} layer with {len(entities)} components",
                    "count": len(entities)
                })
        
        return layers
    
    def _analyze_dependencies(self) -> Dict[str, Any]:
        """Analyze system dependencies."""
        external = []
        internal = []
        
        for rel in self.graph.get("relationships", []):
            if rel.get("type") == "IMPORTS":
                target = rel.get("target", "")
                
                # Check if external
                if any(pattern in target.lower() for pattern in [".", "/"]):
                    # Likely internal
                    internal.append(target)
                else:
                    # Likely external
                    external.append(target)
        
        # Count and deduplicate
        external_unique = list(set(external))
        internal_unique = list(set(internal))
        
        return {
            "external": external_unique[:10],  # Top 10
            "internal": {
                "count": len(internal_unique),
                "examples": internal_unique[:5]
            }
        }
    
    def _extract_design_principles(self) -> List[str]:
        """Extract design principles from the codebase."""
        principles = []
        
        # Look for SOLID principles indicators
        entity_types = Counter(e.get("type", "") for e in self.graph.get("entities", []))
        
        if entity_types.get("interface", 0) > 0:
            principles.append("Interface Segregation - Uses interfaces for contracts")
        
        if entity_types.get("class", 0) > entity_types.get("function", 0):
            principles.append("Object-Oriented Design - Primarily class-based")
        
        # Look for dependency injection patterns
        di_patterns = ["inject", "provider", "factory"]
        if any(pattern in e.get("name", "").lower() 
               for e in self.graph.get("entities", [])
               for pattern in di_patterns):
            principles.append("Dependency Inversion - Uses dependency injection")
        
        return principles
    
    def _get_presentation_tech(self) -> List[str]:
        """Get presentation layer technologies."""
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        presentation = []
        if any(fw in frameworks for fw in ["Flask", "Django", "FastAPI"]):
            presentation.extend(["HTTP", "REST"])
        if any(fw in frameworks for fw in ["React", "Vue", "Angular"]):
            presentation.append("SPA")
        
        return presentation or ["Unknown"]
    
    def _get_business_tech(self) -> List[str]:
        """Get business layer technologies."""
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        business = []
        if "Pydantic" in frameworks:
            business.append("Data Validation")
        if any(fw in frameworks for fw in ["SQLAlchemy", "Django ORM"]):
            business.append("ORM")
        
        return business or ["Business Logic"]
    
    def _get_data_tech(self) -> List[str]:
        """Get data layer technologies."""
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        data = []
        if "SQLAlchemy" in frameworks:
            data.append("SQL Database")
        if "Redis" in frameworks:
            data.append("Cache")
        if any(fw in frameworks for fw in ["pymongo", "motor"]):
            data.append("MongoDB")
        
        return data or ["Unknown"]
    
    def _get_infrastructure_tech(self) -> List[str]:
        """Get infrastructure technologies."""
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        infra = []
        if "pytest" in frameworks:
            infra.append("Testing")
        if "Docker" in self.index_metadata.get("stack", {}).get("infra", []):
            infra.append("Containerization")
        
        return infra or ["Standard"]
    
    def _identify_data_patterns(self, data_models: List[Dict[str, Any]]) -> List[str]:
        """Identify data modeling patterns."""
        patterns = []
        
        # Look for common patterns
        if len(data_models) > 5:
            patterns.append("Rich Domain Model")
        
        # Check for active record pattern
        if any("save" in model.get("name", "").lower() for model in data_models):
            patterns.append("Active Record Pattern")
        
        # Check for repository pattern
        if any("repository" in e.get("name", "").lower() 
               for e in self.graph.get("entities", [])):
            patterns.append("Repository Pattern")
        
        return patterns
    
    def _trace_data_flow(self) -> List[Dict[str, Any]]:
        """Trace data flow through the system."""
        # Simplified data flow analysis
        return [
            {
                "flow": "User Input → Validation → Processing → Storage",
                "components": ["Controller", "Validator", "Service", "Repository"],
                "description": "Standard CRUD operation flow"
            },
            {
                "flow": "Request → Authentication → Authorization → Business Logic",
                "components": ["Middleware", "Auth Service", "Business Service"],
                "description": "Authenticated request flow"
            }
        ]
    
    def _identify_persistence_mechanisms(self) -> List[str]:
        """Identify data persistence mechanisms."""
        mechanisms = []
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        if "SQLAlchemy" in frameworks:
            mechanisms.append("Relational Database (ORM)")
        if "Redis" in frameworks:
            mechanisms.append("In-Memory Cache")
        if any(fw in frameworks for fw in ["pymongo", "motor"]):
            mechanisms.append("Document Database")
        
        return mechanisms or ["File System"]
    
    def _assess_data_integrity(self) -> Dict[str, str]:
        """Assess data integrity measures."""
        return {
            "validation": "Model-based validation using Pydantic",
            "constraints": "Database-level constraints",
            "transactions": "ACID transactions for data consistency"
        }
    
    def _identify_caching_strategy(self) -> str:
        """Identify caching strategy."""
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        if "Redis" in frameworks:
            return "External cache (Redis)"
        elif any("cache" in e.get("name", "").lower() 
                for e in self.graph.get("entities", [])):
            return "In-memory caching"
        else:
            return "No explicit caching"
    
    def _check_outdated_dependencies(self) -> List[str]:
        """Check for potentially outdated dependencies."""
        # This is a placeholder - in practice, you'd check against current versions
        return []
    
    def _find_complex_components(self) -> List[Dict[str, Any]]:
        """Find highly complex components."""
        complex = []
        
        for entity in self.graph.get("entities", []):
            line_count = entity.get("end_line", 0) - entity.get("start_line", 0)
            
            if line_count > 100:  # Arbitrary threshold
                complex.append({
                    "name": entity.get("name"),
                    "file": entity.get("file"),
                    "lines": line_count,
                    "type": entity.get("type")
                })
        
        return complex[:5]  # Top 5
    
    def _check_security_patterns(self) -> List[str]:
        """Check for security anti-patterns."""
        issues = []
        
        # Look for potential SQL injection
        for entity in self.graph.get("entities", []):
            if "execute" in entity.get("name", "").lower():
                issues.append("Direct SQL execution - potential SQL injection risk")
        
        # Look for hardcoded secrets
        if any("password" in e.get("name", "").lower() 
               or "secret" in e.get("name", "").lower()
               for e in self.graph.get("entities", [])):
            issues.append("Potential hardcoded secrets detected")
        
        return issues
    
    def _analyze_coupling(self) -> Dict[str, Any]:
        """Analyze system coupling."""
        # Count cross-file relationships
        cross_file = 0
        same_file = 0
        
        for rel in self.graph.get("relationships", []):
            source = next((e for e in self.graph.get("entities", []) 
                          if e.get("id") == rel.get("source_id")), {})
            target = next((e for e in self.graph.get("entities", []) 
                          if e.get("id") == rel.get("target_id")), {})
            
            if source.get("file") != target.get("file"):
                cross_file += 1
            else:
                same_file += 1
        
        total = cross_file + same_file
        if total > 0:
            coupling_ratio = cross_file / total
            level = "High" if coupling_ratio > 0.5 else "Medium" if coupling_ratio > 0.2 else "Low"
        else:
            coupling_ratio = 0
            level = "None"
        
        return {
            "level": level,
            "cross_file_ratio": coupling_ratio,
            "cross_file_count": cross_file,
            "same_file_count": same_file
        }
    
    def _analyze_cohesion(self) -> Dict[str, Any]:
        """Analyze system cohesion."""
        # Group entities by file and count related entities
        file_cohesion = defaultdict(list)
        
        for entity in self.graph.get("entities", []):
            file_cohesion[entity.get("file", "")].append(entity)
        
        # Calculate average cohesion
        cohesion_scores = []
        for file_path, entities in file_cohesion.items():
            if len(entities) > 1:
                # Count internal relationships
                internal = sum(1 for rel in self.graph.get("relationships", [])
                             if (rel.get("source_id") in [e.get("id") for e in entities] and
                                 rel.get("target_id") in [e.get("id") for e in entities]))
                
                cohesion_score = internal / len(entities)
                cohesion_scores.append(cohesion_score)
        
        avg_cohesion = sum(cohesion_scores) / len(cohesion_scores) if cohesion_scores else 0
        
        return {
            "average": avg_cohesion,
            "level": "High" if avg_cohesion > 0.7 else "Medium" if avg_cohesion > 0.3 else "Low",
            "file_count": len(file_cohesion)
        }
    
    def _identify_high_impact_areas(self) -> List[Dict[str, Any]]:
        """Identify areas with high change impact."""
        # Find entities with many relationships
        entity_relationships = defaultdict(int)
        
        for rel in self.graph.get("relationships", []):
            entity_relationships[rel.get("source_id", "")] += 1
            entity_relationships[rel.get("target_id", "")] += 1
        
        # Get top connected entities
        sorted_entities = sorted(entity_relationships.items(), 
                               key=lambda x: x[1], reverse=True)
        
        high_impact = []
        for entity_id, count in sorted_entities[:10]:
            entity = next((e for e in self.graph.get("entities", []) 
                          if e.get("id") == entity_id), {})
            if entity:
                high_impact.append({
                    "name": entity.get("name"),
                    "file": entity.get("file"),
                    "relationship_count": count,
                    "impact": "High"
                })
        
        return high_impact
    
    def _map_change_propagation(self) -> List[Dict[str, Any]]:
        """Map how changes propagate through the system."""
        return [
            {
                "source": "Model Changes",
                "affected": ["Controllers", "Services", "Tests"],
                "effort": "High"
            },
            {
                "source": "API Changes",
                "affected": ["Clients", "Documentation", "Tests"],
                "effort": "Very High"
            },
            {
                "source": "Database Schema",
                "affected": ["Models", "Repositories", "Migrations"],
                "effort": "High"
            }
        ]
    
    def _recommend_testing_strategy(self) -> Dict[str, Any]:
        """Recommend testing strategy based on architecture."""
        return {
            "unit_tests": "Focus on business logic in service layer",
            "integration_tests": "Test API endpoints and database interactions",
            "e2e_tests": "Critical user workflows",
            "coverage_target": "80% minimum for business logic"
        }
    
    def _identify_scalability_limitations(self) -> List[str]:
        """Identify potential scalability limitations."""
        limitations = []
        
        # Check for synchronous operations
        if any("sync" in e.get("name", "").lower() 
               for e in self.graph.get("entities", [])):
            limitations.append("Synchronous operations may block under load")
        
        # Check for single-threaded patterns
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        if not any(fw in frameworks for fw in ["asyncio", "threading", "multiprocessing"]):
            limitations.append("No concurrency patterns detected")
        
        return limitations
    
    def _identify_scaling_factors(self) -> List[str]:
        """Identify factors that affect scaling."""
        return [
            "Database connection pool size",
            "Memory usage per request",
            "CPU-intensive operations",
            "I/O bottleneck patterns"
        ]
    
    def _identify_bottlenecks(self) -> List[Dict[str, Any]]:
        """Identify potential bottlenecks."""
        return [
            {
                "type": "Database",
                "description": "Shared database may become contention point",
                "mitigation": "Implement caching and read replicas"
            },
            {
                "type": "I/O",
                "description": "File operations may block processing",
                "mitigation": "Use async I/O patterns"
            }
        ]
    
    def _generate_scalability_recommendations(self) -> List[str]:
        """Generate scalability recommendations."""
        return [
            "Implement connection pooling for database access",
            "Add caching layer for frequently accessed data",
            "Consider async processing for long-running operations",
            "Monitor resource usage and identify hotspots"
        ]
    
    def _assess_horizontal_scaling(self) -> Dict[str, Any]:
        """Assess horizontal scaling capability."""
        return {
            "capability": "Medium",
            "requirements": [
                "Stateless application design",
                "External session storage",
                "Load balancer configuration"
            ],
            "challenges": [
                "Database scalability",
                "Session management",
                "File storage consistency"
            ]
        }
    
    def _assess_vertical_scaling(self) -> Dict[str, Any]:
        """Assess vertical scaling capability."""
        return {
            "capability": "Good",
            "factors": [
                "Memory usage patterns",
                "CPU efficiency",
                "I/O characteristics"
            ]
        }
    
    def _check_authentication(self) -> Dict[str, Any]:
        """Check authentication implementation."""
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        if any(fw in frameworks for fw in ["auth0", "jwt", "oauth"]):
            return {
                "implemented": True,
                "method": "Token-based authentication",
                "strength": "Strong"
            }
        else:
            return {
                "implemented": False,
                "recommendation": "Implement proper authentication"
            }
    
    def _check_authorization(self) -> Dict[str, Any]:
        """Check authorization implementation."""
        has_roles = any("role" in e.get("name", "").lower() 
                       for e in self.graph.get("entities", []))
        has_permissions = any("permission" in e.get("name", "").lower() 
                             for e in self.graph.get("entities", []))
        
        return {
            "implemented": has_roles or has_permissions,
            "type": "Role-based" if has_roles else "Attribute-based" if has_permissions else "None"
        }
    
    def _check_data_protection(self) -> Dict[str, Any]:
        """Check data protection measures."""
        has_encryption = any("encrypt" in e.get("name", "").lower() 
                           for e in self.graph.get("entities", []))
        
        return {
            "encryption": has_encryption,
            "recommendation": "Implement encryption for sensitive data"
        }
    
    def _check_input_validation(self) -> Dict[str, Any]:
        """Check input validation implementation."""
        has_validation = any("validate" in e.get("name", "").lower() 
                           for e in self.graph.get("entities", []))
        
        return {
            "implemented": has_validation,
            "coverage": "Partial" if has_validation else "None"
        }
    
    def _check_dependency_security(self) -> Dict[str, Any]:
        """Check dependency security."""
        return {
            "scanning": "Not implemented",
            "recommendation": "Implement dependency vulnerability scanning"
        }
    
    def _check_compliance(self) -> Dict[str, Any]:
        """Check compliance requirements."""
        return {
            "gdpr": "Needs assessment",
            "soc2": "Needs assessment",
            "recommendation": "Conduct compliance review"
        }
    
    def _generate_security_recommendations(self) -> List[str]:
        """Generate security recommendations."""
        return [
            "Implement proper authentication and authorization",
            "Validate all user inputs",
            "Use HTTPS for all communications",
            "Implement proper logging and monitoring",
            "Regular security audits and penetration testing"
        ]
    
    def _extract_coding_standards(self) -> List[str]:
        """Extract coding standards from the codebase."""
        # Look for linting/formatting tools
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        standards = []
        if "Black" in frameworks:
            standards.append("Code formatting with Black")
        if "Ruff" in frameworks or "Flake8" in frameworks:
            standards.append("Linting with Ruff/Flake8")
        if "MyPy" in frameworks:
            standards.append("Type checking with MyPy")
        
        return standards or ["No explicit standards detected"]
    
    def _analyze_testing_practices(self) -> Dict[str, Any]:
        """Analyze testing practices."""
        test_files = [f for f in self.repomap.get("files", {}).keys() 
                     if "test" in f.lower()]
        
        return {
            "framework": "pytest" if "pytest" in self.index_metadata.get("stack", {}).get("frameworks", []) else "Unknown",
            "coverage": f"{len(test_files)} test files",
            "practices": [
                "Unit testing for business logic",
                "Integration testing for APIs",
                "Test fixtures for consistent test data"
            ]
        }
    
    def _generate_review_checklist(self) -> List[str]:
        """Generate code review checklist."""
        return [
            "Code follows project conventions",
            "Tests are included and passing",
            "Documentation is updated",
            "Security implications considered",
            "Performance impact assessed",
            "Error handling implemented"
        ]
    
    def _document_common_patterns(self) -> List[Dict[str, Any]]:
        """Document common patterns in the codebase."""
        return [
            {
                "pattern": "Service Layer",
                "description": "Business logic encapsulated in service classes",
                "example": "UserService.handle_user_registration()"
            },
            {
                "pattern": "Repository Pattern",
                "description": "Data access abstracted through repositories",
                "example": "UserRepository.find_by_id()"
            }
        ]
    
    def _document_anti_patterns(self) -> List[Dict[str, Any]]:
        """Document anti-patterns to avoid."""
        return [
            {
                "anti_pattern": "God Object",
                "description": "Classes with too many responsibilities",
                "avoidance": "Keep classes focused on single responsibility"
            },
            {
                "anti_pattern": "Magic Numbers",
                "description": "Hardcoded numeric values",
                "avoidance": "Use named constants"
            }
        ]
    
    def _list_development_tooling(self) -> List[str]:
        """List development tooling."""
        frameworks = self.index_metadata.get("stack", {}).get("frameworks", [])
        
        tooling = []
        if "pytest" in frameworks:
            tooling.append("pytest for testing")
        if "Black" in frameworks:
            tooling.append("Black for formatting")
        if "MyPy" in frameworks:
            tooling.append("MyPy for type checking")
        
        return tooling or ["Basic Python tooling"]
    
    def _create_quick_start(self) -> List[str]:
        """Create quick start guide."""
        return [
            "1. Clone the repository",
            "2. Install dependencies: pip install -r requirements.txt",
            "3. Run tests: pytest",
            "4. Start development server: python batho.py --help"
        ]
    
    def _document_dev_setup(self) -> Dict[str, str]:
        """Document development setup."""
        return {
            "python_version": "Python 3.12+",
            "ide": "VS Code with Python extension recommended",
            "virtual_env": "Use venv or conda for isolation",
            "pre_commit": "Configure pre-commit hooks"
        }
    
    def _extract_key_concepts(self) -> List[str]:
        """Extract key concepts developers should know."""
        return [
            "C4 Model for architecture visualization",
            "Entity-Relationship modeling",
            "Dependency injection patterns",
            "Test-driven development",
            "Clean architecture principles"
        ]
    
    def _list_common_tasks(self) -> List[Dict[str, str]]:
        """List common development tasks."""
        return [
            {
                "task": "Add new feature",
                "steps": "Create service → Add controller → Write tests"
            },
            {
                "task": "Fix bug",
                "steps": "Reproduce → Write test → Fix → Verify"
            },
            {
                "task": "Update dependency",
                "steps": "Update requirements → Test → Update documentation"
            }
        ]
    
    def _list_learning_resources(self) -> List[str]:
        """List learning resources."""
        return [
            "Project README.md",
            "Architecture documentation",
            "API documentation",
            "Code examples in tests/",
            "Team wiki/knowledge base"
        ]
    
    def _identify_domain_experts(self) -> Dict[str, str]:
        """Identify domain experts (placeholder)."""
        if not self.enable_llm:
            self.logger.debug("skipping_domain_expert_identification", 
                            reason="LLM extensions disabled")
            return {}
        
        # Placeholder implementation - will be implemented when LLM features are enabled
        self.logger.debug("domain_experts_placeholder", 
                        reason="Implementation pending")
        return {
            "Architecture": "Senior developer/tech lead",
            "Business Logic": "Product owner/Business analyst",
            "Database": "Database administrator",
            "Testing": "QA engineer"
        }
    
    def _find_database_in_loops(self) -> List[str]:
        """Find database queries inside loops."""
        if not self.enable_llm:
            self.logger.debug("skipping_database_in_loops_analysis", 
                            reason="LLM extensions disabled")
            return []
        
        # Placeholder implementation - will be implemented when LLM features are enabled
        self.logger.debug("database_in_loops_placeholder", 
                        reason="Implementation pending")
        return []
    
    def _find_large_file_processing(self) -> List[str]:
        """Find large file processing patterns."""
        if not self.enable_llm:
            self.logger.debug("skipping_large_file_processing_analysis", 
                            reason="LLM extensions disabled")
            return []
        
        # Placeholder implementation - will be implemented when LLM features are enabled
        self.logger.debug("large_file_processing_placeholder", 
                        reason="Implementation pending")
        return []
    
    def _find_synchronous_io(self) -> List[str]:
        """Find synchronous I/O operations."""
        if not self.enable_llm:
            self.logger.debug("skipping_synchronous_io_analysis", 
                            reason="LLM extensions disabled")
            return []
        
        # Placeholder implementation - will be implemented when LLM features are enabled
        self.logger.debug("synchronous_io_placeholder", 
                        reason="Implementation pending")
        return []
    
    def _assess_integration_criticality(self, target: str) -> str:
        """Assess the criticality of an integration."""
        critical_patterns = ["payment", "auth", "security", "core"]
        
        if any(pattern in target.lower() for pattern in critical_patterns):
            return "Critical"
        elif "api" in target.lower() or "service" in target.lower():
            return "High"
        else:
            return "Medium"
