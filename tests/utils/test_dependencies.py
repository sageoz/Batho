"""Tests for batho_core.utils.dependencies module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho_core.utils.dependencies import (
    extract_all_dependencies,
    extract_dependency_names,
    extract_package_name,
    parse_cargo_toml,
    parse_package_json,
    parse_pyproject_toml,
    parse_requirements_txt,
    parse_setup_py,
)


# ---------------------------------------------------------------------------
# extract_package_name
# ---------------------------------------------------------------------------

class TestExtractPackageName:

    def test_simple_name(self):
        assert extract_package_name("requests") == "requests"

    def test_with_version(self):
        assert extract_package_name("requests>=2.28.0") == "requests"

    def test_with_extras(self):
        assert extract_package_name("requests[security]>=2.0") == "requests"

    def test_tilde_version(self):
        assert extract_package_name("flask~=2.0") == "flask"

    def test_caret_version(self):
        assert extract_package_name("pydantic^2.0") == "pydantic"

    def test_exact_version(self):
        assert extract_package_name("click==8.0.0") == "click"

    def test_multiple_specifiers(self):
        assert extract_package_name("django>=3.0,<4.0") == "django"


# ---------------------------------------------------------------------------
# parse_requirements_txt
# ---------------------------------------------------------------------------

class TestParseRequirementsTxt:

    def test_basic(self):
        content = "requests>=2.0\nflask\nclick==8.0"
        result = parse_requirements_txt(content)
        assert "requests" in result
        assert "flask" in result
        assert "click" in result

    def test_skips_comments(self):
        content = "# comment\nrequests\n"
        result = parse_requirements_txt(content)
        assert result == ["requests"]

    def test_skips_options(self):
        content = "-r other.txt\n--index-url https://...\nrequests\n"
        result = parse_requirements_txt(content)
        assert result == ["requests"]

    def test_skips_empty_lines(self):
        content = "\n\nrequests\n\n"
        result = parse_requirements_txt(content)
        assert result == ["requests"]

    def test_empty_content(self):
        assert parse_requirements_txt("") == []


# ---------------------------------------------------------------------------
# parse_pyproject_toml
# ---------------------------------------------------------------------------

class TestParsePyprojectToml:

    def test_pep621_dependencies(self):
        content = """
[project]
dependencies = ["requests>=2.0", "click"]

[build-system]
build-backend = "hatchling.build"
"""
        result = parse_pyproject_toml(content)
        assert "requests" in result["dependencies"]
        assert "click" in result["dependencies"]
        assert result["build_tool"] == "hatch"

    def test_optional_dependencies(self):
        content = """
[project]
dependencies = []

[project.optional-dependencies]
test = ["pytest>=8.0", "pytest-cov"]
"""
        result = parse_pyproject_toml(content)
        assert "pytest" in result["optional_dependencies"].get("test", [])

    def test_poetry_dependencies(self):
        content = """
[tool.poetry.dependencies]
python = "^3.12"
fastapi = "^0.100"

[build-system]
build-backend = "poetry.core.masonry.api"
"""
        result = parse_pyproject_toml(content)
        assert "fastapi" in result["dependencies"]
        assert result["build_tool"] == "poetry"


# ---------------------------------------------------------------------------
# parse_setup_py
# ---------------------------------------------------------------------------

class TestParseSetupPy:

    def test_install_requires(self):
        content = """
from setuptools import setup
setup(
    name="test",
    install_requires=["requests>=2.0", "flask"],
    python_requires=">=3.10",
)
"""
        result = parse_setup_py(content)
        assert "requests" in result["dependencies"]
        assert "flask" in result["dependencies"]
        assert result["python_requires"] == ">=3.10"

    def test_no_deps(self):
        content = "from setuptools import setup\nsetup(name='x')\n"
        result = parse_setup_py(content)
        assert result["dependencies"] == []


# ---------------------------------------------------------------------------
# parse_package_json
# ---------------------------------------------------------------------------

class TestParsePackageJson:

    def test_all_dep_types(self):
        content = json.dumps({
            "dependencies": {"react": "^18.0"},
            "devDependencies": {"typescript": "^5.0"},
            "peerDependencies": {"react-dom": "^18.0"},
        })
        result = parse_package_json(content)
        assert "react" in result["dependencies"]
        assert "typescript" in result["dev_dependencies"]
        assert "react-dom" in result["peer_dependencies"]

    def test_detects_package_manager(self):
        content = json.dumps({"packageManager": "pnpm@8.0.0"})
        result = parse_package_json(content)
        assert result["package_manager"] == "pnpm"

    def test_invalid_json(self):
        result = parse_package_json("not json {{{")
        assert result["dependencies"] == {}


# ---------------------------------------------------------------------------
# parse_cargo_toml
# ---------------------------------------------------------------------------

class TestParseCargoToml:

    def test_dependencies(self):
        content = """
[dependencies]
serde = "1.0"
tokio = { version = "1.0", features = ["full"] }

