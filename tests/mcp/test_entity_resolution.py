"""Tests for the EndpointResolver (T20).

Scenario:
    Cross-file references in rels_views are stored as `unresolved:...::fqn`
    stubs under the *referencing* file, or as path-embedded markup IDs.
    EndpointResolver maps any endpoint to its defining file.

Execution Flow:
    1. Build a fake reader exposing tiny agent_views / rels_views /
       file_tracking tables.
    2. Resolve stubs, markup IDs, direct entity IDs, and stdlib refs.
    3. Verify cross_file_edges aggregation and generation invalidation.

Expectations:
    - Stub FQNs resolve via longest-prefix module match.
    - The stub check precedes the entity-index lookup (ordering regression).
    - CONTAINS and intra-file edges are excluded from cross_file_edges.
"""

from __future__ import annotations

import pyarrow as pa
import pytest

from batho.mcp.entity_resolution import (
    KIND_DIRECT,
    KIND_EMBEDDED,
    KIND_EXTERNAL_PACKAGE,
    KIND_EXTERNAL_STDLIB,
    KIND_EXTERNAL_UNRESOLVED,
    KIND_MODULE,
    KIND_NAME,
    EndpointResolver,
    get_resolver,
    stub_fqn,
)

AGENT_SCHEMA = pa.schema([
    pa.field("file_id", pa.int64(), nullable=False),
    pa.field("entity_id", pa.large_utf8(), nullable=False),
    pa.field("name", pa.utf8(), nullable=False),
    pa.field("entity_type", pa.utf8(), nullable=False),
])

RELS_SCHEMA = pa.schema([
    pa.field("file_id", pa.int64(), nullable=False),
    pa.field("source_id", pa.large_utf8(), nullable=False),
    pa.field("target_id", pa.large_utf8(), nullable=False),
    pa.field("relation_type", pa.utf8(), nullable=False),
    pa.field("metadata_json", pa.utf8(), nullable=True),
    pa.field("roles", pa.int32(), nullable=True),
    pa.field("confidence", pa.float32(), nullable=True),
])


class FakeReader:
    """Duck-typed BathoBundleReader backed by in-memory Arrow tables."""

    def __init__(self, agent_rows, rels_rows, files, generation=1, root="/repo",
                 workspace_rows=None):
        self._agent = pa.Table.from_pylist(agent_rows, schema=AGENT_SCHEMA)
        self._rels = pa.Table.from_pylist(rels_rows, schema=RELS_SCHEMA)
        self._files = files
        self.generation = generation
        self.root = root
        self.workspace_rows = workspace_rows or []

    def _get_table(self, logical_name):
        if logical_name == "agent_views":
            return self._agent
        if logical_name == "rels_views":
            return self._rels
        return pa.table({})

    def get_all_file_tracking(self):
        return {
            fp: {"file_id": fid, "file_path": fp, "is_indexed": True}
            for fp, fid in self._files.items()
        }

    def get_manifest(self):
        return {"generation": self.generation}

    def get_latest_run_id(self):
        return "run-1"

    def get_run(self, run_uuid):
        return {"root_path": self.root}

    def get_workspace_manifests(self):
        return self.workspace_rows


def _stub(caller_scope: str, fqn: str) -> str:
    return f"unresolved:batho npm docs-site 0.0.0 {caller_scope}:::{fqn}".replace(":::", "::")


