from __future__ import annotations
import os
import logging
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

class PopularPackagesDB:
    """
    Loader for the bundled 'popular packages DB' — a pre-curated YAML file
    covering the top third-party packages across 5 ecosystems.
    
    Uses set-based lookup for O(1) performance and caches package name sets.
    """

    _instance: PopularPackagesDB | None = None
    _data: Dict[str, Any] = {}
    _package_sets: Dict[str, Set[str]] = {}

    def __new__(cls, db_path: Path | None = None):
        # Singleton pattern to avoid reloading YAML
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Path | None = None):
        if self._initialized:
            return

        if db_path is None:
            db_env = os.environ.get("BATHO_POPULAR_PACKAGES_PATH")
            if db_env:
                db_path = Path(db_env)
            else:
                base_dir = Path(__file__).parent.parent.parent
                db_path = base_dir / "core" / "batho_data" / "popular-packages.yaml"

        self.db_path = db_path
        self._load()
        self._build_package_sets()
        self._initialized = True

    def _load(self):
        if self.db_path and self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self._data = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"Failed to load popular packages DB: {e}")
                self._data = {}

    def _build_package_sets(self):
        """Build O(1) lookup sets for each language."""
        languages = self._data.get("languages", {})
        for lang, config in languages.items():
            packages = config.get("packages", [])
            self._package_sets[lang.lower()] = {
                p.get("name") for p in packages if p.get("name")
            }

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
        Uses O(1) set lookup for performance.
        """
        if full_scan:
            return True

        # O(1) lookup instead of O(N) linear search
        package_set = self._package_sets.get(language.lower())
        if package_set is None:
            return False

        return package_name in package_set

    def get_symbol_indexing_strategy(self, language: str) -> str:
        """Get the symbol indexing strategy for a language."""
        lang_cfg = self.get_language_config(language)
        if not lang_cfg:
            return "bundled_tables_only"

        strategy = lang_cfg.get("symbol_indexing")
        if isinstance(strategy, dict):
            return strategy.get("default_strategy", "bundled_tables_only")
        return strategy or "bundled_tables_only"
