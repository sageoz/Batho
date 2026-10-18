"""T11 unit tests: derived import namespaces — marker chains, manifest roots,
suffix alignment, tsconfig aliases. No hardcoded directory names: every test
writes the evidence the derivation reads."""

from pathlib import Path

import pytest

from batho.modules.extraction import package_roots
from batho.modules.extraction.package_roots import (
    alias_candidates,
    build_module_suffix_index,
    derived_module_variants,
    manifest_roots_and_aliases,
    marker_chain_parts,
    reset_caches,
)


@pytest.fixture(autouse=True)
def _fresh_caches():
    reset_caches()
    yield
    reset_caches()


def _mkpkg(root: Path, rel: str, content: str = "") -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


class TestMarkerChain:
    def test_backend_app_layout(self, tmp_path: Path):
        """sageoz shape: backend/ markerless, app/ marked → strip backend."""
        for d in ("backend/app", "backend/app/services"):
            _mkpkg(tmp_path, f"{d}/__init__.py")
        parts = ["backend", "app", "services", "graph_service"]
        assert marker_chain_parts(tmp_path, parts) == ["app", "services", "graph_service"]

    def test_src_layout(self, tmp_path: Path):
        """src-layout resolves by markers too — no special-casing."""
        _mkpkg(tmp_path, "src/mypkg/__init__.py")
        parts = ["src", "mypkg", "mod"]
        assert marker_chain_parts(tmp_path, parts) == ["mypkg", "mod"]

    def test_flat_layout_no_change(self, tmp_path: Path):
        _mkpkg(tmp_path, "pkg/__init__.py")
        parts = ["pkg", "mod"]
        assert marker_chain_parts(tmp_path, parts) is None  # identical

    def test_no_markers_returns_none(self, tmp_path: Path):
        """Namespace dirs with zero markers → no chain (suffix fallback's job)."""
        parts = ["a", "b", "mod"]
        assert marker_chain_parts(tmp_path, parts) is None

    def test_chain_stops_at_first_unmarked(self, tmp_path: Path):
        """`x/y/z/mod.py` where only z is marked → import path z.mod."""
        (tmp_path / "x/y/z/__init__.py").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "x/y/z/__init__.py").write_text("", encoding="utf-8")
        parts = ["x", "y", "z", "mod"]
        assert marker_chain_parts(tmp_path, parts) == ["z", "mod"]

    def test_root_level_file(self, tmp_path: Path):
        assert marker_chain_parts(tmp_path, ["mod"]) is None

    def test_init_stripped_package_dir(self, tmp_path: Path):
        """backend/app/__init__.py arrives as ["backend", "app"] (the init
        stem popped by the caller): `app` is a package dir, not a file stem,
        so its marker must be checked too."""
        _mkpkg(tmp_path, "backend/app/__init__.py")
        assert marker_chain_parts(tmp_path, ["backend", "app"]) == ["app"]

    def test_init_stripped_full_chain_no_change(self, tmp_path: Path):
        """Fully marked init-stripped chain is already the import path."""
        _mkpkg(tmp_path, "backend/__init__.py")
        _mkpkg(tmp_path, "backend/app/__init__.py")
        assert marker_chain_parts(tmp_path, ["backend", "app"]) is None

    def test_init_stripped_root_package_no_change(self, tmp_path: Path):
        """Root-level package __init__ → parts=["app"]; nothing to strip."""
        _mkpkg(tmp_path, "app/__init__.py")
        assert marker_chain_parts(tmp_path, ["app"]) is None

    def test_unmarked_dir_tail_still_treated_as_stem(self, tmp_path: Path):
        """A dir-named tail WITHOUT a marker (namespace pkg / JS index dir)
        keeps stem semantics — no marker means it can't bound a chain."""
        (tmp_path / "backend/web").mkdir(parents=True)
        assert marker_chain_parts(tmp_path, ["backend", "web"]) is None

    def test_init_stripped_deep_chain(self, tmp_path: Path):
        """backend/app/services/__init__.py → services is the package."""
        _mkpkg(tmp_path, "backend/app/__init__.py")
        _mkpkg(tmp_path, "backend/app/services/__init__.py")
        parts = ["backend", "app", "services"]
        assert marker_chain_parts(tmp_path, parts) == ["app", "services"]


