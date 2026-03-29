"""
backend/utils/dependencies.py — Consolidated dependency extraction utilities.

This module provides unified dependency parsing logic for various manifest files,
eliminating duplication between memory/universal.py and context/stack_detector.py.

Supported manifest formats:
- Python: requirements.txt, pyproject.toml, setup.py
- Node.js: package.json
- Rust: Cargo.toml
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from batho_core.utils.logging import get_logger

logger = get_logger(__name__, component="dependencies")

# Optional tomli import for Python < 3.11 (fallback for tomllib)
tomli: Any = None
try:
    import tomli as _tomli

    tomli = _tomli
except ImportError:
    pass  # tomli is optional - will use tomllib on Python 3.11+

# ---------------------------------------------------------------------------
# Package name extraction utilities
# ---------------------------------------------------------------------------


def extract_package_name(dep_spec: str) -> str:
    """
    Extract the package name from a dependency specification.

    Handles various version specifiers and extras:
    - "package>=1.0" -> "package"
    - "package[extra]==1.0" -> "package"
    - "package~=1.0,<2.0" -> "package"

    Args:
        dep_spec: Dependency specification string (e.g., "requests>=2.0")

    Returns:
        Clean package name
    """
    # Remove extras first (e.g., "package[extra]")
    name = dep_spec.split("[")[0]
    # Remove version specifiers
    for separator in ["<", ">", "=", "!", "~", "^"]:
        name = name.split(separator)[0]
    return name.strip()


# ---------------------------------------------------------------------------
# Requirements.txt parsing
# ---------------------------------------------------------------------------


def parse_requirements_txt(content: str) -> list[str]:
    """
    Parse requirements.txt content and return list of dependency names.

    Args:
        content: Raw content of requirements.txt

    Returns:
        List of package names (version specifiers removed)
    """
    dependencies: list[str] = []

    for line in content.splitlines():
        line = line.strip()
        # Skip empty lines, comments, and options
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        dep = extract_package_name(line)
        if dep:
            dependencies.append(dep)

    return dependencies


def parse_requirements_txt_file(path: Path) -> list[str]:
    """
    Parse a requirements.txt file.

    Args:
        path: Path to requirements.txt

    Returns:
        List of package names, empty list if file cannot be read
    """
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return parse_requirements_txt(content)
    except Exception as exc:
        logger.debug("Failed to parse requirements.txt", path=str(path), error=str(exc))
        return []


# ---------------------------------------------------------------------------
# pyproject.toml parsing
# ---------------------------------------------------------------------------


def parse_pyproject_toml(content: str) -> dict[str, Any]:
    """
    Parse pyproject.toml content and extract dependencies.

    Args:
        content: Raw content of pyproject.toml

    Returns:
        Dictionary with:
        - 'dependencies': list of main dependency names
        - 'optional_dependencies': dict mapping group name to list of deps
        - 'dev_dependencies': list of dev dependency names
        - 'build_tool': detected build tool (poetry, setuptools, etc.)
    """
    result: dict[str, Any] = {
        "dependencies": [],
        "optional_dependencies": {},
        "dev_dependencies": [],
        "build_tool": None,
    }

    try:
        import tomllib

        data = tomllib.loads(content)
    except Exception:
        # Fallback: try tomli if available
        if tomli is not None:
            try:
                data = tomli.loads(content)
            except Exception:
                # Last resort: simple regex extraction
                return _parse_pyproject_toml_regex(content)
        else:
            # Last resort: simple regex extraction
            return _parse_pyproject_toml_regex(content)

    # Detect build tool
    result["build_tool"] = _detect_build_tool_from_pyproject(data)

    # Parse [project] dependencies (PEP 621)
    project = data.get("project", {})
    for dep in project.get("dependencies", []):
        dep_name = extract_package_name(dep)
        if dep_name:
            result["dependencies"].append(dep_name)

    # Parse optional dependencies (extras)
    optional_deps = project.get("optional-dependencies", {})
    for group, deps in optional_deps.items():
        group_deps: list[str] = []
        for dep in deps:
            dep_name = extract_package_name(dep)
            if dep_name:
                group_deps.append(dep_name)
        if group_deps:
            result["optional_dependencies"][group] = group_deps

    # Parse Poetry dependencies
    tool = data.get("tool", {})
    poetry = tool.get("poetry", {})

    poetry_deps = poetry.get("dependencies", {})
    for dep_name in poetry_deps.keys():
        if dep_name.lower() != "python":
            result["dependencies"].append(dep_name)

    # Poetry dev dependencies (legacy key)
    poetry_dev_deps = poetry.get("dev-dependencies", {})
    for dep_name in poetry_dev_deps.keys():
        result["dev_dependencies"].append(dep_name)

    # Poetry group dependencies
    group_deps = poetry.get("group", {})
    for group_name, group_data in group_deps.items():
        packages = group_data.get("dependencies", {})
        for dep_name in packages.keys():
            result["dev_dependencies"].append(dep_name)

    return result


def _detect_build_tool_from_pyproject(data: dict[str, Any]) -> str | None:
    """Detect build tool from parsed pyproject.toml data."""
    build_backend = data.get("build-system", {}).get("build-backend", "")

    if "poetry" in build_backend:
        return "poetry"
    elif "flit" in build_backend:
        return "flit"
    elif "hatchling" in build_backend or "hatch" in build_backend:
        return "hatch"
    elif "setuptools" in build_backend:
        return "setuptools"
    elif "pdm" in build_backend:
        return "pdm"
    elif "maturin" in build_backend:
        return "maturin"

    # Check for tool-specific sections
    tool = data.get("tool", {})
    if "poetry" in tool:
        return "poetry"
    elif "pdm" in tool:
        return "pdm"
    elif "hatch" in tool:
        return "hatch"

    return None


def _parse_pyproject_toml_regex(content: str) -> dict[str, Any]:
    """Fallback regex-based parsing for pyproject.toml."""
    result: dict[str, Any] = {
        "dependencies": [],
        "optional_dependencies": {},
        "dev_dependencies": [],
        "build_tool": None,
    }

    # Simple regex to find dependency names
    matches = re.findall(r"^([a-zA-Z0-9_-]+)\s*=", content, re.MULTILINE)
    for match in matches:
        if match not in ("name", "version", "description", "authors", "package"):
            result["dependencies"].append(match)

    return result


def parse_pyproject_toml_file(path: Path) -> dict[str, Any]:
    """
    Parse a pyproject.toml file.

    Args:
        path: Path to pyproject.toml

    Returns:
        Parsed dependency info, empty structure if file cannot be read
    """
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return parse_pyproject_toml(content)
    except Exception as exc:
        logger.debug("Failed to parse pyproject.toml", path=str(path), error=str(exc))
        return {
            "dependencies": [],
            "optional_dependencies": {},
            "dev_dependencies": [],
            "build_tool": None,
        }


# ---------------------------------------------------------------------------
# setup.py parsing
# ---------------------------------------------------------------------------


def parse_setup_py(content: str) -> dict[str, Any]:
    """
    Parse setup.py content and extract dependencies.

    Args:
        content: Raw content of setup.py

    Returns:
        Dictionary with:
        - 'dependencies': list of install_requires entries
        - 'python_requires': Python version requirement string
    """
    result: dict[str, Any] = {
        "dependencies": [],
        "python_requires": None,
    }

    # Look for install_requires
    install_requires_match = re.search(r"install_requires\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if install_requires_match:
        deps_str = install_requires_match.group(1)
        for match in re.finditer(r'["\']([^"\']+)["\']', deps_str):
            dep = match.group(1)
            dep_name = extract_package_name(dep)
            if dep_name:
                result["dependencies"].append(dep_name)

    # Look for python_requires
    python_requires_match = re.search(r"python_requires\s*=\s*['\"]([^'\"]+)['\"]", content)
    if python_requires_match:
        result["python_requires"] = python_requires_match.group(1)

    return result


def parse_setup_py_file(path: Path) -> dict[str, Any]:
    """
    Parse a setup.py file.

    Args:
        path: Path to setup.py

    Returns:
        Parsed dependency info, empty structure if file cannot be read
    """
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return parse_setup_py(content)
    except Exception as exc:
        logger.debug("Failed to parse setup.py", path=str(path), error=str(exc))
        return {"dependencies": [], "python_requires": None}


# ---------------------------------------------------------------------------
# package.json parsing
# ---------------------------------------------------------------------------


def parse_package_json(content: str) -> dict[str, Any]:
    """
    Parse package.json content and extract dependencies.

    Args:
        content: Raw content of package.json

    Returns:
        Dictionary with:
        - 'dependencies': dict mapping package name to version
        - 'dev_dependencies': dict mapping package name to version
        - 'peer_dependencies': dict mapping package name to version
        - 'package_manager': detected package manager
        - 'engines': dict of engine requirements
    """
    result: dict[str, Any] = {
        "dependencies": {},
        "dev_dependencies": {},
        "peer_dependencies": {},
        "package_manager": None,
        "engines": {},
    }

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return result

    result["dependencies"] = data.get("dependencies", {})
    result["dev_dependencies"] = data.get("devDependencies", {})
    result["peer_dependencies"] = data.get("peerDependencies", {})
    result["engines"] = data.get("engines", {})

    # Detect package manager from packageManager field
    pkg_manager_field = data.get("packageManager", "")
    if pkg_manager_field:
        if "pnpm" in pkg_manager_field:
            result["package_manager"] = "pnpm"
        elif "yarn" in pkg_manager_field:
            result["package_manager"] = "yarn"
        elif "npm" in pkg_manager_field:
            result["package_manager"] = "npm"

    return result


def parse_package_json_file(path: Path) -> dict[str, Any]:
    """
    Parse a package.json file and detect package manager from lock files.

    Args:
        path: Path to package.json

    Returns:
        Parsed dependency info with detected package manager
    """
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        result = parse_package_json(content)
    except Exception as exc:
        logger.debug("Failed to parse package.json", path=str(path), error=str(exc))
        result = {
            "dependencies": {},
            "dev_dependencies": {},
            "peer_dependencies": {},
            "package_manager": None,
            "engines": {},
        }

    # Detect package manager from lock files if not already set
    if not result["package_manager"]:
        result["package_manager"] = _detect_node_package_manager(path.parent)

    return result


def _detect_node_package_manager(root_path: Path) -> str | None:
    """Detect Node.js package manager from lock files."""
    if (root_path / "pnpm-lock.yaml").exists():
        return "pnpm"
    elif (root_path / "yarn.lock").exists():
        return "yarn"
    elif (root_path / "package-lock.json").exists():
        return "npm"
    elif (root_path / "bun.lockb").exists():
        return "bun"
    return None


# ---------------------------------------------------------------------------
# Cargo.toml parsing
# ---------------------------------------------------------------------------


def parse_cargo_toml(content: str) -> dict[str, Any]:
    """
    Parse Cargo.toml content and extract dependencies.

    Args:
        content: Raw content of Cargo.toml

    Returns:
        Dictionary with:
        - 'dependencies': list of dependency names
        - 'dev_dependencies': list of dev dependency names
        - 'build_dependencies': list of build dependency names
    """
    result: dict[str, Any] = {
        "dependencies": [],
        "dev_dependencies": [],
        "build_dependencies": [],
    }

    try:
        import tomllib

        data = tomllib.loads(content)
    except Exception:
        if tomli is not None:
            try:
                data = tomli.loads(content)
            except Exception:
                # Fallback regex parsing
                matches = re.findall(r"^([a-zA-Z0-9_-]+)\s*=", content, re.MULTILINE)
                for match in matches:
                    if match not in ("package", "workspace", "profile"):
                        result["dependencies"].append(match)
                return result
        else:
            # Fallback regex parsing
            matches = re.findall(r"^([a-zA-Z0-9_-]+)\s*=", content, re.MULTILINE)
            for match in matches:
                if match not in ("package", "workspace", "profile"):
                    result["dependencies"].append(match)
            return result

    # Extract dependencies
    deps = data.get("dependencies", {})
    for dep_name in deps.keys():
        result["dependencies"].append(dep_name)

    # Extract dev-dependencies
    dev_deps = data.get("dev-dependencies", {})
    for dep_name in dev_deps.keys():
        result["dev_dependencies"].append(dep_name)

    # Extract build-dependencies
    build_deps = data.get("build-dependencies", {})
    for dep_name in build_deps.keys():
        result["build_dependencies"].append(dep_name)

    return result


def parse_cargo_toml_file(path: Path) -> dict[str, Any]:
    """
    Parse a Cargo.toml file.

    Args:
        path: Path to Cargo.toml

    Returns:
        Parsed dependency info, empty structure if file cannot be read
    """
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return parse_cargo_toml(content)
    except Exception as exc:
        logger.debug("Failed to parse Cargo.toml", path=str(path), error=str(exc))
        return {
            "dependencies": [],
            "dev_dependencies": [],
            "build_dependencies": [],
        }


# ---------------------------------------------------------------------------
# Unified extraction interface
# ---------------------------------------------------------------------------


def extract_all_dependencies(base_path: Path | str) -> dict[str, list[str]]:
    """
    Extract all dependencies from all supported manifest files in a directory.

    This is the main entry point for unified dependency extraction.

    Args:
        base_path: Path to project root directory

    Returns:
        Dictionary mapping dependency source to list of dependency names:
        {
            "python": ["requests", "fastapi", ...],
            "nodejs": ["react", "express", ...],
            "rust": ["serde", "tokio", ...],
        }
    """
    base_path = Path(base_path)
    result: dict[str, list[str]] = {
        "python": [],
        "nodejs": [],
        "rust": [],
    }

    # Python - requirements.txt
    req_path = base_path / "requirements.txt"
    if req_path.exists():
        result["python"].extend(parse_requirements_txt_file(req_path))

    # Python - pyproject.toml
    pyproject_path = base_path / "pyproject.toml"
    if pyproject_path.exists():
        pyproject_data = parse_pyproject_toml_file(pyproject_path)
        result["python"].extend(pyproject_data.get("dependencies", []))
        result["python"].extend(pyproject_data.get("dev_dependencies", []))
        for group_deps in pyproject_data.get("optional_dependencies", {}).values():
            result["python"].extend(group_deps)

    # Python - setup.py
    setup_path = base_path / "setup.py"
    if setup_path.exists():
        setup_data = parse_setup_py_file(setup_path)
        result["python"].extend(setup_data.get("dependencies", []))

    # Node.js - package.json
    pkg_path = base_path / "package.json"
    if pkg_path.exists():
        pkg_data = parse_package_json_file(pkg_path)
        result["nodejs"].extend(pkg_data.get("dependencies", {}).keys())
        result["nodejs"].extend(pkg_data.get("dev_dependencies", {}).keys())
        result["nodejs"].extend(pkg_data.get("peer_dependencies", {}).keys())

    # Rust - Cargo.toml
    cargo_path = base_path / "Cargo.toml"
    if cargo_path.exists():
        cargo_data = parse_cargo_toml_file(cargo_path)
        result["rust"].extend(cargo_data.get("dependencies", []))
        result["rust"].extend(cargo_data.get("dev_dependencies", []))
        result["rust"].extend(cargo_data.get("build_dependencies", []))

    # Deduplicate and sort
    for key in result:
        result[key] = sorted(set(result[key]))

    return result


def extract_dependency_names(base_path: Path | str) -> list[str]:
    """
    Extract all dependency names as a flat list from all manifest files.

    Args:
        base_path: Path to project root directory

    Returns:
        Sorted list of unique dependency names from all sources
    """
    base_path = Path(base_path)
    dependencies: set[str] = set()

    # Python - requirements.txt
    req_path = base_path / "requirements.txt"
    if req_path.exists():
        dependencies.update(parse_requirements_txt_file(req_path))

    # Python - pyproject.toml
    pyproject_path = base_path / "pyproject.toml"
    if pyproject_path.exists():
        pyproject_data = parse_pyproject_toml_file(pyproject_path)
        dependencies.update(pyproject_data.get("dependencies", []))

    # Node.js - package.json
    pkg_path = base_path / "package.json"
    if pkg_path.exists():
        pkg_data = parse_package_json_file(pkg_path)
        dependencies.update(pkg_data.get("dependencies", {}).keys())
        dependencies.update(pkg_data.get("dev_dependencies", {}).keys())

    # Rust - Cargo.toml
    cargo_path = base_path / "Cargo.toml"
    if cargo_path.exists():
        cargo_data = parse_cargo_toml_file(cargo_path)
        dependencies.update(cargo_data.get("dependencies", []))

    return sorted(list(dependencies))
