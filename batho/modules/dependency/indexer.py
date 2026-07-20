from __future__ import annotations
import time
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from batho.modules.extraction.scope_manager import ScopeManager
from batho.core.schemas import PackageManager
from .manifest_parser import ManifestParser, DependencySpec
from .stdlib_tables import StdlibSymbolTable
from .popular_packages import PopularPackagesDB
from .introspector import ThirdPartyIntrospector
from .resolution_cache import ResolutionCache

logger = logging.getLogger(__name__)

@dataclass
class DependencyIndexStats:
    manifests_found: int = 0
    deps_declared: int = 0
    deps_cached: int = 0
    deps_introspected: int = 0
    symbols_indexed: int = 0
    stdlib_modules_indexed: int = 0
    duration_ms: float = 0.0
    errors: List[str] = field(default_factory=list)

class DependencyIndexer:
    """
    Orchestrates the full dependency indexing pipeline and populates the ScopeManager.
    """
    
    def __init__(
        self,
        root: Path,
        scope_manager: ScopeManager,
        cfg: Dict[str, Any],
        cache_dir: str | None = None,
    ) -> None:
        self.root = Path(root)
        self.scope_manager = scope_manager
        self.cfg = cfg
        self.stats = DependencyIndexStats()

        # Initialize components
        self.parser = ManifestParser()
        self.stdlib = StdlibSymbolTable()
        self.popular_db = PopularPackagesDB(
            db_path=Path(cfg.get("introspection", {}).get("popular_packages_db_path"))
            if cfg.get("introspection", {}).get("popular_packages_db_path") else None
        )
        self.introspector = ThirdPartyIntrospector(
            mode=cfg.get("introspection", {}).get("mode", "shallow"),
            timeout_seconds=cfg.get("introspection", {}).get("timeout_seconds", 5)
        )

        cache_path = root / cache_dir if cache_dir else root / ".batho" / "cache"
        self.cache = ResolutionCache(cache_path)

    def run(self) -> DependencyIndexStats:
        t0 = time.monotonic()
        
        try:
            # Detect and cache project metadata
            ManifestParser.detect_project_metadata(self.root, self.cache)
            
            # 1. Parse manifests
            manifests = self.parser.parse_manifests(self.root)
            self.stats.manifests_found = len(set(d.source_file for d in manifests))
            self.stats.deps_declared = len(manifests)
            
            # 2. Index Standard Libraries
            self._index_stdlib()
            
            # 3. Index Third-party Dependencies (parallelized)
            self._index_dependencies_parallel(manifests)
                
        except Exception as e:
            logger.exception("Dependency indexing failed")
            self.stats.errors.append(f"{type(e).__name__}: {e}")
            
        self.stats.duration_ms = (time.monotonic() - t0) * 1000
        return self.stats

    def _index_stdlib(self):
        """Index standard library modules for enabled languages."""
        enabled_langs = self.cfg.get("stdlib", {}).get("languages", ["python", "javascript", "go", "rust"])
        if not self.cfg.get("stdlib", {}).get("enabled", True):
            return

        # Batch add symbols to minimize lock contention
        symbols_to_add: List[tuple[str, str, str]] = []
        registered_modules: Set[str] = set()

        for lang in enabled_langs:
            modules = self.stdlib.get_all_modules(lang)
            for mod_name, symbols in modules.items():
                self.stats.stdlib_modules_indexed += 1
                
                # Register module once per language
                module_key = f"{lang}:{mod_name}"
                if module_key not in registered_modules:
                    registered_modules.add(module_key)
                    symbols_to_add.append((
                        mod_name,
                        f"batho stdlib {lang} {lang} {mod_name}/",
                        "module"
                    ))
                
                for sym in symbols:
                    qualified_name = f"{mod_name}.{sym}"
                    
                    # Language-specific symbol ID format
                    if lang == "python":
                        symbol_id = f"batho pip python 3.x {mod_name}/{sym}()."
                    elif lang == "javascript":
                        symbol_id = f"batho npm nodejs 20.x {mod_name}/{sym}#"
                    else:
                        symbol_id = f"batho stdlib {lang} {lang} {mod_name}/{sym}."
                        
                    symbols_to_add.append((qualified_name, symbol_id, "function"))
                    self.stats.symbols_indexed += 1

        # Batch add all symbols at once
        for name, symbol_id, sym_type in symbols_to_add:
            self.scope_manager.add_external_symbol(
                name=name,
                symbol_id=symbol_id,
                symbol_type=sym_type
            )

    def _index_dependencies_parallel(self, manifests: List[DependencySpec]) -> None:
        """Index dependencies in parallel using thread pool."""
        if not manifests:
            return

        # Filter to unique deps that need introspection
        unique_deps: Dict[str, DependencySpec] = {}
        for dep in manifests:
            key = f"{dep.manager.value}:{dep.name}:{dep.version_spec}"
            if key not in unique_deps:
                unique_deps[key] = dep

        deps_to_introspect = []
        full_scan = self.cfg.get("introspection", {}).get("full_scan", False)
        
        for dep in unique_deps.values():
            # Check cache first
            cached = self.cache.get_symbols(dep.name, dep.version_spec, dep.manager.value)
            if cached:
                self.stats.deps_cached += 1
                self._add_symbols_to_scope(dep, cached)
                continue
            
            # Check if we should introspect
            if self.popular_db.should_introspect(dep.language, dep.name, full_scan):
                deps_to_introspect.append(dep)

        if not deps_to_introspect:
            return

        # Introspect in parallel (I/O bound - safe to use threads)
        max_workers = min(4, len(deps_to_introspect))
        venv_path = self._find_venv()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._introspect_dep, dep, venv_path): dep 
                for dep in deps_to_introspect
            }
            
            for future in as_completed(futures):
                dep = futures[future]
                try:
                    symbols_map = future.result()
                    if symbols_map:
                        self.stats.deps_introspected += 1
                        self.cache.put_symbols(dep.name, dep.version_spec, dep.manager.value, symbols_map)
                        self._add_symbols_to_scope(dep, symbols_map)
                except Exception as e:
                    logger.warning(f"Failed to introspect {dep.name}: {e}")

    def _find_venv(self) -> Path | None:
        """Find virtual environment path."""
        venv_paths = [
            self.root / ".venv",
            self.root / "venv",
            self.root / "env",
        ]
        for venv_path in venv_paths:
            if venv_path.exists():
                return venv_path
        return None

    def _introspect_dep(self, dep: DependencySpec, venv_path: Path | None) -> Dict[str, List[str]]:
        """Introspect a single dependency."""
        if dep.language == "python" and self.cfg.get("introspection", {}).get("enabled", True):
            return self.introspector.introspect_python(dep.name, venv_path)
        return {}

    def _add_symbols_to_scope(self, dep: DependencySpec, symbols_map: Dict[str, List[str]]):
        """Add symbols from a package to the scope manager (batched for performance)."""
        symbols_to_add: List[tuple[str, str, str]] = []
        registered_modules: Set[str] = set()
        suffix = "()." if dep.language == "python" else "#"
        
        for mod_path, symbols in symbols_map.items():
            # Register module once
            if mod_path not in registered_modules:
                registered_modules.add(mod_path)
                symbols_to_add.append((
                    mod_path,
                    f"batho {dep.manager.value} {dep.name} {dep.version_spec} {mod_path}/",
                    "module"
                ))
            
            for sym in symbols:
                qualified_name = f"{mod_path}.{sym}"
                symbol_id = f"batho {dep.manager.value} {dep.name} {dep.version_spec} {mod_path}/{sym}{suffix}"
                symbols_to_add.append((qualified_name, symbol_id, "external"))
                self.stats.symbols_indexed += 1

        # Batch add all symbols
        for name, symbol_id, sym_type in symbols_to_add:
            self.scope_manager.add_external_symbol(
                name=name,
                symbol_id=symbol_id,
                symbol_type=sym_type
            )

def build_dependency_index(
    root: Path,
    scope_manager: ScopeManager,
    cfg: Dict[str, Any],
    cache_dir: str | None = None,
) -> DependencyIndexStats:
    """Convenience function — the primary integration point for build/patch."""
    return DependencyIndexer(root, scope_manager, cfg, cache_dir=cache_dir).run()
