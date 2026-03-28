"""
Tests for event-driven architecture pattern detection.
"""

import pytest

from batho_core.context.c4.detection.event_driven import EventDrivenDetector


class TestEventDrivenDetector:
    """Test cases for EventDrivenDetector."""
    
    def test_initialization(self):
        """Test detector initialization."""
        detector = EventDrivenDetector(min_confidence=0.6)
        assert detector.name == "event_driven"
        assert detector.min_confidence == 0.6
    
    def test_detect_message_brokers(self):
        """Test message broker detection."""
        detector = EventDrivenDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "kafka"},
                {"type": "IMPORTS", "target": "org.apache.kafka"},
                {"type": "IMPORTS", "target": "rabbitmq"}
            ]
        }
        
        repomap = {
            "files": {
                "kafka/config.yaml": {"size": 100},
                "rabbitmq/connection.py": {"size": 50}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect message brokers
        broker_results = [r for r in results if r.pattern_type == "MessageBrokers"]
        assert len(broker_results) > 0
        assert "kafka" in broker_results[0].metadata["brokers"]
        assert "rabbitmq" in broker_results[0].metadata["brokers"]
    
    def test_detect_event_flow(self):
        """Test event flow detection."""
        detector = EventDrivenDetector()
        
        graph = {
            "entities": [
                {"id": "e1", "name": "UserEventProducer", "type": "class"},
                {"id": "e2", "name": "OrderEventConsumer", "type": "class"},
                {"id": "e3", "name": "PaymentEventHandler", "type": "class"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should detect event flow
        flow_results = [r for r in results if r.pattern_type == "EventFlow"]
        assert len(flow_results) > 0
        assert flow_results[0].metadata["producer_count"] > 0
        assert flow_results[0].metadata["consumer_count"] > 0
    
    def test_detect_cqrs_patterns(self):
        """Test CQRS pattern detection."""
        detector = EventDrivenDetector()
        
        graph = {
            "entities": [
                {"id": "e1", "name": "CreateUserCommand", "type": "class"},
                {"id": "e2", "name": "CreateUserCommandHandler", "type": "class"},
                {"id": "e3", "name": "GetUserQuery", "type": "class"},
                {"id": "e4", "name": "UserReadModel", "type": "class"},
                {"id": "e5", "name": "UserWriteModel", "type": "class"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should detect CQRS
        cqrs_results = [r for r in results if r.pattern_type == "CQRS"]
        assert len(cqrs_results) > 0
        assert cqrs_results[0].metadata["command_count"] > 0
        assert cqrs_results[0].metadata["query_count"] > 0
        assert cqrs_results[0].metadata["has_separation"] is True
    
    def test_detect_event_sourcing(self):
        """Test event sourcing detection."""
        detector = EventDrivenDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "eventstore"},
                {"type": "IMPORTS", "target": "eventsourcing"}
            ],
            "entities": [
                {"id": "e1", "name": "UserEventStore", "type": "class"},
                {"id": "e2", "name": "UserAggregateRoot", "type": "class"},
                {"id": "e3", "name": "UserCreatedEvent", "type": "class"}
            ]
        }
        
        repomap = {
            "files": {
                "eventsourcing/config.json": {"size": 100}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect event sourcing
        es_results = [r for r in results if r.pattern_type == "EventSourcing"]
        assert len(es_results) > 0
        assert es_results[0].metadata["event_store_imports"] > 0
    
    def test_detect_stream_processing(self):
        """Test stream processing detection."""
        detector = EventDrivenDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "kafka-streams"},
                {"type": "IMPORTS", "target": "org.apache.flink"}
            ],
            "entities": [
                {"id": "e1", "name": "UserEventStream", "type": "class"},
                {"id": "e2", "name": "PaymentProcessor", "type": "class"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should detect stream processing
        stream_results = [r for r in results if r.pattern_type == "StreamProcessing"]
        assert len(stream_results) > 0
        assert stream_results[0].metadata["stream_imports"] > 0
    
    def test_no_event_driven_patterns(self):
        """Test when no event-driven patterns are found."""
        detector = EventDrivenDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "requests"},
                {"type": "IMPORTS", "target": "sqlalchemy"}
            ],
            "entities": [
                {"id": "e1", "name": "UserController", "type": "class"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should not detect any patterns
        assert len(results) == 0
