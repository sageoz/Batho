"""Entity endpoint resolution for MCP graph tools.

The .batho artifact stores relationships at symbol level, keyed by the
*referencing* file's ``file_id``. Cross-file references appear as stub targets:

    unresolved:[<pkg> ]<caller_scope>::<dotted_target_fqn>

The ref key is dot-normalized at extraction time (``_stub_ref_key`` in
``extractor.py``), so ``::`` occurs exactly once — at the scope/ref boundary.
Legacy artifacts may embed ``::`` inside the ref key (e.g. Rust
``unresolved:scope::std::io::Write``); :func:`stub_fqn` then returns only the
last segment (legacy behavior, scope context lost — a rebuild normalizes).
Markup/structural IDs are path-embedded:

    ent|TYPE|/abs/path|start_byte|end_byte|sline|eline|name

:class:`EndpointResolver` maps any edge endpoint to its defining file so tools
like ``graph_query`` / ``get_file_graph`` / ``file_connectivity`` can answer
file-level connectivity questions in both directions.

Resolution order (order matters — stubs are also materialized in ``agent_views``
under the *referencing* file, so the stub check must precede the entity-index
lookup or every cross-file edge collapses to intra-file):

0. persisted build-time resolution (``stub_resolution_state=resolved`` with a
   valid ``resolved_target_id``) → the concrete defining entity
   (``kind="persisted"``)
1. ``unresolved:`` stub → dotted FQN → longest-prefix match against indexed
   module paths (``kind="module"``)
2. ``unresolved:`` whose first FQN segment is a known stdlib/external module
   (``kind="external_stdlib"``, no path)
3. ``ent|`` markup ID → embedded path (``kind="embedded"``)
4. plain entity_id present in ``agent_views`` (``kind="direct"``)
5. last-resort symbol-name match among defined entities (``kind="name"``) —
   bare single-segment names only when globally unique
6. otherwise ``kind="external_unresolved"``
"""

from __future__ import annotations

import json
import re
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.compute as pc

from batho.core.schemas import PackageManager
from batho.mcp.graph_builder import normalize_legacy_rel_rows
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="entity_resolution")

KIND_DIRECT = "direct"
KIND_EMBEDDED = "embedded"
KIND_MODULE = "module"
KIND_NAME = "name"
KIND_PERSISTED = "persisted"
KIND_EXTERNAL_STDLIB = "external_stdlib"
KIND_EXTERNAL_UNRESOLVED = "external_unresolved"
KIND_EXTERNAL_PACKAGE = "external_package"

# Resolved external symbol namespaces minted by DependencyIndexer:
#   batho stdlib <lang> <ns> <mod>[/<sym>]  e.g. "batho stdlib python python os/"
#   batho <manager> <dep> <spec> <mod>[/<sym>] — one prefix per PackageManager
#   (pip, npm, cargo, go, maven, gradle, gem, composer, nuget, pub, julia,
#   cran, cabal, spm, zigmod, rebar3, opam, luarocks, cpan, agda). Derived
#   from the enum so newly-added managers classify external automatically.
_EXTERNAL_PACKAGE_PREFIXES = tuple(
    f"batho {m.value} " for m in PackageManager
)
_EXTERNAL_STDLIB_PREFIX = "batho stdlib "
# DependencyIndexer's stdlib branch also mints ids through the pip-style
# namespace for the language runtime itself ("batho pip python 3.x <mod>/…").
# Checked BEFORE the package prefixes so stdlib classifies as stdlib.
_EXTERNAL_STDLIB_PREFIXES: tuple[str, ...] = (
    _EXTERNAL_STDLIB_PREFIX,
    "batho pip python ",
)
# Synthetic file paths — never valid resolution targets for file-level tools.
_PSEUDO_FILE_PATHS = frozenset({"", ".", "__external_symbols__"})


