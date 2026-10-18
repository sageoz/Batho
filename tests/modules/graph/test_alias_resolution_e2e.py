"""T11 e2e: import-path ≠ file-path namespaces resolve via derived roots.

Fixtures mirror sageoz: ``backend/app/`` where ``backend/`` is a plain dir
and ``app`` is the real package (``__init__.py`` evidence). Also covers the
PEP-420 namespace fallback (no markers anywhere → suffix alignment) and
tsconfig ``paths`` aliases (``@/`` → ``src/``).
"""

import json
from pathlib import Path

import pytest

from batho.orchestrator.build import run_build, BuildOptions
from batho.modules.storage.arrow_bundle.reader import BathoBundleReader


def _write(root: Path, rel: str, content: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def _rels(reader: BathoBundleReader, rel_type: str):
    rows = reader._get_table("rels_views").to_pylist()
    return [r for r in rows if r.get("relation_type") == rel_type]


def _unresolved_targets(reader: BathoBundleReader) -> list[str]:
    """Ref keys of *edges* still pointing at unresolved ghosts.

    Stub entities persist in storage by design (T2 quarantine) — the signal
    is whether any relationship still targets them.
    """
    rels = reader._get_table("rels_views").to_pylist()
    return [
        r["target_id"].rsplit("::", 1)[-1]
        for r in rels
        if r["target_id"].startswith("unresolved:")
    ]


def _build(repo: Path) -> BathoBundleReader:
    run_build(BuildOptions(root=repo))
    return BathoBundleReader(repo / ".batho" / "artifact")


class TestBackendAppLayout:
    """sageoz: ``backend/app/`` marker-bounded package, ``from app.*`` imports."""

    @pytest.fixture
    def reader(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write(repo, "backend/app/__init__.py", "")
        _write(repo, "backend/app/services/__init__.py", "")
        _write(repo, "backend/app/services/errors.py",
               "class ServiceError(Exception):\n    pass\n")
        _write(repo, "backend/app/services/graph_service.py",
               "class GraphService:\n"
               "    def get_entity(self, entity_id: str) -> dict:\n"
               "        return {}\n")
        _write(repo, "backend/app/deps.py",
               "from app.services.graph_service import GraphService\n"
               "\n"
               "def get_graph_service() -> GraphService:\n"
               "    return GraphService()\n")
        _write(repo, "backend/app/routers/__init__.py", "")
        _write(repo, "backend/app/routers/graph.py",
               "from app.deps import get_graph_service\n"
               "from app.services.errors import ServiceError\n"
               "from app.services.graph_service import GraphService\n"
               "\n"
               "def Depends(f):\n"
               "    return f()\n"
               "\n"
               "def endpoint(graph_svc: GraphService = Depends(get_graph_service)):\n"
               "    try:\n"
               "        return graph_svc.get_entity('x')\n"
               "    except ServiceError:\n"
               "        raise ServiceError('boom')\n")
        return _build(repo)

    def test_no_app_prefixed_stubs(self, reader):
        bad = [t for t in _unresolved_targets(reader) if t.startswith("app.")]
        assert bad == []

    def test_service_error_resolves_first_party(self, reader):
        calls = _rels(reader, "CALLS")
        svc_err = [c for c in calls if "ServiceError" in c["target_id"]]
        assert svc_err, "no ServiceError CALLS edge"
        assert all(
            "backend/app/services/errors" in c["target_id"] for c in svc_err
        ), svc_err

    def test_receiver_via_aliased_param_still_resolves(self, reader):
        calls = _rels(reader, "CALLS")
        get_ent = [
            c for c in calls
            if "get_entity" in c["target_id"]
            and not c["target_id"].startswith("unresolved:")
        ]
        assert get_ent, "graph_svc.get_entity() did not resolve"
        meta = json.loads(get_ent[0].get("metadata_json") or "{}")
        assert meta.get("resolution_strategy") == "receiver_param"


class TestNamespacePackageFallback:
    """No ``__init__.py`` anywhere — marker chain yields nothing; the
    resolution-time suffix index must still join import path to file path."""

    @pytest.fixture
    def reader(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write(repo, "backend/app2/util/helper.py",
               "def helper_fn() -> int:\n    return 1\n")
        _write(repo, "backend/app2/main.py",
               "from app2.util.helper import helper_fn\n"
               "\n"
               "def run():\n"
               "    return helper_fn()\n")
        return _build(repo)

    def test_namespace_import_resolves(self, reader):
        calls = _rels(reader, "CALLS")
        helper = [
            c for c in calls
            if "helper_fn" in c["target_id"]
            and not c["target_id"].startswith("unresolved:")
        ]
        assert helper, (
            "namespace-package import unresolved: "
            f"{[t for t in _unresolved_targets(reader) if 'helper' in t]}"
        )
        assert "backend/app2/util/helper" in helper[0]["target_id"]

    def test_no_app2_stubs(self, reader):
        bad = [t for t in _unresolved_targets(reader) if t.startswith("app2.")]
        assert bad == []


class TestTsconfigAlias:
    """``paths: {"@/*": ["./src/*"]}`` — refs rewritten via manifest evidence."""

    @pytest.fixture
    def reader(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write(repo, "tsconfig.json",
               '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}')
        _write(repo, "src/lib/util.ts",
               "export function utilFn(): number {\n    return 1;\n}\n")
        _write(repo, "src/app.ts",
               "import { utilFn } from '@/lib/util';\n"
               "\n"
               "export function run(): number {\n"
               "    return utilFn();\n"
               "}\n")
        return _build(repo)

    def test_aliased_call_resolves(self, reader):
        calls = _rels(reader, "CALLS")
        resolved = [
            c for c in calls
            if "utilFn" in c["target_id"]
            and not c["target_id"].startswith("unresolved:")
        ]
        assert resolved, (
            "@/-aliased call unresolved: "
            f"{[t for t in _unresolved_targets(reader) if 'util' in t]}"
        )
        assert "src/lib/util" in resolved[0]["target_id"]


class TestRootEscapingSpecifier:
    """``../../../esc`` beyond the repo root must produce no candidate — the
    old `lstrip("./")` fallback turned an escape into a bare-name lookup that
    could hit an unrelated registered module (review ee88786f95f3)."""

    @pytest.fixture
    def reader(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write(repo, "esc.ts",
               "export function escFn(): number {\n    return 1;\n}\n")
        _write(repo, "a/b/mod.ts",
               "import { escFn } from '../../../esc';\n"
               "\n"
               "export function run(): number {\n    return escFn();\n}\n")
        return _build(repo)

    def test_root_escape_does_not_bind_unrelated_module(self, reader):
        imports = _rels(reader, "IMPORTS")
        resolved = [
            r for r in imports
            if not r["target_id"].startswith("unresolved:")
            and "esc" in r["target_id"]
        ]
        assert resolved == [], (
            f"root-escaping specifier bound an unrelated module: {resolved}"
        )


class TestLocalVsExternalCollision:
    """GRH-02: a local `backend/app` package AND a registered external `app`
    dep — the ref `app.services.errors.X` must keep the real local entity as
    primary; external-prefix synthesis can no longer claim it first."""

    def test_local_wins_over_external_ghost(self, tmp_path: Path):
        from batho.core.config import get_active_root, set_active_root
        from batho.core.schemas import Entity, EntityType
        from batho.modules.extraction.scope_manager import ScopeManager
        from batho.modules.graph.builder.codegraph import (
            CodeGraphIndexer, InMemoryGraph,
        )

        repo = tmp_path / "repo"
        _write(repo, "backend/app/__init__.py", "")
        _write(repo, "backend/app/services/__init__.py", "")
        _write(repo, "backend/app/services/errors.py",
               "class ServiceError(Exception):\n    pass\n")

        prev_root = get_active_root()
        set_active_root(repo)
        try:
            indexer = CodeGraphIndexer(
                cache_path=str(tmp_path / "c"), root=str(repo)
            )
            graph = InMemoryGraph()
            sm = ScopeManager()

            # dep-introspection shape: external `app` package registered
            sm.add_external_symbol(
                "app", "batho pip app 1.0.0 app/.", "external"
            )

            # first-party registrations use the FILE-path namespace
            cls_id = "batho test pkg 1.0.0 backend/app/services/errors.py/ServiceError"
            graph.add_entity(Entity(
                type=EntityType.CLASS, name="ServiceError",
                file="backend/app/services/errors.py",
                start_line=1, end_line=1, id_override=cls_id,
            ))
            sm.define_symbol(
                "backend.app.services.errors", "mod:errors",
                "MODULE", is_global=True,
            )
            sm.define_symbol(
                "backend.app.services.errors.ServiceError", cls_id,
                "CLASS", is_global=True,
            )

            scope = "batho test pkg 1.0.0 backend/app/routers/g.py/endpoint"
            stub = Entity(
                type=EntityType.EXTERNAL_SYMBOL,
                name="app.services.errors.ServiceError",
                file="backend/app/routers/g.py", start_line=1, end_line=1,
                metadata={
                    "reference_type": "calls",
                    "resolution_reason": "contextual_stub",
                    "stub_resolution_state": "pending",
                    "caller_scope": scope,
                    "target_name": "app.services.errors.ServiceError",
                },
                id_override=(
                    f"unresolved:{scope}::app.services.errors.ServiceError"
                ),
            )
            graph.add_entity(stub)

            indexer.resolve_contextual_stubs(graph, sm)
            updated = graph.get_entity(stub.id)
            assert updated.metadata.get("resolved_target_id") == cls_id, (
                f"external ghost won primary: {updated.metadata}"
            )
            assert updated.metadata.get("resolution_strategy") == "package_alias"
            indexer.close()
        finally:
            set_active_root(prev_root)
