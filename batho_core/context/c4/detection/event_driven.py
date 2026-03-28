"""
Event-driven architecture pattern detector.
"""

from typing import Any, Dict, List, Optional, Set
from collections import defaultdict

from .base import PatternDetector, DetectionResult


class EventDrivenDetector(PatternDetector):
    """Detector for event-driven architecture patterns."""
    
    def __init__(self, min_confidence: float = 0.5):
        super().__init__("event_driven", min_confidence)
        
        # Message broker patterns
        self.message_brokers = {
            "kafka": ["kafka", "org.apache.kafka", "confluent"],
            "rabbitmq": ["rabbitmq", "amqp", "pika"],
            "pulsar": ["pulsar", "org.apache.pulsar"],
            "nats": ["nats", "nats.io", "stan"],
            "sqs": ["sqs", "boto3.sqs"],
            "sns": ["sns", "boto3.sns"]
        }
        
        # Event pattern indicators
        self.event_patterns = [
            "event", "message", "publish", "subscribe", "emit", "dispatch"
        ]
        
        # CQRS patterns
        self.cqrs_patterns = [
            "command", "query", "cqrs", "readmodel", "writemodel"
        ]
        
        # Event sourcing patterns
        self.event_sourcing_patterns = [
            "eventsourcing", "eventstore", "event-sourcing", "snapshot"
        ]
    
    def detect(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any],
        rules: Optional[Dict[str, Any]] = None
    ) -> List[DetectionResult]:
        """Detect event-driven architecture patterns."""
        results = []
        
        # Detect message brokers
        broker_result = self._detect_message_brokers(graph, repomap)
        if broker_result:
            results.append(broker_result)
        
        # Detect event producers/consumers
        event_flow_result = self._detect_event_flow(graph, repomap)
        if event_flow_result:
            results.append(event_flow_result)
        
        # Detect CQRS patterns
        cqrs_result = self._detect_cqrs_patterns(graph, repomap)
        if cqrs_result:
            results.append(cqrs_result)
        
        # Detect event sourcing
        event_sourcing_result = self._detect_event_sourcing(graph, repomap)
        if event_sourcing_result:
            results.append(event_sourcing_result)
        
        # Detect stream processing
        stream_result = self._detect_stream_processing(graph, repomap)
        if stream_result:
            results.append(stream_result)
        
        return results
    
    def _detect_message_brokers(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect message broker usage."""
        detected_brokers = {}
        
        # Check for each message broker
        for broker_name, patterns in self.message_brokers.items():
            imports = self._find_imports_by_pattern(graph, patterns)
            files = self._find_files_by_pattern(repomap, patterns)
            
            if imports or files:
                detected_brokers[broker_name] = {
                    "imports": imports,
                    "files": files,
                    "usage_count": len(imports) + len(files)
                }
        
        if not detected_brokers:
            return None
        
        # Calculate confidence based on number of brokers and usage
        confidence = min(1.0, len(detected_brokers) / 3.0)
        
        if confidence < self.min_confidence:
            return None
        
        # Create broker entities
        entities = []
        for broker_name, info in detected_brokers.items():
            entities.append({
                "id": f"broker-{broker_name}",
                "name": broker_name.title(),
                "type": "MessageBroker",
                "usage_count": info["usage_count"],
                "description": f"Message broker: {broker_name}"
            })
        
        return DetectionResult(
            pattern_type="MessageBrokers",
            confidence=confidence,
            entities=entities,
            relationships=[],
            metadata={
                "broker_count": len(detected_brokers),
                "brokers": list(detected_brokers.keys())
            }
        )
    
    def _detect_event_flow(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect event producers and consumers."""
        # Find event-related entities
        producer_entities = self._find_entities_by_pattern(
            graph, ["*Producer*", "*Publisher*", "*Emitter*"]
        )
        
        consumer_entities = self._find_entities_by_pattern(
            graph, ["*Consumer*", "*Subscriber*", "*Listener*"]
        )
        
        handler_entities = self._find_entities_by_pattern(
            graph, ["*Handler*", "*Processor*"]
        )
        
        if not (producer_entities or consumer_entities):
            return None
        
        # Calculate confidence
        confidence_indicators = [
            len(producer_entities) > 0,
            len(consumer_entities) > 0,
            len(handler_entities) > 0,
            len(producer_entities) + len(consumer_entities) > 2
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Combine all event-related entities
        all_entities = producer_entities + consumer_entities + handler_entities
        
        # Find event relationships
        relationships = self._find_event_relationships(graph, all_entities)
        
        return DetectionResult(
            pattern_type="EventFlow",
            confidence=confidence,
            entities=all_entities,
            relationships=relationships,
            metadata={
                "producer_count": len(producer_entities),
                "consumer_count": len(consumer_entities),
                "handler_count": len(handler_entities)
            }
        )
    
    def _detect_cqrs_patterns(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect CQRS (Command Query Responsibility Segregation) patterns."""
        # Find CQRS-related entities
        command_entities = self._find_entities_by_pattern(
            graph, ["*Command*", "*CommandHandler*"]
        )
        
        query_entities = self._find_entities_by_pattern(
            graph, ["*Query*", "*QueryHandler*"]
        )
        
        read_model_entities = self._find_entities_by_pattern(
            graph, ["*ReadModel*", "*Projection*"]
        )
        
        write_model_entities = self._find_entities_by_pattern(
            graph, ["*WriteModel*", "*Aggregate*"]
        )
        
        if not (command_entities or query_entities):
            return None
        
        # Calculate confidence
        has_commands = len(command_entities) > 0
        has_queries = len(query_entities) > 0
        has_separation = len(read_model_entities) > 0 or len(write_model_entities) > 0
        
        confidence_indicators = [has_commands, has_queries, has_separation]
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Combine all CQRS entities
        all_entities = (
            command_entities + query_entities + 
            read_model_entities + write_model_entities
        )
        
        # Find CQRS relationships
        relationships = self._find_cqrs_relationships(
            graph, command_entities, query_entities
        )
        
        return DetectionResult(
            pattern_type="CQRS",
            confidence=confidence,
            entities=all_entities,
            relationships=relationships,
            metadata={
                "command_count": len(command_entities),
                "query_count": len(query_entities),
                "read_model_count": len(read_model_entities),
                "write_model_count": len(write_model_entities),
                "has_separation": has_separation
            }
        )
    
    def _detect_event_sourcing(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect event sourcing patterns."""
        # Find event sourcing indicators
        es_imports = self._find_imports_by_pattern(
            graph, self.event_sourcing_patterns
        )
        
        es_entities = self._find_entities_by_pattern(
            graph, ["*EventStore*", "*EventSourcing*", "*AggregateRoot*"]
        )
        
        es_files = self._find_files_by_pattern(
            repomap, self.event_sourcing_patterns
        )
        
        if not (es_imports or es_entities or es_files):
            return None
        
        # Calculate confidence
        confidence_indicators = [
            len(es_imports) > 0,
            len(es_entities) > 0,
            len(es_files) > 0
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Find event entities
        event_entities = self._find_entities_by_pattern(
            graph, ["*Event*", "*DomainEvent*"]
        )
        
        return DetectionResult(
            pattern_type="EventSourcing",
            confidence=confidence,
            entities=es_entities + event_entities,
            relationships=[],
            metadata={
                "event_store_imports": len(es_imports),
                "event_store_entities": len(es_entities),
                "event_store_files": len(es_files),
                "event_entities": len(event_entities)
            }
        )
    
    def _detect_stream_processing(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect stream processing patterns."""
        stream_patterns = [
            "kafka-streams", "flink", "spark-streaming", 
            "kinesis", "beam", "storm"
        ]
        
        # Find stream processing indicators
        stream_imports = self._find_imports_by_pattern(graph, stream_patterns)
        stream_entities = self._find_entities_by_pattern(
            graph, ["*Stream*", "*Processor*", "*Topology*"]
        )
        
        if not (stream_imports or stream_entities):
            return None
        
        # Calculate confidence
        confidence = min(1.0, (len(stream_imports) + len(stream_entities)) / 5.0)
        
        if confidence < self.min_confidence:
            return None
        
        return DetectionResult(
            pattern_type="StreamProcessing",
            confidence=confidence,
            entities=stream_entities,
            relationships=[],
            metadata={
                "stream_imports": len(stream_imports),
                "stream_entities": len(stream_entities)
            }
        )
    
    def _find_event_relationships(
        self,
        graph: Dict[str, Any],
        event_entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Find relationships between event-related entities."""
        relationships = []
        entity_ids = {e.get("id") for e in event_entities}
        
        for rel in graph.get("relationships", []):
            if (rel.get("source") in entity_ids or 
                rel.get("target") in entity_ids):
                
                # Check if this is an event-related relationship
                rel_type = rel.get("type", "").lower()
                if any(pattern in rel_type for pattern in self.event_patterns):
                    relationships.append(rel)
        
        return relationships
    
    def _find_cqrs_relationships(
        self,
        graph: Dict[str, Any],
        command_entities: List[Dict[str, Any]],
        query_entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Find CQRS-specific relationships."""
        relationships = []
        
        # Find command to event relationships
        command_ids = {e.get("id") for e in command_entities}
        
        for rel in graph.get("relationships", []):
            if rel.get("source") in command_ids:
                rel_type = rel.get("type", "").lower()
                if "event" in rel_type or "publish" in rel_type:
                    relationships.append({
                        **rel,
                        "cqrs_type": "CommandToEvent"
                    })
        
        # Find query to read model relationships
        query_ids = {e.get("id") for e in query_entities}
        
        for rel in graph.get("relationships", []):
            if rel.get("source") in query_ids:
                rel_type = rel.get("type", "").lower()
                if "read" in rel_type or "query" in rel_type:
                    relationships.append({
                        **rel,
                        "cqrs_type": "QueryToRead"
                    })
        
        return relationships
