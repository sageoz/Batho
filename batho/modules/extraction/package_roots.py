"""Derive import namespaces from repository evidence — never from layout conventions.

A source file's *import path* (what `from a.b import c` sees) may differ from
its *file path* (where it sits in the tree). This module computes the import
path purely from evidence:

1. **Package markers** — a directory is part of a Python package iff it
   contains a package-marker file (`__init__.py`/`__init__.pyi`). The import
   path is the longest contiguous marked suffix of the file's directory
   chain: `backend/app/services/x.py` → `app.services.x` when `backend/` has
   no marker. This is the same rule CPython's importer applies — and it
   covers src-layout, flat, and monorepo layouts with zero configuration.

2. **Manifest facts** — `pyproject.toml` (`[tool.setuptools] package-dir`,
   `packages.find where`), `setup.cfg` `[options.packages.find] where`,
   `Cargo.toml` (cargo defines the crate root as `<pkg>/src`), `tsconfig*.json`
   (`compilerOptions.baseUrl`/`paths` aliases). These are the repo's own
   declarations.

3. **Configured roots** — `indexer.package_roots` from batho.yaml
   (user-declared escape hatch, empty by default).

Nothing here hardcodes directory names; layout is always derived.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="package_roots")

# Language-defined package markers — `__init__.py`/`.pyi` are what make a
# directory a Python package per the language spec (PEP 420 namespace
# packages are handled by the resolution-time suffix fallback instead).
_PY_PACKAGE_MARKERS = ("__init__.py", "__init__.pyi")

# Manifest filenames whose presence or contents declare package/import roots.
_MANIFEST_FILES = ("pyproject.toml", "setup.cfg", "Cargo.toml", "go.mod")
_TSCONFIG_GLOB = "tsconfig*.json"

# Manifest scan depth — roots are declared at repo root or one level down
# (monorepo package dirs); deeper nesting is covered by suffix matching.
_MANIFEST_SCAN_DEPTH = 2

# Vendored/dependency dirs never declare this repo's import roots — their
# manifests describe external packages, and scanning them would let a
# vendored tsconfig `paths` key rewrite repo-wide refs. Mirrors the
# first-level names in batho/core/config/default-ignore-patterns.yaml (plus
# `vendor`, the ecosystem vendoring convention); kept as a small local
# blocklist so this helper doesn't pull in the full ignore machinery.
_MANIFEST_SKIP_DIRS = frozenset(
    {
        "node_modules",
        "bower_components",
        "vendor",
        "venv",
        "env",
        "virtualenv",
        "dist",
        "build",
        "target",
        "out",
        "__pycache__",
        "site-packages",
    }
)

_marker_cache: dict[str, bool] = {}
_manifest_cache: dict[str, tuple[list[tuple[str, ...]], list[tuple[str, str]]]] = {}


def reset_caches() -> None:
    """Drop memoized evidence (called at build/patch start — new files can
    create or dissolve package boundaries)."""
    _marker_cache.clear()
    _manifest_cache.clear()


def _dir_has_marker(dirpath: Path) -> bool:
    key = str(dirpath)
    hit = _marker_cache.get(key)
    if hit is not None:
        return hit
    try:
        hit = any((dirpath / m).is_file() for m in _PY_PACKAGE_MARKERS)
    except OSError:
        hit = False
    _marker_cache[key] = hit
    return hit


def marker_chain_parts(root: Path, parts: list[str]) -> list[str] | None:
    """Import-path parts via the package-marker chain.

    ``parts`` are the file's repo-relative path segments (stem last, no
    extension). Callers that register package entry files pop the init stem
    first (``backend/app/__init__.py`` → ``["backend", "app"]``), in which
    case every element is a directory. That init-stripped shape is detected
    by the path's own marker file: when ``root/parts`` is itself a marked
    package dir, ``parts[-1]`` is a directory, not a file stem.

    Returns the longest contiguous suffix where every directory is a package
    (marker present), or None when no dir in the chain is a package — i.e.
    nothing to strip.
    """
    init_stripped = bool(parts) and _dir_has_marker(root.joinpath(*parts))
    dirs = parts if init_stripped else parts[:-1]  # file stem isn't a directory
    if not dirs:
        return None
    keep = 0
    for i in range(len(dirs) - 1, -1, -1):
        if _dir_has_marker(root.joinpath(*dirs[: i + 1])):
            keep += 1
        else:
            break
    if keep == 0:
        return None
    trimmed = dirs[len(dirs) - keep :] + ([] if init_stripped else [parts[-1]])
    return trimmed if trimmed != parts else None


# ---------------------------------------------------------------------------
# Manifest-declared roots
# ---------------------------------------------------------------------------


def _scan_manifest_dirs(root: Path) -> list[Path]:
    """Root plus first-level dirs — manifests are scanned at bounded depth."""
    dirs = [root]
    if _MANIFEST_SCAN_DEPTH > 1:
        try:
            for child in sorted(root.iterdir()):
                if (
                    child.is_dir()
                    and not child.is_symlink()
                    and not child.name.startswith(".")
                    and child.name not in _MANIFEST_SKIP_DIRS
                ):
                    dirs.append(child)
        except OSError:
            pass
    return dirs


def _pyproject_roots(path: Path) -> tuple[list[tuple[str, ...]], list[tuple[str, str]]]:
    """``[tool.setuptools] package-dir`` / ``packages.find where`` roots."""
    roots: list[tuple[str, ...]] = []
    try:
        import tomllib

        data = tomllib.loads(path.read_text(encoding="utf-8"))
        st = data.get("tool", {}).get("setuptools", {})
        pkg_dir = st.get("package-dir") or {}
        for v in pkg_dir.values():
            if isinstance(v, str) and v:
                roots.append(tuple(v.replace("\\", "/").strip("/").split("/")))
        find = st.get("packages", {}).get("find", {}) if isinstance(st.get("packages"), dict) else {}
        where = find.get("where") or []
        if isinstance(where, str):
            where = [where]
        for w in where:
            if isinstance(w, str) and w:
                roots.append(tuple(w.replace("\\", "/").strip("/").split("/")))
    except Exception as exc:
        LOGGER.debug("pyproject_roots_parse_failed", path=str(path), error=str(exc))
    return roots, []


def _setup_cfg_roots(path: Path) -> tuple[list[tuple[str, ...]], list[tuple[str, str]]]:
    """``[options.packages.find] where`` entries."""
    roots: list[tuple[str, ...]] = []
    try:
        import configparser

        cp = configparser.ConfigParser()
        cp.read(path, encoding="utf-8")
        if cp.has_option("options.packages.find", "where"):
            for w in cp.get("options.packages.find", "where").split():
                roots.append(tuple(w.replace("\\", "/").strip("/").split("/")))
    except Exception as exc:
        LOGGER.debug("setup_cfg_roots_parse_failed", path=str(path), error=str(exc))
    return roots, []


def _cargo_roots(manifest: Path, root: Path) -> tuple[list[tuple[str, ...]], list[tuple[str, str]]]:
    """Cargo defines the crate root as ``<pkgdir>/src`` (ecosystem spec).

    Returns the manifest-dir-relative root ``("src",)`` — the caller
    prepends the manifest's own directory.
    """
    return [("src",)], []


def _go_roots(manifest: Path, root: Path) -> tuple[list[tuple[str, ...]], list[tuple[str, str]]]:
    """``go.mod`` ``module <path>`` → declared import prefix ↔ dir mapping."""
    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("module "):
                mod = line.split(None, 1)[1].strip()
                try:
                    rel = manifest.parent.relative_to(root)
                except ValueError:
                    rel = Path()
                # `module github.com/x/y` declares that files under this dir
                # are importable as github.com/x/y/... — a dotted alias pair.
                return [], [(mod.replace("/", "."), ".".join(rel.parts))]
    except (OSError, ValueError) as exc:
        LOGGER.debug("go_mod_roots_parse_failed", path=str(manifest), error=str(exc))
    return [], []


def _strip_jsonc_comments(text: str) -> str:
    """Remove `//` and `/* */` comments outside of quoted strings."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _tsconfig_aliases(path: Path, root: Path) -> tuple[list[tuple[str, ...]], list[tuple[str, str]]]:
    """``compilerOptions.baseUrl`` root + ``paths`` alias patterns.

    ``paths: {"@/*": ["./src/*"]}`` → alias pair ``("@/", "src/")`` applied to
    reference-side rewriting. ``baseUrl`` makes its dir a bare-import root.
    """
    roots: list[tuple[str, ...]] = []
    aliases: list[tuple[str, str]] = []
    try:
        # tsconfig allows comments + trailing commas; strip string-aware —
        # a bare regex would eat `//` inside quoted values (e.g. URLs).
        raw = _strip_jsonc_comments(path.read_text(encoding="utf-8"))
        raw = re.sub(r",(\s*[}\]])", r"\1", raw)
        data = json.loads(raw)
        opts = data.get("compilerOptions", {}) if isinstance(data, dict) else {}
        base_dir = path.parent
        try:
            base_rel = base_dir.relative_to(root).parts
        except ValueError:
            base_rel = ()
        base_url = opts.get("baseUrl")
        if isinstance(base_url, str) and base_url and base_url != ".":
            roots.append(tuple(base_rel) + tuple(base_url.strip("./").split("/")))
        elif base_url == ".":
            roots.append(tuple(base_rel))
        paths = opts.get("paths") or {}
        for pat, targets in paths.items():
            if not isinstance(pat, str) or not isinstance(targets, list) or not targets:
                continue
            # Only wildcard `*` aliases are rewritten; exact key aliases map
            # whole names (handled the same way, just without the wildcard).
            is_wildcard = pat.endswith("*")
            pat_prefix = pat[:-1] if is_wildcard else pat
            tgt = targets[0]
            tgt_prefix = tgt[:-1] if isinstance(tgt, str) and tgt.endswith("*") else (tgt or "")
            joined = "/".join(base_rel + (tgt_prefix.strip("./").rstrip("/"),)).strip("/")
            # Wildcard subs carry the trailing separator (ref text is appended
            # verbatim); exact keys join on "." in alias_candidates, which
            # relies on this trailing "/" to tell wildcard pairs from exact
            # ones when enforcing segment boundaries.
            aliases.append((pat_prefix, joined + "/" if (joined and is_wildcard) else joined))
    except Exception as exc:
        LOGGER.debug("tsconfig_roots_parse_failed", path=str(path), error=str(exc))
    return roots, aliases