class TestManifestRoots:
    def test_pyproject_package_dir(self, tmp_path: Path):
        _mkpkg(tmp_path, "pyproject.toml",
               '[tool.setuptools.package-dir]\n"" = "backend"\n')
        roots, aliases = manifest_roots_and_aliases(tmp_path)
        assert ("backend",) in roots

    def test_pyproject_find_where(self, tmp_path: Path):
        _mkpkg(tmp_path, "pyproject.toml",
               '[tool.setuptools.packages.find]\nwhere = ["lib", "contrib"]\n')
        roots, _ = manifest_roots_and_aliases(tmp_path)
        assert ("lib",) in roots and ("contrib",) in roots

    def test_pyproject_nested_package_dir(self, tmp_path: Path):
        _mkpkg(tmp_path, "pyproject.toml",
               '[tool.setuptools.package-dir]\n"mypkg" = "src/mypkg"\n')
        roots, _ = manifest_roots_and_aliases(tmp_path)
        assert ("src", "mypkg") in roots

    def test_setup_cfg_where(self, tmp_path: Path):
        _mkpkg(tmp_path, "setup.cfg",
               "[options.packages.find]\nwhere =\n  backend\n")
        roots, _ = manifest_roots_and_aliases(tmp_path)
        assert ("backend",) in roots

    def test_cargo_src_root(self, tmp_path: Path):
        """Cargo.toml at mycrate/ → crate root is mycrate/src (cargo spec)."""
        _mkpkg(tmp_path, "mycrate/Cargo.toml", '[package]\nname = "x"\n')
        roots, _ = manifest_roots_and_aliases(tmp_path)
        assert ("mycrate", "src") in roots

    def test_go_mod_alias(self, tmp_path: Path):
        """`module <path>` declares a ref-prefix → dir-prefix rewrite."""
        _mkpkg(tmp_path, "svc/go.mod", "module github.com/acme/svc\n")
        roots, aliases = manifest_roots_and_aliases(tmp_path)
        assert ("github.com.acme.svc", "svc") in aliases

    def test_go_mod_at_repo_root(self, tmp_path: Path):
        """go.mod at the repo root maps the module prefix onto '' — the
        most common Go layout."""
        _mkpkg(tmp_path, "go.mod", "module github.com/acme/svc\n")
        _, aliases = manifest_roots_and_aliases(tmp_path)
        assert ("github.com.acme.svc", "") in aliases

    def test_tsconfig_base_url_and_paths(self, tmp_path: Path):
        _mkpkg(tmp_path, "tsconfig.json",
               '{"compilerOptions": {"baseUrl": ".", '
               '"paths": {"@/*": ["./src/*"], "~/lib": ["./src/lib"]}}}')
        roots, aliases = manifest_roots_and_aliases(tmp_path)
        assert ("@/", "src/") in aliases
        assert ("~/lib", "src/lib") in aliases

    def test_tsconfig_nested(self, tmp_path: Path):
        _mkpkg(tmp_path, "web/tsconfig.json",
               '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}')
        _, aliases = manifest_roots_and_aliases(tmp_path)
        assert ("@/", "web/src/") in aliases

    def test_vendored_dirs_not_scanned(self, tmp_path: Path):
        """Manifests inside vendored/dependency dirs describe external
        packages — their roots/aliases must not rewrite repo refs."""
        for d in ("node_modules", "vendor", "dist", "venv"):
            _mkpkg(tmp_path, f"{d}/tsconfig.json",
                   '{"compilerOptions": {"baseUrl": "src", '
                   '"paths": {"@/*": ["./src/*"]}}}')
        _mkpkg(tmp_path, "build/Cargo.toml", '[package]\nname = "x"\n')
        roots, aliases = manifest_roots_and_aliases(tmp_path)
        assert aliases == []
        assert roots == []

    def test_vendored_go_mod_alias_skipped(self, tmp_path: Path):
        """A vendored go.mod `module` line must not leak an alias pair."""
        _mkpkg(tmp_path, "vendor/go.mod", "module example.com/ext\n")
        _, aliases = manifest_roots_and_aliases(tmp_path)
        assert aliases == []

    def test_vendored_skip_keeps_real_manifests(self, tmp_path: Path):
        """Root manifest is scanned first; sibling dirs still count."""
        _mkpkg(tmp_path, "node_modules/tsconfig.json",
               '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}')
        _mkpkg(tmp_path, "tsconfig.json",
               '{"compilerOptions": {"paths": {"~/*": ["./lib/*"]}}}')
        _mkpkg(tmp_path, "web/tsconfig.json",
               '{"compilerOptions": {"paths": {"#/*": ["./app/*"]}}}')
        roots, aliases = manifest_roots_and_aliases(tmp_path)
        assert ("~/", "lib/") in aliases
        assert ("#/", "web/app/") in aliases
        assert not any(pat == "@/" for pat, _ in aliases)

    def test_symlinked_first_level_dir_not_scanned(self, tmp_path: Path):
        """EXT-10: a first-level dir symlinked to outside the repo must not
        leak its manifests into this repo's root/alias derivation."""
        repo = tmp_path / "repo"
        repo.mkdir()
        outside = tmp_path / "outside"
        _mkpkg(outside, "tsconfig.json",
               '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}')
        (repo / "linked").symlink_to(outside, target_is_directory=True)
        _, aliases = manifest_roots_and_aliases(repo)
        assert not any(pat == "@/" for pat, _ in aliases)

    def test_pyproject_find_where_string(self, tmp_path: Path):
        """EXT-13: setuptools accepts `where = "src"` (string) — must not be
        iterated character-by-character into one-letter roots."""
        _mkpkg(tmp_path, "pyproject.toml",
               '[tool.setuptools.packages.find]\nwhere = "src"\n')
        roots, _ = manifest_roots_and_aliases(tmp_path)
        assert ("src",) in roots
        assert not any(r in (("s",), ("r",), ("c",)) for r in roots)

    def test_tsconfig_url_string_survives_comment_strip(self, tmp_path: Path):
        """EXT-15: `//` inside a quoted value is data, not a comment — the
        old regex ate `"https://x"` down to `"https:` breaking JSON."""
        _mkpkg(tmp_path, "tsconfig.json",
               '{\n'
               '  // real comment\n'
               '  "compilerOptions": {\n'
               '    "paths": {\n'
               '      "@/*": ["./src/*"],\n'
               '      "base": ["https://example.com/lib"]  /* block */\n'
               '    }\n'
               '  }\n'
               '}')
        _, aliases = manifest_roots_and_aliases(tmp_path)
        assert ("@/", "src/") in aliases


