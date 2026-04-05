"""
Memory usage monitoring utilities for large repository operations.

Provides functions to monitor memory usage and detect potential memory leaks.
"""

import gc
import os
import time
import psutil
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Dict, Any
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="memory_monitor")


@dataclass
class MemoryStats:
    """Memory usage statistics."""
    rss_mb: float  # Resident Set Size in MB
    vms_mb: float  # Virtual Memory Size in MB
    percent: float  # Memory usage percentage
    available_mb: float  # Available memory in MB
    gc_objects: int  # Number of objects tracked by garbage collector


class MemoryMonitor:
    """Monitor memory usage during operations."""
    
    def __init__(self, warning_threshold_mb: float = 500.0, critical_threshold_mb: float = 1000.0):
        """
        Initialize memory monitor.
        
        Args:
            warning_threshold_mb: Memory usage warning threshold in MB
            critical_threshold_mb: Memory usage critical threshold in MB
        """
        self.warning_threshold_mb = warning_threshold_mb
        self.critical_threshold_mb = critical_threshold_mb
        self.process = psutil.Process(os.getpid())
        self._cached_stats = None
        self._cache_timestamp = 0
        self._cache_ttl = 0.5  # Cache stats for 500ms to reduce overhead
        
    def get_memory_stats(self) -> MemoryStats:
        """
        Get current memory statistics.
        
        Returns:
            Current memory usage statistics
        """
        current_time = time.time()
        
        # Return cached stats if still valid
        if (self._cached_stats is not None and 
            current_time - self._cache_timestamp < self._cache_ttl):
            return self._cached_stats
        
        try:
            memory_info = self.process.memory_info()
            memory_percent = self.process.memory_percent()
            
            # Get system memory info
            system_memory = psutil.virtual_memory()
            
            # Get garbage collector stats (expensive operation)
            try:
                gc_stats = gc.get_stats()
                gc_objects = sum(stat.get('count', 0) for stat in gc_stats)
            except Exception:
                # Use efficient fallback - skip GC object counting if stats fail
                # gc.get_objects() is extremely expensive and can cause memory pressure
                # Instead, we'll estimate based on available information or skip counting
                try:
                    # Try to get a rough estimate without full object enumeration
                    gc_counts = [len(gc.get_objects(i)) for i in range(3)]  # Sample small generations
                    gc_objects = sum(gc_counts) if gc_counts else 0
                except Exception:
                    # Final fallback - use a reasonable estimate or 0
                    gc_objects = 0
                    logger.debug("gc_object_counting_skipped", reason="expensive_fallback_failed")
            
            stats = MemoryStats(
                rss_mb=memory_info.rss / 1024 / 1024,
                vms_mb=memory_info.vms / 1024 / 1024,
                percent=memory_percent,
                available_mb=system_memory.available / 1024 / 1024,
                gc_objects=gc_objects
            )
            
            # Cache the results
            self._cached_stats = stats
            self._cache_timestamp = current_time
            
            return stats
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.error("failed_to_get_memory_stats", error=str(e))
            return MemoryStats(0, 0, 0, 0, 0)
    
    def check_memory_usage(self, operation: str = "unknown") -> Optional[str]:
        """
        Check memory usage and return warning if threshold exceeded.
        
        Args:
            operation: Name of the operation being monitored
            
        Returns:
            Warning message if threshold exceeded, None otherwise
        """
        stats = self.get_memory_stats()
        
        if stats.rss_mb > self.critical_threshold_mb:
            message = (
                f"CRITICAL: Memory usage {stats.rss_mb:.1f}MB exceeds threshold "
                f"during {operation}. Consider reducing batch size or enabling streaming."
            )
            logger.error("memory_critical", operation=operation, usage_mb=stats.rss_mb)
            return message
        elif stats.rss_mb > self.warning_threshold_mb:
            message = (
                f"WARNING: Memory usage {stats.rss_mb:.1f}MB exceeds threshold "
                f"during {operation}. Monitor for potential memory leaks."
            )
            logger.warning("memory_warning", operation=operation, usage_mb=stats.rss_mb)
            return message
        
        return None
    
    def log_memory_stats(self, operation: str) -> None:
        """
        Log current memory statistics.
        
        Args:
            operation: Name of the operation
        """
        stats = self.get_memory_stats()
        logger.info(
            "memory_stats",
            operation=operation,
            rss_mb=f"{stats.rss_mb:.1f}",
            vms_mb=f"{stats.vms_mb:.1f}",
            percent=f"{stats.percent:.1f}",
            available_mb=f"{stats.available_mb:.1f}",
            gc_objects=stats.gc_objects
        )