def manifest_roots_and_aliases(
    root: Path,
) -> tuple[list[tuple[str, ...]], list[tuple[str, str]]]:
    """All manifest-declared import roots and alias pairs for ``root``.

    Returns ``(roots, alias_pairs)`` where roots are repo-relative dir tuples
    to strip from path parts, and alias_pairs are ``(ref_prefix, path_prefix)``
    rewrites for reference-side resolution.
    """
    key = str(root)
    cached = _manifest_cache.get(key)
    if cached is not None:
        return cached

    roots: list[tuple[str, ...]] = []
    aliases: list[tuple[str, str]] = []
    for d in _scan_manifest_dirs(root):
        for name in _MANIFEST_FILES:
            mf = d / name
            if mf.is_symlink() or not mf.is_file():
                continue
            if name == "pyproject.toml":
                r, a = _pyproject_roots(mf)
            elif name == "setup.cfg":
                r, a = _setup_cfg_roots(mf)
            elif name == "Cargo.toml":
                r, a = _cargo_roots(mf, root)
            else:  # go.mod
                r, a = _go_roots(mf, root)
            # Manifest roots are relative to the manifest's own directory.
            try:
                dir_rel = d.relative_to(root).parts
            except ValueError:
                dir_rel = ()
            roots.extend(tuple(dir_rel) + tuple(x) for x in r)
            aliases.extend(a)
        for tsf in sorted(d.glob(_TSCONFIG_GLOB)):
            if tsf.is_symlink():
                continue
            r, a = _tsconfig_aliases(tsf, root)
            roots.extend(r)
            aliases.extend(a)

    out = (roots, aliases)
    _manifest_cache[key] = out
    return out


