"""
Content-addressed caching for LSP responses.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from batho_core.utils.logging import get_logger
from batho_core.utils.file_lock import FileLock
from .types import LSPResponse
from .hasher import LSPResponseHasher


class LSPResponseCache:
    """
    Content-addressed cache for LSP responses.
    
    Ensures identical inputs produce cached outputs,
    supporting deterministic behavior and avoiding
    re-running heavy LSP resolutions for unchanged files.
    """

    def __init__(self, cache_dir: str | Path | None = None):
        self.logger = get_logger(__name__, component="lsp_cache")
        if cache_dir is None:
            self.cache_dir = Path(".ctn/lsp_cache")
        else:
            self.cache_dir = Path(cache_dir)
            
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hasher = LSPResponseHasher()

    def compute_request_hash(self, method: str, params: Dict[str, Any], lsp_version: str) -> str:
        """Compute content hash for request."""
        return self.hasher.hash_request(method, params, lsp_version)

    def _get_cache_path(self, request_hash: str) -> Path:
        """Get file path for a specific cached request hash."""
        # Use first two chars for subdirectory to avoid too many files in one dir
        subdir = self.cache_dir / request_hash[:2]
        subdir.mkdir(exist_ok=True)
        return subdir / f"{request_hash[2:]}.json"

    async def get(self, request_hash: str) -> Optional[LSPResponse]:
        """
        Retrieve cached response by request hash.
        
        Returns None if not found or corrupted.
        """
        path = self._get_cache_path(request_hash)
        if not path.exists():
            return None
            
        lock = FileLock(path.with_suffix('.lock'))
        
        try:
            with lock:
                # Read content
                content = path.read_text(encoding='utf-8')
                data = json.loads(content)
                
                # We could deserialize into specific response types, but in Phase 1
                # we just return the generic LSPResponse. The serializers will be built out later.
                # For now, reconstruct from dict
                
                # Just mock return for now, since we haven't implemented robust
                # Pydantic generic deserialization based on 'method'
                
                self.logger.debug("lsp_cache_hit", hash=request_hash[:8])
                return LSPResponse.model_validate(data)
                
        except Exception as e:
            self.logger.warning("lsp_cache_read_failed", hash=request_hash[:8], error=str(e))
            return None

    async def set(self, request_hash: str, response: LSPResponse, ttl_seconds: Optional[int] = None) -> None:
        """
        Cache an LSP response.
        """
        path = self._get_cache_path(request_hash)
        lock = FileLock(path.with_suffix('.lock'))
        
        try:
            with lock:
                # Need to use model_dump_json for Pydantic v2
                content = response.model_dump_json()
                path.write_text(content, encoding='utf-8')
                self.logger.debug("lsp_cache_store", hash=request_hash[:8])
                
        except Exception as e:
            self.logger.warning("lsp_cache_write_failed", hash=request_hash[:8], error=str(e))
