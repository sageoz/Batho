"""Tests for universal dependency introspection (dep-01 … dep-17).

Scenario:
    Every manifest manager must have a real (or explicitly no) introspector,
    the skip-when-env-missing policy must hold, and no {name: [name]} fallback
    stubs may be registered.

Execution Flow:
    1. Build fixture package trees under tmp_path (never the developer's real
       home / package stores).
    2. Exercise each introspector through its uniform signature.
    3. Exercise the indexer skip policy and routing table.

Expectations:
    - Missing env/store → {} and deps_skipped_no_env increments.
    - Present env → real symbols extracted from fixture files.
    - Routing table covers every PackageManager; no fallback stubs anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from batho.core.schemas import PackageManager
from batho.modules.dependency.indexer import (
    DependencyIndexer,
    _ENV_MATRIX,
    _LANGUAGE_INTROSPECTORS,
)
from batho.modules.dependency.introspector import (
    ThirdPartyIntrospector, _is_safe_dependency_name,
)
from batho.modules.extraction.scope_manager import ScopeManager


@pytest.fixture
def introspector() -> ThirdPartyIntrospector:
    return ThirdPartyIntrospector()


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    """Never touch the developer's real package stores (D7)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    for var in (
        "GEM_HOME", "BUNDLE_PATH", "NUGET_PACKAGES", "PUB_CACHE",
        "JULIA_DEPOT_PATH", "R_LIBS_USER", "ZIG_GLOBAL_CACHE_DIR",
        "OPAMROOT", "OPAMSWITCH", "LUAROCKS", "PERL5LIB",
        "CARGO_HOME", "GOPATH", "MAVEN_REPO", "M2_REPO", "GRADLE_USER_HOME",
    ):
        monkeypatch.delenv(var, raising=False)
    return home


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# dep-17 — routing table completeness
# ----------------------------------------------------------------------

class TestRoutingTable:

    def test_every_manager_has_env_spec_or_is_unrouted(self):
        """Managers either have an env spec or route to nothing by design."""
        no_store_managers = {PackageManager.AGDA, PackageManager.UNKNOWN}
        for manager in PackageManager:
            if manager in no_store_managers:
                assert manager not in _ENV_MATRIX
            else:
                assert manager in _ENV_MATRIX, f"{manager} missing from _ENV_MATRIX"

    def test_every_routed_language_has_a_method(self, introspector):
        for language, route in _LANGUAGE_INTROSPECTORS.items():
            if route is None:
                continue
            assert hasattr(introspector, route), (
                f"{language} routes to missing method {route}"
            )

    def test_no_ecosystem_languages_are_explicit(self):
        for lang in ("bash", "verilog", "c", "cpp", "objc", "agda"):
            assert _LANGUAGE_INTROSPECTORS[lang] is None

    def test_hack_routes_to_composer(self):
        assert _LANGUAGE_INTROSPECTORS["hack"] == "introspect_composer"

    def test_no_fallback_stubs_in_source(self):
        import batho.modules.dependency.indexer as idx_mod
        source = Path(idx_mod.__file__).read_text(encoding="utf-8")
        assert "{dep.name: [dep.name]}" not in source
        assert "return {dep.name: [dep.name]}" not in source


# ----------------------------------------------------------------------
# dep-01 — skip policy
# ----------------------------------------------------------------------

