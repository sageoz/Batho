from __future__ import annotations

from pathlib import Path

from batho.context import pipeline
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType
from batho.utils.hash import compute_bytes_hash


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
        
        def get_file_snapshot(self, *_args):
            return None

    monkeypatch.setattr(pipeline, "BathoCache", _Cache)
    
    file_path = tmp_path / "cached.py"
    file_content = b"print('x')"
    file_path.write_bytes(file_content)

    # Monkeypatch read_file_bytes to return our content regardless of path
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: file_content)

    result = pipeline.process_file_worker(
        file_path,
        "src/cached.py",
        1.0,
        10,
        True,
        str(tmp_path / "cache.db"),
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
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: b"x")

    # Create the dummy file
    file_path = tmp_path / "invalid.py"
    file_path.write_bytes(b"x")

    result = pipeline.process_file_worker(
        file_path,
        "src/invalid.py",
        1.0,
        1,
        False,
        str(tmp_path / "cache.db"),
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
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: b"print('ok')")

    # Create the dummy file
    file_path = tmp_path / "ok.py"
    file_content = b"print('ok')"
    file_path.write_bytes(file_content)
    expected_hash = compute_bytes_hash(file_content)

    result = pipeline.process_file_worker(
        file_path,
        "src/ok.py",
        1.5,
        20,
        True,
        str(tmp_path / "cache.db"),
        14,
        64,
        {},
    )

    assert result == ("src/ok.py", [entity], [rel], False)
    assert cache_calls == [(expected_hash, "src/ok.py", 1, 14)]


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
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: b"raise")

    # Create the dummy file
    file_path = tmp_path / "broken.py"
    file_path.write_bytes(b"raise")

    result = pipeline.process_file_worker(
        file_path,
        "src/broken.py",
        1.0,
        10,
        False,
        str(tmp_path / "cache.db"),
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
            # Dynamic chunk sizing returns 1 for single file (ensures at least 2 chunks per worker)
            assert chunksize == 1
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


def test_initialize_worker_is_idempotent(monkeypatch) -> None:
    calls: list[dict] = []

    monkeypatch.setattr(pipeline, "configure_logging", lambda cfg: calls.append(cfg))
    pipeline._WORKER_LOGGING_INITIALIZED = False

    pipeline._initialize_worker({"level": "ERROR"})
    pipeline._initialize_worker({"level": "DEBUG"})

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
        if "none.py" in str(filepath):
            return None
        return b"print('data')"

    def _worker(file_path, filepath: str, *_args, **_kwargs):
        _ = file_path
        if "fail.py" in filepath or "none.py" in filepath:
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


# ---------------------------------------------------------------------------
# Tests: File snapshot creation in pipeline (Phase 5 - Storage Layer)
# ---------------------------------------------------------------------------


def test_process_file_worker_creates_snapshot_with_gaps(monkeypatch, tmp_path: Path) -> None:
    """When include_gaps=True and cache_enabled, a FileSnapshot should be created."""
    entity = _entity("src/gappy.py")
    rel = _relationship(entity.id)
    snapshot_calls: list[str] = []

    class _BaseExtractor:
        pass

    class _Extractor(_BaseExtractor):
        def parse_file(self, *_args, **_kwargs):
            return [entity], [rel]

    class _Cache:
        def __init__(self, cache_path: str):
            self.cache_path = cache_path
            self._store: dict = {}

        def get_ast(self, *_args):
            return None

        def set_ast(self, *_args):
            pass

        def set_file_snapshot(self, snapshot):
            snapshot_calls.append(snapshot.file_path)

    class _Detector:
        @staticmethod
        def get_extractor(*_args):
            return _Extractor()

    monkeypatch.setattr(pipeline, "ASTExtractor", _BaseExtractor)
    monkeypatch.setattr(pipeline, "BathoCache", _Cache)
    monkeypatch.setattr("batho.context.languages.detector.default_detector", _Detector())
    monkeypatch.setattr("batho.context.languages.registry.get_extractor", lambda _suffix: None)
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: b"print('hello')")

    file_path = tmp_path / "gappy.py"
    file_path.write_bytes(b"print('hello')")

    result = pipeline.process_file_worker(
        file_path,
        "src/gappy.py",
        1.0,
        20,
        True,
        str(tmp_path / "cache.db"),
        14,
        64,
        {},
        index_id=None,
        include_gaps=True,
    )

    assert result is not None
    assert result[0] == "src/gappy.py"
    assert len(snapshot_calls) == 1
    assert snapshot_calls[0] == "src/gappy.py"