class TestDerivedVariants:
    def test_marker_variant(self, tmp_path: Path):
        _mkpkg(tmp_path, "backend/app/__init__.py")
        vs = derived_module_variants(tmp_path, ["backend", "app", "mod"])
        assert ["app", "mod"] in vs

    def test_manifest_variant(self, tmp_path: Path):
        _mkpkg(tmp_path, "pyproject.toml",
               '[tool.setuptools.package-dir]\n"" = "backend"\n')
        vs = derived_module_variants(tmp_path, ["backend", "app", "mod"])
        assert ["app", "mod"] in vs

    def test_no_evidence_no_variants(self, tmp_path: Path):
        assert derived_module_variants(tmp_path, ["a", "b", "c"]) == []

    def test_init_stripped_variant(self, tmp_path: Path):
        """backend/app/__init__.py → parts=["backend","app"]: the package
        spelling `app` must be registered as a variant."""
        _mkpkg(tmp_path, "backend/app/__init__.py")
        vs = derived_module_variants(tmp_path, ["backend", "app"])
        assert ["app"] in vs

    def test_dedup_marker_and_manifest(self, tmp_path: Path):
        _mkpkg(tmp_path, "backend/app/__init__.py")
        _mkpkg(tmp_path, "pyproject.toml",
               '[tool.setuptools.package-dir]\n"" = "backend"\n')
        vs = derived_module_variants(tmp_path, ["backend", "app", "mod"])
        assert vs == [["app", "mod"]]