class TestSkipPolicy:

    def _indexer(self, root: Path, cfg: dict | None = None) -> DependencyIndexer:
        return DependencyIndexer(root, ScopeManager(), cfg=cfg or {})

    def test_python_dep_without_venv_is_skipped(self, tmp_path):
        """The headline requirement: no venv → skip, no stub, no cache."""
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        idx = self._indexer(tmp_path)
        from batho.modules.dependency.manifest_parser import DependencySpec
        dep = DependencySpec(
            name="requests", version_spec=">=2", manager=PackageManager.PIP,
            language="python", source_file="pyproject.toml",
        )
        idx._index_dependencies_parallel([dep])

        assert idx.stats.deps_skipped_no_env == 1
        assert idx.stats.deps_introspected == 0
        assert idx.scope_manager.global_symbol_count == 0
        assert idx.cache.get_symbols("requests", ">=2", "pip", scope=".") is None

    def test_npm_dep_without_node_modules_is_skipped(self, tmp_path):
        from batho.modules.dependency.manifest_parser import DependencySpec
        idx = self._indexer(tmp_path)
        dep = DependencySpec(
            name="react", version_spec="^19", manager=PackageManager.NPM,
            language="javascript", source_file="package.json",
        )
        idx._index_dependencies_parallel([dep])
        assert idx.stats.deps_skipped_no_env == 1

    def test_store_dep_without_store_is_skipped(self, tmp_path):
        from batho.modules.dependency.manifest_parser import DependencySpec
        idx = self._indexer(tmp_path)
        dep = DependencySpec(
            name="serde", version_spec="1", manager=PackageManager.CARGO,
            language="rust", source_file="Cargo.toml",
        )
        # No CARGO_HOME, no ~/.cargo (isolated home) → skip
        idx._index_dependencies_parallel([dep])
        assert idx.stats.deps_skipped_no_env == 1

    def test_skip_missing_env_false_attempts_introspection(self, tmp_path):
        from batho.modules.dependency.manifest_parser import DependencySpec
        idx = self._indexer(tmp_path, cfg={
            "introspection": {"skip_missing_env": False},
        })
        dep = DependencySpec(
            name="react", version_spec="^19", manager=PackageManager.NPM,
            language="javascript", source_file="package.json",
        )
        idx._index_dependencies_parallel([dep])
        # Attempted (no env, but not skipped) → counted as no_symbols
        assert idx.stats.deps_skipped_no_env == 0
        assert idx.stats.deps_no_symbols == 1

    def test_no_ecosystem_dep_is_classified_not_stubbed(self, tmp_path):
        from batho.modules.dependency.manifest_parser import DependencySpec
        idx = self._indexer(tmp_path, cfg={
            # full_scan bypasses the popular-DB gate (agda is not in the DB)
            "introspection": {"full_scan": True},
        })
        dep = DependencySpec(
            name="some-crate", version_spec="1", manager=PackageManager.AGDA,
            language="agda", source_file="some.agda-lib",
        )
        idx._index_dependencies_parallel([dep])
        assert idx.stats.deps_no_ecosystem == 1
        assert idx.stats.deps_introspected == 0
        assert idx.scope_manager.global_symbol_count == 0

    def test_manager_config_override_disables_introspection(self, tmp_path):
        from batho.modules.dependency.manifest_parser import DependencySpec
        (tmp_path / "vendor" / "symfony" / "yaml").mkdir(parents=True)
        idx = self._indexer(tmp_path, cfg={
            "introspection": {"managers": {"composer": False}},
        })
        dep = DependencySpec(
            name="symfony/yaml", version_spec="^7", manager=PackageManager.COMPOSER,
            language="php", source_file="composer.json",
        )
        idx._index_dependencies_parallel([dep])
        assert idx.stats.deps_introspected == 0
        assert idx.stats.deps_skipped_no_env == 0  # disabled, not skipped

    def test_unknown_manager_override_warns_and_is_ignored(self, tmp_path):
        import structlog
        from batho.modules.dependency.manifest_parser import DependencySpec
        idx = self._indexer(tmp_path, cfg={
            "introspection": {"managers": {"not-a-manager": False}},
        })
        normalized = idx._validate_manager_overrides(
            {"managers": {"not-a-manager": False, "pip": True}}
        )
        assert normalized == {"pip": True}


# ----------------------------------------------------------------------
# dep-03 … dep-15 — introspectors (fixture trees, uniform signature)
# ----------------------------------------------------------------------

class TestIntrospectGem:

    def test_extracts_modules_classes_defs(self, tmp_path, introspector):
        lib = tmp_path / "gems" / "nokogiri-1.16.0" / "lib"
        _write(lib / "nokogiri.rb", """
module Nokogiri
  class HTML
    def self.parse; end
    def at_css; end
  end
end
""")
        result = introspector.introspect_gem(
            "nokogiri", "1.16.0", tmp_path)
        assert "Nokogiri" in result["nokogiri"]
        assert "HTML" in result["nokogiri"]
        assert "parse" in result["nokogiri"]
        assert "at_css" in result["nokogiri"]

    def test_missing_env_returns_empty(self, introspector):
        assert introspector.introspect_gem("nokogiri") == {}

    def test_gem_home_env_resolution(self, tmp_path, monkeypatch, introspector):
        gemdir = tmp_path / "gemhome"
        _write(gemdir / "gems" / "rack-3.0.0" / "lib" / "rack.rb",
               "module Rack\n  class Request\n  end\nend\n")
        monkeypatch.setenv("GEM_HOME", str(gemdir))
        result = introspector.introspect_gem("rack")
        assert "Request" in result["rack"]


