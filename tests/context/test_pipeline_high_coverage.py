from __future__ import annotations

from pathlib import Path

from batho.context import pipeline
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType


def _entity(file_path: str = "src/a.py") -> Entity:
    return Entity(
        type=EntityType.FUNCTION,
        name="fn",
        file=file_path,
        start_line=1,
        end_line=1,
    )


def _relationship(entity_id: str) -> Relationship:
    return Relationship(
        source_id=entity_id,
        target_id=entity_id,
        type=RelationshipType.CALLS,
    )


def test_process_file_worker_returns_cached_entities(monkeypatch, tmp_path: Path) -> None:
    cached = [_entity("src/cached.py")]
    cached_rels = [_relationship(cached[0].id)]

    class _Cache:
        def __init__(self, cache_path: str):
            self.cache_path = cache_path

        def get_ast(self, *_args):
            return cached, cached_rels

    monkeypatch.setattr(pipeline, "BathoCache", _Cache)

    result = pipeline.process_file_worker(
        tmp_path / "cached.py",
        "src/cached.py",
        b"print('x')",
        "hash-1",
        1.0,
        10,
        True,
        "cache.db",
        7,
        64,
        {},
    )

    assert result == ("src/cached.py", cached, cached_rels, True)


def test_process_file_worker_returns_none_for_invalid_extractor(monkeypatch, tmp_path: Path) -> None:
    class _BaseExtractor:
        pass

    class _Cache:
        def __init__(self, cache_path: str):
            self.cache_path = cache_path

        def get_ast(self, *_args):
            return None

        def set_ast(self, *_args):
            return None

    class _Detector:
        @staticmethod
        def get_extractor(*_args):
            return object()

    monkeypatch.setattr(pipeline, "ASTExtractor", _BaseExtractor)
    monkeypatch.setattr(pipeline, "BathoCache", _Cache)
    monkeypatch.setattr("batho.context.languages.detector.default_detector", _Detector())
    monkeypatch.setattr("batho.context.languages.registry.get_extractor", lambda _suffix: None)

    result = pipeline.process_file_worker(
        tmp_path / "invalid.py",
        "src/invalid.py",
        b"x",
        "hash-2",
        1.0,
        1,
        False,
        "cache.db",
        7,
        64,
        {},
    )

    assert result is None


def test_process_file_worker_parses_and_caches(monkeypatch, tmp_path: Path) -> None:
    entity = _entity("src/ok.py")
    rel = _relationship(entity.id)
    cache_calls: list[tuple[str, str, int, int]] = []

    class _BaseExtractor:
        pass

    class _Extractor(_BaseExtractor):
        def parse_file(self, *_args):
            return [entity], [rel]

    class _Cache:
        def __init__(self, cache_path: str):
            self.cache_path = cache_path

        def get_ast(self, *_args):
            return None

        def set_ast(
            self,
            file_hash: str,
            file_path: str,
            entities: list[Entity],
            relationships: list[Relationship],
            current_mtime: float,
            size: int,
            ttl_days: int,
        ) -> None:
            _ = current_mtime, size, relationships
            cache_calls.append((file_hash, file_path, len(entities), ttl_days))

    class _Detector:
        @staticmethod
        def get_extractor(*_args):
            return _Extractor()

    monkeypatch.setattr(pipeline, "ASTExtractor", _BaseExtractor)
    monkeypatch.setattr(pipeline, "BathoCache", _Cache)
    monkeypatch.setattr("batho.context.languages.detector.default_detector", _Detector())
    monkeypatch.setattr("batho.context.languages.registry.get_extractor", lambda _suffix: None)

    result = pipeline.process_file_worker(
        tmp_path / "ok.py",
        "src/ok.py",
        b"print('ok')",
        "hash-3",
        1.5,
        20,
        True,
        "cache.db",
        14,
        64,
        {},
    )

    assert result == ("src/ok.py", [entity], [rel], False)
    assert cache_calls == [("hash-3", "src/ok.py", 1, 14)]


def test_process_file_worker_handles_exceptions(monkeypatch, tmp_path: Path) -> None:
    class _BaseExtractor:
        pass

    class _BrokenExtractor(_BaseExtractor):
        def parse_file(self, *_args):
            raise RuntimeError("boom")

    class _Detector:
        @staticmethod
        def get_extractor(*_args):
            return _BrokenExtractor()

    monkeypatch.setattr(pipeline, "ASTExtractor", _BaseExtractor)
    monkeypatch.setattr("batho.context.languages.detector.default_detector", _Detector())
    monkeypatch.setattr("batho.context.languages.registry.get_extractor", lambda _suffix: None)

    result = pipeline.process_file_worker(
        tmp_path / "broken.py",
        "src/broken.py",
        b"raise",
        "hash-4",
        1.0,
        10,
        False,
        "cache.db",
        7,
        64,
        {},
    )

    assert result is None


