from __future__ import annotations
import os
import time
import hashlib
import structlog
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from batho.modules.extraction.scope_manager import ScopeManager
from batho.core.schemas import PackageManager
from .manifest_parser import ManifestParser, DependencySpec
from .stdlib_tables import StdlibSymbolTable
from .popular_packages import PopularPackagesDB
from .introspector import ThirdPartyIntrospector
from .resolution_cache import ResolutionCache

logger = structlog.get_logger(__name__)

# Language-specific stdlib symbol ID templates.
# Maps language -> (registry, runtime, version, suffix) used to build
# symbol IDs of the form: "batho {registry} {runtime} {version} {mod}/{sym}{suffix}"
_STDLIB_SYMBOL_TEMPLATES: dict[str, tuple[str, str, str, str]] = {
    "python":     ("pip",       "python",     "3.x",     "()."),
    "javascript": ("npm",       "nodejs",     "20.x",    "#"),
    "typescript": ("npm",       "typescript", "5.x",     "#"),
    "go":         ("go",        "golang",     "1.21",    "."),
    "rust":       ("cargo",     "rust",       "1.75",    "."),
    "c":          ("system",    "c",          "c11",     "."),
    "cpp":        ("system",    "cpp",        "c++17",   "."),
    "java":       ("maven",     "java",       "21",      "()."),
    "ruby":       ("gem",       "ruby",       "3.x",     "()."),
    "csharp":     ("nuget",     "csharp",     "8.x",     "()."),
    "php":        ("composer",  "php",        "8.x",     "()."),
    "kotlin":     ("maven",     "kotlin",     "1.9",     "()."),
    "swift":      ("spm",       "swift",      "5.9",     "()."),
    "scala":      ("sbt",       "scala",      "3.x",     "()."),
    "dart":       ("pub",       "dart",       "3.x",     "()."),
    "haskell":    ("cabal",     "haskell",    "9.x",     "."),
    "lua":        ("luarocks",  "lua",        "5.4",     "()."),
    "r":          ("cran",      "r",          "4.x",     "()."),
    "perl":       ("cpan",      "perl",       "5.x",     "()."),
    "julia":      ("pkg",       "julia",      "1.9",     "()."),
    "zig":        ("zigmod",    "zig",        "0.11",    "."),
    "bash":       ("system",    "bash",       "5.x",     "."),
    "objc":       ("system",    "objc",       "2.0",     "()."),
    "erlang":     ("rebar3",    "erlang",     "26",      "()."),
    "ocaml":      ("opam",      "ocaml",      "5.x",     "."),
    "hack":       ("composer",  "hack",       "4.x",     "()."),
    "verilog":    ("system",    "verilog",    "2017",    "."),
    "agda":       ("agda",      "agda",       "2.x",     "."),
}


# ---------------------------------------------------------------------------
# Universal introspection (dep-01 / dep-17).
#
# _ENV_MATRIX: how to resolve each manager's introspection environment.
# Two classes (D1):
#   - "project": an env dir that must exist under the workspace root, found
#     by walking up from the declaring manifest dir (bounded at root).
#   - "store": a machine-level package store, resolved from env-var
#     overrides (os.pathsep-separated lists supported) first, then platform
#     defaults under Path.home(), then default_globs under Path.home().
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _EnvSpec:
    kind: str                                    # "project" | "store"
    markers: tuple[str, ...] = ()                # project-scoped dir names
    env_vars: tuple[str, ...] = ()               # store env-var overrides
    env_suffix: tuple[str, ...] = ()             # appended to env-var value
    default_root: tuple[str, ...] = ()           # store root under Path.home()
    default_globs: tuple[str, ...] = ()          # glob patterns under home