def test_process_file_worker_skips_snapshot_without_gaps(monkeypatch, tmp_path: Path) -> None:
    """When include_gaps=False, no FileSnapshot should be created."""
    entity = _entity("src/nogaps.py")
    rel = _relationship(entity.id)
    snapshot_calls: list[str] = []

    class _BaseExtractor:
        pass

    class _Extractor(_BaseExtractor):
        def parse_file(self, *_args, **_kwargs):
            return [entity], [rel]

    class _Cache:
        def __init__(self, cache_path: str):
            self.cache_path = cache_path

        def get_ast(self, *_args):
            return None

        def set_ast(self, *_args):
            pass

        def set_file_snapshot(self, snapshot):
            snapshot_calls.append(snapshot.file_path)

    class _Detector:
        @staticmethod
        def get_extractor(*_args):
            return _Extractor()

    monkeypatch.setattr(pipeline, "ASTExtractor", _BaseExtractor)
    monkeypatch.setattr(pipeline, "BathoCache", _Cache)
    monkeypatch.setattr("batho.context.languages.detector.default_detector", _Detector())
    monkeypatch.setattr("batho.context.languages.registry.get_extractor", lambda _suffix: None)
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: b"print('bye')")

    file_path = tmp_path / "nogaps.py"
    file_path.write_bytes(b"print('bye')")

    result = pipeline.process_file_worker(
        file_path,
        "src/nogaps.py",
        1.0,
        15,
        True,
        str(tmp_path / "cache.db"),
        14,
        64,
        {},
        index_id=None,
        include_gaps=False,
    )

    assert result is not None
    assert len(snapshot_calls) == 0


def test_process_file_worker_creates_snapshot_on_cache_hit(monkeypatch, tmp_path: Path) -> None:
    """With a cache hit and include_gaps=True, a snapshot should still be created."""
    entity = _entity("src/cached_snap.py")
    snapshot_calls: list[str] = []

    class _Cache:
        def __init__(self, cache_path: str):
            self.cache_path = cache_path

        def get_ast(self, *_args):
            return [entity], []

        def get_file_snapshot(self, *_args):
            return None

        def set_file_snapshot(self, snapshot):
            snapshot_calls.append(snapshot.file_path)

    monkeypatch.setattr(pipeline, "BathoCache", _Cache)
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: b"x")

    file_path = tmp_path / "cached_snap.py"
    file_path.write_bytes(b"x")

    result = pipeline.process_file_worker(
        file_path,
        "src/cached_snap.py",
        1.0,
        10,
        True,
        str(tmp_path / "cache.db"),
        7,
        64,
        {},
        index_id=None,
        include_gaps=True,
    )

    assert result is not None
    assert result[3] is True  # cached_hit = True
    assert len(snapshot_calls) == 1
    assert snapshot_calls[0] == "src/cached_snap.py"


