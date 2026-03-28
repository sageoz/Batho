"""
Tests for data architecture pattern detection.
"""

import pytest

from batho_core.context.c4.detection.data_patterns import DataPatternDetector


class TestDataPatternDetector:
    """Test cases for DataPatternDetector."""
    
    def test_initialization(self):
        """Test detector initialization."""
        detector = DataPatternDetector(min_confidence=0.6)
        assert detector.name == "data_patterns"
        assert detector.min_confidence == 0.6
    
    def test_detect_sharding(self):
        """Test database sharding detection."""
        detector = DataPatternDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "shardingsphere"},
                {"type": "IMPORTS", "target": "apache.shardingsphere"}
            ],
            "entities": [
                {"id": "e1", "name": "UserShardManager", "type": "class"},
                {"id": "e2", "name": "OrderPartitionHandler", "type": "class"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should detect sharding
        sharding_results = [r for r in results if r.pattern_type == "DatabaseSharding"]
        assert len(sharding_results) > 0
        assert "shardingsphere" in sharding_results[0].metadata["sharding_solutions"]
    
    def test_detect_replication(self):
        """Test database replication detection."""
        detector = DataPatternDetector()
        
        graph = {
            "entities": [
                {"id": "e1", "name": "MasterDatabase", "type": "class"},
                {"id": "e2", "name": "SlaveDatabase", "type": "class"},
                {"id": "e3", "name": "ReadReplicaManager", "type": "class"}
            ]
        }
        
        repomap = {
            "files": {
                "config/read-replica.yaml": {"size": 100},
                "database/replication.py": {"size": 150}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect replication
        replication_results = [r for r in results if r.pattern_type == "DatabaseReplication"]
        assert len(replication_results) > 0
        assert replication_results[0].metadata["topology"]["has_read_replicas"] is True
    
    def test_detect_cqrs(self):
        """Test CQRS detection."""
        detector = DataPatternDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "axon"},
                {"type": "IMPORTS", "target": "mediatr"}
            ],
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
        assert "axon" in cqrs_results[0].metadata["frameworks"]
        assert cqrs_results[0].metadata["has_separation"] is True
    
    def test_detect_polyglot_persistence(self):
        """Test polyglot persistence detection."""
        detector = DataPatternDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "mysql"},
                {"type": "IMPORTS", "target": "mongodb"},
                {"type": "IMPORTS", "target": "redis"},
                {"type": "IMPORTS", "target": "elasticsearch"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should detect polyglot persistence
        polyglot_results = [r for r in results if r.pattern_type == "PolyglotPersistence"]
        assert len(polyglot_results) > 0
        assert len(polyglot_results[0].metadata["database_types"]) >= 2
        assert "sql" in polyglot_results[0].metadata["database_types"]
        assert "nosql" in polyglot_results[0].metadata["database_types"]
    
    def test_detect_migrations(self):
        """Test database migration detection."""
        detector = DataPatternDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "flyway"},
                {"type": "IMPORTS", "target": "org.flywaydb"},
                {"type": "IMPORTS", "target": "liquibase"}
            ]
        }
        
        repomap = {
            "files": {
                "migrations/V1__Initial.sql": {"size": 100},
                "migrations/V2__AddUsers.sql": {"size": 50},
                "db/migrate/001_create_users.sql": {"size": 75}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect migrations
        migration_results = [r for r in results if r.pattern_type == "DatabaseMigrations"]
        assert len(migration_results) > 0
        assert "flyway" in migration_results[0].metadata["migration_tools"]
        assert "liquibase" in migration_results[0].metadata["migration_tools"]
        assert len(migration_results[0].metadata["migration_files"]) > 0
    
    def test_no_data_patterns(self):
        """Test when no data patterns are found."""
        detector = DataPatternDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "flask"},
                {"type": "IMPORTS", "target": "requests"}
            ],
            "entities": [
                {"id": "e1", "name": "UserController", "type": "class"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should not detect any patterns
        assert len(results) == 0
    
    def test_insufficient_polyglot_persistence(self):
        """Test that single database type doesn't count as polyglot."""
        detector = DataPatternDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "mysql"},
                {"type": "IMPORTS", "target": "sqlalchemy"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should not detect polyglot with only one database type
        polyglot_results = [r for r in results if r.pattern_type == "PolyglotPersistence"]
        assert len(polyglot_results) == 0
