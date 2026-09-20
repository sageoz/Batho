from __future__ import annotations
import hashlib
import json
import structlog
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Any, Callable

from batho.core.schemas import PackageManager, PackageMetadata

logger = structlog.get_logger(__name__)

# Safe import for tomllib
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

# Safe import for yaml (pubspec.yaml / stack.yaml manifests)
try:
    import yaml as _yaml
except ImportError:
    _yaml = None

# Pre-compiled regex patterns for performance
REQUIREMENT_PATTERN = re.compile(r'^([a-zA-Z0-9_\-\[\]]+)(.*)$')
TOML_NAME_PATTERN = re.compile(r'name\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
TOML_VERSION_PATTERN = re.compile(r'version\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
GO_MOD_MODULE_PATTERN = re.compile(r'^module\s+(.+)$')
GO_MOD_VERSION_PATTERN = re.compile(r'^go\s+(.+)$')
GRADLE_NAME_PATTERN = re.compile(r'rootProject\.name\s*=\s*["\']([^"\']+)["\']')
GRADLE_VERSION_PATTERN = re.compile(r'(?:^|\n)\s*version\s*=\s*["\']([^"\']+)["\']')
BUILD_GRADLE_DEP_PATTERN = re.compile(r'(?:implementation|api|compile|runtimeOnly)\s*\(?\s*[\'"]([^\'"]+)[\'"]')
BUILD_GRADLE_TEST_DEP_PATTERN = re.compile(r'(?:testImplementation|testRuntimeOnly|testCompile)\s*\(?\s*[\'"]([^\'"]+)[\'"]')
GO_MOD_REQUIRE_BLOCK_PATTERN = re.compile(r'require\s*\((.*?)\)', re.DOTALL)
GO_MOD_SINGLE_REQUIRE_PATTERN = re.compile(r'require\s+([^\s]+)\s+([^\s]+)')

_TEST_GROUP_NAMES = frozenset({"test", "tests", "testing", "integration-test", "integration-tests"})


_TEST_GROUP_NAMES = frozenset({"test", "tests", "testing", "integration-test", "integration-tests"})

_REQ_TEST_TOKENS = frozenset({"test", "tests", "testing"})
_REQ_DEV_TOKENS = frozenset({"dev", "develop", "development"})


def _requirements_file_kind(path: Path) -> str:
    """Heuristic dep kind from a requirements filename."""
    stem = path.stem.lower().replace("_", "-")
    tokens = re.split(r"[-_.]+", stem)
    if any(t in _REQ_TEST_TOKENS for t in tokens):
        return "test"
    if any(t in _REQ_DEV_TOKENS for t in tokens):
        return "dev"
    return "runtime"


# rebar3 dep-spec keywords — atoms that head source/version tuples inside a
# deps entry ({name, {git, "u", {tag, "v"}}}) and must never be read as deps.
_REBAR_SPEC_KEYWORDS = frozenset({
    "deps", "git", "hg", "pkg", "vsn", "tag", "branch", "ref",
    "raw", "checkout", "git_subdir", "hex", "subdir", "first_files",
})


def _extract_erlang_list(content: str, marker: str) -> str | None:
    """Return the body of ``{marker, [ … ]}`` — depth/string aware.

    A plain ``\\[(.*?)\\]`` regex stops at the first ``]``, which truncates
    on nested lists like ``{bear, "0.9.0", [{pkg, bear2}]}``.
    """
    m = re.search(marker + r"\s*,\s*\[", content)
    if not m:
        return None
    start = m.end()
    depth = 1
    in_str = False
    for i in range(start, len(content)):
        ch = content[i]
        if in_str:
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return content[start:i]
    return None


def _split_erlang_list(body: str) -> list[str]:
    """Split an Erlang list body into top-level comma-separated entries.

    Brace/bracket-depth aware with string skipping — rebar dep specs nest
    tuples like ``{cowboy, {git, "u", {tag, "2.9.0"}}}``.
    """
    entries = []
    depth = 0
    cur: list[str] = []
    in_str = False
    for ch in body:
        if in_str:
            cur.append(ch)
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            cur.append(ch)
        elif ch in "{[":
            depth += 1
            cur.append(ch)
        elif ch in "}]":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            entries.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        entries.append("".join(cur))
    return entries


def _parse_rebar_dep_entry(entry: str) -> tuple[str, str] | None:
    """One rebar deps-list entry → ``(name, version_spec)`` or ``None``.

    Forms: ``cowboy`` · ``{cowboy, "2.9.0"}`` · ``{cowboy, {pkg, "3.1.0"}}`` ·
    ``{cowboy, {pkg, cowboy2, "3.1.0"}}`` ·
    ``{cowboy, {git|hg|…, "url", {tag|branch|ref, "V"}}}`` ·
    ``{cowboy, "2.9.0", [{pkg, cowboy2}]}`` (alt-name triple).
    """
    entry = entry.strip()
    if not entry:
        return None
    if not entry.startswith("{"):
        m = re.match(r"[a-z][a-zA-Z0-9_]*", entry)
        if m and m.group(0) not in _REBAR_SPEC_KEYWORDS:
            return m.group(0), "*"
        return None
    if not entry.endswith("}"):
        return None
    inner = entry[1:-1]
    m = re.match(r"\s*([a-zA-Z0-9_]+)\s*", inner)
    if not m:
        return None
    name = m.group(1)
    if name in _REBAR_SPEC_KEYWORDS:
        return None
    rest = inner[m.end():]
    if not rest.startswith(","):
        return name, "*"  # {cowboy} — atom in braces
    rest = rest[1:].lstrip()
    # {name, "ver", [altname]?} — the first quoted token is the version
    if rest.startswith(('"', "'")):
        vm = re.match(r"['\"]([^\"'}]+)['\"]", rest)
        return name, vm.group(1) if vm else "*"
    # {name, {pkg, "ver"}} / {name, {pkg, alt_name, "ver"}}
    pm = re.search(
        r'\{pkg\s*,\s*["\']?[^,}]+["\']?\s*,\s*"([^"}]+)"'
        r'|\{pkg\s*,\s*"([^"}]+)"',
        rest,
    )
    if pm:
        return name, pm.group(1) or pm.group(2)
    # {name, {git|hg|…, "url", {tag|branch|ref, "V"}}} — inner version tuple
    vm = re.search(r'\{(?:tag|branch|ref)\s*,\s*"([^"}]+)"', rest)
    if vm:
        return name, vm.group(1)
    return name, "*"

@dataclass(frozen=True, slots=True)
class DependencySpec:
    name: str                  # "requests", "numpy", "express"
    version_spec: str          # ">=2.28.0", "^1.2.3", "*"
    manager: PackageManager
    language: str              # "python", "javascript", "rust", "go", "java"
    source_file: str           # relative path to the manifest file
    kind: str = "runtime"      # "runtime" | "dev" | "test" | "optional"

class ManifestParser:
    """
    Unified manifest file detection and parsing.
    Returns list[DependencySpec] which contains declared dependencies.
    """

    # Directories to skip when searching for nested manifest files.
    _SKIP_DIRS = frozenset({
        ".git", ".hg", ".svn", ".batho", "__pycache__", "node_modules",
        "target", "vendor", ".venv", "venv", ".tox", "dist", "build",
        ".eggs", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "site-packages", "Cargo.lock", ".idea", ".vscode",
    })

    # Maximum depth for recursive manifest search (root = depth 0).
    _MAX_SEARCH_DEPTH = 3

    # Manifest-type priority within a depth level (depth-major ordering —
    # shallower manifests always outrank deeper ones regardless of type).
    _METADATA_MANIFEST_ORDER = (
        "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        "pom.xml", "build.gradle", "build.gradle.kts",
        # G2a/G2b ecosystems — identity-capable manifests
        "composer.json", "pubspec.yaml", "Project.toml", "DESCRIPTION",
        "*.csproj", "*.rockspec",
    )

    @classmethod
    def _find_manifests(cls, root: Path, pattern: str) -> list[Path]:
        """Find manifest files matching *pattern* in root and nested subdirectories.

        Checks the root first (most common case), then searches recursively
        up to _MAX_SEARCH_DEPTH levels deep, skipping irrelevant directories.
        """
        root = Path(root)
        found: list[Path] = []

        # Root-level check (fast path)
        root_file = root / pattern
        if root_file.is_file():
            found.append(root_file)

        # Recursive search for nested manifests (e.g. tokenizers/tokenizers/Cargo.toml)
        # Always search — monorepos and Rust workspaces have both root and
        # nested manifests (e.g. root Cargo.toml + member crates at subdir/Cargo.toml).
        seen = set(found)
        for path in root.rglob(pattern):
            if path in seen:
                continue
            # Skip if any path component is in the skip set
            if any(part in cls._SKIP_DIRS for part in path.parts):
                continue
            # Enforce max depth relative to root
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            depth = len(rel.parts) - 1  # exclude the filename itself
            if depth <= cls._MAX_SEARCH_DEPTH:
                found.append(path)
                seen.add(path)

        # T6: optional workspace.manifest_dirs allow/deny filter
        return [p for p in found if cls._manifest_allowed(root, p)]

    def parse_manifests(self, root: Path) -> List[DependencySpec]:
        """Parse all detected manifests in the root directory tree.

        Searches the root directory first, then recursively up to 3 levels
        deep for nested manifest files (e.g. monorepo workspaces, Rust
        sub-crates at repo/subdir/Cargo.toml).
        """
        all_deps = []
        root = Path(root)

        # 1. Pip/Poetry/Setuptools (Python)
        for req_file in root.glob("requirements*.txt"):
            all_deps.extend(self._parse_requirements_txt(req_file))

        for pyproject in self._find_manifests(root, "pyproject.toml"):
            all_deps.extend(self._parse_pyproject_toml(pyproject))

        for setup_cfg in self._find_manifests(root, "setup.cfg"):
            all_deps.extend(self._parse_setup_cfg(setup_cfg))

        # 2. NPM (JavaScript)
        for pkg_json in self._find_manifests(root, "package.json"):
            all_deps.extend(self._parse_package_json(pkg_json))

        # 3. Cargo (Rust)
        for cargo_toml in self._find_manifests(root, "Cargo.toml"):
            all_deps.extend(self._parse_cargo_toml(cargo_toml))

        # 4. Go (Go)
        for go_mod in self._find_manifests(root, "go.mod"):
            all_deps.extend(self._parse_go_mod(go_mod))

        # 5. Maven (Java)
        for pom_xml in self._find_manifests(root, "pom.xml"):
            all_deps.extend(self._parse_pom_xml(pom_xml))

        # 6. Gradle (Java)
        for gradle_file in self._find_manifests(root, "build.gradle"):
            all_deps.extend(self._parse_build_gradle(gradle_file))
        for gradle_file in self._find_manifests(root, "build.gradle.kts"):
            all_deps.extend(self._parse_build_gradle(gradle_file))

        # 7. PHP / Composer (G2a)
        for composer in self._find_manifests(root, "composer.json"):
            all_deps.extend(self._parse_composer_json(composer))

        # 8. Dart / pub (G2a)
        for pubspec in self._find_manifests(root, "pubspec.yaml"):
            all_deps.extend(self._parse_pubspec_yaml(pubspec))

        # 9. Julia (G2a) — Project.toml guarded by uuid key
        for project_toml in self._find_manifests(root, "Project.toml"):
            all_deps.extend(self._parse_julia_project(project_toml))

        # 10. R (G2a)
        for desc in self._find_manifests(root, "DESCRIPTION"):
            all_deps.extend(self._parse_r_description(desc))

        # 11. C# / NuGet (G2a)
        for csproj in self._find_manifests(root, "*.csproj"):
            all_deps.extend(self._parse_csproj(csproj))

        # 12. Ruby / gems (G2b)
        for gemfile in self._find_manifests(root, "Gemfile"):
            all_deps.extend(self._parse_gemfile(gemfile))
        for gemspec in self._find_manifests(root, "*.gemspec"):
            all_deps.extend(self._parse_gemspec(gemspec))

        # 13. Swift / SwiftPM (G2b)
        for pkg_swift in self._find_manifests(root, "Package.swift"):
            all_deps.extend(self._parse_package_swift(pkg_swift))

        # 14. Haskell / Cabal (G2b)
        for cabal in self._find_manifests(root, "*.cabal"):
            all_deps.extend(self._parse_cabal(cabal))

        # 15. Zig (G2b)
        for zig_zon in self._find_manifests(root, "build.zig.zon"):
            all_deps.extend(self._parse_zig_zon(zig_zon))

        # 16. Erlang / rebar3 (G2b)
        for rebar in self._find_manifests(root, "rebar.config"):
            all_deps.extend(self._parse_rebar_config(rebar))

        # 17. OCaml / opam (G2b)
        for opam in self._find_manifests(root, "*.opam"):
            all_deps.extend(self._parse_opam(opam))

        # 18. Lua / LuaRocks (G2b)
        for rockspec in self._find_manifests(root, "*.rockspec"):
            all_deps.extend(self._parse_rockspec(rockspec))

        # 19. Perl / CPAN (G2b)
        for cpanfile in self._find_manifests(root, "cpanfile"):
            all_deps.extend(self._parse_cpanfile(cpanfile))

        # 20. Agda (G3)
        for agda_lib in self._find_manifests(root, "*.agda-lib"):
            all_deps.extend(self._parse_agda_lib(agda_lib))

        return all_deps

    @staticmethod
    def _with_cache(
        cache, file_path: Path, parser_fn: Callable[[], PackageMetadata | None]
    ) -> PackageMetadata | None:
        """Generic cache wrapper for metadata parsing."""
        try:
            file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        except Exception as e:
            logger.warning(f"Failed to hash {file_path}: {e}")
            return None

        # Check cache
        if cache is not None:
            try:
                cached = cache.get_project_metadata(str(file_path), file_hash)
                if cached is not None:
                    return PackageMetadata(
                        manager=PackageManager(cached["manager"]),
                        name=cached["name"],
                        version=cached["version"],
                        source=cached.get("source") or None
                    )
            except Exception as e:
                logger.debug(f"Cache read failed for {file_path}: {e}")

        # Parse
        try:
            result = parser_fn()
        except Exception as e:
            logger.debug(f"Parse failed for {file_path}: {e}")
            return None

        # Store in cache
        if result is not None and cache is not None:
            try:
                cache.put_project_metadata(
                    str(file_path), file_hash,
                    {"manager": result.manager.value, "name": result.name,
                     "version": result.version, "source": result.source or ""}
                )
            except Exception as e:
                logger.debug(f"Cache write failed for {file_path}: {e}")

        return result

    @classmethod
    def _metadata_candidates(cls, root: Path) -> list[tuple[int, int, str, Path]]:
        """All manifests that can carry project metadata, sorted depth-major.

        Ordering key is ``(depth, manifest-type rank, path)``: manifests closer
        to the root always outrank nested ones, while two manifests at the same
        depth keep the fixed type priority from ``_METADATA_MANIFEST_ORDER``
        (npm before pip before cargo …). The path component makes same-depth
        same-type ties deterministic — rglob order is OS-dependent.
        """
        root = Path(root)
        candidates: list[tuple[int, int, str, Path]] = []
        for rank, pattern in enumerate(cls._METADATA_MANIFEST_ORDER):
            for path in cls._find_manifests(root, pattern):
                depth = len(path.relative_to(root).parts) - 1
                candidates.append((depth, rank, str(path), path))
        candidates.sort()
        return candidates

    @classmethod
    def _parse_metadata_for(cls, path: Path) -> PackageMetadata | None:
        """Dispatch to the metadata parser matching the manifest filename."""
        name = path.name
        if name == "package.json":
            return cls._parse_npm_metadata(path)
        if name == "pyproject.toml":
            return cls._parse_pyproject_metadata(path)
        if name == "Cargo.toml":
            return cls._parse_cargo_metadata(path)
        if name == "go.mod":
            return cls._parse_go_metadata(path)
        if name == "pom.xml":
            return cls._parse_maven_metadata(path)
        if name == "build.gradle":
            return cls._parse_gradle_metadata(path.parent, path, None)
        if name == "build.gradle.kts":
            return cls._parse_gradle_metadata(path.parent, None, path)
        if name == "composer.json":
            return cls._parse_composer_metadata(path)
        if name == "pubspec.yaml":
            return cls._parse_pubspec_metadata(path)
        if name == "Project.toml":
            return cls._parse_julia_metadata(path)
        if name == "DESCRIPTION":
            return cls._parse_r_metadata(path)
        if name.endswith(".csproj"):
            return cls._parse_csproj_metadata(path)
        if name.endswith(".rockspec"):
            return cls._parse_rockspec_metadata(path)
        return None

    @staticmethod
    def _parse_composer_metadata(path: Path) -> PackageMetadata | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("name")
            if name:
                return PackageMetadata(
                    manager=PackageManager.COMPOSER, name=name,
                    version=str(data.get("version", "0.0.0")))
        except Exception as e:
            logger.debug(f"Metadata parse failed for {path}: {e}")
        return None

    @classmethod
    def _parse_pubspec_metadata(cls, path: Path) -> PackageMetadata | None:
        if _yaml is None:
            return None
        try:
            data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            name = data.get("name")
            if name:
                return PackageMetadata(
                    manager=PackageManager.PUB, name=name,
                    version=str(data.get("version", "0.0.0")))
        except Exception as e:
            logger.debug(f"Metadata parse failed for {path}: {e}")
        return None

    @classmethod
    def _parse_julia_metadata(cls, path: Path) -> PackageMetadata | None:
        if tomllib is None:
            return None
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            if not data.get("uuid"):
                return None
            name = data.get("name")
            if name:
                return PackageMetadata(
                    manager=PackageManager.JULIA, name=name,
                    version=str(data.get("version", "0.0.0")))
        except Exception as e:
            logger.debug(f"Metadata parse failed for {path}: {e}")
        return None

    @classmethod
    def _parse_r_metadata(cls, path: Path) -> PackageMetadata | None:
        try:
            fields = cls._parse_dcf(path)
            name = fields.get("Package")
            if name:
                return PackageMetadata(
                    manager=PackageManager.CRAN, name=name,
                    version=fields.get("Version", "0.0.0"))
        except Exception as e:
            logger.debug(f"Metadata parse failed for {path}: {e}")
        return None

    @classmethod
    def _parse_csproj_metadata(cls, path: Path) -> PackageMetadata | None:
        try:
            try:
                from defusedxml.ElementTree import parse as safe_parse
                tree = safe_parse(path)
            except ImportError:
                tree = ET.parse(path)
            root = tree.getroot()
            name = version = None
            for elem in root.iter():
                tag = elem.tag.rsplit("}", 1)[-1]
                if tag == "AssemblyName" and elem.text and not name:
                    name = elem.text.strip()
                elif tag == "Version" and elem.text and not version:
                    version = elem.text.strip()
            if name:
                return PackageMetadata(
                    manager=PackageManager.NUGET, name=name,
                    version=version or "0.0.0")
        except Exception as e:
            logger.debug(f"Metadata parse failed for {path}: {e}")
        return None

    @classmethod
    def _parse_rockspec_metadata(cls, path: Path) -> PackageMetadata | None:
        try:
            content = path.read_text(encoding="utf-8")
            pkg = re.search(r'package\s*=\s*["\']([^"\']+)["\']', content)
            ver = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if pkg:
                return PackageMetadata(
                    manager=PackageManager.LUAROCKS, name=pkg.group(1),
                    version=ver.group(1) if ver else "0.0.0")
        except Exception as e:
            logger.debug(f"Metadata parse failed for {path}: {e}")
        return None

    @classmethod
    def _config_package_override(cls) -> PackageMetadata | None:
        """Optional ``project.package`` identity override from batho.yaml (T6)."""
        override = cls._workspace_config().get("package")
        if not isinstance(override, dict) or not override.get("name"):
            return None
        try:
            manager = PackageManager(override.get("manager", "pip"))
        except ValueError:
            manager = PackageManager.PIP
        return PackageMetadata(
            manager=manager,
            name=override["name"],
            version=str(override.get("version", "0.0.0")),
        )

    @classmethod
    def _manifest_allowed(cls, root: Path, path: Path) -> bool:
        """Apply the optional ``workspace.manifest_dirs`` allow/deny filter (T6).

        Config shapes: ``manifest_dirs: [docs-site, examples]`` (allowlist),
        or ``manifest_dirs: {allow: […], deny: […], }``. Prefixes are
        repo-relative dir paths; ``deny`` wins over ``allow``.
        """
        rules = cls._workspace_config().get("manifest_dirs")
        if not rules:
            return True
        if isinstance(rules, dict):
            allow = list(rules.get("allow") or [])
            deny = list(rules.get("deny") or [])
        else:
            allow, deny = list(rules), []

        try:
            rel = path.parent.relative_to(root).as_posix()
        except ValueError:
            rel = "."

        def _under(prefixes: list) -> bool:
            for prefix in prefixes:
                p = str(prefix).strip().strip("/")
                if not p:
                    continue
                if rel == p or rel.startswith(p + "/"):
                    return True
            return False

        if allow and not _under(allow):
            return False
        if deny and _under(deny):
            return False
        return True

    @staticmethod
    def _workspace_config() -> dict:
        """The merged ``workspace``/``project`` config subtree, or ``{}``."""
        try:
            from batho.core.config import get_config_cached
            cfg = get_config_cached()
        except Exception:
            return {}
        if cfg is None:
            return {}
        if hasattr(cfg, "model_dump"):
            cfg = cfg.model_dump()
        if not isinstance(cfg, dict):
            return {}
        workspace = cfg.get("workspace") if isinstance(cfg.get("workspace"), dict) else {}
        project = cfg.get("project") if isinstance(cfg.get("project"), dict) else {}
        merged = dict(workspace)
        if isinstance(project.get("package"), dict):
            merged["package"] = project["package"]
        return merged

    @classmethod
    def detect_project_metadata(cls, root: Path, cache=None) -> PackageMetadata | None:
        """Detect the project's own package metadata from manifest files.

        Depth-major ordering: the shallowest manifest that parses wins, so a
        root manifest always claims the workspace identity and nested
        manifests (monorepo members, docs sites) only apply when no shallower
        manifest yields metadata.

        An explicit ``project.package`` config override (T6) is consulted
        first and bypasses detection entirely.
        """
        override = cls._config_package_override()
        if override:
            return override
        for _depth, _rank, _key, path in cls._metadata_candidates(root):
            result = cls._with_cache(
                cache, path, lambda p=path: cls._parse_metadata_for(p))
            if result:
                return result
        return None

    @classmethod
    def detect_workspace_packages(
        cls, root: Path, cache=None
    ) -> dict[str, list[PackageMetadata]]:
        """Map ``{manifest_dir → [PackageMetadata, …]}`` for the whole workspace.

        Keys are repo-relative dir strings (``"."`` for the root manifest
        dir). A dir hosting several manifests (polyglot root) keeps all of
        them so callers can disambiguate per file language.

        An explicit ``project.package`` config override (T6) replaces the
        root manifest dir's identity (``"."``); nested subprojects still map.
        """
        override = cls._config_package_override()
        root = Path(root)
        packages: dict[str, list[PackageMetadata]] = {}
        for _depth, _rank, _key, path in cls._metadata_candidates(root):
            meta = cls._with_cache(
                cache, path, lambda p=path: cls._parse_metadata_for(p))
            if not meta:
                continue
            try:
                rel_dir = path.parent.relative_to(root).as_posix()
            except ValueError:
                rel_dir = "."
            packages.setdefault(rel_dir or ".", []).append(meta)
        if override:
            packages["."] = [override]
        return packages

    @staticmethod
    def _parse_npm_metadata(path: Path) -> PackageMetadata | None:
        """Parse package.json for metadata."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("name")
        version = data.get("version", "0.0.0")
        if name:
            return PackageMetadata(manager=PackageManager.NPM, name=name, version=version)
        return None

    @staticmethod
    def _parse_pyproject_metadata(path: Path) -> PackageMetadata | None:
        """Parse pyproject.toml for metadata."""
        content = path.read_text(encoding="utf-8")
        data = None
        if tomllib is not None:
            try:
                data = tomllib.loads(content)
            except Exception:
                pass

        name = version = None
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
                    name_match = TOML_NAME_PATTERN.search(section)
                    if name_match:
                        name = name_match.group(1)
                    version_match = TOML_VERSION_PATTERN.search(section)
                    if version_match:
                        version = version_match.group(1)
                    break

        if name:
            return PackageMetadata(manager=PackageManager.PIP, name=name, version=version or "0.0.0")
        return None

    @staticmethod
    def _parse_cargo_metadata(path: Path) -> PackageMetadata | None:
        """Parse Cargo.toml for metadata."""
        content = path.read_text(encoding="utf-8")
        data = None
        if tomllib is not None:
            try:
                data = tomllib.loads(content)
            except Exception:
                pass

        name = version = None
        if data:
            package_sec = data.get("package", {})
            name = package_sec.get("name")
            version = package_sec.get("version")

        if not name:
            sections = content.split('\n[')
            for section in sections:
                if '[package]' in section:
                    name_match = TOML_NAME_PATTERN.search(section)
                    if name_match:
                        name = name_match.group(1)
                    version_match = TOML_VERSION_PATTERN.search(section)
                    if version_match:
                        version = version_match.group(1)
                    break

        if name:
            return PackageMetadata(manager=PackageManager.CARGO, name=name, version=version or "0.0.0")
        return None

    @staticmethod
    def _parse_go_metadata(path: Path) -> PackageMetadata | None:
        """Parse go.mod for metadata."""
        name = None
        go_version = "0.0.0"
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("module "):
                    name = line.split(None, 1)[1].strip()
                elif line.startswith("go "):
                    go_version = line.split(None, 1)[1].strip()
        if name:
            return PackageMetadata(manager=PackageManager.GO, name=name, version=go_version)
        return None

    @staticmethod
    def _parse_maven_metadata(path: Path) -> PackageMetadata | None:
        """Parse pom.xml for metadata."""
        try:
            from defusedxml.ElementTree import parse as safe_parse
            tree = safe_parse(path)
        except ImportError:
            content = path.read_text(encoding="utf-8")
            content_upper = content.upper()
            if "&" in content and ("<!ENTITY" in content_upper or "<!DOCTYPE" in content_upper):
                raise ValueError("XML contains entity references - skipping for security")
            tree = ET.parse(path)

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
            return PackageMetadata(manager=PackageManager.MAVEN, name=name, version=version)
        return None

    @staticmethod
    def _parse_gradle_metadata(root: Path, build_gradle: Path, build_gradle_kts: Path) -> PackageMetadata | None:
        """Parse Gradle build files for metadata."""
        name = None
        version = "0.0.0"

        settings_gradle = root / "settings.gradle"
        settings_gradle_kts = root / "settings.gradle.kts"
        for settings_file in (settings_gradle, settings_gradle_kts):
            if settings_file.is_file():
                content = settings_file.read_text(encoding="utf-8")
                name_match = GRADLE_NAME_PATTERN.search(content)
                if name_match:
                    name = name_match.group(1)
                    break

        if not name:
            name = root.name

        for build_file in (build_gradle, build_gradle_kts):
            if build_file.is_file():
                content = build_file.read_text(encoding="utf-8")
                version_match = GRADLE_VERSION_PATTERN.search(content)
                if version_match:
                    version = version_match.group(1)
                    break

        return PackageMetadata(manager=PackageManager.GRADLE, name=name, version=version)

    def _parse_requirements_txt(self, path: Path) -> List[DependencySpec]:
        deps = []
        dep_kind = _requirements_file_kind(path)
        try:
            content = path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith(('#', '-', '.')):
                    continue
                match = REQUIREMENT_PATTERN.match(line)
                if match:
                    name = match.group(1).strip()
                    version = match.group(2).strip() or "*"
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=version,
                        manager=PackageManager.PIP,
                        language="python",
                        source_file=str(path),
                        kind=dep_kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_pyproject_toml(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            if tomllib is None:
                return deps

            content = path.read_text(encoding="utf-8")
            data = tomllib.loads(content)

            # [project] dependencies (PEP 621)
            project_deps = data.get("project", {}).get("dependencies", [])
            for dep in project_deps:
                match = REQUIREMENT_PATTERN.match(dep)
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

            # [project.optional-dependencies] (PEP 621 extras)
            opt_deps = data.get("project", {}).get("optional-dependencies", {})
            for extra, extra_deps in opt_deps.items():
                extra_kind = "test" if extra.lower() in _TEST_GROUP_NAMES else "optional"
                for dep in extra_deps:
                    match = REQUIREMENT_PATTERN.match(dep)
                    if match:
                        deps.append(DependencySpec(
                            name=match.group(1).strip(),
                            version_spec=match.group(2).strip() or "*",
                            manager=PackageManager.PIP,
                            language="python",
                            source_file=str(path),
                            kind=extra_kind,
                        ))

            # [dependency-groups] (PEP 735)
            dep_groups = data.get("dependency-groups", {})
            for group_name, entries in dep_groups.items():
                group_kind = "test" if group_name.lower() in _TEST_GROUP_NAMES else "dev"
                for entry in entries:
                    if not isinstance(entry, str):
                        continue  # {include-group: ...} entries
                    match = REQUIREMENT_PATTERN.match(entry)
                    if match:
                        deps.append(DependencySpec(
                            name=match.group(1).strip(),
                            version_spec=match.group(2).strip() or "*",
                            manager=PackageManager.PIP,
                            language="python",
                            source_file=str(path),
                            kind=group_kind,
                        ))

            # [tool.poetry.dev-dependencies] (legacy poetry)
            poetry_dev = data.get("tool", {}).get("poetry", {}).get("dev-dependencies", {})
            for name, version in poetry_dev.items():
                v_spec = version if isinstance(version, str) else "*"
                deps.append(DependencySpec(
                    name=name,
                    version_spec=v_spec,
                    manager=PackageManager.PIP,
                    language="python",
                    source_file=str(path),
                    kind="dev",
                ))

            # [tool.poetry.group.<name>.dependencies]
            poetry_groups = data.get("tool", {}).get("poetry", {}).get("group", {})
            for group_name, group_data in poetry_groups.items():
                group_kind = "test" if group_name.lower() in _TEST_GROUP_NAMES else "dev"
                for name, version in group_data.get("dependencies", {}).items():
                    if name.lower() == "python":
                        continue
                    v_spec = version if isinstance(version, str) else "*"
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=v_spec,
                        manager=PackageManager.PIP,
                        language="python",
                        source_file=str(path),
                        kind=group_kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_setup_cfg(self, path: Path) -> List[DependencySpec]:
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
                        match = REQUIREMENT_PATTERN.match(clean_line)
                        if match:
                            deps.append(DependencySpec(
                                name=match.group(1).strip(),
                                version_spec=match.group(2).strip() or "*",
                                manager=PackageManager.PIP,
                                language="python",
                                source_file=str(path)
                            ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_package_json(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for key, kind in (("dependencies", "runtime"),
                              ("devDependencies", "dev"),
                              ("optionalDependencies", "optional")):
                pkg_deps = data.get(key, {})
                for name, version in pkg_deps.items():
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=version if isinstance(version, str) else "*",
                        manager=PackageManager.NPM,
                        language="javascript",
                        source_file=str(path),
                        kind=kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_cargo_toml(self, path: Path) -> List[DependencySpec]:
        deps = []
        if tomllib is None:
            return deps

        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))

            for section, dep_kind in (("dependencies", "runtime"),
                                      ("dev-dependencies", "dev"),
                                      ("build-dependencies", "dev")):
                cargo_deps = data.get(section, {})
                for name, val in cargo_deps.items():
                    v_spec = val if isinstance(val, str) else "*"
                    if isinstance(val, dict):
                        v_spec = val.get("version", "*")
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=v_spec,
                        manager=PackageManager.CARGO,
                        language="rust",
                        source_file=str(path),
                        kind=dep_kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_go_mod(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            content = path.read_text(encoding="utf-8")

            # Parse require block
            require_block_match = GO_MOD_REQUIRE_BLOCK_PATTERN.search(content)
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

            # Parse single requires
            for name, version in GO_MOD_SINGLE_REQUIRE_PATTERN.findall(content):
                if name != "(":  # skip block start
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=version,
                        manager=PackageManager.GO,
                        language="go",
                        source_file=str(path)
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_pom_xml(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            raw_content = path.read_text(encoding="utf-8")
            try:
                from defusedxml.ElementTree import parse as safe_parse
                tree = safe_parse(path)
            except ImportError:
                content = raw_content
                content_upper = content.upper()
                if "&" in content and ("<!ENTITY" in content_upper or "<!DOCTYPE" in content_upper):
                    raise ValueError("XML contains entity references - skipping for security")
                tree = ET.parse(path)
            root = tree.getroot()
            # Handle XML namespaces if present
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"

            dep_language = self._jvm_language_for_build_file(path, raw_content)

            for dependency in root.findall(f".//{ns}dependency"):
                group_id = dependency.find(f"{ns}groupId")
                artifact_id = dependency.find(f"{ns}artifactId")
                version = dependency.find(f"{ns}version")
                scope = dependency.find(f"{ns}scope")

                if group_id is not None and artifact_id is not None:
                    name = f"{group_id.text}:{artifact_id.text}"
                    v_spec = version.text if version is not None else "*"
                    dep_kind = "test" if (
                        scope is not None and scope.text
                        and scope.text.strip() == "test"
                    ) else "runtime"
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=v_spec,
                        manager=PackageManager.MAVEN,
                        language=dep_language,
                        source_file=str(path),
                        kind=dep_kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    # JVM language signals inside build files (G1): Gradle/Maven declare
    # Kotlin/Scala via their compiler plugins; the build file *contents*
    # carry the signal (SCIP attributes language per source file, but the
    # manifest's declared language drives stdlib registration + dep IDs).
    _KOTLIN_PLUGIN_PATTERN = re.compile(
        r"org\.jetbrains\.kotlin|kotlin\s*\(\s*[\"']jvm[\"']\s*\)|\bid\s*[\"']?kotlin\b")
    _SCALA_PLUGIN_PATTERN = re.compile(
        r"plugins?\s*\{[^}]*\bid\s*[\"']scala['\"]|apply\s+plugin:\s*['\"]scala['\"]")

    @staticmethod
    def _jvm_language_for_build_file(path: Path, content: str) -> str:
        """Language attribution for JVM build files (G1).

        ``build.gradle.kts`` implies Kotlin DSL; a Gradle/Maven build
        declaring the Kotlin or Scala plugin implies that language; sbt's
        ``build.sbt`` does NOT imply Scala (Java sbt projects exist).
        """
        if path.suffix == ".kts":
            return "kotlin"
        if "org.jetbrains.kotlin" in content or "kotlin-maven-plugin" in content:
            return "kotlin"
        if ManifestParser._SCALA_PLUGIN_PATTERN.search(content):
            return "scala"
        return "java"

    def _parse_build_gradle(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            dep_language = self._jvm_language_for_build_file(path, content)
            for pattern, dep_kind in ((BUILD_GRADLE_DEP_PATTERN, "runtime"),
                                      (BUILD_GRADLE_TEST_DEP_PATTERN, "test")):
                for match in pattern.findall(content):
                    parts = match.split(':')
                    if len(parts) >= 2:
                        name = f"{parts[0]}:{parts[1]}"
                        v_spec = parts[2] if len(parts) > 2 else "*"
                        deps.append(DependencySpec(
                            name=name,
                            version_spec=v_spec,
                            manager=PackageManager.GRADLE,
                            language=dep_language,
                            source_file=str(path),
                            kind=dep_kind,
                        ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    # ------------------------------------------------------------------
    # G2a — structured-format manifests (composer, pubspec, Project.toml,
    # DESCRIPTION, .csproj)
    # ------------------------------------------------------------------

    def _parse_composer_json(self, path: Path) -> List[DependencySpec]:
        """composer.json — JSON; require → runtime, require-dev → dev."""
        deps = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, kind in (("require", "runtime"), ("require-dev", "dev")):
                for name, version in (data.get(key) or {}).items():
                    if name in ("php", "hhvm") or name.startswith(("ext-", "lib-")):
                        continue  # platform requirements, not packages
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=version if isinstance(version, str) else "*",
                        manager=PackageManager.COMPOSER,
                        language="php",
                        source_file=str(path),
                        kind=kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_pubspec_yaml(self, path: Path) -> List[DependencySpec]:
        """pubspec.yaml — YAML; dependencies / dev_dependencies."""
        deps = []
        if _yaml is None:
            return deps
        try:
            data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for key, kind in (("dependencies", "runtime"),
                              ("dev_dependencies", "dev")):
                for name, spec in (data.get(key) or {}).items():
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=spec if isinstance(spec, str) else "*",
                        manager=PackageManager.PUB,
                        language="dart",
                        source_file=str(path),
                        kind=kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_julia_project(self, path: Path) -> List[DependencySpec]:
        """Project.toml — TOML; [deps] runtime, [extras]+[targets] test."""
        deps = []
        if tomllib is None:
            return deps
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            # Julia guard: Project.toml carries a top-level uuid; a generic
            # TOML file without one is not a Julia manifest.
            if not data.get("uuid"):
                return deps
            compat = data.get("compat", {})
            for name in data.get("deps", {}):
                v = compat.get(name, "*")
                deps.append(DependencySpec(
                    name=name,
                    version_spec=str(v) if v else "*",
                    manager=PackageManager.JULIA,
                    language="julia",
                    source_file=str(path),
                    kind="runtime",
                ))
            extras = set(data.get("extras", {}).keys())
            targets = data.get("targets", {})
            for name in targets.get("test", []) if isinstance(targets, dict) else []:
                if name in extras:
                    deps.append(DependencySpec(
                        name=name,
                        version_spec="*",
                        manager=PackageManager.JULIA,
                        language="julia",
                        source_file=str(path),
                        kind="test",
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    @staticmethod
    def _parse_dcf(path: Path) -> dict:
        """Parse a DCF file (R DESCRIPTION): ``Field: value`` with indented
        continuation lines."""
        fields: Dict[str, str] = {}
        current: str | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line[:1] in (" ", "\t"):
                if current:
                    fields[current] += " " + line.strip()
            elif ":" in line:
                key, _, value = line.partition(":")
                current = key.strip()
                fields[current] = value.strip()
        return fields

    def _parse_r_description(self, path: Path) -> List[DependencySpec]:
        """R DESCRIPTION — DCF; Depends/Imports runtime, Suggests optional."""
        deps = []
        try:
            fields = self._parse_dcf(path)
            for field, kind in (("Depends", "runtime"), ("Imports", "runtime"),
                                ("LinkingTo", "runtime"), ("Suggests", "optional")):
                raw = fields.get(field, "")
                for entry in raw.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    match = re.match(r"^([A-Za-z][A-Za-z0-9.]*)\s*(?:\(([^)]+)\))?\s*$", entry)
                    if match and match.group(1) != "R":  # 'R' is the interpreter
                        deps.append(DependencySpec(
                            name=match.group(1),
                            version_spec=(match.group(2) or "*").strip(),
                            manager=PackageManager.CRAN,
                            language="r",
                            source_file=str(path),
                            kind=kind,
                        ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_csproj(self, path: Path) -> List[DependencySpec]:
        """*.csproj — MSBuild XML; PackageReference → deps."""
        deps = []
        try:
            try:
                from defusedxml.ElementTree import parse as safe_parse
                tree = safe_parse(path)
            except ImportError:
                content = path.read_text(encoding="utf-8")
                content_upper = content.upper()
                if "&" in content and ("<!ENTITY" in content_upper or "<!DOCTYPE" in content_upper):
                    raise ValueError("XML contains entity references - skipping for security")
                tree = ET.parse(path)
            root = tree.getroot()
            for elem in root.iter():
                if not elem.tag.endswith("PackageReference"):
                    continue
                name = elem.get("Include")
                if not name:
                    continue
                version = elem.get("Version") or "*"
                private = None
                for child in elem:
                    if child.tag.endswith("PrivateAssets"):
                        private = (child.text or "").strip()
                        break
                deps.append(DependencySpec(
                    name=name,
                    version_spec=version or "*",
                    manager=PackageManager.NUGET,
                    language="csharp",
                    source_file=str(path),
                    kind="dev" if private == "all" else "runtime",
                ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    # ------------------------------------------------------------------
    # G2b — DSL / line-parseable manifests (conservative regex; no eval)
    # ------------------------------------------------------------------

    def _parse_gemfile(self, path: Path) -> List[DependencySpec]:
        """Gemfile — Ruby DSL; group blocks → dev."""
        deps = []
        try:
            kind = "runtime"
            for raw in path.read_text(encoding="utf-8").splitlines():
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("group") and stripped.rstrip().endswith("do"):
                    kind = "dev"
                    continue
                if stripped == "end":
                    kind = "runtime"
                    continue
                match = re.match(r"^gem\s+['\"]([\w.\-]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?", stripped)
                if match:
                    deps.append(DependencySpec(
                        name=match.group(1),
                        version_spec=match.group(2) or "*",
                        manager=PackageManager.GEM,
                        language="ruby",
                        source_file=str(path),
                        kind=kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_gemspec(self, path: Path) -> List[DependencySpec]:
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            for pattern, kind in ((re.compile(
                    r"add_development_dependency\s*\(?\s*['\"]([\w.\-]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?"),
                    "dev"),
                    (re.compile(r"add_(?:runtime_)?dependency\s*\(?\s*['\"]([\w.\-]+)['\"](?:\s*,?\s*['\"]([^'\"]*)['\"])?"),
                     "runtime")):
                for name, version in pattern.findall(content):
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=version or "*",
                        manager=PackageManager.GEM,
                        language="ruby",
                        source_file=str(path),
                        kind=kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_package_swift(self, path: Path) -> List[DependencySpec]:
        """Package.swift — Swift DSL; .package(url:…) entries."""
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            for url, from_ver, exact in re.findall(
                    r"\.package\s*\(\s*url:\s*\"([^\"]+)\"[^)]*?"
                    r"(?:from:\s*\"([^\"]+)\"|\.exact\(\s*\"([^\"]+)\"\s*\))",
                    content):
                name = url.rstrip("/").split("/")[-1]
                if name.endswith(".git"):
                    name = name[:-4]
                deps.append(DependencySpec(
                    name=name,
                    version_spec=from_ver or exact or "*",
                    manager=PackageManager.SPM,
                    language="swift",
                    source_file=str(path),
                    kind="runtime",
                ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_cabal(self, path: Path) -> List[DependencySpec]:
        """*.cabal — per-component build-depends; test-suite/benchmark → test."""
        deps = []
        try:
            section_kind = "runtime"
            field = None
            buf = ""
            lines = path.read_text(encoding="utf-8").splitlines() + [""]

            def _flush():
                if field != "build-depends":
                    return
                for entry in buf.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    m = re.match(r"^([A-Za-z0-9][\w.-]*)(?:\s+[=!<>]=?\s*.+)?$", entry)
                    if m:
                        deps.append(DependencySpec(
                            name=m.group(1),
                            version_spec=entry[len(m.group(1)):].strip() or "*",
                            manager=PackageManager.CABAL,
                            language="haskell",
                            source_file=str(path),
                            kind=section_kind,
                        ))

            for raw in lines:
                if not raw.strip() or raw.strip().startswith("--"):
                    continue
                if raw[0].isspace():
                    # Cabal fields are indented inside stanzas — a line like
                    # "  build-depends: base, aeson" starts/continues a field.
                    stripped = raw.strip()
                    if ":" in stripped and not field == "build-depends":
                        first = stripped.split(":", 1)[0].strip()
                        if first and " " not in first:
                            _flush()
                            field = first
                            buf = stripped.partition(":")[2]
                            continue
                    if field == "build-depends":
                        buf += " " + stripped
                    continue
                # Top-level: stanza headers (no colon) or fields
                first_word = raw.split()[0].rstrip(":")
                if first_word in ("library", "executable", "test-suite", "benchmark", "common"):
                    _flush()
                    field = None
                    section_kind = "test" if first_word in ("test-suite", "benchmark") else "runtime"
                elif ":" in raw:
                    _flush()
                    field = raw.split(":", 1)[0].strip()
                    buf = raw.partition(":")[2]
            _flush()
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_zig_zon(self, path: Path) -> List[DependencySpec]:
        """build.zig.zon — ZON; .dependencies struct entries.

        Dependency entries are ``.name = .{ .url = …, .hash = … }`` or
        ``.{ .path = … }`` structs — matched directly (brace-nesting-safe)
        by requiring ``.url``/``.path`` inside the struct body.
        """
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            # Dependency entries are flat structs (no nested braces): exclude
            # both brace kinds from the body so the outer .dependencies
            # wrapper can't match.
            for match in re.finditer(
                    r"\.(\w+)\s*=\s*\.\{([^{}]*\.(?:url|path)[^{}]*)\}", content):
                name, body = match.group(1), match.group(2)
                if ".path" in body:
                    continue  # local path dependency
                version = "*"
                url_m = re.search(r"\.url\s*=\s*\"([^\"]+)\"", body)
                if url_m:
                    tail = url_m.group(1).rstrip("/").split("/")[-1]
                    version = tail if re.match(r"^[\w.\-]+$", tail) else "*"
                deps.append(DependencySpec(
                    name=name,
                    version_spec=version,
                    manager=PackageManager.ZIGMOD,
                    language="zig",
                    source_file=str(path),
                    kind="runtime",
                ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_rebar_config(self, path: Path) -> List[DependencySpec]:
        """rebar.config — Erlang terms; {deps, […]}, profile-test deps."""
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            blocks = ((_extract_erlang_list(content, r"\{deps"), "runtime"),
                      (_extract_erlang_list(content, r"\{\s*test\s*,\s*\[\s*\{deps"), "test"))
            for body, kind in blocks:
                if not body:
                    continue
                seen = set()
                for entry in _split_erlang_list(body):
                    spec = _parse_rebar_dep_entry(entry)
                    if spec is None:
                        continue
                    name, version = spec
                    if name in seen:
                        continue
                    seen.add(name)
                    deps.append(DependencySpec(
                        name=name,
                        version_spec=version,
                        manager=PackageManager.REBAR3,
                        language="erlang",
                        source_file=str(path),
                        kind=kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_opam(self, path: Path) -> List[DependencySpec]:
        """*.opam — depends:/depopts: with {with-test}/{build} filters."""
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            for field in ("depends", "depopts"):
                # Non-greedy to the first ']' — opam version constraints use
                # braces, so ']' ends the block (single- or multi-line).
                block = re.search(rf"^{field}\s*:\s*\[(.*?)\]",
                                  content, re.DOTALL | re.MULTILINE)
                if not block:
                    continue
                for name, filters in re.findall(
                        r"\"([a-zA-Z0-9_.\-]+)\"\s*(?:\{([^}]*)\})?", block.group(1)):
                    kind = "optional"
                    if field == "depends":
                        ftext = filters or ""
                        if "with-test" in ftext or "with-doc" in ftext:
                            kind = "test"
                        elif "build" in ftext:
                            kind = "dev"
                        else:
                            kind = "runtime"
                    deps.append(DependencySpec(
                        name=name,
                        version_spec="*",
                        manager=PackageManager.OPAM,
                        language="ocaml",
                        source_file=str(path),
                        kind=kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_rockspec(self, path: Path) -> List[DependencySpec]:
        """*.rockspec — Lua table; dependencies/build/test_dependencies."""
        deps = []
        try:
            content = path.read_text(encoding="utf-8")
            for section, kind in (("dependencies", "runtime"),
                                  ("build_dependencies", "dev"),
                                  ("test_dependencies", "test")):
                block = re.search(
                    rf"{section}\s*=\s*\{{(.*?)\}}", content, re.DOTALL)
                if not block:
                    continue
                for entry in re.findall(r"[\"']([^\"']+)[\"']", block.group(1)):
                    parts = entry.split()
                    if not parts or parts[0] == "lua":
                        continue
                    deps.append(DependencySpec(
                        name=parts[0],
                        version_spec=" ".join(parts[1:]) or "*",
                        manager=PackageManager.LUAROCKS,
                        language="lua",
                        source_file=str(path),
                        kind=kind,
                    ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_cpanfile(self, path: Path) -> List[DependencySpec]:
        """cpanfile — Perl DSL; requires/test_requires/on 'phase' blocks."""
        deps = []
        try:
            phase = "runtime"
            for raw in path.read_text(encoding="utf-8").splitlines():
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                phase_match = re.match(r"^on\s+['\"](\w+)['\"]", stripped)
                if phase_match:
                    phase = phase_match.group(1)
                m = re.match(
                    r"^(?:test_requires|requires|recommends|suggests)\s+['\"]([\w:]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?",
                    stripped)
                if not m:
                    continue
                name, version = m.group(1), m.group(2) or "*"
                if stripped.startswith("test_requires"):
                    kind = "test"
                elif phase == "develop":
                    kind = "dev"
                elif phase == "test":
                    kind = "test"
                else:
                    kind = "runtime"
                deps.append(DependencySpec(
                    name=name.replace("::", "-"),
                    version_spec=version or "*",
                    manager=PackageManager.CPAN,
                    language="perl",
                    source_file=str(path),
                    kind=kind,
                ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps

    def _parse_agda_lib(self, path: Path) -> List[DependencySpec]:
        """*.agda-lib — line format; depend: lists library names (G3)."""
        deps = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("depend:"):
                    for lib in line.partition(":")[2].split():
                        deps.append(DependencySpec(
                            name=lib,
                            version_spec="*",
                            manager=PackageManager.AGDA,
                            language="agda",
                            source_file=str(path),
                            kind="runtime",
                        ))
        except Exception as e:
            logger.debug(f"Failed to parse {path}: {e}")
        return deps
