"""
Tests for microservice pattern detection.
"""

import pytest
from unittest.mock import MagicMock

from batho_core.context.c4.detection.microservices import MicroserviceDetector


class TestMicroserviceDetector:
    """Test cases for MicroserviceDetector."""
    
    def test_initialization(self):
        """Test detector initialization."""
        detector = MicroserviceDetector(min_confidence=0.6)
        assert detector.name == "microservices"
        assert detector.min_confidence == 0.6
    
    def test_detect_service_boundaries(self):
        """Test service boundary detection."""
        detector = MicroserviceDetector()
        
        # Create test data
        graph = {
            "entities": [
                {"id": "e1", "name": "UserController", "file": "services/user/controller.py"},
                {"id": "e2", "name": "OrderController", "file": "services/order/controller.py"},
                {"id": "e3", "name": "CommonUtils", "file": "shared/utils.py"}
            ]
        }
        
        repomap = {
            "files": {
                "services/user/controller.py": {"size": 100},
                "services/order/controller.py": {"size": 100},
                "shared/utils.py": {"size": 50}
            }
        }
        
        # Run detection
        results = detector.detect(graph, repomap)
        
        # Should detect service boundaries
        service_boundary_results = [
            r for r in results if r.pattern_type == "ServiceBoundaries"
        ]
        
        assert len(service_boundary_results) > 0
        result = service_boundary_results[0]
        assert result.confidence > 0
        assert "user" in result.metadata["service_names"]
        assert "order" in result.metadata["service_names"]
    
    def test_detect_service_mesh(self):
        """Test service mesh detection."""
        detector = MicroserviceDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "istio.io/client"},
                {"type": "IMPORTS", "target": "istio.io/api"},
                {"type": "IMPORTS", "target": "kubernetes/client"}
            ]
        }
        
        repomap = {
            "files": {
                "istio/config.yaml": {"size": 100},
                "istio/virtualservice.yaml": {"size": 100},
                "istio/gateway.yaml": {"size": 100},
                "k8s/deployment.yaml": {"size": 100}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect Istio service mesh
        mesh_results = [r for r in results if r.pattern_type == "ServiceMesh"]
        assert len(mesh_results) > 0
        assert mesh_results[0].metadata["mesh_type"] == "istio"
    
    def test_detect_api_gateway(self):
        """Test API gateway detection."""
        detector = MicroserviceDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "kong"},
                {"type": "IMPORTS", "target": "zuul"}
            ]
        }
        
        repomap = {
            "files": {
                "gateway/routes.yaml": {"size": 100},
                "api-gateway/main.py": {"size": 200}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect API gateway
        gateway_results = [r for r in results if r.pattern_type == "APIGateway"]
        assert len(gateway_results) > 0
        assert gateway_results[0].confidence > 0
    
    def test_detect_circuit_breakers(self):
        """Test circuit breaker detection."""
        detector = MicroserviceDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "netflix.hystrix"},
                {"type": "IMPORTS", "target": "resilience4j"}
            ],
            "entities": [
                {"id": "e1", "name": "UserServiceCircuitBreaker", "type": "class"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should detect circuit breakers
        cb_results = [r for r in results if r.pattern_type == "CircuitBreaker"]
        assert len(cb_results) > 0
        assert cb_results[0].metadata["circuit_breaker_imports"] > 0
    
    def test_no_service_boundaries(self):
        """Test when no service boundaries are found."""
        detector = MicroserviceDetector()
        
        graph = {"entities": []}
        repomap = {"files": {"main.py": {"size": 100}}}
        
        results = detector.detect(graph, repomap)
        
        # Should not detect service boundaries
        service_boundary_results = [
            r for r in results if r.pattern_type == "ServiceBoundaries"
        ]
        assert len(service_boundary_results) == 0
    
    def test_low_confidence_filtered(self):
        """Test that low confidence results are filtered."""
        detector = MicroserviceDetector(min_confidence=0.9)
        
        graph = {"entities": []}
        repomap = {"files": {"service/main.py": {"size": 100}}}
        
        results = detector.detect(graph, repomap)
        
        # Single service should have low confidence
        assert len(results) == 0
