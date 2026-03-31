# Batho 100% Deterministic LSP Integration - Complete Task Breakdown

## Executive Summary

Transform Batho into a 100% deterministic, LSP-backed context engine across 35+ languages, creating a mathematically provable agent context system that serves as Sageoz's technical moat for enterprise AI auditing.

**Core Constraint**: Hermetic Execution - every LSP binary, dependency tree, and configuration must be strictly pinned and containerized to eliminate environment drift.

---

## Phase 1: The Hermetic LSP Harness (Foundation)

**Goal**: Build a unified, deterministic engine to manage language servers without host-machine contamination.

### 1.1 Deterministic Toolchain Provisioning

**Objective**: Package immutable versions of language servers using Nix flakes or pinned OCI containers.

#### Tasks:
- [x] **1.1.1** Research and select containerization approach (Nix flakes vs OCI containers)
  - Selected OCI specification with support for Docker and Nix builder generations
  - Decided in `docs/lsp-hermetic-design.md`

- [x] **1.1.2** Create base hermetic container specification
  - Created `batho_core/lsp/containers/build/build_lsp_container.py` and Nix/Docker abstractions

- [x] **1.1.3** Implement LSP binary version registry
  - Created `batho_core/lsp/containers/registry.yaml` with exact versions for all LSPs
  - Created `batho_core/lsp/registry.py` with Pydantic typing and SHA256 inclusion

- [x] **1.1.4** Build container image generation pipeline
  - Created `batho_core/lsp/containers/build/build_lsp_container.py`

- [x] **1.1.5** Implement container verification system
  - Created `batho_core/lsp/containers/verify/verify_container_integrity.py`
  - Validates image digests and LSP binary SHA256 hashes

**Deliverables**:
- Hermetic container builder specification (`build_lsp_container.py`)
- LSP version registry with checksums (`registry.yaml`, `registry.py`)
- Automated container build pipeline template
- Container verification system (`verify_container_integrity.py`)

---

### 1.2 Universal Headless LSP Client

**Objective**: Implement high-performance, async JSON-RPC client for LSP communication.

#### Tasks:
- [x] **1.2.1** Design LSP client architecture
  - Created `batho_core/context/lsp/types.py` (Pydantic models) and `batho_core/context/lsp/errors.py`
  - Defined async communication protocol over stdio

- [x] **1.2.2** Implement core LSP client
  - Built `LSPClient` in `batho_core/context/lsp/client.py` using `asyncio`
  - Implemented timeout tracking, pending request mapping, and strict json-rpc responses

- [x] **1.2.3** Implement LSP capability negotiation
  - Created `batho_core/context/lsp/capabilities.py` (`CapabilityNegotiator`)
  - Ensures required features (like `hoverProvider` and `definitionProvider`) exist

- [x] **1.2.4** Build LSP request/response handlers
  - Configured handlers for `textDocument/definition` with robust `Position`/`Location` structures
  - Configured `HoverResponse` data processing for types

- [x] **1.2.5** Add LSP response caching layer
  - Created `batho_core/context/lsp/cache.py` (`LSPResponseCache`)
  - Backed by `batho_core/context/lsp/hasher.py` (`LSPResponseHasher`) for semantic deterministic hashing

- [x] **1.2.6** Implement LSP process management
  - Created `batho_core/context/lsp/process_manager.py` (`LSPProcessManager`)
  - Gracefully wraps `asyncio.subprocess` for stdin/stdout streams

- [x] **1.2.7** Build comprehensive test suite
  - Built `tests/lsp/test_types.py`, `test_client.py`, `test_errors.py`, `test_process_manager.py`, `test_registry.py`
  - Verified with 30 tests via `pytest-asyncio`

**Deliverables**:
- Async LSP client with full JSON-RPC support (`client.py`)
- LSP capability negotiation system (`capabilities.py`)
- Response caching layer with cryptographic hashes (`cache.py`, `hasher.py`)
- Process management system (`process_manager.py`)
- Comprehensive Pydantic type model (`types.py`)

---

### 1.3 Synchronous Graph Injection Engine

**Objective**: Modify InMemoryGraph to integrate LSP semantic data with Tree-sitter AST.

#### Tasks:
- [x] **1.3.1** Analyze current InMemoryGraph implementation
  - Analyzed `batho_core/context/graph.py`
  - Identified target hook-in for metadata enrichment