class TestIntrospectComposer:

    def test_extracts_psr4_classes(self, tmp_path, introspector):
        pkg = tmp_path / "vendor" / "symfony" / "yaml"
        _write(pkg / "composer.json",
               '{"autoload": {"psr-4": {"Symfony\\\\Component\\\\Yaml\\\\": "src/"}}}')
        _write(pkg / "src" / "Yaml.php",
               "<?php\nnamespace Symfony\\Component\\Yaml;\nclass Yaml {}\n")
        result = introspector.introspect_composer("symfony/yaml", None, tmp_path / "vendor")
        assert "Yaml" in result["symfony/yaml"]
        assert "Symfony\\Component\\Yaml\\Yaml" in result["symfony/yaml"]

    def test_missing_vendor_returns_empty(self, introspector):
        assert introspector.introspect_composer("symfony/yaml") == {}

    def test_hack_package_uses_same_route(self, tmp_path, introspector):
        pkg = tmp_path / "vendor" / "hhvm" / "hacklib"
        _write(pkg / "src" / "H.php", "<?php\nclass H {}\n")
        result = introspector.introspect_composer("hhvm/hacklib", None, tmp_path / "vendor")
        assert "H" in result["hhvm/hacklib"]


class TestIntrospectNuget:

    def test_extracts_types_from_xml_docs(self, tmp_path, introspector):
        pkg = tmp_path / "packages" / "newtonsoft.json" / "13.0.3"
        _write(pkg / "lib" / "net6.0" / "Newtonsoft.Json.xml",
               '<?xml version="1.0"?>\n<doc><members>'
               '<member name="T:Newtonsoft.Json.JsonConvert">'
               "</member></members></doc>\n")
        result = introspector.introspect_nuget(
            "Newtonsoft.Json", "13.0.3", tmp_path / "packages")
        assert "JsonConvert" in result["Newtonsoft.Json"]
        assert "Newtonsoft.Json.JsonConvert" in result["Newtonsoft.Json"]

    def test_nuspec_fallback(self, tmp_path, introspector):
        pkg = tmp_path / "packages" / "serilog" / "4.0.0"
        _write(pkg / "serilog.nuspec",
               '<?xml version="1.0"?>\n<dependencies>'
               '<dependency id="Serilog.Sinks.Console" version="6.0.0" />'
               "</dependencies>\n")
        result = introspector.introspect_nuget("Serilog", None, tmp_path / "packages")
        assert "Serilog.Sinks.Console" in result["Serilog"]

    def test_missing_store_returns_empty(self, introspector):
        assert introspector.introspect_nuget("Newtonsoft.Json") == {}


class TestIntrospectPub:

    def test_package_config_json_resolution(self, tmp_path, introspector):
        pc = tmp_path / ".dart_tool" / "package_config.json"
        pkg_root = tmp_path / "third_party" / "http"
        _write(pkg_root / "lib" / "http.dart",
               "class Request {}\nmixin Parseable {}\nString read() => '';\n")
        _write(pc, '{"packages": [{"name": "http", "rootUri": "../third_party/http"}]}')
        result = introspector.introspect_pub("http", None, None, tmp_path)
        assert "Request" in result["http"]
        assert "Parseable" in result["http"]
        assert "read" in result["http"]

    def test_pub_cache_fallback(self, tmp_path, introspector):
        cache = tmp_path / "pubcache"
        _write(cache / "hosted" / "pub.dev" / "http-1.2.0" / "lib" / "http.dart",
               "class Client {}\n")
        result = introspector.introspect_pub("http", None, cache, None)
        assert "Client" in result["http"]

    def test_missing_everything_returns_empty(self, introspector):
        assert introspector.introspect_pub("http") == {}