@pytest.fixture
def resolver():
    agent_rows = [
        {"file_id": 1, "entity_id": "ent-main-App", "name": "App", "entity_type": "CLASS"},
        {"file_id": 1, "entity_id": "ent-main-main", "name": "main", "entity_type": "FUNCTION"},
        {"file_id": 2, "entity_id": "ent-utils-helper", "name": "helper", "entity_type": "FUNCTION"},
        {"file_id": 3, "entity_id": "ent-models-User", "name": "User", "entity_type": "CLASS"},
        {"file_id": 4, "entity_id": "ent-config-init", "name": "set_active_root", "entity_type": "FUNCTION"},
    ]
    rels_rows = [
        {"file_id": 1, "source_id": "ent-main-main", "target_id": _stub("main().", "helper"),
         "relation_type": "CALLS", "metadata_json": None, "roles": 0, "confidence": 1.0},
        {"file_id": 1, "source_id": "ent-main-App", "target_id": _stub("App#.", "models.User"),
         "relation_type": "READS", "metadata_json": None, "roles": 0, "confidence": 1.0},
        {"file_id": 1, "source_id": "ent-main-main", "target_id": _stub("main().", "typing.Any"),
         "relation_type": "READS", "metadata_json": None, "roles": 0, "confidence": 1.0},
        {"file_id": 1, "source_id": "ent-main-App", "target_id": "ent-main-main",
         "relation_type": "CONTAINS", "metadata_json": None, "roles": 0, "confidence": 1.0},
        {"file_id": 2, "source_id": "ent-utils-helper", "target_id": "ent-utils-helper",
         "relation_type": "CONTAINS", "metadata_json": None, "roles": 0, "confidence": 1.0},
        {"file_id": 2, "source_id": "ent-utils-helper", "target_id": "ent-models-User",
         "relation_type": "USES", "metadata_json": None, "roles": 0, "confidence": 1.0},
        {"file_id": 1, "source_id": "ent-main-main",
         "target_id": _stub("main().", "batho.core.config.set_active_root"),
         "relation_type": "CALLS", "metadata_json": None, "roles": 0, "confidence": 1.0},
    ]
    files = {
        "main.py": 1,
        "utils.py": 2,
        "models.py": 3,
        "batho/core/config/__init__.py": 4,
    }
    return EndpointResolver(FakeReader(agent_rows, rels_rows, files))


class TestStubResolution:
    def test_stub_resolves_via_module_index(self, resolver):
        target = resolver.resolve(_stub("main().", "helper"))
        assert target.kind == KIND_NAME
        assert target.file_id == 2
        assert target.path == "utils.py"

    def test_stub_package_fqn_resolves_to_init(self, resolver):
        target = resolver.resolve(_stub("main().", "batho.core.config.set_active_root"))
        assert target.kind == KIND_MODULE
        assert target.file_id == 4
        assert target.path == "batho/core/config/__init__.py"

    def test_stub_stdlib_classified_external(self, resolver):
        target = resolver.resolve(_stub("main().", "typing.Any"))
        assert target.kind == KIND_EXTERNAL_STDLIB
        assert target.file_id is None
        assert target.path is None

    def test_stub_checked_before_entity_index(self, resolver):
        """Regression: stubs are materialized in agent_views under the
        referencing file; the stub check must precede the entity lookup or
        every cross-file edge collapses to intra-file."""
        stub_id = _stub("main().", "helper")
        reader = resolver._reader
        agent_rows = reader._agent.to_pylist() + [
            {"file_id": 1, "entity_id": stub_id, "name": "helper", "entity_type": "FUNCTION"},
        ]
        reader._agent = pa.Table.from_pylist(agent_rows, schema=AGENT_SCHEMA)
        resolver._generation = None
        target = resolver.resolve(stub_id)
        assert target.file_id == 2
        assert target.path == "utils.py"

    def test_unresolvable_stub(self, resolver):
        target = resolver.resolve(_stub("main().", "totally_unknown_symbol_xyz"))
        assert target.kind == KIND_EXTERNAL_UNRESOLVED


class TestDirectAndEmbedded:
    def test_direct_entity(self, resolver):
        target = resolver.resolve("ent-models-User")
        assert target.kind == KIND_DIRECT
        assert target.file_id == 3
        assert target.path == "models.py"

    def test_embedded_markup_path(self, resolver):
        eid = "ent|ELEMENT|/repo/docs/x.md|0|30|1|1|header"
        target = resolver.resolve(eid)
        assert target.kind == KIND_EMBEDDED
        assert target.file_id is None
        assert target.path == "/repo/docs/x.md"

    def test_embedded_path_with_repo_root(self, resolver):
        eid = "ent|ELEMENT|/repo/main.py|0|30|1|1|header"
        target = resolver.resolve(eid)
        assert target.kind == KIND_EMBEDDED
        assert target.file_id == 1


