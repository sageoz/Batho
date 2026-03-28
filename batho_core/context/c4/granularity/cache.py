"""
Caching system for granularity decisions and metrics.
"""

import hashlib
import json
import time
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict

from batho_core.utils.logging import get_logger
from .analyzer import RepositoryMetrics
from .engine import GranularityDecision

logger = get_logger(__name__, component="granularity_cache")


@dataclass
class CacheEntry:
    """Cache entry with value and metadata."""
    value: Any
    timestamp: float
    ttl: float  # Time to live in seconds
    hash: str
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return time.time() - self.timestamp > self.ttl


class GranularityCache:
    """Cache for granularity decisions and metrics."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.logger = get_logger(self.__class__.__name__, component="granularity_cache")
        self.cache_dir = cache_dir or Path.home() / ".batho" / "cache" / "granularity"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache for faster access
        self._memory_cache: Dict[str, CacheEntry] = {}
        
        # Default TTL values (seconds)
        self.default_ttls = {
            "metrics": 3600,      # 1 hour
            "decision": 7200,     # 2 hours
            "grouping": 1800,     # 30 minutes
            "filtering": 1800     # 30 minutes
        }
    
    def _generate_key(self, data: Dict[str, Any], prefix: str) -> str:
        """Generate cache key from data."""
        # Create deterministic hash of the data
        data_str = json.dumps(data, sort_keys=True)
        hash_obj = hashlib.sha256(data_str.encode())
        return f"{prefix}:{hash_obj.hexdigest()[:16]}"
    
    def _get_cache_file(self, key: str) -> Path:
        """Get cache file path for key."""
        return self.cache_dir / f"{key.replace(':', '_')}.json"
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        # Check memory cache first
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if entry.is_expired():
                del self._memory_cache[key]
                self.logger.debug("Memory cache entry expired", key=key)
            else:
                self.logger.debug("Cache hit (memory)", key=key)
                return entry.value
        
        # Check file cache
        cache_file = self._get_cache_file(key)
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                
                entry = CacheEntry(**data)
                
                if entry.is_expired():
                    cache_file.unlink()
                    self.logger.debug("File cache entry expired", key=key)
                else:
                    # Store in memory cache
                    self._memory_cache[key] = entry
                    self.logger.debug("Cache hit (file)", key=key)
                    return entry.value
                    
            except Exception as e:
                self.logger.warning("Failed to read cache file", file=str(cache_file), error=str(e))
                # Remove corrupted cache file
                try:
                    cache_file.unlink()
                except:
                    pass
        
        return None
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        persist: bool = True
    ) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
            persist: Whether to persist to disk
        """
        # Determine TTL
        if ttl is None:
            # Extract prefix to get default TTL
            prefix = key.split(":")[0]
            ttl = self.default_ttls.get(prefix, 3600)
        
        # Create cache entry
        entry = CacheEntry(
            value=value,
            timestamp=time.time(),
            ttl=ttl,
            hash=key
        )
        
        # Store in memory cache
        self._memory_cache[key] = entry
        
        # Persist to disk if requested
        if persist:
            try:
                cache_file = self._get_cache_file(key)
                
                # Convert to serializable format
                serializable_value = self._make_serializable(value)
                entry_dict = asdict(entry)
                entry_dict["value"] = serializable_value
                
                with open(cache_file, 'w') as f:
                    json.dump(entry_dict, f, indent=2)
                
                self.logger.debug("Cache stored", key=key, file=str(cache_file))
                
            except Exception as e:
                self.logger.warning("Failed to write cache file", file=str(cache_file), error=str(e))
    
    def _make_serializable(self, value: Any) -> Any:
        """Convert value to JSON-serializable format."""
        if hasattr(value, 'to_dict'):
            return value.to_dict()
        elif hasattr(value, '__dict__'):
            return value.__dict__
        elif isinstance(value, (list, tuple)):
            return [self._make_serializable(v) for v in value]
        elif isinstance(value, dict):
            return {k: self._make_serializable(v) for k, v in value.items()}
        else:
            return value
    
    def invalidate(self, pattern: Optional[str] = None) -> None:
        """
        Invalidate cache entries.
        
        Args:
            pattern: Pattern to match (e.g., "metrics:"), None for all
        """
        # Invalidate memory cache
        keys_to_remove = []
        for key in self._memory_cache:
            if pattern is None or key.startswith(pattern):
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self._memory_cache[key]
        
        # Invalidate file cache
        for cache_file in self.cache_dir.glob("*.json"):
            if pattern is None or cache_file.stem.replace('_', ':').startswith(pattern):
                try:
                    cache_file.unlink()
                    self.logger.debug("Invalidated cache file", file=str(cache_file))
                except Exception as e:
                    self.logger.warning("Failed to delete cache file", file=str(cache_file), error=str(e))
        
        self.logger.info("Cache invalidated", pattern=pattern or "all")
    
    def get_metrics(
        self,
        graph_hash: str,
        repomap_hash: str
    ) -> Optional[RepositoryMetrics]:
        """
        Get cached repository metrics.
        
        Args:
            graph_hash: Hash of graph data
            repomap_hash: Hash of repomap data
            
        Returns:
            Cached metrics or None
        """
        key = self._generate_key({
            "graph": graph_hash,
            "repomap": repomap_hash
        }, "metrics")
        
        value = self.get(key)
        if value:
            try:
                return RepositoryMetrics(**value)
            except Exception as e:
                self.logger.warning("Failed to deserialize metrics", error=str(e))
        
        return None
    
    def set_metrics(
        self,
        graph_hash: str,
        repomap_hash: str,
        metrics: RepositoryMetrics
    ) -> None:
        """
        Cache repository metrics.
        
        Args:
            graph_hash: Hash of graph data
            repomap_hash: Hash of repomap data
            metrics: Repository metrics to cache
        """
        key = self._generate_key({
            "graph": graph_hash,
            "repomap": repomap_hash
        }, "metrics")
        
        self.set(key, metrics.to_dict())
    
    def get_decision(
        self,
        metrics_hash: str,
        override: Optional[str] = None
    ) -> Optional[GranularityDecision]:
        """
        Get cached granularity decision.
        
        Args:
            metrics_hash: Hash of metrics data
            override: Override parameter used
            
        Returns:
            Cached decision or None
        """
        key_data = {"metrics": metrics_hash}
        if override:
            key_data["override"] = override
        
        key = self._generate_key(key_data, "decision")
        
        value = self.get(key)
        if value:
            try:
                # Reconstruct GranularityDecision
                from .engine import GranularityLevel
                return GranularityDecision(
                    level=GranularityLevel(value["level"]),
                    reasoning=value["reasoning"],
                    confidence=value["confidence"],
                    settings=value["settings"]
                )
            except Exception as e:
                self.logger.warning("Failed to deserialize decision", error=str(e))
        
        return None
    
    def set_decision(
        self,
        metrics_hash: str,
        decision: GranularityDecision,
        override: Optional[str] = None
    ) -> None:
        """
        Cache granularity decision.
        
        Args:
            metrics_hash: Hash of metrics data
            decision: Granularity decision to cache
            override: Override parameter used
        """
        key_data = {"metrics": metrics_hash}
        if override:
            key_data["override"] = override
        
        key = self._generate_key(key_data, "decision")
        self.set(key, decision.to_dict())
    
    def cleanup(self) -> None:
        """Clean up expired cache entries."""
        current_time = time.time()
        
        # Clean memory cache
        expired_keys = []
        for key, entry in self._memory_cache.items():
            if entry.is_expired():
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._memory_cache[key]
        
        # Clean file cache
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                
                timestamp = data.get("timestamp", 0)
                ttl = data.get("ttl", 3600)
                
                if current_time - timestamp > ttl:
                    cache_file.unlink()
                    self.logger.debug("Cleaned up expired cache file", file=str(cache_file))
                    
            except Exception as e:
                # Remove corrupted files
                try:
                    cache_file.unlink()
                except:
                    pass
        
        self.logger.info("Cache cleanup complete")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        # Count entries by type
        type_counts = defaultdict(int)
        for key in self._memory_cache:
            prefix = key.split(":")[0]
            type_counts[prefix] += 1
        
        # Count file cache entries
        file_count = len(list(self.cache_dir.glob("*.json")))
        
        # Calculate total size
        total_size = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                total_size += cache_file.stat().st_size
            except:
                pass
        
        return {
            "memory_entries": len(self._memory_cache),
            "file_entries": file_count,
            "type_breakdown": dict(type_counts),
            "total_size_bytes": total_size,
            "cache_directory": str(self.cache_dir)
        }