# Entity display names carry a parameter-hash suffix: ``helper_[ef2e96]``.
# Stub FQNs reference the base name, so the name index needs the stripped
# form as an alias (same pattern as scope_manager._PARAM_HASH_PATTERN).
_ENTITY_NAME_HASH = re.compile(r"_\[[a-fA-F0-9]+\]")


def is_unresolved(entity_id: str) -> bool:
    """True for quarantined `unresolved:` reference stubs (T2).

    These entities stay in storage for provenance but are excluded from
    default query surfaces (search_entities, graph_query, graph_overview)
    unless the caller passes ``include_unresolved=true``.
    """
    return entity_id.startswith("unresolved:")


def external_ref_root(entity_id: str) -> str:
    """Root name of an external reference for reporting.

    Handles both shapes: ``unresolved:`` stubs (dotted FQN, root = first
    segment) and resolved external ids (``batho stdlib <lang> <ns> <mod>``
    or ``batho <ns> <dep> <spec> <mod>``, root = module/dep name).
    """
    if is_unresolved(entity_id):
        return stub_fqn(entity_id).split(".")[0]
    for stdlib_prefix in _EXTERNAL_STDLIB_PREFIXES:
        if entity_id.startswith(stdlib_prefix):
            toks = entity_id.split()
            if len(toks) > 4:
                return toks[4].split("/")[0].rstrip("/")
    else:
        for prefix in _EXTERNAL_PACKAGE_PREFIXES:
            if entity_id.startswith(prefix):
                toks = entity_id.split()
                if len(toks) > 2:
                    return toks[2]
    return ""

_STDLIB_PREFIXES = frozenset({
    "abc", "argparse", "array", "ast", "asyncio", "atexit", "base64", "binascii",
    "bisect", "builtins", "bz2", "calendar", "cmath", "collections", "concurrent",
    "contextlib", "contextvars", "copy", "copyreg", "csv", "ctypes", "dataclasses",
    "datetime", "decimal", "difflib", "dis", "doctest", "email", "enum", "errno",
    "faulthandler", "filecmp", "fileinput", "fnmatch", "fractions", "ftplib",
    "functools", "gc", "getopt", "getpass", "gettext", "glob", "graphlib", "gzip",
    "hashlib", "heapq", "hmac", "html", "http", "imaplib", "importlib", "inspect",
    "io", "ipaddress", "itertools", "json", "keyword", "linecache", "locale",
    "logging", "lzma", "mailbox", "math", "mimetypes", "mmap", "multiprocessing",
    "numbers", "operator", "os", "pathlib", "pdb", "pickle", "pickletools",
    "pkgutil", "platform", "plistlib", "pprint", "profile", "pstats", "pty",
    "queue", "quopri", "random", "re", "readline", "reprlib", "resource",
    "rlcompleter", "runpy", "sched", "secrets", "select", "selectors", "shelve",
    "shlex", "shutil", "signal", "site", "smtplib", "socket", "socketserver",
    "sqlite3", "ssl", "stat", "statistics", "string", "struct", "subprocess",
    "symtable", "sys", "sysconfig", "tarfile", "tempfile", "termios", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "traceback", "tracemalloc",
    "types", "typing", "unicodedata", "unittest", "urllib", "uuid", "venv",
    "warnings", "wave", "weakref", "webbrowser", "wsgiref", "xml", "xmlrpc",
    "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
    "node", "browser", "std",
    # Rust std crates (module-index match runs first, so an indexed local
    # module with one of these names always wins over the stdlib bucket).
    "core", "alloc", "proc_macro",
})

_INIT_STEMS = frozenset({"__init__", "index", "mod"})

_CODE_SUFFIXES = frozenset({
    ".py", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".swift", ".cs", ".php", ".rb",
})


def _module_for_path(file_path: str) -> str | None:
    p = Path(file_path)
    if p.suffix not in _CODE_SUFFIXES:
        return None
    if p.stem in _INIT_STEMS:
        return ".".join(p.parent.parts) if p.parent.parts else None
    return ".".join([*p.parent.parts, p.stem])