class TestIntrospectJulia:

    def test_export_list_is_public_api(self, tmp_path, introspector):
        src = tmp_path / "packages" / "Example" / "abc12" / "src"
        _write(src / "Example.jl",
               "module Example\nexport hello, goodbye\n"
               "hello() = 1\nstruct Thing\nend\nend\n")
        result = introspector.introspect_julia("Example", None, tmp_path)
        assert set(result["Example"]) == {"hello", "goodbye"}

    def test_no_exports_falls_back_to_defs(self, tmp_path, introspector):
        src = tmp_path / "packages" / "Example" / "abc12" / "src"
        _write(src / "Example.jl",
               "module Example\nstruct Thing\nend\nfunction run(x)\nend\nend\n")
        result = introspector.introspect_julia("Example", None, tmp_path)
        assert "Thing" in result["Example"]
        assert "run" in result["Example"]

    def test_missing_depot_returns_empty(self, introspector):
        assert introspector.introspect_julia("Example") == {}


class TestIntrospectCran:

    def test_namespace_exports(self, tmp_path, introspector):
        pkg = tmp_path / "renv" / "library" / "R-4.3" / "x86_64" / "dplyr"
        _write(pkg / "NAMESPACE", "export(mutate, select)\nexportClasses(DataFrame)\n")
        result = introspector.introspect_cran("dplyr", None, None, tmp_path)
        assert "mutate" in result["dplyr"]
        assert "select" in result["dplyr"]
        assert "DataFrame" in result["dplyr"]

    def test_export_pattern_enumerates_sources(self, tmp_path, introspector):
        pkg = tmp_path / "renv" / "library" / "R-4.3" / "x86_64" / "tools"
        _write(pkg / "NAMESPACE", 'exportPattern("^[^\\\\.]")\n')
        _write(pkg / "R" / "utils.R", "flatten <- function(x) x\n")
        result = introspector.introspect_cran("tools", None, None, tmp_path)
        assert "flatten" in result["tools"]

    def test_missing_library_returns_empty(self, introspector):
        assert introspector.introspect_cran("dplyr") == {}


class TestIntrospectCabal:

    def test_exposed_modules(self, tmp_path, introspector):
        cabal = tmp_path / "packages" / "hackage.haskell.org" / "text" / "2.1"
        _write(cabal / "text.cabal",
               "library\n  exposed-modules: Data.Text\n    Data.Text.IO\n")
        result = introspector.introspect_cabal("text", None, tmp_path)
        assert "Data.Text" in result["text"]
        assert "Data.Text.IO" in result["text"]

    def test_missing_store_returns_empty(self, introspector):
        assert introspector.introspect_cabal("text") == {}


class TestIntrospectSpm:

    def test_public_declarations_only(self, tmp_path, introspector):
        sources = tmp_path / "checkouts" / "alamofire" / "Sources"
        _write(sources / "AF.swift",
               "public struct AF {}\npublic func request() {}\n"
               "internal func helper() {}\nstruct Hidden {}\n")
        result = introspector.introspect_spm("alamofire", None, tmp_path / "checkouts")
        assert "AF" in result["alamofire"]
        assert "request" in result["alamofire"]
        assert "helper" not in result["alamofire"]
        assert "Hidden" not in result["alamofire"]

    def test_missing_checkouts_returns_empty(self, introspector):
        assert introspector.introspect_spm("alamofire") == {}


class TestIntrospectZigmod:

    def test_vendored_deps(self, tmp_path, introspector):
        dep = tmp_path / ".zigmod" / "deps" / "zqtt"
        _write(dep / "build.zig.zon", '.name = .zqtt\n')
        _write(dep / "src" / "lib.zig",
               "pub fn connect() void {}\npub const Client = struct {};\n")
        result = introspector.introspect_zigmod("zqtt", None, None, tmp_path)
        assert "connect" in result["zqtt"]
        assert "Client" in result["zqtt"]

    def test_cache_match_by_zon_name(self, tmp_path, introspector):
        cache = tmp_path / "zigcache"
        _write(cache / "p" / "abc123" / "build.zig.zon", '.name = .zqtt\n')
        _write(cache / "p" / "abc123" / "lib.zig", "pub fn poll() void {}\n")
        result = introspector.introspect_zigmod("zqtt", None, cache / "p", None)
        assert "poll" in result["zqtt"]

    def test_missing_everything_returns_empty(self, introspector):
        assert introspector.introspect_zigmod("zqtt") == {}


