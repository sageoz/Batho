# Comprehensive Testing Implementation Tasks

Consolidate all planning into detailed phase-wise implementation tasks for achieving 90%+ test coverage across Batho core features with comprehensive test automation for both real repository testing and local functional testing.

## Phase 1: Foundation and Infrastructure Setup

### Task 1.1: Create Test Directory Structure
- [x] Create `tests/` directory in project root
- [x] Create `tests/testdata/` directory structure
- [x] Set up `tests/testdata/repositories/` subdirectories
- [x] Create `tests/testdata/files/` for individual file samples
- [x] Create `tests/testdata/outputs/` for expected results
- [x] Create `tests/testdata/fixtures/` for test support data
- [x] Create `tests/cli/`, `tests/context/`, `tests/utils/`, `tests/core/` modules

### Task 1.2: Root Test Runner Script
- [x] Create `test.py` in project root
- [x] Implement test discovery functionality
- [x] Add coverage reporting integration
- [x] Configure test result aggregation
- [x] Add CI/CD compatibility features
- [x] Implement parallel test execution support
- [x] Add test filtering and selection options

### Task 1.3: Test Configuration Setup
- [x] Create `pytest.ini` configuration file
- [x] Create `tests/conftest.py` for shared fixtures
- [x] Configure pytest markers for test categorization
- [x] Set up coverage configuration (.coveragerc)
- [x] Configure test logging and output formatting
- [x] Add test environment configuration

### Task 1.4: Open Source Repository Setup
- [x] Clone Flask repository to `tests/testdata/repositories/flask/`
- [x] Pin to specific version (2.3.3) for consistency
- [x] Remove unnecessary files (.git, CI artifacts, docs/_build/)
- [x] Analyze and document repository structure
- [x] Create repository metadata and statistics
- [x] Set up repository-specific test fixtures

## Phase 2: Sample Repository Creation

### Task 2.1: Simple Python Repository
- [x] Create `tests/testdata/repositories/simple_python/`
- [x] Set up basic Python package structure
- [x] Create `src/` module with functions, classes, imports
- [x] Add `tests/` directory with sample tests
- [x] Include standard Python files (setup.py, requirements.txt)
- [x] Add `.gitignore` with common patterns
- [x] Create README.md with documentation

### Task 2.2: Multi-Language Repository
- [x] Create `tests/testdata/repositories/multi_language/`
- [x] Set up Python backend with Flask/FastAPI patterns
- [x] Create TypeScript/React frontend structure
- [x] Add shared type definitions
- [x] Include Docker configuration files
- [x] Create complex import/dependency patterns
- [x] Add package.json, tsconfig.json, requirements.txt

### Task 2.3: Edge Cases Repository
- [x] Create `tests/testdata/repositories/edge_cases/`
- [x] Add binary files (images, PDFs, executables)
- [x] Create encoding issue files (Latin-1, UTF-16, mixed)
- [x] Set up deep directory nesting structure
- [x] Add files with special characters in names
- [x] Create empty and whitespace-only files
- [x] Set up custom ignore pattern scenarios

### Task 2.4: File Samples Collection
- [x] Create Python code samples (functions, classes, imports, decorators)
- [x] Add JavaScript/TypeScript samples (ES6+, modules, components)
- [x] Include other language samples (Go, Rust, Java, C++)
- [x] Create configuration file samples (YAML, JSON, TOML, INI)
- [x] Add markup file samples (Markdown, HTML, XML)
- [x] Organize samples by language and type in `tests/testdata/files/`

## Phase 3: Core Feature Tests Implementation

### Task 3.1: CLI Command Tests
- [x] Create `tests/cli/test_cli_commands.py`
- [x] Test `cmd_index()` with various inputs and options
- [x] Test `cmd_stats()` metadata access and display
- [x] Test `cmd_snapshots()` listing functionality
- [x] Test `cmd_diff_snapshots()` comparison logic
- [x] Test `cmd_patch()` incremental reindexing
- [x] Test `cmd_webhook()` payload handling
- [x] Test `cmd_invalidate()` cache clearing
- [x] Add error handling and edge case tests
- [x] Test with all sample repositories

### Task 3.2: CLI Parser Tests
- [x] Create `tests/cli/test_cli_parser.py`
- [x] Test argument parsing for all commands
- [x] Test argument validation and error handling
- [x] Test default values and option combinations
- [x] Test help text and usage messages
- [x] Add invalid input tests

### Task 3.3: CLI Integration Tests
- [x] Create `tests/cli/test_cli_integration.py`
- [x] Test end-to-end CLI workflows
- [x] Test command chaining and state management
- [x] Test with real repository (Flask)
- [x] Test performance with large repositories
- [x] Add filesystem integration tests

