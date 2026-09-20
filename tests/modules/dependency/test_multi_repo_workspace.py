"""Tests for multi-repo workspace identity: manifest ordering (T1),
dep-scoped env discovery (T4), and the workspace_manifests table (T8)."""
import json
from pathlib import Path

import pytest

from batho.modules.dependency.manifest_parser import ManifestParser, DependencySpec
from batho.modules.dependency.indexer import (
    DependencyIndexer, build_workspace_manifest_rows,
)
from batho.modules.dependency.resolution_cache import ResolutionCache
from batho.modules.extraction.scope_manager import ScopeManager
from batho.core.schemas import PackageManager


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _pyproject(name: str, version: str = "1.0.0") -> str:
    return f'[project]\nname = "{name}"\nversion = "{version}"\n'


def _package_json(name: str, version: str = "0.0.0", **extra) -> str:
    return json.dumps({"name": name, "version": version, **extra})


# ----------------------------------------------------------------------
# T1 — depth-major manifest ordering
# ----------------------------------------------------------------------

class TestDepthMajorOrdering:

    def test_root_pyproject_beats_nested_package_json(self, tmp_path):
        _write(tmp_path / "pyproject.toml", _pyproject("batho", "1.4.2"))
        _write(tmp_path / "docs-site" / "package.json", _package_json("docs-site"))

        meta = ManifestParser.detect_project_metadata(tmp_path)
        assert (meta.manager, meta.name, meta.version) == (
            PackageManager.PIP, "batho", "1.4.2")

    def test_nested_only_manifest_still_detected(self, tmp_path):
        _write(tmp_path / "sub" / "package.json", _package_json("inner", "2.0.0"))

        meta = ManifestParser.detect_project_metadata(tmp_path)
        assert (meta.manager, meta.name) == (PackageManager.NPM, "inner")

    def test_root_beats_nested_regardless_of_type(self, tmp_path):
        _write(tmp_path / "package.json", _package_json("rootpkg"))
        _write(tmp_path / "sub" / "pyproject.toml", _pyproject("inner"))

        meta = ManifestParser.detect_project_metadata(tmp_path)
        assert (meta.manager, meta.name) == (PackageManager.NPM, "rootpkg")

    def test_same_depth_type_priority_unchanged(self, tmp_path):
        _write(tmp_path / "package.json", _package_json("rootpkg"))
        _write(tmp_path / "pyproject.toml", _pyproject("pypkg"))

        meta = ManifestParser.detect_project_metadata(tmp_path)
        assert (meta.manager, meta.name) == (PackageManager.NPM, "rootpkg")

    def test_nameless_root_manifest_falls_through(self, tmp_path):
        _write(tmp_path / "pyproject.toml", "[build-system]\nrequires = []\n")
        _write(tmp_path / "sub" / "package.json", _package_json("inner"))

        meta = ManifestParser.detect_project_metadata(tmp_path)
        assert (meta.manager, meta.name) == (PackageManager.NPM, "inner")

    def test_same_depth_same_type_deterministic(self, tmp_path):
        _write(tmp_path / "a" / "package.json", _package_json("pkg-a"))
        _write(tmp_path / "b" / "package.json", _package_json("pkg-b"))

        results = {ManifestParser.detect_project_metadata(tmp_path).name
                   for _ in range(5)}
        assert results == {"pkg-a"}  # lexicographic tiebreak, stable

    def test_no_manifests_returns_none(self, tmp_path):
        assert ManifestParser.detect_project_metadata(tmp_path) is None

    def test_detect_workspace_packages_map(self, tmp_path):
        _write(tmp_path / "pyproject.toml", _pyproject("batho", "1.4.2"))
        _write(tmp_path / "docs-site" / "package.json", _package_json("docs-site"))

        packages = ManifestParser.detect_workspace_packages(tmp_path)
        assert set(packages) == {".", "docs-site"}
        assert packages["."][0].manager == PackageManager.PIP
        assert packages["docs-site"][0].manager == PackageManager.NPM

    def test_detect_workspace_packages_same_dir_multi_manifest(self, tmp_path):
        _write(tmp_path / "package.json", _package_json("rootpkg"))
        _write(tmp_path / "pyproject.toml", _pyproject("pypkg"))

        packages = ManifestParser.detect_workspace_packages(tmp_path)
        assert set(packages) == {"."}
        assert {p.manager for p in packages["."]} == {
            PackageManager.NPM, PackageManager.PIP}


