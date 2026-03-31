"""Authentication utilities for webhook verification."""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional


def verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature.
    
    Args:
        payload: Raw request body
        signature: Value from X-Hub-Signature-256 header
        secret: Webhook secret key
        
    Returns:
        True if signature is valid
    """
    if not signature.startswith("sha256="):
        return False
    
    # Compute expected signature
    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    # Compare signatures securely
    expected_sig = f"sha256={expected}"
    return hmac.compare_digest(signature, expected_sig)


def verify_gitlab_token(token: str, secret: str) -> bool:
    """Verify GitLab webhook token.
    
    Args:
        token: Value from X-Gitlab-Token header
        secret: Webhook secret key
        
    Returns:
        True if token matches
    """
    return hmac.compare_digest(token, secret)
