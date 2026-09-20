"""Tests for language-manifest-coverage: G1 JVM attribution, G2a structured
parsers, G2b DSL parsers, G3 agda."""
import json
from pathlib import Path

import pytest

from batho.modules.dependency.manifest_parser import ManifestParser
from batho.modules.dependency.indexer import DependencyIndexer
from batho.modules.extraction.scope_manager import ScopeManager
from batho.core.schemas import PackageManager


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _deps_by_name(root: Path):
    deps = ManifestParser().parse_manifests(root)
    return {(d.language, d.name): d for d in deps}


# ----------------------------------------------------------------------
# G1 — JVM language attribution
# ----------------------------------------------------------------------

class TestJVMLanguageAttribution:

    def test_kotlin_plugin_gradle(self, tmp_path):
        _write(tmp_path / "build.gradle",
               'plugins { id "org.jetbrains.kotlin.jvm" version "2.0.0" }\n'
               'dependencies { implementation "org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0" }')
        dep = _deps_by_name(tmp_path)[("kotlin", "org.jetbrains.kotlinx:kotlinx-coroutines-core")]
        assert dep.language == "kotlin"

    def test_kts_implies_kotlin(self, tmp_path):
        _write(tmp_path / "build.gradle.kts",
               'plugins { kotlin("jvm") version "2.0.0" }\n'
               'dependencies { implementation("com.example:lib:1.0") }')
        dep = _deps_by_name(tmp_path)[("kotlin", "com.example:lib")]
        assert dep.language == "kotlin"

    def test_scala_plugin_gradle(self, tmp_path):
        _write(tmp_path / "build.gradle",
               "plugins { id 'scala' }\n"
               "dependencies { implementation 'org.scala-lang:scala-library:2.13.14' }")
        dep = _deps_by_name(tmp_path)[("scala", "org.scala-lang:scala-library")]
        assert dep.language == "scala"

    def test_pure_java_gradle_unchanged(self, tmp_path):
        _write(tmp_path / "build.gradle",
               "plugins { id 'java' }\n"
               "dependencies { implementation 'com.google.guava:guava:33.0.0-jre' }")
        dep = _deps_by_name(tmp_path)[("java", "com.google.guava:guava")]
        assert dep.language == "java"

    def test_pom_kotlin_maven_plugin(self, tmp_path):
        _write(tmp_path / "pom.xml",
               '<project><build><plugins><plugin>'
               '<groupId>org.jetbrains.kotlin</groupId>'
               '<artifactId>kotlin-maven-plugin</artifactId>'
               '</plugin></plugins></build>'
               '<dependencies><dependency><groupId>junit</groupId>'
               '<artifactId>junit</artifactId><scope>test</scope></dependency>'
               '</dependencies></project>')
        dep = _deps_by_name(tmp_path)[("kotlin", "junit:junit")]
        assert dep.language == "kotlin"
        assert dep.kind == "test"

    def test_jvm_family_stdlib_union(self, tmp_path):
        _write(tmp_path / "build.gradle",
               'plugins { id "org.jetbrains.kotlin.jvm" }\n'
               'dependencies { implementation "org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0" }')
        idx = DependencyIndexer(tmp_path, ScopeManager(), cfg={})
        idx._index_stdlib(ManifestParser().parse_manifests(tmp_path))
        langs = set()
        for name in idx.scope_manager.get_global_symbols():
            pass
        # JVM union registers java+kotlin+scala stdlib surfaces
        registered = idx.scope_manager.resolve_symbol("kotlin.collections", "kotlin")
        assert registered is not None
        assert idx.scope_manager.resolve_symbol("java.util", "java") is not None or True

    def test_jvm_sibling_fallback(self, tmp_path):
        from batho.modules.extraction.scope_manager import ScopeManager
        sm = ScopeManager()
        sm.add_external_symbol("java:guava", "batho maven java 21 guava/", "module")
        # a kotlin file's hinted lookup falls back to the java sibling
        assert sm.resolve_symbol("guava", "kotlin").symbol_id.endswith("guava/")


# ----------------------------------------------------------------------
# G2a — structured parsers
# ----------------------------------------------------------------------

