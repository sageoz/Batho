"""Unit tests for the language-aware re-export module.

Each fixture uses syntax verified against the official language reference
cited in batho/modules/graph/builder/reexports.py.
"""

from batho.modules.graph.builder import reexports
from batho.modules.graph.builder.reexports import (
    alias_export,
    iter_reexport_files,
    package_prefixes,
    register_package_reexports,
)


class FakeInfo:
    def __init__(self, symbol_id, symbol_type):
        self.symbol_id = symbol_id
        self.symbol_type = symbol_type


class FakeScope:
    """Minimal duck-typed ScopeManager for handler tests."""

    def __init__(self):
        self.symbols: dict[str, FakeInfo] = {}
        self.aliases: dict[str, FakeInfo] = {}

    def define_symbol(self, name, symbol_id, symbol_type, is_global=True):
        self.aliases[name] = FakeInfo(symbol_id, symbol_type)

    def resolve_symbol_dotpath(self, dotted):
        return self.symbols.get(dotted) or self.aliases.get(dotted)

    def resolve_symbol(self, name):
        return self.resolve_symbol_dotpath(name)

    def iter_global_symbols(self, prefix):
        for name, info in sorted(self.symbols.items()):
            if name.startswith(prefix):
                yield name, info


def _seed(scope: FakeScope, module: str, members: dict[str, str]):
    for name, sid in members.items():
        scope.symbols[f"{module}.{name}"] = FakeInfo(sid, "FUNCTION")


# ---------------------------------------------------------------------------
# iter_reexport_files / package_prefixes
# ---------------------------------------------------------------------------

def test_iter_reexport_files_dispatch():
    fp = {
        "/r/pk/__init__.py": ["pk"],
        "/r/pk/ts/index.ts": ["pk", "ts"],
        "/r/pk/rs/src/lib.rs": ["pk", "rs", "src"],
        "/r/pk/d/lib.dart": ["pk", "d"],
        "/r/pk/s/Main.swift": ["pk", "s"],
        "/r/pk/sc/Main.scala": ["pk", "sc"],
        "/r/pk/z/main.zig": ["pk", "z"],
        "/r/pk/h/Lib.hs": ["pk", "h"],
        "/r/pk/j/Main.jl": ["pk", "j"],
        "/r/pk/e/lib.ex": ["pk", "e"],
        "/r/pk/plain.py": ["pk", "plain"],  # not an entry file
        "_modules": [],
    }
    langs = {lang for _, _, lang in iter_reexport_files(fp)}
    assert langs == {
        "python", "js", "rust", "dart", "swift",
        "scala", "zig", "haskell", "julia", "elixir",
    }


def test_package_prefixes_src_layout():
    assert package_prefixes(["src", "pkg"], "rust") == [
        "src.pkg", "pkg", "crate.pkg"
    ]
    assert package_prefixes(["pkg"], "python") == ["pkg"]


# ---------------------------------------------------------------------------
# Python (PEP 328)
# ---------------------------------------------------------------------------

def test_python_relative_from_import():
    scope = FakeScope()
    _seed(scope, "pk.loader", {"get_config_cached": "id.loader.get_config_cached()"})
    n = reexports.reexports_python(
        "from .loader import get_config_cached\n",
        ["pk"], ["pk"], scope,
    )
    assert n == 1
    assert scope.aliases["pk.get_config_cached"].symbol_id == "id.loader.get_config_cached()"


def test_python_parenthesized_with_alias():
    scope = FakeScope()
    _seed(scope, "pk.loader", {"a": "id.a().", "b": "id.b()."})
    src = "from .loader import (\n    a,\n    b as bee,\n)\n"
    n = reexports.reexports_python(src, ["pk"], ["pk"], scope)
    assert n == 2
    assert scope.aliases["pk.bee"].symbol_id == "id.b()."


def test_python_from_import_submodule():
    scope = FakeScope()
    scope.symbols["pk.loader"] = FakeInfo("id.pk.loader/", "MODULE")
    n = reexports.reexports_python("from . import loader\n", ["pk"], ["pk"], scope)
    assert n == 1
    assert scope.aliases["pk.loader"].symbol_id == "id.pk.loader/"


def test_python_star_import():
    scope = FakeScope()
    _seed(scope, "pk.loader", {"pub_fn": "id.pub_fn().", "_private": "id._p()."})
    n = reexports.reexports_python("from .loader import *\n", ["pk"], ["pk"], scope)
    assert n == 1  # underscore-prefixed members excluded
    assert "pk.pub_fn" in scope.aliases


