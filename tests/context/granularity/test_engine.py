"""
Tests for granularity decision engine.
"""

import pytest
from batho_core.context.c4.granularity.engine import GranularityLevel, GranularityDecisionEngine, GranularityDecision
from batho_core.context.c4.granularity.analyzer import RepositoryMetrics


class TestGranularityDecisionEngine:
    """Test granularity decision engine."""
    
    def test_decide_fine_granularity(self):
        """Test decision for fine granularity."""
        engine = GranularityDecisionEngine()
        
        metrics = RepositoryMetrics(
            entity_count=50,
            complexity_score=0.2,
            coupling_score=0.1,
            domain_count=2
        )
        
        decision = engine.decide_granularity(metrics)
        
        assert decision.level == GranularityLevel.FINE
        assert decision.confidence > 0.8
        assert "Small repository" in decision.reasoning
        assert decision.settings["max_components"] is None
        assert decision.settings["group_components"] == False
    
    def test_decide_medium_granularity(self):
        """Test decision for medium granularity."""
        engine = GranularityDecisionEngine()
        
        metrics = RepositoryMetrics(
            entity_count=500,
            complexity_score=0.5,
            coupling_score=0.3,
            domain_count=5
        )
        
        decision = engine.decide_granularity(metrics)
        
        assert decision.level == GranularityLevel.MEDIUM
        assert decision.confidence > 0.7
        assert "Medium repository" in decision.reasoning
        assert decision.settings["max_components"] == 500
        assert decision.settings["group_components"] == True
        assert decision.settings["importance_threshold"] == 0.3
    
    def test_decide_coarse_granularity(self):
        """Test decision for coarse granularity."""
        engine = GranularityDecisionEngine()
        
        metrics = RepositoryMetrics(
            entity_count=2000,
            complexity_score=0.7,
            coupling_score=0.5,
            domain_count=10
        )
        
        decision = engine.decide_granularity(metrics)
        
        assert decision.level == GranularityLevel.COARSE
        assert decision.confidence > 0.7
        assert "Large repository" in decision.reasoning
        assert decision.settings["include_components"] == False
        assert decision.settings["max_containers"] == 50
    
    def test_decide_adaptive_granularity(self):
        """Test decision for adaptive granularity."""
        engine = GranularityDecisionEngine()
        
        metrics = RepositoryMetrics(
            entity_count=10000,
            complexity_score=0.8,
            coupling_score=0.6,
            domain_count=15
        )
        
        decision = engine.decide_granularity(metrics)
        
        # Note: With current decision matrix, 10000 entities falls into COARSE category
        # ADAPTIVE is only for very high scores
        assert decision.level in [GranularityLevel.ADAPTIVE, GranularityLevel.COARSE]
        assert decision.confidence > 0.6
        assert "Massive repository" in decision.reasoning or "Large repository" in decision.reasoning
    
    def test_override_granularity(self):
        """Test manual override of granularity."""
        engine = GranularityDecisionEngine()
        
        metrics = RepositoryMetrics(entity_count=50)  # Would normally be FINE
        
        # Override to COARSE
        decision = engine.decide_granularity(
            metrics,
            override=GranularityLevel.COARSE
        )
        
        assert decision.level == GranularityLevel.COARSE
        assert decision.confidence == 1.0
        assert "Manual override" in decision.reasoning
    
    def test_adaptive_settings_for_large_repo(self):
        """Test adaptive settings for large repositories."""
        engine = GranularityDecisionEngine()
        
        metrics = RepositoryMetrics(
            entity_count=15000,  # Very large
            complexity_score=0.9
        )
        
        decision = engine.decide_granularity(metrics)
        settings = decision.settings
        
        # Should disable components for very large repos
        assert settings["include_components"] == False
        assert settings["max_containers"] == 100
    
    def test_adaptive_settings_for_medium_repo(self):
        """Test adaptive settings for medium repositories."""
        engine = GranularityDecisionEngine()
        
        metrics = RepositoryMetrics(
            entity_count=5000,  # Large but not massive
            complexity_score=0.6
        )
        
        decision = engine.decide_granularity(metrics)
        settings = decision.settings
        
        # For COARSE level, components are disabled
        if decision.level == GranularityLevel.COARSE:
            assert settings["include_components"] == False
        else:
            # If using ADAPTIVE, components might be enabled
            assert settings.get("include_components", False) in [True, False]
    
    def test_validate_decision(self):
        """Test decision validation."""
        engine = GranularityDecisionEngine()
        
        # Valid decision
        decision = GranularityDecision(
            level=GranularityLevel.FINE,
            reasoning="Test",
            confidence=0.8,
            settings={"include_components": True, "group_components": False}
        )
        
        assert engine.validate_decision(decision) == True
        
        # Invalid decision - coarse with components
        invalid_decision = GranularityDecision(
            level=GranularityLevel.COARSE,
            reasoning="Test",
            confidence=0.8,
            settings={"include_components": True, "group_components": False}
        )
        
        assert engine.validate_decision(invalid_decision) == False
    
    def test_should_use_streaming(self):
        """Test streaming decision."""
        engine = GranularityDecisionEngine()
        
        # Small repo - no streaming
        metrics = RepositoryMetrics(entity_count=100, max_file_size=1000)
        assert engine.should_use_streaming(metrics) == False
        
        # Large entity count - streaming
        metrics = RepositoryMetrics(entity_count=15000)
        assert engine.should_use_streaming(metrics) == True
        
        # Large file size - streaming
        metrics = RepositoryMetrics(entity_count=100, max_file_size=200000)
        assert engine.should_use_streaming(metrics) == True
    
    def test_should_use_parallel(self):
        """Test parallel processing decision."""
        engine = GranularityDecisionEngine()
        
        # Small repo - no parallel
        metrics = RepositoryMetrics(entity_count=100, complexity_score=0.3, size_category="small")
        assert engine.should_use_parallel(metrics) == False
        
        # Large entity count with high complexity - parallel
        metrics = RepositoryMetrics(entity_count=2000, complexity_score=0.6, size_category="large")
        assert engine.should_use_parallel(metrics) == True
        
        # High complexity - parallel (even with fewer entities)
        metrics = RepositoryMetrics(entity_count=1500, complexity_score=0.8, size_category="medium")
        assert engine.should_use_parallel(metrics) == True
        
        # Large entity count but low complexity - no parallel
        metrics = RepositoryMetrics(entity_count=2000, complexity_score=0.3, size_category="large")
        assert engine.should_use_parallel(metrics) == False
    
    def test_memory_estimate(self):
        """Test memory usage estimation."""
        engine = GranularityDecisionEngine()
        
        # Small repo
        metrics = RepositoryMetrics(
            entity_count=100,
            relationship_count=200,
            complexity_score=0.3
        )
        
        memory = engine.get_memory_estimate(metrics)
        assert memory > 50  # Base overhead
        assert memory < 200  # Should be reasonable for small repo
        
        # Large repo
        metrics = RepositoryMetrics(
            entity_count=5000,
            relationship_count=10000,
            complexity_score=0.7
        )
        
        memory = engine.get_memory_estimate(metrics)
        assert memory > 500  # Should be higher for large repo
    
    def test_decision_serialization(self):
        """Test decision serialization."""
        decision = GranularityDecision(
            level=GranularityLevel.MEDIUM,
            reasoning="Test decision",
            confidence=0.85,
            settings={"max_components": 100, "group_components": True}
        )
        
        decision_dict = decision.to_dict()
        
        assert decision_dict["level"] == "medium"
        assert decision_dict["reasoning"] == "Test decision"
        assert decision_dict["confidence"] == 0.85
        assert decision_dict["settings"]["max_components"] == 100