def configured_roots() -> list[tuple[str, ...]]:
    """``indexer.package_roots`` from the active config (user-declared).

    Deliberately not memoized: the value is config-derived, not root-derived,
    and ``get_config_cached`` already caches — a second process-global cache
    here could only pin a stale config across roots in one process.
    """
    roots: list[tuple[str, ...]] = []
    try:
        from batho.core.config import get_config_cached

        raw = get_config_cached().get("indexer", {}).get("package_roots") or []
        for item in raw:
            if isinstance(item, str) and item.strip():
                roots.append(tuple(item.replace("\\", "/").replace(".", "/").strip("/").split("/")))
    except Exception:
        pass
    return roots


def derived_module_variants(
    root: Path | None, parts: list[str]
) -> list[list[str]]:
    """Alternate module-path spellings for a file, all evidence-derived.

    ``parts`` are the file's repo-relative path segments (stem last, no
    extension — the same shape `_register_module_entities` produces).
    Returns additional variants to register; empty when the path spelling
    is already the only defensible namespace.
    """
    if root is None or not parts:
        return []
    variants: list[list[str]] = []

    trimmed = marker_chain_parts(root, parts)
    if trimmed:
        variants.append(trimmed)

    manifest_roots, _ = manifest_roots_and_aliases(root)
    for prefix in manifest_roots + configured_roots():
        if len(parts) > len(prefix) and tuple(parts[: len(prefix)]) == prefix:
            v = parts[len(prefix) :]
            if v and v != parts and v not in variants:
                variants.append(v)

    return variants