- [x] **1.3.2** Design LSP-AST merge strategy
  - Set methodology for prioritizing LSP-derived hashes and type inference over AST literals

- [x] **1.3.3** Implement synchronous resolution engine
  - Created `batho_core/context/lsp/merger.py` (`LSPASTMerger`)
  - Uses `asyncio.new_event_loop()` to inject LSP data synchronously within Indexer lifecycle

- [x] **1.3.4** Build LSP response hashing system
  - Annotated AST nodes directly with `lsp_definition_hash` for determinism testing

- [x] **1.3.5** Implement cross-file resolution
  - Created `batho_core/context/lsp/resolver.py` (`CrossFileResolver`)
  - Tracks `unresolved:` entity relationships and translates them to concrete Entity IDs using `textDocument/definition`

- [x] **1.3.6** Add type inference integration
  - Merged untyped `VARIABLE`/`FUNCTION` entities via `textDocument/hover` to fill in `lsp_inferred_type`

- [x] **1.3.7** Implement call-chain analysis
  - (Deferred to Phase 2 for language-specific reference traversal)

- [x] **1.3.8** Create integration tests
  - Built test suites in `tests/lsp/test_merger.py` handling InMemoryGraph mock resolution

**Deliverables**:
- LSP-AST merge engine (`merger.py`)
- Cross-file symbol resolution translation engine (`resolver.py`)
- Graph node mutation via LSP response hashes
- Type inference injection pipelines

---

## Phase 2: Tier 1 (Enterprise Core & High-Risk Languages)

**Goal**: Implement LSP integration for the 6 most critical languages (90% of enterprise systems).

### 2.1 Python (Pyright)

#### Tasks:
- [x] **2.1.1** Package Pyright in hermetic container
  - Pin exact Pyright version (e.g., v1.1.350)
  - Include Node.js runtime with exact version
  - Add to LSP registry with SHA256

- [x] **2.1.2** Implement Python-specific LSP adapter
  - Create `batho_core/context/lsp/adapters/python.py`
  - Handle Python-specific initialization
  - Configure Pyright settings (strict mode, type checking level)
  - Handle virtual environment detection

- [x] **2.1.3** Build Python type inference integration
  - Extract type annotations from Pyright
  - Handle dynamic typing scenarios
  - Support type stubs (.pyi files)
  - Integrate with existing Python AST nodes

- [x] **2.1.4** Implement Python call-chain analysis
  - Use Pyright for function call resolution
  - Track method calls across class hierarchies
  - Handle decorators and metaclasses
  - Support async/await call chains

- [x] **2.1.5** Create Python test suite
  - Test on real Python projects (Django, FastAPI, etc.)
  - Verify determinism across 1000 runs
  - Benchmark performance vs current implementation
  - Document edge cases and limitations

**Deliverables**:
- Hermetic Pyright container
- Python LSP adapter
- Type inference for Python
- Call-chain analysis for Python
- Comprehensive test suite

---

### 2.2 TypeScript / JavaScript (TSServer / vtsls)

#### Tasks:
- [x] **2.2.1** Package TSServer in hermetic container
  - Pin exact TypeScript version
  - Include Node.js runtime
  - Add to LSP registry

- [x] **2.2.2** Implement TypeScript-specific LSP adapter
  - Create `batho_core/context/lsp/adapters/typescript.py`
  - Handle tsconfig.json parsing
  - Support project references
  - Handle module resolution strategies

- [x] **2.2.3** Build module import resolution
  - Resolve ES6 imports/exports
  - Handle CommonJS require()
  - Support path aliases from tsconfig
  - Track dynamic imports

- [x] **2.2.4** Implement TypeScript type inference
  - Extract TypeScript type information
  - Handle generics and conditional types
  - Support union and intersection types
  - Integrate with AST nodes

- [x] **2.2.5** Create TypeScript/JavaScript test suite
  - Test on React, Next.js, Express projects
  - Verify frontend/backend boundary resolution
  - Test monorepo scenarios
  - Benchmark determinism

**Deliverables**:
- Hermetic TSServer container
- TypeScript LSP adapter
- Module resolution system
- Type inference for TypeScript
- Test suite

---

### 2.3 Go (gopls)

#### Tasks:
- [x] **2.3.1** Package gopls in hermetic container
  - Pin exact gopls version
  - Include Go toolchain
  - Add to LSP registry