_ENV_MATRIX: dict[PackageManager, _EnvSpec] = {
    PackageManager.PIP: _EnvSpec("project", markers=(".venv", "venv", "env")),
    PackageManager.NPM: _EnvSpec("project", markers=("node_modules",)),
    PackageManager.COMPOSER: _EnvSpec("project", markers=("vendor",)),
    PackageManager.SPM: _EnvSpec("project", markers=(".build/checkouts",)),
    PackageManager.REBAR3: _EnvSpec("project", markers=("_build/default/lib",)),
    PackageManager.CRAN: _EnvSpec(
        "project", markers=("renv/library",), env_vars=("R_LIBS_USER",),
        default_globs=("Library/R/*/library", "R/*-library/*"),
    ),
    PackageManager.CARGO: _EnvSpec(
        "store", env_vars=("CARGO_HOME",), env_suffix=("registry", "src"),
        default_root=(".cargo", "registry", "src"),
    ),
    PackageManager.GO: _EnvSpec(
        "store", env_vars=("GOPATH",), env_suffix=("pkg", "mod"),
        default_root=("go", "pkg", "mod"),
    ),
    PackageManager.MAVEN: _EnvSpec(
        "store", env_vars=("MAVEN_REPO", "M2_REPO"), default_root=(".m2", "repository"),
    ),
    PackageManager.GRADLE: _EnvSpec(
        "store", env_vars=("GRADLE_USER_HOME",), env_suffix=("caches", "modules-2"),
        default_root=(".gradle", "caches", "modules-2"),
    ),
    PackageManager.GEM: _EnvSpec(
        "store", env_vars=("GEM_HOME", "BUNDLE_PATH"), default_root=(".gem",),
    ),
    PackageManager.NUGET: _EnvSpec(
        "store", env_vars=("NUGET_PACKAGES",), default_root=(".nuget", "packages"),
    ),
    PackageManager.PUB: _EnvSpec(
        "store", env_vars=("PUB_CACHE",), default_root=(".pub-cache",),
    ),
    PackageManager.JULIA: _EnvSpec(
        "store", env_vars=("JULIA_DEPOT_PATH",), default_root=(".julia",),
    ),
    PackageManager.CABAL: _EnvSpec("store", default_root=(".cabal",)),
    PackageManager.ZIGMOD: _EnvSpec(
        "store", env_vars=("ZIG_GLOBAL_CACHE_DIR",), default_root=(".cache", "zig", "p"),
    ),
    PackageManager.OPAM: _EnvSpec("store", env_vars=("OPAMROOT",), default_root=(".opam",)),
    PackageManager.LUAROCKS: _EnvSpec("store", env_vars=("LUAROCKS",), default_root=(".luarocks",)),
    PackageManager.CPAN: _EnvSpec(
        "store", env_vars=("PERL5LIB",), default_root=("perl5", "lib", "perl5"),
    ),
}


def _resolve_store_env(spec: _EnvSpec) -> Path | None:
    """Resolve a user-store env: env-var override (pathsep lists supported)
    → home default root → first home glob match. None when nothing exists."""
    for var in spec.env_vars:
        val = os.environ.get(var)
        if not val:
            continue
        for entry in val.split(os.pathsep):
            if not entry:
                continue
            cand = Path(entry).joinpath(*spec.env_suffix) if spec.env_suffix else Path(entry)
            if cand.is_dir():
                return cand
    if spec.default_root:
        cand = Path.home().joinpath(*spec.default_root)
        if cand.is_dir():
            return cand
    for pattern in spec.default_globs:
        for cand in sorted(Path.home().glob(pattern)):
            if cand.is_dir():
                return cand
    return None


