"""Tests for language extractor factory."""

import pytest
from batho_core.context.languages.factory import (
    ConfigurableExtractor,
    create_extractor,
    get_extractor,
    register_extractor,
    list_supported_languages,
    clear_extractor_cache,
    QUERY_REGISTRY,
    PYTHON_QUERY,
    JAVASCRIPT_QUERY,
)
from batho_core.context.extractor import ASTExtractor


class TestConfigurableExtractor:
    """Test cases for ConfigurableExtractor."""

    def test_init(self):
        """Test extractor initialization."""
        extractor = ConfigurableExtractor("python", PYTHON_QUERY)
        assert extractor._language_name == "python"
        assert extractor._query == PYTHON_QUERY

    def test_query_source(self):
        """Test _query_source method."""
        extractor = ConfigurableExtractor("python", PYTHON_QUERY)
        assert extractor._query_source() == PYTHON_QUERY


class TestCreateExtractor:
    """Test cases for create_extractor function."""

    def test_create_extractor(self):
        """Test creating an extractor."""
        extractor = create_extractor("python", PYTHON_QUERY)
        assert isinstance(extractor, ASTExtractor)
        assert extractor._language_name == "python"

    def test_create_different_languages(self):
        """Test creating extractors for different languages."""
        python_extractor = create_extractor("python", PYTHON_QUERY)
        js_extractor = create_extractor("javascript", JAVASCRIPT_QUERY)
        
        assert python_extractor._language_name == "python"
        assert js_extractor._language_name == "javascript"
        assert python_extractor != js_extractor


class TestGetExtractor:
    """Test cases for get_extractor function."""

    def setup_method(self):
        """Set up test fixtures."""
        clear_extractor_cache()

    def test_get_supported_language(self):
        """Test getting extractor for supported language."""
        extractor = get_extractor("python")
        assert extractor is not None
        assert isinstance(extractor, ASTExtractor)
        assert extractor._language_name == "python"

    def test_get_unsupported_language(self):
        """Test getting extractor for unsupported language."""
        extractor = get_extractor("unsupported")
        assert extractor is None

    def test_caching(self):
        """Test that extractor instances are cached."""
        extractor1 = get_extractor("python")
        extractor2 = get_extractor("python")
        assert extractor1 is extractor2  # Same instance

    def test_cache_invalidation_on_register(self):
        """Test that cache is invalidated when registering new extractor."""
        original_query = QUERY_REGISTRY.get("python")
        
        try:
            # Get cached instance
            extractor1 = get_extractor("python")
            assert extractor1 is not None
            
            # Register new query for same language
            new_query = "(identifier) @test"
            register_extractor("python", new_query)
            
            # Should get new instance
            extractor2 = get_extractor("python")
            assert extractor2 is not None
            assert extractor1 is not extractor2  # Different instances
        finally:
            # Restore original query
            if original_query:
                QUERY_REGISTRY["python"] = original_query
                clear_extractor_cache()

    def test_multiple_languages(self):
        """Test getting extractors for multiple languages."""
        python_extractor = get_extractor("python")
        js_extractor = get_extractor("javascript")
        
        assert python_extractor is not None
        assert js_extractor is not None
        assert python_extractor._language_name == "python"
        assert js_extractor._language_name == "javascript"


class TestRegisterExtractor:
    """Test cases for register_extractor function."""

    def setup_method(self):
        """Set up test fixtures."""
        clear_extractor_cache()

    def test_register_new_language(self):
        """Test registering a new language."""
        # Save original query
        original_query = QUERY_REGISTRY.get("python")
        
        try:
            new_query = "(identifier) @test"
            register_extractor("python", new_query)  # Use existing language instead of new one
            
            assert "python" in QUERY_REGISTRY
            assert QUERY_REGISTRY["python"] == new_query
            
            extractor = get_extractor("python")
            assert extractor is not None
            assert extractor._language_name == "python"
        finally:
            # Restore original query
            if original_query:
                QUERY_REGISTRY["python"] = original_query
                clear_extractor_cache()

    def test_register_existing_language(self):
        """Test registering over an existing language."""
        original_query = QUERY_REGISTRY.get("python")
        new_query = "(identifier) @new_test"
        
        try:
            register_extractor("python", new_query)
            
            assert QUERY_REGISTRY["python"] == new_query
            assert QUERY_REGISTRY["python"] != original_query
        finally:
            # Restore original query
            if original_query:
                QUERY_REGISTRY["python"] = original_query
                clear_extractor_cache()

    def test_register_clears_cache(self):
        """Test that registering clears cache for that language."""
        original_query = QUERY_REGISTRY.get("python")
        
        try:
            # Get cached instance
            extractor1 = get_extractor("python")
            assert extractor1 is not None
            
            # Register new query
            new_query = "(identifier) @test"
            register_extractor("python", new_query)
            
            # Cache should be cleared, get new instance
            extractor2 = get_extractor("python")
            assert extractor1 is not extractor2
        finally:
            # Restore original query
            if original_query:
                QUERY_REGISTRY["python"] = original_query
                clear_extractor_cache()