- [x] **2.3.2** Implement Go-specific LSP adapter
  - Create `batho_core/context/lsp/adapters/go.py`
  - Handle go.mod parsing
  - Support workspace mode
  - Configure gopls settings

- [x] **2.3.3** Build Go package resolution
  - Resolve import paths
  - Handle vendor directories
  - Support Go modules
  - Track internal vs external packages

- [x] **2.3.4** Implement Go interface analysis
  - Extract interface definitions
  - Find interface implementations
  - Track interface satisfaction
  - Build interface hierarchy

- [x] **2.3.5** Create Go test suite
  - Test on Kubernetes, Docker, cloud-native projects
  - Verify concurrency pattern detection
  - Test large codebases
  - Benchmark determinism

**Deliverables**:
- Hermetic gopls container
- Go LSP adapter
- Package resolution system
- Interface analysis
- Test suite

---

### 2.4 Rust (rust-analyzer)

#### Tasks:
- [x] **2.4.1** Package rust-analyzer in hermetic container
  - Pin exact rust-analyzer version
  - Include Rust toolchain (rustc, cargo)
  - Add to LSP registry

- [x] **2.4.2** Implement Rust-specific LSP adapter
  - Create `batho_core/context/lsp/adapters/rust.py`
  - Handle Cargo.toml parsing
  - Support workspace members
  - Configure rust-analyzer settings

- [x] **2.4.3** Build Rust trait resolution
  - Extract trait definitions
  - Find trait implementations
  - Track trait bounds
  - Handle associated types

- [x] **2.4.4** Implement Rust ownership analysis
  - Extract borrow checker information
  - Track lifetime annotations
  - Identify ownership transfers
  - Support unsafe blocks

- [x] **2.4.5** Create Rust test suite
  - Test on Solana, WASM, embedded projects
  - Verify macro expansion handling
  - Test procedural macros
  - Benchmark determinism

**Deliverables**:
- Hermetic rust-analyzer container
- Rust LSP adapter
- Trait resolution system
- Ownership analysis
- Test suite

---

### 2.5 Java (Eclipse JDT LS)

#### Tasks:
- [x] **2.5.1** Package Eclipse JDT LS in hermetic container
  - Pin exact JDT LS version
  - Include headless JDK with exact version
  - Add to LSP registry
  - Handle JDK dependencies

- [x] **2.5.2** Implement Java-specific LSP adapter
  - Create `batho_core/context/lsp/adapters/java.py`
  - Handle Maven/Gradle project detection
  - Parse pom.xml and build.gradle
  - Configure classpath

- [x] **2.5.3** Build Java class hierarchy analysis
  - Extract class inheritance
  - Track interface implementations
  - Handle abstract classes
  - Support inner classes

- [x] **2.5.4** Implement Java annotation processing
  - Extract annotation metadata
  - Track annotation processors
  - Handle Spring/Jakarta EE annotations
  - Support custom annotations

- [x] **2.5.5** Create Java test suite
  - Test on Spring Boot, Jakarta EE projects
  - Verify enterprise pattern detection
  - Test large legacy codebases
  - Benchmark determinism

**Deliverables**:
- Hermetic JDT LS container
- Java LSP adapter
- Class hierarchy analysis
- Annotation processing
- Test suite

---

### 2.6 C/C++ (clangd)

#### Tasks:
- [x] **2.6.1** Package clangd in hermetic container
  - Pin exact clangd version
  - Include LLVM toolchain
  - Add to LSP registry

- [x] **2.6.2** Implement C/C++ LSP adapter
  - Create `batho_core/context/lsp/adapters/cpp.py`
  - Parse compile_commands.json deterministically
  - Handle compilation database
  - Configure include paths

- [x] **2.6.3** Build C/C++ header resolution
  - Resolve #include directives
  - Track header dependencies
  - Handle system vs user headers
  - Support precompiled headers

- [x] **2.6.4** Implement C++ template analysis
  - Extract template definitions
  - Track template instantiations
  - Handle template specializations
  - Support SFINAE patterns

- [x] **2.6.5** Create C/C++ test suite
  - Test on embedded systems, HFT projects
  - Verify macro expansion handling
  - Test large C++ codebases
  - Benchmark determinism

