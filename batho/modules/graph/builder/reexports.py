"""Language-aware re-export (barrel / package-alias) detection.

Extracted from ``codegraph.py`` so the regex tables and per-language handlers
live in one dependency-light module (no imports from the graph builder —
``scope_manager`` is duck-typed). This keeps ``codegraph.py`` focused on graph
construction and makes the tables unit-testable in isolation.

Syntax below is verified against official language references:

=================  =====================================================  ====
Language           Construct                                              Ref
=================  =====================================================  ====
Python             ``from .mod import a as b`` / ``from . import m`` /    [1]
                   ``from mod import *`` (filtered by ``__all__``)
JavaScript/TS      ``export {a as b} from 'm'`` / ``export * from`` /     [2]
                   ``export * as ns from`` / ``export type {...} from``
Rust               ``pub use a::{B, C as D}`` / ``pub use a::*`` /        [3]
                   ``pub use self::x`` / ``pub(crate) use``
Dart               ``export 'src/x.dart' show A, B;`` / ``hide C;``       [4]
Swift              ``@_exported import Module``                           [5]
Scala 3            ``export a.b.{c, d as e}`` / ``export a.b.*``          [6]
Zig                ``pub const x = @import("x.zig");``                    [7]
Haskell            ``module M ( module N ) where``                        [8]
Julia              ``import Other: f`` + ``export f``                     [9]
Elixir             ``defdelegate f(args), to: Mod``                       [10]
=================  =====================================================  ====

Languages with NO static module-level re-export construct (verified absent —
not detected, by design): Go (name-based export; manual ``type X = pkg.T``
aliases), Java (``import`` is per-compilation-unit), Kotlin (``typealias`` is
a type alias, not a member re-export), C# / F# / VB.NET (``using`` aliases are
not re-exportable), Ruby / PHP / Lua / Clojure / Erlang / R / Perl / Bash /
Objective-C (runtime binding only), C / C++ (header forwarding is file-level;
``using``-declarations are ambiguous between local convenience and re-export
intent). Resolving those would require semantic analysis — out of scope for
Batho's deterministic, syntax-only resolution.

References:
[1] PEP 328 + https://docs.python.org/3/reference/import.html
[2] https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/export
    + https://tc39.es/ecma262/ + https://www.typescriptlang.org/docs/handbook/modules/reference.html
[3] https://doc.rust-lang.org/reference/items/use-declarations.html
[4] https://dart.dev/language/libraries
[5] https://github.com/swiftlang/swift/blob/main/docs/ReferenceGuides/UnderscoredAttributes.md
[6] https://docs.scala-lang.org/scala3/reference/other-new-features/export.html
[7] https://ziglang.org/documentation/master/
[8] https://www.haskell.org/onlinereport/haskell2010/haskellch5.html
[9] https://docs.julialang.org/en/v1/manual/modules/
[10] https://hexdocs.pm/elixir/Kernel.html
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# File-classification tables
# ---------------------------------------------------------------------------

#: (stem, extension) pairs that denote their containing package/crate rather
#: than a module of their own.
INIT_STEMS: dict[str, frozenset[str]] = {
    "__init__": frozenset({".py", ".pyi"}),
    "index": frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}),
    "mod": frozenset({".rs"}),
    "lib": frozenset({".rs"}),
    "main": frozenset({".rs"}),
}

#: Code-file extensions that get a synthesized MODULE entity (docs/config
#: formats are excluded — a markdown file is not an importable module).
MODULE_ENTITY_EXTS = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".kts", ".scala",
    ".rb", ".php", ".cs", ".swift", ".dart", ".lua",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".zig",
    ".jl", ".ex", ".exs", ".erl", ".hs", ".clj", ".cljs",
    ".fs", ".fsx", ".r", ".m", ".mm",
})

JS_EXTS = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
PY_EXTS = frozenset({".py", ".pyi"})
RS_INIT_NAMES = frozenset({"mod.rs", "lib.rs", "main.rs"})
DART_EXTS = frozenset({".dart"})
SWIFT_EXTS = frozenset({".swift"})
SCALA_EXTS = frozenset({".scala"})
ZIG_EXTS = frozenset({".zig"})
HS_EXTS = frozenset({".hs"})
JL_EXTS = frozenset({".jl"})
EX_EXTS = frozenset({".ex", ".exs"})

# ---------------------------------------------------------------------------
# Verified re-export regexes
# ---------------------------------------------------------------------------

# Python: `from .mod import a, b (as c)` / `from . import mod` / star. [1]
RE_PY_FROM_IMPORT = re.compile(
    r"from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+(\((?:[^()]*)\)|[^\n#]+)"
)

# JS/TS barrel re-exports in index.* files. [2]
RE_JS_BRACED = re.compile(
    r"export\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]"
)
RE_JS_STAR_NS = re.compile(
    r"export\s+\*\s+as\s+(\w+)\s+from\s*['\"]([^'\"]+)['\"]"
)
RE_JS_STAR = re.compile(
    r"export\s+\*\s+from\s*['\"]([^'\"]+)['\"]"
)
# TS 5.0 type-only star re-exports (elided from JS emit; type members only).
RE_JS_TYPE_STAR = re.compile(
    r"export\s+type\s+\*\s+from\s*['\"]([^'\"]+)['\"]"
)

# Rust `pub use a::B`, `pub use self::a::{B, C as D}`, `pub use crate::x::*`. [3]
# The plain form also admits a trailing glob (`pub use a::*;`).
RE_RS_BRACED = re.compile(
    r"pub(?:\(\w+(?:::\w+)*\))?\s+use\s+([\w:]+)\s*::\s*\{([^}]*)\}\s*;"
)
RE_RS_PLAIN = re.compile(
    r"pub(?:\(\w+(?:::\w+)*\))?\s+use\s+([\w:]+(?:::\*)?)(?:\s+as\s+(\w+))?\s*;"
)

# Dart `export 'src/x.dart' show A, B;` / `hide C;` — no `as` renaming. [4]
RE_DART_EXPORT = re.compile(
    r"^[ \t]*export[ \t]+['\"]([^'\"]+)['\"]"
    r"(?:[ \t]+show[ \t]+([^;]+?)|[ \t]+hide[ \t]+([^;]+?))?[ \t]*;",
    re.MULTILINE,
)

# Swift `@_exported import Module` (+ selective `@_exported import func M.f`). [5]
RE_SWIFT_EXPORTED = re.compile(
    r"^[ \t]*@_exported[ \t]+import[ \t]+"
    r"(?:(?:class|struct|enum|protocol|func|var|let|typealias)[ \t]+)?([\w.]+)",
    re.MULTILINE,
)

# Scala 3 `export a.b.{c, d as e}` / `export a.b.*` / `export a.b.c`. [6]
RE_SCALA_EXPORT = re.compile(
    r"^[ \t]*export[ \t]+([\w.]+)"
    r"(?:[ \t]*\.[ \t]*\{([^}]*)\}|[ \t]*\.[ \t]*(\*|given\b)|[ \t]*\.[ \t]*(\w+))",
    re.MULTILINE,
)

# Zig `pub const x = @import("x.zig");` / `pub const Foo = @import("f.zig").Foo;`. [7]
RE_ZIG_EXPORT = re.compile(
    r"^[ \t]*pub[ \t]+const[ \t]+(\w+)[ \t]*=[ \t]*@import\(\"([^\"]+)\"\)"
    r"(?:[ \t]*\.[ \t]*(\w+))?[ \t]*;",
    re.MULTILINE,
)

# Haskell `module M ( module N, f ) where` export lists. [8]
RE_HS_MODULE_HEADER = re.compile(
    r"^module[ \t]+([\w.']+)[ \t]*\(([^)]*)\)",
    re.MULTILINE,
)

# Julia `import Other: f, g` / `export f` pairs. [9]
RE_JL_IMPORT_FROM = re.compile(
    r"^[ \t]*import[ \t]+([\w.]+)(?:[ \t]*:[ \t]*([\w., \t]+))?",
    re.MULTILINE,
)
RE_JL_EXPORT = re.compile(r"^[ \t]*export[ \t]+([^#\n]+)", re.MULTILINE)

# Elixir `defdelegate f(args), to: Mod` (+ `as: :other`). [10]
RE_EX_DELEGATE = re.compile(
    r"^[ \t]*defdelegate[ \t]+(\w+)\s*\([^)]*\)\s*,[ \t]*to:\s*([\w.]+)"
    r"(?:[ \t]*,[ \t]*as:[ \t]*:(\w+))?",
    re.MULTILINE,
)


def _split_alias(item: str) -> tuple[str, str]:
    """Split ``orig as public`` → (orig, public); identity when unaliased."""
    if " as " in item:
        orig, public = item.split(" as ", 1)
        return orig.strip(), public.strip()
    return item.strip(), item.strip()


_SOURCE_EXTS = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".rs", ".go", ".java", ".kt", ".scala", ".dart", ".swift",
    ".zig", ".jl", ".hs", ".ex", ".exs", ".erl", ".lua", ".rb",
    ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".fs", ".r", ".m",
})


def _resolve_spec_module(spec: str, parts: list[str]) -> str | None:
    """Relative JS/Dart/Zig specifier → package-relative dotted module path.

    ``./x``, ``../x``, ``../../x/y`` resolve against the barrel file's own
    package parts; ``package:pkg/src/x.dart`` (Dart) resolves against ``src``.
    A trailing source extension on the final segment is stripped. Returns None
    when the specifier escapes the package or is package-external.
    """
    segs = spec.split("/")
    if segs and segs[0].startswith("package:"):
        # package:pkg/src/x.dart → treat src/... as the package root.
        segs = segs[0].split(":", 1)[1:] + segs[1:]
        if "src" in segs:
            i = segs.index("src")
            segs = segs[i + 1:]
            return ".".join(segs) if segs else None
        return None
    up = 0
    while segs and segs[0] in (".", ".."):
        if segs[0] == "..":
            up += 1
        segs.pop(0)
    if not segs or up > len(parts):
        return None
    last = Path(segs[-1])
    if last.suffix.lower() in _SOURCE_EXTS:
        segs[-1] = last.stem
    return ".".join(parts[: len(parts) - up] + segs)


def iter_reexport_files(
    file_parts: dict[str, list[str]] | None,
) -> "list[tuple[str, list[str], str]]":
    """Yield ``(abs_path, parts, language)`` for package/barrel entry files.

    Language dispatch by entry-file convention:
    Python ``__init__.*`` · JS/TS ``index.*`` · Rust ``mod.rs``/``lib.rs``/
    ``main.rs`` · Dart ``<pkg>.dart`` (or any top-level library file) ·
    Swift/Zig/Scala/Haskell/Julia/Elixir: any file using the construct
    (their entry conventions are not filename-based).
    """
    if not file_parts:
        return []
    out = []
    for fpath, parts in file_parts.items():
        if fpath == "_modules":
            continue
        name = Path(fpath).name
        suffix = Path(fpath).suffix.lower()
        if suffix in PY_EXTS and name.split(".")[0] == "__init__":
            out.append((fpath, parts, "python"))
        elif suffix in JS_EXTS and name.split(".")[0] == "index":
            out.append((fpath, parts, "js"))
        elif name in RS_INIT_NAMES:
            out.append((fpath, parts, "rust"))
        elif suffix in DART_EXTS:
            out.append((fpath, parts, "dart"))
        elif suffix in SWIFT_EXTS:
            out.append((fpath, parts, "swift"))
        elif suffix in SCALA_EXTS:
            out.append((fpath, parts, "scala"))
        elif suffix in ZIG_EXTS:
            out.append((fpath, parts, "zig"))
        elif suffix in HS_EXTS:
            out.append((fpath, parts, "haskell"))
        elif suffix in JL_EXTS:
            out.append((fpath, parts, "julia"))
        elif suffix in EX_EXTS:
            out.append((fpath, parts, "elixir"))
    return out


def read_source(fpath: str) -> str | None:
    try:
        return Path(fpath).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def package_prefixes(parts: list[str], language: str) -> list[str]:
    """Dotted package names under which aliases must be registered.

    src/lib-layout projects register symbols under the stripped path too, so
    aliases must exist under both package spellings; Rust crates additionally
    under ``crate.``.
    """
    pkg_dotted = ".".join(parts)
    prefixes = [pkg_dotted]
    if parts and parts[0] in ("src", "lib") and len(parts) > 1:
        stripped = ".".join(parts[1:])
        prefixes.append(stripped)
        if language == "rust":
            prefixes.append(f"crate.{stripped}")
    return prefixes


def alias_export(
    scope_manager,
    prefixes: list[str],
    target_module: str,
    orig: str,
    public: str,
) -> int:
    """Register ``<pkg>.<public>`` → resolved ``<target_module>.<orig>``
    under every package-name variant in ``prefixes``.

    ``orig == '*'`` enumerates the target module's registered public members.
    Returns the number of aliases registered.
    """
    pkg_dotted = prefixes[0]
    if orig == "*":
        prefix = f"{target_module}."
        count = 0
        for reg_name, info in scope_manager.iter_global_symbols(prefix):
            leaf = reg_name[len(prefix):]
            if "." not in leaf and not leaf.startswith("_"):
                for p in prefixes:
                    scope_manager.define_symbol(
                        f"{p}.{leaf}", info.symbol_id,
                        info.symbol_type, is_global=True,
                    )
                count += 1
        return count
    info = scope_manager.resolve_symbol_dotpath(f"{target_module}.{orig}")
    if info is None:
        # `from . import loader` / `export * as ns` — name is a submodule
        # (module entities are registered by the module-entity pass).
        info = scope_manager.resolve_symbol(f"{pkg_dotted}.{orig}")
    if info is None:
        return 0
    for p in prefixes:
        scope_manager.define_symbol(
            f"{p}.{public}", info.symbol_id,
            info.symbol_type, is_global=True,
        )
    return 1


# ---------------------------------------------------------------------------
# Per-language handlers — each returns the number of aliases registered.
# ---------------------------------------------------------------------------

def reexports_python(src, parts, prefixes, scope_manager) -> int:
    aliased = 0
    for m in RE_PY_FROM_IMPORT.finditer(src):
        dots, module, names_blob = m.group(1), m.group(2), m.group(3)
        level = len(dots)
        if level == 0:
            # Absolute form must re-export from inside this package.
            if not any(module.startswith(p + ".") for p in prefixes):
                continue
            target_module = module
        else:
            base = parts[: len(parts) - (level - 1)]
            target_module = ".".join(base + ([module] if module else []))
        blob = re.sub(r"\s+", " ", names_blob.strip("()"))
        for item in blob.split(","):
            item = item.strip()
            if not item:
                continue
            orig, public = _split_alias(item)
            aliased += alias_export(scope_manager, prefixes, target_module, orig, public)
    return aliased


def reexports_js(src, parts, prefixes, scope_manager) -> int:
    aliased = 0
    for m in RE_JS_BRACED.finditer(src):
        target_module = _resolve_spec_module(m.group(2), parts)
        if target_module is None:
            continue
        for item in m.group(1).split(","):
            item = item.strip()
            if item.startswith("type "):
                item = item[5:].strip()
            if not item or item == "default":
                continue
            orig, public = _split_alias(item)
            aliased += alias_export(scope_manager, prefixes, target_module, orig, public)
    # `export * as ns from './m'` — ns aliases the target module itself.
    for m in RE_JS_STAR_NS.finditer(src):
        target_module = _resolve_spec_module(m.group(2), parts)
        if target_module is None:
            continue
        info = scope_manager.resolve_symbol_dotpath(target_module)
        if info is not None:
            for p in prefixes:
                scope_manager.define_symbol(
                    f"{p}.{m.group(1)}", info.symbol_id,
                    info.symbol_type, is_global=True,
                )
            aliased += 1
    for m in RE_JS_STAR.finditer(src):
        target_module = _resolve_spec_module(m.group(1), parts)
        if target_module is None:
            continue
        aliased += alias_export(scope_manager, prefixes, target_module, "*", "*")
    for m in RE_JS_TYPE_STAR.finditer(src):
        target_module = _resolve_spec_module(m.group(1), parts)
        if target_module is None:
            continue
        aliased += alias_export(scope_manager, prefixes, target_module, "*", "*")
    return aliased


def _rust_base_candidates(path_parts: list[str], parts: list[str]) -> list[list[str]]:
    """Candidate module part-lists for a Rust `use` path.

    ``crate::`` resolves relative to the crate root — approximated as
    (a) this file's own package when it IS the crate root (lib.rs/main.rs/
    mod.rs at top level), (b) the ``src`` dir for src-layout crates,
    (c) the bare tail for stripped registrations.
    """
    if path_parts[0] == "self":
        return [parts + path_parts[1:]]
    if path_parts[0] == "super":
        return [parts[:-1] + path_parts[1:]] if len(parts) > 1 else []
    tail = path_parts[1:] if path_parts[0] == "crate" else path_parts
    cands: list[list[str]] = [parts + tail]          # (a) same package
    if "src" in parts:
        i = parts.index("src")
        cands.append(parts[: i + 1] + tail)          # (b) src crate root
        cands.append(parts[:i] + tail)               # (b') above src
    cands.append(tail)                               # (c) stripped
    return cands


def reexports_rust(src, parts, prefixes, scope_manager) -> int:
    aliased = 0
    for m in RE_RS_BRACED.finditer(src):
        head = [s for s in m.group(1).split("::") if s]
        if not head:
            continue
        done = False
        for base in _rust_base_candidates(head, parts):
            if done:
                break
            target_module = ".".join(base)
            for item in m.group(2).split(","):
                item = item.strip()
                if not item:
                    continue
                orig, public = _split_alias(item)
                n = alias_export(scope_manager, prefixes, target_module, orig, public)
                if n:
                    aliased += n
                    done = True
    for m in RE_RS_PLAIN.finditer(src):
        chain = [s for s in m.group(1).split("::") if s and s != "*"]
        is_glob = m.group(1).endswith("::*")
        if not chain or "{" in m.group(0):
            continue  # brace form handled above
        alias = m.group(2)
        if is_glob:
            # `pub use a::*;` / `pub use crate::a::*;` — star re-export.
            # `chain` already excludes the trailing `*` segment.
            for cand in _rust_base_candidates(chain, parts):
                n = alias_export(scope_manager, prefixes, ".".join(cand), "*", "*")
                if n:
                    aliased += n
                    break
            continue
        orig = chain[-1]
        public = alias or orig
        if len(chain) == 1:
            cands = [parts]  # `pub use Foo;` — same-package name
        else:
            cands = _rust_base_candidates(chain[:-1], parts)
        for base in cands:
            n = alias_export(scope_manager, prefixes, ".".join(base), orig, public)
            if n:
                aliased += n
                break
    return aliased


def reexports_dart(src, parts, prefixes, scope_manager) -> int:
    """`export 'src/x.dart' show A, B;` / `hide C;` / bare whole-library."""
    aliased = 0
    for m in RE_DART_EXPORT.finditer(src):
        target_module = _resolve_spec_module(m.group(1), parts)
        if target_module is None:
            continue
        if m.group(2):  # show A, B — alias only listed names
            for item in m.group(2).split(","):
                item = item.strip()
                if item:
                    aliased += alias_export(
                        scope_manager, prefixes, target_module, item, item
                    )
        else:  # bare or hide — alias all public members (minus hidden)
            hidden = set()
            if m.group(3):
                hidden = {x.strip() for x in m.group(3).split(",") if x.strip()}
            prefix = f"{target_module}."
            for reg_name, info in scope_manager.iter_global_symbols(prefix):
                leaf = reg_name[len(prefix):]
                if "." not in leaf and not leaf.startswith("_") and leaf not in hidden:
                    for p in prefixes:
                        scope_manager.define_symbol(
                            f"{p}.{leaf}", info.symbol_id,
                            info.symbol_type, is_global=True,
                        )
                    aliased += 1
    return aliased


def reexports_swift(src, parts, prefixes, scope_manager) -> int:
    aliased = 0
    pkg_dotted = prefixes[0]
    for m in RE_SWIFT_EXPORTED.finditer(src):
        target = m.group(1)
        # Module form `@_exported import Module` — resolve the module path.
        # Selective form `func M.f` — resolve M.f as a member path.
        info = scope_manager.resolve_symbol_dotpath(target)
        if info is None:
            info = scope_manager.resolve_symbol_dotpath(f"{pkg_dotted}.{target}")
        if info is None:
            continue
        leaf = target.rsplit(".", 1)[-1]
        for p in prefixes:
            scope_manager.define_symbol(
                f"{p}.{leaf}", info.symbol_id,
                info.symbol_type, is_global=True,
            )
        aliased += 1
    return aliased


def reexports_scala(src, parts, prefixes, scope_manager) -> int:
    aliased = 0
    for m in RE_SCALA_EXPORT.finditer(src):
        qualifier, braced, wildcard, single = m.groups()
        # The qualifier is a path relative to the enclosing scope — try it
        # bare first, then package-prefixed.
        targets = [qualifier] + [
            f"{p}.{qualifier}" for p in reversed(prefixes) if p != qualifier
        ]
        if braced:
            for item in braced.split(","):
                item = item.strip()
                if not item or item == "_":
                    continue
                orig, public = _split_alias(item)
                for target in targets:
                    n = alias_export(scope_manager, prefixes, target, orig, public)
                    if n:
                        aliased += n
                        break
        elif wildcard:
            for target in targets:
                n = alias_export(scope_manager, prefixes, target, "*", "*")
                if n:
                    aliased += n
                    break
        elif single:
            for target in targets:
                n = alias_export(scope_manager, prefixes, target, single, single)
                if n:
                    aliased += n
                    break
    return aliased


def reexports_zig(src, parts, prefixes, scope_manager) -> int:
    aliased = 0
    for m in RE_ZIG_EXPORT.finditer(src):
        public, spec, field = m.group(1), m.group(2), m.group(3)
        target_module = _resolve_spec_module(spec, parts)
        if target_module is None:
            continue
        if field:
            # `pub const Foo = @import("foo.zig").Foo;` — single decl.
            aliased += alias_export(scope_manager, prefixes, target_module, field, public)
        else:
            # `pub const x = @import("x.zig");` — whole-module alias.
            info = scope_manager.resolve_symbol_dotpath(target_module)
            if info is not None:
                for p in prefixes:
                    scope_manager.define_symbol(
                        f"{p}.{public}", info.symbol_id,
                        info.symbol_type, is_global=True,
                    )
                aliased += 1
    return aliased


def reexports_haskell(src, parts, prefixes, scope_manager) -> int:
    aliased = 0
    for m in RE_HS_MODULE_HEADER.finditer(src):
        for item in m.group(2).split(","):
            item = item.strip()
            if not item:
                continue
            if item.startswith("module "):
                # `module N` — re-export all of N's exported entities.
                target = item[len("module "):].strip()
                candidates = [target] + [
                    f"{p}.{target}" for p in reversed(prefixes) if p != target
                ]
                for cand in candidates:
                    n = alias_export(scope_manager, prefixes, cand, "*", "*")
                    if n:
                        aliased += n
                        break
            elif "." in item:
                # `N.f` — qualified single-entity re-export. `N` is a module
                # path; try it bare, then package-prefixed.
                target, orig = item.rsplit(".", 1)
                candidates = [target] + [
                    f"{p}.{target}" for p in reversed(prefixes) if p != target
                ]
                for cand in candidates:
                    n = alias_export(scope_manager, prefixes, cand, orig, orig)
                    if n:
                        aliased += n
                        break
    return aliased


def reexports_julia(src, parts, prefixes, scope_manager) -> int:
    exported: set[str] = set()
    for m in RE_JL_EXPORT.finditer(src):
        for item in m.group(1).split(","):
            item = item.strip()
            if item:
                exported.add(item)
    if not exported:
        return 0
    aliased = 0
    for m in RE_JL_IMPORT_FROM.finditer(src):
        module, names_blob = m.group(1), m.group(2)
        if names_blob:
            for item in names_blob.split(","):
                orig = item.strip()
                if orig in exported:
                    aliased += alias_export(scope_manager, prefixes, module, orig, orig)
        else:
            # `import Other` + `export f` — resolve f as Other.f.
            for orig in sorted(exported):
                aliased += alias_export(scope_manager, prefixes, module, orig, orig)
    return aliased


def reexports_elixir(src, parts, prefixes, scope_manager) -> int:
    aliased = 0
    for m in RE_EX_DELEGATE.finditer(src):
        public, target, as_name = m.group(1), m.group(2), m.group(3)
        orig = as_name or public
        aliased += alias_export(scope_manager, prefixes, target, orig, public)
    return aliased


def register_package_reexports(
    scope_manager,
    file_parts: dict[str, list[str]] | None,
    logger=None,
) -> int:
    """Scan package/barrel entry files and register re-export aliases.

    Returns the number of aliases registered. ``scope_manager`` is duck-typed
    (define_symbol / resolve_symbol_dotpath / resolve_symbol /
    iter_global_symbols) so this module stays import-cycle-free.
    """
    if not file_parts:
        return 0
    aliased = 0
    for fpath, parts, language in iter_reexport_files(file_parts):
        src = read_source(fpath)
        if src is None:
            continue
        prefixes = package_prefixes(parts, language)
        if language == "python":
            aliased += reexports_python(src, parts, prefixes, scope_manager)
        elif language == "js":
            aliased += reexports_js(src, parts, prefixes, scope_manager)
        elif language == "rust":
            aliased += reexports_rust(src, parts, prefixes, scope_manager)
        elif language == "dart":
            aliased += reexports_dart(src, parts, prefixes, scope_manager)
        elif language == "swift":
            aliased += reexports_swift(src, parts, prefixes, scope_manager)
        elif language == "scala":
            aliased += reexports_scala(src, parts, prefixes, scope_manager)
        elif language == "zig":
            aliased += reexports_zig(src, parts, prefixes, scope_manager)
        elif language == "haskell":
            aliased += reexports_haskell(src, parts, prefixes, scope_manager)
        elif language == "julia":
            aliased += reexports_julia(src, parts, prefixes, scope_manager)
        elif language == "elixir":
            aliased += reexports_elixir(src, parts, prefixes, scope_manager)
    if aliased and logger is not None:
        logger.info("package_reexports_registered", aliases=aliased)
    return aliased