class TestOwnPackageClassification:
    """T2: own-workspace package triples classify KIND_DIRECT, not external."""

    WS_ROWS = [
        {"scope": "workspace", "manager": "pip", "name": "batho",
         "version": "1.4.2", "kind": "primary", "source_file": "pyproject.toml",
         "manifest_dir": ".", "language": None, "content_hash": "h1"},
        {"scope": "workspace", "manager": "npm", "name": "docs-site",
         "version": "0.0.0", "kind": "subproject",
         "source_file": "docs-site/package.json", "manifest_dir": "docs-site",
         "language": None, "content_hash": "h2"},
    ]

    @staticmethod
    def _resolver(agent_rows, workspace_rows=None):
        return EndpointResolver(FakeReader(
            agent_rows, [], {}, workspace_rows=workspace_rows))

    def test_own_package_triple_classifies_direct(self):
        eid = "batho npm docs-site 0.0.0 docs_site/src/app/App()."
        agent_rows = [{"file_id": 1, "entity_id": eid, "name": "App",
                       "entity_type": "CLASS"}]
        r = self._resolver(agent_rows, workspace_rows=self.WS_ROWS)
        target = r.resolve("batho npm docs-site 0.0.0 docs_site/src/app/App().")
        assert target.kind == KIND_DIRECT
        assert target.file_id == 1

    def test_third_party_package_stays_external(self):
        r = self._resolver([])
        target = r.resolve("batho pip numpy >=2.0 numpy/random/rand().")
        assert target.kind == KIND_EXTERNAL_PACKAGE

    def test_prefix_only_fallback_without_table(self):
        # pre-T8 artifact: no workspace rows → prefix-only classification
        r = self._resolver([])
        target = r.resolve("batho pip batho 1.4.2 batho/mcp/server/x().")
        assert target.kind == KIND_EXTERNAL_PACKAGE

    def test_own_entity_with_file_row_direct_without_table(self):
        """Pre-T8 artifact, no workspace rows: an entity with a real file row
        is intra-repo even though its id carries the package prefix — the
        file map, not the workspace table, supplies the fallback signal
        (issue 1f6d3a08b7c2)."""
        eid = "batho pip batho 1.4.2 batho/mcp/server/x()."
        agent_rows = [{"file_id": 1, "entity_id": eid, "name": "x",
                       "entity_type": "FUNCTION"}]
        r = EndpointResolver(FakeReader(
            agent_rows, [], {"batho/mcp/server/x.py": 1}, workspace_rows=None))
        target = r.resolve(eid)
        assert target.kind == KIND_DIRECT
        assert target.file_id == 1
        assert target.path == "batho/mcp/server/x.py"

    def test_non_member_entity_with_file_row_direct_with_table(self):
        """Own-set populated but NOT containing this triple: a real file row
        still reclassifies the entity intra-repo — membership is not the only
        path to KIND_DIRECT (issue 0918802ecd10)."""
        eid = "batho npm somelib 2.0 src/x/f()."
        agent_rows = [{"file_id": 1, "entity_id": eid, "name": "f",
                       "entity_type": "FUNCTION"}]
        r = EndpointResolver(FakeReader(
            agent_rows, [], {"src/x.py": 1}, workspace_rows=self.WS_ROWS))
        target = r.resolve(eid)
        assert target.kind == KIND_DIRECT
        assert target.file_id == 1
        assert target.path == "src/x.py"

    def test_non_member_entity_on_pseudo_file_stays_external_with_table(self):
        """Same non-member triple on a pseudo-file stays external — the
        file-row rescue must not flip dep entities."""
        eid = "batho npm somelib 2.0 somelib/f()."
        agent_rows = [{"file_id": 2, "entity_id": eid, "name": "f",
                       "entity_type": "EXTERNAL_SYMBOL"}]
        r = EndpointResolver(FakeReader(
            agent_rows, [], {"__external_symbols__": 2},
            workspace_rows=self.WS_ROWS))
        assert r.resolve(eid).kind == KIND_EXTERNAL_PACKAGE

    def test_external_entity_on_pseudo_file_stays_external_without_table(self):
        """Dep/stdlib entities ride on pseudo-files — '.' and
        '__external_symbols__' rows must not flip them to intra-repo."""
        eid = "batho pip structlog 24 structlog/get_logger()."
        agent_rows = [{"file_id": 2, "entity_id": eid, "name": "get_logger",
                       "entity_type": "EXTERNAL_SYMBOL"}]
        r = EndpointResolver(FakeReader(
            agent_rows, [], {"__external_symbols__": 2}, workspace_rows=None))
        assert r.resolve(eid).kind == KIND_EXTERNAL_PACKAGE

        r2 = EndpointResolver(FakeReader(
            agent_rows, [], {".": 2}, workspace_rows=None))
        assert r2.resolve(eid).kind == KIND_EXTERNAL_PACKAGE

    def test_stdlib_still_external_with_own_set(self):
        r = self._resolver([], workspace_rows=self.WS_ROWS)
        target = r.resolve("batho stdlib python python os/")
        assert target.kind == KIND_EXTERNAL_STDLIB

    def test_non_original_managers_classify_external(self):
        """All PackageManager prefixes classify external — not just
        pip/npm/cargo/go/maven (issue b82e4a16f9c3)."""
        eid = "batho gem rails 7.1 rails/Application()."
        agent_rows = [{"file_id": 2, "entity_id": eid, "name": "Application",
                       "entity_type": "EXTERNAL_SYMBOL"}]
        r = EndpointResolver(FakeReader(
            agent_rows, [], {"__external_symbols__": 2}, workspace_rows=None))
        target = r.resolve(eid)
        assert target.kind == KIND_EXTERNAL_PACKAGE

        eid2 = "batho composer symfony 6 symfony/console/Application()."
        agent_rows2 = [{"file_id": 2, "entity_id": eid2, "name": "Application",
                        "entity_type": "EXTERNAL_SYMBOL"}]
        r2 = EndpointResolver(FakeReader(
            agent_rows2, [], {"__external_symbols__": 2}, workspace_rows=None))
        assert r2.resolve(eid2).kind == KIND_EXTERNAL_PACKAGE


