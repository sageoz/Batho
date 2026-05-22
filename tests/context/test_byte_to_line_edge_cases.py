"""
Test byte to line number calculation edge cases.
"""

import pytest


def test_byte_to_line_offset_zero():
    """Test that offset 0 returns line 1."""
    content = b"line1\nline2\nline3"
    offset = 0
    expected_line = 1
    actual_line = content[:offset].count(b"\n") + 1 if offset <= len(content) else content[:len(content)].count(b"\n") + 1
    assert actual_line == expected_line, f"Offset 0 should return line 1, got {actual_line}"


def test_byte_to_line_at_file_size():
    """Test that offset == file_size returns the last line number, not 1."""
    content = b"line1\nline2\nline3"
    offset = len(content)  # 17 bytes
    expected_line = 3  # 3 lines
    actual_line = content[:offset].count(b"\n") + 1 if offset <= len(content) else content[:len(content)].count(b"\n") + 1
    assert actual_line == expected_line, f"Offset at file_size should return last line (3), got {actual_line}"


def test_byte_to_line_beyond_file_size():
    """Test that offset > file_size is clamped to file size."""
    content = b"line1\nline2\nline3"
    offset = len(content) + 100
    expected_line = 3  # Should be clamped to file size, so last line
    actual_line = content[:offset].count(b"\n") + 1 if offset <= len(content) else content[:len(content)].count(b"\n") + 1
    assert actual_line == expected_line, f"Offset beyond file_size should be clamped to last line (3), got {actual_line}"


def test_byte_to_line_middle_of_file():
    """Test offset in the middle of the file."""
    content = b"line1\nline2\nline3"
    offset = 8  # In the middle of "line2"
    expected_line = 2
    actual_line = content[:offset].count(b"\n") + 1 if offset <= len(content) else content[:len(content)].count(b"\n") + 1
    assert actual_line == expected_line, f"Offset in middle should return line 2, got {actual_line}"


def test_byte_to_line_single_line():
    """Test single line file."""
    content = b"single line"
    offset = 5
    expected_line = 1
    actual_line = content[:offset].count(b"\n") + 1 if offset <= len(content) else content[:len(content)].count(b"\n") + 1
    assert actual_line == expected_line, f"Single line file should always return line 1, got {actual_line}"


def test_byte_to_line_empty_content():
    """Test empty content."""
    content = b""
    offset = 0
    expected_line = 1
    actual_line = content[:offset].count(b"\n") + 1 if offset <= len(content) else content[:len(content)].count(b"\n") + 1
    assert actual_line == expected_line, f"Empty content should return line 1, got {actual_line}"
