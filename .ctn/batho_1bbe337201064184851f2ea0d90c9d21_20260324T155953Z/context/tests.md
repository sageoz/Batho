## Summary
- Total tests files: 115
- Total entities: 8141

📁 tests/ (Testing Suite)
  📄 conftest.py (1 entities: 1 function)
  📄 test_flask_fixture.py (4 entities: 4 function)
  📄 test_time_machine.py (19 entities: 5 class, 14 method)

📁 tests/cli/
  📄 test_cli_commands.py (14 entities: 4 class, 10 method)
  📄 test_cli_integration.py (6 entities: 1 class, 5 method)
  📄 test_cli_parser.py (14 entities: 1 class, 13 method)

📁 tests/context/
  📄 test_codegraph.py (43 entities: 6 class, 37 method)
  📄 test_css_extractor.py (20 entities: 1 class, 2 function, 17 method)
  📄 test_factory.py (32 entities: 8 class, 24 method)
  📄 test_hcl_extractor.py (19 entities: 1 class, 2 function, 16 method)
  📄 test_html_extractor.py (14 entities: 1 class, 13 method)
  📄 test_language_detector_comprehensive.py (23 entities: 1 class, 22 method)
  📄 test_languages.py (22 entities: 4 class, 18 method)
  📄 test_markdown_extractor.py (16 entities: 1 class, 15 method)
  📄 test_repomap.py (27 entities: 7 class, 20 method)
  📄 test_stack_detector.py (33 entities: 6 class, 27 method)
  📄 test_yaml_extractor.py (21 entities: 2 class, 2 function, 17 method)

📁 tests/core/
  📄 test_config.py (33 entities: 6 class, 27 method)
  📄 test_extractor.py (20 entities: 4 class, 16 method)
  📄 test_schema.py (23 entities: 4 class, 19 method)

📁 tests/integration/
  📄 test_cross_platform.py (13 entities: 1 class, 12 method)
  📄 test_error_handling.py (14 entities: 1 class, 1 function, 12 method)
  📄 test_workflows.py (8 entities: 1 class, 7 method)

📁 tests/performance/
  📄 test_performance.py (15 entities: 1 class, 6 function, 8 method)

📁 tests/testdata/
  📄 PHASE1_COMPLETION_SUMMARY.md (88 entities: 1 document, 87 element)
  📄 PHASES1_5_COMPLETION_SUMMARY.md (116 entities: 1 document, 115 element)

📁 tests/testdata/files/
  📄 README.md (6 entities: 1 document, 5 element)

📁 tests/testdata/files/config/ (Configuration)
  📄 sample_config.json (64 entities: 1 document, 17 section, 46 setting)
  📄 sample_config.toml (66 entities: 1 document, 19 section, 46 setting)
  📄 sample_config.yaml (64 entities: 1 document, 17 section, 46 setting)

📁 tests/testdata/files/cpp/
  📄 sample_cpp.cpp (27 entities: 3 class, 13 function, 8 method, 3 namespace)

📁 tests/testdata/files/css/
  📄 advanced.css (21 entities: 1 document, 6 element, 14 setting)
  📄 basic.css (13 entities: 1 document, 3 element, 9 setting)
  📄 complex_selectors.css (30 entities: 1 document, 12 element, 17 setting)
  📄 scss_style.scss (13 entities: 1 document, 6 element, 6 setting)

📁 tests/testdata/files/go/
  📄 sample_go.go (10 entities: 3 function, 1 interface, 4 method, 2 struct)

📁 tests/testdata/files/hcl/
  📄 basic.tf (5 entities: 1 document, 4 section)
  📄 complex.tf (11 entities: 1 document, 10 section)

📁 tests/testdata/files/java/
  📄 SampleClass.java (28 entities: 2 class, 6 field, 20 method)

📁 tests/testdata/files/javascript/
  📄 sample_es6.js (13 entities: 2 class, 5 function, 6 method)

📁 tests/testdata/files/markup/
  📄 sample_html.html (166 entities: 60 attribute, 1 document, 105 element)
  📄 sample_markdown.md (55 entities: 1 document, 54 element)

📁 tests/testdata/files/python/
  📄 sample_functions.py (9 entities: 1 class, 6 function, 2 method)

📁 tests/testdata/files/rust/
  📄 sample_rust.rs (21 entities: 2 enum, 9 function, 7 method, 2 struct, 1 trait)

📁 tests/testdata/files/yaml/
  📄 basic.yaml (18 entities: 1 document, 4 section, 13 setting)
  📄 complex.yaml (58 entities: 1 document, 21 section, 36 setting)

📁 tests/testdata/fixtures/
  📄 README.md (6 entities: 1 document, 5 element)

📁 tests/testdata/outputs/
  📄 PHASE7_COMPLETION_SUMMARY.md (69 entities: 1 document, 68 element)
  📄 README.md (6 entities: 1 document, 5 element)

📁 tests/testdata/outputs/api_responses/
  📄 error_response.json (11 entities: 1 document, 3 section, 7 setting)
  📄 index_success.json (22 entities: 1 document, 5 section, 16 setting)
  📄 stats_response.json (34 entities: 1 document, 9 section, 24 setting)

📁 tests/testdata/outputs/configs/ (Configuration)
  📄 default_config.json (17 entities: 1 document, 5 section, 11 setting)

📁 tests/testdata/outputs/configs/custom_configs/
  📄 language_specific_config.yaml (17 entities: 1 document, 5 section, 11 setting)
  📄 large_repository_config.json (17 entities: 1 document, 5 section, 11 setting)
  📄 performance_tuning_config.toml (17 entities: 1 document, 5 section, 11 setting)