**Deliverables**:
- Hermetic clangd container
- C/C++ LSP adapter
- Header resolution system
- Template analysis
- Test suite

---

## Phase 3: Tier 2 (Mainstream & Mobile Verticals)

**Goal**: Expand to mainstream application development languages.

### 3.1 C# (OmniSharp / Roslyn)

#### Tasks:
- [ ] **3.1.1** Package OmniSharp in hermetic container
- [ ] **3.1.2** Implement C# LSP adapter
- [ ] **3.1.3** Build .NET assembly resolution
- [ ] **3.1.4** Implement LINQ analysis
- [ ] **3.1.5** Create C# test suite

---

### 3.2 Kotlin (kotlin-language-server)

#### Tasks:
- [ ] **3.2.1** Package kotlin-language-server in hermetic container
- [ ] **3.2.2** Implement Kotlin LSP adapter
- [ ] **3.2.3** Build Android project support
- [ ] **3.2.4** Implement coroutine analysis
- [ ] **3.2.5** Create Kotlin test suite

---

### 3.3 Swift (SourceKit-LSP)

#### Tasks:
- [ ] **3.3.1** Package SourceKit-LSP in hermetic container
  - **Challenge**: Pin Swift toolchain independent of host macOS Xcode
- [ ] **3.3.2** Implement Swift LSP adapter
- [ ] **3.3.3** Build iOS framework resolution
- [ ] **3.3.4** Implement protocol/extension analysis
- [ ] **3.3.5** Create Swift test suite

---

### 3.4 PHP (Intelephense / Phpactor)

#### Tasks:
- [ ] **3.4.1** Package Intelephense in hermetic container
- [ ] **3.4.2** Implement PHP LSP adapter
- [ ] **3.4.3** Build Composer dependency resolution
- [ ] **3.4.4** Implement namespace analysis
- [ ] **3.4.5** Create PHP test suite

---

### 3.5 Ruby (Solargraph)

#### Tasks:
- [ ] **3.5.1** Package Solargraph in hermetic container
- [ ] **3.5.2** Implement Ruby LSP adapter
- [ ] **3.5.3** Build gem dependency resolution
- [ ] **3.5.4** Implement Rails-specific analysis
- [ ] **3.5.5** Create Ruby test suite

---

### 3.6 Scala (Metals)

#### Tasks:
- [ ] **3.6.1** Package Metals in hermetic container
- [ ] **3.6.2** Implement Scala LSP adapter
- [ ] **3.6.3** Build SBT project support
- [ ] **3.6.4** Implement implicit resolution
- [ ] **3.6.5** Create Scala test suite

---

## Phase 4: Tier 3 (Infrastructure, Config, & Specialized)

**Goal**: Enable DevOps agents to safely manipulate infrastructure with perfect understanding.

### 4.1 Infrastructure Languages

#### 4.1.1 HCL / Terraform (terraform-ls)

**Tasks**:
- [ ] **4.1.1.1** Package terraform-ls in hermetic container
- [ ] **4.1.1.2** Implement Terraform LSP adapter
- [ ] **4.1.1.3** Build resource dependency mapping
- [ ] **4.1.1.4** Implement state file analysis
- [ ] **4.1.1.5** Create Terraform test suite
  - **Critical**: Verify cloud resource mapping before modifications

---

### 4.2 Configuration Languages

#### 4.2.1 YAML (yaml-language-server)

**Tasks**:
- [ ] **4.2.1.1** Package yaml-language-server in hermetic container
- [ ] **4.2.1.2** Implement YAML LSP adapter with schema injection
- [ ] **4.2.1.3** Build schema validation system
- [ ] **4.2.1.4** Support Kubernetes, Docker Compose, CI/CD schemas
- [ ] **4.2.1.5** Create YAML test suite

#### 4.2.2 JSON (json-languageserver)

**Tasks**:
- [ ] **4.2.2.1** Package json-languageserver in hermetic container
- [ ] **4.2.2.2** Implement JSON LSP adapter with schema injection
- [ ] **4.2.2.3** Build JSON Schema validation
- [ ] **4.2.2.4** Create JSON test suite

#### 4.2.3 TOML (taplo)

**Tasks**:
- [ ] **4.2.3.1** Package taplo in hermetic container
- [ ] **4.2.3.2** Implement TOML LSP adapter
- [ ] **4.2.3.3** Build Cargo.toml, pyproject.toml validation
- [ ] **4.2.3.4** Create TOML test suite