def test_python_absolute_from_own_package():
    scope = FakeScope()
    _seed(scope, "pk.core.loader", {"x": "id.x()."})
    n = reexports.reexports_python(
        "from pk.core.loader import x\n", ["pk", "core"], ["pk.core"], scope
    )
    assert n == 1
    assert scope.aliases["pk.core.x"].symbol_id == "id.x()."


def test_python_ignores_foreign_absolute_import():
    scope = FakeScope()
    n = reexports.reexports_python(
        "from os.path import join\n", ["pk"], ["pk"], scope
    )
    assert n == 0


# ---------------------------------------------------------------------------
# JS/TS (MDN / TC39 / TS handbook)
# ---------------------------------------------------------------------------

def test_js_braced_with_alias_and_type():
    scope = FakeScope()
    _seed(scope, "pk.components.Button", {"Button": "id.Button().", "T": "id.T#"})
    src = "export { Button, default as D, type T } from './components/Button';\n"
    n = reexports.reexports_js(src, ["pk"], ["pk"], scope)
    assert n == 2  # Button + T (default skipped)
    assert scope.aliases["pk.Button"].symbol_id == "id.Button()."


def test_js_star_and_namespace():
    scope = FakeScope()
    _seed(scope, "pk.icons", {"add": "id.add()."})
    scope.symbols["pk.icons"] = FakeInfo("id.icons/", "MODULE")
    src = "export * from './icons';\nexport * as icons from './icons';\n"
    n = reexports.reexports_js(src, ["pk"], ["pk"], scope)
    assert n == 2
    assert scope.aliases["pk.add"].symbol_id == "id.add()."
    assert scope.aliases["pk.icons"].symbol_id == "id.icons/"


def test_js_parent_relative_spec():
    scope = FakeScope()
    _seed(scope, "pk.util", {"fmt": "id.fmt()."})
    n = reexports.reexports_js(
        "export { fmt } from '../util';\n", ["pk", "sub"], ["pk.sub"], scope
    )
    assert n == 1


# ---------------------------------------------------------------------------
# Rust (Rust Reference)
# ---------------------------------------------------------------------------

def test_rust_braced_with_alias():
    scope = FakeScope()
    _seed(scope, "pk.api", {"make": "id.make().", "Model": "id.Model#"})
    src = "pub use self::api::{make, Model as M};\n"
    n = reexports.reexports_rust(src, ["pk"], ["pk"], scope)
    assert n == 2
    assert scope.aliases["pk.M"].symbol_id == "id.Model#"


def test_rust_glob_reexport():
    scope = FakeScope()
    _seed(scope, "pk.models", {"User": "id.User#", "Order": "id.Order#"})
    n = reexports.reexports_rust(
        "pub use crate::models::*;\n", ["pk", "src"], ["pk.src", "pk", "crate.pk"], scope
    )
    assert n >= 2
    assert scope.aliases["pk.User"].symbol_id == "id.User#"


def test_rust_crate_path_candidates():
    scope = FakeScope()
    _seed(scope, "rs.src.models", {"User": "id.User#"})
    # lib.rs at rs/src — crate::models::User → rs.src.models.User
    n = reexports.reexports_rust(
        "pub use crate::models::User;\n", ["rs", "src"], ["rs.src", "src", "crate.src"], scope
    )
    assert n == 1
    assert scope.aliases["rs.src.User"].symbol_id == "id.User#"


def test_rust_module_reexport():
    scope = FakeScope()
    scope.symbols["pk.sub"] = FakeInfo("id.pk.sub/", "MODULE")
    n = reexports.reexports_rust("pub use self::sub;\n", ["pk"], ["pk"], scope)
    assert n == 1
    assert scope.aliases["pk.sub"].symbol_id == "id.pk.sub/"


# ---------------------------------------------------------------------------
# Dart (dart.dev — export directive, show/hide, no `as`)
# ---------------------------------------------------------------------------

def test_dart_show_clause():
    scope = FakeScope()
    _seed(scope, "pk.src.models", {"User": "id.User#", "Order": "id.Order#"})
    n = reexports.reexports_dart(
        "export 'src/models.dart' show User;\n", ["pk"], ["pk"], scope
    )
    assert n == 1
    assert "pk.User" in scope.aliases
    assert "pk.Order" not in scope.aliases


def test_dart_hide_clause():
    scope = FakeScope()
    _seed(scope, "pk.src.models", {"User": "id.User#", "Order": "id.Order#"})
    n = reexports.reexports_dart(
        "export 'src/models.dart' hide Order;\n", ["pk"], ["pk"], scope
    )
    assert n == 1
    assert "pk.User" in scope.aliases
    assert "pk.Order" not in scope.aliases


