"""Tests for the manifest parser module."""
import json
import tempfile
from pathlib import Path

import pytest

from batho.modules.dependency.manifest_parser import (
    ManifestParser,
    DependencySpec,
    REQUIREMENT_PATTERN,
    TOML_NAME_PATTERN,
    TOML_VERSION_PATTERN,
)
from batho.core.schemas import PackageManager, PackageMetadata


class TestCompiledRegexPatterns:
    """Tests for pre-compiled regex patterns."""

    def test_requirement_pattern_simple(self):
        match = REQUIREMENT_PATTERN.match("requests>=2.31.0")
        assert match is not None
        assert match.group(1) == "requests"
        assert match.group(2) == ">=2.31.0"

    def test_requirement_pattern_with_extras(self):
        match = REQUIREMENT_PATTERN.match("requests[security]>=2.31.0")
        assert match is not None
        assert match.group(1) == "requests[security]"

    def test_requirement_pattern_only_name(self):
        match = REQUIREMENT_PATTERN.match("requests")
        assert match is not None
        assert match.group(1) == "requests"
        assert match.group(2) == ""

    def test_toml_name_pattern(self):
        match = TOML_NAME_PATTERN.search('name = "my-package"')
        assert match is not None
        assert match.group(1) == "my-package"

    def test_toml_version_pattern(self):
        match = TOML_VERSION_PATTERN.search('version = "1.0.0"')
        assert match is not None
        assert match.group(1) == "1.0.0"


class TestDependencySpec:
    """Tests for DependencySpec dataclass."""

    def test_creation(self):
        spec = DependencySpec(
            name="requests",
            version_spec=">=2.31.0",
            manager=PackageManager.PIP,
            language="python",
            source_file="requirements.txt"
        )
        assert spec.name == "requests"
        assert spec.version_spec == ">=2.31.0"
        assert spec.manager == PackageManager.PIP
        assert spec.language == "python"
        assert spec.source_file == "requirements.txt"

    def test_frozen_equality(self):
        spec1 = DependencySpec("requests", ">=2.0", PackageManager.PIP, "python", "req.txt")
        spec2 = DependencySpec("requests", ">=2.0", PackageManager.PIP, "python", "req.txt")
        assert spec1 == spec2
        assert hash(spec1) == hash(spec2)


class TestManifestParserRequirementsTxt:
    """Tests for requirements.txt parsing."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_parse_empty_requirements(self, temp_dir):
        parser = ManifestParser()
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("")
        deps = parser._parse_requirements_txt(req_file)
        assert deps == []

    def test_parse_simple_requirements(self, temp_dir):
        parser = ManifestParser()
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("requests>=2.31.0\nnumpy==1.24.0\n")
        deps = parser._parse_requirements_txt(req_file)
        assert len(deps) == 2
        assert deps[0].name == "requests"
        assert deps[0].version_spec == ">=2.31.0"
        assert deps[1].name == "numpy"

    def test_parse_requirements_with_comments(self, temp_dir):
        parser = ManifestParser()
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("# This is a comment\nrequests>=2.31.0\n")
        deps = parser._parse_requirements_txt(req_file)
        assert len(deps) == 1
        assert deps[0].name == "requests"

    def test_parse_requirements_with_options(self, temp_dir):
        parser = ManifestParser()
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("-e .\nrequests>=2.31.0\n")
        deps = parser._parse_requirements_txt(req_file)
        assert len(deps) == 1
        assert deps[0].name == "requests"


class TestManifestParserPackageJson:
    """Tests for package.json parsing."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_parse_package_json(self, temp_dir):
        parser = ManifestParser()
        pkg_file = temp_dir / "package.json"
        pkg_file.write_text(json.dumps({
            "name": "test-project",
            "version": "1.0.0",
            "dependencies": {
                "express": "^4.18.0",
                "lodash": "^4.17.0"
            },
            "devDependencies": {
                "jest": "^29.0.0"
            }
        }))
        deps = parser._parse_package_json(pkg_file)
        assert len(deps) == 3
        
        dep_names = {d.name for d in deps}
        assert "express" in dep_names
        assert "lodash" in dep_names
        assert "jest" in dep_names

    def test_parse_invalid_json(self, temp_dir):
        parser = ManifestParser()
        pkg_file = temp_dir / "package.json"
        pkg_file.write_text("not valid json")
        deps = parser._parse_package_json(pkg_file)
        assert deps == []


class TestManifestParserDetectProjectMetadata:
    """Tests for project metadata detection."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_detect_npm_metadata(self, temp_dir):
        pkg_file = temp_dir / "package.json"
        pkg_file.write_text(json.dumps({
            "name": "my-project",
            "version": "2.0.0"
        }))
        
        result = ManifestParser.detect_project_metadata(temp_dir)
        assert result is not None
        assert result.name == "my-project"
        assert result.version == "2.0.0"
        assert result.manager == PackageManager.NPM

    def test_detect_no_metadata(self, temp_dir):
        result = ManifestParser.detect_project_metadata(temp_dir)
        assert result is None

    def test_detect_npm_missing_name(self, temp_dir):
        pkg_file = temp_dir / "package.json"
        pkg_file.write_text(json.dumps({"version": "1.0.0"}))
        
        result = ManifestParser.detect_project_metadata(temp_dir)
        assert result is None


class TestManifestParserParseManifests:
    """Tests for the main parse_manifests method."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_parse_multiple_manifests(self, temp_dir):
        # Create requirements.txt
        (temp_dir / "requirements.txt").write_text("requests>=2.0\n")
        
        # Create package.json
        (temp_dir / "package.json").write_text(json.dumps({
            "name": "test",
            "dependencies": {"express": "^4.0"}
        }))
        
        parser = ManifestParser()
        deps = parser.parse_manifests(temp_dir)
        
        # Should have 2 deps: requests from requirements.txt and express from package.json
        assert len(deps) == 2
        
        dep_names = {d.name for d in deps}
        assert "requests" in dep_names
        assert "express" in dep_names

    def test_parse_no_manifests(self, temp_dir):
        parser = ManifestParser()
        deps = parser.parse_manifests(temp_dir)
        assert deps == []
