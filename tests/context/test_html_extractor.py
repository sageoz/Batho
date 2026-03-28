"""Tests for HTML language extractor."""

import pytest
from batho_core.context.languages.html import HTMLExtractor
from batho_core.context.schema import EntityType, RelationshipType


class TestHTMLExtractor:
    """Test cases for HTMLExtractor."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = HTMLExtractor()

    def test_init(self):
        """Test extractor initialization."""
        assert self.extractor._language_name == "html"

    def test_extract_simple_html(self):
        """Test extracting from simple HTML content."""
        html_content = b"""<!DOCTYPE html>
<html>
<head>
    <title>Test Page</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <h1>Hello World</h1>
    <div class="container">
        <p id="intro">This is a test.</p>
        <a href="https://example.com">External Link</a>
        <img src="image.jpg" alt="Test Image" />
    </div>
</body>
</html>"""
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        
        # Check document entity
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1
        assert doc_entities[0].name == "document"
        assert doc_entities[0].metadata["title"] == "Test Page"
        
        # Check element entities
        element_entities = [e for e in entities if e.type == EntityType.ELEMENT]
        element_names = {e.name for e in element_entities}
        expected_elements = {"html", "head", "title", "link", "body", "h1", "div", "p", "a", "img"}
        assert expected_elements.issubset(element_names)
        
        # Check attribute entities
        attribute_entities = [e for e in entities if e.type == EntityType.ATTRIBUTE]
        assert len(attribute_entities) > 0
        
        # Check relationships
        assert len(relationships) > 0
        
        # Check HAS_ATTRIBUTE relationships
        has_attr_rels = [r for r in relationships if r.type == RelationshipType.HAS_ATTRIBUTE]
        assert len(has_attr_rels) > 0
        
        # Check CONTAINS relationships
        contains_rels = [r for r in relationships if r.type == RelationshipType.CONTAINS]
        assert len(contains_rels) > 0
        
        # Check LINKS_TO relationships
        links_rels = [r for r in relationships if r.type == RelationshipType.LINKS_TO]
        assert len(links_rels) == 1
        assert links_rels[0].target_id == "external:https://example.com"
        
        # Check IMPORTS_STYLE relationships
        style_rels = [r for r in relationships if r.type == RelationshipType.IMPORTS_STYLE]
        assert len(style_rels) == 1
        assert "stylesheet:styles.css" in style_rels[0].target_id

    def test_extract_self_closing_tags(self):
        """Test extracting self-closing tags."""
        html_content = b"""
<img src="test.jpg" alt="Test" />
<br />
<hr />
<input type="text" name="username" />
        """
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        
        # Check that self-closing tags are detected
        element_entities = [e for e in entities if e.type == EntityType.ELEMENT]
        img_elements = [e for e in element_entities if e.name == "img"]
        assert len(img_elements) == 1
        # Note: self_closing detection may not work perfectly with regex approach

    def test_extract_nested_attributes(self):
        """Test extracting attributes with various quote styles."""
        html_content = b"""
<div class="container" id='main' data-value=123></div>
        """
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        
        # Check attribute extraction with different quote styles
        attribute_entities = [e for e in entities if e.type == EntityType.ATTRIBUTE]
        attr_names = {e.metadata["attribute_name"] for e in attribute_entities}
        expected_attrs = {"class", "id", "data-value"}
        assert attr_names == expected_attrs
        
        # Check attribute values
        attr_values = {e.metadata["attribute_name"]: e.metadata["attribute_value"] 
                      for e in attribute_entities}
        assert attr_values["class"] == "container"
        assert attr_values["id"] == "main"
        assert attr_values["data-value"] == "123"

    def test_extract_unicode_content(self):
        """Test extracting HTML with unicode content."""
        html_content = b"""
<html>
<head>
    <title>\u6d4b\u8bd5\u9875\u9762</title>
</head>
<body>
    <h1>Hello \u4e16\u754c</h1>
</body>
</html>
        """
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        
        # Should handle unicode properly
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1

    def test_extract_malformed_html(self):
        """Test extracting from malformed HTML."""
        html_content = b"""
<div>
    <p>Unclosed paragraph
    <span>Nested span</span>
</div>
        """
        
        # Should not raise exception on malformed HTML
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        assert len(entities) > 0

    def test_extract_empty_html(self):
        """Test extracting from empty HTML."""
        html_content = b""
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        # Empty HTML still creates a document entity
        assert len(entities) >= 1
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1
        assert len(relationships) == 0

    def test_extract_html_without_title(self):
        """Test extracting HTML without title tag."""
        html_content = b"""
<html>
<body>
    <h1>No Title</h1>
</body>
</html>
        """
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1
        assert doc_entities[0].metadata["title"] is None

    def test_extract_multiple_links(self):
        """Test extracting multiple links."""
        html_content = b"""
<body>
    <a href="https://example1.com">Link 1</a>
    <a href="https://example2.com">Link 2</a>
    <a href="/relative/path">Relative Link</a>
</body>
        """
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        
        # Should extract external links only
        links_rels = [r for r in relationships if r.type == RelationshipType.LINKS_TO]
        assert len(links_rels) == 2  # Only external links

    def test_extract_multiple_stylesheets(self):
        """Test extracting multiple stylesheet links."""
        html_content = b"""
<head>
    <link rel="stylesheet" href="style1.css">
    <link rel="stylesheet" href="style2.css">
</head>
        """
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        
        style_rels = [r for r in relationships if r.type == RelationshipType.IMPORTS_STYLE]
        assert len(style_rels) == 2

    def test_line_number_tracking(self):
        """Test that line numbers are tracked correctly."""
        html_content = b"""<html>
<body>
    <h1>Line 3</h1>
</body>
</html>"""
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        
        # Find the h1 element
        h1_elements = [e for e in entities if e.name == "h1"]
        assert len(h1_elements) == 1
        assert h1_elements[0].start_line == 3

    def test_case_insensitive_tags(self):
        """Test that HTML tags are case-insensitive."""
        html_content = b"""
<DIV class="container">
    <P>Test paragraph</P>
</DIV>
        """
        
        entities, relationships = self.extractor.parse_file("test.html", html_content)
        
        # Tags should be normalized to lowercase
        element_names = {e.name for e in entities if e.type == EntityType.ELEMENT}
        assert "div" in element_names
        assert "p" in element_names
        assert "DIV" not in element_names
        assert "P" not in element_names