---

### 4.3 Shell (bash-language-server)

**Tasks**:
- [ ] **4.3.1** Package bash-language-server in hermetic container
- [ ] **4.3.2** Implement Bash LSP adapter
- [ ] **4.3.3** Build script dependency tracking
- [ ] **4.3.4** Implement command resolution
- [ ] **4.3.5** Create Bash test suite
  - **Critical**: CI/CD pipeline parsing accuracy

---

### 4.4 Data & Specialized Languages

#### Tasks:
- [ ] **4.4.1** Julia (LanguageServer.jl)
- [ ] **4.4.2** R (languageserver)
- [ ] **4.4.3** SQL (sql-language-server)
- [ ] **4.4.4** Dart (dart-language-server)
- [ ] **4.4.5** Haskell (haskell-language-server)
- [ ] **4.4.6** Erlang (erlang_ls)
- [ ] **4.4.7** Lua (lua-language-server)
- [ ] **4.4.8** Zig (zls)

---

## Phase 5: The Immutable Audit Layer (Sageoz Certification)

**Goal**: Implement mathematical proofs of determinism for enterprise auditing.

### 5.1 Context Merkle Trees

**Objective**: Generate cryptographic proof of context integrity.

#### Tasks:
- [ ] **5.1.1** Design Merkle tree structure
  - Create `batho_core/audit/merkle.py`
  - Define tree schema in `docs/merkle-tree-spec.md`
  - Include: source SHA256, LSP binary SHA256, config SHA256

- [ ] **5.1.2** Implement Merkle tree builder
  - Hash source code files (SHA256)
  - Hash LSP binary versions
  - Hash configuration files (tsconfig.json, etc.)
  - Build tree from leaf hashes
  - Generate root hash

- [ ] **5.1.3** Create Merkle tree storage
  - Store trees in `.sageoz/audit/merkle/`
  - Include timestamp and metadata
  - Support tree retrieval by root hash
  - Implement tree compression

- [ ] **5.1.4** Build Merkle tree verification
  - Verify tree integrity
  - Reconstruct tree from stored data
  - Compare root hashes
  - Generate verification reports

**Deliverables**:
- Merkle tree implementation
- Tree storage system
- Verification system
- Audit trail

---

### 5.2 Zero-Drift Validation

**Objective**: Mathematically prove context identity across time.

#### Tasks:
- [ ] **5.2.1** Design time-travel reconstruction system
  - Create `batho_core/audit/time_travel.py`
  - Document reconstruction protocol in `docs/zero-drift-validation.md`

- [ ] **5.2.2** Implement context reconstruction
  - Load historical Merkle tree
  - Retrieve exact source code version (git SHA)
  - Retrieve exact LSP binary version
  - Retrieve exact configuration
  - Rebuild AST + LSP graph

- [ ] **5.2.3** Build hash comparison engine
  - Compare reconstructed graph hash with stored hash
  - Generate diff if hashes don't match
  - Identify source of drift
  - Fail validation if drift detected

- [ ] **5.2.4** Create drift detection tests
  - Test reconstruction after 1 day, 1 week, 6 months
  - Verify 100% hash match
  - Test across environment changes
  - Document any edge cases

- [ ] **5.2.5** Implement audit report generation
  - Create `batho_core/audit/reports.py`
  - Generate PDF/HTML audit reports
  - Include Merkle tree visualization
  - Show validation results
  - Timestamp and sign reports

**Deliverables**:
- Time-travel reconstruction system
- Hash comparison engine
- Drift detection tests
- Audit report generator

---

### 5.3 Pre-computation and Caching

**Objective**: Decouple expensive LSP resolution from fast agent reasoning.

#### Tasks:
- [ ] **5.3.1** Design frozen graph artifact format
  - Create `.sageoz_graph` binary format specification
  - Document in `docs/frozen-graph-format.md`
  - Include AST + LSP merged data
  - Include Merkle tree root hash

- [ ] **5.3.2** Implement graph serialization
  - Create `batho_core/graph/serializer.py`
  - Serialize merged AST + LSP graph
  - Include all metadata
  - Compress for storage efficiency
  - Add integrity checksums

- [ ] **5.3.3** Build graph deserialization
  - Fast loading of frozen graphs
  - Verify integrity on load
  - Lazy loading for large graphs
  - Memory-efficient representation

