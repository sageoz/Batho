"""
Tests for repository analyzer.
"""

import pytest
from batho_core.context.c4.granularity.analyzer import RepositoryAnalyzer, RepositoryMetrics


class TestRepositoryAnalyzer:
    """Test repository analysis functionality."""
    
    def test_analyze_small_repository(self):
        """Test analysis of a small repository."""
        analyzer = RepositoryAnalyzer()
        
        # Small repository data
        graph = {
            "entities": [
                {"id": "e1", "name": "UserController", "type": "class", "file": "controllers/user.py"},
                {"id": "e2", "name": "UserService", "type": "class", "file": "services/user.py"},
                {"id": "e3", "name": "UserModel", "type": "class", "file": "models/user.py"}
            ],
            "relationships": [
                {"type": "IMPORTS", "source": "e1", "target": "e2"},
                {"type": "IMPORTS", "source": "e2", "target": "e3"}
            ]
        }
        
        repomap = {
            "files": {
                "controllers/user.py": {"size": 100},
                "services/user.py": {"size": 150},
                "models/user.py": {"size": 80}
            }
        }
        
        metrics = analyzer.analyze(graph, repomap)
        
        # Verify basic metrics
        assert metrics.entity_count == 3
        assert metrics.file_count == 3
        assert metrics.relationship_count == 2
        assert metrics.size_category == "small"
        
        # Verify calculated metrics
        assert 0 <= metrics.coupling_score <= 1
        assert 0 <= metrics.cohesion_score <= 1
        assert 0 <= metrics.complexity_score <= 1
        assert metrics.domain_count >= 1
        
        # Verify file size metrics
        assert metrics.avg_file_size == 110  # (100 + 150 + 80) / 3
        assert metrics.max_file_size == 150
    
    def test_analyze_large_repository(self):
        """Test analysis of a large repository."""
        analyzer = RepositoryAnalyzer()
        
        # Generate large repository data
        entities = []
        relationships = []
        files = {}
        
        for i in range(1500):
            entity_id = f"e{i}"
            entities.append({
                "id": entity_id,
                "name": f"Component{i}",
                "type": "class",
                "file": f"module{i}/component.py"
            })
            files[f"module{i}/component.py"] = {"size": 200}
            
            # Add some relationships
            if i > 0:
                relationships.append({
                    "type": "IMPORTS",
                    "source": f"e{i}",
                    "target": f"e{i-1}"
                })
        
        graph = {"entities": entities, "relationships": relationships}
        repomap = {"files": files}
        
        metrics = analyzer.analyze(graph, repomap)
        
        # Verify size categorization
        assert metrics.entity_count == 1500
        assert metrics.size_category == "large"
        assert metrics.package_count == 1500  # Each in its own module
    
    def test_analyze_massive_repository(self):
        """Test analysis of a massive repository."""
        analyzer = RepositoryAnalyzer()
        
        # Generate massive repository data
        entities = []
        relationships = []
        files = {}
        
        for i in range(15000):
            entity_id = f"e{i}"
            entities.append({
                "id": entity_id,
                "name": f"Component{i}",
                "type": "class",
                "file": f"module{i}/component.py"
            })
            files[f"module{i}/component.py"] = {"size": 300}
        
        graph = {"entities": entities, "relationships": relationships}
        repomap = {"files": files}
        
        metrics = analyzer.analyze(graph, repomap)
        
        # Verify size categorization
        assert metrics.entity_count == 15000
        assert metrics.size_category == "massive"
    
    def test_domain_detection(self):
        """Test domain boundary detection."""
        analyzer = RepositoryAnalyzer()
        
        graph = {
            "entities": [
                {"id": "e1", "name": "UserController", "type": "class", "file": "user/controller.py"},
                {"id": "e2", "name": "OrderService", "type": "class", "file": "order/service.py"},
                {"id": "e3", "name": "PaymentProcessor", "type": "class", "file": "payment/processor.py"},
                {"id": "e4", "name": "ProductCatalog", "type": "class", "file": "catalog/product.py"}
            ],
            "relationships": []
        }
        
        repomap = {"files": {}}
        
        metrics = analyzer.analyze(graph, repomap)
        
        # Should detect multiple domains
        assert metrics.domain_count >= 4  # user, order, payment, catalog
    
    def test_cohesion_calculation(self):
        """Test cohesion score calculation."""
        analyzer = RepositoryAnalyzer()
        
        # High cohesion: entities in same directory with relationships
        graph = {
            "entities": [
                {"id": "e1", "name": "UserModel", "type": "class", "file": "user/model.py"},
                {"id": "e2", "name": "UserService", "type": "class", "file": "user/service.py"},
                {"id": "e3", "name": "UserController", "type": "class", "file": "user/controller.py"}
            ],
            "relationships": [
                {"type": "IMPORTS", "source": "e2", "target": "e1"},
                {"type": "IMPORTS", "source": "e3", "target": "e2"}
            ]
        }
        
        repomap = {"files": {}}
        
        metrics = analyzer.analyze(graph, repomap)
        
        # Should have high cohesion (all relationships within same directory)
        assert metrics.cohesion_score > 0.5
    
    def test_coupling_calculation(self):
        """Test coupling score calculation."""
        analyzer = RepositoryAnalyzer()
        
        # High coupling: many cross-dependencies
        entities = []
        relationships = []
        
        for i in range(10):
            entities.append({
                "id": f"e{i}",
                "name": f"Component{i}",
                "type": "class",
                "file": f"module{i}/component.py"
            })
        
        # Create many cross-dependencies
        for i in range(10):
            for j in range(10):
                if i != j:
                    relationships.append({
                        "type": "IMPORTS",
                        "source": f"e{i}",
                        "target": f"e{j}"
                    })
        
        graph = {"entities": entities, "relationships": relationships}
        repomap = {"files": {}}
        
        metrics = analyzer.analyze(graph, repomap)
        
        # Should have high coupling
        assert metrics.coupling_score > 0.5
    
    def test_performance_targets(self):
        """Test performance target calculation."""
        analyzer = RepositoryAnalyzer()
        
        # Test small repository
        metrics = RepositoryMetrics(
            entity_count=50,
            size_category="small",
            complexity_score=0.3
        )
        
        targets = analyzer.get_performance_targets(metrics)
        
        assert targets["max_time_seconds"] <= 2.0  # Should be fast for small repos
        assert targets["use_parallel_processing"] == False
        assert targets["use_streaming"] == False
        assert targets["cache_enabled"] == True
        
        # Test large repository
        metrics = RepositoryMetrics(
            entity_count=5000,
            size_category="large",
            complexity_score=0.7
        )
        
        targets = analyzer.get_performance_targets(metrics)
        
        assert targets["max_time_seconds"] > 5.0  # More time for large repos
        assert targets["use_parallel_processing"] == True
        assert targets["use_streaming"] == False
        assert targets["cache_enabled"] == True
    
    def test_empty_repository(self):
        """Test analysis of empty repository."""
        analyzer = RepositoryAnalyzer()
        
        graph = {"entities": [], "relationships": []}
        repomap = {"files": {}}
        
        metrics = analyzer.analyze(graph, repomap)
        
        # Should handle empty repository gracefully
        assert metrics.entity_count == 0
        assert metrics.size_category == "small"
        assert metrics.coupling_score == 0.0
        assert metrics.cohesion_score == 0.0
        assert metrics.complexity_score == 0.0