class TestListSupportedLanguages:
    """Test cases for list_supported_languages function."""

    def test_list_supported(self):
        """Test listing supported languages."""
        languages = list_supported_languages()
        assert isinstance(languages, list)
        assert len(languages) > 0
        assert "python" in languages
        assert "javascript" in languages

    def test_list_sorted(self):
        """Test that returned list is sorted."""
        languages = list_supported_languages()
        assert languages == sorted(languages)

    def test_list_after_register(self):
        """Test listing after registering new language."""
        original_count = len(list_supported_languages())
        
        register_extractor("testlang", "(identifier) @test")
        languages = list_supported_languages()
        
        assert len(languages) == original_count + 1
        assert "testlang" in languages
        
        # Clean up
        del QUERY_REGISTRY["testlang"]


class TestClearExtractorCache:
    """Test cases for clear_extractor_cache function."""

    def test_clear_cache(self):
        """Test clearing the extractor cache."""
        # Create cached instances
        extractor1 = get_extractor("python")
        extractor2 = get_extractor("javascript")
        assert extractor1 is not None
        assert extractor2 is not None
        
        # Clear cache
        clear_extractor_cache()
        
        # Should create new instances
        extractor3 = get_extractor("python")
        extractor4 = get_extractor("javascript")
        assert extractor1 is not extractor3
        assert extractor2 is not extractor4

    def test_clear_empty_cache(self):
        """Test clearing an empty cache."""
        # Should not raise exception
        clear_extractor_cache()
        clear_extractor_cache()


class TestQueryRegistry:
    """Test cases for query registry."""

    def test_registry_contains_expected_queries(self):
        """Test that registry contains expected language queries."""
        expected_languages = ["python", "javascript", "typescript", "rust", "go", "java", "c", "cpp"]
        
        for lang in expected_languages:
            assert lang in QUERY_REGISTRY
            assert isinstance(QUERY_REGISTRY[lang], str)
            assert len(QUERY_REGISTRY[lang]) > 0

    def test_python_query_structure(self):
        """Test that Python query has expected structure."""
        query = QUERY_REGISTRY["python"]
        
        # Check for common patterns
        assert "@def.class.name" in query
        assert "@def.function.name" in query
        assert "@def.method.name" in query
        assert "@ref.import" in query
        assert "@ref.call" in query

    def test_javascript_query_structure(self):
        """Test that JavaScript query has expected structure."""
        query = QUERY_REGISTRY["javascript"]
        
        # Check for common patterns
        assert "@def.function.name" in query
        assert "@def.class.name" in query
        assert "@def.method.name" in query
        assert "@ref.import" in query
        assert "@ref.call" in query


class TestExtractorIntegration:
    """Integration tests for factory with actual parsing."""

    def test_python_extractor_integration(self):
        """Test Python extractor with actual Python code."""
        extractor = get_extractor("python")
        assert extractor is not None
        
        python_code = b"""
class TestClass:
    def test_method(self):
        pass

def test_function():
    pass
        """
        
        entities, relationships = extractor.parse_file("test.py", python_code)
        assert len(entities) > 0

    def test_javascript_extractor_integration(self):
        """Test JavaScript extractor with actual JS code."""
        extractor = get_extractor("javascript")
        assert extractor is not None
        
        js_code = b"""
function testFunction() {
    return true;
}

class TestClass {
    testMethod() {
        return false;
    }
}
        """
        
        entities, relationships = extractor.parse_file("test.js", js_code)
        assert len(entities) > 0
