from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Iterator

from batho.core.config import get_active_root

# Pre-compiled regex for removing parameter hash suffixes from symbol names
_PARAM_HASH_PATTERN = re.compile(r'_\[[a-fA-F0-9]+\]')


@dataclass
class SymbolInfo:
    """Information about a symbol in scope."""
    symbol_id: str
    symbol_type: str  # class, function, variable, etc.
    scope_path: str
    is_external: bool = False
    is_heuristic: bool = False


class ReadWriteLock:
    """
    A fair reader-writer lock that prevents starvation.
    Multiple readers can hold the lock simultaneously, but only one writer.
    Uses a FIFO queue to ensure fairness and prevent writer starvation.
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._readers_ok = threading.Condition(self._lock)
        self._writers_ok = threading.Condition(self._lock)
        self._readers = 0
        self._writers = 0
        self._waiting_readers = 0
        self._waiting_writers = 0
        self._write_turn = False  # True if writers have priority

    def acquire_read(self) -> None:
        with self._lock:
            self._waiting_readers += 1
            # Wait if there are active writers or if it's write turn and there are waiting writers
            while self._writers > 0 or (self._write_turn and self._waiting_writers > 0):
                self._readers_ok.wait()
            self._waiting_readers -= 1
            self._readers += 1

    def release_read(self) -> None:
        with self._lock:
            self._readers -= 1
            if self._readers == 0:
                # Give writers a turn if any are waiting
                if self._waiting_writers > 0:
                    self._write_turn = True
                self._writers_ok.notify_all()
                self._readers_ok.notify_all()

    def acquire_write(self) -> None:
        with self._lock:
            self._waiting_writers += 1
            # Wait for all readers to finish and current writer to release
            while self._readers > 0 or self._writers > 0:
                self._writers_ok.wait()
            self._waiting_writers -= 1
            self._writers = 1

    def release_write(self) -> None:
        with self._lock:
            self._writers = 0
            # Give readers a turn if any are waiting
            if self._waiting_readers > 0:
                self._write_turn = False
            self._readers_ok.notify_all()
            self._writers_ok.notify_all()

    @contextmanager
    def read_lock(self) -> Iterator[None]:
        self.acquire_read()
        try:
            yield
        finally:
            self.release_read()

    @contextmanager
    def write_lock(self) -> Iterator[None]:
        self.acquire_write()
        try:
            yield
        finally:
            self.release_write()





class ScopeManager:
    """
    Manages hierarchical scopes for symbol resolution.

    Supports nested scopes (module -> class -> function) and
    cross-file symbol resolution via a global symbol table.
    """

    def __init__(self) -> None:
        self._local_data = threading.local()

        # Partitioned locks and data stores
        self._global_lock = threading.RLock()
        self._locks: Dict[str, ReadWriteLock] = {}

        # Maps partition_key -> (name -> SymbolInfo)
        self._partitioned_global: Dict[str, Dict[str, SymbolInfo]] = {}
        self._partitioned_local: Dict[str, Dict[str, Dict[str, SymbolInfo]]] = {}

        # Sentinel cache for failed lookups (Eclipse JDT TheNotFoundType pattern).
        # Avoids repeated O(n) lookups for names known to be unresolvable.
        # Must be cleared via clear_failed_lookups() after registering new symbols.
        self._failed_lookups: Set[str] = set()
        self._failed_lock = threading.Lock()

    @property
    def _scope_stack(self) -> List[str]:
        if not hasattr(self._local_data, "stack"):
            self._local_data.stack = []
        return self._local_data.stack

    def _get_partition_key(self, name: str) -> str:
        """Partition symbol tables by package/namespace prefix to reduce lock contention."""
        # E.g. hierarchical ID prefix: 'batho pip my_app' -> partition 'my_app'
        if name.startswith("batho "):
            parts = name.split()
            if len(parts) >= 3:
                return parts[2]
        
        # Fallback: first component of dot-path or slash-path
        clean_name = name.replace("/", ".").replace("#", ".").replace("().", "")
        parts = clean_name.split(".")
        return parts[0] if parts else "default"

    def _get_partition_lock(self, partition: str) -> ReadWriteLock:
        with self._global_lock:
            if partition not in self._locks:
                self._locks[partition] = ReadWriteLock()
                self._partitioned_global[partition] = {}
                self._partitioned_local[partition] = {}
            return self._locks[partition]

    def push_scope(self, scope_name: str, scope_type: str) -> str:
        """Enter a new scope and return its full path."""
        # scope_stack is thread-local, no locks needed to manipulate the stack itself
        stack = self._scope_stack
        if stack:
            parent = stack[-1]
            scope_path = f"{parent}/{scope_name}"
        else:
            scope_path = scope_name

        stack.append(scope_path)
        
        # Initialize local scope map for the new path
        partition = self._get_partition_key(scope_path)
        lock = self._get_partition_lock(partition)
        with lock.write_lock():
            self._partitioned_local[partition].setdefault(scope_path, {})
            
        return scope_path

    def pop_scope(self) -> Optional[str]:
        """Exit current scope and return its path."""
        stack = self._scope_stack
        if not stack:
            return None
        return stack.pop()

    def get_current_scope(self) -> str:
        """Get current scope path, or empty string if no scope."""
        stack = self._scope_stack
        return stack[-1] if stack else ""

    def define_symbol(self, name: str, symbol_id: str, symbol_type: str, is_global: bool = False) -> None:
        """Define a symbol in the current scope or the global table."""
        current_scope = self.get_current_scope()
        symbol_info = SymbolInfo(
            symbol_id=symbol_id,
            symbol_type=symbol_type,
            scope_path=current_scope,
            is_external=False
        )

        clean_name = _PARAM_HASH_PATTERN.sub('', name)

        if is_global or not current_scope:
            partition = self._get_partition_key(name)
            lock = self._get_partition_lock(partition)
            with lock.write_lock():
                self._partitioned_global[partition][name] = symbol_info
            if clean_name != name:
                clean_partition = self._get_partition_key(clean_name)
                clean_lock = self._get_partition_lock(clean_partition)
                with clean_lock.write_lock():
                    self._partitioned_global[clean_partition][clean_name] = symbol_info
        else:
            partition = self._get_partition_key(current_scope)
            lock = self._get_partition_lock(partition)
            with lock.write_lock():
                self._partitioned_local[partition].setdefault(current_scope, {})[name] = symbol_info
                if clean_name != name:
                    self._partitioned_local[partition].setdefault(current_scope, {})[clean_name] = symbol_info

    def define_global_symbol_qualified(self, name: str, symbol_id: str, symbol_type: str, filepath: str, is_global: bool = False) -> None:
        """
        Define a symbol in the scope manager under its local name,
        as well as its qualified names relative to the package root.
        """
        # Always define the unqualified name
        self.define_symbol(name, symbol_id, symbol_type, is_global=is_global)
        
        # Calculate qualified names relative to the package root
        if is_global:
            root = get_active_root()
            module_parts = []
            if root:
                try:
                    rel_path = Path(filepath).relative_to(root)
                    module_parts = list(rel_path.with_suffix("").parts)
                except ValueError:
                    pass
            if not module_parts:
                stem = Path(filepath).stem
                if stem != "__init__":
                    module_parts = [stem]
                else:
                    module_parts = [Path(filepath).parent.name]
            
            if module_parts and module_parts[-1] == "__init__":
                module_parts.pop()
                
            module_parts = [p for p in module_parts if p]
            if module_parts:
                module_dot = ".".join(module_parts)
                module_slash = "/".join(module_parts)
                
                # Define qualified variants
                self.define_symbol(f"{module_dot}.{name}", symbol_id, symbol_type, is_global=is_global)
                self.define_symbol(f"{module_slash}/{name}", symbol_id, symbol_type, is_global=is_global)

    def add_external_symbol(self, name: str, symbol_id: str, symbol_type: str) -> None:
        """Add an external symbol (from another package) to global table."""
        symbol_info = SymbolInfo(
            symbol_id=symbol_id,
            symbol_type=symbol_type,
            scope_path="external",
            is_external=True
        )

        partition = self._get_partition_key(name)
        lock = self._get_partition_lock(partition)
        
        with lock.write_lock():
            self._partitioned_global[partition][name] = symbol_info

    def resolve_symbol(self, name: str) -> Optional[SymbolInfo]:
        """
        Resolve symbol by searching from the current scope stack outward, 
        then check the exact global partition matching the name.
        """
        stack = self._scope_stack
        
        # 1. Search local scopes (innermost first)
        for scope in reversed(stack):
            partition = self._get_partition_key(scope)
            lock = self._get_partition_lock(partition)
            with lock.read_lock():
                local_map = self._partitioned_local[partition].get(scope)
                if local_map and name in local_map:
                    return local_map[name]

        # 2. Search exact global partition matching the name
        primary_partition = self._get_partition_key(name)
        lock = self._get_partition_lock(primary_partition)
        with lock.read_lock():
            global_map = self._partitioned_global[primary_partition]
            if name in global_map:
                return global_map[name]

        return None

    def resolve_symbol_strict(self, name: str) -> Optional[SymbolInfo]:
        """
        Resolve symbol with exact match only, with sentinel caching.

        Uses a failed-lookup cache (Eclipse JDT's TheNotFoundType pattern) to
        avoid repeated O(n) lookups for names known to be unresolvable.
        Call clear_failed_lookups() after registering new symbols so that
        previously-failed lookups are retried.
        """
        # Fast path: check failed-lookup cache
        with self._failed_lock:
            if name in self._failed_lookups:
                return None

        result = self.resolve_symbol(name)

        # Cache failures
        if result is None:
            with self._failed_lock:
                self._failed_lookups.add(name)

        return result

    def clear_failed_lookups(self) -> None:
        """Clear the failed-lookup sentinel cache.

        Call this after registering new symbols (e.g., after
        _register_project_symbols or _materialize_external_symbols) so
        previously-failed lookups are retried against the new symbols.
        """
        with self._failed_lock:
            self._failed_lookups.clear()

    def resolve_symbol_dotpath(self, name: str) -> Optional[SymbolInfo]:
        """
        Resolve a dotted symbol by progressively checking:
        1. Exact match (existing resolve_symbol)
        2. Module prefix match: "json.dumps" → check if "json" is external, 
           then synthesize SymbolInfo for "json.dumps"
        """
        # 1. Exact match
        info = self.resolve_symbol(name)
        if info:
            return info
            
        # 2. Module prefix match (for external symbols)
        if "." in name:
            parts = name.split(".")
            for i in range(len(parts) - 1, 0, -1):
                prefix = ".".join(parts[:i])
                prefix_info = self.resolve_symbol(prefix)
                if prefix_info and prefix_info.is_external:
                    # Synthesize SymbolInfo for the sub-symbol
                    # We assume it exists if the parent module is external
                    return SymbolInfo(
                        symbol_id=f"{prefix_info.symbol_id}{'.'.join(parts[i:])}",
                        symbol_type="external",
                        scope_path=prefix_info.scope_path,
                        is_external=True
                    )
        
        return None

    @property
    def global_symbol_count(self) -> int:
        """Return the total number of global symbols across all partitions.
        
        Note: Under concurrent access, this count is an approximation
        as partition locks are acquired sequentially, not atomically.
        """
        with self._global_lock:
            partitions = list(self._partitioned_global.keys())
        total = 0
        for part in partitions:
            lock = self._get_partition_lock(part)
            with lock.read_lock():
                total += len(self._partitioned_global[part])
        return total

    def get_global_symbols(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Serialize global symbol partitions."""
        with self._global_lock:
            partitions = list(self._partitioned_global.keys())
            
        serialized = {}
        for part in partitions:
            lock = self._get_partition_lock(part)
            with lock.read_lock():
                serialized[part] = {
                    name: {
                        "symbol_id": info.symbol_id,
                        "symbol_type": info.symbol_type,
                        "scope_path": info.scope_path,
                        "is_external": info.is_external,
                        "is_heuristic": info.is_heuristic
                    }
                    for name, info in self._partitioned_global[part].items()
                }
        return serialized

    def load_global_symbols(self, data: dict[str, dict[str, dict[str, Any]]]) -> None:
        """Load global symbol partitions from serialized data."""
        with self._global_lock:
            for part, symbols_map in data.items():
                lock = self._get_partition_lock(part)
                with lock.write_lock():
                    self._partitioned_global[part] = {
                        name: SymbolInfo(
                            symbol_id=info["symbol_id"],
                            symbol_type=info["symbol_type"],
                            scope_path=info["scope_path"],
                            is_external=info.get("is_external", False),
                            is_heuristic=info.get("is_heuristic", False)
                        )
                        for name, info in symbols_map.items()
                    }