class TestIntrospectRebar3:

    def test_export_lists(self, tmp_path, introspector):
        src = tmp_path / "_build" / "default" / "lib" / "proper" / "src"
        _write(src / "proper.erl",
               "-module(proper).\n-export([quickcheck/2, forall/3]).\n")
        result = introspector.introspect_rebar3("proper", None, tmp_path / "_build" / "default" / "lib")
        assert "proper" in result["proper"]
        assert "quickcheck" in result["proper"]
        assert "forall" in result["proper"]

    def test_missing_build_returns_empty(self, introspector):
        assert introspector.introspect_rebar3("proper") == {}


class TestIntrospectOpam:

    def test_mli_interfaces(self, tmp_path, introspector):
        lib = tmp_path / "opam" / "default" / "lib" / "lwt"
        _write(lib / "lwt.mli",
               "val sleep : float -> unit Lwt.t\ntype 'a t\nmodule Lwt_list : sig end\nexception Canceled\n")
        result = introspector.introspect_opam("lwt", None, tmp_path / "opam")
        assert "sleep" in result["lwt"]
        assert "t" in result["lwt"]
        assert "Lwt_list" in result["lwt"]
        assert "Canceled" in result["lwt"]

    def test_ml_fallback_when_no_mli(self, tmp_path, introspector):
        lib = tmp_path / "opam" / "default" / "lib" / "cmdliner"
        _write(lib / "cmdliner.ml", "let exit = 0\nlet term = 1\n")
        result = introspector.introspect_opam("cmdliner", None, tmp_path / "opam")
        assert "exit" in result["cmdliner"]
        assert "term" in result["cmdliner"]

    def test_missing_root_returns_empty(self, introspector):
        assert introspector.introspect_opam("lwt") == {}


class TestIntrospectLuarocks:

    def test_module_table_functions(self, tmp_path, introspector):
        share = tmp_path / "luarocks" / "share" / "lua" / "5.4"
        _write(share / "lpeg.lua",
               "local M = {}\nfunction M.match(p, s) end\n"
               "function M.compile(p) end\nreturn M\n")
        result = introspector.introspect_luarocks("lpeg", None, tmp_path / "luarocks")
        assert "match" in result["lpeg"]
        assert "compile" in result["lpeg"]

    def test_missing_tree_returns_empty(self, introspector):
        assert introspector.introspect_luarocks("lpeg") == {}


class TestIntrospectCpan:

    def test_package_and_subs(self, tmp_path, introspector):
        root = tmp_path / "perl5" / "lib" / "perl5"
        _write(root / "Try" / "Tiny.pm",
               "package Try::Tiny;\nsub try {}\nsub catch {}\nsub _private {}\n")
        result = introspector.introspect_cpan("Try::Tiny", None, root)
        assert "Try::Tiny" in result["Try::Tiny"]
        assert "try" in result["Try::Tiny"]
        assert "catch" in result["Try::Tiny"]
        assert "_private" not in result["Try::Tiny"]

    def test_dist_form_name_resolves_module_file(self, tmp_path, introspector):
        """cpanfile stores Try::Tiny as Try-Tiny; the .pm path must still be
        found (issue d53a8e27c4f6)."""
        root = tmp_path / "perl5" / "lib" / "perl5"
        _write(root / "Try" / "Tiny.pm",
               "package Try::Tiny;\nsub try {}\nsub catch {}\n")
        result = introspector.introspect_cpan("Try-Tiny", None, root)
        assert result
        syms = next(iter(result.values()))
        assert "try" in syms and "catch" in syms

    def test_missing_root_returns_empty(self, introspector):
        assert introspector.introspect_cpan("Try::Tiny") == {}


# ----------------------------------------------------------------------
# dep-16 — Gradle store in jar introspection
# ----------------------------------------------------------------------

