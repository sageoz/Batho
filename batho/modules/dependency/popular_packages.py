from __future__ import annotations
import os
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

class PopularPackagesDB:
    """
    Loader for the bundled 'popular packages DB' — a pre-curated YAML file
    covering the top third-party packages across 5 ecosystems.
    """
    
    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            # Resolve from environment or package data
            db_env = os.environ.get("BATHO_POPULAR_PACKAGES_PATH")
            if db_env:
                db_path = Path(db_env)
            else:
                # Assuming this file is in batho/modules/dependency/
                # and the data is in batho/core/batho_data/
                # Structure: /path/to/batho-v1.1.0/batho/modules/dependency/popular_packages.py
                # Data: /path/to/batho-v1.1.0/batho/core/batho_data/popular-packages.yaml
                base_dir = Path(__file__).parent.parent.parent
                db_path = base_dir / "core" / "batho_data" / "popular-packages.yaml"
        
        self.db_path = db_path
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self):
        if self.db_path and self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self._data = yaml.safe_load(f) or {}
            except Exception:
                self._data = {}

    def get_language_config(self, language: str) -> Dict[str, Any] | None:
        """Get configuration for a specific language."""
        return self._data.get("languages", {}).get(language.lower())

    def get_packages(self, language: str, limit: int | None = None) -> List[Dict[str, Any]]:
        """Get the list of popular packages for a language."""
        lang_cfg = self.get_language_config(language)
        if not lang_cfg:
            return []
        
        pkgs = lang_cfg.get("packages", [])
        if limit is not None:
            return pkgs[:limit]
        return pkgs

    def should_introspect(self, language: str, package_name: str, full_scan: bool) -> bool:
        """
        Check if a package should be introspected.
        If full_scan is true, all packages are introspected.
        Otherwise, only popular packages are introspected.
        """
        if full_scan:
            return True
        
        pkgs = self.get_packages(language)
        return any(p.get("name") == package_name for p in pkgs)

    def get_symbol_indexing_strategy(self, language: str) -> str:
        """Get the symbol indexing strategy for a language."""
        lang_cfg = self.get_language_config(language)
        if not lang_cfg:
            return "bundled_tables_only"
        
        strategy = lang_cfg.get("symbol_indexing")
        if isinstance(strategy, dict):
            return strategy.get("default_strategy", "bundled_tables_only")
        return strategy or "bundled_tables_only"
