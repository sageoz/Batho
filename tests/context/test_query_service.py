from __future__ import annotations

import json
from pathlib import Path

import pytest

import batho_core.context.query as query_module
from batho_core.context.query import QueryService


def _write_graph(ctn_dir: Path, index_id: str) -> None:
    index_dir = ctn_dir / index_id
    index_dir.mkdir(parents=True, exist_ok=True)
    graph_payload = {
        "entities_by_id": {
            "e1": {
                "id": "e1",
                "type": "FUNCTION",
                "name": "alpha",
                "file": "src/a.py",
                "signature": "alpha()",
                "metadata": {"language": "python"},
            },
            "e2": {
                "id": "e2",
                "type": "CLASS",
                "name": "Beta",
                "file": "src/b.py",
                "metadata": {"language": "python"},
            },
        },
        "relationships": [
            {
                "id": "r1",
                "type": "CALLS",
                "source_id": "e1",
                "target_id": "e2",
                "metadata": {},
            }
        ],
    }
    (index_dir / "graph.json").write_text(json.dumps(graph_payload), encoding="utf-8")
    (ctn_dir / "index.json").write_text(
        json.dumps({"current_index_id": index_id, "indexes": {index_id: {}}}),
        encoding="utf-8",
    )


def test_query_service_fallback_uses_graph_when_registry_indexes_missing(
    tmp_path: Path,
) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    _write_graph(ctn_dir, "idx1")

    service = QueryService(ctn_dir)

    entities = service.entities_by_type("function", limit=10)
    assert len(entities) == 1
    assert entities[0]["entity_id"] == "e1"

    relationships = service.relationships_by_type("calls", limit=10)
    assert len(relationships) == 1
    assert relationships[0]["relationship_id"] == "r1"


def test_query_service_rebuild_persists_indexes_for_registry_queries(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    _write_graph(ctn_dir, "idx1")

    service = QueryService(ctn_dir)
    stats = service.rebuild_indexes()

    assert stats["entities_indexed"] == 2
    assert stats["relationships_indexed"] == 1

    # Remove graph to ensure query can still resolve from persisted indexes.
    graph_path = ctn_dir / "idx1" / "graph.json"
    graph_path.unlink()

    fresh_service = QueryService(ctn_dir)
    entities = fresh_service.entities_by_type("function", limit=10)
    assert len(entities) == 1
    assert entities[0]["name"] == "alpha"


def test_query_service_index_metadata_invalid_json_and_missing_index(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    (ctn_dir / "index.json").write_text("{broken", encoding="utf-8")

    service = QueryService(ctn_dir)
    assert service._index_metadata() == {}
    assert service._resolve_index_id() is None


def test_query_service_explicit_index_id_and_registry_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()

    calls = {"count": 0}

    def _fake_query_entities(*_args, **_kwargs):
        calls["count"] += 1
        return [
            {
                "entity_id": "e1",
                "entity_type": "function",
                "file_path": "src/a.py",
                "name": "alpha",
                "signature": None,
                "metadata": {},
            }
        ]

    monkeypatch.setattr(query_module, "query_entities_from_registry", _fake_query_entities)

    service = QueryService(ctn_dir, index_id="idx-explicit")
    first = service.entities_by_type("function", limit=10)
    second = service.entities_by_type("function", limit=10)

    assert len(first) == 1
    assert second == first
    assert calls["count"] == 1


def test_query_service_cache_disabled_and_iter_helpers(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    _write_graph(ctn_dir, "idx1")

    service = QueryService(ctn_dir, cache_enabled=False)
    rows = service.entities_by_type("function", limit=10)
    assert len(rows) == 1
    assert service._cache == {}

    entities_from_list = service._iter_entities(
        {
            "entities": [
                {"id": "e-list", "type": "function"},
                {"name": "missing-id"},
                "bad",
            ]
        }
    )
    assert entities_from_list == [("e-list", {"id": "e-list", "type": "function"})]

    rels = service._iter_relationships({"relationships": [{"id": "r1"}, "bad"]})
    assert rels == [{"id": "r1"}]


def test_query_service_file_and_relationship_fallback_from_graph(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    idx = ctn_dir / "idx1"
    idx.mkdir()
    (ctn_dir / "index.json").write_text(
        json.dumps({"current_index_id": "idx1", "indexes": {"idx1": {}}}),
        encoding="utf-8",
    )
    (idx / "graph.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"id": "e1", "type": "FUNCTION", "file": "src/a.py", "name": "alpha"},
                    {"id": "e2", "type": "CLASS", "file": "src/b.py", "name": "Beta"},
                ],
                "relationships": [
                    {
                        "id": "r1",
                        "type": "CALLS",
                        "source_id": "e1",
                        "target_id": "e2",
                        "metadata": "not-a-dict",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    service = QueryService(ctn_dir)
    by_file = service.entities_by_file("src/b.py", limit=10)
    assert len(by_file) == 1
    assert by_file[0]["entity_id"] == "e2"

    by_type = service.relationships_by_type("calls", limit=10)
    assert len(by_type) == 1
    assert by_type[0]["relationship_id"] == "r1"
    assert by_type[0]["metadata"] == {}


def test_query_service_graph_payload_decode_error_and_rebuild_no_index(tmp_path: Path) -> None:
    ctn_dir = tmp_path / ".ctn"
    ctn_dir.mkdir()
    bad_idx = ctn_dir / "idx1"
    bad_idx.mkdir()
    (ctn_dir / "index.json").write_text(
        json.dumps({"current_index_id": "idx1", "indexes": {"idx1": {}}}),
        encoding="utf-8",
    )
    (bad_idx / "graph.json").write_text("{broken", encoding="utf-8")

    service = QueryService(ctn_dir)
    assert service._graph_payload("idx1") == {}

    missing_service = QueryService(ctn_dir / "missing")
    stats = missing_service.rebuild_indexes()
    assert stats == {"entities_indexed": 0, "relationships_indexed": 0}