def _persisted_stub_target(stub_id: str, metadata_json: str | None) -> str | None:
    """Concrete target recorded at build time, if valid.

    Reads the T5 persistence contract off a stub's metadata:
    ``stub_resolution_state=resolved`` plus a ``resolved_target_id`` that is
    neither the stub itself nor another stub. Polluted artifacts (stub→stub /
    self-resolutions) are treated as absent — the read-time heuristics then
    apply.
    """
    if not metadata_json:
        return None
    try:
        meta = json.loads(metadata_json)
    except (ValueError, TypeError):
        return None
    if meta.get("stub_resolution_state") != "resolved":
        return None
    target = meta.get("resolved_target_id")
    if not target or target == stub_id or target.startswith("unresolved:"):
        return None
    return target


def stub_fqn(eid: str) -> str:
    """Dotted FQN carried by an ``unresolved:`` stub ID.

    Stub IDs have the form ``unresolved:[<pkg> ]<caller_scope>::<ref_key>``.
    The ref key is dot-normalized at extraction time (``_stub_ref_key``), so
    the single ``::`` separates caller scope from the dotted target FQN.
    Legacy artifacts may embed ``::`` inside the ref key (e.g. Rust
    ``unresolved:scope::std::io::Write``); for those, the last segment is
    returned — the documented legacy behavior (scope context is lost).
    """
    if "::" in eid:
        return eid.rsplit("::", 1)[-1].strip()
    scope = eid[len("unresolved:"):].strip()
    if " " in scope:
        scope = scope.split(" ", 1)[1]
    scope = scope.split("#", 1)[0].split("(", 1)[0].strip()
    return scope.replace("/", ".")


@dataclass(frozen=True)
class ResolvedTarget:
    """Result of resolving one edge endpoint to a defining file."""

    entity_id: str
    file_id: int | None
    path: str | None
    kind: str


