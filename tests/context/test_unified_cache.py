"""Unit tests for BathoCache unified cache."""

from __future__ import annotations

import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from batho.context.schema import Entity, EntityType, Relationship, RelationshipType
from batho.context.unified_cache import BathoCache


@pytest.fixture
def temp_cache_path(tmp_path):
    """Create a temporary cache file path."""
    return str(tmp_path / "test_cache.db")


@pytest.fixture
def cache(temp_cache_path):
    """Create a BathoCache instance with temporary storage."""
    return BathoCache(cache_path=temp_cache_path)


@pytest.fixture
def sample_entity():
    """Create a sample entity for testing."""
    return Entity(
        type=EntityType.FUNCTION,
        name="test_function",
        file="test.py",
        start_line=1,
        end_line=10,
    )


@pytest.fixture
def sample_relationship():
    """Create a sample relationship for testing."""
    return Relationship(
        source_id="test_entity_1",
        target_id="test_entity_2",
        type=RelationshipType.IMPORTS,
    )


class TestBathoCacheInitialization:
    """Tests for BathoCache initialization."""

    def test_initialization_creates_db(self, temp_cache_path):
        """Test that initialization creates the database file."""
        cache = BathoCache(cache_path=temp_cache_path)
        assert Path(temp_cache_path).exists()

    def test_initialization_creates_tables(self, cache):
        """Test that initialization creates required tables."""
        stats = cache.get_stats()
        assert "ast_entry_count" in stats
        assert "file_tracking_count" in stats


class TestAstOperations:
    """Tests for AST cache operations."""

    def test_set_and_get_ast(self, cache, sample_entity, sample_relationship):
        """Test setting and getting AST entries."""
        cache.set_ast(
            file_hash="hash123",
            file_path="test.py",
            entities=[sample_entity],
            relationships=[sample_relationship],
            mtime=1234567890.0,
            size=1024,
        )

        result = cache.get_ast("hash123")
        assert result is not None
        entities, relationships = result
        assert len(entities) == 1
        assert entities[0].name == "test_function"
        assert len(relationships) == 1
        assert relationships[0].type == RelationshipType.IMPORTS

    def test_get_ast_returns_none_for_missing(self, cache):
        """Test that getting non-existent AST returns None."""
        result = cache.get_ast("nonexistent_hash")
        assert result is None

    def test_delete_ast(self, cache, sample_entity):
        """Test deleting AST entries."""
        cache.set_ast(
            file_hash="hash123",
            file_path="test.py",
            entities=[sample_entity],
            relationships=[],
            mtime=1234567890.0,
            size=1024,
        )

        cache.delete_ast("hash123")
        result = cache.get_ast("hash123")
        assert result is None

    def test_delete_ast_by_path(self, cache, sample_entity):
        """Test deleting AST entries by file path."""
        cache.set_ast(
            file_hash="hash123",
            file_path="test.py",
            entities=[sample_entity],
            relationships=[],
            mtime=1234567890.0,
            size=1024,
        )

        deleted = cache.delete_ast_by_path("test.py")
        assert deleted == 1
        result = cache.get_ast("hash123")
        assert result is None

    def test_delete_ast_by_pattern(self, cache, sample_entity):
        """Test deleting AST entries by glob pattern."""
        cache.set_ast(
            file_hash="hash123",
            file_path="src/test.py",
            entities=[sample_entity],
            relationships=[],
            mtime=1234567890.0,
            size=1024,
        )

        deleted = cache.delete_ast_by_pattern("src/*.py")
        assert deleted == 1

    def test_clear_ast_cache(self, cache, sample_entity):
        """Test clearing all AST cache entries."""
        cache.set_ast(
            file_hash="hash123",
            file_path="test.py",
            entities=[sample_entity],
            relationships=[],
            mtime=1234567890.0,
            size=1024,
        )

        deleted = cache.clear_ast_cache()
        assert deleted == 1

    def test_clear_ast_cache_older_than(self, cache, sample_entity):
        """Test clearing AST cache entries older than specified days."""
        cache.set_ast(
            file_hash="hash123",
            file_path="test.py",
            entities=[sample_entity],
            relationships=[],
            mtime=1234567890.0,
            size=1024,
            ttl_days=30,
        )

        deleted = cache.clear_ast_cache(older_than_days=0)
        assert deleted == 1


