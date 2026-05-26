import os
import tempfile
import pytest
from batho.context.codegraph import InMemoryGraph
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType
from batho.bridge_core.services.amnesia import ContextAmnesiaAnalyzer
from pathlib import Path


class TestContextAmnesiaAnalyzer:
    def test_bfs_traversal(self):
        # Create a small graph
        graph = InMemoryGraph()
        
        e1 = Entity(
            type=EntityType.FUNCTION,
            name="func_a",
            file="a.py",
            start_line=1,
            end_line=10,
            raw_content="def func_a():\n    pass",
        )
        e2 = Entity(
            type=EntityType.FUNCTION,
            name="func_b",
            file="b.py",
            start_line=1,
            end_line=5,
            raw_content="def func_b():\n    pass",
        )
        e3 = Entity(
            type=EntityType.FUNCTION,
            name="func_c",
            file="c.py",
            start_line=1,
            end_line=5,
            raw_content="def func_c():\n    pass",
        )
        
        graph.add_entity(e1)
        graph.add_entity(e2)
        graph.add_entity(e3)
        
        r1 = Relationship(
            source_id=e1.id,
            target_id=e2.id,
            type=RelationshipType.CALLS
        )
        r2 = Relationship(
            source_id=e2.id,
            target_id=e3.id,
            type=RelationshipType.CALLS
        )
        
        graph.add_relationship(r1)
        graph.add_relationship(r2)
        
        analyzer = ContextAmnesiaAnalyzer(graph)
        
        # Analyze with a large context limit (should fit everything)
        analysis = analyzer.analyze(e1.id, context_limit=4000)
        assert analysis.center_node == e1.id
        assert len(analysis.within_reach) == 3
        assert len(analysis.amnesia_zone) == 0
        assert analysis.coverage_percent == 100.0
        
        # Analyze with a tiny context limit (should push some to amnesia zone)
        analysis_tiny = analyzer.analyze(e1.id, context_limit=5)
        # 5 tokens = 20 chars. Each entity is around 17-18 chars, so only 1 should fit.
        assert len(analysis_tiny.within_reach) < 3
        assert len(analysis_tiny.amnesia_zone) > 0
        assert analysis_tiny.coverage_percent < 100.0


class TestGreenTelemetry:
    def test_green_metrics(self):
        from batho.bridge_core.services.green_telemetry import GreenTelemetry, RequestMetrics
        
        telemetry = GreenTelemetry()
        
        # Record some metrics
        metrics = RequestMetrics(
            endpoint="neighborhood",
            duration_ms=50.0,
            cpu_time_ms=45.0,
            memory_delta_mb=1.0,
        )
        telemetry.record(metrics)
        
        stats = telemetry.get_stats()
        assert stats["total_requests"] == 1
        assert stats["avg_duration_ms"] == 50.0
        assert stats["avg_cpu_ms"] == 45.0