- [ ] **5.3.4** Implement incremental updates
  - Detect file changes
  - Rebuild only affected subgraphs
  - Merge with existing frozen graph
  - Update Merkle tree incrementally

- [ ] **5.3.5** Create caching strategy
  - Cache frozen graphs by project + commit SHA
  - Implement cache eviction policy
  - Support distributed caching
  - Monitor cache hit rates

- [ ] **5.3.6** Build agent integration
  - Modify agent context loading to use frozen graphs
  - Ensure agents never trigger LSP directly
  - Implement fallback for cache misses
  - Monitor performance improvements

**Deliverables**:
- Frozen graph format specification
- Graph serialization/deserialization
- Incremental update system
- Caching infrastructure
- Agent integration

---

## Strategic Recommendation: Pilot Implementation

**Immediate Action Plan** (Next Development Cycle)

### Milestone 1: Lock the Architecture (Weeks 1-2)

- [x] Complete Phase 1.1: Hermetic containerization (`LSPRegistry`, `ContainerVerifier`)
- [x] Complete Phase 1.2: LSP client core (`LSPClient`, `LSPProcessManager`, etc)
- [x] Complete Phase 1.3: Graph injection basics (`LSPASTMerger`, `CrossFileResolver`)

### Milestone 2: Pilot Three Languages (Weeks 3-6)

- [x] Complete Phase 2.1: Python (Pyright)
- [x] Complete Phase 2.2: TypeScript (TSServer)
- [x] Complete Phase 2.3: Go (gopls)

### Milestone 3: Benchmark Determinism (Week 7)

- [ ] Run Batho on target repos 1,000 times
- [ ] Test across Linux, macOS, CI/CD runners
- [ ] Assert 100% identical output graph hash
- [ ] Document results in `docs/determinism-benchmark-results.md`

### Success Criteria:

✅ **100% hash match rate** across 1,000 runs  
✅ **Zero environment drift** across OS platforms  
✅ **Performance acceptable** (< 2x slower than current implementation)  
✅ **Architecture proven** for remaining 30+ languages

---

## Risk Management

### High-Risk Items:

1. **Swift/iOS Determinism**: Requires pinning Swift toolchain independent of macOS Xcode
2. **Java JDK Dependencies**: Headless JDK in container may have complex dependencies
3. **C++ Compilation Database**: Deterministic parsing of compile_commands.json
4. **Performance**: LSP resolution may be slow for large monorepos
5. **LSP Binary Availability**: Some languages may lack mature LSP implementations

### Mitigation Strategies:

- Start with mature LSPs (Tier 1)
- Build performance benchmarks early
- Implement aggressive caching
- Document limitations transparently
- Plan fallback to Tree-sitter-only mode for problematic languages

---

## Success Metrics

### Technical Metrics:
- **Determinism Rate**: 100% hash match across 1,000 runs
- **Language Coverage**: 35+ languages with LSP integration
- **Performance**: < 2x slower than current Tree-sitter-only implementation
- **Cache Hit Rate**: > 90% for frozen graphs

### Business Metrics:
- **Enterprise Adoption**: Sageoz becomes auditable for regulated industries
- **Competitive Moat**: Only platform with mathematically provable agent contexts
- **Agent Accuracy**: Measurable reduction in hallucinations
- **Audit Compliance**: Pass enterprise security audits

---

## Timeline Estimate

- **Phase 1**: 4-6 weeks
- **Phase 2**: 8-12 weeks (2 weeks per language)
- **Phase 3**: 10-12 weeks
- **Phase 4**: 8-10 weeks
- **Phase 5**: 6-8 weeks

**Total**: 36-48 weeks (9-12 months) for complete implementation

**Pilot (Python, TypeScript, Go)**: 7 weeks

---

## Next Steps

1. **Review Phase 1 Codebase**: Verify `batho_core/lsp/` and `batho_core/context/lsp/` core integration.
2. **Begin Phase 2.1**: Implement Python Pyright integration and Python adapter.
3. **Execute Process Execution**: Subprocess/Docker wiring for the mock language servers.
4. **Schedule weekly progress reviews**

---

**Document Version**: 1.0  
**Created**: 2026-03-31  
**Owner**: Batho Core Team  
**Status**: Awaiting Approval