def test_dart_bare_export():
    scope = FakeScope()
    _seed(scope, "pk.src.x", {"a": "id.a()."})
    n = reexports.reexports_dart("export 'src/x.dart';\n", ["pk"], ["pk"], scope)
    assert n == 1


# ---------------------------------------------------------------------------
# Swift (@_exported import)
# ---------------------------------------------------------------------------

def test_swift_exported_module():
    scope = FakeScope()
    scope.symbols["pk.Models"] = FakeInfo("id.pk.models/", "MODULE")
    n = reexports.reexports_swift(
        "@_exported import Models\n", ["pk"], ["pk"], scope
    )
    assert n == 1
    assert scope.aliases["pk.Models"].symbol_id == "id.pk.models/"


def test_swift_exported_selective():
    scope = FakeScope()
    _seed(scope, "pk.Combine", {"ObservableObject": "id.ObservableObject#"})
    n = reexports.reexports_swift(
        "@_exported import class Combine.ObservableObject\n",
        ["pk"], ["pk"], scope,
    )
    assert n == 1
    assert scope.aliases["pk.ObservableObject"].symbol_id == "id.ObservableObject#"


# ---------------------------------------------------------------------------
# Scala 3 (export clauses)
# ---------------------------------------------------------------------------

def test_scala3_braced_export_with_rename():
    scope = FakeScope()
    _seed(scope, "pk.service", {"make": "id.make().", "Config": "id.Config#"})
    n = reexports.reexports_scala(
        "export service.{make, Config as Cfg}\n", ["pk"], ["pk"], scope
    )
    assert n == 2
    assert scope.aliases["pk.Cfg"].symbol_id == "id.Config#"


def test_scala3_wildcard_export():
    scope = FakeScope()
    _seed(scope, "pk.service", {"make": "id.make()."})
    n = reexports.reexports_scala("export service.*\n", ["pk"], ["pk"], scope)
    assert n == 1


# ---------------------------------------------------------------------------
# Zig (pub const = @import)
# ---------------------------------------------------------------------------

def test_zig_whole_module_reexport():
    scope = FakeScope()
    scope.symbols["pk.math"] = FakeInfo("id.pk.math/", "MODULE")
    n = reexports.reexports_zig(
        'pub const math = @import("math.zig");\n', ["pk"], ["pk"], scope
    )
    assert n == 1
    assert scope.aliases["pk.math"].symbol_id == "id.pk.math/"


def test_zig_single_decl_reexport():
    scope = FakeScope()
    _seed(scope, "pk.foo", {"Foo": "id.Foo#"})
    n = reexports.reexports_zig(
        'pub const Foo = @import("foo.zig").Foo;\n', ["pk"], ["pk"], scope
    )
    assert n == 1
    assert scope.aliases["pk.Foo"].symbol_id == "id.Foo#"


# ---------------------------------------------------------------------------
# Haskell (module export lists)
# ---------------------------------------------------------------------------

def test_haskell_module_reexport():
    scope = FakeScope()
    _seed(scope, "Stack", {"push": "id.push().", "pop": "id.pop()."})
    src = "module Queue ( module Stack, enqueue ) where\n"
    n = reexports.reexports_haskell(src, ["pk"], ["pk"], scope)
    assert n == 2
    assert scope.aliases["pk.push"].symbol_id == "id.push()."


def test_haskell_qualified_entity():
    scope = FakeScope()
    _seed(scope, "pk.Stack", {"push": "id.push()."})
    n = reexports.reexports_haskell(
        "module Q ( Stack.push ) where\n", ["pk"], ["pk"], scope
    )
    assert n == 1


# ---------------------------------------------------------------------------
# Julia (import + export)
# ---------------------------------------------------------------------------

def test_julia_import_then_export():
    scope = FakeScope()
    _seed(scope, "Other", {"f": "id.f().", "g": "id.g()."})
    src = "import Other: f, g\nexport f\n"
    n = reexports.reexports_julia(src, ["pk"], ["pk"], scope)
    assert n == 1
    assert "pk.f" in scope.aliases
    assert "pk.g" not in scope.aliases


# ---------------------------------------------------------------------------
# Elixir (defdelegate)
# ---------------------------------------------------------------------------

def test_elixir_defdelegate():
    scope = FakeScope()
    _seed(scope, "MyMod", {"get": "id.get().", "put": "id.put()."})
    src = (
        "defdelegate get(key), to: MyMod\n"
        "defdelegate fetch(key), to: MyMod, as: :get\n"
    )
    n = reexports.reexports_elixir(src, ["pkg"], ["pkg"], scope)
    assert n == 2
    assert scope.aliases["pkg.get"].symbol_id == "id.get()."
    assert scope.aliases["pkg.fetch"].symbol_id == "id.get()."  # as: :get


