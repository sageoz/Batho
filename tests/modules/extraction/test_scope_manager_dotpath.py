"""Slash-subpath and hyphen/underscore variants in resolve_symbol_dotpath.

npm import specifiers address package roots plus a subpath
(`@tauri-apps/api/core`), while cargo manifests declare hyphenated crate
names that Rust code imports with underscores (`tauri_plugin_shell`). The
dotpath resolver must reach the registered external module in both cases.
"""

from batho.modules.extraction.package_roots import build_module_suffix_index
from batho.modules.extraction.scope_manager import ScopeManager


def _sm() -> ScopeManager:
    sm = ScopeManager()
    sm.add_external_symbol(
        name="@tauri-apps/api",
        symbol_id="batho npm @tauri-apps/api ^2.11.1 @tauri-apps/api/",
        symbol_type="module",
    )
    sm.add_external_symbol(
        name="zustand",
        symbol_id="batho npm zustand ^5.0.3 zustand/",
        symbol_type="module",
    )
    sm.add_external_symbol(
        name="tauri-plugin-shell",
        symbol_id="batho cargo tauri-plugin-shell 2 tauri-plugin-shell/",
        symbol_type="module",
    )
    sm.add_external_symbol(
        name="serde",
        symbol_id="batho cargo serde 1 serde/",
        symbol_type="module",
    )
    return sm


def test_scoped_npm_subpath_resolves_to_package_root():
    info = _sm().resolve_symbol_dotpath("@tauri-apps/api/core")
    assert info is not None
    assert info.is_external
    assert info.symbol_id.startswith("batho npm @tauri-apps/api")


def test_unscoped_npm_subpath_resolves():
    info = _sm().resolve_symbol_dotpath("zustand/middleware")
    assert info is not None
    assert "zustand" in info.symbol_id


def test_scope_alone_is_not_a_package():
    """`@tauri-apps` (scope only) must not collapse to a package match."""
    sm = _sm()
    sm.add_external_symbol(
        name="@tauri-apps",
        symbol_id="batho npm @tauri-apps-scope fake @tauri-apps/",
        symbol_type="module",
    )
    # With a scope-level module registered, deeper paths still prefer the
    # longest registered prefix (@tauri-apps/api) over the bare scope.
    info = sm.resolve_symbol_dotpath("@tauri-apps/api/core")
    assert "api" in info.symbol_id


def test_hyphen_underscore_crate_variant():
    info = _sm().resolve_symbol_dotpath("tauri_plugin_shell.process.CommandEvent")
    assert info is not None
    assert "tauri-plugin-shell" in info.symbol_id


def test_underscore_hyphen_reverse_variant():
    sm = _sm()
    sm.add_external_symbol(
        name="my_lib",
        symbol_id="batho cargo my_lib 1 my_lib/",
        symbol_type="module",
    )
    info = sm.resolve_symbol_dotpath("my-lib.helper")
    assert info is not None
    assert "my_lib" in info.symbol_id


def test_exact_match_still_wins():
    """Registered qualified symbols resolve without synthesis."""
    sm = _sm()
    sm.add_external_symbol(
        name="serde.Serialize",
        symbol_id="batho cargo serde 1 serde/Serialize.",
        symbol_type="external",
    )
    info = sm.resolve_symbol_dotpath("serde.Serialize")
    assert info.symbol_id == "batho cargo serde 1 serde/Serialize."


def test_unregistered_name_still_misses():
    assert _sm().resolve_symbol_dotpath("nonexistent/pkg/sub") is None
    assert _sm().resolve_symbol_dotpath("totally_unknown.thing") is None


def test_suffix_index_invalidated_on_late_registration():
    """EXT-09: the builder caches `_batho_module_suffix_index` lazily on the
    scope manager — any post-build registration must drop it, or the new
    module is invisible to suffix alignment for the rest of the run."""
    sm = ScopeManager()
    sm.define_symbol(
        "backend.app.mod", "batho pip x backend/app/mod.py::mod", "MODULE",
        is_global=True,
    )
    sm._batho_module_suffix_index = build_module_suffix_index(sm)
    assert sm._batho_module_suffix_index is not None

    sm.define_symbol(
        "other.app.mod", "batho pip x other/app/mod.py::mod", "MODULE",
        is_global=True,
    )
    assert sm._batho_module_suffix_index is None
    idx = build_module_suffix_index(sm)
    assert "other.app.mod" in idx["app.mod"]

    sm._batho_module_suffix_index = idx
    sm.add_external_symbol(
        name="late-pkg",
        symbol_id="batho npm late-pkg 1 late-pkg/",
        symbol_type="module",
    )
    assert sm._batho_module_suffix_index is None