class TestIntrospectJarGradle:

    def _make_sources_jar(self, path: Path, entries: list[str]) -> None:
        import zipfile
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            for e in entries:
                zf.writestr(e, "// source")

    def test_gradle_store_sources_jar(self, tmp_path, monkeypatch, introspector):
        store = tmp_path / "gradle" / "caches" / "modules-2" / "files-2.1"
        self._make_sources_jar(
            store / "org.apache.commons" / "commons-lang3" / "3.14.0" / "abc" / "commons-lang3-3.14.0-sources.jar",
            ["org/apache/commons/lang3/StringUtils.java",
             "org/apache/commons/lang3/ArrayUtils.java"],
        )
        monkeypatch.setenv("GRADLE_USER_HOME", str(tmp_path / "gradle"))
        result = introspector.introspect_jar("org.apache.commons:commons-lang3", "3.14")
        assert "StringUtils" in result["org.apache.commons:commons-lang3"]
        assert "ArrayUtils" in result["org.apache.commons:commons-lang3"]

    def test_gradle_store_binary_jar_fallback(self, tmp_path, monkeypatch, introspector):
        import zipfile
        store = tmp_path / "gradle" / "caches" / "modules-2" / "files-2.1"
        jar = store / "com.google.guava" / "guava" / "33.0.0" / "abc" / "guava-33.0.0.jar"
        jar.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(jar, "w") as zf:
            zf.writestr("com/google/common/collect/ImmutableList.class", b"\x00\x01")
            zf.writestr("com/google/common/base/Strings.class", b"\x00\x01")
        monkeypatch.setenv("GRADLE_USER_HOME", str(tmp_path / "gradle"))
        result = introspector.introspect_jar("com.google.guava:guava", "33")
        assert "ImmutableList" in result["com.google.guava:guava"]
        assert "Strings" in result["com.google.guava:guava"]

    def test_no_store_returns_empty_no_stub(self, introspector):
        result = introspector.introspect_jar("org.example:missing", "1.0")
        assert result == {}  # was {artifact: [artifactId]} before dep-02


# ----------------------------------------------------------------------
# dep-02 — cache version bump
# ----------------------------------------------------------------------

class TestCacheVersionBump:

    def test_v1_cache_entry_is_a_miss(self, tmp_path):
        """Old (v1-hash) cache files are never read after the version bump."""
        import hashlib
        import msgpack
        from batho.modules.dependency.resolution_cache import ResolutionCache

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        legacy_key = hashlib.sha256(b"react:^19:npm:.").hexdigest()[:16]
        legacy_file = cache_dir / "dep" / f"{legacy_key}.msgpack"
        legacy_file.parent.mkdir(exist_ok=True)
        legacy_file.write_bytes(msgpack.packb({"react": ["stub"]}))

        cache = ResolutionCache(cache_dir)
        assert cache.get_symbols("react", "^19", "npm", scope=".") is None


# ----------------------------------------------------------------------
# specs/full-scan-declared-introspection — full_scan contract + accounting
# ----------------------------------------------------------------------

def _accounted_total(stats) -> int:
    return (
        stats.deps_cached + stats.deps_gate_dropped + stats.deps_manager_disabled
        + stats.deps_no_ecosystem + stats.deps_skipped_no_env
        + stats.deps_introspected + stats.deps_no_symbols
    )


