"""
Deterministic hashing of LSP responses for auditability.
"""

import hashlib
import json
from typing import Any, Dict


class LSPResponseHasher:
    """
    Computes deterministic SHA256 hashes of raw LSP responses.
    This provides the cryptographic proof of what the LSP returned,
    vital for the enterprise audit trail.
    """

    @staticmethod
    def hash_response(raw_response: str | bytes | Dict[str, Any]) -> str:
        """
        Compute SHA256 hash of an LSP response.
        
        If raw_response is a dictionary, it will be canonically serialized
        to JSON (keys sorted, no whitespace) before hashing.
        
        Args:
            raw_response: The response data to hash
            
        Returns:
            Hex string of the SHA256 hash
        """
        if isinstance(raw_response, dict):
            # Canonical JSON serialization for objects
            data = json.dumps(raw_response, sort_keys=True, separators=(',', ':')).encode('utf-8')
        elif isinstance(raw_response, str):
            data = raw_response.encode('utf-8')
        else:
            data = raw_response
            
        hasher = hashlib.sha256()
        hasher.update(data)
        return hasher.hexdigest()

    @staticmethod
    def hash_request(method: str, params: Dict[str, Any], lsp_version: str) -> str:
        """
        Compute deterministic hash for a request.
        
        Used primarily for content-addressed caching of responses.
        Includes the LSP version to ensure cache invalidation across upgrades.
        
        Args:
            method: JSON-RPC method name
            params: Request parameters
            lsp_version: Version string of the LSP binary
            
        Returns:
            Hex string of the SHA256 hash
        """
        request_obj = {
            "method": method,
            "params": params,
            "lsp_version": lsp_version
        }
        
        data = json.dumps(request_obj, sort_keys=True, separators=(',', ':')).encode('utf-8')
        hasher = hashlib.sha256()
        hasher.update(data)
        return hasher.hexdigest()

    @staticmethod
    def hash_batch(response_hashes: list[str]) -> str:
        """
        Compute a combined hash for a batch of responses.
        
        Args:
            response_hashes: List of individual response hashes
            
        Returns:
            Hex string of the combined SHA256 hash
        """
        hasher = hashlib.sha256()
        for h in sorted(response_hashes):
            hasher.update(h.encode('utf-8'))
        return hasher.hexdigest()