class TestCrossFileEdges:
    def test_excludes_contains_and_intra_file(self, resolver):
        edges = resolver.cross_file_edges()
        for rel, sf, tf in edges:
            assert rel["relation_type"] != "CONTAINS"
            assert sf != tf

    def test_includes_known_cross_file_edges(self, resolver):
        edges = resolver.cross_file_edges()
        pairs = {(sf, tf) for _, sf, tf in edges}
        assert (1, 2) in pairs
        assert (1, 3) in pairs
        assert (1, 4) in pairs
        assert (2, 3) in pairs

    def test_cached_until_generation_bump(self, resolver):
        first = resolver.cross_file_edges()
        assert resolver.cross_file_edges() is first
        resolver._reader.generation = 2
        second = resolver.cross_file_edges()
        assert second is not first


class TestResolveSymbol:
    def test_stub_maps_to_defining_entity(self, resolver):
        eid = resolver.resolve_symbol(_stub("main().", "helper"))
class TestResolverPool:
    def test_get_resolver_reuses_instance(self):
        reader = FakeReader([], [], {"a.py": 1})
        assert get_resolver(reader) is get_resolver(reader)


class TestStubFqn:
    """Round-4 fix: single stub-ID parse helper (stub_fqn).

    New artifacts carry a dot-normalized ref key, so the single ``::``
    separates caller scope from the dotted target FQN. Legacy artifacts may
    embed ``::`` inside the ref key; the last segment is returned (legacy
    behavior, pinned).
    """

    def test_new_format_scoped_ref(self):
        assert stub_fqn("unresolved:my_scope::std.io.Write") == "std.io.Write"

    def test_legacy_space_form_no_separator(self):
        assert stub_fqn("unresolved:batho pkg 1.0 main()::helper") == "helper"

    def test_legacy_scope_laden_ref_key_returns_last_segment(self):
        assert stub_fqn("unresolved:scope::std::io::Write") == "Write"

    def test_unscoped_legacy_form(self):
        assert stub_fqn("unresolved:helper") == "helper"

    def test_empty_ref_key(self):
        assert stub_fqn("unresolved:") == ""

    def test_path_slash_form(self):
        assert stub_fqn("unresolved:/abs/path mod.py") == "mod.py"