class TestFullScanContract:
    """FS-04 matrix: full_scan ∈ {true, false} × gate outcomes, the pinned
    bucket attribution, and the completeness invariant."""

    def _indexer(self, root: Path, cfg: dict | None = None) -> DependencyIndexer:
        return DependencyIndexer(root, ScopeManager(), cfg=cfg or {})

    def _dep(self, name: str = "requests", language: str = "python",
             manager=PackageManager.PIP) -> "DependencySpec":
        from batho.modules.dependency.manifest_parser import DependencySpec
        return DependencySpec(
            name=name, version_spec=">=1", manager=manager,
            language=language, source_file="pyproject.toml",
        )

    def _fake_python(self, monkeypatch, idx) -> dict:
        seen: dict = {}
        def fake(name, version_spec=None, env_path=None, project_root=None):
            seen[name] = env_path
            return {name: ["sym"]}
        monkeypatch.setattr(idx.introspector, "introspect_python", fake)
        return seen

    def _popular_python_package(self) -> str:
        from batho.modules.dependency.popular_packages import PopularPackagesDB
        db = PopularPackagesDB()
        for name in ("requests", "numpy", "pydantic", "pyyaml", "pytest"):
            if db.should_introspect("python", name, False):
                return name
        # fall back to the first DB member for python
        return next(iter(db._package_sets["python"]))

    NON_POPULAR = "zzz-definitely-not-a-popular-package"

    # -- full_scan: false → popular only --------------------------------

    def test_false_popular_dep_introspected(self, tmp_path, monkeypatch):
        (tmp_path / ".venv").mkdir()
        idx = self._indexer(tmp_path)
        self._fake_python(monkeypatch, idx)
        idx._index_dependencies_parallel([self._dep(self._popular_python_package())])
        assert idx.stats.deps_introspected == 1
        assert idx.stats.deps_gate_dropped == 0
        assert _accounted_total(idx.stats) == idx.stats.deps_unique == 1

    def test_false_non_popular_dep_gate_dropped(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        idx = self._indexer(tmp_path)
        idx._index_dependencies_parallel([self._dep(self.NON_POPULAR)])
        assert idx.stats.deps_gate_dropped == 1
        assert idx.stats.deps_introspected == 0
        assert _accounted_total(idx.stats) == idx.stats.deps_unique == 1

    def test_false_no_ecosystem_dep_counts_as_gate_dropped(self, tmp_path):
        """Pinned attribution (D4): gate ② runs before route ④, so a
        non-popular bash dep is gate_dropped when full_scan=false."""
        idx = self._indexer(tmp_path)
        idx._index_dependencies_parallel([self._dep(self.NON_POPULAR, language="bash")])
        assert idx.stats.deps_gate_dropped == 1
        assert idx.stats.deps_no_ecosystem == 0

    def test_gate_drop_debug_log_with_hint(self, tmp_path):
        import structlog.testing
        (tmp_path / ".venv").mkdir()
        idx = self._indexer(tmp_path)
        with structlog.testing.capture_logs() as logs:
            idx._index_dependencies_parallel([self._dep(self.NON_POPULAR)])
        events = [e for e in logs if e.get("event") == "introspection_gate_dropped"]
        assert events, "gate-drop debug log missing"
        assert "full_scan: true" in events[0]["hint"]

    def test_false_manager_disabled_popular_dep(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        idx = self._indexer(tmp_path, cfg={
            "introspection": {"managers": {"pip": False}},
        })
        idx._index_dependencies_parallel([self._dep(self._popular_python_package())])
        assert idx.stats.deps_manager_disabled == 1
        assert idx.stats.deps_introspected == 0
        assert _accounted_total(idx.stats) == idx.stats.deps_unique == 1

    # -- full_scan: true → all declared ---------------------------------

    def test_true_non_popular_dep_introspected(self, tmp_path, monkeypatch):
        (tmp_path / ".venv").mkdir()
        idx = self._indexer(tmp_path, cfg={"introspection": {"full_scan": True}})
        seen = self._fake_python(monkeypatch, idx)
        idx._index_dependencies_parallel([self._dep(self.NON_POPULAR)])
        assert idx.stats.deps_introspected == 1
        assert idx.stats.deps_gate_dropped == 0
        assert self.NON_POPULAR in seen

    def test_true_no_ecosystem_dep_classified(self, tmp_path):
        idx = self._indexer(tmp_path, cfg={"introspection": {"full_scan": True}})
        idx._index_dependencies_parallel([self._dep("anything", language="bash")])
        assert idx.stats.deps_no_ecosystem == 1
        assert idx.stats.deps_gate_dropped == 0

    def test_true_manager_disabled_dep(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        idx = self._indexer(tmp_path, cfg={
            "introspection": {"full_scan": True, "managers": {"pip": False}},
        })
        idx._index_dependencies_parallel([self._dep(self.NON_POPULAR)])
        assert idx.stats.deps_manager_disabled == 1

    def test_true_venvless_dep_skipped(self, tmp_path):
        idx = self._indexer(tmp_path, cfg={"introspection": {"full_scan": True}})
        idx._index_dependencies_parallel([self._dep(self._popular_python_package())])
        assert idx.stats.deps_skipped_no_env == 1
        assert idx.stats.deps_introspected == 0
        assert _accounted_total(idx.stats) == idx.stats.deps_unique == 1

    def test_cached_dep_accounted_once(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        idx = self._indexer(tmp_path)
        dep = self._dep(self._popular_python_package())
        idx.cache.put_symbols(
            dep.name, dep.version_spec, "pip", {dep.name: ["sym"]},
            scope=idx._dep_scope_key(dep),
        )
        idx._index_dependencies_parallel([dep])
        assert idx.stats.deps_cached == 1
        assert idx.stats.deps_introspected == 0
        assert _accounted_total(idx.stats) == idx.stats.deps_unique == 1

    def test_unique_count_not_raw_rows(self, tmp_path, monkeypatch):
        """Duplicate manifest rows collapse to one unique dep."""
        (tmp_path / ".venv").mkdir()
        idx = self._indexer(tmp_path, cfg={"introspection": {"full_scan": True}})
        self._fake_python(monkeypatch, idx)
        dep = self._dep(self._popular_python_package())
        idx._index_dependencies_parallel([dep, dep, dep])
        assert idx.stats.deps_unique == 1
        assert idx.stats.deps_declared == 0  # raw rows set by run(), not here
        assert _accounted_total(idx.stats) == 1

    # -- invariant --------------------------------------------------------

    def test_no_accounting_mismatch_logged_on_clean_run(self, tmp_path, monkeypatch):
        import structlog.testing
        (tmp_path / ".venv").mkdir()
        idx = self._indexer(tmp_path, cfg={"introspection": {"full_scan": True}})
        self._fake_python(monkeypatch, idx)
        with structlog.testing.capture_logs() as logs:
            idx._index_dependencies_parallel([
                self._dep(self._popular_python_package()),
                self._dep(self.NON_POPULAR),
                self._dep("x", language="bash"),
            ])
        assert not [e for e in logs if e.get("event") == "introspection_accounting_mismatch"]
        assert idx.stats.deps_unique == 3
        assert _accounted_total(idx.stats) == 3

    def test_invariant_canary_detects_uncounted_dep(self, tmp_path):
        """A stats object with an uncounted dep must trigger the warning —
        proves the assertion detects future gates added without a bucket."""
        import structlog.testing
        idx = self._indexer(tmp_path)
        idx.stats.deps_unique = 2
        idx.stats.deps_introspected = 1  # one dep unaccounted
        with structlog.testing.capture_logs() as logs:
            idx._assert_accounting_invariant()
        events = [e for e in logs if e.get("event") == "introspection_accounting_mismatch"]
        assert events and events[0]["unique"] == 2 and events[0]["accounted"] == 1


class TestFullScanSelfTest:
    """Full-repo integration: run the real gate against this repo's manifests.

    The modern form of the old T2 acceptance — with full_scan: true every
    unique declared dep reaches an outcome (attempted, classified, or
    skipped); gate drops must be zero. Environment-independent: deps whose
    env exists introspect for real, the rest land in skipped_no_env —
    either way every dep is accounted and nothing is gate-dropped.
    """

    @pytest.mark.timeout(120)  # CI: real .venv introspection on cold imports
    def test_repo_full_scan_attempts_all_declared(self):
        import tempfile
        from batho.core.config import get_config_with_root
        from batho.modules.dependency import build_dependency_index, ManifestParser

        root = Path(__file__).resolve().parents[3]
        cfg = dict(get_config_with_root(root).get("dependency", {}))
        cfg.setdefault("introspection", {})["full_scan"] = True
        manifests = ManifestParser().parse_manifests(root)
        unique = {(d.manager.value, d.name, d.version_spec) for d in manifests}

        with tempfile.TemporaryDirectory() as td:
            stats = build_dependency_index(
                root=root, scope_manager=ScopeManager(), cfg=cfg, cache_dir=td,
            )
        assert stats.deps_unique == len(unique) > 0
        assert stats.deps_gate_dropped == 0
        assert stats.deps_manager_disabled == 0
        assert _accounted_total(stats) == stats.deps_unique


class TestSafeDependencyName:
    """``_is_safe_dependency_name`` gates manifest-derived names before they
    reach subprocess argv or glob paths — a leading-dash name would parse as
    a flag in calls like ``ghc-pkg field <name>`` (issue 66778e44a336)."""

    def test_rejects_leading_dash(self):
        assert _is_safe_dependency_name("-x") is False
        assert _is_safe_dependency_name("--help") is False
        assert _is_safe_dependency_name("-") is False

    def test_rejects_traversal_null_and_absolute(self):
        assert _is_safe_dependency_name("../etc") is False
        assert _is_safe_dependency_name("a/../b") is False
        assert _is_safe_dependency_name("a\0b") is False
        assert _is_safe_dependency_name("/abs") is False
        assert _is_safe_dependency_name("a\\b") is False

    def test_accepts_normal_names(self):
        assert _is_safe_dependency_name("numpy") is True
        assert _is_safe_dependency_name("@scope/pkg") is True
        assert _is_safe_dependency_name("a.b-c_d") is True
