"""Tests for C4 generator."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from batho_core.context.c4_generator import C4Generator


class TestC4Generator:
    """Test cases for C4Generator class."""

    @pytest.fixture
    def mock_graph(self):
        """Mock graph data."""
        return {
            "entities": [
                {
                    "id": "entity1",
                    "type": "class",
                    "name": "UserService",
                    "file": "/src/services/user_service.py",
                    "start_line": 10,
                    "end_line": 50,
                    "signature": "class UserService:"
                },
                {
                    "id": "entity2",
                    "type": "function",
                    "name": "main",
                    "file": "/src/main.py",
                    "start_line": 1,
                    "end_line": 20,
                    "signature": "def main():"
                }
            ],
            "relationships": [
                {
                    "id": "rel1",
                    "source_id": "entity2",
                    "target_id": "entity1",
                    "type": "CALLS"
                },
                {
                    "id": "rel2",
                    "source": "/src/services/user_service.py",
                    "target": "sqlalchemy",
                    "type": "IMPORTS"
                }
            ]
        }
    
    @pytest.fixture
    def mock_repomap(self):
        """Mock repomap data."""
        return {
            "files": {
                "src/services/user_service.py": [
                    {"name": "UserService", "type": "class"}
                ],
                "src/main.py": [
                    {"name": "main", "type": "function"}
                ]
            }
        }
    
    @pytest.fixture
    def mock_index_metadata(self):
        """Mock index metadata."""
        return {
            "root": "/test/project",
            "entity_count": 100,
            "relationship_count": 80,
            "stack": {
                "languages": ["Python 3.12"],
                "frameworks": ["Flask", "SQLAlchemy", "pytest"],
                "build_tools": ["Hatch"]
            }
        }
    
    @pytest.fixture
    def c4_generator(self, tmp_path, mock_graph, mock_repomap, mock_index_metadata):
        """Create C4Generator instance with mock data."""
        # Create mock .ctn directory structure
        ctn_dir = tmp_path / ".ctn"
        index_id = "test_index_123"
        versioned_dir = ctn_dir / index_id
        versioned_dir.mkdir(parents=True)
        
        # Write mock files
        (versioned_dir / "graph.json").write_text(json.dumps(mock_graph))
        (versioned_dir / "repomap.json").write_text(json.dumps(mock_repomap))
        
        # Write index.json
        index_data = {
            "current_index_id": index_id,
            "indexes": {index_id: mock_index_metadata}
        }
        (ctn_dir / "index.json").write_text(json.dumps(index_data))
        
        return C4Generator(ctn_dir, index_id)
    
    def test_load_artifacts(self, c4_generator):
        """Test that artifacts are loaded correctly."""
        assert c4_generator.graph is not None
        assert c4_generator.repomap is not None
        assert c4_generator.index_metadata is not None
        assert "entities" in c4_generator.graph
        assert "files" in c4_generator.repomap
        assert "stack" in c4_generator.index_metadata
    
    def test_generate_c4_model(self, c4_generator):
        """Test C4 model generation."""
        model = c4_generator.generate_c4_model()
        
        # Check basic structure
        assert "name" in model
        assert "model" in model
        assert "views" in model
        assert "llm_extensions" in model
        
        # Check model sections
        assert "people" in model["model"]
        assert "softwareSystems" in model["model"]
        assert "containers" in model["model"]
        assert "components" in model["model"]
        
        # Should have at least one software system
        assert len(model["model"]["softwareSystems"]) > 0
        
        # Should detect database from SQLAlchemy import
        people = model["model"]["people"]
        database_actors = [p for p in people if p["name"] == "Database"]
        assert len(database_actors) > 0
    
    def test_analyze_imports(self, c4_generator):
        """Test import analysis."""
        analysis = c4_generator._analyze_imports()
        
        assert "external_systems" in analysis
        assert "external_actors" in analysis
        assert "Database" in analysis["external_systems"]
        assert "Database" in analysis["external_actors"]
    
    def test_calculate_entity_importance(self, c4_generator):
        """Test entity importance calculation."""
        importance = c4_generator._calculate_entity_importance()
        
        assert isinstance(importance, dict)
        assert "entity1" in importance
        assert "entity2" in importance
        assert all(0 <= score <= 1 for score in importance.values())
    
    def test_generate_people(self, c4_generator):
        """Test people (actors) generation."""
        people = c4_generator._generate_people()
        
        assert isinstance(people, list)
        # Should have Database actor from SQLAlchemy import
        database_actors = [p for p in people if p["name"] == "Database"]
        assert len(database_actors) > 0
        
        # Check actor structure
        for actor in people:
            assert "id" in actor
            assert "name" in actor
            assert "description" in actor
            assert "type" in actor
    
    def test_generate_software_systems(self, c4_generator):
        """Test software systems generation."""
        systems = c4_generator._generate_software_systems()
        
        assert len(systems) > 0
        
        system = systems[0]
        assert "id" in system
        assert "name" in system
        assert "description" in system
        assert "type" in system
        assert "properties" in system
        
        # Should detect Flask framework
        assert "Flask" in system["properties"]["frameworks"]
    
    def test_generate_containers(self, c4_generator):
        """Test containers generation."""
        containers = c4_generator._generate_containers()
        
        # Should have web application container from Flask
        web_containers = [c for c in containers if c["type"] == "Web Application"]
        assert len(web_containers) > 0
        
        # Should have database container from SQLAlchemy
        db_containers = [c for c in containers if c["type"] == "Database"]
        assert len(db_containers) > 0
        
        # Should have test suite from pytest
        test_containers = [c for c in containers if c["type"] == "Test Suite"]
        assert len(test_containers) > 0
    
    def test_generate_components(self, c4_generator):
        """Test components generation."""
        components = c4_generator._generate_components()
        
        assert isinstance(components, list)
        
        for component in components:
            assert "id" in component
            assert "name" in component
            assert "description" in component
            assert "type" in component
            assert "containerId" in component
    
    def test_generate_views(self, c4_generator):
        """Test views generation."""
        views = c4_generator._generate_views()
        
        assert "systemContext" in views
        assert "container" in views
        assert "component" in views
        
        # Should have system context view if people exist
        if c4_generator._generate_people():
            assert len(views["systemContext"]) > 0
        
        # Should have container view if containers exist
        if c4_generator._generate_containers():
            assert len(views["container"]) > 0
    
    def test_generate_llm_extensions(self, c4_generator):
        """Test LLM extensions generation."""
        extensions = c4_generator._generate_llm_extensions()
        
        required_keys = [
            "entity_summaries",
            "interaction_patterns",
            "data_flow",
            "key_algorithms",
            "extension_points",
            "complexity_metrics",
            "business_capabilities",
            "tech_debt_indicators"
        ]
        
        for key in required_keys:
            assert key in extensions
    
    def test_map_file_to_container(self, c4_generator):
        """Test file to container mapping."""
        # Test service file
        container_id = c4_generator._map_file_to_container("/src/services/user_service.py")
        assert container_id in ["web-app", "cli-tool", None]
        
        # Test file - check if test files exist in the generator's repomap
        test_files = [f for f in c4_generator.repomap.get("files", {}).keys() if "test" in f]
        if test_files:
            container_id = c4_generator._map_file_to_container(test_files[0])
            assert container_id == "test-suite"
        
        # Test doc file
        doc_files = [f for f in c4_generator.repomap.get("files", {}).keys() if f.endswith(('.md', '.rst'))]
        if doc_files:
            container_id = c4_generator._map_file_to_container(doc_files[0])
            assert container_id == "documentation"
    
    def test_get_language_from_file(self, c4_generator):
        """Test language detection from file."""
        assert c4_generator._get_language_from_file("test.py") == "Python"
        assert c4_generator._get_language_from_file("test.js") == "JavaScript"
        assert c4_generator._get_language_from_file("test.ts") == "TypeScript"
        assert c4_generator._get_language_from_file("test.java") == "Java"
        assert c4_generator._get_language_from_file("test.unknown") == "Unknown"
    
    def test_infer_entity_purpose(self, c4_generator):
        """Test entity purpose inference."""
        # Test various patterns
        assert "Configuration" in c4_generator._infer_entity_purpose({
            "name": "ConfigManager",
            "type": "class"
        })
        
        assert "Testing" in c4_generator._infer_entity_purpose({
            "name": "test_user",
            "type": "function"
        })
        
        assert "Data modeling" in c4_generator._infer_entity_purpose({
            "name": "UserModel",
            "type": "class"
        })
    
    def test_estimate_complexity(self, c4_generator):
        """Test complexity estimation."""
        # Low complexity
        assert c4_generator._estimate_complexity({
            "start_line": 10,
            "end_line": 15
        }) == "Low"
        
        # Medium complexity
        assert c4_generator._estimate_complexity({
            "start_line": 10,
            "end_line": 35
        }) == "Medium"
        
        # High complexity
        assert c4_generator._estimate_complexity({
            "start_line": 10,
            "end_line": 80
        }) == "High"
    
    @patch('batho_core.context.c4_generator.C4Generator._load_graph')
    @patch('batho_core.context.c4_generator.C4Generator._load_repomap')
    @patch('batho_core.context.c4_generator.C4Generator._load_index_metadata')
    def test_missing_artifacts(self, mock_index, mock_repomap, mock_graph, tmp_path):
        """Test handling of missing artifacts."""
        mock_graph.side_effect = FileNotFoundError("graph.json not found")
        
        ctn_dir = tmp_path / ".ctn"
        index_id = "test_index"
        
        with pytest.raises(FileNotFoundError):
            C4Generator(ctn_dir, index_id)
    
    def test_empty_repository(self, tmp_path):
        """Test handling of empty repository."""
        # Create empty artifacts
        ctn_dir = tmp_path / ".ctn"
        index_id = "empty_index"
        versioned_dir = ctn_dir / index_id
        versioned_dir.mkdir(parents=True)
        
        (versioned_dir / "graph.json").write_text(json.dumps({
            "entities": [],
            "relationships": []
        }))
        (versioned_dir / "repomap.json").write_text(json.dumps({
            "files": {}
        }))
        
        index_data = {
            "current_index_id": index_id,
            "indexes": {
                index_id: {
                    "root": "/empty",
                    "entity_count": 0,
                    "relationship_count": 0,
                    "stack": {"languages": ["Python"], "frameworks": []}
                }
            }
        }
        (ctn_dir / "index.json").write_text(json.dumps(index_data))
        
        generator = C4Generator(ctn_dir, index_id)
        model = generator.generate_c4_model()
        
        # Should still generate a system even with no entities
        assert len(model["model"]["softwareSystems"]) > 0
        assert "empty" in model["name"]