# ---------------------------------------------------------------------------
# Resolution-time helpers: module suffix index + alias rewriting
# ---------------------------------------------------------------------------


def build_module_suffix_index(scope_manager: Any) -> dict[str, set[str]]:
    """``{dotted module-path suffix -> {full registered module keys}}``.

    Enables namespace-agnostic alignment: a ref module `app.services.errors`
    matches registered `backend.app.services.errors` because the latter's
    segment sequence ends with the former's.
    """
    index: dict[str, set[str]] = {}
    try:
        entries = scope_manager.iter_global_symbols()
    except Exception:
        return index
    for key, info in entries:
        if getattr(info, "is_external", False):
            continue
        if getattr(info, "symbol_type", "") != "MODULE":
            continue
        if "/" in key:
            key = key.replace("/", ".")
        if "." not in key:
            continue
        parts = key.split(".")
        for i in range(len(parts)):
            suffix = ".".join(parts[i:])
            index.setdefault(suffix, set()).add(key)
    return index


def alias_candidates(
    target_name: str, alias_pairs: list[tuple[str, str]]
) -> list[str]:
    """Rewrite a ref through manifest-declared alias prefixes.

    ``@/components/x.Button`` with pair ``("@/", "src/")`` →
    ``src.components.x.Button``. Returns candidate dotted names (the original
    first, then rewrites).
    """
    out = [target_name]
    for pat, sub in alias_pairs:
        if not pat:
            continue
        # Wildcard pairs (`@/*` → `src/*`) are produced with a trailing "/"
        # on the pattern prefix or the substitution; they append the ref
        # tail verbatim, so a bare startswith is the right match.
        wildcard = pat.endswith("/") or sub.endswith("/")
        if wildcard:
            if not target_name.startswith(pat):
                continue
        elif not (
            target_name == pat
            or target_name.startswith(pat + "/")
            or target_name.startswith(pat + ".")
        ):
            # Exact keys (`app`, `~/lib`, go module paths) must match a full
            # name or a segment boundary — `app` must not rewrite `apple.x`.
            continue
        rewritten = (sub + target_name[len(pat) :]).replace("/", ".")
        # A root-level manifest maps the module prefix onto "" (e.g. go.mod
        # at repo root) — the join leaves a leading "." that splits into an
        # empty first segment and can never match the suffix index.
        rewritten = rewritten.lstrip(".")
        if rewritten and rewritten != target_name:
            out.append(rewritten)
    return out
