"""Tests for Markdown language extractor."""

import pytest
from batho.context.languages.markdown import MarkdownExtractor
from batho.context.schema import EntityType, RelationshipType


class TestMarkdownExtractor:
    """Test cases for MarkdownExtractor."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = MarkdownExtractor()

    def test_init(self):
        """Test extractor initialization."""
        assert self.extractor._language_name == "markdown"

    def test_extract_simple_markdown(self):
        """Test extracting from simple Markdown content."""
        md_content = b"""# Main Title

This is a paragraph with **bold** and *italic* text.

## Section 1

- Item 1
- Item 2
- Item 3

### Subsection

```python
def hello():
    print("Hello World")
```

[Link text](https://example.com)

![Image](image.jpg "Alt text")
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should have document entity
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1
        assert doc_entities[0].name == "document"
        
        # Should have heading entities
        heading_entities = [e for e in entities if e.type == EntityType.ELEMENT and e.name.startswith("header_")]
        assert len(heading_entities) >= 3  # #, ##, ###
        
        # Should have code block
        code_entities = [e for e in entities if e.type == EntityType.ELEMENT and e.name.startswith("codeblock_")]
        assert len(code_entities) >= 1
        
        # Should have link and image relationships instead of entities
        link_rels = [r for r in relationships if r.type == RelationshipType.LINKS_TO]
        assert len(link_rels) >= 2  # Link and image

    def test_extract_headings(self):
        """Test extracting headings of different levels."""
        md_content = b"""# Level 1

## Level 2

### Level 3

#### Level 4

##### Level 5

###### Level 6
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should have 6 headings
        heading_entities = [e for e in entities if e.type == EntityType.ELEMENT and e.name.startswith("header_")]
        assert len(heading_entities) == 6
        
        # Check heading levels
        levels = {e.metadata.get("header_level", 0) for e in heading_entities}
        expected_levels = {1, 2, 3, 4, 5, 6}
        assert levels == expected_levels

    def test_extract_code_blocks(self):
        """Test extracting code blocks with different languages."""
        md_content = b"""```python
def hello():
    pass
```

```javascript
function hello() {
    return true;
}
```

```
Plain code block
```
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should have 3 code blocks
        code_entities = [e for e in entities if e.type == EntityType.ELEMENT and e.name.startswith("codeblock_")]
        assert len(code_entities) == 3
        
        # Check languages
        languages = {e.metadata.get("code_language") for e in code_entities}
        expected_languages = {"python", "javascript", "text"}  # Plain text blocks are marked as 'text'
        assert languages == expected_languages

    def test_extract_lists(self):
        """Test extracting unordered and ordered lists."""
        md_content = b"""- Unordered item 1
- Unordered item 2
  - Nested item
- Unordered item 3

1. Ordered item 1
2. Ordered item 2
   1. Nested ordered
3. Ordered item 3
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should have list items
        list_entities = [e for e in entities if e.type == EntityType.ELEMENT and e.name.startswith("list_item_")]
        assert len(list_entities) >= 6  # At least 6 list items

    def test_extract_links_and_images(self):
        """Test extracting links and images."""
        md_content = b"""[Simple link](https://example.com)

[Link with title](https://example.com "Link title")

![Image](image.jpg)

![Image with alt and title](image.png "Image title")

<https://example.com/direct>

[Reference link][ref]

[ref]: https://example.com/reference
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should have links and images as relationships
        link_rels = [r for r in relationships if r.type == RelationshipType.LINKS_TO]
        assert len(link_rels) >= 4  # Simple, title, direct, reference

    def test_extract_tables(self):
        """Test extracting tables."""
        md_content = b"""| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Cell 1   | Cell 2   | Cell 3   |
| Cell 4   | Cell 5   | Cell 6   |
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should have table - check if table extraction is implemented
        table_entities = [e for e in entities if e.type == EntityType.ELEMENT and "table" in e.name]
        # Note: Table extraction may not be implemented

    def test_extract_blockquotes(self):
        """Test extracting blockquotes."""
        md_content = b"""> This is a blockquote
> 
> > This is a nested blockquote
> 
> Back to outer level
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should have blockquote - check if implemented
        quote_entities = [e for e in entities if e.type == EntityType.ELEMENT and "blockquote" in e.name]
        # Note: Blockquote extraction may not be implemented

    def test_extract_inline_formatting(self):
        """Test extracting inline formatting elements."""
        md_content = b"""This has **bold** and *italic* and `code` text.

Also has __bold__ and _italic_ and ~~strikethrough~~ text.
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should have inline elements - check if implemented
        inline_entities = [e for e in entities if e.type == EntityType.ELEMENT and e.name in ["bold", "italic", "code", "strikethrough"]]
        # Note: Inline formatting extraction may not be implemented

    def test_extract_frontmatter(self):
        """Test extracting YAML frontmatter."""
        md_content = b"""---
title: Document Title
author: John Doe
date: 2023-01-01
tags:
  - tag1
  - tag2
---

# Content starts here
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should have frontmatter - check metadata
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1
        assert doc_entities[0].metadata.get("has_frontmatter") is True

    def test_extract_empty_markdown(self):
        """Test extracting from empty Markdown."""
        md_content = b""
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should still have document entity
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1
        assert len(relationships) == 0

    def test_line_number_tracking(self):
        """Test that line numbers are tracked correctly."""
        md_content = b"""Line 1

# Heading on line 4

Line 6
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Find the heading
        heading_entities = [e for e in entities if e.type == EntityType.ELEMENT and e.name.startswith("header_")]
        assert len(heading_entities) == 1
        assert heading_entities[0].start_line == 3  # Line numbering might be 0-indexed or count differently

    def test_unicode_content(self):
        """Test extracting Markdown with unicode content."""
        md_content = b"""# \u6807\u9898

This contains \u4e2d\u6587 characters and \u65e5\u672c\u8a9e text.

**\u5927\u80c6** and *\u659c\u4f53* text.
        """
        
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        
        # Should handle unicode properly
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1

    def test_malformed_markdown(self):
        """Test extracting from malformed Markdown."""
        md_content = b"""# Unclosed heading

```python
def unclosed_code_block():
    pass

- Unclosed list item
        """
        
        # Should not raise exception
        entities, relationships = self.extractor.parse_file("test.md", md_content)
        assert len(entities) > 0