### Task 3.4: CodeGraphIndexer Tests
- [x] Create `tests/context/test_codegraph.py`
- [x] Test InMemoryGraph entity and relationship management
- [x] Test CodeGraphIndexer file processing pipeline
- [x] Test binary detection (magic bytes, entropy, null bytes)
- [x] Test file caching (mtime + SHA-256 caching)
- [x] Test parallel processing and thread safety
- [x] Test import resolution logic
- [x] Test error isolation and exception handling
- [x] Test performance metrics collection
- [x] Add large-scale tests with Flask repository

### Task 3.5: RepoMap Rendering Tests
- [x] Create `tests/context/test_repomap.py`
- [x] Test RepoMap.build() graph conversion
- [x] Test render_full() aider-style output
- [x] Test render_compressed() token-budgeted rendering
- [x] Test render_json() structured output
- [x] Test render_hierarchical() directory tree
- [x] Test token estimation algorithms
- [x] Test dependency mapping accuracy
- [x] Validate output formats against expected results

## Phase 4: Language and Configuration Tests

### Task 4.1: Language Detection Tests
- [x] Create `tests/context/test_languages.py`
- [x] Test extension-based language detection
- [x] Test shebang detection for executable files
- [x] Test heuristic detection for ambiguous files
- [x] Test extractor registry and loading
- [x] Test query-based extraction functionality
- [x] Test cross-language support in multi-language repo
- [x] Add edge cases for unknown file types

### Task 4.2: Stack Detection Tests
- [x] Create `tests/context/test_stack_detector.py`
- [x] Test technology stack identification
- [x] Test framework detection patterns
- [x] Test dependency analysis
- [x] Validate stack detection on sample repositories
- [x] Test edge cases and ambiguous stacks

### Task 4.3: Configuration Management Tests
- [x] Create `tests/core/test_config.py`
- [x] Test Pydantic model validation
- [x] Test environment variable overrides
- [x] Test config file loading (JSON, YAML, TOML)
- [x] Test default configuration values
- [x] Test configuration caching and reload
- [x] Test schema version management
- [x] Test build info and version handling
- [x] Add invalid configuration tests

### Task 4.4: Schema and Extractor Tests
- [x] Create `tests/core/test_schema.py`
- [x] Test Entity and Relationship schema validation
- [x] Test entity type enumeration
- [x] Test relationship type definitions
- [x] Test metadata handling
- [x] Test schema serialization/deserialization

### Task 4.5: Base Extractor Tests
- [x] Create `tests/core/test_extractor.py`
- [x] Test ASTExtractor base functionality
- [x] Test tree-sitter integration
- [x] Test query execution and result parsing
- [x] Test error handling for malformed code
- [x] Test position and range calculations

## Phase 5: Utility Module Tests

### Task 5.1: Logging Tests
- [x] Create `tests/utils/test_logging.py`
- [x] Test structured logging configuration
- [x] Test console vs JSON rendering
- [x] Test log level handling
- [x] Test context binding and logger creation
- [x] Test log message formatting
- [x] Test integration with stdlib logging

### Task 5.2: Hash Utility Tests
- [x] Create `tests/utils/test_hash.py`
- [x] Test SHA-256 computation for bytes and strings
- [x] Test file hashing with chunked reading
- [x] Test cached file hashing with mtime invalidation
- [x] Test entity ID generation
- [x] Test relationship ID generation
- [x] Test hash truncation functionality
- [x] Add performance tests for large files

### Task 5.3: Ignore Pattern Tests
- [x] Create `tests/utils/test_ignore.py`
- [x] Test default ignore patterns
- [x] Test .gitignore file loading and parsing
- [x] Test .bathoignore file handling
- [x] Test pathspec integration and fallback
- [x] Test pattern matching for files and directories
- [x] Test should_ignore_path convenience function
- [x] Test walk_ignored_filtered iterator
- [x] Test rglob_ignored_filtered function
- [x] Add complex pattern tests

### Task 5.4: Encoding Tests
- [x] Create `tests/utils/test_encoding.py`
- [x] Test read_text_with_fallback functionality
- [x] Test decode_bytes_with_fallback
- [x] Test normalize_to_utf8 conversion
- [x] Test multiple encoding fallbacks
- [x] Test error handling strategies
- [x] Add tests for problematic encodings

### Task 5.5: Dependency Tests
- [x] Create `tests/utils/test_dependencies.py`
- [x] Test dependency parsing functionality
- [x] Test import statement analysis
- [x] Test dependency graph construction
- [x] Test cross-file dependency resolution
- [x] Add tests for complex dependency patterns

## Phase 6: Integration and Performance Tests

### Task 6.1: End-to-End Workflow Tests
- [x] Create `tests/integration/test_workflows.py`
- [x] Test complete indexing workflow on all sample repos
- [x] Test snapshot creation and management
- [x] Test incremental patch workflows
- [x] Test configuration-driven workflows
- [x] Test error recovery and cleanup

### Task 6.2: Performance Tests
- [x] Create `tests/performance/test_performance.py`
- [x] Test indexing performance on Flask repository
- [x] Test memory usage with large repositories
- [x] Test parallel processing efficiency
- [x] Test cache performance and hit rates
- [x] Create performance benchmarks and regression tests
- [x] Test scalability with increasing file counts