class EndpointResolver:
    """Resolves relationship endpoints (entity IDs / stubs) to defining files.

    One instance per :class:`BathoBundleReader`. Indexes are built lazily on
    first use and rebuilt automatically when the artifact manifest generation
    changes (e.g. after ``batho patch``), so no MCP restart is needed.
    """

    def __init__(self, reader: Any) -> None:
        self._reader = reader
        self._lock = threading.RLock()
        self._generation: int | None = None
        self._entity_file: dict[str, int] = {}
        self._name_by_id: dict[str, str] = {}
        self._name_index: dict[str, list[tuple[str, int]]] = {}
        self._module_index: dict[str, int] = {}
        self._file_paths: dict[int, str] = {}
        self._path_to_fid: dict[str, int] = {}
        self._repo_root = ""
        self._own_packages: set[tuple[str, str]] = set()
        self._cross_file_edges: list[tuple[dict, int, int]] | None = None
        # Persisted build-time resolution (T5 contract): stub_id ->
        # resolved_target_id, for stubs whose metadata carries
        # stub_resolution_state=resolved and a non-stub target.
        self._stub_target: dict[str, str] = {}
        # Reverse map: concrete target_id -> [stub_id, ...] (artifact order).
        self._refs_by_target: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _generation_now(self) -> int:
        try:
            return int(self._reader.get_manifest().get("generation", 0))
        except Exception:
            return 0

    def _ensure_indexes(self) -> None:
        with self._lock:
            gen = self._generation_now()
            if self._generation == gen and self._entity_file:
                return

            # File tracking first — the agent pass needs pseudo-file
            # classification (`.`, `__external_symbols__`) to keep
            # externals out of the name index.
            file_paths: dict[int, str] = {}
            path_to_fid: dict[str, int] = {}
            module_index: dict[str, int] = {}
            tracking = self._reader.get_all_file_tracking()
            for fp, tr in tracking.items():
                fid = tr.get("file_id")
                if fid is None:
                    continue
                file_paths[fid] = fp
                path_to_fid[fp] = fid
                mod = _module_for_path(fp)
                if mod:
                    module_index.setdefault(mod, fid)

            entity_file: dict[str, int] = {}
            name_by_id: dict[str, str] = {}
            name_index: dict[str, list[tuple[str, int]]] = {}
            stub_target: dict[str, str] = {}
            refs_by_target: dict[str, list[str]] = {}
            pending_stub_targets: list[tuple[str, str]] = []
            agent = self._reader._get_table("agent_views")
            if agent.num_rows > 0:
                # Project only the columns the indexes need — a full
                # to_pylist() materializes every column of agent_views
                # (raw_content, ast_node_type, ...) on large repos (2a4c6e8b).
                names = agent.schema.names
                ids = agent.column("entity_id").to_pylist() if "entity_id" in names else []
                fids = agent.column("file_id").to_pylist() if "file_id" in names else []
                nms = agent.column("name").to_pylist() if "name" in names else []
                etypes = agent.column("entity_type").to_pylist() if "entity_type" in names else []
                metas = (
                    agent.column("metadata_json").to_pylist()
                    if "metadata_json" in names
                    else [None] * agent.num_rows
                )
                for eid, fid, nm, etype, meta_str in zip(ids, fids, nms, etypes, metas):
                    if not eid:
                        continue
                    entity_file[eid] = fid
                    name_by_id[eid] = nm
                    if not eid.startswith("unresolved:"):
                        fpath = file_paths.get(fid, "")
                        # Externals (pseudo-files / EXTERNAL_SYMBOL rows) must
                        # never serve as name-match targets — the KIND_NAME
                        # fallback would link bare names like `config` to
                        # unrelated files.
                        if nm and etype != "EXTERNAL_SYMBOL" and fpath not in _PSEUDO_FILE_PATHS:
                            name_index.setdefault(nm, []).append((eid, fid))
                            base_nm = _ENTITY_NAME_HASH.sub("", nm)
                            if base_nm != nm:
                                name_index.setdefault(base_nm, []).append((eid, fid))
                    elif nm:
                        # Persisted build-time resolution wins over the
                        # read-time heuristics below (T5 contract). Deferred:
                        # the target's row may appear later in the table, so
                        # membership is checked in a second pass below.
                        resolved = _persisted_stub_target(eid, meta_str)
                        if resolved:
                            pending_stub_targets.append((eid, resolved))

            for eid, resolved in pending_stub_targets:
                if resolved in entity_file:
                    stub_target[eid] = resolved
                    refs_by_target.setdefault(resolved, []).append(eid)

            # __init__/index/mod files define their package module; let them
            # win over same-named module files so `pkg.symbol` resolves into
            # the package even when the symbol itself has no entity.
            for fp, tr in tracking.items():
                fid = tr.get("file_id")
                if fid is not None and Path(fp).stem in _INIT_STEMS:
                    mod = _module_for_path(fp)
                    if mod:
                        module_index[mod] = fid

            self._entity_file = entity_file
            self._name_by_id = name_by_id
            self._name_index = name_index
            self._stub_target = stub_target
            self._refs_by_target = refs_by_target
            self._file_paths = file_paths
            self._path_to_fid = path_to_fid
            self._module_index = module_index
            self._repo_root = self._detect_repo_root()
            for fid, fp in file_paths.items():
                if self._repo_root:
                    path_to_fid.setdefault(f"{self._repo_root}/{fp}", fid)
            self._own_packages = self._load_own_packages()
            self._generation = gen
            self._cross_file_edges = None

    def _load_own_packages(self) -> set[tuple[str, str]]:
        """Workspace own-package identities from the workspace_manifests table.

        Returns ``{(manager, name)}`` for ``scope='workspace'`` rows. Empty
        when the table is absent (pre-T8 artifacts) — callers then fall back
        to prefix-only classification.
        """
        try:
            rows = self._reader.get_workspace_manifests()
        except Exception:
            return set()
        own: set[tuple[str, str]] = set()
        for row in rows or []:
            if row.get("scope") == "workspace" and row.get("name"):
                own.add((row.get("manager", ""), row["name"]))
        return own

    def _detect_repo_root(self) -> str:
        try:
            latest = self._reader.get_latest_run_id()
            if latest:
                run = self._reader.get_run(latest)
                if run:
                    return str(run.get("root_path", "")).rstrip("/")
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, entity_id: str) -> ResolvedTarget:
        """Resolve one edge endpoint to its defining file."""
        self._ensure_indexes()
        if entity_id.startswith("unresolved:"):
            return self._resolve_stub(entity_id)
        # Resolved external symbols materialize under the synthetic
        # "__external_symbols__" file — classify them as external so
        # file-level tools don't report a bogus intra-repo dependency.
        # Stdlib prefixes are checked BEFORE the package prefixes: the
        # pip-style runtime namespace ("batho pip python 3.x …") is
        # otherwise classified as a third-party package.
        for stdlib_prefix in _EXTERNAL_STDLIB_PREFIXES:
            if entity_id.startswith(stdlib_prefix):
                return ResolvedTarget(entity_id, None, None, KIND_EXTERNAL_STDLIB)
        if entity_id.startswith(_EXTERNAL_PACKAGE_PREFIXES):
            # T2: own-workspace packages classify DIRECT by own-set
            # membership — an entity id whose package triple belongs to a
            # workspace manifest (e.g. `batho npm docs-site …` for the
            # docs-site subproject) is intra-repo, not third-party.
            if self._own_packages and self._is_own_package_id(entity_id):
                fid = self._entity_file.get(entity_id)
                return ResolvedTarget(
                    entity_id, fid,
                    self._file_paths.get(fid) if fid is not None else None,
                    KIND_DIRECT,
                )
            # A materialized file row wins over own-set membership — the table
            # may be empty (pre-T8 artifacts, dep-disabled builds) or filtered
            # by workspace.manifest_dirs so this triple is absent. Either way
            # an entity with a real file row is intra-repo; pseudo-file rows
            # (__external_symbols__, '.') and absent rows classify external
            # (issue 1f6d3a08b7c2).
            fid = self._entity_file.get(entity_id)
            if fid is not None:
                fpath = self._file_paths.get(fid)
                if fpath and fpath != "__external_symbols__" and fpath != ".":
                    return ResolvedTarget(entity_id, fid, fpath, KIND_DIRECT)
            return ResolvedTarget(entity_id, None, None, KIND_EXTERNAL_PACKAGE)
        if entity_id.startswith("ent|"):
            parts = entity_id.split("|")
            if len(parts) > 2:
                fid = self._path_to_fid.get(parts[2])
                return ResolvedTarget(entity_id, fid, parts[2], KIND_EMBEDDED)
        fid = self._entity_file.get(entity_id)
        if fid is not None:
            return ResolvedTarget(entity_id, fid, self._file_paths.get(fid), KIND_DIRECT)
        return ResolvedTarget(entity_id, None, None, KIND_EXTERNAL_UNRESOLVED)

    def _is_own_package_id(self, entity_id: str) -> bool:
        """True when the entity id's package triple is a workspace package.

        Matches on ``(manager, name)`` — robust to version-format drift
        between id strings and manifest rows.
        """
        toks = entity_id.split()
        if len(toks) < 4 or toks[0] != "batho":
            return False
        return (toks[1], toks[2]) in self._own_packages

    def _resolve_stub(self, eid: str) -> ResolvedTarget:
        # 0. Persisted build-time resolution wins — richer strategies ran at
        # build with the full graph in hand (receiver typing, reexports,
        # package aliases). Polluted entries are filtered at index time.
        persisted = self._stub_target.get(eid)
        if persisted is not None:
            fid = self._entity_file.get(persisted)
            return ResolvedTarget(
                persisted, fid, self._file_paths.get(fid) if fid is not None else None,
                KIND_PERSISTED,
            )
        fqn = stub_fqn(eid)
        if not fqn:
            return ResolvedTarget(eid, None, None, KIND_EXTERNAL_UNRESOLVED)
        parts = fqn.split(".")
        for i in range(len(parts) - 1, 0, -1):
            fid = self._module_index.get(".".join(parts[:i]))
            if fid is not None:
                return ResolvedTarget(eid, fid, self._file_paths.get(fid), KIND_MODULE)
        if parts[0] in _STDLIB_PREFIXES:
            return ResolvedTarget(eid, None, None, KIND_EXTERNAL_STDLIB)
        candidates = self._name_index.get(parts[-1], [])
        if candidates:
            # Bare single-segment names (`config`, `build`, `sorted`) are too
            # ambiguous for a name match across files — accept only a unique
            # global candidate; multi-segment FQNs keep the scoped ranking.
            if len(parts) == 1 and len(candidates) > 1:
                return ResolvedTarget(eid, None, None, KIND_EXTERNAL_UNRESOLVED)
            # 7e9a1c3b: multiple files may define the same symbol name. Prefer
            # the candidate whose module path longest-prefix-matches the
            # stub's FQN scope (stub `pkg.mod.symbol` prefers `pkg/mod.py`
            # over `other/symbol.py`); ties keep deterministic artifact order
            # (first defined wins).
            scope_segs = parts[:-1]
            best_shared = -1
            best_fid: int | None = None
            for _ceid, cfid in candidates:
                cmod = _module_for_path(self._file_paths.get(cfid) or "") or ""
                shared = 0
                if cmod and scope_segs:
                    for a, b in zip(cmod.split("."), scope_segs):
                        if a != b:
                            break
                        shared += 1
                if shared > best_shared:
                    best_shared = shared
                    best_fid = cfid
            return ResolvedTarget(eid, best_fid, self._file_paths.get(best_fid), KIND_NAME)
        return ResolvedTarget(eid, None, None, KIND_EXTERNAL_UNRESOLVED)

    def resolve_symbol(self, entity_id: str) -> str | None:
        """Best-effort mapping of a stub ID to a concrete defined entity_id."""
        target = self.resolve(entity_id)
        if target.kind == KIND_PERSISTED:
            return target.entity_id
        if target.kind not in (KIND_MODULE, KIND_NAME) or target.file_id is None:
            return None
        fqn = stub_fqn(entity_id)
        last = fqn.rsplit(".", 1)[-1] if fqn else ""
        for ceid, cfid in self._name_index.get(last, []):
            if cfid == target.file_id:
                return ceid
        return None

    def stub_refs_for(self, entity_id: str) -> list[str]:
        """Stub ids whose build-time resolution points at ``entity_id``."""
        self._ensure_indexes()
        return self._refs_by_target.get(entity_id, [])

    def resolve_dotted(self, dotted: str) -> str | None:
        """Concrete entity_id for a dotted path like ``pkg.mod.Name``.

        Longest-prefix match against indexed module paths, then an exact
        name (or parameter-hash alias) match within that module's file.
        Returns None for bare names, unknown modules, or missing symbols.
        """
        self._ensure_indexes()
        if "." not in dotted:
            return None
        parts = dotted.split(".")
        for i in range(len(parts) - 1, 0, -1):
            fid = self._module_index.get(".".join(parts[:i]))
            if fid is None:
                continue
            # Everything after the module prefix is the entity's dotted
            # (possibly parent-qualified nested) name.
            leaf = ".".join(parts[i:])
            for ceid, cfid in self._name_index.get(leaf, []):
                if cfid == fid:
                    return ceid
            return None
        return None

    def persisted_target(self, stub_id: str) -> str | None:
        """Build-time resolved target for a stub, if recorded and valid."""
        self._ensure_indexes()
        return self._stub_target.get(stub_id)

    # ------------------------------------------------------------------
    # Lookups over built indexes
    # ------------------------------------------------------------------

    def file_id_for(self, entity_id: str) -> int | None:
        return self.resolve(entity_id).file_id

    def path_for_file(self, file_id: int) -> str | None:
        self._ensure_indexes()
        return self._file_paths.get(file_id)

    def name_for(self, entity_id: str) -> str:
        self._ensure_indexes()
        return self._name_by_id.get(entity_id, "")

    def cross_file_edges(self) -> list[tuple[dict, int, int]]:
        """Edges whose endpoints resolve to different files, cached per generation.

        Each item is ``(rel_row, source_file_id, target_file_id)``. CONTAINS
        edges are excluded (structural containment, not a dependency), including
        legacy ``CONTAINED_WITHIN`` rows after T15 re-classification.
        """
        self._ensure_indexes()
        with self._lock:
            if self._cross_file_edges is not None:
                return self._cross_file_edges
            rels = self._reader._get_table("rels_views")
            out: list[tuple[dict, int, int]] = []
            if rels.num_rows > 0:
                # Project only the columns consumers use (relation_type,
                # confidence, target_id, file_id) plus source_id (needed by
                # normalize_legacy_rel_rows for the endpoint swap), and
                # pre-filter containment (forward CONTAINS and legacy
                # CONTAINED_WITHIN) via Arrow compute — a full to_pylist()
                # materializes every column of rels_views per generation
                # (2a4c6e8b).
                proj_cols = [c for c in ("file_id", "source_id", "target_id", "relation_type", "confidence") if c in rels.schema.names]
                proj = rels.select(proj_cols)
                if "relation_type" in proj_cols:
                    # Exclude structural containment in both spellings. The
                    # other legacy inverse types (CALLED_BY, IMPORTED_BY,
                    # REFERENCED_IN) are real dependencies — they are kept
                    # and re-classified below.
                    rt_col = proj.column("relation_type")
                    mask = pc.not_equal(rt_col, "CONTAINS")
                    mask = pc.and_(mask, pc.not_equal(rt_col, "CONTAINED_WITHIN"))
                    proj = proj.filter(mask)
                # T15 (8d4f2a91): re-classify legacy inverse types (forward
                # type + swapped endpoints) so file_connectivity and
                # get_file_graph file_dependencies report forward type keys
                # on pre-T15 artifacts, matching the Relationship model.
                for rel in normalize_legacy_rel_rows(proj.to_pylist()):
                    sf = rel.get("file_id")
                    tf = self.resolve(rel.get("target_id", "")).file_id
                    if sf is None or tf is None or sf == tf:
                        continue
                    out.append((rel, sf, tf))
            self._cross_file_edges = out
            return out


_resolvers: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_resolvers_lock = threading.Lock()


def get_resolver(reader: Any) -> EndpointResolver:
    """Return the cached :class:`EndpointResolver` for a reader (lazily created)."""
    with _resolvers_lock:
        resolver = _resolvers.get(reader)
        if resolver is None:
            resolver = EndpointResolver(reader)
            _resolvers[reader] = resolver
        return resolver


def redirect_endpoint(
    resolver: EndpointResolver, entity_id: str, cache: dict[str, str]
) -> str:
    """Rewire one stub endpoint to its resolved definition (T20, shared).

    Used by every graph tool so a stub target like
    ``unresolved:…::pkg.mod.symbol`` becomes the defining entity, turning
    cross-file refs into traversable/reportable edges. Non-stub ids pass
    through untouched. ``cache`` memoizes per call site (caller-owned).
    """
    if not is_unresolved(entity_id):
        return entity_id
    hit = cache.get(entity_id)
    if hit is None:
        hit = resolver.resolve_symbol(entity_id) or entity_id
        cache[entity_id] = hit
    return hit
