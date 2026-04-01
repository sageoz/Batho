"""
Tests for Java Adapter.
"""

import pytest
from batho_core.context.lsp.adapters.java import JavaAdapter

def test_get_file_patterns():
    adapter = JavaAdapter()
    assert "*.java" in adapter.get_file_patterns()

def test_initialize_options_maven_detection(tmp_path):
    pom = tmp_path / "pom.xml"
    pom.write_text("<project></project>")
    
    adapter = JavaAdapter()
    config = adapter.parse_project_config(str(tmp_path))
    assert "pom.xml" in config.files

def test_parse_project_config_gradle_fallback(tmp_path):
    gradle = tmp_path / "build.gradle"
    gradle.write_text("plugins {}")
    
    adapter = JavaAdapter()
    config = adapter.parse_project_config(str(tmp_path))
    assert "build.gradle" in config.files

def test_extract_type_info_signature():
    adapter = JavaAdapter()
    hover = "```java\npublic void doSomething()\n```\nDoc"
    res = adapter.extract_type_info(hover)
    assert res == "public void doSomething()"
