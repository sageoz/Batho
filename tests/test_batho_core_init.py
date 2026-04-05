from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def test_batho_init_success_reexport_branch(tmp_path: Path) -> None:
    module_path = Path(__file__).resolve().parents[1] / "batho" / "__init__.py"

    fake_root = ModuleType("fakepkg")
    fake_root.__path__ = []  # mark as package

    fake_batho_cli = ModuleType("fakepkg.batho_cli")
    fake_batho_cli.CodeGraphIndexer = lambda: None
    fake_batho_cli.QueryService = lambda: None

    sys.modules["fakepkg"] = fake_root
    sys.modules["fakepkg.batho_cli"] = fake_batho_cli

    try:
        spec = importlib.util.spec_from_file_location(
            "fakepkg.batho",
            module_path,
            submodule_search_locations=[str(tmp_path)],
        )
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        sys.modules["fakepkg.batho"] = module
        spec.loader.exec_module(module)

        # Check that the module exports the expected public APIs
        assert "CodeGraphIndexer" in module.__all__
        assert "QueryService" in module.__all__
    finally:
        sys.modules.pop("fakepkg.batho", None)
        sys.modules.pop("fakepkg.batho_cli", None)
        sys.modules.pop("fakepkg", None)