### Task 6.3: Cross-Platform Tests
- [x] Create `tests/integration/test_cross_platform.py`
- [x] Test path handling on different operating systems
- [x] Test file permission scenarios
- [x] Test special character handling in paths
- [x] Test encoding issues across platforms

### Task 6.4: Error Handling Tests
- [x] Create `tests/integration/test_error_handling.py`
- [x] Test malformed file handling
- [x] Test permission denied scenarios
- [x] Test disk space exhaustion
- [x] Test network failure scenarios
- [x] Test corrupted cache recovery

## Phase 7: Expected Outputs and Validation

### Task 7.1: Generate Expected Graph Outputs
- [x] Generate expected graph JSON for simple_python repo
- [x] Generate expected graph JSON for multi_language repo
- [x] Create sample graph JSON for Flask repository
- [x] Validate entity and relationship counts
- [x] Document expected import resolution results

### Task 7.2: Generate Expected RepoMap Outputs
- [x] Create expected full rendering for simple_python
- [x] Create expected compressed rendering with token budgets
- [x] Create expected hierarchical tree output
- [x] Generate expected JSON structured output
- [x] Validate dependency mapping accuracy

### Task 7.3: Create Configuration Samples
- [x] Create default configuration expectations
- [x] Generate custom configuration examples
- [x] Create environment override scenarios
- [x] Add invalid configuration examples for error testing

### Task 7.4: Webhook and API Mock Data
- [x] Create GitHub push webhook payload samples
- [x] Create GitHub PR webhook payload samples
- [x] Add invalid webhook payload examples
- [x] Create API response mock data

## Phase 8: Coverage Optimization and Validation

### Task 8.1: Coverage Analysis
- [x] Run initial coverage analysis on all tests
- [x] Identify uncovered code paths and branches
- [x] Analyze coverage gaps by module
- [x] Create coverage improvement plan

### Task 8.2: Additional Tests for Coverage
- [x] Add tests for uncovered error handling paths
- [x] Add tests for edge case conditions
- [x] Add tests for configuration edge cases
- [x] Add tests for utility function edge cases
- [x] **CSS Extractor Tests** - Improved from 9.68% to 87.90% ✅ ALL TESTS PASSING
- [x] **HCL Extractor Tests** - Improved from 6.50% to 69.50% ✅ ALL TESTS PASSING  
- [x] **YAML Extractor Tests** - Improved from 14.15% to 71.70% ✅ ALL TESTS PASSING
- [x] **Language Detector Tests** - Improved from 41.06% to 50.33% ✅ ALL TESTS PASSING

### Task 8.3: Branch Coverage Enhancement
- [ ] Add tests for all conditional branches
- [ ] Add exception handling tests
- [ ] Add boundary condition tests
- [ ] Add parameter validation tests

### Task 8.4: Final Coverage Validation
- [ ] Achieve 90%+ coverage across all modules
- [ ] Validate coverage quality (not just quantity)
- [ ] Generate HTML coverage reports
- [ ] Create coverage trend analysis

## Phase 9: Documentation and Maintenance

### Task 9.1: Test Documentation
- [ ] Create test execution guide
- [ ] Document test data organization
- [ ] Create contribution guidelines for tests
- [ ] Document performance benchmark procedures

### Task 9.2: CI/CD Integration
- [ ] Configure GitHub Actions for automated testing
- [ ] Set up coverage reporting integration
- [ ] Configure performance regression detection
- [ ] Add test data validation in CI pipeline

### Task 9.3: Maintenance Procedures
- [ ] Document test data update procedures
- [ ] Create repository version management plan
- [ ] Document test environment setup
- [ ] Create troubleshooting guide

### Task 9.4: Quality Assurance
- [ ] Review all test code for quality
- [ ] Validate test data integrity
- [ ] Ensure test independence and isolation
- [ ] Verify test reproducibility

## Success Criteria

### Coverage Requirements
- [ ] Minimum 90% code coverage across all modules
- [ ] 100% coverage for critical CLI commands
- [ ] 95%+ coverage for core indexing functionality
- [ ] All error handling paths covered

### Functional Requirements
- [ ] All CLI commands tested with comprehensive scenarios
- [ ] All sample repositories processed successfully
- [ ] Performance tests validate scalability
- [ ] Integration tests cover complete workflows

### Quality Requirements
- [ ] Tests are maintainable and well-documented
- [ ] Test data is realistic and comprehensive
- [ ] Coverage reports are generated and analyzed
- [ ] CI/CD integration is functional

### Performance Requirements
- [ ] Flask repository indexing completes in reasonable time
- [ ] Memory usage stays within acceptable limits
- [ ] Parallel processing provides performance benefits
- [ ] Cache hit rates meet expectations

This comprehensive task list consolidates all planning into actionable implementation phases for achieving thorough test coverage and automation for Batho core features.
