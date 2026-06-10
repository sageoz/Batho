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
        """Verify REQUIREMENT_PATTERN parses simple requirement definitions.

        Scenario:
            A pip package requirement with a minimum version is parsed.

        Execution Flow:
            1. Apply REQUIREMENT_PATTERN regex to 'requests>=2.31.0'.
            2. Assert that the pattern matches and capture groups extract the package name and version specifier.

        Expectations:
            - The match is not None.
            - Capture group 1 is 'requests'.
            - Capture group 2 is '>=2.31.0'.
        """
        match = REQUIREMENT_PATTERN.match("requests>=2.31.0")
        assert match is not None
        assert match.group(1) == "requests"
        assert match.group(2) == ">=2.31.0"

    def test_requirement_pattern_with_extras(self):
        """Verify REQUIREMENT_PATTERN parses package requirements with extra options.

        Scenario:
            A pip package requirement specifying extra dependencies is parsed.

        Execution Flow:
            1. Apply REQUIREMENT_PATTERN regex to 'requests[security]>=2.31.0'.
            2. Assert that group 1 extracts the name with extras.

        Expectations:
            - The match is not None.
            - Capture group 1 is 'requests[security]'.
        """
        match = REQUIREMENT_PATTERN.match("requests[security]>=2.31.0")
        assert match is not None
        assert match.group(1) == "requests[security]"

    def test_requirement_pattern_only_name(self):
        """Verify REQUIREMENT_PATTERN parses requirements without version specifiers.

        Scenario:
            A requirements entry contains only a package name.

        Execution Flow:
            1. Apply REQUIREMENT_PATTERN to 'requests'.
            2. Assert that the package name is extracted and version specifier is empty.

        Expectations:
            - The match is not None.
            - Capture group 1 is 'requests'.
            - Capture group 2 is ''.
        """
        match = REQUIREMENT_PATTERN.match("requests")
        assert match is not None
        assert match.group(1) == "requests"
        assert match.group(2) == ""

    def test_toml_name_pattern(self):
        """Verify TOML_NAME_PATTERN extracts project name from TOML.

        Scenario:
            A project name declaration string in TOML format is searched.

        Execution Flow:
            1. Search 'name = "my-package"' using TOML_NAME_PATTERN.
            2. Assert that the package name is successfully matched.

        Expectations:
            - The match is not None.
            - Capture group 1 is 'my-package'.
        """
        match = TOML_NAME_PATTERN.search('name = "my-package"')
        assert match is not None
        assert match.group(1) == "my-package"

    def test_toml_version_pattern(self):
        """Verify TOML_VERSION_PATTERN extracts project version from TOML.

        Scenario:
            A project version declaration string in TOML format is searched.

        Execution Flow:
            1. Search 'version = "1.0.0"' using TOML_VERSION_PATTERN.
            2. Assert that the version is successfully matched.

        Expectations:
            - The match is not None.
            - Capture group 1 is '1.0.0'.
        """
        match = TOML_VERSION_PATTERN.search('version = "1.0.0"')
        assert match is not None
        assert match.group(1) == "1.0.0"


