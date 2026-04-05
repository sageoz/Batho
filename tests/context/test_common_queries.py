from __future__ import annotations

from batho.context.languages._common import (
    CallPatterns,
    CommonQueries,
    ImportPatterns,
    ProgrammingLanguageExtractor,
)


def test_common_queries_have_expected_markers() -> None:
    http_query = CommonQueries.http_server_entry_points()
    react_query = CommonQueries.react_render_entry_points()
    class_extends = CommonQueries.class_with_extends()
    class_impl = CommonQueries.class_with_implements()
    method_query = CommonQueries.method_with_params_return()
    function_query = CommonQueries.function_with_params_return()

    assert "listen" in http_query
    assert "ReactDOM" in react_query
    assert "class_declaration" in class_extends
    assert "implements_clause" in class_impl
    assert "method_definition" in method_query
    assert "function_declaration" in function_query


def test_programming_language_extractor_combine_queries() -> None:
    combined = ProgrammingLanguageExtractor.combine_queries("  one  ", "", " two ")
    assert combined == "one\n\ntwo"


def test_import_and_call_patterns_have_expected_captures() -> None:
    assert "@ref.import.module" in ImportPatterns.string_import()
    assert "dotted_name" in ImportPatterns.dotted_name_import()
    assert "namespace_use_clause" in ImportPatterns.qualified_name_import()
    assert "@ref.call" in CallPatterns.direct_call()


def test_common_queries_default_basics_are_empty() -> None:
    assert CommonQueries.basic_imports() == ""
    assert CommonQueries.basic_calls() == ""
