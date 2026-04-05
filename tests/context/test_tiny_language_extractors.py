from __future__ import annotations

import importlib
import inspect

import pytest

from batho_core.context.extractor import ASTExtractor


TINY_LANGUAGE_MODULES = [
    "bash",
    "c",
    "cpp",
    "csharp",
    "dart",
    "erlang",
    "go",
    "hack",
    "haskell",
    "java",
    "javascript",
    "julia",
    "kotlin",
    "lua",
    "ocaml",
    "perl",
    "php",
    "ruby",
    "rust",
    "scala",
    "swift",
    "verilog",
    "zig",
]


@pytest.mark.parametrize("module_name", TINY_LANGUAGE_MODULES)
def test_tiny_extractors_initialize_and_return_query(
    module_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Avoid parser initialization overhead; this test validates module glue code.
    monkeypatch.setattr(ASTExtractor, "__init__", lambda self, *_args, **_kwargs: None)

    module = importlib.import_module(f"batho_core.context.languages.{module_name}")
    extractor_classes = [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if obj.__module__ == module.__name__
        and obj is not ASTExtractor
        and issubclass(obj, ASTExtractor)
        and obj.__name__.endswith("Extractor")
    ]

    assert extractor_classes, f"No extractor class found for {module_name}"

    extractor = extractor_classes[0]()
    query = extractor._query_source()

    assert isinstance(query, str)
    assert query.strip()
