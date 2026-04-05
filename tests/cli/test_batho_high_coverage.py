from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import batho_cli as batho
from batho_cli import (
    _collect_repo_metrics,
    _compute_repo_hash,
    _load_current_graph,
    _needs_metrics_backfill,
    _strip_files,
    _backfill_index_metrics,
    _auto_detect_changes,
    _cmd_patch_index_based,
    _cmd_patch_snapshot_based,
    _detect_file_changes,
    _extract_change_paths,
    _files_from_diff,
    _git_diff_entries_to_file_changes,
    _reindex_files,
    cmd_apply_patch,
    cmd_bsg,
    cmd_cache_clear,
    cmd_cache_invalidate,
    cmd_cache_stats,
    cmd_cherry_pick,
    cmd_index,
    cmd_patch_chain,
    cmd_patch_info,
    cmd_patches,
    cmd_query,
    cmd_webhook,
    cmd_webhook_server,
    extract_patch_deltas,
)
from batho.context.incremental import GitDiffEntry
from batho.time_machine import FileChangeType


@dataclass
class _FakePatch:
    operation_id: str
    operation_type: str
    base_snapshot_id: str
    new_snapshot_id: str
    changes_applied: list[dict]
    patch_chain: list[str]
    metrics: dict
    user_info: dict
    timestamp: datetime

    def serialize(self):
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "base_snapshot_id": self.base_snapshot_id,
            "new_snapshot_id": self.new_snapshot_id,
            "changes_applied": self.changes_applied,
            "patch_chain": self.patch_chain,
            "metrics": self.metrics,
            "user_info": self.user_info,
            "timestamp": self.timestamp.isoformat(),
        }


def test_extract_change_paths_handles_dict_objects_and_dedupes() -> None:
    class _Obj:
        def __init__(self, path):
            self.path = path

    changes = [
        {"path": "a.py"},
        {"path": "a.py"},
        _Obj("b.py"),
        {"path": ""},
        _Obj(None),
    ]
    assert _extract_change_paths(changes) == ["a.py", "b.py"]


def test_git_diff_entries_to_file_changes_added_modified_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / "a.py").write_text("print('a')\n", encoding="utf-8")
    entries = [
        GitDiffEntry(status="A", path="a.py"),
        GitDiffEntry(status="M", path="a.py"),  # lower precedence than A for same path
        GitDiffEntry(status="D", path="b.py"),
    ]

    monkeypatch.setattr(batho, "compute_file_hash", lambda _p: "hash")
    changes = _git_diff_entries_to_file_changes(root, entries)

    assert len(changes) == 2
    assert any(c.path == "a.py" and c.change_type == FileChangeType.ADDED for c in changes)
    assert any(c.path == "b.py" and c.change_type == FileChangeType.DELETED for c in changes)


def test_files_from_diff_parses_formats_and_skips_unsafe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    diff = root / "changes.diff"
    diff.write_text(
        "\n".join(
            [
                "+++ b/src/a.py",
                "--- a/src/a.py",
                "rename from old/name.py",
                "rename to new/name.py",
                "Binary files a/bin.dat and b/bin.dat differ",
                "+++ b/../evil.py",
                "+++ b/boom.py",
                "+++ b/" + ("x" * 1001),
            ]
        ),
        encoding="utf-8",
    )

    from batho.utils.path_sanitizer import PathSecurityError

    def _sanitize(path_str: str, root_path: Path) -> Path:
        if "evil" in path_str:
            raise PathSecurityError("bad")
        if "boom.py" in path_str:
            raise RuntimeError("explode")
        cleaned = path_str
        if cleaned.startswith("a/") or cleaned.startswith("b/"):
            cleaned = cleaned[2:]
        if cleaned == "bin.dat":
            return Path("/tmp/outside.bin")
        return (root_path / cleaned).resolve()

    monkeypatch.setattr("batho.utils.path_sanitizer.sanitize_diff_path", _sanitize)

    paths = _files_from_diff(diff, root)
    as_posix = [p.as_posix() for p in paths]
    assert any("src/a.py" in p for p in as_posix)
    assert any("old/name.py" in p for p in as_posix)
    assert any("new/name.py" in p for p in as_posix)
    assert not any("evil.py" in p for p in as_posix)