def test_process_file_worker_skips_snapshot_when_cache_disabled(monkeypatch, tmp_path: Path) -> None:
    """When cache_enabled=False, no FileSnapshot should be created."""
    entity = _entity("src/nocache.py")
    rel = _relationship(entity.id)
    snapshot_calls: list[str] = []

    class _BaseExtractor:
        pass

    class _Extractor(_BaseExtractor):
        def parse_file(self, *_args, **_kwargs):
            return [entity], [rel]

    class _Cache:
        def __init__(self, cache_path: str):
            self.cache_path = cache_path

        def get_ast(self, *_args):
            return None

        def set_ast(self, *_args):
            pass

        def set_file_snapshot(self, snapshot):
            snapshot_calls.append(snapshot.file_path)

    class _Detector:
        @staticmethod
        def get_extractor(*_args):
            return _Extractor()

    monkeypatch.setattr(pipeline, "ASTExtractor", _BaseExtractor)
    monkeypatch.setattr(pipeline, "BathoCache", _Cache)
    monkeypatch.setattr("batho.context.languages.detector.default_detector", _Detector())
    monkeypatch.setattr("batho.context.languages.registry.get_extractor", lambda _suffix: None)
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: b"print('test')")

    file_path = tmp_path / "nocache.py"
    file_path.write_bytes(b"print('test')")

    result = pipeline.process_file_worker(
        file_path,
        "src/nocache.py",
        1.0,
        10,
        False,
        str(tmp_path / "cache.db"),
        7,
        64,
        {},
        index_id=None,
        include_gaps=True,
    )

    assert result is not None
    assert len(snapshot_calls) == 0


def test_process_file_worker_cache_hit_enrichment(monkeypatch, tmp_path: Path) -> None:
    """Verify that cached entities are successfully enriched with raw content, bytes, and hash."""
    from batho.utils.hash import compute_bytes_hash

    # Create a cached entity that has offsets pointing to sliced content but raw_content=None
    cached_entity = Entity(
        type=EntityType.FUNCTION,
        name="fn_cached",
        file="src/enrich.py",
        start_line=1,
        end_line=1,
        start_byte=12,
        end_byte=27,
        raw_content=None,
        content_hash="",
        raw_bytes=None,
    )

    class _Cache:
        def __init__(self, cache_path: str):
            self.cache_path = cache_path

        def get_ast(self, *_args):
            return [cached_entity], []

    monkeypatch.setattr(pipeline, "BathoCache", _Cache)

    file_content = b"some prefix;def fn_cached(): pass; some suffix"
    file_path = tmp_path / "enrich.py"
    file_path.write_bytes(file_content)
    
    # Monkeypatch for the first call
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: file_content)

    # Slice is content[12:27] = b"def fn_cached()"
    expected_raw_content = "def fn_cached()"
    expected_hash = compute_bytes_hash(b"def fn_cached()")

    result = pipeline.process_file_worker(
        file_path,
        "src/enrich.py",
        1.0,
        len(file_content),
        True,
        str(tmp_path / "cache.db"),
        7,
        64,
        {},
    )

    assert result is not None
    filepath, entities, relationships, cached_hit = result
    assert cached_hit is True
    assert len(entities) == 1
    enriched = entities[0]
    assert enriched.raw_content == expected_raw_content
    assert enriched.content_hash == expected_hash
    assert enriched.raw_bytes is None  # Successful UTF-8 decode results in raw_bytes=None

    # Now verify with UnicodeDecodeError fallback (non-UTF-8 bytes)
    bad_bytes_entity = Entity(
        type=EntityType.FUNCTION,
        name="fn_bad",
        file="src/enrich.py",
        start_line=1,
        end_line=1,
        start_byte=0,
        end_byte=4,
        raw_content=None,
        content_hash="",
        raw_bytes=None,
    )

    class _CacheBad:
        def __init__(self, cache_path: str):
            self.cache_path = cache_path

        def get_ast(self, *_args):
            return [bad_bytes_entity], []

    monkeypatch.setattr(pipeline, "BathoCache", _CacheBad)

    bad_content = b"\xff\xfe\xfd\xfc"
    file_path.write_bytes(bad_content)
    
    # Monkeypatch for the second call
    monkeypatch.setattr(pipeline, "read_file_bytes", lambda *_args, **_kwargs: bad_content)

    result_bad = pipeline.process_file_worker(
        file_path,
        "src/enrich.py",
        1.0,
        4,
        True,
        str(tmp_path / "cache.db"),
        7,
        64,
        {},
    )
    assert result_bad is not None
    _, entities_bad, _, _ = result_bad
    enriched_bad = entities_bad[0]
    # Check that it contains replacement characters and raw_bytes is set
    assert "\ufffd" in enriched_bad.raw_content
    assert enriched_bad.raw_bytes == bad_content
    assert enriched_bad.content_hash == compute_bytes_hash(bad_content)
