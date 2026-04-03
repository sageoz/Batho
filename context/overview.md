# 📊 batho - Repository Overview

*Generated: 2026-04-03T18:21:53.075616+00:00*

## Repository Summary

| Metric | Value |
|--------|-------|
| Total Files | 193 |
| Total Entities | 9849 |
| Total Relationships | 95 |

## File Distribution

- **Source**: 66 files (34.2%) | 558 entities
- **Tests**: 33 files (17.1%) | 656 entities
- **Docs**: 7 files (3.6%) | 831 entities
- **Config**: 6 files (3.1%) | 434 entities
- **.devcontainer**: 1 files (0.5%) | 13 entities
- **Api_responses**: 3 files (1.6%) | 67 entities
- **Backend**: 2 files (1.0%) | 10 entities
- **Configs**: 1 files (0.5%) | 17 entities
- **Cpp**: 1 files (0.5%) | 27 entities
- **Css**: 4 files (2.1%) | 77 entities
- **Custom_configs**: 3 files (1.6%) | 51 entities
- **Edge_cases**: 1 files (0.5%) | 1 entities
- **Env_override_configs**: 1 files (0.5%) | 29 entities
- **Files**: 1 files (0.5%) | 6 entities
- **Fixtures**: 1 files (0.5%) | 6 entities
- **Flask**: 23 files (11.9%) | 620 entities
- **Frontend**: 2 files (1.0%) | 21 entities
- **Go**: 1 files (0.5%) | 10 entities
- **Graphs**: 2 files (1.0%) | 1543 entities
- **Hcl**: 2 files (1.0%) | 16 entities
- **Invalid_configs**: 3 files (1.6%) | 44 entities
- **Java**: 1 files (0.5%) | 28 entities
- **Javascript**: 1 files (0.5%) | 13 entities
- **Json**: 3 files (1.6%) | 61 entities
- **Markup**: 2 files (1.0%) | 221 entities
- **Outputs**: 2 files (1.0%) | 75 entities
- **Python**: 1 files (0.5%) | 9 entities
- **Repomaps**: 3 files (1.6%) | 3869 entities
- **Rust**: 1 files (0.5%) | 21 entities
- **Simple_python**: 1 files (0.5%) | 2 entities
- **Src**: 4 files (2.1%) | 14 entities
- **Testdata**: 2 files (1.0%) | 204 entities
- **To**: 1 files (0.5%) | 1 entities
- **Webhooks**: 5 files (2.6%) | 218 entities
- **Yaml**: 2 files (1.0%) | 76 entities

## Language Breakdown

| Language | Files | Percentage |
|----------|-------|------------|
| Python | 128 | 66.3% |
| JSON | 24 | 12.4% |
| MD | 15 | 7.8% |
| YAML | 7 | 3.6% |
| TOML | 4 | 2.1% |
| CSS | 3 | 1.6% |
| TF | 2 | 1.0% |
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
  📄 batho.yaml
  📄 extract_graph_data.py
  📄 pyproject.toml
  ... and 1 more
    📁 plans/
      📄 batho-testing-checklist-c65c7b.md
  📁 batho_core/
    📄 config.py
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
      📄 file_io.py
      📄 file_lock.py
      📄 hash.py
      ... and 5 more
    📁 webhook/
      📄 auth.py
      📄 config.py
      📄 handler.py
      📄 parser.py
      📄 processor.py
      ... and 2 more
  📁 docs/ (Documentation)
    📄 production-readiness-report.md
    📄 test.md
    📄 updated.md
    📄 webhook-setup.md
  📁 tests/ (Testing Suite)
    📄 conftest.py
    📄 test_flask_fixture.py
    📄 test_incremental_patch.py
    📄 test_time_machine.py
    📄 test_webhook.py
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
| setting | 4907 |
| section | 1829 |
| element | 1312 |
| method | 1043 |
| function | 354 |
| class | 258 |
| attribute | 60 |
| document | 58 |
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
| tests/testdata/outputs/repomaps/flask_sample_repomap.json | 5 |
| batho_core.time_machine | 4 |
| sys | 4 |
| tests/testdata/repositories/flask/.readthedocs.yaml | 4 |
| warnings | 4 |
| batho_core.context.languages.registry | 3 |
| batho_core.context.codegraph | 2 |
| batho_core.context.languages.detector | 2 |
| datetime | 2 |
