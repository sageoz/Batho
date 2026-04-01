"""
Tests for LSPResponseCache.
"""

import pytest
import shutil
from pathlib import Path

from batho_core.context.lsp.cache import LSPResponseCache
from batho_core.context.lsp.types import LSPResponse


@pytest.fixture
def cache_dir(tmp_path):
    d = tmp_path / "lsp_cache"
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_compute_hash(cache_dir):
    cache = LSPResponseCache(cache_dir)
    h = cache.compute_request_hash("textDocument/definition", {"a": 1}, "1.0.0")
    assert len(h) == 64  # SHA256 hex


@pytest.mark.asyncio
async def test_set_and_get(cache_dir):
    cache = LSPResponseCache(cache_dir)
    req_hash = cache.compute_request_hash("test", {}, "1.0")
    
    resp = LSPResponse(
        raw_json='{"result": "ok"}',
        hash='testhash',
        duration_ms=10
    )
    
    await cache.set(req_hash, resp)
    
    cached = await cache.get(req_hash)
    assert cached is not None
    assert cached.hash == 'testhash'
    assert cached.duration_ms == 10
    assert cached.raw_json == '{"result": "ok"}'


@pytest.mark.asyncio
async def test_get_missing(cache_dir):
    cache = LSPResponseCache(cache_dir)
    cached = await cache.get("nonexistent_hash")
    assert cached is None