# dep-17 routing table: language → ThirdPartyIntrospector method name.
# None = no offline package store for this language ("no ecosystem") — the
# bundled stdlib tables are its coverage story; deps are skipped explicitly.
# hack is composer-backed (vendor/ scan) per the language coverage audit.
_LANGUAGE_INTROSPECTORS: dict[str, str | None] = {
    "python": "introspect_python",
    "javascript": "introspect_npm",
    "typescript": "introspect_npm",
    "rust": "introspect_crate",
    "go": "introspect_go_module",
    "java": "introspect_jar",
    "kotlin": "introspect_jar",
    "scala": "introspect_jar",
    "ruby": "introspect_gem",
    "php": "introspect_composer",
    "hack": "introspect_composer",
    "csharp": "introspect_nuget",
    "dart": "introspect_pub",
    "julia": "introspect_julia",
    "r": "introspect_cran",
    "haskell": "introspect_cabal",
    "swift": "introspect_spm",
    "zig": "introspect_zigmod",
    "erlang": "introspect_rebar3",
    "ocaml": "introspect_opam",
    "lua": "introspect_luarocks",
    "perl": "introspect_cpan",
    # No offline package store — bundled stdlib tables only:
    "bash": None,
    "verilog": None,
    "c": None,
    "cpp": None,
    "objc": None,
    "agda": None,
}


@dataclass
class DependencyIndexStats:
    manifests_found: int = 0
    deps_declared: int = 0
    deps_unique: int = 0
    deps_cached: int = 0
    deps_introspected: int = 0
    deps_gate_dropped: int = 0
    deps_manager_disabled: int = 0
    deps_skipped_no_env: int = 0
    deps_no_symbols: int = 0
    deps_no_ecosystem: int = 0
    symbols_indexed: int = 0
    stdlib_modules_indexed: int = 0
    duration_ms: float = 0.0
    errors: List[str] = field(default_factory=list)