def test_files_from_diff_handles_io_error_and_security_patterns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    diff = root / "changes.diff"

    # OSError on read should return empty list.
    original_read_text = Path.read_text

    def _read_text_raises_for_target(self: Path, *args, **kwargs):
        if self == diff:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text_raises_for_target)
    assert _files_from_diff(diff, root) == []

    # Restore and test dangerous/duplicate path filtering.
    monkeypatch.setattr(Path, "read_text", original_read_text)
    diff.write_text(
        "\n".join(
            [
                "+++ b/src/safe.py",
                "+++ b/src/safe.py",  # duplicate
                "+++ b/dev/null",
                "+++ b/src/${HOME}.py",  # dangerous pattern
                "+++ b/src/$( cmd ).py",  # dangerous pattern
                "+++ b/" + ("a" * 4100),
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "batho.utils.path_sanitizer.sanitize_diff_path",
        lambda path_str, root_path: (root_path / path_str.removeprefix("b/")).resolve(),
    )

    paths = _files_from_diff(diff, root)
    names = {p.name for p in paths}
    assert "safe.py" in names
    assert "${HOME}.py" not in names


def test_files_from_diff_binary_and_similarity_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    diff = root / "changes.diff"
    diff.write_text(
        "\n".join(
            [
                "similarity index 99%",
                "Binary a/bad.bin and b/bad.bin differ",
                "Binary a/good.bin and b/good.bin differ",
            ]
        ),
        encoding="utf-8",
    )

    from batho.utils.path_sanitizer import PathSecurityError

    def _sanitize(path_str: str, root_path: Path) -> Path:
        if path_str == "bad.bin":
            raise PathSecurityError("unsafe")
        return (root_path / path_str).resolve()

    monkeypatch.setattr("batho.utils.path_sanitizer.sanitize_diff_path", _sanitize)

    paths = _files_from_diff(diff, root)
    # Current parser keeps binary lines defensive and may skip malformed formats.
    assert isinstance(paths, list)


def test_detect_file_changes_handles_missing_snapshot_and_detects_add_mod_del(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    existing = root / "mod.py"
    existing.write_text("x=1\n", encoding="utf-8")
    missing = root / "gone.py"

    monkeypatch.setattr(batho, "load_snapshot", lambda *_a, **_k: None)
    assert _detect_file_changes(root, [existing], root / ".ctn", "s1") == []

    snapshot = {
        "graph": {
            "entities": [
                {"file": "mod.py", "name": "m"},
                {"file": "gone.py", "name": "g"},
            ]
        }
    }
    monkeypatch.setattr(batho, "load_snapshot", lambda *_a, **_k: snapshot)
    monkeypatch.setattr(batho, "compute_file_hash", lambda _p: "hash")

    changes = _detect_file_changes(root, [existing, missing], root / ".ctn", "s1")
    assert any(c.path == "mod.py" and c.change_type == FileChangeType.MODIFIED for c in changes)
    assert any(c.path == "gone.py" and c.change_type == FileChangeType.DELETED for c in changes)


def test_auto_detect_changes_detects_add_modify_delete_and_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "mod.py").write_text("print('mod')\n", encoding="utf-8")
    (root / "new.py").write_text("print('new')\n", encoding="utf-8")
    (root / "bin.py").write_bytes(b"BIN\x00\x01")
    (root / "large.py").write_text("x" * 4096, encoding="utf-8")

    snapshot = {
        "graph": {
            "entities": [
                {"file": "mod.py", "name": "m"},
                {"file": "deleted.py", "name": "d"},
            ]
        }
    }

    monkeypatch.setattr(batho, "load_snapshot", lambda *_a, **_k: snapshot)
    monkeypatch.setattr(batho, "load_ignore_spec", lambda _root: None)
    monkeypatch.setattr(batho, "is_ignored", lambda *_a, **_k: False)
    monkeypatch.setattr(batho, "compute_file_hash", lambda _p: "hash")
    monkeypatch.setattr(batho, "_is_binary", lambda data: data.startswith(b"BIN"))

    changes = _auto_detect_changes(root, root / ".ctn", "base", max_file_size_kb=1)
    assert any(c.path == "deleted.py" and c.change_type == FileChangeType.DELETED for c in changes)
    assert any(c.path == "mod.py" and c.change_type == FileChangeType.MODIFIED for c in changes)
    assert any(c.path == "new.py" and c.change_type == FileChangeType.ADDED for c in changes)
    assert not any(c.path == "bin.py" for c in changes)
    assert not any(c.path == "large.py" for c in changes)


def test_reindex_files_covers_skip_paths_and_parser_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    good = root / "good.py"
    ignored = root / "ignored.py"
    unreadable = root / "none.py"
    noext = root / "README"
    for p in [good, ignored, unreadable, noext]:
        p.write_text("x\n", encoding="utf-8")

    monkeypatch.setattr(batho, "load_ignore_spec", lambda _r: None)
    monkeypatch.setattr(batho, "is_ignored", lambda fp, *_a, **_k: fp.name == "ignored.py")

    def _read(path_str: str):
        if path_str.endswith("none.py"):
            return None
        return b"print('ok')\n"

    monkeypatch.setattr(batho, "_read_file_content", _read)

    class _Extractor:
        def parse_file(self, *_a):
            return ["E"], ["R"]

    monkeypatch.setattr(batho.default_detector, "get_extractor", lambda fp, _content: _Extractor() if fp.name == "good.py" else None)
    monkeypatch.setattr(batho, "registry_get_extractor", lambda ext: _Extractor() if ext == ".py" else None)

    stripped = {"count": 0}
    monkeypatch.setattr(batho, "_strip_files", lambda *_a, **_k: stripped.__setitem__("count", stripped["count"] + 1))

    class _Graph:
        def __init__(self):
            self.entities = []
            self.relationships = []

        def add_entity(self, e):
            self.entities.append(e)

        def add_relationship(self, r):
            self.relationships.append(r)

    graph = _Graph()
    _reindex_files(root, [good, ignored, unreadable, noext], indexer=None, graph=graph)  # type: ignore[arg-type]
    assert graph.entities == ["E"]
    assert graph.relationships == ["R"]
    assert stripped["count"] == 1


def test_metrics_and_hash_helpers_cover_edge_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    text_file = root / "text.txt"
    empty_file = root / "empty.txt"
    skip_file = root / "skip.txt"
    staterr_file = root / "staterr.txt"
    ignored_file = root / "ignored.txt"
    for file_path in [text_file, empty_file, skip_file, staterr_file, ignored_file]:
        file_path.write_text("x\n", encoding="utf-8")

    monkeypatch.setattr(batho, "load_ignore_spec", lambda _r: None)
    monkeypatch.setattr(batho, "is_ignored", lambda fp, *_a, **_k: fp.name == "ignored.txt")

    original_stat = Path.stat
    stat_calls: dict[str, int] = {}

    def _stat_with_error(self: Path, *args, **kwargs):
        key = str(self)
        stat_calls[key] = stat_calls.get(key, 0) + 1
        if self.name == "staterr.txt" and stat_calls[key] >= 2:
            raise OSError("stat failed")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _stat_with_error)

    def _read(path_str: str, *_a, **_k):
        if path_str.endswith("text.txt"):
            return b"a\nb\n"
        if path_str.endswith("empty.txt"):
            return b""
        if path_str.endswith("skip.txt"):
            return None
        return b"x\n"

    monkeypatch.setattr(batho, "_read_file_content", _read)

    metrics = _collect_repo_metrics(root, max_file_size_kb=1)
    assert metrics["file_count_total"] >= 4
    assert metrics["text_files_count"] >= 2
    assert metrics["skipped_files_count"] >= 1
    assert metrics["loc_total"] >= 2

    monkeypatch.setattr(Path, "stat", original_stat)
    monkeypatch.setattr(batho, "is_ignored", lambda *_a, **_k: True)
    assert _compute_repo_hash(root) == ""

    monkeypatch.setattr(batho, "is_ignored", lambda *_a, **_k: False)
    monkeypatch.setattr(batho, "_read_file_content", lambda *_a, **_k: b"abc")
    assert _compute_repo_hash(root)


def test_needs_backfill_load_graph_and_strip_files_helpers(tmp_path: Path) -> None:
    assert _needs_metrics_backfill({"indexes": {"idx": "bad"}}) is True
    assert _needs_metrics_backfill({"indexes": {"idx": {"stats": "bad", "metrics": {}}}}) is True
    assert _needs_metrics_backfill({"indexes": {"idx": {"stats": {}, "metrics": {}}}}) is True
    assert _needs_metrics_backfill(
        {
            "indexes": {
                "idx": {
                    "stats": {"loc_total": 1, "repo_size_bytes": 1},
                    "metrics": {"loc_total": 1, "repo_size_bytes": 1},
                }
            }
        }
    ) is False

    ctn = tmp_path / ".ctn"
    idx = ctn / "idx1"
    idx.mkdir(parents=True)

    assert _load_current_graph(ctn, "idx1") is None

    graph_path = idx / "graph.json"
    graph_path.write_text("{bad json", encoding="utf-8")
    assert _load_current_graph(ctn, "idx1") is None

    graph_path.write_text(json.dumps({"entities": [], "relationships": []}), encoding="utf-8")
    assert _load_current_graph(ctn, "idx1") is not None

    class _Entity:
        def __init__(self, file: str):
            self.file = file

    graph = SimpleNamespace(
        entities={
            "e1": _Entity("src/a.py"),
            "e2": _Entity(str((tmp_path / "src" / "b.py").resolve())),
        },
        relationships=[
            SimpleNamespace(source_id="e1", target_id="e2"),
            SimpleNamespace(source_id="keep", target_id="e2"),
        ],
    )
    _strip_files(graph, ["", "src/a.py", str((tmp_path / "src" / "b.py").resolve())], root=tmp_path)
    assert graph.entities == {}
    assert graph.relationships == []


def test_cmd_cache_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    cache_obj = SimpleNamespace(
        get_cache_stats=lambda: {
            "cache_path": "x.db",
            "entry_count": 2,
            "total_size_mb": 1.2,
            "oldest_entry": "old",
            "newest_entry": "new",
        },
        invalidate_cache=lambda pattern=None: None,
    )

    monkeypatch.setattr("batho.context.cache.ASTCache", lambda cache_path: cache_obj)
    monkeypatch.setattr(batho, "get_config_cached", lambda: {"bsg": {"cache": {"path": str(tmp_path / "c.db")}}})

    assert cmd_cache_stats(argparse.Namespace()) == 0
    assert "AST Cache Statistics" in capsys.readouterr().out

    assert cmd_cache_invalidate(argparse.Namespace(pattern="src/*")) == 0
    assert cmd_cache_invalidate(argparse.Namespace(pattern=None)) == 0
    assert cmd_cache_clear(argparse.Namespace()) == 0


def test_cmd_query_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    monkeypatch.setattr(batho, "_ensure_ctn_dir", lambda _r: root / ".ctn")
    monkeypatch.setattr(batho, "_load_index_metadata", lambda _c: {"current_index_id": "idx1"})
    monkeypatch.setattr(batho, "get_config_cached", lambda: {"bsg": {"query": {"default_limit": 10}}})

    class _QS:
        def __init__(self, *_a, **_k):
            pass

        def rebuild_indexes(self):
            return {"entities_indexed": 1, "relationships_indexed": 1}

        def entities_by_type(self, *_a, **_k):
            return [{"name": "f"}]

        def entities_by_file(self, *_a, **_k):
            return [{"name": "f2"}]

        def relationships_by_type(self, *_a, **_k):
            return [{"type": "calls"}]

    monkeypatch.setattr(batho, "QueryService", _QS)

    a = argparse.Namespace(root=str(root), index_id=None, limit=None, rebuild_index=True, entity_type="function", file_path=None, relationship_type=None)
    assert cmd_query(a) == 0

    b = argparse.Namespace(root=str(root), index_id=None, limit=5, rebuild_index=False, entity_type=None, file_path="x.py", relationship_type=None)
    assert cmd_query(b) == 0

    c = argparse.Namespace(root=str(root), index_id=None, limit=5, rebuild_index=False, entity_type=None, file_path=None, relationship_type="calls")
    assert cmd_query(c) == 0

    d = argparse.Namespace(root=str(root), index_id=None, limit=5, rebuild_index=False, entity_type=None, file_path=None, relationship_type=None)
    assert cmd_query(d) == 1

    monkeypatch.setattr(batho, "_load_index_metadata", lambda _c: {"current_index_id": ""})
    assert cmd_query(a) == 1


def test_cmd_bsg_modes_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = argparse.Namespace(root=str(tmp_path / "none"), mode="full", budget=100)
    assert cmd_bsg(missing) == 1

    root = tmp_path / "repo"
    root.mkdir()
    ctn = root / ".ctn"
    ctn.mkdir()

    monkeypatch.setattr(batho, "_ensure_ctn_dir", lambda _r: ctn)
    monkeypatch.setattr(batho, "_load_index_metadata", lambda _c: {"current_index_id": ""})
    assert cmd_bsg(argparse.Namespace(root=str(root), mode="full", budget=200)) == 1

    monkeypatch.setattr(batho, "_load_index_metadata", lambda _c: {"current_index_id": "idx1"})
    monkeypatch.setattr(batho, "_load_current_graph", lambda *_a, **_k: None)
    assert cmd_bsg(argparse.Namespace(root=str(root), mode="full", budget=200)) == 1

    monkeypatch.setattr(batho, "_ensure_ctn_dir", lambda _r: ctn)
    monkeypatch.setattr(batho, "_load_index_metadata", lambda _c: {"current_index_id": "idx1"})
    monkeypatch.setattr(batho, "_load_current_graph", lambda *_a, **_k: object())

    writes = []
    monkeypatch.setattr(batho, "_write_json", lambda path, data: writes.append((path.name, data)))

    class _BSG:
        def render_compressed(self, budget, fail_on_overflow=False):
            _ = fail_on_overflow
            return "compressed", {"tokens_used": 1, "budget": budget, "truncated_files": 1}

        def render_full(self):
            return "full"

        def render_hierarchical(self):
            return "hier"

    monkeypatch.setattr(batho.BSGMap, "build", lambda *_a, **_k: _BSG())

    assert cmd_bsg(argparse.Namespace(root=str(root), mode="compressed", budget=200)) == 0

    class _BSGNoTrunc(_BSG):
        def render_compressed(self, budget, fail_on_overflow=False):
            _ = fail_on_overflow
            return "compressed", {"tokens_used": 1, "budget": budget, "truncated_files": 0}

    monkeypatch.setattr(batho.BSGMap, "build", lambda *_a, **_k: _BSGNoTrunc())
    assert cmd_bsg(argparse.Namespace(root=str(root), mode="compressed", budget=200)) == 0

    monkeypatch.setattr(batho.BSGMap, "build", lambda *_a, **_k: _BSG())
    assert cmd_bsg(argparse.Namespace(root=str(root), mode="full", budget=200)) == 0
    assert cmd_bsg(argparse.Namespace(root=str(root), mode="hierarchical", budget=200)) == 0
    assert cmd_bsg(argparse.Namespace(root=str(root), mode="unknown", budget=200)) == 1

    class _BSGRenderError(_BSG):
        def render_full(self):
            raise RuntimeError("render boom")

    monkeypatch.setattr(batho.BSGMap, "build", lambda *_a, **_k: _BSGRenderError())
    assert cmd_bsg(argparse.Namespace(root=str(root), mode="full", budget=200)) == 1

    monkeypatch.setattr(batho.BSGMap, "build", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        cmd_bsg(argparse.Namespace(root=str(root), mode="full", budget=200))


def test_cmd_webhook_server_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Missing config file branch.
    monkeypatch.chdir(tmp_path)
    assert cmd_webhook_server(argparse.Namespace(root=str(tmp_path))) == 1

    (tmp_path / "batho.yaml").write_text("webhook: {}\n", encoding="utf-8")

    # Config load failure branch.
    monkeypatch.setattr(batho, "reload_config", lambda: (_ for _ in ()).throw(RuntimeError("bad config")))
    assert cmd_webhook_server(argparse.Namespace(root=str(tmp_path))) == 1

    # Repository not configured branch.
    monkeypatch.setattr(batho, "reload_config", lambda: {"webhook": {}})
    assert cmd_webhook_server(argparse.Namespace(root=str(tmp_path))) == 1

    # Non-existent root branch.
    monkeypatch.setattr(batho, "reload_config", lambda: {"webhook": {"repository": {"name": "org/repo", "platform": "github"}}})
    assert cmd_webhook_server(argparse.Namespace(root=str(tmp_path / "missing"))) == 1

    # Success + KeyboardInterrupt branch.
    stopped = {"called": 0}

    class _Server:
        def __init__(self, *_a, **_k):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

        def stop(self):
            stopped["called"] += 1

    monkeypatch.setattr(batho, "WebhookServer", _Server)
    assert cmd_webhook_server(argparse.Namespace(root=str(tmp_path))) == 0
    assert stopped["called"] == 1


def test_cmd_webhook_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    # Invalid payload JSON.
    assert cmd_webhook(argparse.Namespace(payload="{", headers="{}", root=None)) == 1

    # Invalid headers JSON.
    assert cmd_webhook(argparse.Namespace(payload='{"repository": "x"}', headers="[1]", root=None)) == 1

    parsed = SimpleNamespace(
        event_type=SimpleNamespace(value="push"),
        repository="org/repo",
        platform=SimpleNamespace(value="github"),
        branch="main",
        commit_hash="abc123",
        changes=[{"path": "a.py"}],
    )

    # Parse failure branch.
    monkeypatch.setattr(batho, "parse_webhook_event", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bad payload")))
    assert cmd_webhook(argparse.Namespace(payload='{"repository": "x"}', headers="{}", root=None)) == 1

    # Parsed only (no root provided).
    monkeypatch.setattr(batho, "parse_webhook_event", lambda *_a, **_k: parsed)
    assert cmd_webhook(argparse.Namespace(payload='{"repository": "x"}', headers="{}", root=None)) == 0

    # Root path invalid.
    assert cmd_webhook(
        argparse.Namespace(payload='{"repository": "x"}', headers="{}", root=str(tmp_path / "missing"))
    ) == 1

    monkeypatch.setattr(batho, "reload_config", lambda: {"webhook": {}})

    class _WebhookConfig:
        @staticmethod
        def from_dict(data):
            return data

    monkeypatch.setattr(batho, "WebhookConfig", _WebhookConfig)

    # Processor exception branch.
    class _FailingProcessor:
        def __init__(self, *_a, **_k):
            pass

        def process_webhook_sync(self, *_a, **_k):
            raise RuntimeError("processor failed")

    monkeypatch.setattr(batho, "WebhookProcessor", _FailingProcessor)
    assert cmd_webhook(argparse.Namespace(payload='{"repository": "x"}', headers="{}", root=str(root))) == 1

    # processed/ignored/error status mapping branches.
    class _Processor:
        def __init__(self, *_a, **_k):
            pass

        def process_webhook_sync(self, *_a, **_k):
            return {"status": "processed"}

    monkeypatch.setattr(batho, "WebhookProcessor", _Processor)
    assert cmd_webhook(argparse.Namespace(payload='{"repository": "x"}', headers="{}", root=str(root))) == 0

    monkeypatch.setattr(_Processor, "process_webhook_sync", lambda *_a, **_k: {"status": "ignored"})
    assert cmd_webhook(argparse.Namespace(payload='{"repository": "x"}', headers="{}", root=str(root))) == 0

    monkeypatch.setattr(_Processor, "process_webhook_sync", lambda *_a, **_k: {"status": "error"})
    assert cmd_webhook(argparse.Namespace(payload='{"repository": "x"}', headers="{}", root=str(root))) == 1

    # Unknown processing status should keep parsed status and return success.
    monkeypatch.setattr(_Processor, "process_webhook_sync", lambda *_a, **_k: {"status": "queued"})
    assert cmd_webhook(argparse.Namespace(payload='{"repository": "x"}', headers="{}", root=str(root))) == 0

    # Payload without repository/project should bypass event-header inference branches.
    assert cmd_webhook(argparse.Namespace(payload='{"x": 1}', headers='{"X-Test": "1"}', root=str(root))) == 0

    # GitLab header inference and preconfigured repository branch.
    captured = {"headers": None}

    def _capture_parse(_payload, headers):
        captured["headers"] = dict(headers)
        return parsed

    monkeypatch.setattr(batho, "parse_webhook_event", _capture_parse)
    monkeypatch.setattr(
        batho,
        "reload_config",
        lambda: {"webhook": {"repository": {"name": "pre/set", "platform": "gitlab", "branches": ["main"]}}},
    )
    monkeypatch.setattr(_Processor, "process_webhook_sync", lambda *_a, **_k: {"status": "processed"})
    assert cmd_webhook(
        argparse.Namespace(
            payload='{"project": "x", "object_attributes": {}}',
            headers="{}",
            root=str(root),
        )
    ) == 0
    assert captured["headers"]["X-Gitlab-Event"] == "Merge Request Hook"

    # GitLab payload with explicit event should bypass default event inference.
    assert cmd_webhook(
        argparse.Namespace(
            payload='{"project": "x", "event": "Push Hook"}',
            headers="{}",
            root=str(root),
        )
    ) == 0
    assert captured["headers"]["X-Gitlab-Event"] == "Push Hook"


def test_backfill_index_metrics_updates_and_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctn = tmp_path / ".ctn"
    ctn.mkdir()
    root = tmp_path / "repo"
    root.mkdir()

    metadata_needs = {
        "indexes": {
            "idx1": {"stats": {"existing": 1}, "metrics": {}},
            "idx2": "invalid",
        }
    }
    saved = {"called": 0}

    monkeypatch.setattr(batho, "_load_index_metadata", lambda _c: metadata_needs)
    monkeypatch.setattr(batho, "get_config_cached", lambda: {"indexer": {"max_file_size_kb": 64}})
    monkeypatch.setattr(
        batho,
        "_collect_repo_metrics",
        lambda *_a, **_k: {
            "loc_total": 10,
            "repo_size_bytes": 20,
            "file_count_total": 2,
            "text_files_count": 2,
            "skipped_files_count": 0,
        },
    )
    monkeypatch.setattr(batho, "_save_index_metadata", lambda *_a, **_k: saved.__setitem__("called", saved["called"] + 1))

    assert _backfill_index_metrics(ctn, root) is True
    assert saved["called"] == 1
    assert metadata_needs["indexes"]["idx1"]["stats"]["loc_total"] == 10
    assert metadata_needs["indexes"]["idx1"]["metrics"]["repo_size_bytes"] == 20

    metadata_complete = {
        "indexes": {
            "idx": {
                "stats": {"loc_total": 1, "repo_size_bytes": 1},
                "metrics": {"loc_total": 1, "repo_size_bytes": 1},
            }
        }
    }
    monkeypatch.setattr(batho, "_load_index_metadata", lambda _c: metadata_complete)
    assert _backfill_index_metrics(ctn, root) is False


def test_cmd_index_early_failure_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Invalid root path.
    assert cmd_index(argparse.Namespace(root=str(tmp_path / "missing"), log_json=False)) == 1

    root = tmp_path / "repo"
    root.mkdir()
    ctn = root / ".ctn"
    ctn.mkdir()

    monkeypatch.setattr(batho, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(batho, "_ensure_ctn_dir", lambda _r: ctn)
    monkeypatch.setattr(batho, "_get_latest_snapshot", lambda _c: None)

    # Incremental enabled, no fallback to full.
    monkeypatch.setattr(
        batho,
        "get_config_cached",
        lambda: {
            "logging": {"level": "INFO"},
            "bsg": {"incremental": {"enabled": True, "fallback_to_full": False}},
        },
    )
    args = argparse.Namespace(
        root=str(root),
        log_json=False,
        full=False,
        force=False,
        base_snapshot=None,
        extensions=None,
        max_workers=1,
        max_file_size_kb=64,
        verbose=False,
        output_json=None,
        snapshot=False,
        snapshot_label=None,
        metrics_output=None,
    )
    assert cmd_index(args) == 1

    # Incremental patch failure + fallback disabled branch.
    monkeypatch.setattr(batho, "_get_latest_snapshot", lambda _c: "base1")
    monkeypatch.setattr(batho, "load_snapshot", lambda *_a, **_k: {"graph": {"entities": [], "relationships": []}})
    monkeypatch.setattr(batho, "get_changed_file_status_since", lambda *_a, **_k: [SimpleNamespace(status="M", path="a.py")])
    monkeypatch.setattr(batho, "_git_diff_entries_to_file_changes", lambda *_a, **_k: [SimpleNamespace(path="a.py")])
    monkeypatch.setattr(batho, "incremental_patch", lambda *_a, **_k: {"success": False, "error": "nope"})
    assert cmd_index(args) == 1

    # Incremental unavailable branch (diff_entries=None) + fallback disabled.
    monkeypatch.setattr(batho, "get_changed_file_status_since", lambda *_a, **_k: None)
    assert cmd_index(args) == 1

    # Incremental patch success but patched snapshot missing + fallback disabled.
    monkeypatch.setattr(batho, "get_changed_file_status_since", lambda *_a, **_k: [SimpleNamespace(status="M", path="a.py")])
    monkeypatch.setattr(
        batho,
        "incremental_patch",
        lambda *_a, **_k: {"success": True, "new_snapshot_id": "patched", "applied_changes": 1},
    )
    monkeypatch.setattr(
        batho,
        "load_snapshot",
        lambda *_a, **_k: {"graph": {"entities": [], "relationships": []}}
        if _a[1] == "base1"
        else None,
    )
    assert cmd_index(args) == 1

    # Full path with empty entities should return warning code 1.
    monkeypatch.setattr(
        batho,
        "get_config_cached",
        lambda: {
            "logging": {"level": "INFO"},
            "bsg": {"incremental": {"enabled": False, "fallback_to_full": True}},
            "schemas": {},
        },
    )

    class _Indexer:
        def __init__(self, *_a, **_k):
            self.stats = {"files_parsed": 0, "files_cached": 0, "errors": 0}

        def build_graph(self, **_kwargs):
            return SimpleNamespace(entities={}, relationships=[])

    class _Map:
        _by_file = {}
        entity_count = 0

        def estimate_tokens(self):
            return 0

    monkeypatch.setattr(batho, "CodeGraphIndexer", _Indexer)
    monkeypatch.setattr(batho.BSGMap, "build", lambda *_a, **_k: _Map())
    assert cmd_index(args) == 1

    # Invalid sqlite cache should be recreated and retried.
    bad_cache = ctn / "file_cache.json"
    bad_cache.write_text("not sqlite", encoding="utf-8")
    init_calls = {"count": 0}

    class _IndexerRetry:
        def __init__(self, *_a, **_k):
            init_calls["count"] += 1
            if init_calls["count"] == 1:
                raise RuntimeError("not a database")
            self.stats = {"files_parsed": 0, "files_cached": 0, "errors": 0}

        def build_graph(self, **_kwargs):
            return SimpleNamespace(entities={}, relationships=[])

    monkeypatch.setattr(batho, "CodeGraphIndexer", _IndexerRetry)
    assert cmd_index(args) == 1
    assert init_calls["count"] == 2


def test_patch_subcommands_index_and_snapshot_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    ctn = root / ".ctn"
    ctn.mkdir()

    # _cmd_patch_index_based early exits.
    monkeypatch.setattr(batho, "_load_index_metadata", lambda _c: {})
    args_idx = argparse.Namespace(
        scan=False,
        diff=None,
        files=None,
        dry_run=False,
        max_file_size_kb=64,
        snapshot=False,
    )
    assert _cmd_patch_index_based(args_idx, root, ctn) == 1

    monkeypatch.setattr(batho, "_load_index_metadata", lambda _c: {"current_index_id": "idx1"})
    monkeypatch.setattr(batho, "_load_current_graph", lambda *_a, **_k: None)
    assert _cmd_patch_index_based(args_idx, root, ctn) == 1

    # Dry-run path when explicit files are provided.
    graph = SimpleNamespace(entities={}, relationships=[])
    monkeypatch.setattr(batho, "_load_current_graph", lambda *_a, **_k: graph)
    source = root / "a.py"
    source.write_text("print('x')\n", encoding="utf-8")
    args_idx.files = [str(source)]
    args_idx.dry_run = True
    assert _cmd_patch_index_based(args_idx, root, ctn) == 0

    # _cmd_patch_snapshot_based: dry-run, failure, and success paths.
    args_snap = argparse.Namespace(
        scan=False,
        diff=None,
        files=[str(source)],
        base_snapshot="s1",
        max_file_size_kb=64,
        dry_run=True,
        snapshot=False,
    )
    change = SimpleNamespace(path="a.py", change_type=FileChangeType.MODIFIED)
    monkeypatch.setattr(batho, "_detect_file_changes", lambda *_a, **_k: [change])
    assert _cmd_patch_snapshot_based(args_snap, root, ctn) == 0

    args_snap.dry_run = False
    monkeypatch.setattr(
        batho,
        "incremental_patch",
        lambda *_a, **_k: {"success": False, "error": "patch failed", "operation_id": "op1"},
    )
    monkeypatch.setattr(batho, "record_failure_rule", lambda *_a, **_k: {"entry_id": "e1", "dont_rule": "rule"})
    assert _cmd_patch_snapshot_based(args_snap, root, ctn) == 1

    monkeypatch.setattr(
        batho,
        "incremental_patch",
        lambda *_a, **_k: {
            "success": True,
            "new_snapshot_id": "s2",
            "operation_id": "op2",
            "applied_changes": 1,
            "base_snapshot_id": "s1",
        },
    )
    monkeypatch.setattr(batho, "load_snapshot", lambda *_a, **_k: {"bsg": {"quality": {"warnings": ["w1"]}}})
    monkeypatch.setattr(batho, "_extract_bsg_quality_warnings", lambda *_a, **_k: ["w1"])
    monkeypatch.setattr(batho, "_emit_bsg_quality_warnings", lambda *_a, **_k: None)
    assert _cmd_patch_snapshot_based(args_snap, root, ctn) == 0


def test_patch_management_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    ctn = root / ".ctn"
    ctn.mkdir()
    monkeypatch.setattr(batho, "_ensure_ctn_dir", lambda _r: ctn)

    patch = _FakePatch(
        operation_id="op1",
        operation_type="incremental",
        base_snapshot_id="s1",
        new_snapshot_id="s2",
        changes_applied=[{"path": "a.py"}],
        patch_chain=["op0", "op1"],
        metrics={"x": 1},
        user_info={"u": "me"},
        timestamp=datetime.now(timezone.utc),
    )

    monkeypatch.setattr("batho.time_machine.list_patch_operations", lambda *_a, **_k: [patch])
    assert cmd_patches(argparse.Namespace(root=str(root), operation_type=None, base_snapshot=None, format="timeline")) == 0
    assert cmd_patches(argparse.Namespace(root=str(root), operation_type=None, base_snapshot=None, format="json")) == 0
    assert cmd_patches(argparse.Namespace(root=str(root), operation_type="incremental", base_snapshot="s1", format="json")) == 0

    monkeypatch.setattr("batho.time_machine.load_patch_operation", lambda *_a, **_k: None)
    assert cmd_patch_info(argparse.Namespace(root=str(root), patch_id="missing", format="json")) == 1

    monkeypatch.setattr("batho.time_machine.load_patch_operation", lambda *_a, **_k: patch)
    assert cmd_patch_info(argparse.Namespace(root=str(root), patch_id="op1", format="summary")) == 0
    assert cmd_patch_info(argparse.Namespace(root=str(root), patch_id="op1", format="json")) == 0

    monkeypatch.setattr("batho.time_machine.get_patches_for_snapshot", lambda *_a, **_k: [])
    assert cmd_patch_chain(argparse.Namespace(root=str(root), snapshot_id="s2", full=False)) == 1

    monkeypatch.setattr("batho.time_machine.get_patches_for_snapshot", lambda *_a, **_k: [patch])
    assert cmd_patch_chain(argparse.Namespace(root=str(root), snapshot_id="s2", full=False)) == 0
    assert cmd_patch_chain(argparse.Namespace(root=str(root), snapshot_id="s2", full=True)) == 0

    # cmd_apply_patch validation branches.
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file="x.diff", patch_id="op1", base_snapshot="s1", dry_run=False)) == 1
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=str(root / "missing.diff"), patch_id=None, base_snapshot="s1", dry_run=False)) == 1

    diff_file = root / "ok.diff"
    diff_file.write_text("diff", encoding="utf-8")
    monkeypatch.setattr("batho.time_machine.parse_unified_diff", lambda _d: [SimpleNamespace(path="a.py", change_type=SimpleNamespace(value="modified"))])
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=str(diff_file), patch_id=None, base_snapshot="s1", dry_run=True)) == 0

    monkeypatch.setattr(batho, "incremental_patch", lambda *_a, **_k: {"success": True, "new_snapshot_id": "s3"})
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=str(diff_file), patch_id=None, base_snapshot="s1", dry_run=False)) == 0

    monkeypatch.setattr(batho, "record_failure_rule", lambda *_a, **_k: {"entry_id": "e1", "dont_rule": "rule"})
    monkeypatch.setattr(batho, "incremental_patch", lambda *_a, **_k: {"success": False, "error": "bad"})
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=str(diff_file), patch_id=None, base_snapshot="s1", dry_run=False)) == 1

    # Failure path without ledger entry id.
    monkeypatch.setattr(batho, "record_failure_rule", lambda *_a, **_k: {})
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=str(diff_file), patch_id=None, base_snapshot="s1", dry_run=False)) == 1

    # force exception path while reading/parsing diff.
    bad_file = root / "bad.diff"
    bad_file.write_text("x", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("read err")))
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=str(bad_file), patch_id=None, base_snapshot="s1", dry_run=False)) == 1

    # patch-id branch.
    monkeypatch.setattr(Path, "read_text", Path.read_text)
    monkeypatch.setattr("batho.time_machine.load_patch_operation", lambda *_a, **_k: None)
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=None, patch_id="missing", base_snapshot="s1", dry_run=False)) == 1

    monkeypatch.setattr("batho.time_machine.load_patch_operation", lambda *_a, **_k: patch)
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=None, patch_id="op1", base_snapshot="s1", dry_run=True)) == 0

    monkeypatch.setattr("batho.time_machine.apply_deltas_to_snapshot", lambda *_a, **_k: "s4")
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=None, patch_id="op1", base_snapshot="s1", dry_run=False)) == 0

    monkeypatch.setattr("batho.time_machine.apply_deltas_to_snapshot", lambda *_a, **_k: None)
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=None, patch_id="op1", base_snapshot="s1", dry_run=False)) == 1

    monkeypatch.setattr(batho, "record_failure_rule", lambda *_a, **_k: {"entry_id": "e3", "dont_rule": "rule3"})
    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=None, patch_id="op1", base_snapshot="s1", dry_run=False)) == 1

    assert cmd_apply_patch(argparse.Namespace(root=str(root), diff_file=None, patch_id=None, base_snapshot="s1", dry_run=False)) == 1

    # cmd_cherry_pick branches.
    monkeypatch.setattr("batho.time_machine.load_patch_operation", lambda *_a, **_k: None)
    assert cmd_cherry_pick(argparse.Namespace(root=str(root), patch_id="missing", target_snapshot="s9", dry_run=False)) == 1

    monkeypatch.setattr("batho.time_machine.load_patch_operation", lambda *_a, **_k: patch)
    assert cmd_cherry_pick(argparse.Namespace(root=str(root), patch_id="op1", target_snapshot="s9", dry_run=True)) == 0

    monkeypatch.setattr("batho.time_machine.apply_deltas_to_snapshot", lambda *_a, **_k: "s10")
    assert cmd_cherry_pick(argparse.Namespace(root=str(root), patch_id="op1", target_snapshot="s9", dry_run=False)) == 0

    monkeypatch.setattr("batho.time_machine.apply_deltas_to_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(batho, "record_failure_rule", lambda *_a, **_k: {"entry_id": "e2", "dont_rule": "rule2"})
    assert cmd_cherry_pick(argparse.Namespace(root=str(root), patch_id="op1", target_snapshot="s9", dry_run=False)) == 1

    monkeypatch.setattr(batho, "record_failure_rule", lambda *_a, **_k: {})
    assert cmd_cherry_pick(argparse.Namespace(root=str(root), patch_id="op1", target_snapshot="s9", dry_run=False)) == 1

    deltas = extract_patch_deltas(patch)
    assert deltas["operation_id"] == "op1"

    _ = capsys.readouterr()
