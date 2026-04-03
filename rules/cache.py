"""
Rule caching mechanism for C4 rule system.

Provides in-memory and persistent caching to improve rule loading performance.
"""

from __future__ import annotations

import json
import time
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from batho_core.utils.logging import get_logger

logger = get_logger(__name__, component="rule_cache")


class RuleCache:
    """Cache for loaded rules with TTL and file change detection."""
    
    def __init__(self, cache_dir: Optional[Path] = None, default_ttl: int = 3600):
        """
        Initialize rule cache.
        
        Args:
            cache_dir: Directory for persistent cache. If None, uses in-memory only.
            default_ttl: Default time-to-live in seconds (default: 1 hour).
        """
        self.default_ttl = default_ttl
        self.cache_dir = cache_dir
        self._memory_cache: Dict[str, Tuple[Any, float, str]] = {}  # key -> (value, expiry, file_hash)
        self._persistent_cache: Dict[str, Any] = {}
        
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_persistent_cache()
    
    def get(self, key: str, file_path: Optional[Path] = None) -> Optional[Any]:
        """
        Get cached value.
        
        Args:
            key: Cache key.
            file_path: Path to rule file for change detection.
            
        Returns:
            Cached value or None if not found/expired.
        """
        # Check memory cache first
        if key in self._memory_cache:
            value, expiry, file_hash = self._memory_cache[key]
            
            # Check expiry
            if time.time() > expiry:
                logger.debug("Cache entry expired", key=key)
                del self._memory_cache[key]
                return None
            
            # Check file changes if file path provided
            if file_path and file_path.exists():
                current_hash = self._get_file_hash(file_path)
                if current_hash != file_hash:
                    logger.debug("File changed, invalidating cache", key=key, file=str(file_path))
                    del self._memory_cache[key]
                    return None
            
            logger.debug("Cache hit (memory)", key=key)
            return value
        
        # Check persistent cache
        if key in self._persistent_cache:
            cached_data = self._persistent_cache[key]
            
            # Check expiry
            if time.time() > cached_data.get('expiry', 0):
                logger.debug("Persistent cache expired", key=key)
                del self._persistent_cache[key]
                return None
            
            # Check file changes
            if file_path and file_path.exists():
                current_hash = self._get_file_hash(file_path)
                if current_hash != cached_data.get('file_hash', ''):
                    logger.debug("File changed, invalidating persistent cache", key=key)
                    del self._persistent_cache[key]
                    return None
            
            logger.debug("Cache hit (persistent)", key=key)
            return cached_data['value']
        
        logger.debug("Cache miss", key=key)
        return None
    
    def set(self, key: str, value: Any, file_path: Optional[Path] = None, ttl: Optional[int] = None) -> None:
        """
        Set cached value.
        
        Args:
            key: Cache key.
            value: Value to cache.
            file_path: Path to rule file for change detection.
            ttl: Time-to-live in seconds. Uses default if None.
        """
        expiry = time.time() + (ttl or self.default_ttl)
        file_hash = self._get_file_hash(file_path) if file_path else ""
        
        # Store in memory cache
        self._memory_cache[key] = (value, expiry, file_hash)
        
        # Store in persistent cache if enabled
        if self.cache_dir:
            self._persistent_cache[key] = {
                'value': value,
                'expiry': expiry,
                'file_hash': file_hash,
                'cached_at': time.time()
            }
            self._save_persistent_cache()
        
        logger.debug("Cached value", key=key, ttl=ttl or self.default_ttl)
    
    def invalidate(self, key: str) -> None:
        """Invalidate a specific cache entry."""
        self._memory_cache.pop(key, None)
        self._persistent_cache.pop(key, None)
        logger.debug("Invalidated cache entry", key=key)
    
    def invalidate_all(self) -> None:
        """Invalidate all cache entries."""
        self._memory_cache.clear()
        self._persistent_cache.clear()
        if self.cache_dir:
            cache_file = self.cache_dir / "rule_cache.json"
            if cache_file.exists():
                cache_file.unlink()
        logger.debug("Invalidated all cache entries")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        memory_entries = len(self._memory_cache)
        persistent_entries = len(self._persistent_cache)
        
        # Calculate hit ratio (simplified)
        total_entries = memory_entries + persistent_entries
        
        return {
            "memory_entries": memory_entries,
            "persistent_entries": persistent_entries,
            "total_entries": total_entries,
            "cache_dir": str(self.cache_dir) if self.cache_dir else None,
            "default_ttl": self.default_ttl
        }
    
    def cleanup_expired(self) -> int:
        """Remove expired entries from cache."""
        current_time = time.time()
        removed = 0
        
        # Clean memory cache
        expired_keys = [
            key for key, (_, expiry, _) in self._memory_cache.items()
            if current_time > expiry
        ]
        for key in expired_keys:
            del self._memory_cache[key]
            removed += 1
        
        # Clean persistent cache
        expired_keys = [
            key for key, data in self._persistent_cache.items()
            if current_time > data.get('expiry', 0)
        ]
        for key in expired_keys:
            del self._persistent_cache[key]
            removed += 1
        
        if removed > 0 and self.cache_dir:
            self._save_persistent_cache()
        
        logger.debug("Cleaned up expired entries", count=removed)
        return removed
    
    def _get_file_hash(self, file_path: Optional[Path]) -> str:
        """Get SHA256 hash of file contents."""
        if not file_path or not file_path.exists():
            return ""
        
        try:
            with open(file_path, 'rb') as f:
                return sha256(f.read()).hexdigest()
        except Exception as e:
            logger.warning("Failed to hash file", file=str(file_path), error=str(e))
            return ""
    
    def _load_persistent_cache(self) -> None:
        """Load persistent cache from disk."""
        if not self.cache_dir:
            return
        
        cache_file = self.cache_dir / "rule_cache.json"
        if not cache_file.exists():
            return
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._persistent_cache = data.get('cache', {})
            logger.debug("Loaded persistent cache", entries=len(self._persistent_cache))
        except Exception as e:
            logger.warning("Failed to load persistent cache", error=str(e))
            self._persistent_cache = {}
    
    def _save_persistent_cache(self) -> None:
        """Save persistent cache to disk."""
        if not self.cache_dir:
            return
        
        cache_file = self.cache_dir / "rule_cache.json"
        try:
            data = {
                'version': '1.0',
                'cache': self._persistent_cache,
                'saved_at': time.time()
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, sort_keys=True)
        except Exception as e:
            logger.warning("Failed to save persistent cache", error=str(e))
