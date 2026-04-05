from __future__ import annotations

from pathlib import Path

from batho.context import mmap_storage


def test_read_text_with_optional_mmap_disabled(tmp_path: Path) -> None:
    path = tmp_path / "small.txt"
    path.write_text("hello", encoding="utf-8")

    content = mmap_storage.read_text_with_optional_mmap(
        path,
        mmap_enabled=False,
        min_size_bytes=1,
    )

    assert content == "hello"


def test_read_text_with_optional_mmap_falls_back_when_stat_fails() -> None:
    class _NoStatPath:
        @staticmethod
        def stat():
            raise OSError("no stat")

        @staticmethod
        def read_text(encoding: str = "utf-8") -> str:
            _ = encoding
            return "fallback"

    content = mmap_storage.read_text_with_optional_mmap(
        _NoStatPath(),
        mmap_enabled=True,
        min_size_bytes=1,
    )

    assert content == "fallback"


def test_read_text_with_optional_mmap_falls_back_for_small_files(tmp_path: Path) -> None:
    path = tmp_path / "small.txt"
    path.write_text("abc", encoding="utf-8")

    content = mmap_storage.read_text_with_optional_mmap(
        path,
        mmap_enabled=True,
        min_size_bytes=10,
    )

    assert content == "abc"


def test_read_text_with_optional_mmap_reads_via_mmap(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_text("hello mmap", encoding="utf-8")

    content = mmap_storage.read_text_with_optional_mmap(
        path,
        mmap_enabled=True,
        min_size_bytes=1,
    )

    assert content == "hello mmap"


def test_read_text_with_optional_mmap_falls_back_on_mmap_errors(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "large.txt"
    path.write_text("fallback text", encoding="utf-8")

    def _raise(*_args, **_kwargs):
        raise ValueError("bad mmap")

    monkeypatch.setattr(mmap_storage.mmap, "mmap", _raise)

    content = mmap_storage.read_text_with_optional_mmap(
        path,
        mmap_enabled=True,
        min_size_bytes=1,
    )

    assert content == "fallback text"


def test_load_json_with_optional_mmap_returns_dict(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text('{"ok": true}', encoding="utf-8")

    payload = mmap_storage.load_json_with_optional_mmap(
        path,
        mmap_enabled=True,
        min_size_bytes=1,
    )

    assert payload == {"ok": True}


def test_load_json_with_optional_mmap_returns_empty_for_non_object(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    payload = mmap_storage.load_json_with_optional_mmap(
        path,
        mmap_enabled=True,
        min_size_bytes=1,
    )

    assert payload == {}
