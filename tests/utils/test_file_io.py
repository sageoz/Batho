from __future__ import annotations

from pathlib import Path

from batho.utils import file_io


def test_read_file_bytes_uses_config_default_limit(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "large.bin"
    path.write_bytes(b"x" * 2048)

    monkeypatch.setattr(file_io, "get_config_cached", lambda: {"indexer": {"max_file_size_kb": 1}})

    assert file_io.read_file_bytes(path, max_size_kb=None) is None


def test_read_file_bytes_without_normalization_returns_raw_bytes(tmp_path: Path) -> None:
    path = tmp_path / "raw.bin"
    raw = b"\xff\xfe\x00abc"
    path.write_bytes(raw)

    result = file_io.read_file_bytes(path, normalize_encoding=False, detect_binary=False)
    assert result == raw


def test_read_file_text_returns_none_for_binary_content(tmp_path: Path) -> None:
    path = tmp_path / "binary.dat"
    path.write_bytes(b"\x00\x01\x02")

    result = file_io.read_file_text(path)
    assert result is None


def test_read_file_text_uses_decode_fallback(monkeypatch) -> None:
    monkeypatch.setattr(file_io, "read_file_bytes", lambda *_args, **_kwargs: b"\xff\xfe")
    monkeypatch.setattr(
        "batho.utils.encoding.decode_bytes_with_fallback",
        lambda _data, errors="replace": f"fallback:{errors}",
    )

    result = file_io.read_file_text("unused", encoding="utf-8", errors="strict")
    assert result == "fallback:strict"


def test_write_atomically_handles_json_bytes_and_text(tmp_path: Path) -> None:
    json_target = tmp_path / "payload.json"
    bytes_target = tmp_path / "payload.bin"
    text_target = tmp_path / "payload.txt"

    assert file_io.write_atomically(json_target, '{"ok": true}', is_json=True) is True
    assert '"ok": true' in json_target.read_text(encoding="utf-8")

    assert file_io.write_atomically(bytes_target, b"abc") is True
    assert bytes_target.read_bytes() == b"abc"

    assert file_io.write_atomically(text_target, "hello") is True
    assert text_target.read_text(encoding="utf-8") == "hello"


def test_write_atomically_failure_removes_stale_temp_file(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "result.txt"
    temp_path = target.with_suffix(".txt.tmp")
    temp_path.write_bytes(b"stale")

    def _raise_write(self: Path, data: bytes) -> int:
        _ = self, data
        raise OSError("write failed")

    monkeypatch.setattr(Path, "write_bytes", _raise_write)

    assert file_io.write_atomically(target, "content") is False
    assert not temp_path.exists()


def test_write_atomically_ignores_temp_cleanup_failure(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "result.txt"
    temp_path = target.with_suffix(".txt.tmp")
    temp_path.write_bytes(b"stale")

    def _raise_write(self: Path, data: bytes) -> int:
        _ = self, data
        raise OSError("write failed")

    def _raise_unlink(self: Path) -> None:
        _ = self
        raise OSError("unlink failed")

    monkeypatch.setattr(Path, "write_bytes", _raise_write)
    monkeypatch.setattr(Path, "unlink", _raise_unlink)

    assert file_io.write_atomically(target, "content") is False


def test_legacy_read_wrappers_delegate_to_read_file_bytes(monkeypatch) -> None:
    calls: list[tuple[str, int | None, bool, bool]] = []

    def _fake_read(
        filepath: str,
        max_size_kb: int | None = None,
        normalize_encoding: bool = True,
        detect_binary: bool = False,
    ) -> bytes:
        calls.append((filepath, max_size_kb, normalize_encoding, detect_binary))
        return b"ok"

    monkeypatch.setattr(file_io, "read_file_bytes", _fake_read)

    assert file_io._read_file_bytes("a.py", max_size_kb=10) == b"ok"
    assert file_io._read_file_content("b.py", max_size_kb=20) == b"ok"
    assert calls == [
        ("a.py", 10, True, False),
        ("b.py", 20, True, True),
    ]