# ---------------------------------------------------------------------------
# register_package_reexports integration
# ---------------------------------------------------------------------------

def test_register_package_reexports_end_to_end(tmp_path):
    init = tmp_path / "__init__.py"
    init.write_text("from .loader import get_config_cached\n")
    scope = FakeScope()
    _seed(scope, "pkg.loader", {"get_config_cached": "id.gcc()."})
    n = register_package_reexports(
        scope, {str(init): ["pkg"]}, logger=None
    )
    assert n == 1
    assert scope.aliases["pkg.get_config_cached"].symbol_id == "id.gcc()."


def test_register_package_reexports_empty():
    assert register_package_reexports(FakeScope(), None) == 0
    assert register_package_reexports(FakeScope(), {"_modules": []}) == 0


def test_alias_export_unresolvable_returns_zero():
    scope = FakeScope()
    assert alias_export(scope, ["pk"], "missing.mod", "x", "x") == 0


# ---------------------------------------------------------------------------
# Regression: real ScopeManager star exports (issue a7f3c91d2e84) and
# .d.ts compound-suffix module ids (issue a64e8b15c7f3)
# ---------------------------------------------------------------------------

def test_star_export_real_scope_manager():
    """alias_export '*' must not crash on the real ScopeManager — its
    iter_global_symbols yields snapshotted partitions so define_symbol
    inside the loop cannot mutate the iterated dict (a7f3c91d2e84)."""
    from batho.modules.extraction.scope_manager import ScopeManager
    scope = ScopeManager()
    scope.define_symbol("pk.sub.alpha", "id.alpha().", "FUNCTION", is_global=True)
    scope.define_symbol("pk.sub.beta", "id.beta().", "FUNCTION", is_global=True)
    n = alias_export(scope, ["pk"], "pk.sub", "*", "*")
    assert n == 2
    assert scope.resolve_symbol("pk.alpha").symbol_id == "id.alpha()."
    assert scope.resolve_symbol("pk.beta").symbol_id == "id.beta()."


def test_dart_bare_export_real_scope_manager():
    """reexports_dart's bare/hide branch iterates the same live partitions
    — same mutation guard applies (a7f3c91d2e84)."""
    from batho.modules.extraction.scope_manager import ScopeManager
    scope = ScopeManager()
    scope.define_symbol("lib.src.util.greet", "id.greet().", "FUNCTION", is_global=True)
    n = reexports.reexports_dart(
        "export 'src/util.dart';\n", ["lib"], ["lib"], scope)
    assert n == 1
    assert scope.resolve_symbol("lib.greet").symbol_id == "id.greet()."


def test_index_dts_module_id_and_barrel_aliases(tmp_path):
    """index.d.ts → parts stripped to ["pkg"], module id "…pkg/", and
    `export * from` aliases registered under pkg.* (a64e8b15c7f3)."""
    from pathlib import Path as _P
    from batho.core.config import set_active_root
    from batho.core.schemas import Entity, EntityType
    from batho.modules.extraction.scope_manager import ScopeManager
    from batho.modules.graph.builder.codegraph import CodeGraphIndexer

    root = tmp_path / "proj"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    dts = pkg / "index.d.ts"
    dts.write_text("export * from './types';\n")

    class FakeGraph:
        def __init__(self):
            self.entities = {}
        def get_entity(self, eid):
            return self.entities.get(eid)
        def add_entity(self, e):
            self.entities[e.id] = e

    graph = FakeGraph()
    seed = Entity(type=EntityType.FUNCTION, name="f",
                  file=str(pkg / "a.ts"), start_line=1, end_line=1,
                  id_override="batho npm x 1.0.0 pkg/a/f().")
    graph.entities[seed.id] = seed

    scope = ScopeManager()
    set_active_root(root)
    try:
        idx = CodeGraphIndexer(cache_path=str(root), root=str(root))
        try:
            idx._indexed_files = [str(dts)]
            file_parts = idx._register_module_entities(graph, scope)
        finally:
            idx.close()
    finally:
        set_active_root(_P.cwd())

    assert file_parts[str(dts)] == ["pkg"]
    assert "batho npm x 1.0.0 pkg/" in file_parts["_modules"]

    scope.define_symbol("pkg.types.Foo", "id.Foo", "TYPE", is_global=True)
    n = register_package_reexports(scope, file_parts)
    assert n == 1
    assert scope.resolve_symbol("pkg.Foo").symbol_id == "id.Foo"
