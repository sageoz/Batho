from __future__ import annotations
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Any

from batho.core.schemas import PackageManager, PackageMetadata

# Safe import for tomllib
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

@dataclass(frozen=True, slots=True)
class DependencySpec:
    name: str                  # "requests", "numpy", "express"
    version_spec: str          # ">=2.28.0", "^1.2.3", "*"
    manager: PackageManager
    language: str              # "python", "javascript", "rust", "go", "java"
    source_file: str           # relative path to the manifest file

class ManifestParser:
    """
    Unified manifest file detection and parsing.
    Returns list[DependencySpec] which contains declared dependencies.
    """
    
    def parse_manifests(self, root: Path) -> List[DependencySpec]:
        """Parse all detected manifests in the root directory."""
        all_deps = []
        root = Path(root)
        
        # 1. Pip/Poetry/Setuptools (Python)
        for req_file in root.glob("requirements*.txt"):
            all_deps.extend(self._parse_requirements_txt(req_file))
        
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            all_deps.extend(self._parse_pyproject_toml(pyproject))
            
        setup_cfg = root / "setup.cfg"
        if setup_cfg.is_file():
            all_deps.extend(self._parse_setup_cfg(setup_cfg))
            
        # 2. NPM (JavaScript)
        pkg_json = root / "package.json"
        if pkg_json.is_file():
            all_deps.extend(self._parse_package_json(pkg_json))
            
        # 3. Cargo (Rust)
        cargo_toml = root / "Cargo.toml"
        if cargo_toml.is_file():
            all_deps.extend(self._parse_cargo_toml(cargo_toml))
            
        # 4. Go (Go)
        go_mod = root / "go.mod"
        if go_mod.is_file():
            all_deps.extend(self._parse_go_mod(go_mod))
            
        # 5. Maven (Java)
        pom_xml = root / "pom.xml"
        if pom_xml.is_file():
            all_deps.extend(self._parse_pom_xml(pom_xml))
            
        # 6. Gradle (Java)
        for gradle_file in root.glob("build.gradle*"):
            all_deps.extend(self._parse_build_gradle(gradle_file))
            
        return all_deps

    @classmethod
    def detect_project_metadata(cls, root: Path, cache=None) -> PackageMetadata | None:
        """Detect the project's own package metadata from root configuration files."""
        root = Path(root)

        # 1. NPM (package.json)
        package_json = root / "package.json"
        if package_json.is_file():
            try:
                file_hash = hashlib.sha256(package_json.read_bytes()).hexdigest()
                if cache is not None:
                    cached = cache.get_project_metadata(str(package_json), file_hash)
                    if cached is not None:
                        return PackageMetadata(
                            manager=PackageManager(cached["manager"]),
                            name=cached["name"],
                            version=cached["version"],
                            source=cached.get("source") or None
                        )
                with open(package_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                name = data.get("name")
                version = data.get("version", "0.0.0")
                if name:
                    result = PackageMetadata(manager=PackageManager.NPM, name=name, version=version)
                    if cache is not None:
                        cache.put_project_metadata(
                            str(package_json), file_hash,
                            {"manager": result.manager.value, "name": result.name,
                             "version": result.version, "source": result.source or ""}
                        )
                    return result
            except Exception:
                pass

        # 2. PIP / Poetry (pyproject.toml)
        pyproject_toml = root / "pyproject.toml"
        if pyproject_toml.is_file():
            try:
                file_hash = hashlib.sha256(pyproject_toml.read_bytes()).hexdigest()
                if cache is not None:
                    cached = cache.get_project_metadata(str(pyproject_toml), file_hash)
                    if cached is not None:
                        return PackageMetadata(
                            manager=PackageManager(cached["manager"]),
                            name=cached["name"],
                            version=cached["version"],
                            source=cached.get("source") or None
                        )
                content = pyproject_toml.read_text(encoding="utf-8")
                data = None
                if tomllib is not None:
                    try:
                        data = tomllib.loads(content)
                    except Exception:
                        pass
                name = None
                version = None
                if data:
                    poetry_sec = data.get("tool", {}).get("poetry", {})
                    if poetry_sec:
                        name = poetry_sec.get("name")
                        version = poetry_sec.get("version")
                    if not name:
                        project_sec = data.get("project", {})
                        if project_sec:
                            name = project_sec.get("name")
                            version = project_sec.get("version")
                if not name:
                    sections = content.split('\n[')
                    for section in sections:
                        if '[tool.poetry]' in section or '[project]' in section:
                            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', section, re.IGNORECASE)
                            if name_match:
                                name = name_match.group(1)
                            version_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', section, re.IGNORECASE)
                            if version_match:
                                version = version_match.group(1)
                            break
                if name:
                    result = PackageMetadata(manager=PackageManager.PIP, name=name, version=version or "0.0.0")
                    if cache is not None:
                        cache.put_project_metadata(
                            str(pyproject_toml), file_hash,
                            {"manager": result.manager.value, "name": result.name,
                             "version": result.version, "source": result.source or ""}
                        )
                    return result
            except Exception:
                pass

        # 3. Cargo (Cargo.toml)
        cargo_toml = root / "Cargo.toml"
        if cargo_toml.is_file():
            try:
                file_hash = hashlib.sha256(cargo_toml.read_bytes()).hexdigest()
                if cache is not None:
                    cached = cache.get_project_metadata(str(cargo_toml), file_hash)
                    if cached is not None:
                        return PackageMetadata(
                            manager=PackageManager(cached["manager"]),
                            name=cached["name"],
                            version=cached["version"],
                            source=cached.get("source") or None
                        )
                content = cargo_toml.read_text(encoding="utf-8")
                data = None
                if tomllib is not None:
                    try:
                        data = tomllib.loads(content)
                    except Exception:
                        pass
                name = None
                version = None
                if data:
                    package_sec = data.get("package", {})
                    name = package_sec.get("name")
                    version = package_sec.get("version")
                if not name:
                    sections = content.split('\n[')
                    for section in sections:
                        if '[package]' in section:
                            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', section, re.IGNORECASE)
                            if name_match:
                                name = name_match.group(1)
                            version_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', section, re.IGNORECASE)
                            if version_match:
                                version = version_match.group(1)
                            break
                if name:
                    result = PackageMetadata(manager=PackageManager.CARGO, name=name, version=version or "0.0.0")
                    if cache is not None:
                        cache.put_project_metadata(
                            str(cargo_toml), file_hash,
                            {"manager": result.manager.value, "name": result.name,
                             "version": result.version, "source": result.source or ""}
                        )
                    return result
            except Exception:
                pass

        # 4. Go (go.mod)
        go_mod = root / "go.mod"
        if go_mod.is_file():
            try:
                file_hash = hashlib.sha256(go_mod.read_bytes()).hexdigest()
                if cache is not None:
                    cached = cache.get_project_metadata(str(go_mod), file_hash)
                    if cached is not None:
                        return PackageMetadata(
                            manager=PackageManager(cached["manager"]),
                            name=cached["name"],
                            version=cached["version"],
                            source=cached.get("source") or None
                        )
                name = None
                go_version = "0.0.0"
                with open(go_mod, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("module "):
                            name = line.split(None, 1)[1].strip()
                        elif line.startswith("go "):
                            go_version = line.split(None, 1)[1].strip()
                if name:
                    result = PackageMetadata(manager=PackageManager.GO, name=name, version=go_version)
                    if cache is not None:
                        cache.put_project_metadata(
                            str(go_mod), file_hash,
                            {"manager": result.manager.value, "name": result.name,
                             "version": result.version, "source": result.source or ""}
                        )
                    return result
            except Exception:
                pass

        # 5. Maven (pom.xml)
        pom_xml = root / "pom.xml"
        if pom_xml.is_file():
            try:
                file_hash = hashlib.sha256(pom_xml.read_bytes()).hexdigest()
                if cache is not None:
                    cached = cache.get_project_metadata(str(pom_xml), file_hash)
                    if cached is not None:
                        return PackageMetadata(
                            manager=PackageManager(cached["manager"]),
                            name=cached["name"],
                            version=cached["version"],
                            source=cached.get("source") or None
                        )
                try:
                    from defusedxml.ElementTree import parse as safe_parse
                    tree = safe_parse(pom_xml)
                except ImportError:
                    content = pom_xml.read_text(encoding="utf-8")
                    if "&" in content and ("<!ENTITY" in content or "<!DOCTYPE" in content):
                        raise ValueError("XML contains entity references - skipping for security")
                    tree = ET.parse(pom_xml)
                xml_root = tree.getroot()
                ns = ""
                if xml_root.tag.startswith("{"):
                    ns = xml_root.tag.split("}")[0] + "}"
                artifactId_node = xml_root.find(f"{ns}artifactId")
                version_node = xml_root.find(f"{ns}version")
                if version_node is None:
                    parent_node = xml_root.find(f"{ns}parent")
                    if parent_node is not None:
                        version_node = parent_node.find(f"{ns}version")
                name = artifactId_node.text.strip() if artifactId_node is not None and artifactId_node.text else None
                version = version_node.text.strip() if version_node is not None and version_node.text else "0.0.0"
                if name:
                    result = PackageMetadata(manager=PackageManager.MAVEN, name=name, version=version)
                    if cache is not None:
                        cache.put_project_metadata(
                            str(pom_xml), file_hash,
                            {"manager": result.manager.value, "name": result.name,
                             "version": result.version, "source": result.source or ""}
                        )
                    return result
            except Exception:
                pass

        # 6. Gradle (build.gradle / settings.gradle)
        build_gradle = root / "build.gradle"
        build_gradle_kts = root / "build.gradle.kts"
        if build_gradle.is_file() or build_gradle_kts.is_file():
            try:
                file_hash = hashlib.sha256((build_gradle.read_bytes() if build_gradle.is_file() else build_gradle_kts.read_bytes())).hexdigest()
                gradle_path = build_gradle if build_gradle.is_file() else build_gradle_kts
                if cache is not None:
                    cached = cache.get_project_metadata(str(gradle_path), file_hash)
                    if cached is not None:
                        return PackageMetadata(
                            manager=PackageManager(cached["manager"]),
                            name=cached["name"],
                            version=cached["version"],
                            source=cached.get("source") or None
                        )
                name = None
                version = "0.0.0"
                settings_gradle = root / "settings.gradle"
                settings_gradle_kts = root / "settings.gradle.kts"
                for settings_file in (settings_gradle, settings_gradle_kts):
                    if settings_file.is_file():
                        content = settings_file.read_text(encoding="utf-8")
                        name_match = re.search(r'rootProject\.name\s*=\s*["\']([^"\']+)["\']', content)
                        if name_match:
                            name = name_match.group(1)
                            break
                if not name:
                    name = root.name
                for build_file in (build_gradle, build_gradle_kts):
                    if build_file.is_file():
                        content = build_file.read_text(encoding="utf-8")
                        version_match = re.search(r'(?:^|\n)\s*version\s*=\s*["\']([^"\']+)["\']', content)
                        if version_match:
                            version = version_match.group(1)
                            break
                result = PackageMetadata(manager=PackageManager.GRADLE, name=name, version=version)
                if cache is not None:
                    cache.put_project_metadata(
                        str(gradle_path), file_hash,
                        {"manager": result.manager.value, "name": result.name,
                         "version": result.version, "source": result.source or ""}
                    )
                return result
            except Exception:
                pass

        return None

    def _parse_requirements_txt(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith(('#', '-', '.')):
                    continue
                # Simple parser for package==version
                match = re.match(r'^([a-zA-Z0-9_\-\[\]]+)(.*)$', line)
                if match:
                    name = match.group(1).strip()
                    version = match.group(2).strip() or "*"
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=version,
                        manager=PackageManager.PIP,
                        language="python",
                        source_file=str(path)
                    ))
        except Exception:
            pass
        return deps

    def _parse_pyproject_toml(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            if tomllib is None:
                return deps
            
            data = tomllib.loads(content)
            
            # [project] dependencies (PEP 621)
            project_deps = data.get("project", {}).get("dependencies", [])
            for dep in project_deps:
                # Simple parsing for "name>=version"
                match = re.match(r'^([a-zA-Z0-9_\-\[\]]+)(.*)$', dep)
                if match:
                    deps.append(DependencySpec(
                        name=match.group(1).strip(),
                        version_spec=match.group(2).strip() or "*",
                        manager=PackageManager.PIP,
                        language="python",
                        source_file=str(path)
                    ))
                    
            # [tool.poetry.dependencies]
            poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            for name, version in poetry_deps.items():
                if name.lower() == "python":
                    continue
                v_spec = version if isinstance(version, str) else "*"
                deps.append(DependencySpec(
                    name=name,
                    version_spec=v_spec,
                    manager=PackageManager.PIP,
                    language="python",
                    source_file=str(path)
                ))
        except Exception:
            pass
        return deps

    def _parse_setup_cfg(self, path: Path) -> List[DependencySpec]:
        # Minimalist implementation for setup.cfg
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            in_install_requires = False
            for line in content.splitlines():
                if "[options]" in line:
                    continue
                if "install_requires" in line:
                    in_install_requires = True
                    continue
                if in_install_requires:
                    if line.startswith("[") or (line and not line.startswith(" ")):
                        in_install_requires = False
                        continue
                    clean_line = line.strip()
                    if clean_line:
                        match = re.match(r'^([a-zA-Z0-9_\-\[\]]+)(.*)$', clean_line)
                        if match:
                            deps.append(DependencySpec(
                                name=match.group(1).strip(),
                                version_spec=match.group(2).strip() or "*",
                                manager=PackageManager.PIP,
                                language="python",
                                source_file=str(path)
                            ))
        except Exception:
            pass
        return deps

    def _parse_package_json(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            for key in ["dependencies", "devDependencies"]:
                pkg_deps = data.get(key, {})
                for name, version in pkg_deps.items():
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=version if isinstance(version, str) else "*",
                        manager=PackageManager.NPM,
                        language="javascript",
                        source_file=str(path)
                    ))
        except Exception:
            pass
        return deps

    def _parse_cargo_toml(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            if tomllib is None: return deps
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            
            cargo_deps = data.get("dependencies", {})
            for name, val in cargo_deps.items():
                v_spec = val if isinstance(val, str) else "*"
                if isinstance(val, dict):
                    v_spec = val.get("version", "*")
                deps.append(DependencySpec(
                    name=name,
                    version_spec=v_spec,
                    manager=PackageManager.CARGO,
                    language="rust",
                    source_file=str(path)
                ))
        except Exception:
            pass
        return deps

    def _parse_go_mod(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            # Simple regex for 'require ( ... )' and 'require name version'
            require_block_match = re.search(r'require\s*\((.*?)\)', content, re.DOTALL)
            if require_block_match:
                block = require_block_match.group(1)
                for line in block.splitlines():
                    line = line.strip()
                    if line:
                        parts = line.split()
                        if len(parts) >= 2:
                            deps.append(DependencySpec(
                                name=parts[0],
                                version_spec=parts[1],
                                manager=PackageManager.GO,
                                language="go",
                                source_file=str(path)
                            ))
            
            single_requires = re.findall(r'require\s+([^\s]+)\s+([^\s]+)', content)
            for name, version in single_requires:
                if name != "(" : # avoid catching block start
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=version,
                        manager=PackageManager.GO,
                        language="go",
                        source_file=str(path)
                    ))
        except Exception:
            pass
        return deps

    def _parse_pom_xml(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            # Handle XML namespaces if present
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"
            
            for dependency in root.findall(f".//{ns}dependency"):
                group_id = dependency.find(f"{ns}groupId")
                artifact_id = dependency.find(f"{ns}artifactId")
                version = dependency.find(f"{ns}version")
                
                if group_id is not None and artifact_id is not None:
                    name = f"{group_id.text}:{artifact_id.text}"
                    v_spec = version.text if version is not None else "*"
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=v_spec,
                        manager=PackageManager.MAVEN,
                        language="java",
                        source_file=str(path)
                    ))
        except Exception:
            pass
        return deps

    def _parse_build_gradle(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            # Heuristic match for implementation "group:artifact:version" or implementation group: '...', name: '...', version: '...'
            # This is very simplified.
            matches = re.findall(r'(?:implementation|api|compile|runtimeOnly)\s+[\'"]([^\'"]+)[\'"]', content)
            for match in matches:
                parts = match.split(':')
                if len(parts) >= 2:
                    name = f"{parts[0]}:{parts[1]}"
                    v_spec = parts[2] if len(parts) > 2 else "*"
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=v_spec,
                        manager=PackageManager.GRADLE,
                        language="java",
                        source_file=str(path)
                    ))
        except Exception:
            pass
        return deps
