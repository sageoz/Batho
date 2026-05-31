from __future__ import annotations
import time
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from batho.modules.extraction.scope_manager import ScopeManager
from batho.core.schemas import PackageManager
from .manifest_parser import ManifestParser, DependencySpec
from .stdlib_tables import StdlibSymbolTable
from .popular_packages import PopularPackagesDB
from .introspector import ThirdPartyIntrospector
from .resolution_cache import ResolutionCache

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

        cache_dir = cache_dir
        cache_path = root / cache_dir
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
            
            # 3. Index Third-party Dependencies
            for dep in manifests:
                self._index_dependency(dep)
                
        except Exception as e:
            self.stats.errors.append(str(e))
            
        self.stats.duration_ms = (time.monotonic() - t0) * 1000
        return self.stats

    def _index_stdlib(self):
        """Index standard library modules for enabled languages."""
        enabled_langs = self.cfg.get("stdlib", {}).get("languages", ["python", "javascript", "go", "rust"])
        if not self.cfg.get("stdlib", {}).get("enabled", True):
            return

        for lang in enabled_langs:
            modules = self.stdlib.get_all_modules(lang)
            for mod_name, symbols in modules.items():
                self.stats.stdlib_modules_indexed += 1
                for sym in symbols:
                    # Synthetic ID for stdlib
                    # batho <manager> <name> <version> <path>
                    # For stdlib, we use 'stdlib' as manager and version
                    qualified_name = f"{mod_name}.{sym}"
                    symbol_id = f"batho stdlib {lang} {lang} {mod_name}/{sym}."
                    if lang == "python":
                        symbol_id = f"batho pip python 3.x {mod_name}/{sym}()."
                    elif lang == "javascript":
                        symbol_id = f"batho npm nodejs 20.x {mod_name}/{sym}#"
                        
                    self.scope_manager.add_external_symbol(
                        name=qualified_name,
                        symbol_id=symbol_id,
                        symbol_type="function" # default
                    )
                    # Register the module itself to enable dot-path resolution
                    if not self.scope_manager.resolve_symbol_strict(mod_name):
                        self.scope_manager.add_external_symbol(
                            name=mod_name,
                            symbol_id=f"batho stdlib {lang} {lang} {mod_name}/",
                            symbol_type="module"
                        )
                    self.stats.symbols_indexed += 1

    def _index_dependency(self, dep: DependencySpec):
        """Index a single third-party dependency."""
        # Check cache first
        cached_symbols = self.cache.get_symbols(dep.name, dep.version_spec, dep.manager.value)
        if cached_symbols:
            self.stats.deps_cached += 1
            self._add_symbols_to_scope(dep, cached_symbols)
            return

        # Check if we should introspect
        full_scan = self.cfg.get("introspection", {}).get("full_scan", False)
        if not self.popular_db.should_introspect(dep.language, dep.name, full_scan):
            return

        # Introspect
        symbols_map = {}
        if dep.language == "python" and self.cfg.get("introspection", {}).get("enabled", True):
            # Try to find venv
            venv_path = self.root / ".venv"
            if not venv_path.exists(): venv_path = None
            
            symbols_map = self.introspector.introspect_python(dep.name, venv_path)
            if symbols_map:
                self.stats.deps_introspected += 1
                self.cache.put_symbols(dep.name, dep.version_spec, dep.manager.value, symbols_map)
                self._add_symbols_to_scope(dep, symbols_map)
        
        # Placeholder for other languages introspection

    def _add_symbols_to_scope(self, dep: DependencySpec, symbols_map: Dict[str, List[str]]):
        """Add symbols from a package to the scope manager."""
        for mod_path, symbols in symbols_map.items():
            for sym in symbols:
                qualified_name = f"{mod_path}.{sym}"
                
                # Synthetic ID format (SCIP-compatible):
                # batho pip requests 2.31.0 requests/Session().
                # batho npm express 4.18.2 express/Router#
                
                suffix = "()." if dep.language == "python" else "#"
                symbol_id = f"batho {dep.manager.value} {dep.name} {dep.version_spec} {mod_path}/{sym}{suffix}"
                
                self.scope_manager.add_external_symbol(
                    name=qualified_name,
                    symbol_id=symbol_id,
                    symbol_type="external"
                )
                # Register the module itself to enable dot-path resolution
                if not self.scope_manager.resolve_symbol_strict(mod_path):
                    self.scope_manager.add_external_symbol(
                        name=mod_path,
                        symbol_id=f"batho {dep.manager.value} {dep.name} {dep.version_spec} {mod_path}/",
                        symbol_type="module"
                    )
                self.stats.symbols_indexed += 1

def build_dependency_index(
    root: Path,
    scope_manager: ScopeManager,
    cfg: Dict[str, Any],
    cache_dir: str | None = None,
) -> DependencyIndexStats:
    """Convenience function — the primary integration point for build/patch."""
    return DependencyIndexer(root, scope_manager, cfg, cache_dir=cache_dir).run()