class DependencyIndexer:
    """
    Orchestrates the full dependency indexing pipeline and populates the ScopeManager.
    """
    
    def __init__(
        self,
        root: Path,
        scope_manager: ScopeManager,
        cfg: Dict[str, Any],
        cache_dir: str | None = None,
    ) -> None:
        self.root = Path(root)
        self.scope_manager = scope_manager
        self.cfg = cfg
        self.stats = DependencyIndexStats()
        # Parsed manifest dep specs from run() — lets the workspace_manifests
        # emit reuse them instead of re-walking and re-parsing the tree.
        self.manifest_deps: List[DependencySpec] | None = None

        # Initialize components
        self.parser = ManifestParser()
        self.stdlib = StdlibSymbolTable()
        self.popular_db = PopularPackagesDB(
            db_path=Path(cfg.get("introspection", {}).get("popular_packages_db_path"))
            if cfg.get("introspection", {}).get("popular_packages_db_path") else None
        )
        self.introspector = ThirdPartyIntrospector(
            mode=cfg.get("introspection", {}).get("mode", "shallow"),
            timeout_seconds=cfg.get("introspection", {}).get("timeout_seconds", 5)
        )

        cache_path = root / cache_dir if cache_dir else root / ".batho" / "cache"
        self.cache = ResolutionCache(cache_path)

    def run(self) -> DependencyIndexStats:
        t0 = time.monotonic()
        
        try:
            # Detect and cache project metadata
            ManifestParser.detect_project_metadata(self.root, self.cache)
            
            # 1. Parse manifests
            manifests = self.parser.parse_manifests(self.root)
            self.manifest_deps = manifests
            self.stats.manifests_found = len(set(d.source_file for d in manifests))
            self.stats.deps_declared = len(manifests)
            
            # 2. Index Standard Libraries
            self._index_stdlib(manifests, file_languages=self._file_language_census())
            
            # 3. Index Third-party Dependencies (parallelized)
            self._index_dependencies_parallel(manifests)
                
        except Exception as e:
            logger.exception("Dependency indexing failed")
            self.stats.errors.append(f"{type(e).__name__}: {e}")
            
        self.stats.duration_ms = (time.monotonic() - t0) * 1000
        return self.stats

    def _file_language_census(self) -> Set[str]:
        """Source-file language census for stdlib scoping (spec T4).

        Manifest-derived detection misses languages the repo uses without a
        manifest (a JS monorepo with a Python tools dir and no pyproject) —
        those files' stdlib refs would resolve through another language's
        flat table (``import os`` → ``nodejs os/``).
        """
        from batho.utils.ignore import load_ignore_spec, walk_ignored_filtered
        from batho.modules.extraction.submodules.parser_factory.registry import (
            get_extractor,
        )

        langs: Set[str] = set()
        try:
            spec = load_ignore_spec(self.root)
            for _dirpath, _dirnames, filenames in walk_ignored_filtered(
                self.root, spec=spec
            ):
                for filename in filenames:
                    ext = Path(filename).suffix.lower()
                    if not ext:
                        continue
                    extractor = get_extractor(ext)
                    lang = getattr(extractor, "_language_name", None) if extractor else None
                    if lang:
                        langs.add(str(lang).lower())
        except Exception as exc:
            logger.debug("stdlib_file_census_failed", error=str(exc))
        return langs

    def _index_stdlib(
        self,
        manifests: List[DependencySpec] | None = None,
        file_languages: Set[str] | None = None,
    ):
        """Index standard library modules for enabled languages.

        Defaults to the languages detected in project manifests plus the
        source-file census rather than all 28 languages — a flat global
        namespace means shared module names (yaml, io, re, path, …) collide
        across languages and produce wrong-language resolutions. Explicit
        ``stdlib.languages`` config still overrides.
        """
        explicit = self.cfg.get("stdlib", {}).get("languages")
        if explicit:
            enabled_langs = explicit
        else:
            detected = {d.language for d in (manifests or [])}
            if file_languages:
                detected |= set(file_languages)
            # JS/TS share the node/web platform surface — register together
            if detected & {"javascript", "typescript"}:
                detected |= {"javascript", "typescript"}
            # JVM family: mixed Java/Kotlin/Scala projects compile jointly —
            # register all three surfaces when any is detected (G1)
            if detected & {"java", "kotlin", "scala"}:
                detected |= {"java", "kotlin", "scala"}
            enabled_langs = sorted(detected) if detected else ["python"]

        if not self.cfg.get("stdlib", {}).get("enabled", True):
            return

        # Batch add symbols to minimize lock contention
        # Tuples: (flat_name, namespaced_name, symbol_id, symbol_type)
        symbols_to_add: List[tuple[str, str, str, str]] = []
        registered_modules: Set[str] = set()

        for lang in enabled_langs:
            modules = self.stdlib.get_all_modules(lang)
            for mod_name, symbols in modules.items():
                self.stats.stdlib_modules_indexed += 1

                # Register module once per language
                module_key = f"{lang}:{mod_name}"
                if module_key not in registered_modules:
                    registered_modules.add(module_key)
                    module_id = f"batho stdlib {lang} {lang} {mod_name}/"
                    symbols_to_add.append((mod_name, f"{lang}:{mod_name}", module_id, "module"))

                for sym in symbols:
                    qualified_name = f"{mod_name}.{sym}"

                    # Language-specific symbol ID format
                    template = _STDLIB_SYMBOL_TEMPLATES.get(lang)
                    if template:
                        registry, runtime, version, suffix = template
                        symbol_id = f"batho {registry} {runtime} {version} {mod_name}/{sym}{suffix}"
                    else:
                        symbol_id = f"batho stdlib {lang} {lang} {mod_name}/{sym}."

                    symbols_to_add.append((qualified_name, f"{lang}:{qualified_name}", symbol_id, "function"))
                    self.stats.symbols_indexed += 1

        # Batch add all symbols at once (flat + namespaced keys share one id)
        for name, ns_name, symbol_id, sym_type in symbols_to_add:
            self.scope_manager.add_external_symbol(
                name=name,
                symbol_id=symbol_id,
                symbol_type=sym_type
            )
            self.scope_manager.add_external_symbol(
                name=ns_name,
                symbol_id=symbol_id,
                symbol_type=sym_type
            )

    def _index_dependencies_parallel(self, manifests: List[DependencySpec]) -> None:
        """Index dependencies in parallel using thread pool.

        Gate chain (pinned order — every unique dep reaches exactly one
        terminal bucket; specs/full-scan-declared-introspection/):

            ① cache     hit                                   → deps_cached
            ② popular   full_scan=false and not in popular DB  → deps_gate_dropped
            ③ managers  disabled by introspection.managers    → deps_manager_disabled
            ④ route     no offline store (bash/verilog/c/cpp/
                        objc/agda)                            → deps_no_ecosystem
            ⑤ env       skip_missing_env (default true) and
                        env not found                         → deps_skipped_no_env
            ⑥ introspect symbols found                        → deps_introspected
                        none found                            → deps_no_symbols

        full_scan contract: ``full_scan: true`` attempts every declared dep
        subject to gates ③④⑤; ``full_scan: false`` attempts only
        popular-DB members. ``full_scan`` is the ONLY declared-dep bypass —
        there is no dep.declared always-bypass (supersedes the
        stub-resolution-persistence T2 approach). Gate ② runs before ④, so
        a non-popular no-ecosystem dep counts as gate_dropped when
        full_scan=false and as no_ecosystem when full_scan=true (pinned
        attribution, D4). No {name: [name]} fallback stubs (dep-02).
        """
        if not manifests:
            return

        introspection_cfg = self.cfg.get("introspection", {}) or {}
        if not introspection_cfg.get("enabled", True):
            return

        # Filter to unique deps that need introspection. The dedup key is
        # scope-blind (manager:name:version) for FS-02 accounting, but all
        # declaring manifest dirs are kept in dep_scopes so cache/env checks
        # consult every scope — a dep that only exists in a sibling scope's
        # env must not collapse to a first-scope env-miss (issue e56b9d02a371).
        unique_deps: Dict[str, DependencySpec] = {}
        dep_scopes: Dict[str, List[DependencySpec]] = {}
        for dep in manifests:
            key = f"{dep.manager.value}:{dep.name}:{dep.version_spec}"
            dep_scopes.setdefault(key, []).append(dep)
            if key not in unique_deps:
                unique_deps[key] = dep
        self.stats.deps_unique = len(unique_deps)

        skip_missing_env = introspection_cfg.get("skip_missing_env", True)
        manager_overrides = self._validate_manager_overrides(introspection_cfg)

        # (dep, env, env_dep) — env_dep is the declaring scope whose env
        # satisfied the dep, so the cache write lands under that scope's key.
        deps_to_introspect: List[tuple[DependencySpec, Path | None, DependencySpec]] = []
        full_scan = introspection_cfg.get("full_scan", False)
        env_cache: Dict[tuple, Optional[Path]] = {}
        warned_managers: Set[str] = set()

        for key, dep in unique_deps.items():
            siblings = dep_scopes.get(key) or [dep]
            # ① Check cache first — scoped by the declaring manifest's dir so
            # the same dep/spec in different subproject envs stays distinct.
            # Consult every declaring scope: a cache hit under any of them
            # satisfies the dep.
            cached = None
            for sib in siblings:
                cached = self.cache.get_symbols(
                    dep.name, dep.version_spec, dep.manager.value,
                    scope=self._dep_scope_key(sib),
                )
                if cached:
                    break
            if cached:
                self.stats.deps_cached += 1
                self._add_symbols_to_scope(dep, cached)
                continue

            # ② Popular-DB gate (full_scan is the only declared-dep bypass)
            if not self.popular_db.should_introspect(dep.language, dep.name, full_scan):
                self.stats.deps_gate_dropped += 1
                logger.debug(
                    "introspection_gate_dropped",
                    language=dep.language, package=dep.name,
                    hint="set dependency.introspection.full_scan: true to attempt it",
                )
                continue

            # ③ Per-manager config override (core-01)
            if not manager_overrides.get(dep.manager.value, True):
                self.stats.deps_manager_disabled += 1
                logger.debug(
                    "introspection_manager_disabled",
                    manager=dep.manager.value, package=dep.name,
                )
                continue

            # ④ Route: no offline package store for this language (dep-17)
            if _LANGUAGE_INTROSPECTORS.get(dep.language) is None:
                self.stats.deps_no_ecosystem += 1
                logger.debug(
                    "introspection_no_ecosystem",
                    language=dep.language, package=dep.name,
                )
                continue

            # ⑤ Skip policy (D2): no env → no introspection attempt, no stub,
            # no cache pollution. Logged once per manager per build.
            # Consult every declaring scope's env — the deduped row may point
            # at a scope without an env while a sibling scope has one.
            env: Path | None = None
            env_dep = dep
            for sib in siblings:
                env = self._env_for_dep(sib, env_cache)
                if env is not None and env.exists():
                    env_dep = sib
                    break
            if skip_missing_env and (env is None or not env.exists()):
                self.stats.deps_skipped_no_env += 1
                if dep.manager.value not in warned_managers:
                    warned_managers.add(dep.manager.value)
                    logger.warning(
                        "introspection_skipped_no_env",
                        manager=dep.manager.value,
                        package=dep.name,
                        env_hint=str(env) if env is not None else "no environment found",
                    )
                continue

            # ⑥ Attempted — outcome recorded by the pool loop below
            deps_to_introspect.append((dep, env, env_dep))

        if not deps_to_introspect:
            self._assert_accounting_invariant()
            return

        # Introspect in parallel (I/O bound - safe to use threads)
        max_workers = min(4, len(deps_to_introspect))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._introspect_dep, dep, env): (dep, env_dep)
                for dep, env, env_dep in deps_to_introspect
            }

            for future in as_completed(futures):
                dep, env_dep = futures[future]
                try:
                    symbols_map = future.result()
                    if symbols_map:
                        self.stats.deps_introspected += 1
                        self.cache.put_symbols(
                            dep.name, dep.version_spec, dep.manager.value,
                            symbols_map, scope=self._dep_scope_key(env_dep),
                        )
                        self._add_symbols_to_scope(dep, symbols_map)
                    else:
                        # Attempted but produced no symbols — distinct from
                        # skipped-no-env (dep-02).
                        self.stats.deps_no_symbols += 1
                except Exception as e:
                    logger.warning(f"Failed to introspect {dep.name}: {e}")

        self._assert_accounting_invariant()

    def _assert_accounting_invariant(self) -> None:
        """Completeness invariant (FS-02): every unique declared dep reaches
        exactly one terminal bucket.

            deps_unique == deps_cached + deps_gate_dropped
                        + deps_manager_disabled + deps_no_ecosystem
                        + deps_skipped_no_env + deps_introspected
                        + deps_no_symbols

        Log-only — a mismatch means a future gate was added without a bucket
        (or an introspection exception escaped ``_introspect_dep``'s internal
        guard), which is exactly what we want to hear about.
        """
        accounted = (
            self.stats.deps_cached
            + self.stats.deps_gate_dropped
            + self.stats.deps_manager_disabled
            + self.stats.deps_no_ecosystem
            + self.stats.deps_skipped_no_env
            + self.stats.deps_introspected
            + self.stats.deps_no_symbols
        )
        if accounted != self.stats.deps_unique:
            logger.warning(
                "introspection_accounting_mismatch",
                unique=self.stats.deps_unique,
                accounted=accounted,
                cached=self.stats.deps_cached,
                gate_dropped=self.stats.deps_gate_dropped,
                manager_disabled=self.stats.deps_manager_disabled,
                no_ecosystem=self.stats.deps_no_ecosystem,
                skipped_no_env=self.stats.deps_skipped_no_env,
                introspected=self.stats.deps_introspected,
                no_symbols=self.stats.deps_no_symbols,
            )

    def _validate_manager_overrides(self, introspection_cfg: Dict[str, Any]) -> Dict[str, bool]:
        """Normalize per-manager enable overrides (core-01); unknown keys
        warn once and are ignored."""
        overrides = introspection_cfg.get("managers") or {}
        valid = {m.value for m in PackageManager}
        normalized: Dict[str, bool] = {}
        for key, val in overrides.items():
            if key not in valid:
                logger.warning("introspection_unknown_manager", manager=key)
                continue
            normalized[key] = bool(val)
        return normalized

    def _dep_scope_key(self, dep: DependencySpec) -> str:
        """Repo-relative dir of the declaring manifest — the cache key scope."""
        if not dep.source_file:
            return ""
        try:
            return Path(dep.source_file).parent.relative_to(self.root).as_posix()
        except (ValueError, OSError):
            return ""

    def _find_env_up(self, start: Path, markers: tuple[str, ...]) -> Path | None:
        """Walk ``start`` upward to ``self.root`` for the first existing marker dir.

        Bounded at the workspace root — never escapes the tree. Deps from the
        same manifest share an environment, so callers memoize per dir.
        """
        try:
            current = start.resolve()
            root = self.root.resolve()
            current.relative_to(root)
        except (OSError, ValueError):
            current, root = self.root, self.root
        while True:
            for marker in markers:
                candidate = current / marker
                if candidate.exists():
                    return candidate
            if current == root:
                break
            current = current.parent
        return None

    def _env_for_dep(
        self, dep: DependencySpec, env_cache: Dict[tuple, Optional[Path]]
    ) -> Path | None:
        """Resolve the toolchain env for a dep via ``_ENV_MATRIX`` (D1).

        project kind → walk up from the manifest dir for the first marker
        (bounded at root), then the spec's env-var/glob fallbacks;
        store kind → env-var override → home default root → home globs.
        Memoized per (manager, manifest dir). Returns None when nothing
        exists — the caller applies the skip policy.
        """
        key = (dep.manager.value, dep.source_file or "")
        if key in env_cache:
            return env_cache[key]
        try:
            start = Path(dep.source_file).parent if dep.source_file else self.root
        except (OSError, TypeError):
            start = self.root
        spec = _ENV_MATRIX.get(dep.manager)
        env: Path | None = None
        if spec is not None:
            if spec.kind == "project":
                env = self._find_env_up(start, spec.markers)
                if env is None and (spec.env_vars or spec.default_globs):
                    env = _resolve_store_env(spec)
            else:
                env = _resolve_store_env(spec)
        env_cache[key] = env
        return env

    def _find_venv(self) -> Path | None:
        """Find virtual environment path."""
        venv_paths = [
            self.root / ".venv",
            self.root / "venv",
            self.root / "env",
        ]
        for venv_path in venv_paths:
            if venv_path.exists():
                return venv_path
        return None

    def _introspect_dep(self, dep: DependencySpec, env_path: Path | None) -> Dict[str, List[str]]:
        """Introspect a single dependency via its language route (dep-17).

        Routes through ``_LANGUAGE_INTROSPECTORS`` with the uniform
        introspector signature (name, version_spec, env_path, project_root).
        No route → no introspection; no {name: [name]} fallback stubs (dep-02)
        — a dep that resolves no symbols returns {} and is counted by the
        caller as ``deps_no_symbols``.
        """
        introspection_enabled = self.cfg.get("introspection", {}).get("enabled", True)
        if not introspection_enabled:
            return {}

        route = _LANGUAGE_INTROSPECTORS.get(dep.language)
        if route is None:
            logger.debug(
                "introspection_no_route",
                language=dep.language, package=dep.name, reason="no_ecosystem",
            )
            return {}

        method = getattr(self.introspector, route, None)
        if method is None:
            return {}
        try:
            return method(dep.name, dep.version_spec, env_path, self.root)
        except Exception as e:
            logger.warning(
                "introspection_failed",
                package=dep.name, language=dep.language, error=str(e),
            )
            return {}

    def _add_symbols_to_scope(self, dep: DependencySpec, symbols_map: Dict[str, List[str]]):
        """Add symbols from a package to the scope manager (batched for performance).

        Registers each name twice: the flat key (legacy, last-writer-wins)
        and a ``{language}:{name}`` namespaced key that language-hinted
        resolution prefers (T5).
        """
        symbols_to_add: List[tuple[str, str, str, str]] = []  # (flat, namespaced, id, type)
        registered_modules: Set[str] = set()
        suffix = "()." if dep.language == "python" else "#"

        for mod_path, symbols in symbols_map.items():
            # Register module once
            if mod_path not in registered_modules:
                registered_modules.add(mod_path)
                symbols_to_add.append((
                    mod_path,
                    f"{dep.language}:{mod_path}",
                    f"batho {dep.manager.value} {dep.name} {dep.version_spec} {mod_path}/",
                    "module"
                ))

            for sym in symbols:
                qualified_name = f"{mod_path}.{sym}"
                symbol_id = f"batho {dep.manager.value} {dep.name} {dep.version_spec} {mod_path}/{sym}{suffix}"
                symbols_to_add.append((qualified_name, f"{dep.language}:{qualified_name}", symbol_id, "external"))
                self.stats.symbols_indexed += 1

        # Batch add all symbols (flat + namespaced keys share one SymbolInfo)
        for name, ns_name, symbol_id, sym_type in symbols_to_add:
            self.scope_manager.add_external_symbol(
                name=name,
                symbol_id=symbol_id,
                symbol_type=sym_type
            )
            self.scope_manager.add_external_symbol(
                name=ns_name,
                symbol_id=symbol_id,
                symbol_type=sym_type
            )