class TestRustStdlibStubs:
    """New-format Rust stdlib stubs bucket via the stdlib roots; module
    index wins over the stdlib bucket for indexed local modules."""

    @pytest.fixture
    def rust_resolver(self):
        agent_rows = [
            {"file_id": 1, "entity_id": "ent-main-run", "name": "run", "entity_type": "FUNCTION"},
        ]
        rels_rows = [
            {"file_id": 1, "source_id": "ent-main-run",
             "target_id": "unresolved:run().::std.io.Write",
             "relation_type": "USES", "metadata_json": None, "roles": 0, "confidence": 1.0},
        ]
        files = {"src/main.rs": 1}
        return EndpointResolver(FakeReader(agent_rows, rels_rows, files))

    def test_rust_std_ref_is_stdlib(self, rust_resolver):
        target = rust_resolver.resolve("unresolved:run().::std.io.Write")
        assert target.kind == KIND_EXTERNAL_STDLIB
        assert target.file_id is None

    @pytest.mark.parametrize("root", ["core", "alloc", "proc_macro"])
    def test_rust_std_crate_roots(self, rust_resolver, root):
        target = rust_resolver.resolve(f"unresolved:run().::{root}.mem")
        assert target.kind == KIND_EXTERNAL_STDLIB

    def test_local_module_named_core_wins_over_stdlib(self):
        # A root-level core.py indexes as module "core", which the
        # longest-prefix module match finds before the stdlib bucket.
        agent_rows = [
            {"file_id": 1, "entity_id": "ent-run", "name": "run", "entity_type": "FUNCTION"},
        ]
        rels_rows = []
        files = {"core.py": 1}
        resolver = EndpointResolver(FakeReader(agent_rows, rels_rows, files))
        target = resolver.resolve("unresolved:run().::core.mem")
        assert target.kind == KIND_MODULE
        assert target.file_id == 1

    def test_legacy_rust_stub_keeps_last_segment_behavior(self, rust_resolver):
        # Pre-normalization artifact: ref key still carries '::'. The parse
        # degrades to the last segment (documented legacy behavior).
        target = rust_resolver.resolve("unresolved:run().::std::io::Write")
        assert target.kind == KIND_EXTERNAL_UNRESOLVED

    def test_resolve_symbol_new_format_rust_name_fallback(self):
        # "crate" is neither a stdlib root nor an indexed module, so the stub
        # resolves through the scope-aware name fallback to the defining file.
        agent_rows = [
            {"file_id": 1, "entity_id": "ent-main-run", "name": "run", "entity_type": "FUNCTION"},
            {"file_id": 2, "entity_id": "ent-services-helper", "name": "helper", "entity_type": "FUNCTION"},
        ]
        files = {"src/main.rs": 1, "src/services.rs": 2}
        resolver = EndpointResolver(FakeReader(agent_rows, [], files))
        eid = resolver.resolve_symbol("unresolved:run().::crate.services.helper")
        assert eid == "ent-services-helper"

    def test_resolve_symbol_stdlib_root_returns_none(self, rust_resolver):
        # "std" buckets as stdlib before the name fallback fires.
        assert rust_resolver.resolve_symbol("unresolved:run().::std.io.Write") is None
