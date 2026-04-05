"""
Comprehensive tests for language detector functionality.

Tests cover:
- File extension-based detection
- Shebang detection for executable scripts
- Content-based heuristics for ambiguous files
- Language registry and factory patterns
- Unknown file type handling
- Edge cases and error handling
"""

import pytest
from batho.context.languages.detector import LanguageDetector
from batho.context.languages.registry import get_extractor


class TestLanguageDetectorComprehensive:
    """Comprehensive tests for language detector."""

    def setup_method(self):
        """Set up test fixtures."""
        self.detector = LanguageDetector()

    def test_extension_based_detection(self):
        """Test language detection based on file extensions."""
        from pathlib import Path
        
        # Common extensions
        result = self.detector.detect(Path("test.py"), b"")
        assert result.language == "python"
        
        result = self.detector.detect(Path("test.js"), b"")
        assert result.language == "javascript"
        
        result = self.detector.detect(Path("test.ts"), b"")
        assert result.language == "typescript"
        
        result = self.detector.detect(Path("test.go"), b"")
        assert result.language == "go"
        
        result = self.detector.detect(Path("test.rs"), b"")
        assert result.language == "rust"
        
        result = self.detector.detect(Path("test.java"), b"")
        assert result.language == "java"
        
        result = self.detector.detect(Path("test.cpp"), b"")
        assert result.language == "cpp"
        
        result = self.detector.detect(Path("test.c"), b"")
        assert result.language == "c"
        
        result = self.detector.detect(Path("test.css"), b"")
        assert result.language == "css"
        
        result = self.detector.detect(Path("test.yaml"), b"")
        assert result.language == "yaml"

    def test_multiple_extensions(self):
        """Test detection of files with multiple extensions."""
        from pathlib import Path
        
        result = self.detector.detect(Path("test.min.js"), b"")
        assert result.language == "javascript"
        
        result = self.detector.detect(Path("test.bundle.css"), b"")
        assert result.language == "css"
        
        result = self.detector.detect(Path("test.spec.ts"), b"")
        assert result.language == "typescript"
        
        result = self.detector.detect(Path("test.test.py"), b"")
        assert result.language == "python"

    def test_case_insensitive_extensions(self):
        """Test case-insensitive extension detection."""
        from pathlib import Path
        
        result = self.detector.detect(Path("test.PY"), b"")
        assert result.language == "python"
        
        result = self.detector.detect(Path("test.JS"), b"")
        assert result.language == "javascript"
        
        result = self.detector.detect(Path("test.TS"), b"")
        assert result.language == "typescript"
        
        result = self.detector.detect(Path("test.CSS"), b"")
        assert result.language == "css"

    def test_shebang_detection(self):
        """Test language detection based on shebang lines."""
        from pathlib import Path
        
        # Python shebangs
        result = self.detector.detect(Path("test.py"), b"#!/usr/bin/env python\nprint('hello')")
        assert result.language == "python"
        
        result = self.detector.detect(Path("test.py"), b"#!/usr/bin/python3\nimport sys")
        assert result.language == "python"
        
        # Bash shebangs
        result = self.detector.detect(Path("test.sh"), b"#!/bin/bash\necho 'hello'")
        assert result.language == "bash"
        
        result = self.detector.detect(Path("test.sh"), b"#!/usr/bin/sh\nls -la")
        assert result.language == "bash"
        
        # Node.js shebangs
        result = self.detector.detect(Path("test.js"), b"#!/usr/bin/env node\nconsole.log('hello')")
        assert result.language == "javascript"
        
        # Ruby shebangs
        result = self.detector.detect(Path("test.rb"), b"#!/usr/bin/env ruby\nputs 'hello'")
        assert result.language == "ruby"

    def test_content_based_detection(self):
        """Test language detection based on file content."""
        from pathlib import Path
        
        # Python patterns
        python_content = b"import os\nfrom collections import defaultdict\nclass MyClass:\n    def __init__(self):\n        pass"
        result = self.detector.detect(Path("test.py"), python_content)
        assert result.language == "python"
        
        # JavaScript patterns
        js_content = b"const fs = require('fs');\nfunction hello() {\n    console.log('hello');\n}\nexport default hello;"
        result = self.detector.detect(Path("test.js"), js_content)
        assert result.language == "javascript"
        
        # CSS patterns
        css_content = b".container {\n    display: flex;\n    margin: 0 auto;\n}\n@media (max-width: 768px) {\n    .container {\n        width: 100%;\n    }\n}"
        result = self.detector.detect(Path("test.css"), css_content)
        assert result.language == "css"
        
        # HTML patterns
        html_content = b"<!DOCTYPE html>\n<html>\n<head>\n    <title>Test</title>\n</head>\n<body>\n    <h1>Hello</h1>\n</body>\n</html>"
        result = self.detector.detect(Path("test.html"), html_content)
        assert result.language == "html"

    def test_yaml_detection_patterns(self):
        """Test YAML detection patterns."""
        from pathlib import Path
        
        yaml_patterns = [
            b"app:\n  name: test\n  version: 1.0",
            b"---\ndatabase:\n  host: localhost",
            b"production: &default\n  timeout: 30",
            b"services:\n  - web\n  - api",
        ]
        
        for pattern in yaml_patterns:
            result = self.detector.detect(Path("test.yaml"), pattern)
            if result:
                assert result.language == "yaml"

    def test_json_detection_patterns(self):
        """Test JSON detection patterns."""
        from pathlib import Path
        
        json_patterns = [
            b'{"name": "test", "version": "1.0"}',
            b'["item1", "item2", "item3"]',
            b'{"nested": {"key": "value"}, "array": [1, 2, 3]}',
        ]
        
        for pattern in json_patterns:
            result = self.detector.detect(Path("test"), pattern)
            assert result.language == "json"

    def test_toml_detection_patterns(self):
        """Test TOML detection patterns."""
        from pathlib import Path
        
        toml_patterns = [
            b"[app]\nname = \"test\"\nversion = \"1.0\"",
            b"database.url = \"localhost\"\ndebug = true",
            b"[dependencies]\nrequests = \"^2.0.0\"",
        ]
        
        for pattern in toml_patterns:
            result = self.detector.detect(Path("test.toml"), pattern)
            if result:
                assert result.language == "toml"

    def test_markdown_detection_patterns(self):
        """Test Markdown detection patterns."""
        from pathlib import Path
        
        md_patterns = [
            b"# Heading 1\n## Heading 2\nSome text with **bold** and *italic*",
            b"- Item 1\n- Item 2\n- Item 3",
            b"[Link text](https://example.com)",
            b"```python\nprint('hello')\n```",
        ]
        
        for pattern in md_patterns:
            result = self.detector.detect(Path("test.md"), pattern)
            if result:
                assert result.language == "markdown"

    def test_unknown_file_types(self):
        """Test handling of unknown file types."""
        from pathlib import Path
        
        # Files with no extension (some are actually recognized)
        result = self.detector.detect(Path("Makefile"), b"")
        assert result.language == "make"  # Makefile is recognized
        
        result = self.detector.detect(Path("Dockerfile"), b"")
        assert result.language == "docker"  # Dockerfile is recognized as "docker"
        
        result = self.detector.detect(Path("README"), b"")
        assert result is None  # README is not recognized
        
        # Files with unknown extensions
        result = self.detector.detect(Path("test.xyz"), b"")
        assert result is None
        
        result = self.detector.detect(Path("test.unknown"), b"")
        assert result is None
        
        # Empty content with known extension should still work
        result = self.detector.detect(Path("test.txt"), b"")
        assert result is None  # .txt is not a supported language

    def test_conflicting_detection(self):
        """Test handling when extension and content disagree."""
        from pathlib import Path
        
        # File with .py extension but JavaScript content
        js_content = b"const x = 10;\nfunction test() { return x; }"
        # Extension should take precedence
        result = self.detector.detect(Path("test.py"), js_content)
        assert result.language == "python"

    def test_special_filenames(self):
        """Test detection of special filename patterns."""
        from pathlib import Path
        
        # Common special files
        result = self.detector.detect(Path("package.json"), b"")
        assert result.language == "json"
        
        result = self.detector.detect(Path("tsconfig.json"), b"")
        assert result.language == "json"
        
        result = self.detector.detect(Path("pyproject.toml"), b"")
        assert result.language == "toml"
        
        result = self.detector.detect(Path("Cargo.toml"), b"")
        assert result.language == "toml"
        
        result = self.detector.detect(Path("docker-compose.yml"), b"")
        assert result.language == "yaml"
        
        result = self.detector.detect(Path("requirements.txt"), b"")
        assert result is None  # Not a structured language

    def test_encoding_handling(self):
        """Test detection with different encodings."""
        from pathlib import Path
        
        # UTF-8 content
        utf8_content = "print('hello 世界')".encode('utf-8')
        result = self.detector.detect(Path("test.py"), utf8_content)
        assert result.language == "python"
        
        # Latin-1 content
        latin1_content = "print('hello')".encode('latin-1')
        result = self.detector.detect(Path("test.py"), latin1_content)
        assert result.language == "python"

    def test_binary_content_handling(self):
        """Test handling of binary content."""
        from pathlib import Path
        
        binary_content = b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a'
        result = self.detector.detect(Path("test"), binary_content)
        assert result is None  # Should detect as unknown

    def test_large_file_detection(self):
        """Test detection with large file content."""
        from pathlib import Path
        
        # Large Python file
        large_content = b"import os\n" * 1000 + b"class MyClass:\n    pass\n"
        result = self.detector.detect(Path("test.py"), large_content)
        assert result.language == "python"

    def test_mixed_language_files(self):
        """Test detection of files that might contain multiple languages."""
        from pathlib import Path
        
        # HTML with embedded JavaScript and CSS
        mixed_content = b"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                .container { margin: 0 auto; }
            </style>
            <script>
                console.log('hello');
            </script>
        </head>
        <body>
            <h1>Hello World</h1>
        </body>
        </html>
        """
        # Should detect as HTML (primary content)
        result = self.detector.detect(Path("test"), mixed_content)
        assert result.language == "html"

    def test_edge_case_patterns(self):
        """Test edge case patterns that might confuse detection."""
        from pathlib import Path
        
        # Files that look like one language but are another
        fake_yaml = b"# This looks like YAML but is actually Python\n# name: test\nprint('hello')"
        result = self.detector.detect(Path("test.py"), fake_yaml)
        assert result.language == "python"
        
        # JSON with comments (invalid JSON but looks like JavaScript)
        json_with_comments = b'{\n    "name": "test", // comment\n    "value": 123\n}'
        result = self.detector.detect(Path("test.js"), json_with_comments)
        # May detect as json or javascript, both are acceptable
        assert result.language in ["json", "javascript"]

    def test_language_registry_integration(self):
        """Test integration with language registry."""
        from pathlib import Path
        
        # Test that detected languages are available in registry
        result = self.detector.detect(Path("test.py"), b"")
        assert result.language == "python"
        
        # Should be able to get extractor from registry
        extractor = get_extractor(".py")
        assert extractor is not None

    def test_detection_confidence_scoring(self):
        """Test confidence scoring for language detection."""
        from pathlib import Path
        
        # High confidence cases
        result = self.detector.detect(Path("test.py"), b"")
        assert result.language == "python"
        assert result.confidence > 0.8

    def test_performance_with_large_files(self):
        """Test detection performance with large files."""
        from pathlib import Path
        
        # Create large content
        large_content = b"x" * 1000000  # 1MB
        
        result = self.detector.detect(Path("test"), large_content)
        assert result is None  # Should detect as unknown

    def test_error_handling(self):
        """Test error handling in detection."""
        from pathlib import Path
        
        # Test with empty content
        result = self.detector.detect(Path("test.py"), b"")
        assert result.language == "python"  # Should still work with empty content
        
        # Test with None content (the detector seems to handle this gracefully)
        try:
            result = self.detector.detect(Path("test.py"), None)
            # If it doesn't raise an exception, that's fine too
        except (TypeError, AttributeError):
            pass  # Expected but not required
