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

1. ``unresolved:`` stub → dotted FQN → longest-prefix match against indexed
   module paths (``kind="module"``)
2. ``unresolved:`` whose first FQN segment is a known stdlib/external module
   (``kind="external_stdlib"``, no path)
3. ``ent|`` markup ID → embedded path (``kind="embedded"``)
4. plain entity_id present in ``agent_views`` (``kind="direct"``)
5. last-resort symbol-name match among defined entities (``kind="name"``)
6. otherwise ``kind="external_unresolved"``
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.compute as pc

from batho.mcp.graph_builder import normalize_legacy_rel_rows
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="entity_resolution")

KIND_DIRECT = "direct"
KIND_EMBEDDED = "embedded"
KIND_MODULE = "module"
KIND_NAME = "name"
KIND_EXTERNAL_STDLIB = "external_stdlib"
KIND_EXTERNAL_UNRESOLVED = "external_unresolved"

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
        self._cross_file_edges: list[tuple[dict, int, int]] | None = None

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

            entity_file: dict[str, int] = {}
            name_by_id: dict[str, str] = {}
            name_index: dict[str, list[tuple[str, int]]] = {}
            agent = self._reader._get_table("agent_views")
            if agent.num_rows > 0:
                # Project only the columns the indexes need — a full
                # to_pylist() materializes every column of agent_views
                # (raw_content, ast_node_type, ...) on large repos (2a4c6e8b).
                names = agent.schema.names
                ids = agent.column("entity_id").to_pylist() if "entity_id" in names else []
                fids = agent.column("file_id").to_pylist() if "file_id" in names else []
                nms = agent.column("name").to_pylist() if "name" in names else []
                for eid, fid, nm in zip(ids, fids, nms):
                    if eid:
                        entity_file[eid] = fid
                        name_by_id[eid] = nm
                        # Stubs are materialized under the referencing file;
                        # they must never serve as resolution targets.
                        if nm and not eid.startswith("unresolved:"):
                            name_index.setdefault(nm, []).append((eid, fid))

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
            self._file_paths = file_paths
            self._path_to_fid = path_to_fid
            self._module_index = module_index
            self._repo_root = self._detect_repo_root()
            for fid, fp in file_paths.items():
                if self._repo_root:
                    path_to_fid.setdefault(f"{self._repo_root}/{fp}", fid)
            self._generation = gen
            self._cross_file_edges = None

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
        if entity_id.startswith("ent|"):
            parts = entity_id.split("|")
            if len(parts) > 2:
                fid = self._path_to_fid.get(parts[2])
                return ResolvedTarget(entity_id, fid, parts[2], KIND_EMBEDDED)
        fid = self._entity_file.get(entity_id)
        if fid is not None:
            return ResolvedTarget(entity_id, fid, self._file_paths.get(fid), KIND_DIRECT)
        return ResolvedTarget(entity_id, None, None, KIND_EXTERNAL_UNRESOLVED)

    def _resolve_stub(self, eid: str) -> ResolvedTarget:
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
        if target.kind not in (KIND_MODULE, KIND_NAME) or target.file_id is None:
            return None
        fqn = stub_fqn(entity_id)
        last = fqn.rsplit(".", 1)[-1] if fqn else ""
        for ceid, cfid in self._name_index.get(last, []):
            if cfid == target.file_id:
                return ceid
        return None

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
