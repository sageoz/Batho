"""
Microservice architecture pattern detector.
"""

from typing import Any, Dict, List, Optional, Set
from collections import defaultdict
from pathlib import Path

from .base import PatternDetector, DetectionResult


class MicroserviceDetector(PatternDetector):
    """Detector for microservice architecture patterns."""
    
    def __init__(self, min_confidence: float = 0.5):
        super().__init__("microservices", min_confidence)
        
        # Service boundary indicators
        self.service_boundary_indicators = [
            "service", "microservice", "api", "gateway", "edge"
        ]
        
        # Communication patterns
        self.communication_patterns = [
            "rest", "grpc", "graphql", "message", "event", "queue"
        ]
        
        # Service mesh indicators
        self.service_mesh_indicators = {
            "istio": ["istio.io", "istio"],
            "linkerd": ["linkerd.io", "linkerd"],
            "consul": ["consul.io/connect", "consul-connect"]
        }
    
    def detect(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any],
        rules: Optional[Dict[str, Any]] = None
    ) -> List[DetectionResult]:
        """Detect microservice patterns."""
        results = []
        
        # Detect service boundaries
        service_boundary_result = self._detect_service_boundaries(graph, repomap)
        if service_boundary_result:
            results.append(service_boundary_result)
        
        # Detect service mesh
        service_mesh_result = self._detect_service_mesh(graph, repomap)
        if service_mesh_result:
            results.append(service_mesh_result)
        
        # Detect API gateway
        gateway_result = self._detect_api_gateway(graph, repomap)
        if gateway_result:
            results.append(gateway_result)
        
        # Detect inter-service communication
        communication_result = self._detect_service_communication(graph, repomap)
        if communication_result:
            results.append(communication_result)
        
        # Detect circuit breakers
        circuit_breaker_result = self._detect_circuit_breakers(graph, repomap)
        if circuit_breaker_result:
            results.append(circuit_breaker_result)
        
        return results
    
    def _detect_service_boundaries(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect service boundaries in the codebase."""
        # Find service directories
        service_dirs = self._find_service_directories(repomap)
        
        if not service_dirs:
            return None
        
        # Group entities by service
        service_entities = self._group_entities_by_service(graph, service_dirs)
        
        # Calculate confidence based on isolation indicators
        confidence_indicators = [
            len(service_dirs) > 1,  # Multiple services
            any("api" in d.lower() or "gateway" in d.lower() 
                for d in service_dirs),  # API/Gateway present
            len(service_entities) > 0  # Found entities in services
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Create service entities for result
        entities = []
        for service_name, entity_list in service_entities.items():
            entities.append({
                "id": f"service-{service_name}",
                "name": service_name,
                "type": "Service",
                "file": service_dirs.get(service_name, ""),
                "entity_count": len(entity_list),
                "description": f"Microservice: {service_name}"
            })
        
        # Find inter-service relationships
        relationships = self._find_inter_service_relationships(
            graph, service_entities
        )
        
        return DetectionResult(
            pattern_type="ServiceBoundaries",
            confidence=confidence,
            entities=entities,
            relationships=relationships,
            metadata={
                "service_count": len(service_dirs),
                "service_names": list(service_dirs.keys())
            }
        )
    
    def _detect_service_mesh(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect service mesh implementation."""
        mesh_detected = None
        mesh_confidence = 0.0
        
        # Check for service mesh indicators
        for mesh_name, indicators in self.service_mesh_indicators.items():
            imports = self._find_imports_by_pattern(graph, indicators)
            files = self._find_files_by_pattern(repomap, indicators)
            
            if imports or files:
                mesh_detected = mesh_name
                mesh_confidence = min(1.0, (len(imports) + len(files)) / 5.0)
                break
        
        if not mesh_detected or mesh_confidence < self.min_confidence:
            return None
        
        # Find mesh-related entities
        mesh_entities = self._find_entities_by_pattern(
            graph, ["*Mesh*", "*Sidecar*", "*Proxy*"]
        )
        
        return DetectionResult(
            pattern_type="ServiceMesh",
            confidence=mesh_confidence,
            entities=mesh_entities,
            relationships=[],
            metadata={
                "mesh_type": mesh_detected,
                "implementation": self.service_mesh_indicators[mesh_detected]
            }
        )
    
    def _detect_api_gateway(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect API gateway implementation."""
        gateway_patterns = [
            "gateway", "api-gateway", "edge", "proxy", "zuul", "kong", "traefik"
        ]
        
        # Find gateway files and directories
        gateway_files = self._find_files_by_pattern(repomap, gateway_patterns)
        gateway_imports = self._find_imports_by_pattern(graph, gateway_patterns)
        
        if not gateway_files and not gateway_imports:
            return None
        
        # Calculate confidence
        confidence_indicators = [
            len(gateway_files) > 0,
            len(gateway_imports) > 0,
            any("gateway" in f.lower() or "edge" in f.lower() 
                for f in gateway_files)
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Find gateway entities
        gateway_entities = self._find_entities_by_pattern(
            graph, ["*Gateway*", "*Route*", "*Proxy*"]
        )
        
        return DetectionResult(
            pattern_type="APIGateway",
            confidence=confidence,
            entities=gateway_entities,
            relationships=[],
            metadata={
                "gateway_files": gateway_files,
                "gateway_imports": [imp.get("target") for imp in gateway_imports]
            }
        )
    
    def _detect_service_communication(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect inter-service communication patterns."""
        # Find communication-related imports
        comm_imports = self._find_imports_by_pattern(
            graph, self.communication_patterns
        )
        
        if len(comm_imports) < 3:  # Need multiple communication patterns
            return None
        
        # Group by communication type
        comm_types = defaultdict(list)
        for imp in comm_imports:
            target = imp.get("target", "").lower()
            for pattern in self.communication_patterns:
                if pattern in target:
                    comm_types[pattern].append(imp)
        
        # Calculate confidence based on diversity of communication
        confidence = min(1.0, len(comm_types) / len(self.communication_patterns))
        
        if confidence < self.min_confidence:
            return None
        
        # Create communication entities
        entities = []
        for comm_type, imports in comm_types.items():
            entities.append({
                "id": f"comm-{comm_type}",
                "name": f"{comm_type.title()} Communication",
                "type": "Communication",
                "usage_count": len(imports),
                "description": f"Service communication via {comm_type}"
            })
        
        return DetectionResult(
            pattern_type="ServiceCommunication",
            confidence=confidence,
            entities=entities,
            relationships=[],
            metadata={
                "communication_types": list(comm_types.keys()),
                "total_communications": len(comm_imports)
            }
        )
    
    def _detect_circuit_breakers(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect circuit breaker implementations."""
        circuit_breaker_patterns = [
            "hystrix", "resilience4j", "polly", "circuit-breaker", "breaker"
        ]
        
        # Find circuit breaker imports and entities
        cb_imports = self._find_imports_by_pattern(graph, circuit_breaker_patterns)
        cb_entities = self._find_entities_by_pattern(
            graph, ["*CircuitBreaker*", "*Fallback*", "*Bulkhead*"]
        )
        
        if not cb_imports and not cb_entities:
            return None
        
        # Calculate confidence
        confidence_indicators = [
            len(cb_imports) > 0,
            len(cb_entities) > 0,
            any("hystrix" in imp.get("target", "").lower() 
                for imp in cb_imports)
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        return DetectionResult(
            pattern_type="CircuitBreaker",
            confidence=confidence,
            entities=cb_entities,
            relationships=[],
            metadata={
                "circuit_breaker_imports": len(cb_imports),
                "circuit_breaker_entities": len(cb_entities)
            }
        )
    
    def _find_service_directories(self, repomap: Dict[str, Any]) -> Dict[str, str]:
        """Find directories that likely contain services."""
        service_dirs = {}
        
        for file_path in repomap.get("files", {}).keys():
            parts = Path(file_path).parts
            
            # Look for service indicators in directory names
            for i, part in enumerate(parts):
                part_lower = part.lower()
                
                # Check if this part indicates a service
                if any(indicator in part_lower 
                       for indicator in self.service_boundary_indicators):
                    
                    # Use the next part as service name if available
                    if i + 1 < len(parts):
                        service_name = parts[i + 1]
                    else:
                        service_name = part
                    
                    # Store the directory path
                    service_dir = "/".join(parts[:i + 2])
                    if service_name not in service_dirs:
                        service_dirs[service_name] = service_dir
        
        return service_dirs
    
    def _group_entities_by_service(
        self,
        graph: Dict[str, Any],
        service_dirs: Dict[str, str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group entities by their service."""
        service_entities = defaultdict(list)
        
        for entity in graph.get("entities", []):
            file_path = entity.get("file", "")
            
            # Find which service this entity belongs to
            for service_name, service_dir in service_dirs.items():
                if file_path.startswith(service_dir):
                    service_entities[service_name].append(entity)
                    break
        
        return dict(service_entities)
    
    def _find_inter_service_relationships(
        self,
        graph: Dict[str, Any],
        service_entities: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Find relationships between services."""
        relationships = []
        
        # Create entity ID to service mapping
        entity_to_service = {}
        for service_name, entities in service_entities.items():
            for entity in entities:
                entity_to_service[entity.get("id")] = service_name
        
        # Find cross-service relationships
        for rel in graph.get("relationships", []):
            source_service = entity_to_service.get(rel.get("source"))
            target_service = entity_to_service.get(rel.get("target"))
            
            if source_service and target_service and source_service != target_service:
                relationships.append({
                    "source": f"service-{source_service}",
                    "target": f"service-{target_service}",
                    "type": rel.get("type", "UNKNOWN"),
                    "description": f"{source_service} -> {target_service}"
                })
        
        return relationships