def build_dependency_index(
    root: Path,
    scope_manager: ScopeManager,
    cfg: Dict[str, Any],
    cache_dir: str | None = None,
) -> DependencyIndexStats:
    """Convenience function — the primary integration point for build/patch."""
    return DependencyIndexer(root, scope_manager, cfg, cache_dir=cache_dir).run()


def build_workspace_manifest_rows(
    root: Path, deps: List[DependencySpec] | None = None
) -> List[Dict[str, Any]]:
    """Build rows for the ``workspace_manifests`` artifact table.

    Emits one ``workspace`` row per manifest that yields package metadata
    (depth-major — the first is ``kind="primary"``) plus one ``dependency``
    row per declared dep, tagged with its declaring manifest's provenance and
    content hash. Cheap: manifest parsing only — no introspection.

    ``deps`` may carry dependency specs already parsed by DependencyIndexer
    (build/patch just ran it); when omitted they are parsed from disk here.
    """
    root = Path(root)
    hashes: dict[str, str] = {}

    def _hash(path: Path) -> str:
        key = str(path)
        if key not in hashes:
            try:
                hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                hashes[key] = ""
        return hashes[key]

    def _rel(path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)

    rows: List[Dict[str, Any]] = []

    primary_taken = False
    for _depth, _rank, _key, path in ManifestParser._metadata_candidates(root):
        meta = ManifestParser._parse_metadata_for(path)
        if not meta:
            continue
        rows.append({
            "scope": "workspace",
            "manager": meta.manager.value,
            "name": meta.name,
            "version": meta.version,
            "kind": "subproject" if primary_taken else "primary",
            "source_file": _rel(path),
            "manifest_dir": _rel(path.parent) or ".",
            "language": None,
            "content_hash": _hash(path),
        })
        primary_taken = True

    for dep in (deps if deps is not None else ManifestParser().parse_manifests(root)):
        src = Path(dep.source_file) if dep.source_file else None
        rows.append({
            "scope": "dependency",
            "manager": dep.manager.value,
            "name": dep.name,
            "version": dep.version_spec,
            "kind": dep.kind,
            "source_file": _rel(src) if src else "",
            "manifest_dir": _rel(src.parent) if src else "",
            "language": dep.language,
            "content_hash": _hash(src) if src else "",
        })

    return rows