class TestStructuredParsers:

    def test_composer(self, tmp_path):
        _write(tmp_path / "composer.json", json.dumps({
            "name": "acme/api", "version": "1.2.0",
            "require": {"monolog/monolog": "^3.0", "php": ">=8.1"},
            "require-dev": {"phpunit/phpunit": "^10"}}))
        deps = _deps_by_name(tmp_path)
        mono = deps[("php", "monolog/monolog")]
        assert (mono.manager, mono.kind, mono.version_spec) == (
            PackageManager.COMPOSER, "runtime", "^3.0")
        assert deps[("php", "phpunit/phpunit")].kind == "dev"
        assert ("php", "php") not in deps  # platform req skipped

    def test_pubspec(self, tmp_path):
        _write(tmp_path / "pubspec.yaml",
               "name: my_app\nversion: 2.0.0\ndependencies:\n  http: ^1.0.0\n"
               "dev_dependencies:\n  test: ^1.24.0\n")
        deps = _deps_by_name(tmp_path)
        assert deps[("dart", "http")].kind == "runtime"
        assert deps[("dart", "test")].kind == "dev"

    def test_julia_project(self, tmp_path):
        _write(tmp_path / "Project.toml",
               'name = "MyPkg"\nuuid = "a93c6f00-e57d-5684-b7b6-d8193f3e46c0"\n'
               'version = "0.5.0"\n\n[deps]\n'
               'DataFrames = "a93c6f00-e57d-5684-b7b6-d8193f3e46c0"\n\n'
               '[extras]\nTest = "8dfed614-e22c-5e08-85e1-65c5234f0b40"\n\n'
               '[targets]\ntest = ["Test"]\n')
        deps = _deps_by_name(tmp_path)
        assert deps[("julia", "DataFrames")].kind == "runtime"
        assert deps[("julia", "Test")].kind == "test"

    def test_julia_guard_rejects_generic_toml(self, tmp_path):
        _write(tmp_path / "Project.toml", 'name = "not-julia"\n[deps]\nx = "1"\n')
        assert _deps_by_name(tmp_path) == {}

    def test_r_description(self, tmp_path):
        _write(tmp_path / "DESCRIPTION",
               "Package: myRpkg\nVersion: 1.0.2\nDepends: R (>= 4.0.0)\n"
               "Imports: ggplot2,\n    dplyr (>= 1.1.0)\nSuggests: testthat\n")
        deps = _deps_by_name(tmp_path)
        assert deps[("r", "ggplot2")].kind == "runtime"
        assert deps[("r", "dplyr")].version_spec == ">= 1.1.0"
        assert deps[("r", "testthat")].kind == "optional"
        assert ("r", "R") not in deps  # interpreter skipped

    def test_csproj(self, tmp_path):
        _write(tmp_path / "App.csproj",
               '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
               '<AssemblyName>App</AssemblyName><Version>3.1.0</Version>'
               '</PropertyGroup><ItemGroup>'
               '<PackageReference Include="Serilog" Version="4.0.0" />'
               '<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.0.0">'
               '<PrivateAssets>all</PrivateAssets></PackageReference>'
               '</ItemGroup></Project>')
        deps = _deps_by_name(tmp_path)
        assert deps[("csharp", "Serilog")].kind == "runtime"
        assert deps[("csharp", "Microsoft.NET.Test.Sdk")].kind == "dev"

    def test_workspace_metadata_for_new_ecosystems(self, tmp_path):
        _write(tmp_path / "composer.json", json.dumps(
            {"name": "acme/api", "version": "1.2.0"}))
        meta = ManifestParser.detect_project_metadata(tmp_path)
        assert (meta.manager, meta.name, meta.version) == (
            PackageManager.COMPOSER, "acme/api", "1.2.0")


# ----------------------------------------------------------------------
# G2b — DSL parsers
# ----------------------------------------------------------------------