class _FakeInfo:
    def __init__(self, key, symbol_type="MODULE", external=False):
        self.symbol_id = key
        self.symbol_type = symbol_type
        self.is_external = external


class _FakeScope:
    def __init__(self, entries):
        self._entries = entries

    def iter_global_symbols(self):
        return iter(self._entries)


class TestSuffixIndex:
    def test_suffix_alignment(self):
        sm = _FakeScope([("backend.app.services.errors",
                          _FakeInfo("backend.app.services.errors"))])
        idx = build_module_suffix_index(sm)
        assert idx["app.services.errors"] == {"backend.app.services.errors"}
        assert idx["services.errors"] == {"backend.app.services.errors"}
        assert idx["errors"] == {"backend.app.services.errors"}

    def test_ambiguous_suffix_kept_distinct(self):
        sm = _FakeScope([
            ("a.pkg.mod", _FakeInfo("a.pkg.mod")),
            ("b.pkg.mod", _FakeInfo("b.pkg.mod")),
        ])
        idx = build_module_suffix_index(sm)
        assert idx["pkg.mod"] == {"a.pkg.mod", "b.pkg.mod"}  # caller skips len>1

    def test_external_modules_excluded(self):
        sm = _FakeScope([
            ("fastapi.routing", _FakeInfo("x", external=True)),
            ("backend.app.mod", _FakeInfo("backend.app.mod")),
        ])
        idx = build_module_suffix_index(sm)
        assert "fastapi.routing" not in idx


class TestAliasCandidates:
    def test_wildcard_rewrite(self):
        out = alias_candidates(
            "@/components/x.Button", [("@/", "src/")]
        )
        assert "src.components.x.Button" in out

    def test_exact_alias(self):
        out = alias_candidates("~/lib.util.f", [("~/lib", "src/lib")])
        assert "src.lib.util.f" in out

    def test_no_match_passthrough(self):
        out = alias_candidates("app.x.Y", [("@/", "src/")])
        assert out == ["app.x.Y"]

    def test_exact_alias_segment_boundary(self):
        """Exact key `app` must not rewrite `apple.x` — prefix alone is not
        a match; only a full name or a `.`/`/` boundary counts."""
        pairs = [("app", "src/app")]
        assert alias_candidates("apple.x.Y", pairs) == ["apple.x.Y"]
        assert "src.app.x.Y" in alias_candidates("app.x.Y", pairs)
        assert "src.app.x.Y" in alias_candidates("app/x/Y", pairs)
        assert "src.app" in alias_candidates("app", pairs)

    def test_go_module_alias_boundary(self):
        """Dotted go-module pair still rewrites on a segment boundary."""
        pairs = [("github.com.acme.svc", "svc")]
        assert "svc.foo.Bar" in alias_candidates(
            "github.com.acme.svc.foo.Bar", pairs
        )
        assert alias_candidates("github.com.acme.svcx.foo", pairs) == [
            "github.com.acme.svcx.foo"
        ]

    def test_wildcard_verbatim_append_unchanged(self):
        """Wildcard pairs (sub ends with "/") keep verbatim-append semantics
        — `app*` legitimately matches `apple`."""
        out = alias_candidates("apple.x", [("app", "src/")])
        assert "src.le.x" in out

    def test_root_manifest_alias_no_leading_dot(self):
        """A root-level manifest pair (sub == "") must produce a rooted
        candidate, not a leading-dot name whose empty first segment can
        never match the suffix index."""
        pairs = [("github.com.acme.svc", "")]
        out = alias_candidates("github.com.acme.svc.pkg.foo.Bar", pairs)
        assert "pkg.foo.Bar" in out
        assert not any(c.startswith(".") or not c for c in out)
        # Exact module match rewrites to nothing — emit no empty candidate.
        assert alias_candidates("github.com.acme.svc", pairs) == [
            "github.com.acme.svc"
        ]



