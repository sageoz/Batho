"""
batho_core/context/categorizer.py — Enterprise-level file categorization.

Classifies repository files into categories for knowledge transfer:
- TESTS: Test files, fixtures, mocks
- DOCS: Documentation, markdown, guides
- CONFIG: Configuration, settings, build files
- SOURCE: Main production codebase
- UNCATEGORIZED: Files that don't fit other categories
"""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path, PurePosixPath
from typing import Set


class FileCategory(Enum):
    """Categories for organizing repository files."""

    TESTS = auto()
    DOCS = auto()
    CONFIG = auto()
    SOURCE = auto()
    UNCATEGORIZED = auto()

    def __str__(self) -> str:
        return self.name.lower()


class FileCategorizer:
    """
    Enterprise-level file categorization using path patterns, extensions, and heuristics.

    Categorization priority (first match wins):
    1. Tests - Test files and test infrastructure
    2. Docs - Documentation and guides
    3. Config - Configuration and build files
    4. Source - Production source code
    5. Uncategorized - Everything else
    """

    # Test patterns
    TEST_PATH_PATTERNS: Set[str] = {
        "tests",
        "test",
        "__tests__",
        "spec",
        "specs",
        ".pytest_cache",
        "fixtures",
        "mocks",
        "testdata",
        "test_data",
        "mock_data",
        "__pycache__",
    }

    TEST_FILE_PREFIXES: Set[str] = {"test_"}
    TEST_FILE_SUFFIXES: Set[str] = {
        "_test.py",
        "_test.js",
        "_test.ts",
        "_test.jsx",
        "_test.tsx",
        ".test.py",
        ".test.js",
        ".test.ts",
        ".test.jsx",
        ".test.tsx",
        ".spec.py",
        ".spec.js",
        ".spec.ts",
        ".spec.jsx",
        ".spec.tsx",
        "_spec.py",
        "_spec.js",
        "_spec.ts",
        "_spec.jsx",
        "_spec.tsx",
        "Test.java",
        "Test.kt",
        "Test.scala",
        "Test.go",
        "Spec.scala",
        "Spec.rb",
        "_test.go",
        "_test.rs",
    }

    # Documentation patterns
    DOC_EXTENSIONS: Set[str] = {".md", ".markdown", ".rst", ".txt", ".adoc", ".org", ".asciidoc"}

    DOC_PATH_PATTERNS: Set[str] = {"docs", "doc", "documentation", "wiki", "guides", "examples"}

    DOC_SPECIAL_FILES: Set[str] = {
        "README",
        "CHANGELOG",
        "CONTRIBUTING",
        "LICENSE",
        "COPYING",
        "CODE_OF_CONDUCT",
        "SECURITY",
        "AUTHORS",
        "CONTRIBUTORS",
        "HISTORY",
        "NEWS",
        "NOTICE",
        "PATENTS",
        "THANKS",
        "TODO",
    }

    # Configuration patterns
    CONFIG_EXTENSIONS: Set[str] = {
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".env",
        ".properties",
        ".conf",
        ".config",
        ".cfg",
    }

    CONFIG_PATH_PATTERNS: Set[str] = {
        "config",
        "configs",
        "configuration",
        ".github",
        ".gitlab",
        "ci",
        "build",
        ".circleci",
        ".travis",
        "jenkins",
    }

    CONFIG_FILE_PATTERNS: Set[str] = {
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "Cargo.toml",
        "Cargo.lock",
        "go.mod",
        "go.sum",
        "build.gradle",
        "pom.xml",
        "composer.json",
        "Gemfile",
        "Gemfile.lock",
        "Makefile",
        "CMakeLists.txt",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".dockerignore",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        ".eslintrc",
        ".prettierrc",
        ".babelrc",
        ".npmrc",
        ".yarnrc",
        "tsconfig.json",
        "jsconfig.json",
        "webpack.config.js",
        "rollup.config.js",
        "vite.config.js",
        "jest.config.js",
        "karma.conf.js",
        "protractor.conf.js",
        "tslint.json",
        ".pylintrc",
        ".flake8",
        "mypy.ini",
        "pytest.ini",
        "tox.ini",
        ".pre-commit-config.yaml",
        "renovate.json",
        "dependabot.yml",
    }

    CONFIG_FILE_SUFFIXES: Set[str] = {
        ".config.js",
        ".config.ts",
        ".config.mjs",
        ".config.cjs",
        ".config.json",
        ".config.yaml",
        ".config.yml",
        "rc.js",
        "rc.json",
        "rc.yaml",
        "rc.yml",
    }

    # Source code extensions
    SOURCE_EXTENSIONS: Set[str] = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".java",
        ".rb",
        ".php",
        ".cs",
        ".kt",
        ".kts",
        ".swift",
        ".scala",
        ".dart",
        ".hs",
        ".jl",
        ".erl",
        ".ml",
        ".lua",
        ".r",
        ".pl",
        ".v",
        ".zig",
        ".sh",
        ".bash",
        ".zsh",
        ".m",
        ".mm",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".hh",
        ".hxx",
        ".ps1",
        ".bat",
        ".clj",
        ".cljs",
        ".ex",
        ".exs",
        ".elm",
        ".fs",
        ".fsx",
        ".vb",
        ".groovy",
        ".nim",
        ".cr",
        ".d",
    }

    SOURCE_PATH_PATTERNS: Set[str] = {
        "src",
        "lib",
        "app",
        "core",
        "api",
        "models",
        "services",
        "utils",
        "helpers",
        "components",
        "controllers",
        "views",
        "routes",
        "middleware",
        "handlers",
        "pkg",
        "internal",
        "domain",
        "infrastructure",
        "application",
        "presentation",
    }

    def __init__(self) -> None:
        """Initialize the categorizer."""
        pass

    def categorize(self, file_path: str) -> FileCategory:
        """
        Categorize a file based on its path and name.

        Args:
            file_path: Relative or absolute file path

        Returns:
            FileCategory enum value
        """
        # Normalize to PurePosixPath for consistent handling
        path = PurePosixPath(file_path)
        filename = path.name.lower()
        stem = path.stem.lower()
        suffix = path.suffix.lower()
        parts = [p.lower() for p in path.parts]

        # Priority 1: Tests
        if self._is_test_file(parts, filename, stem, suffix):
            return FileCategory.TESTS

        # Priority 2: Documentation
        if self._is_doc_file(parts, filename, stem, suffix):
            return FileCategory.DOCS

        # Priority 3: Configuration
        if self._is_config_file(parts, filename, stem, suffix):
            return FileCategory.CONFIG

        # Priority 4: Source code
        if self._is_source_file(parts, filename, suffix):
            return FileCategory.SOURCE

        # Default: Uncategorized
        return FileCategory.UNCATEGORIZED

    def _is_test_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool:
        """Check if file is a test file."""
        # Check path patterns
        for part in parts:
            if part in self.TEST_PATH_PATTERNS:
                return True

        # Check file prefixes
        for prefix in self.TEST_FILE_PREFIXES:
            if filename.startswith(prefix):
                return True

        # Check file suffixes
        for test_suffix in self.TEST_FILE_SUFFIXES:
            if filename.endswith(test_suffix):
                return True

        return False

    def _is_doc_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool:
        """Check if file is a documentation file."""
        # Check path patterns
        for part in parts:
            if part in self.DOC_PATH_PATTERNS:
                return True

        # Check extensions
        if suffix in self.DOC_EXTENSIONS:
            return True

        # Check special file names (case-insensitive, any extension)
        stem_upper = stem.upper()
        for special in self.DOC_SPECIAL_FILES:
            if stem_upper == special or stem_upper.startswith(special + "."):
                return True

        return False

    def _is_config_file(self, parts: list[str], filename: str, stem: str, suffix: str) -> bool:
        """Check if file is a configuration file."""
        # Check path patterns
        for part in parts:
            if part in self.CONFIG_PATH_PATTERNS:
                return True

        # Check exact filename matches
        if filename in self.CONFIG_FILE_PATTERNS:
            return True

        # Check file suffixes
        for config_suffix in self.CONFIG_FILE_SUFFIXES:
            if filename.endswith(config_suffix):
                return True

        # Check extensions (only if not in a source directory)
        has_source_dir = any(part in self.SOURCE_PATH_PATTERNS for part in parts)
        if not has_source_dir and suffix in self.CONFIG_EXTENSIONS:
            return True

        return False

    def _is_source_file(self, parts: list[str], filename: str, suffix: str) -> bool:
        """Check if file is a source code file."""
        # Check if it has a source code extension
        if suffix not in self.SOURCE_EXTENSIONS:
            return False

        # Check if in a source directory (preferred but not required)
        has_source_dir = any(part in self.SOURCE_PATH_PATTERNS for part in parts)

        # If it's a source extension and not already categorized, it's source code
        return True


# Global categorizer instance
_categorizer = FileCategorizer()


def categorize_file(file_path: str) -> FileCategory:
    """
    Categorize a file using the global categorizer instance.

    Args:
        file_path: Relative or absolute file path

    Returns:
        FileCategory enum value
    """
    return _categorizer.categorize(file_path)