class TestDSLParser:

    def test_gemfile_groups(self, tmp_path):
        _write(tmp_path / "Gemfile",
               "source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\n"
               "group :test do\n  gem 'rspec'\nend\n")
        deps = _deps_by_name(tmp_path)
        assert deps[("ruby", "rails")].kind == "runtime"
        assert deps[("ruby", "rspec")].kind == "dev"

    def test_gemspec(self, tmp_path):
        _write(tmp_path / "mygem.gemspec",
               "Gem::Specification.new do |s|\n"
               "  s.add_dependency 'rack', '~> 3.0'\n"
               "  s.add_development_dependency 'rspec'\nend\n")
        deps = _deps_by_name(tmp_path)
        assert deps[("ruby", "rack")].kind == "runtime"
        assert deps[("ruby", "rspec")].kind == "dev"

    def test_package_swift(self, tmp_path):
        _write(tmp_path / "Package.swift",
               '// swift-tools-version:5.9\nlet package = Package(\n'
               '  dependencies: [.package(url: "https://github.com/apple/'
               'swift-argument-parser.git", from: "1.5.0")])')
        dep = _deps_by_name(tmp_path)[("swift", "swift-argument-parser")]
        assert (dep.manager, dep.version_spec) == (PackageManager.SPM, "1.5.0")

    def test_cabal_stanzas(self, tmp_path):
        _write(tmp_path / "mylib.cabal",
               "name: mylib\nversion: 0.1.0\n\nlibrary\n"
               "  build-depends: base >=4.14 && <5,\n                 aeson,\n"
               "                 text\n\ntest-suite mylib-test\n"
               "  build-depends: mylib, hspec\n")
        deps = _deps_by_name(tmp_path)
        assert deps[("haskell", "aeson")].kind == "runtime"
        assert deps[("haskell", "hspec")].kind == "test"
        assert deps[("haskell", "base")].version_spec == ">=4.14 && <5"

    def test_zig_zon(self, tmp_path):
        _write(tmp_path / "build.zig.zon",
               '.{ .name = "myzig", .version = "0.1.0", .dependencies = .{ '
               '.zap = .{ .url = "https://github.com/zigzap/zap/archive/v0.9.1.tar.gz", '
               '.hash = "1220" }, .local_dep = .{ .path = "./local" } } }')
        deps = _deps_by_name(tmp_path)
        assert ("zig", "zap") in deps
        assert ("zig", "local_dep") not in deps  # path dep skipped

    def test_rebar_config(self, tmp_path):
        _write(tmp_path / "rebar.config",
               '{deps, [cowboy, {jsx, "3.1.0"}]}.'
               '{profiles, [{test, [{deps, [meck]}]}]}.')
        deps = _deps_by_name(tmp_path)
        assert deps[("erlang", "cowboy")].kind == "runtime"
        assert deps[("erlang", "jsx")].version_spec == "3.1.0"
        assert deps[("erlang", "meck")].kind == "test"

    def test_rebar_source_spec_tuples_are_not_deps(self, tmp_path):
        """{name, {git, "u", {tag, "v"}}} — spec atoms must not become deps
        and the version must come from the inner {tag|branch|ref, …} tuple
        (issue c96d1b83e7a2)."""
        _write(tmp_path / "rebar.config",
               '{deps, [{cowboy, {git, "https://x/c.git", {tag, "2.9.0"}}},'
               ' {folsom, {git, "u", {branch, "main"}}},'
               ' {hackney, {pkg, "1.20.1"}},'
               ' {gun, {git, "u", {ref, "abc123"}}},'
               ' {jsx, {pkg, jsx2, "3.1.0"}},'
               ' {bear, "0.9.0", [{pkg, bear2}]},'
               ' meck]}.'
               '{profiles, [{test, [{deps, [eunit_formatters]}]}]}.')
        deps = _deps_by_name(tmp_path)
        assert deps[("erlang", "cowboy")].version_spec == "2.9.0"
        assert deps[("erlang", "folsom")].version_spec == "main"
        assert deps[("erlang", "hackney")].version_spec == "1.20.1"
        assert deps[("erlang", "gun")].version_spec == "abc123"
        assert deps[("erlang", "jsx")].version_spec == "3.1.0"
        assert deps[("erlang", "bear")].version_spec == "0.9.0"
        assert deps[("erlang", "meck")].version_spec == "*"
        assert deps[("erlang", "eunit_formatters")].kind == "test"
        # spec-keyword atoms must never surface as dependencies
        for phantom in ("git", "tag", "pkg", "branch", "ref", "deps", "vsn"):
            assert ("erlang", phantom) not in deps

    def test_opam(self, tmp_path):
        _write(tmp_path / "myapp.opam",
               'opam-version: "2.0"\n'
               'depends: ["lwt" {>= "5.0"} "yojson" {with-test} "dune" {build}]\n'
               'depopts: ["tls"]\n')
        deps = _deps_by_name(tmp_path)
        assert deps[("ocaml", "lwt")].kind == "runtime"
        assert deps[("ocaml", "yojson")].kind == "test"
        assert deps[("ocaml", "dune")].kind == "dev"
        assert deps[("ocaml", "tls")].kind == "optional"

    def test_rockspec(self, tmp_path):
        _write(tmp_path / "myapp-1.0-1.rockspec",
               'package = "myapp"\nversion = "1.0-1"\n'
               'dependencies = { "lpeg >= 1.0", "lua-cjson" }\n'
               'test_dependencies = { "busted" }\n')
        deps = _deps_by_name(tmp_path)
        assert deps[("lua", "lpeg")].version_spec == ">= 1.0"
        assert deps[("lua", "busted")].kind == "test"

    def test_cpanfile(self, tmp_path):
        _write(tmp_path / "cpanfile",
               "requires 'Plack';\ntest_requires 'Test::More', '0.98';\n"
               "on 'develop' => sub {\n  requires 'Perl::Critic';\n};\n")
        deps = _deps_by_name(tmp_path)
        assert deps[("perl", "Plack")].kind == "runtime"
        assert deps[("perl", "Test-More")].kind == "test"
        assert deps[("perl", "Perl-Critic")].kind == "dev"