def test_build_graph_parallel_delegates_when_disabled(monkeypatch) -> None:
    sentinel = ([("x.py", [], [], False)], 2)
    monkeypatch.setattr(pipeline, "build_graph_sequential", lambda *_args, **_kwargs: sentinel)

    result = pipeline.build_graph_parallel(
        candidates=[(Path("/tmp/x.py"), "x.py")],
        configured_max_file_size_kb=64,
        bsg_cfg={"parallel": {"enabled": False}},
    )

    assert result == sentinel


def test_build_graph_parallel_returns_early_for_empty_candidates() -> None:
    result = pipeline.build_graph_parallel(
        candidates=[],
        configured_max_file_size_kb=64,
        bsg_cfg={"parallel": {"enabled": True}},
    )
    assert result == ([], 0)


def test_build_graph_parallel_collects_valid_results(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "a.py"
    src.write_text("print('a')\n", encoding="utf-8")

    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: b"print('a')\n")
    monkeypatch.setattr(pipeline.os, "cpu_count", lambda: 0)

    class _Pool:
        def __init__(self, processes: int, initializer=None, initargs=()):
            self.processes = processes
            assert callable(initializer)
            assert isinstance(initargs, tuple)
            assert isinstance(initargs[0], dict)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        def starmap(self, func, work_items, chunksize: int):
            _ = func
            assert self.processes == 1
            assert len(work_items) == 1
            assert chunksize == 3
            return [("src/a.py", [], [], False), None]

    monkeypatch.setattr("multiprocessing.context.SpawnContext.Pool", _Pool)

    results, errors = pipeline.build_graph_parallel(
        candidates=[(src, "src/a.py")],
        configured_max_file_size_kb=64,
        bsg_cfg={"parallel": {"enabled": True, "max_workers": 8, "chunk_size": 3}},
    )

    assert results == [("src/a.py", [], [], False)]
    assert errors == 1


def test_build_graph_parallel_falls_back_when_pool_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    src = tmp_path / "fallback.py"
    src.write_text("print('fallback')\n", encoding="utf-8")

    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: b"x")

    class _ImportErrorPool:
        def __init__(self, processes: int, initializer=None, initargs=()):
            self.processes = processes
            self.initializer = initializer
            self.initargs = initargs

        def __enter__(self):
            raise ImportError("multiprocessing unavailable")

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

    monkeypatch.setattr("multiprocessing.context.SpawnContext.Pool", _ImportErrorPool)
    sentinel = ([("fallback.py", [], [], False)], 9)
    monkeypatch.setattr(pipeline, "build_graph_sequential", lambda *_args, **_kwargs: sentinel)

    result = pipeline.build_graph_parallel(
        candidates=[(src, "fallback.py")],
        configured_max_file_size_kb=64,
        bsg_cfg={"parallel": {"enabled": True}},
    )

    assert result == sentinel


def test_initialize_worker_logging_is_idempotent(monkeypatch) -> None:
    calls: list[dict] = []

    monkeypatch.setattr(pipeline, "configure_logging", lambda cfg: calls.append(cfg))
    pipeline._WORKER_LOGGING_INITIALIZED = False

    pipeline._initialize_worker_logging({"level": "ERROR"})
    pipeline._initialize_worker_logging({"level": "DEBUG"})

    assert calls == [{"level": "ERROR"}]
    pipeline._WORKER_LOGGING_INITIALIZED = False


def test_build_graph_sequential_counts_errors_and_success(tmp_path: Path, monkeypatch) -> None:
    ok = tmp_path / "ok.py"
    ok.write_text("print('ok')\n", encoding="utf-8")

    fail = tmp_path / "fail.py"
    fail.write_text("print('fail')\n", encoding="utf-8")

    none_file = tmp_path / "none.py"
    none_file.write_text("print('none')\n", encoding="utf-8")

    large = tmp_path / "large.py"
    large.write_bytes(b"x" * 4096)

    class _BadStatPath:
        suffix = ".py"

        @staticmethod
        def stat():
            raise OSError("stat failed")

    def _read_content(filepath: str, max_size_kb: int | None = None, **kwargs):
        if filepath == "none.py":
            return None
        return b"print('data')"

    def _worker(file_path, filepath: str, *_args, **_kwargs):
        _ = file_path
        if filepath == "fail.py":
            return None
        return (filepath, [], [], False)

    monkeypatch.setattr(pipeline, "read_file_bytes", _read_content)
    monkeypatch.setattr(pipeline, "process_file_worker", _worker)

    results, errors = pipeline.build_graph_sequential(
        candidates=[
            (_BadStatPath(), "bad.py"),
            (large, "large.py"),
            (none_file, "none.py"),
            (fail, "fail.py"),
            (ok, "ok.py"),
        ],
        configured_max_file_size_kb=1,
        bsg_cfg={"cache": {"enabled": False}},
    )

    assert results == [("ok.py", [], [], False)]
    assert errors == 3
