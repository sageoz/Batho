"""
Data architecture pattern detector.
"""

from typing import Any, Dict, List, Optional, Set
from collections import defaultdict

from .base import PatternDetector, DetectionResult


class DataPatternDetector(PatternDetector):
    """Detector for data architecture patterns."""
    
    def __init__(self, min_confidence: float = 0.5):
        super().__init__("data_patterns", min_confidence)
        
        # Sharding patterns
        self.sharding_patterns = {
            "shardingsphere": ["shardingsphere", "apache.shardingsphere"],
            "vitess": ["vitess", "vitess.io"],
            "citus": ["citus", "citusdata"]
        }
        
        # Replication patterns
        self.replication_patterns = [
            "replication", "replica", "master", "slave", "read-replica",
            "pglogical", "wal2json", "mongodb-replica"
        ]
        
        # CQRS patterns
        self.cqrs_patterns = {
            "axon": ["axon", "axonframework"],
            "mediatr": ["mediatr", "mediat-r"],
            "eventflow": ["eventflow", "event-flow"]
        }
        
        # Database types for polyglot persistence
        self.database_types = {
            "sql": ["sql", "mysql", "postgresql", "oracle", "sqlserver"],
            "nosql": ["mongodb", "cassandra", "dynamodb", "couchdb"],
            "graph": ["neo4j", "orientdb", "arangodb"],
            "search": ["elasticsearch", "solr", "algolia"],
            "cache": ["redis", "memcached", "hazelcast"]
        }
        
        # Migration tools
        self.migration_patterns = {
            "flyway": ["flyway", "org.flywaydb"],
            "liquibase": ["liquibase", "org.liquibase"],
            "prisma": ["prisma", "@prisma"]
        }
    
    def detect(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any],
        rules: Optional[Dict[str, Any]] = None
    ) -> List[DetectionResult]:
        """Detect data architecture patterns."""
        results = []
        
        # Detect database sharding
        sharding_result = self._detect_sharding(graph, repomap)
        if sharding_result:
            results.append(sharding_result)
        
        # Detect database replication
        replication_result = self._detect_replication(graph, repomap)
        if replication_result:
            results.append(replication_result)
        
        # Detect CQRS patterns
        cqrs_result = self._detect_cqrs(graph, repomap)
        if cqrs_result:
            results.append(cqrs_result)
        
        # Detect polyglot persistence
        polyglot_result = self._detect_polyglot_persistence(graph, repomap)
        if polyglot_result:
            results.append(polyglot_result)
        
        # Detect database migrations
        migration_result = self._detect_migrations(graph, repomap)
        if migration_result:
            results.append(migration_result)
        
        return results
    
    def _detect_sharding(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect database sharding implementations."""
        detected_sharding = {}
        
        # Check for each sharding solution
        for solution, patterns in self.sharding_patterns.items():
            imports = self._find_imports_by_pattern(graph, patterns)
            files = self._find_files_by_pattern(repomap, patterns)
            
            if imports or files:
                detected_sharding[solution] = {
                    "imports": imports,
                    "files": files,
                    "usage_count": len(imports) + len(files)
                }
        
        if not detected_sharding:
            return None
        
        # Calculate confidence
        confidence = min(1.0, len(detected_sharding) / 2.0)
        
        if confidence < self.min_confidence:
            return None
        
        # Find sharding-related entities
        sharding_entities = self._find_entities_by_pattern(
            graph, ["*Shard*", "*Partition*", "*Sharding*"]
        )
        
        return DetectionResult(
            pattern_type="DatabaseSharding",
            confidence=confidence,
            entities=sharding_entities,
            relationships=[],
            metadata={
                "sharding_solutions": list(detected_sharding.keys()),
                "total_implementations": sum(
                    info["usage_count"] for info in detected_sharding.values()
                )
            }
        )
    
    def _detect_replication(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect database replication setups."""
        # Find replication-related files and imports
        replication_files = self._find_files_by_pattern(
            repomap, self.replication_patterns
        )
        
        replication_imports = self._find_imports_by_pattern(
            graph, self.replication_patterns
        )
        
        replication_entities = self._find_entities_by_pattern(
            graph, ["*Replica*", "*Replication*", "*Master*", "*Slave*"]
        )
        
        if not (replication_files or replication_imports or replication_entities):
            return None
        
        # Calculate confidence
        confidence_indicators = [
            len(replication_files) > 0,
            len(replication_imports) > 0,
            len(replication_entities) > 0,
            any("read-replica" in f.lower() or "replica" in f.lower() 
                for f in replication_files)
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Analyze replication topology
        topology = self._analyze_replication_topology(
            replication_files, replication_entities
        )
        
        return DetectionResult(
            pattern_type="DatabaseReplication",
            confidence=confidence,
            entities=replication_entities,
            relationships=[],
            metadata={
                "replication_files": replication_files,
                "topology": topology,
                "entity_count": len(replication_entities)
            }
        )
    
    def _detect_cqrs(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect CQRS (Command Query Responsibility Segregation)."""
        detected_cqrs = {}
        
        # Check for each CQRS framework
        for framework, patterns in self.cqrs_patterns.items():
            imports = self._find_imports_by_pattern(graph, patterns)
            files = self._find_files_by_pattern(repomap, patterns)
            
            if imports or files:
                detected_cqrs[framework] = {
                    "imports": imports,
                    "files": files,
                    "usage_count": len(imports) + len(files)
                }
        
        # Find CQRS entities
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
        
        has_cqrs_entities = bool(
            command_entities or query_entities or 
            read_model_entities or write_model_entities
        )
        
        if not detected_cqrs and not has_cqrs_entities:
            return None
        
        # Calculate confidence
        confidence_indicators = [
            len(detected_cqrs) > 0,
            has_cqrs_entities,
            len(command_entities) > 0,
            len(query_entities) > 0,
            len(read_model_entities) > 0
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Combine all CQRS entities
        all_entities = (
            command_entities + query_entities + 
            read_model_entities + write_model_entities
        )
        
        return DetectionResult(
            pattern_type="CQRS",
            confidence=confidence,
            entities=all_entities,
            relationships=[],
            metadata={
                "frameworks": list(detected_cqrs.keys()),
                "command_count": len(command_entities),
                "query_count": len(query_entities),
                "read_model_count": len(read_model_entities),
                "write_model_count": len(write_model_entities),
                "has_separation": len(read_model_entities) > 0
            }
        )
    
    def _detect_polyglot_persistence(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect polyglot persistence (multiple database types)."""
        detected_databases = {}
        
        # Check for each database type
        for db_type, patterns in self.database_types.items():
            imports = self._find_imports_by_pattern(graph, patterns)
            files = self._find_files_by_pattern(repomap, patterns)
            
            if imports or files:
                detected_databases[db_type] = {
                    "imports": imports,
                    "files": files,
                    "usage_count": len(imports) + len(files)
                }
        
        # Need at least 2 different database types for polyglot
        if len(detected_databases) < 2:
            return None
        
        # Calculate confidence based on diversity
        confidence = min(1.0, len(detected_databases) / 4.0)
        
        if confidence < self.min_confidence:
            return None
        
        # Create database entities
        entities = []
        for db_type, info in detected_databases.items():
            entities.append({
                "id": f"db-{db_type}",
                "name": f"{db_type.title()} Database",
                "type": "Database",
                "usage_count": info["usage_count"],
                "description": f"{db_type.title()} database storage"
            })
        
        return DetectionResult(
            pattern_type="PolyglotPersistence",
            confidence=confidence,
            entities=entities,
            relationships=[],
            metadata={
                "database_types": list(detected_databases.keys()),
                "total_databases": len(detected_databases),
                "most_used": max(detected_databases.items(), 
                               key=lambda x: x[1]["usage_count"])[0]
            }
        )
    
    def _detect_migrations(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect database migration tools."""
        detected_migrations = {}
        
        # Check for each migration tool
        for tool, patterns in self.migration_patterns.items():
            imports = self._find_imports_by_pattern(graph, patterns)
            files = self._find_files_by_pattern(repomap, patterns)
            
            if imports or files:
                detected_migrations[tool] = {
                    "imports": imports,
                    "files": files,
                    "usage_count": len(imports) + len(files)
                }
        
        if not detected_migrations:
            return None
        
        # Calculate confidence
        confidence = min(1.0, len(detected_migrations) / 2.0)
        
        if confidence < self.min_confidence:
            return None
        
        # Find migration files
        migration_files = []
        for file_path in repomap.get("files", {}).keys():
            file_lower = file_path.lower()
            if any(pattern in file_lower for pattern in ["migration", "migrate"]):
                migration_files.append(file_path)
        
        return DetectionResult(
            pattern_type="DatabaseMigrations",
            confidence=confidence,
            entities=[],
            relationships=[],
            metadata={
                "migration_tools": list(detected_migrations.keys()),
                "migration_files": migration_files,
                "total_migrations": len(migration_files)
            }
        )
    
    def _analyze_replication_topology(
        self,
        replication_files: List[str],
        replication_entities: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze the replication topology."""
        topology = {
            "type": "unknown",
            "has_read_replicas": False,
            "has_master_slave": False,
            "has_multi_master": False
        }
        
        # Analyze file names for topology hints
        for file_path in replication_files:
            file_lower = file_path.lower()
            
            if "read-replica" in file_lower or "readonly" in file_lower:
                topology["has_read_replicas"] = True
                topology["type"] = "master-slave"
            
            if "master" in file_lower and "slave" in file_lower:
                topology["has_master_slave"] = True
                topology["type"] = "master-slave"
            
            if "multi-master" in file_lower or "multi-master" in file_lower:
                topology["has_multi_master"] = True
                topology["type"] = "multi-master"
        
        # Analyze entities for additional hints
        entity_names = [e.get("name", "").lower() for e in replication_entities]
        
        if any("master" in name and "slave" in name for name in entity_names):
            topology["has_master_slave"] = True
        
        if any("replica" in name or "readonly" in name for name in entity_names):
            topology["has_read_replicas"] = True
        
        return topology
