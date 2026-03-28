# 📊 batho - Repository Overview

*Generated: 2026-03-24T15:59:53.190406+00:00*

## Repository Summary

| Metric | Value |
|--------|-------|
| Total Files | 181 |
| Total Entities | 9529 |
| Total Relationships | 84 |

## File Distribution

- **SOURCE**: 53 files (29.3%) | 369 entities
- **TESTS**: 115 files (63.5%) | 8141 entities
- **DOCS**: 10 files (5.5%) | 903 entities
- **CONFIG**: 3 files (1.7%) | 116 entities
- **UNCATEGORIZED**: 0 files (0.0%) | 0 entities

## Language Breakdown

| Language | Files | Percentage |
|----------|-------|------------|
| Python | 112 | 61.9% |
| JSON | 24 | 13.3% |
| MD | 19 | 10.5% |
| YAML | 6 | 3.3% |
| TOML | 5 | 2.8% |
| CSS | 3 | 1.7% |
| TF | 2 | 1.1% |
| YML | 1 | 0.6% |
| C++ | 1 | 0.6% |
| SCSS | 1 | 0.6% |
| Go | 1 | 0.6% |
| Java | 1 | 0.6% |
| JavaScript | 1 | 0.6% |
| HTML | 1 | 0.6% |
| Rust | 1 | 0.6% |
| TypeScript (React) | 1 | 0.6% |
| TypeScript | 1 | 0.6% |

**Primary Language**: Python

## Technology Stack

## Directory Structure

📁 root/
  📄 Brownfield-Core-Engine-PDD.docx.md
  📄 README.md
  📄 batho.py
  📄 pyproject.toml
  📄 rulebased-c4-generation-plan.md
  ... and 3 more
  📁 batho_core/
    📄 config.py
    📄 pyproject.toml
    📄 time_machine.py
      📁 workflows/
    📁 context/
      📄 categorizer.py
      📄 codegraph.py
      📄 extractor.py
      📄 repomap.py
      📄 schema.py
      ... and 1 more
      📁 languages/
    📁 utils/ (Utilities)
      📄 dependencies.py
      📄 encoding.py
      📄 hash.py
      📄 ignore.py
      📄 logging.py
  📁 docs/ (Documentation)
    📄 architecture-diagrams.md
    📄 batho-kt.md
    📄 cleanup.md
    📄 sageoz-core-scope-validation.md
    📄 v1-feature-checklist.md
    ... and 1 more
  📁 tests/ (Testing Suite)
    📄 conftest.py
    📄 test_flask_fixture.py
    📄 test_time_machine.py
    📁 cli/
      📄 test_cli_commands.py
      📄 test_cli_integration.py
      📄 test_cli_parser.py
    📁 context/
      📄 test_codegraph.py
      📄 test_css_extractor.py
      📄 test_factory.py
      📄 test_hcl_extractor.py
      📄 test_html_extractor.py
      ... and 6 more
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
| setting | 4821 |
| section | 1793 |
| element | 1380 |
| method | 883 |
| function | 295 |
| class | 207 |
| document | 62 |
| attribute | 60 |
| entry_point | 10 |
| field | 6 |
| struct | 4 |
| namespace | 3 |
| interface | 2 |
| enum | 2 |
| trait | 1 |

## Top Dependencies

| Dependency | References |
|------------|------------|
| pathlib | 6 |
| tests/testdata/repositories/flask/repository_metadata.json | 5 |
| tests/testdata/repositories/flask/.readthedocs.yaml | 4 |
| warnings | 4 |
| sys | 3 |
| typing | 3 |
| re | 3 |
| argparse | 2 |
| batho_core.context.codegraph | 2 |
| batho_core.context.languages.registry | 2 |