📁 tests/testdata/outputs/configs/env_override_configs/
  📄 override_example.json (29 entities: 1 document, 6 section, 22 setting)

📁 tests/testdata/outputs/configs/invalid_configs/
  📄 missing_fields.json (7 entities: 1 document, 4 section, 2 setting)
  📄 schema_violation.json (17 entities: 1 document, 5 section, 11 setting)
  📄 type_errors.json (20 entities: 1 document, 8 section, 11 setting)

📁 tests/testdata/outputs/graphs/
  📄 multi_language_graph.json (1089 entities: 1 document, 184 section, 904 setting)
  📄 simple_python_graph.json (454 entities: 1 document, 78 section, 375 setting)

📁 tests/testdata/outputs/repomaps/
  📄 flask_sample_repomap.json (3520 entities: 1 document, 1073 section, 2446 setting)
  📄 multi_language_repomap.json (236 entities: 1 document, 81 section, 154 setting)
  📄 simple_python_repomap.json (113 entities: 1 document, 37 section, 75 setting)

📁 tests/testdata/outputs/webhooks/
  📄 github_pr_merged.json (59 entities: 1 document, 11 section, 47 setting)
  📄 github_pr_opened.json (54 entities: 1 document, 10 section, 43 setting)
  📄 github_push_main.json (62 entities: 1 document, 18 section, 43 setting)
  📄 invalid_missing_fields.json (10 entities: 1 document, 3 section, 6 setting)
  📄 invalid_wrong_format.json (33 entities: 1 document, 12 section, 20 setting)

📁 tests/testdata/repositories/edge_cases/
  📄 latin1_file.py (1 entities: 1 function)

📁 tests/testdata/repositories/edge_cases/deep/nested/path/to/
  📄 file.py (1 entities: 1 function)

📁 tests/testdata/repositories/flask/
  📄 .pre-commit-config.yaml (56 entities: 1 document, 26 section, 29 setting)
  📄 .readthedocs.yaml (17 entities: 1 document, 8 section, 8 setting)
  📄 CODE_OF_CONDUCT.md (18 entities: 1 document, 17 element)
  📄 metadata.py (4 entities: 2 entry_point, 2 function)
  📄 pyproject.toml (105 entities: 1 document, 35 section, 69 setting)
  📄 repository_metadata.json (152 entities: 1 document, 8 section, 143 setting)

📁 tests/testdata/repositories/flask/.devcontainer/
  📄 devcontainer.json (13 entities: 1 document, 5 section, 7 setting)

📁 tests/testdata/repositories/flask/docs/ (Documentation)
  📄 conf.py (2 entities: 2 function)

📁 tests/testdata/repositories/flask/src/flask/
  📄 __init__.py (1 entities: 1 function)
  📄 app.py (49 entities: 1 class, 4 function, 44 method)
  📄 blueprints.py (16 entities: 2 class, 8 function, 6 method)
  📄 cli.py (37 entities: 6 class, 2 entry_point, 16 function, 13 method)
  📄 config.py (14 entities: 2 class, 12 method)
  📄 ctx.py (30 entities: 3 class, 5 function, 22 method)
  📄 debughelpers.py (11 entities: 4 class, 3 function, 4 method)
  📄 globals.py (3 entities: 1 class, 1 function, 1 method)
  📄 helpers.py (21 entities: 1 class, 16 function, 4 method)
  📄 logging.py (2 entities: 2 function)
  📄 scaffold.py (17 entities: 1 class, 9 function, 7 method)
  📄 sessions.py (26 entities: 5 class, 1 function, 20 method)
  📄 signals.py (1 entities: 1 function)
  📄 templating.py (17 entities: 2 class, 8 function, 7 method)
  📄 testing.py (14 entities: 3 class, 1 function, 10 method)
  📄 views.py (5 entities: 2 class, 3 method)
  📄 wrappers.py (4 entities: 2 class, 2 method)

📁 tests/testdata/repositories/flask/src/flask/json/
  📄 __init__.py (5 entities: 5 function)
  📄 provider.py (13 entities: 2 class, 1 function, 10 method)
  📄 tag.py (43 entities: 10 class, 33 method)

📁 tests/testdata/repositories/multi_language/backend/
  📄 app.py (3 entities: 1 class, 2 function)
  📄 models.py (7 entities: 3 class, 4 method)

📁 tests/testdata/repositories/multi_language/frontend/
  📄 package.json (11 entities: 1 document, 3 section, 7 setting)
  📄 tsconfig.json (10 entities: 1 document, 3 section, 6 setting)

📁 tests/testdata/repositories/multi_language/frontend/src/ (Source Code)
  📄 App.tsx (2 entities: 1 function, 1 interface)
  📄 utils.ts (2 entities: 2 function)

📁 tests/testdata/repositories/simple_python/
  📄 README.md (2 entities: 1 document, 1 element)

📁 tests/testdata/repositories/simple_python/src/ (Source Code)
  📄 calculator.py (8 entities: 1 class, 4 function, 3 method)
  📄 utils.py (2 entities: 2 function)

📁 tests/testdata/repositories/simple_python/tests/ (Testing Suite)
  📄 test_calculator.py (3 entities: 3 function)

📁 tests/utils/ (Utilities)
  📄 test_dependencies.py (39 entities: 7 class, 32 method)
  📄 test_encoding.py (16 entities: 3 class, 13 method)
  📄 test_hash.py (26 entities: 5 class, 21 method)
  📄 test_ignore.py (26 entities: 5 class, 21 method)
  📄 test_logging.py (11 entities: 3 class, 8 method)
