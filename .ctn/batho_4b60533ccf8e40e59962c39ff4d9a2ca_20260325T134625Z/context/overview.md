# 📊 batho - Repository Overview

*Generated: 2026-03-25T13:46:25.940646+00:00*

## Repository Summary

| Metric | Value |
|--------|-------|
| Total Files | 185 |
| Total Entities | 9781 |
| Total Relationships | 85 |

## File Distribution

- **SOURCE**: 57 files (30.8%) | 509 entities
- **TESTS**: 116 files (62.7%) | 8157 entities
- **DOCS**: 9 files (4.9%) | 917 entities
- **CONFIG**: 3 files (1.6%) | 198 entities
- **UNCATEGORIZED**: 0 files (0.0%) | 0 entities

## Language Breakdown

| Language | Files | Percentage |
|----------|-------|------------|
| Python | 117 | 63.2% |
| JSON | 24 | 13.0% |
| MD | 18 | 9.7% |
| YAML | 6 | 3.2% |
| TOML | 5 | 2.7% |
| CSS | 3 | 1.6% |
| TF | 2 | 1.1% |
| YML | 1 | 0.5% |
| C++ | 1 | 0.5% |
| SCSS | 1 | 0.5% |
| Go | 1 | 0.5% |
| Java | 1 | 0.5% |
| JavaScript | 1 | 0.5% |
| HTML | 1 | 0.5% |
| Rust | 1 | 0.5% |
| TypeScript (React) | 1 | 0.5% |
| TypeScript | 1 | 0.5% |

**Primary Language**: Python

## Technology Stack

## Directory Structure

📁 root/
  📄 README.md
  📄 batho.py
  📄 pyproject.toml
  📄 test.py
  📁 batho_core/
    📄 config.py
    📄 pyproject.toml
    📄 time_machine.py
      📁 workflows/
    📁 context/
      📄 c4_generator.py
      📄 c4_llm_extensions.py
      📄 c4_rules.py
      📄 c4_structurizr.py
      📄 categorizer.py
      ... and 5 more
      📁 languages/
    📁 utils/ (Utilities)
      📄 dependencies.py
      📄 encoding.py
      📄 file_io.py
      📄 hash.py
      📄 ignore.py
      ... and 1 more
  📁 docs/ (Documentation)
    📄 Brownfield-Core-Engine-PDD.docx.md
    📄 architecture-diagrams.md
    📄 batho-kt.md
    📄 cleanup.md
    📄 sageoz-core-scope-validation.md
    ... and 3 more
  📁 tests/ (Testing Suite)
    📄 conftest.py
    📄 test_flask_fixture.py
    📄 test_time_machine.py
    📁 cli/
      📄 test_cli_commands.py
      📄 test_cli_integration.py
      📄 test_cli_parser.py
    📁 context/
      📄 test_c4_generator.py
      📄 test_codegraph.py
      📄 test_css_extractor.py
      📄 test_factory.py
      📄 test_hcl_extractor.py
      ... and 7 more
    📁 core/
      📄 test_config.py
      📄 test_extractor.py
      📄 test_schema.py
    📁 integration/
      📄 test_cross_platform.py
      📄 test_error_handling.py
      📄 test_workflows.py
    📁 performance/
      📄 test_performance.py
    📁 testdata/
      📄 PHASE1_COMPLETION_SUMMARY.md
      📄 PHASES1_5_COMPLETION_SUMMARY.md
      📁 files/
      📁 fixtures/
      📁 outputs/
    📁 utils/ (Utilities)
      📄 test_dependencies.py
      📄 test_encoding.py
      📄 test_hash.py
      📄 test_ignore.py
      📄 test_logging.py

## Entity Statistics

| Entity Type | Count |
|-------------|-------|
| setting | 4875 |
| section | 1821 |
| element | 1395 |
| method | 1031 |
| function | 296 |
| class | 216 |
| document | 61 |
| attribute | 60 |
| entry_point | 8 |
| field | 6 |
| struct | 4 |
| namespace | 3 |
| interface | 2 |
| enum | 2 |
| trait | 1 |

## Top Dependencies

| Dependency | References |
|------------|------------|
| pathlib | 5 |
| tests/testdata/repositories/flask/repository_metadata.json | 4 |
| warnings | 4 |
| sys | 3 |
| tests/testdata/repositories/flask/.readthedocs.yaml | 3 |
| batho_core.context.codegraph | 2 |
| batho_core.context.languages.registry | 2 |
| datetime | 2 |
| time | 2 |
| traceback | 2 |
