"""
Integration tests for the complete detection system.
"""

import pytest
import tempfile
from pathlib import Path

from batho_core.context.c4.detection.registry import DetectorRegistry, get_registry, auto_register_detectors
from batho_core.context.c4_generator import C4Generator

# Import detectors for testing
from batho_core.context.c4.detection.microservices import MicroserviceDetector


class TestDetectionIntegration:
    """Integration tests for pattern detection system."""
    
    def test_registry_auto_registration(self):
        """Test that detectors are auto-registered."""
        # Use global registry
        registry = get_registry()
        auto_register_detectors()
        
        # Should have all detectors registered
        detectors = registry.list_detectors()
        assert "microservices" in detectors
        assert "event_driven" in detectors
        assert "cloud_native" in detectors
        assert "data_patterns" in detectors
    
    def test_detect_all_patterns(self):
        """Test running all detectors on sample data."""
        # Use global registry
        registry = get_registry()
        auto_register_detectors()
        
        # Create comprehensive test data
        graph = {
            "entities": [
                {"id": "e1", "name": "UserController", "type": "class", "file": "services/user/controller.py"},
                {"id": "e2", "name": "UserEventProducer", "type": "class", "file": "services/user/producer.py"},
                {"id": "e3", "name": "UserCommandHandler", "type": "class", "file": "services/user/command.py"},
                {"id": "e4", "name": "UserShardManager", "type": "class", "file": "database/sharding.py"},
                {"id": "e5", "name": "LambdaHandler", "type": "class", "file": "functions/handler.py"}
            ],
            "relationships": [
                {"type": "IMPORTS", "target": "kafka"},
                {"type": "IMPORTS", "target": "kubernetes"},
                {"type": "IMPORTS", "target": "aws-lambda"},
                {"type": "IMPORTS", "target": "shardingsphere"},
                {"type": "IMPORTS", "target": "axon"},
                {"type": "IMPORTS", "target": "docker"},
                {"type": "IMPORTS", "target": "redis"},
                {"type": "IMPORTS", "target": "mongodb"},
                {"type": "IMPORTS", "target": "mysql"}
            ]
        }
        
        repomap = {
            "files": {
                "services/user/controller.py": {"size": 100},
                "services/order/controller.py": {"size": 100},
                "k8s/deployment.yaml": {"size": 200},
                "k8s/service.yaml": {"size": 100},
                "Dockerfile": {"size": 150},
                "docker-compose.yml": {"size": 200},
                "lambda/handler.py": {"size": 100},
                "infra/main.tf": {"size": 300},
                "helm/Chart.yaml": {"size": 100},
                "migrations/V1__Initial.sql": {"size": 100}
            }
        }
        
        # Run all detectors
        results = registry.detect_all(graph, repomap)
        
        # Should have results from multiple detectors
        assert len(results) > 0
        
        # Get summary
        summary = registry.get_summary(results)
        assert summary["total_patterns"] > 0
        assert summary["average_confidence"] > 0
    
    def test_c4_generator_with_detection(self, temp_ctn_dir):
        """Test C4Generator integration with detection system."""
        # Create sample C4 data
        versioned_dir = temp_ctn_dir / "test123"
        versioned_dir.mkdir(parents=True)
        
        # Create graph with architectural patterns
        graph = {
            "entities": [
                {"id": "e1", "name": "UserService", "type": "class", "file": "services/user/service.py"},
                {"id": "e2", "name": "OrderService", "type": "class", "file": "services/order/service.py"},
                {"id": "e3", "name": "UserEventProducer", "type": "class", "file": "events/user/producer.py"},
                {"id": "e4", "name": "K8sDeployment", "type": "class", "file": "k8s/deployment.py"}
            ],
            "relationships": [
                {"type": "IMPORTS", "target": "kafka"},
                {"type": "IMPORTS", "target": "kubernetes"},
                {"type": "IMPORTS", "target": "docker"}
            ]
        }
        
        (versioned_dir / "graph.json").write_text('{"entities": [], "relationships": []}')
        (versioned_dir / "repomap.json").write_text('{"files": {}}')
        (temp_ctn_dir / "index.json").write_text('{"indexes": {"test123": {"timestamp": "2024-01-01"}}}')
        
        # Create generator
        generator = C4Generator(temp_ctn_dir, "test123")
        
        # Should have detection results
        assert hasattr(generator, '_detection_results')
        assert isinstance(generator._detection_results, dict)
    
    def test_detector_filtering(self):
        """Test filtering specific detectors."""
        registry = DetectorRegistry()
        auto_register_detectors()
        
        graph = {"entities": [], "relationships": []}
        repomap = {"files": {}}
        
        # Run only specific detectors
        results = registry.detect_all(
            graph, 
            repomap, 
            detector_names=["microservices", "cloud_native"]
        )
        
        # Should only have results from specified detectors
        assert len(results) <= 2
        if "microservices" in results:
            assert all(r.pattern_type == "ServiceBoundaries" 
                      for r in results["microservices"])
    
    def test_confidence_filtering(self):
        """Test that low confidence results are filtered."""
        from batho_core.context.c4.detection.microservices import MicroserviceDetector
        
        detector = MicroserviceDetector(min_confidence=0.9)
        
        # Create data that would result in low confidence
        graph = {"entities": []}
        repomap = {"files": {"service.py": {"size": 100}}}
        
        results = detector.detect(graph, repomap)
        
        # Should filter out low confidence results
        assert len(results) == 0
    
    def test_error_handling(self):
        """Test error handling in detection system."""
        registry = DetectorRegistry()
        
        # Create a mock detector that raises an error
        class FailingDetector:
            name = "failing"
            min_confidence = 0.5
            
            def detect(self, graph, repomap, rules=None):
                raise Exception("Test error")
        
        registry.register(FailingDetector())
        
        # Should handle errors gracefully
        results = registry.detect_all({}, {})
        assert "failing" in results
        assert len(results["failing"]) == 0  # Empty list on error


@pytest.fixture
def temp_ctn_dir():
    """Create a temporary .ctn directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ctn_dir = Path(tmpdir)
        yield ctn_dir