class TestCacheResetOrdering:
    """EXT-04: package-root evidence caches are process-wide and must be
    reset BEFORE build_graph's results loop consumes them — pre-fix the
    reset ran inside _register_project_symbols, after first consumers."""

    def test_reset_runs_before_first_evidence_read(self, tmp_path: Path):
        import batho.modules.graph.builder.codegraph as cg

        from batho.orchestrator.build import BuildOptions, run_build

        root = tmp_path / "repo"
        _mkpkg(root, "outer/pkg/mod.py", "def func():\n    return 1\n")

        events: list[str] = []
        real_reset = package_roots.reset_caches
        real_marker = package_roots._dir_has_marker
        real_variants = package_roots.derived_module_variants

        def spy_reset():
            events.append("reset")
            return real_reset()

        def spy_marker(d):
            events.append("marker")
            return real_marker(d)

        def spy_variants(r, parts):
            events.append("variants")
            return real_variants(r, parts)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cg, "reset_package_root_caches", spy_reset)
        monkeypatch.setattr(package_roots, "_dir_has_marker", spy_marker)
        monkeypatch.setattr(
            package_roots, "derived_module_variants", spy_variants
        )
        try:
            assert run_build(BuildOptions(root=root, force_full=True)).success
        finally:
            monkeypatch.undo()

        assert "reset" in events, "build_graph never reset the caches"
        first_reset = events.index("reset")
        consumers = [
            i for i, e in enumerate(events) if e in ("marker", "variants")
        ]
        assert consumers, "no evidence consumer observed"
        assert first_reset < min(consumers), (
            f"evidence consumed before reset: {events[:12]}"
        )

    def test_config_roots_do_not_leak_across_roots(self, tmp_path: Path):
        """Root A's `indexer.package_roots` must not shape root B's module
        registrations — the configured_roots() read must be config-derived
        per call, never process-global (EXT-12)."""
        from batho.orchestrator.build import BuildOptions, run_build
        from batho.modules.storage.arrow_bundle.reader import (
            BathoBundleReader,
        )

        root_a = tmp_path / "a"
        _mkpkg(root_a, "outer/a1.py", "def one():\n    return 1\n")
        (root_a / "batho.yaml").write_text(
            "indexer:\n  package_roots:\n    - outer\n", encoding="utf-8"
        )
        assert run_build(BuildOptions(root=root_a, force_full=True)).success

        # B: two same-stem modules make the bare `x` suffix ambiguous —
        # if A's ("outer",) root leaked, `x.thing` would falsely resolve to
        # outer.x.thing via the registered `x` variant.
        root_b = tmp_path / "b"
        _mkpkg(root_b, "outer/x.py", "def thing():\n    return 1\n")
        _mkpkg(root_b, "other/x.py", "def other_thing():\n    return 2\n")
        _mkpkg(root_b, "user.py",
               "import x\n\ndef use():\n    return x.thing()\n")
        assert run_build(BuildOptions(root=root_b, force_full=True)).success

        reader = BathoBundleReader(root_b / ".batho" / "artifact")
        unresolved = [
            r["target_id"]
            for r in reader._get_table("rels_views").to_pylist()
            if str(r["target_id"]).startswith("unresolved:")
        ]
        assert any("x.thing" in t for t in unresolved), (
            "x.thing should stay unresolved (ambiguous `x` module); "
            "a leaked configured root resolved it to outer.x.thing"
        )