class TestDependencySpec:
    """Tests for DependencySpec dataclass."""

    def test_creation(self):
        """Verify correct initialization of DependencySpec properties.

        Scenario:
            A DependencySpec object is instantiated with valid fields.

        Execution Flow:
            1. Construct a DependencySpec instance.
            2. Assert that properties match the provided argument values.

        Expectations:
            - The instantiated fields represent the correct dependency specification data.
        """
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
        """Verify equality and hash behavior of the frozen DependencySpec dataclass.

        Scenario:
            Two distinct DependencySpec instances with identical properties are compared.

        Execution Flow:
            1. Instantiate two duplicate DependencySpec objects.
            2. Assert that they are equal and produce the same hash.

        Expectations:
            - The equality check evaluates to True.
            - The hash values of both objects match.
        """
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
        """Verify manifest parser behavior on an empty requirements.txt file.

        Scenario:
            An empty requirements.txt file is processed by ManifestParser.

        Execution Flow:
            1. Create an empty requirements.txt file.
            2. Parse the file using _parse_requirements_txt().
            3. Assert that the returned list of specs is empty.

        Expectations:
            - Returns an empty list of dependencies.
        """
        parser = ManifestParser()
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("")
        deps = parser._parse_requirements_txt(req_file)
        assert deps == []

    def test_parse_simple_requirements(self, temp_dir):
        """Verify requirements.txt parsing with simple dependencies.

        Scenario:
            A requirements.txt containing two python package declarations is parsed.

        Execution Flow:
            1. Write a requirements.txt with two packages and version rules.
            2. Invoke _parse_requirements_txt().
            3. Assert that both dependencies are parsed with accurate details.

        Expectations:
            - Parser returns exactly two DependencySpec objects.
            - First package name is "requests" with ">=2.31.0".
            - Second package name is "numpy".
        """
        parser = ManifestParser()
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("requests>=2.31.0\nnumpy==1.24.0\n")
        deps = parser._parse_requirements_txt(req_file)
        assert len(deps) == 2
        assert deps[0].name == "requests"
        assert deps[0].version_spec == ">=2.31.0"
        assert deps[1].name == "numpy"

    def test_parse_requirements_with_comments(self, temp_dir):
        """Verify requirements.txt parsing ignores lines starting with comments.

        Scenario:
            A requirements.txt contains inline or block comments alongside valid packages.

        Execution Flow:
            1. Write requirements.txt with comment lines and a 'requests' dependency.
            2. Parse the file.
            3. Verify comment lines are ignored and only valid package specs are returned.

        Expectations:
            - Returns a single dependency spec for "requests".
        """
        parser = ManifestParser()
        req_file = temp_dir / "requirements.txt"
        req_file.write_text("# This is a comment\nrequests>=2.31.0\n")
        deps = parser._parse_requirements_txt(req_file)
        assert len(deps) == 1
        assert deps[0].name == "requests"

    def test_parse_requirements_with_options(self, temp_dir):
        """Verify requirements.txt parsing filters out pip command options.

        Scenario:
            A requirements.txt contains command line flags (like -e).

        Execution Flow:
            1. Write requirements.txt with '-e .' option and 'requests' dependency.
            2. Parse requirements file.
            3. Assert that options are ignored.

        Expectations:
            - Only "requests" is returned.
        """
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
        """Verify package.json parsing for npm dependencies.

        Scenario:
            A package.json file with production and development dependencies is parsed.

        Execution Flow:
            1. Write a package.json file with dependencies and devDependencies.
            2. Call _parse_package_json().
            3. Verify production and development packages are extracted.

        Expectations:
            - Parser returns three specs.
            - express, lodash, and jest names are present in the returned list.
        """
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
        """Verify parsing behavior on an invalid package.json format.

        Scenario:
            An invalid json string is supplied in the package.json path.

        Execution Flow:
            1. Write invalid json string into package.json.
            2. Call _parse_package_json().
            3. Verify empty list is returned instead of raising JSONDecodeError.

        Expectations:
            - Returns an empty list of specifications.
        """
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
        """Verify detection of project name and version from package.json.

        Scenario:
            A package.json containing name and version properties is in the root directory.

        Execution Flow:
            1. Write a package.json with name and version keys.
            2. Execute detect_project_metadata().
            3. Verify the metadata manager, name, and version fields.

        Expectations:
            - The returned PackageMetadata is not None.
            - Name matches "my-project".
            - Version matches "2.0.0".
            - Manager is PackageManager.NPM.
        """
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
        """Verify metadata detection returns None when no manifests exist.

        Scenario:
            The target project directory is completely empty.

        Execution Flow:
            1. Execute detect_project_metadata() on the directory.
            2. Assert that the result is None.

        Expectations:
            - Returns None indicating no project metadata could be discovered.
        """
        result = ManifestParser.detect_project_metadata(temp_dir)
        assert result is None

    def test_detect_npm_missing_name(self, temp_dir):
        """Verify project metadata detection fails if the name key is missing in package.json.

        Scenario:
            A package.json exists but lacks the name property.

        Execution Flow:
            1. Write a package.json with only version.
            2. Execute detect_project_metadata().
            3. Assert that the result is None.

        Expectations:
            - Returns None because name is a required field.
        """
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
        """Verify that parse_manifests parses both pip and npm dependencies.

        Scenario:
            A project contains both a requirements.txt and a package.json.

        Execution Flow:
            1. Write requirements.txt with "requests".
            2. Write package.json with "express".
            3. Call parse_manifests() on the directory.
            4. Assert that dependencies from both managers are resolved.

        Expectations:
            - Two dependencies are parsed: "requests" and "express".
        """
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
        """Verify parse_manifests behavior when no manifest files are present.

        Scenario:
            The parsed directory has no requirements.txt or package.json.

        Execution Flow:
            1. Instantiate ManifestParser.
            2. Call parse_manifests() on the empty directory.
            3. Assert that the result is an empty list.

        Expectations:
            - Returns an empty list of package specifications.
        """
        parser = ManifestParser()
        deps = parser.parse_manifests(temp_dir)
        assert deps == []