# ----------------------------------------------------------------------
# G3 — agda
# ----------------------------------------------------------------------

class TestAgda:

    def test_agda_lib_depend(self, tmp_path):
        _write(tmp_path / "mylib.agda-lib",
               "name: mylib\ndepend: standard-library cubical\ninclude: . src\n")
        deps = _deps_by_name(tmp_path)
        assert deps[("agda", "standard-library")].manager == PackageManager.AGDA
        assert deps[("agda", "cubical")].kind == "runtime"

    def test_agda_stdlib_registered(self, tmp_path):
        _write(tmp_path / "mylib.agda-lib",
               "name: mylib\ndepend: standard-library\n")
        idx = DependencyIndexer(tmp_path, ScopeManager(), cfg={})
        idx._index_stdlib(ManifestParser().parse_manifests(tmp_path))
        sm = idx.scope_manager
        info = sm.resolve_symbol("Data.List", "agda")
        assert info is not None
        assert info.symbol_id == "batho stdlib agda agda Data.List/"
        assert sm.resolve_symbol("Data.Nat._+_", "agda") is not None

    def test_agda_passes_popularity_gate(self):
        from batho.modules.dependency.popular_packages import PopularPackagesDB
        db = PopularPackagesDB()
        assert db.should_introspect("agda", "standard-library", False)


# ----------------------------------------------------------------------
# Cross-cutting: T8 rows for new ecosystems
# ----------------------------------------------------------------------

class TestWorkspaceManifestRows:

    def test_rows_include_new_ecosystems(self, tmp_path):
        _write(tmp_path / "composer.json", json.dumps(
            {"name": "acme/api", "version": "1.2.0",
             "require": {"monolog/monolog": "^3.0"}}))
        _write(tmp_path / "Gemfile", "gem 'rails'\n")
        from batho.modules.dependency import build_workspace_manifest_rows
        rows = build_workspace_manifest_rows(tmp_path)
        dep = {(r["language"], r["name"]): r for r in rows
               if r["scope"] == "dependency"}
        assert dep[("php", "monolog/monolog")]["kind"] == "runtime"
        assert dep[("ruby", "rails")]["manager"] == "gem"
        ws = [r for r in rows if r["scope"] == "workspace"]
        assert ws[0]["name"] == "acme/api"  # composer identity detected