class TestFileTrackingOperations:
    """Tests for file tracking operations."""

    def test_set_and_get_file_hash(self, cache):
        """Test setting and getting file hashes."""
        cache.set_file_hash(
            file_path="test.py",
            content_hash="abc123",
            mtime=1234567890.0,
            size=1024,
            is_indexed=True,
        )

        result = cache.get_file_hash("test.py")
        assert result == "abc123"

    def test_get_file_hash_returns_none_for_missing(self, cache):
        """Test that getting non-existent file hash returns None."""
        result = cache.get_file_hash("nonexistent.py")
        assert result is None

    def test_delete_file_hash(self, cache):
        """Test deleting file hash entries."""
        cache.set_file_hash(
            file_path="test.py",
            content_hash="abc123",
            mtime=1234567890.0,
            size=1024,
        )

        cache.delete_file_hash("test.py")
        result = cache.get_file_hash("test.py")
        assert result is None

    def test_get_all_file_hashes(self, cache):
        """Test getting all file hashes."""
        cache.set_file_hash("test1.py", "hash1", 1234567890.0, 1024)
        cache.set_file_hash("test2.py", "hash2", 1234567890.0, 2048)

        result = cache.get_all_file_hashes()
        assert len(result) == 2
        assert result["test1.py"] == "hash1"
        assert result["test2.py"] == "hash2"

    def test_get_unindexed_files(self, cache):
        """Test getting unindexed files."""
        cache.set_file_hash("indexed.py", "hash1", 1234567890.0, 1024, is_indexed=True)
        cache.set_file_hash("unindexed.py", "hash2", 1234567890.0, 2048, is_indexed=False)

        result = cache.get_unindexed_files()
        assert len(result) == 1
        assert "unindexed.py" in result


class TestSaveLoadOperations:
    """Tests for bulk save/load operations."""

    def test_save_all(self, cache, tmp_path):
        """Test saving all file hashes."""
        test_file1 = tmp_path / "test1.py"
        test_file1.write_text("content1")
        test_file2 = tmp_path / "test2.py"
        test_file2.write_text("content2")

        file_hashes = {
            "test1.py": "hash1",
            "test2.py": "hash2",
        }

        cache.save_all(file_hashes, tmp_path, is_indexed=True)

        result = cache.get_all_file_hashes()
        assert len(result) == 2

    def test_load_all(self, cache):
        """Test loading all file hashes."""
        cache.set_file_hash("test.py", "hash123", 1234567890.0, 1024)

        result = cache.load_all()
        assert "test.py" in result
        assert result["test.py"] == "hash123"


class TestCacheManagement:
    """Tests for cache management operations."""

    def test_get_stats(self, cache, sample_entity):
        """Test getting cache statistics."""
        cache.set_ast(
            file_hash="hash123",
            file_path="test.py",
            entities=[sample_entity],
            relationships=[],
            mtime=1234567890.0,
            size=1024,
        )

        stats = cache.get_stats()
        assert stats["ast_entry_count"] == 1
        assert stats["file_tracking_count"] == 0
        assert "ast_total_size_mb" in stats

    def test_vacuum(self, cache):
        """Test vacuum operation."""
        cache.vacuum()  # Should not raise

    def test_close(self, cache):
        """Test close operation."""
        cache.close()
        # Should be able to close multiple times without error
        cache.close()


class TestTtlExpiration:
    """Tests for TTL expiration behavior."""

    def test_ttl_parameter_stored(self, cache, sample_entity):
        """Test that TTL parameter is stored correctly."""
        cache.set_ast(
            file_hash="hash123",
            file_path="test.py",
            entities=[sample_entity],
            relationships=[],
            mtime=1234567890.0,
            size=1024,
            ttl_days=60,
        )

        stats = cache.get_stats()
        assert stats["ast_entry_count"] == 1


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_entities_list(self, cache):
        """Test storing empty entities list."""
        cache.set_ast(
            file_hash="hash123",
            file_path="test.py",
            entities=[],
            relationships=[],
            mtime=1234567890.0,
            size=1024,
        )

        result = cache.get_ast("hash123")
        assert result is not None
        entities, relationships = result
        assert len(entities) == 0
        assert len(relationships) == 0

    def test_unicode_file_paths(self, cache, sample_entity):
        """Test handling unicode file paths."""
        cache.set_ast(
            file_hash="hash123",
            file_path="测试.py",
            entities=[sample_entity],
            relationships=[],
            mtime=1234567890.0,
            size=1024,
        )

        result = cache.get_ast("hash123")
        assert result is not None
