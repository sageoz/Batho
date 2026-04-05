from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def test_batho_core_init_success_reexport_branch(tmp_path: Path) -> None:
    module_path = Path(__file__).resolve().parents[1] / "batho_core" / "__init__.py"

    fake_root = ModuleType("fakepkg")
    fake_root.__path__ = []  # mark as package

    fake_batho = ModuleType("fakepkg.batho")
    fake_batho.build_parser = lambda: None
    fake_batho.main = lambda: None

    sys.modules["fakepkg"] = fake_root
    sys.modules["fakepkg.batho"] = fake_batho

    try:
        spec = importlib.util.spec_from_file_location(
            "fakepkg.batho_core",
            module_path,
            submodule_search_locations=[str(tmp_path)],
        )
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        sys.modules["fakepkg.batho_core"] = module
        spec.loader.exec_module(module)

        assert module.__all__ == ["build_parser", "main"]
    finally:
        sys.modules.pop("fakepkg.batho_core", None)
        sys.modules.pop("fakepkg.batho", None)
        sys.modules.pop("fakepkg", None)