# ----------------------------------------------------------------------
# T4 — dep-scoped toolchain discovery
# ----------------------------------------------------------------------

def _indexer(root: Path) -> DependencyIndexer:
    return DependencyIndexer(root, ScopeManager(), cfg={})


def _dep(source_file: Path | None, language: str = "javascript") -> DependencySpec:
    return DependencySpec(
        name="react", version_spec="^19.0.0",
        manager=PackageManager.NPM if language == "javascript" else PackageManager.PIP,
        language=language,
        source_file=str(source_file) if source_file else "",
    )


class TestDepScopedEnvironments:

    def test_nested_node_modules_wins(self, tmp_path):
        nm = tmp_path / "docs-site" / "node_modules"
        nm.mkdir(parents=True)
        dep = _dep(tmp_path / "docs-site" / "package.json")

        idx = _indexer(tmp_path)
        assert idx._env_for_dep(dep, {}) == nm

    def test_root_node_modules_for_root_manifest(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        dep = _dep(tmp_path / "package.json")

        assert _indexer(tmp_path)._env_for_dep(dep, {}) == nm

    def test_walk_reaches_root_from_nested(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        dep = _dep(tmp_path / "docs-site" / "package.json")

        assert _indexer(tmp_path)._env_for_dep(dep, {}) == nm

    def test_nearest_env_wins_over_root(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        nested = tmp_path / "sub" / "node_modules"
        nested.mkdir(parents=True)
        dep = _dep(tmp_path / "sub" / "package.json")

        assert _indexer(tmp_path)._env_for_dep(dep, {}) == nested

    def test_python_venv_walk(self, tmp_path):
        venv = tmp_path / "svc" / "api" / ".venv"
        venv.mkdir(parents=True)
        dep = DependencySpec(
            name="pydantic", version_spec=">=2", manager=PackageManager.PIP,
            language="python",
            source_file=str(tmp_path / "svc" / "api" / "pyproject.toml"),
        )
        assert _indexer(tmp_path)._env_for_dep(dep, {}) == venv

    def test_no_env_returns_none(self, tmp_path):
        dep = _dep(tmp_path / "docs-site" / "package.json")
        assert _indexer(tmp_path)._env_for_dep(dep, {}) is None

    def test_missing_source_file_uses_root(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        dep = _dep(None)
        assert _indexer(tmp_path)._env_for_dep(dep, {}) == nm

    def test_env_memoized_per_manifest(self, tmp_path):
        (tmp_path / "sub" / "node_modules").mkdir(parents=True)
        idx = _indexer(tmp_path)
        cache = {}
        dep = _dep(tmp_path / "sub" / "package.json")
        first = idx._env_for_dep(dep, cache)
        (tmp_path / "sub" / "node_modules").rmdir()  # env vanishes
        assert idx._env_for_dep(dep, cache) == first  # cached

    def test_scope_key_distinguishes_dirs(self, tmp_path):
        idx = _indexer(tmp_path)
        root_dep = _dep(tmp_path / "package.json")
        nested_dep = _dep(tmp_path / "docs-site" / "package.json")
        assert idx._dep_scope_key(root_dep) == "."
        assert idx._dep_scope_key(nested_dep) == "docs-site"
        assert idx._dep_scope_key(_dep(None)) == ""

    def test_cache_scope_isolates_envs(self, tmp_path):
        cache = ResolutionCache(tmp_path / "cache")
        cache.put_symbols("react", "^19", "npm", {"react": ["a"]}, scope=".")
        cache.put_symbols("react", "^19", "npm", {"react": ["a", "b"]},
                          scope="docs-site")
        assert cache.get_symbols("react", "^19", "npm", scope=".") == {
            "react": ["a"]}
        assert cache.get_symbols("react", "^19", "npm",
                                 scope="docs-site") == {"react": ["a", "b"]}
        # unscoped lookups see neither (new key shape)
        assert cache.get_symbols("react", "^19", "npm") is None

    def test_introspect_npm_uses_scoped_env(self, tmp_path, monkeypatch):
        nm = tmp_path / "docs-site" / "node_modules"
        (nm / "react").mkdir(parents=True)
        idx = _indexer(tmp_path)

        seen = {}
        def fake_npm(name, version_spec=None, env_path=None, project_root=None):
            seen["nm"] = env_path
            return {name: ["realSymbol"]}
        monkeypatch.setattr(idx.introspector, "introspect_npm", fake_npm)

        dep = _dep(tmp_path / "docs-site" / "package.json")
        env = idx._env_for_dep(dep, {})
        result = idx._introspect_dep(dep, env)
        assert seen["nm"] == nm
        assert result == {"react": ["realSymbol"]}


# ----------------------------------------------------------------------
# T8 — kind tagging + workspace_manifests rows
# ----------------------------------------------------------------------

class TestDependencyKindTagging:

    def test_package_json_kinds(self, tmp_path):
        _write(tmp_path / "package.json", _package_json(
            "x", dependencies={"react": "^19"},
            devDependencies={"vitest": "^1"},
            optionalDependencies={"fsevents": "*"},
        ))
        deps = {d.name: d.kind
                for d in ManifestParser()._parse_package_json(
                    tmp_path / "package.json")}
        assert deps == {"react": "runtime", "vitest": "dev",
                        "fsevents": "optional"}

    def test_pyproject_optional_and_groups(self, tmp_path):
        _write(tmp_path / "pyproject.toml", """
[project]
name = "x"
version = "1.0.0"
dependencies = ["pydantic>=2"]

[project.optional-dependencies]
test = ["pytest>=8"]
docs = ["sphinx"]

[dependency-groups]
dev = ["ruff"]
""".lstrip())
        deps = {d.name: d.kind
                for d in ManifestParser()._parse_pyproject_toml(
                    tmp_path / "pyproject.toml")}
        assert deps == {"pydantic": "runtime", "pytest": "test",
                        "sphinx": "optional", "ruff": "dev"}

    def test_poetry_dev_and_group_deps(self, tmp_path):
        _write(tmp_path / "pyproject.toml", """
[tool.poetry]
name = "x"
version = "1.0.0"

[tool.poetry.dependencies]
requests = "^2"

[tool.poetry.dev-dependencies]
black = "^24"

[tool.poetry.group.test.dependencies]
pytest = "^8"
""".lstrip())
        deps = {d.name: d.kind
                for d in ManifestParser()._parse_pyproject_toml(
                    tmp_path / "pyproject.toml")}
        assert deps == {"requests": "runtime", "black": "dev",
                        "pytest": "test"}

    def test_requirements_filename_heuristic(self, tmp_path):
        for filename, expected in (("requirements.txt", "runtime"),
                                   ("requirements-dev.txt", "dev"),
                                   ("requirements-test.txt", "test")):
            p = _write(tmp_path / filename, "requests>=2\n")
            (dep,) = ManifestParser()._parse_requirements_txt(p)
            assert dep.kind == expected

    def test_cargo_dev_deps(self, tmp_path):
        _write(tmp_path / "Cargo.toml", """
[package]
name = "x"
version = "1.0.0"

[dependencies]
serde = "1"

[dev-dependencies]
criterion = "0.5"
""".lstrip())
        deps = {d.name: d.kind
                for d in ManifestParser()._parse_cargo_toml(
                    tmp_path / "Cargo.toml")}
        assert deps == {"serde": "runtime", "criterion": "dev"}

    def test_pom_test_scope(self, tmp_path):
        _write(tmp_path / "pom.xml", """
<project>
  <dependencies>
    <dependency><groupId>g</groupId><artifactId>a</artifactId>
      <version>1</version></dependency>
    <dependency><groupId>junit</groupId><artifactId>junit</artifactId>
      <scope>test</scope></dependency>
  </dependencies>
</project>
""".lstrip())
        deps = {d.name: d.kind
                for d in ManifestParser()._parse_pom_xml(tmp_path / "pom.xml")}
        assert deps == {"g:a": "runtime", "junit:junit": "test"}

    def test_gradle_test_deps(self, tmp_path):
        _write(tmp_path / "build.gradle",
               "implementation 'g:a:1'\ntestImplementation 'j:junit:4'\n")
        deps = {d.name: d.kind
                for d in ManifestParser()._parse_build_gradle(
                    tmp_path / "build.gradle")}
        assert deps == {"g:a": "runtime", "j:junit": "test"}


class TestWorkspaceManifestRows:

    def test_rows_cover_identities_and_deps(self, tmp_path):
        _write(tmp_path / "pyproject.toml",
               _pyproject("root-pkg", "2.0.0") +
               'dependencies = ["requests>=2"]\n')
        _write(tmp_path / "docs" / "package.json", _package_json(
            "docs", dependencies={"react": "^19"},
            devDependencies={"vitest": "^1"}))

        rows = build_workspace_manifest_rows(tmp_path)
        ws = [r for r in rows if r["scope"] == "workspace"]
        dep = [r for r in rows if r["scope"] == "dependency"]

        assert [(r["name"], r["kind"], r["manifest_dir"]) for r in ws] == [
            ("root-pkg", "primary", "."), ("docs", "subproject", "docs")]

        by_name = {r["name"]: r for r in dep}
        assert by_name["requests"]["kind"] == "runtime"
        assert by_name["requests"]["manifest_dir"] == "."
        assert by_name["vitest"]["kind"] == "dev"
        assert by_name["vitest"]["manifest_dir"] == "docs"
        assert by_name["react"]["source_file"] == "docs/package.json"

    def test_content_hash_tracks_manifest(self, tmp_path):
        p = _write(tmp_path / "pyproject.toml", _pyproject("x"))
        import hashlib
        expected = hashlib.sha256(p.read_bytes()).hexdigest()

        rows = build_workspace_manifest_rows(tmp_path)
        assert rows[0]["content_hash"] == expected

        _write(tmp_path / "pyproject.toml", _pyproject("x", "9.9.9"))
        rows2 = build_workspace_manifest_rows(tmp_path)
        assert rows2[0]["content_hash"] != expected

    def test_ipc_roundtrip(self, tmp_path):
        pytest.importorskip("pyarrow")
        from batho.modules.storage.arrow_bundle.schemas import (
            WORKSPACE_MANIFESTS_SCHEMA)
        from batho.modules.storage.arrow_bundle.writer import (
            write_simple_ipc, read_ipc_table)

        _write(tmp_path / "pyproject.toml", _pyproject("root-pkg"))
        rows = build_workspace_manifest_rows(tmp_path)

        out = tmp_path / "workspace_manifests.ipc"
        write_simple_ipc(rows, WORKSPACE_MANIFESTS_SCHEMA, out)
        table = read_ipc_table(out)

        assert table.num_rows == len(rows)
        back = table.to_pylist()
        assert back[0]["scope"] == "workspace"
        assert back[0]["name"] == "root-pkg"

    def test_reuses_preparsed_deps(self, tmp_path, monkeypatch):
        """``deps=`` short-circuits the second parse_manifests — build already
        parsed every manifest during dependency indexing (issue bd26f002244a)."""
        _write(tmp_path / "pyproject.toml", _pyproject("root-pkg"))

        calls = []
        monkeypatch.setattr(
            ManifestParser, "parse_manifests",
            lambda self, root: calls.append(str(root)) or [],
        )

        rows = build_workspace_manifest_rows(tmp_path, deps=[])
        assert calls == []  # reuse path never re-parses
        assert any(r["scope"] == "workspace" for r in rows)

        build_workspace_manifest_rows(tmp_path)
        assert len(calls) == 1  # deps omitted → parse runs as before


# ----------------------------------------------------------------------
# T3 — per-file identity resolution
# ----------------------------------------------------------------------

class TestPerFilePackageResolution:
    PKG_MAP = {
        ".": [{"manager": "pip", "name": "batho", "version": "1.4.2", "source": None}],
        "docs-site": [{"manager": "npm", "name": "docs-site", "version": "0.0.0"}],
    }

    def test_python_file_gets_pip_identity(self):
        from batho.modules.extraction.pipeline import _package_for_file
        pkg = _package_for_file("batho/mcp/server.py", self.PKG_MAP, {})
        assert (pkg["manager"], pkg["name"]) == ("pip", "batho")

    def test_ts_file_gets_npm_identity(self):
        from batho.modules.extraction.pipeline import _package_for_file
        pkg = _package_for_file("docs-site/src/app.ts", self.PKG_MAP, {})
        assert (pkg["manager"], pkg["name"]) == ("npm", "docs-site")

    def test_manifest_less_file_gets_nearest_ancestor(self, tmp_path):
        # .yaml has no manager — nearest ancestor (root pip) governs
        from batho.modules.extraction.pipeline import _package_for_file
        pkg = _package_for_file(
            "batho/core/data/popular-packages.yaml", self.PKG_MAP, {})
        assert pkg["manager"] == "pip"

    def test_ungoverned_file_gets_none(self):
        from batho.modules.extraction.pipeline import _package_for_file
        assert _package_for_file(
            "script.py", {"docs-site": [{"manager": "npm", "name": "d", "version": "0"}]},
            {}) is None

    def test_same_dir_polyglot_tiebreak(self, tmp_path):
        from batho.modules.extraction.pipeline import _package_for_file
        pkg_map = {".": [
            {"manager": "npm", "name": "rootpkg", "version": "1"},
            {"manager": "pip", "name": "pypkg", "version": "1"},
        ]}
        assert _package_for_file("main.py", pkg_map, {})["manager"] == "pip"
        assert _package_for_file("cli.ts", pkg_map, {})["manager"] == "npm"

    def test_memoized_per_dir(self):
        from batho.modules.extraction.pipeline import _package_for_file
        cache = {}
        _package_for_file("batho/a.py", self.PKG_MAP, cache)
        _package_for_file("batho/b.py", self.PKG_MAP, cache)
        assert list(cache) == ["batho"]  # one entry for the shared dir

    def test_cache_variant_fingerprint_changes_key(self):
        from batho.modules.storage.cache.unified_cache import build_ast_cache_variant
        base = build_ast_cache_variant(include_gaps=False, parsing_config={})
        fp1 = build_ast_cache_variant(include_gaps=False, parsing_config={},
                                      identity_fingerprint="abc")
        fp2 = build_ast_cache_variant(include_gaps=False, parsing_config={},
                                      identity_fingerprint="other")
        assert fp1 != base
        assert fp1 != fp2
        # same fingerprint → same variant (deterministic)
        assert build_ast_cache_variant(
            include_gaps=False, parsing_config={}, identity_fingerprint="abc"
        ) == fp1


# ----------------------------------------------------------------------
# T5 — language-namespaced external symbols
# ----------------------------------------------------------------------

class TestLanguageNamespacedResolution:

    def _sm(self):
        from batho.modules.extraction.scope_manager import ScopeManager
        sm = ScopeManager()
        sm.add_external_symbol("os", "batho stdlib python python os/", "module")
        sm.add_external_symbol("python:os", "batho stdlib python python os/", "module")
        sm.add_external_symbol("javascript:os", "batho npm nodejs 20.x os/", "module")
        return sm

    def test_hint_selects_language(self):
        sm = self._sm()
        assert sm.resolve_symbol("os", "python").symbol_id.endswith("python os/")
        assert sm.resolve_symbol("os", "javascript").symbol_id.endswith("nodejs 20.x os/")

    def test_sibling_language_fallback(self):
        sm = self._sm()
        assert sm.resolve_symbol("os", "typescript").symbol_id.endswith(
            "nodejs 20.x os/")

    def test_unhinted_uses_flat(self):
        sm = self._sm()
        assert sm.resolve_symbol("os").symbol_id.endswith("python os/")

    def test_strict_and_dotpath_thread_hint(self):
        sm = self._sm()
        sm.add_external_symbol("os.getcwd", "batho stdlib python python os/getcwd().", "function")
        sm.add_external_symbol("python:os.getcwd", "batho stdlib python python os/getcwd().", "function")
        assert sm.resolve_symbol_strict("os.getcwd", "python") is not None
        assert sm.resolve_symbol_dotpath("os.getcwd", "python").symbol_id.endswith(
            "os/getcwd().")

    def test_failed_lookup_keyed_by_hint(self):
        from batho.modules.extraction.scope_manager import ScopeManager
        sm = ScopeManager()
        assert sm.resolve_symbol_strict("ghost", "python") is None
        # flat lookup for the same name must not be poisoned by the hint miss
        sm.add_external_symbol("ghost", "batho pip x 1 x/", "module")
        assert sm.resolve_symbol_strict("ghost") is not None


# ----------------------------------------------------------------------
# T6 — config overrides
# ----------------------------------------------------------------------

class TestConfigOverrides:
    """T6: project.package override + workspace.manifest_dirs allow/deny."""

    def test_project_package_override_wins(self, tmp_path, monkeypatch):
        _write(tmp_path / "package.json", _package_json("nested", "9.9"))
        from batho.modules.dependency import manifest_parser as mp
        monkeypatch.setattr(
            mp.ManifestParser, "_workspace_config",
            classmethod(lambda cls: {"package": {
                "manager": "pip", "name": "overridden", "version": "3.0.0"}}),
        )
        meta = ManifestParser.detect_project_metadata(tmp_path)
        assert (meta.manager, meta.name, meta.version) == (
            PackageManager.PIP, "overridden", "3.0.0")

    def test_override_replaces_root_dir_in_map(self, tmp_path, monkeypatch):
        from batho.modules.dependency import manifest_parser as mp
        _write(tmp_path / "pyproject.toml", _pyproject("auto"))
        _write(tmp_path / "sub" / "package.json", _package_json("sub"))
        monkeypatch.setattr(
            mp.ManifestParser, "_workspace_config",
            classmethod(lambda cls: {"package": {
                "manager": "cargo", "name": "forced", "version": "2.0"}}),
        )
        packages = mp.ManifestParser.detect_workspace_packages(tmp_path)
        assert packages["."][0].name == "forced"
        assert packages["."][0].manager.value == "cargo"
        assert packages["sub"][0].name == "sub"

    def test_no_config_means_auto_detection(self, tmp_path, monkeypatch):
        from batho.modules.dependency import manifest_parser as mp
        _write(tmp_path / "pyproject.toml", _pyproject("auto"))
        monkeypatch.setattr(
            mp.ManifestParser, "_workspace_config",
            classmethod(lambda cls: {}),
        )
        meta = mp.ManifestParser.detect_project_metadata(tmp_path)
        assert meta.name == "auto"

    def test_manifest_dirs_deny_excludes_tree(self, tmp_path, monkeypatch):
        from batho.modules.dependency import manifest_parser as mp
        _write(tmp_path / "pyproject.toml", _pyproject("root"))
        _write(tmp_path / "docs-site" / "package.json", _package_json("docs"))
        monkeypatch.setattr(
            mp.ManifestParser, "_workspace_config",
            classmethod(lambda cls: {"manifest_dirs": {"deny": ["docs-site"]}}),
        )
        found = mp.ManifestParser._find_manifests(tmp_path, "package.json")
        assert found == []
        # root manifest unaffected by the deny rule
        assert mp.ManifestParser.detect_project_metadata(tmp_path).name == "root"

    def test_manifest_dirs_allowlist(self, tmp_path, monkeypatch):
        from batho.modules.dependency import manifest_parser as mp
        _write(tmp_path / "other" / "package.json", _package_json("other"))
        _write(tmp_path / "keep" / "package.json", _package_json("kept"))
        monkeypatch.setattr(
            mp.ManifestParser, "_workspace_config",
            classmethod(lambda cls: {"manifest_dirs": ["sub"]}),
        )
        # allowlist excludes both root and docs-site manifests
        assert mp.ManifestParser._find_manifests(tmp_path, "package.json") == []