[dev-dependencies]
criterion = "0.5"
"""
        result = parse_cargo_toml(content)
        assert "serde" in result["dependencies"]
        assert "tokio" in result["dependencies"]
        assert "criterion" in result["dev_dependencies"]


# ---------------------------------------------------------------------------
# extract_all_dependencies / extract_dependency_names
# ---------------------------------------------------------------------------

class TestUnifiedExtraction:

    def test_extract_from_python_repo(self, simple_python_repo: Path):
        result = extract_all_dependencies(simple_python_repo)
        assert isinstance(result, dict)
        assert "python" in result
        # requirements.txt has requests, click, pydantic
        assert "requests" in result["python"]

    def test_extract_names_flat(self, simple_python_repo: Path):
        names = extract_dependency_names(simple_python_repo)
        assert isinstance(names, list)
        assert "requests" in names

    def test_empty_dir(self, tmp_path: Path):
        result = extract_all_dependencies(tmp_path)
        assert result["python"] == []
        assert result["nodejs"] == []
        assert result["rust"] == []

    def test_extract_with_complex_requirements(self, tmp_path: Path):
        """Test extraction with complex requirement specifications."""
        requirements = """
# Regular dependencies
requests>=2.28.0
flask~=2.0
click==8.0.0

# Git dependencies
git+https://github.com/user/repo.git@v1.0#egg=mypackage

# Local dependencies
./local-package
-e ./editable-package

# URL dependencies
https://files.pythonhosted.org/packages/source/p/package/package.tar.gz

# Environment markers
pywin32>=223; sys_platform == "win32"
        """
        (tmp_path / "requirements.txt").write_text(requirements)
        result = extract_all_dependencies(tmp_path)
        assert "requests" in result["python"]
        assert "flask" in result["python"]
        assert "click" in result["python"]

    def test_extract_with_multiple_dependency_files(self, tmp_path: Path):
        """Test extraction with multiple dependency files."""
        # Create requirements.txt
        (tmp_path / "requirements.txt").write_text("requests\nflask")
        
        # Create pyproject.toml
        pyproject = """
[project]
dependencies = ["django>=4.0", "celery"]
        """
        (tmp_path / "pyproject.toml").write_text(pyproject)
        
        # Create package.json
        package_json = json.dumps({
            "dependencies": {"react": "^18.0"},
            "devDependencies": {"typescript": "^5.0"}
        })
        (tmp_path / "package.json").write_text(package_json)
        
        result = extract_all_dependencies(tmp_path)
        assert "requests" in result["python"]
        assert "flask" in result["python"]
        assert "django" in result["python"]
        assert "celery" in result["python"]
        assert "react" in result["nodejs"]
        assert "typescript" in result["nodejs"]

    def test_extract_with_invalid_files(self, tmp_path: Path):
        """Test extraction with invalid or malformed files."""
        # Invalid JSON
        (tmp_path / "package.json").write_text("invalid json {{{")
        
        # Invalid TOML
        (tmp_path / "pyproject.toml").write_text("invalid toml [[[")
        
        # Invalid setup.py (syntax error)
        (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup(name='test', install_requires=[\n")
        
        # Should not crash and return empty lists
        result = extract_all_dependencies(tmp_path)
        assert isinstance(result, dict)
        assert "python" in result
        assert "nodejs" in result
        assert "rust" in result

    def test_extract_with_cargo_toml(self, tmp_path: Path):
        """Test extraction from Cargo.toml."""
        cargo_toml = """
[package]
name = "test-rust-app"
version = "0.1.0"

[dependencies]
serde = "1.0"
tokio = { version = "1.0", features = ["full"] }
anyhow = "1.0"

[dev-dependencies]
criterion = "0.5"

[target.'cfg(unix)'.dependencies]
libc = "0.2"
        """
        (tmp_path / "Cargo.toml").write_text(cargo_toml)
        
        result = extract_all_dependencies(tmp_path)
        assert "serde" in result["rust"]
        assert "tokio" in result["rust"]
        assert "anyhow" in result["rust"]
        assert "criterion" in result["rust"]

    def test_extract_with_go_mod(self, tmp_path: Path):
        """Test extraction with go.mod - not supported yet."""
        # This test documents that Go extraction is not yet supported
        go_mod = """
module test-go-app

go 1.21

require (
    github.com/gin-gonic/gin v1.9.0
)
        """
        (tmp_path / "go.mod").write_text(go_mod)
        
        result = extract_all_dependencies(tmp_path)
        # Go is not yet supported, so it should not be in the result
        assert "go" not in result

    def test_extract_with_composer_json(self, tmp_path: Path):
        """Test extraction with composer.json - not supported yet."""
        # This test documents that PHP extraction is not yet supported
        composer_json = json.dumps({
            "require": {
                "php": ">=8.0",
                "symfony/console": "^6.0"
            }
        })
        (tmp_path / "composer.json").write_text(composer_json)
        
        result = extract_all_dependencies(tmp_path)
        # PHP is not yet supported, so it should not be in the result
        assert "php" not in result

    def test_extract_with_gemfile(self, tmp_path: Path):
        """Test extraction with Gemfile - not supported yet."""
        # This test documents that Ruby extraction is not yet supported
        gemfile = """
source "https://rubygems.org"
gem "rails", "~> 7.0"
        """
        (tmp_path / "Gemfile").write_text(gemfile)
        
        result = extract_all_dependencies(tmp_path)
        # Ruby is not yet supported, so it should not be in the result
        assert "ruby" not in result

    def test_extract_with_pom_xml(self, tmp_path: Path):
        """Test extraction with pom.xml - not supported yet."""
        # This test documents that Java extraction is not yet supported
        pom_xml = """
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <groupId>com.example</groupId>
    <artifactId>test-app</artifactId>
    <version>1.0.0</version>
</project>
        """
        (tmp_path / "pom.xml").write_text(pom_xml)
        
        result = extract_all_dependencies(tmp_path)
        # Java is not yet supported, so it should not be in the result
        assert "java" not in result