@contextmanager
def memory_monitor(operation: str, warning_threshold_mb: float = 500.0, critical_threshold_mb: float = 1000.0):
    """
    Context manager for monitoring memory usage during an operation.
    
    Args:
        operation: Name of the operation being monitored
        warning_threshold_mb: Memory usage warning threshold in MB
        critical_threshold_mb: Memory usage critical threshold in MB
        
    Usage:
        with memory_monitor("indexing"):
            # Perform memory-intensive operation
            pass
    """
    monitor = MemoryMonitor(warning_threshold_mb, critical_threshold_mb)
    
    # Log initial memory state
    initial_stats = monitor.get_memory_stats()
    logger.info(
        "memory_monitor_start",
        operation=operation,
        initial_rss_mb=f"{initial_stats.rss_mb:.1f}",
        initial_gc_objects=initial_stats.gc_objects
    )
    
    try:
        # Check memory at start
        warning = monitor.check_memory_usage(f"{operation}_start")
        if warning:
            logger.warning("memory_monitor_start_warning", operation=operation, warning=warning)
        
        yield monitor
        
        # Log final memory state
        final_stats = monitor.get_memory_stats()
        memory_diff_mb = final_stats.rss_mb - initial_stats.rss_mb
        gc_diff = final_stats.gc_objects - initial_stats.gc_objects
        
        logger.info(
            "memory_monitor_end",
            operation=operation,
            final_rss_mb=f"{final_stats.rss_mb:.1f}",
            memory_diff_mb=f"{memory_diff_mb:+.1f}",
            final_gc_objects=final_stats.gc_objects,
            gc_diff=f"{gc_diff:+d}"
        )
        
        # Check memory at end
        warning = monitor.check_memory_usage(f"{operation}_end")
        if warning:
            logger.warning("memory_monitor_end_warning", operation=operation, warning=warning)
            
        # Suggest garbage collection if memory increased significantly
        if memory_diff_mb > 100:  # More than 100MB increase
            logger.info("suggest_gc", operation=operation, memory_increase_mb=memory_diff_mb)
            
    except Exception as e:
        logger.error("memory_monitor_error", operation=operation, error=str(e))
        raise


def force_garbage_collection() -> Dict[str, Any]:
    """
    Force garbage collection and return statistics.
    
    Returns:
        Dictionary with garbage collection statistics
    """
    # Get stats before GC
    before_stats = gc.get_stats()
    before_objects = sum(stat.get('count', 0) for stat in before_stats)
    
    # Force garbage collection
    collected = gc.collect()
    
    # Get stats after GC
    after_stats = gc.get_stats()
    after_objects = sum(stat.get('count', 0) for stat in after_stats)
    
    result = {
        "collected_objects": collected,
        "objects_before": before_objects,
        "objects_after": after_objects,
        "objects_freed": before_objects - after_objects,
        "collections_performed": 1
    }
    
    logger.info(
        "garbage_collection_completed",
        **result
    )
    
    return result


def get_system_memory_info() -> Dict[str, Any]:
    """
    Get system-wide memory information.
    
    Returns:
        Dictionary with system memory statistics
    """
    try:
        virtual_memory = psutil.virtual_memory()
        swap_memory = psutil.swap_memory()
        
        return {
            "total_mb": virtual_memory.total / 1024 / 1024,
            "available_mb": virtual_memory.available / 1024 / 1024,
            "used_mb": virtual_memory.used / 1024 / 1024,
            "percent": virtual_memory.percent,
            "swap_total_mb": swap_memory.total / 1024 / 1024,
            "swap_used_mb": swap_memory.used / 1024 / 1024,
            "swap_percent": swap_memory.percent
        }
    except Exception as e:
        logger.error("failed_to_get_system_memory", error=str(e))
        return {}


def check_memory_pressure(threshold_percent: float = 90.0) -> bool:
    """
    Check if system is under memory pressure.
    
    Args:
        threshold_percent: Memory usage percentage threshold
        
    Returns:
        True if system is under memory pressure, False otherwise
    """
    try:
        virtual_memory = psutil.virtual_memory()
        return virtual_memory.percent > threshold_percent
    except Exception as e:
        logger.error("failed_to_check_memory_pressure", error=str(e))
        return False
