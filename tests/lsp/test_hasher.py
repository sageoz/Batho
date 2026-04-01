"""
Tests for LSPResponseHasher.
"""

from batho_core.context.lsp.hasher import LSPResponseHasher


def test_hash_response_string():
    hasher = LSPResponseHasher()
    h1 = hasher.hash_response("hello")
    h2 = hasher.hash_response("hello")
    h3 = hasher.hash_response("world")
    
    assert h1 == h2
    assert h1 != h3


def test_hash_response_dict_canonical():
    hasher = LSPResponseHasher()
    
    dict1 = {"a": 1, "b": {"c": 2, "d": [1, 2, 3]}}
    dict2 = {"b": {"d": [1, 2, 3], "c": 2}, "a": 1}
    
    h1 = hasher.hash_response(dict1)
    h2 = hasher.hash_response(dict2)
    
    # Must be identical regardless of key insertion order
    assert h1 == h2


def test_hash_request():
    hasher = LSPResponseHasher()
    h1 = hasher.hash_request("textDocument/definition", {"position": {"line": 1, "character": 2}}, "1.0.0")
    h2 = hasher.hash_request("textDocument/definition", {"position": {"character": 2, "line": 1}}, "1.0.0")
    h3 = hasher.hash_request("textDocument/definition", {"position": {"line": 1, "character": 2}}, "2.0.0")
    
    assert h1 == h2
    assert h1 != h3


def test_hash_batch():
    hasher = LSPResponseHasher()
    h1 = hasher.hash_batch(["abc", "def", "ghi"])
    h2 = hasher.hash_batch(["def", "ghi", "abc"])
    
    assert h1 == h2
