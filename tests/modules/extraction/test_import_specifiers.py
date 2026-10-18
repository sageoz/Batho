"""T12 — import-specifier resolution gaps.

Relative specifiers ('./', '../', '/') normalize onto real file paths;
extras-suffixed manifest names strip to the base package; brace groups
expand without emitting literal '{…}' candidates; scoped-package leaves
don't produce noise stubs; '::'-registered stdlib names resolve via
dot-normalized aliases.
"""

import tempfile
from pathlib import Path

from batho.modules.dependency.indexer import DependencyIndexer
from batho.modules.dependency.manifest_parser import DependencySpec, PackageManager
from batho.modules.extraction.extractor import _expand_import_targets
from batho.modules.extraction.scope_manager import ScopeManager


# ── _expand_import_targets ──────────────────────────────────────────────────

def test_group_expansion_no_brace_literals():
    targets = _expand_import_targets("std::io::{Read, Write}")
    assert "std.io.Read" in targets
    assert "std.io.Write" in targets
    assert not any("{" in t or "}" in t for t in targets)


def test_scoped_package_no_leaf_noise():
    targets = _expand_import_targets("@tauri-apps/plugin-dialog")
    assert "@tauri-apps/plugin-dialog" in targets
    assert "plugin-dialog" not in targets


def test_unscoped_slash_keeps_leaf_fallback():
    """'dir/file' leaf fallback survives for non-scoped specifiers."""
    targets = _expand_import_targets("lib/utils")
    assert "lib/utils" in targets
    assert "utils" in targets


def test_relative_specifier_passes_through():
    """'./x' / '../x' stay intact for the relative_path strategy."""
    assert "./sibling" in _expand_import_targets("./sibling")
    assert "../up/mod" in _expand_import_targets("../up/mod")


# ── DependencySpec extras normalization ─────────────────────────────────────

def _dep(name: str) -> DependencySpec:
    return DependencySpec(
        name=name, version_spec="*", manager=PackageManager.PIP,
        language="python", source_file="pyproject.toml",
    )


def test_extras_suffix_stripped():
    assert _dep("uvicorn[standard]").name == "uvicorn"


def test_extras_multi_stripped():
    assert _dep("requests[security,socks]").name == "requests"


def test_plain_name_untouched():
    assert _dep("fastapi").name == "fastapi"


# ── stdlib '::'→'.' alias registration ──────────────────────────────────────

def test_stdlib_double_colon_names_resolve_via_dot_alias():
    """rust/ruby '::'-style table entries must be reachable from
    dot-normalized refs ('std.io.Read' → registered 'std::io.Read')."""
    with tempfile.TemporaryDirectory() as tmp:
        sm = ScopeManager()
        idx = DependencyIndexer(Path(tmp), sm, cfg={})
        idx._index_stdlib(file_languages={"rust"})
        info = sm.resolve_symbol_dotpath("std.io.Read")
        assert info is not None
        assert "std::io" in info.symbol_id or "std" in info.symbol_id


def test_stdlib_dot_lookup_still_works():
    """Dot-native languages (python os.path) unaffected by the alias."""
    with tempfile.TemporaryDirectory() as tmp:
        sm = ScopeManager()
        idx = DependencyIndexer(Path(tmp), sm, cfg={})
        idx._index_stdlib(file_languages={"python"})
        info = sm.resolve_symbol_dotpath("os.path.join")
        assert info is not None


# ── assigned_inner DI-wrapper gating (5cdb9a304a5b) ─────────────────────────

def test_assigned_inner_only_for_known_di_wrappers():
    """Any single-arg call used to record ``assigned_inner``; only known DI
    wrappers (``Depends(f)``, ``Provide(f)``, ``inject(f)``) may do so now —
    otherwise ``x = list(User)`` types ``x`` as ``User`` downstream and
    fabricates ``x.foo()`` edges."""
    from batho.modules.extraction.submodules.parser_factory.factory import (
        get_extractor,
    )

    extractor = get_extractor("python")
    source = (
        b"def f():\n"
        b"    x = sorted(users)\n"
        b"    y = list(User)\n"
        b"    z = str(value)\n"
        b"    svc = Depends(get_x)\n"
        b"    svc2 = Depends(get_y())\n"
    )
    _, rels = extractor.parse_file("test.py", source)
    bound = {
        (r.metadata or {}).get("assigned_to"): (r.metadata or {})
        for r in rels
        if (r.metadata or {}).get("assigned_to")
    }
    # Ordinary single-arg calls: bound var recorded, inner must NOT be.
    assert "assigned_inner" not in bound.get("x", {})
    assert "assigned_inner" not in bound.get("y", {})
    assert "assigned_inner" not in bound.get("z", {})
    # DI wrapper: inner callee still recorded — both bare-identifier and
    # inner-call argument forms.
    assert bound.get("svc", {}).get("assigned_inner") == "get_x"
    assert bound.get("svc2", {}).get("assigned_inner") == "get_y"


# ── dep-branch '::'→'.' alias registration (EXT-01) ────────────────────────

def test_dep_symbols_register_dot_aliases():
    """EXT-01: dependency-introspection symbols must get the same '::'→'.'
    alias pair as the stdlib branch — a perl-style dep 'Try::Tiny' must
    resolve from the dot-normalized ref 'Try.Tiny.try'."""
    with tempfile.TemporaryDirectory() as tmp:
        sm = ScopeManager()
        idx = DependencyIndexer(Path(tmp), sm, cfg={})
        dep = DependencySpec(
            name="Try-Tiny", version_spec="1.0",
            manager=PackageManager.CPAN, language="perl",
            source_file="cpanfile",
        )
        idx._add_symbols_to_scope(dep, {"Try::Tiny": ["try", "catch"]})
        # '::'-native key works, and the dot-normalized alias resolves too
        assert sm.resolve_symbol_dotpath("Try::Tiny.try") is not None
        info = sm.resolve_symbol_dotpath("Try.Tiny.try")
        assert info is not None, "dep symbol unreachable via dot alias"
        assert "Try::Tiny" in info.symbol_id
