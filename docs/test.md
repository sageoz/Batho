# Batho v1.0 Production-Readiness Testing Checklist

This comprehensive checklist validates Batho v1.0's core features against massive, complex repositories to ensure production readiness.

---

## Repository Test Matrix

| Category | Repository | Primary Language(s) | Difficulty Level | Why Test It? |
|----------|------------|---------------------|------------------|--------------|
| Language Polyglot | facebook/react-native | JS, Java, Obj-C++, C++ | High | Tests cross-platform symbol resolution and multi-language context switching |
| Language Polyglot | pytorch/pytorch | Python, C++, CUDA | High | Validates ability to follow Python bindings into native C++ implementations |
| Monolith (Scale) | torvalds/linux | C | Extreme | Tests raw indexing speed, memory management, and deeply nested file systems |
| Monolith (Scale) | microsoft/vscode | TypeScript | High | Challenges parser with massive modularity and heavy type-checking overhead |
| Syntax Edge Case | rust-lang/rust | Rust | Extreme | Contains complex macros and cutting-edge syntax that breaks standard parsers |
| Syntax Edge Case | swiftlang/swift | Swift, C++ | High | Tests modern functional programming patterns and complex generic resolutions |
| Dependency Tree | spring-projects/spring-boot | Java | Med/High | Tests resolution of deep Maven/Gradle dependency trees and heavy annotation usage |
| Dependency Tree | vercel/next.js | TypeScript, Rust | Medium | Massive monorepo testing internal package linking and workspace resolution |
| Generated Code | grpc/grpc | Polyglot (C++, Py, etc.) | Medium | Tests handling of non-human auto-generated code from .proto files |
| Generated Code | tensorflow/tensorflow | Python, C++, Bazel | Extreme | Challenges tool to find hidden code generated during build process |

---

## Phase 1: Core CLI & Lifecycle Testing (All Repositories)

### 1.1 Command: `batho index` (Initial Generation)
- **Test**: Run indexing on repository root
```bash
batho index --root /path/to/repo --verbose
```
- **Validation**:
  - [ ] `.ctn/` directory is created
  - [ ] `graph.json`, `bsg.json`, and `architecture.md` are populated
  - [ ] Completes without crashing
  - [ ] AST generation gracefully skips unsupported files without halting
- **Success Metric**: Process exits with code 0 (success) or 2 (partial success with parse errors)

### 1.2 Command: `batho stats` (Metadata Verification)
- **Test**: Run immediately after indexing
```bash
batho stats --root /path/to/repo
```
- **Validation**:
  - [ ] Entity counts accurately reflect repository scale
  - [ ] File counts match expected repository size
  - [ ] Relationship metrics are populated
  - [ ] Compression ratios are calculated
- **Success Metric**: JSON output contains valid summary statistics

### 1.3 Command: `batho invalidate` (Cache Purging)
- **Test**: Run command, then run `batho index` again
```bash
batho invalidate --root /path/to/repo
batho index --root /path/to/repo --verbose
```
- **Validation**:
  - [ ] File cache is cleanly wiped
  - [ ] Subsequent index triggers full parse (not incremental)
  - [ ] Cache hit rate is 0.0 on re-index
- **Success Metric**: Second indexing takes similar time to first (full re-parse)

### 1.4 Command: `batho patch` / Time Machine (Cherry-picking)
- **Test**: Make local change, generate patch snapshot, attempt dry run
```bash
# Make a small change to a file
batho patch --root /path/to/repo --dry-run file1.py
```
- **Validation**:
  - [ ] `evolution_ledger.json` accurately logs the delta
  - [ ] Dry run shows affected files without making changes
  - [ ] Patch operation completes successfully
- **Success Metric**: Evolution ledger updated with correct change detection

---

## Phase 2: "Green Architecture" Profiling

### 2.1 Idle CPU Check
- **Test**: Open workspace in VS Code, leave idle for 10 minutes
- **Validation**:
  - [ ] TypeScript Watcher consumes **0% CPU** during idle
  - [ ] No background processes consuming resources
  - [ ] Memory usage remains stable
- **Success Metric**: CPU usage < 1% averaged over 10 minutes

### 2.2 Extension Activation (Lazy Loading)
- **Test**: Open repository without `.ctn/` folder and no AI agent active
- **Validation**:
  - [ ] Batho extension does **not** activate initially
  - [ ] Extension activates after running `batho index`
  - [ ] Activation is lazy, not eager
- **Success Metric**: Extension load time < 500ms after index creation

### 2.3 Payload Size Limit
- **Test**: Trigger massive terminal failure (e.g., failing build in linux or pytorch)
- **Validation**:
  - [ ] Python MCP server does not crash from large stdout/stderr payload
  - [ ] Error handling gracefully manages large outputs
  - [ ] No memory exhaustion from payload processing
- **Success Metric**: Server remains responsive after handling >10MB terminal output

### 2.4 AST Parse Speed (Tree-sitter)
- **Test**: Time AST extraction on large files
```bash
time batho index --root /path/to/repo --verbose 2>&1 | grep "parsed"
```
- **Validation**:
  - [ ] Parsing resolves in milliseconds per file
  - [ ] Even massive files (e.g., vscode's checker.ts) parse quickly
  - [ ] Parallel processing utilizes multiple cores
- **Success Metric**: Average parse time <100ms per file, even for large files

---

## Phase 3: Repository-Specific Stress Tests

### 3.1 Language Polyglot (Cross-Language Context)

#### Target: facebook/react-native (JS/C++/Java/Obj-C)
- **Test 1**: Cross-Boundary AST Parsing
  - **Action**: Modify a JavaScript file that calls native Java/Obj-C modules
  - **Validation**:
    - [ ] `ast_parser.py` maps context across language boundaries
    - [ ] `baseline_map.json` includes cross-language relationships
    - [ ] Import chains are properly resolved across languages
  - **Success Metric**: Cross-language calls appear in relationship graph

#### Target: pytorch/pytorch (Python/C++/CUDA)
- **Test 2**: MCP Brief Accuracy
  - **Action**: Call `mcp.tool.get_nexus_brief("tensor.py")` in PyTorch
  - **Validation**:
    - [ ] Brief includes relevant C++ references, not just Python context
    - [ ] CUDA kernel bindings are properly referenced
    - [ ] Template instantiations are tracked
  - **Success Metric**: Brief spans multiple language contexts accurately

### 3.2 Monolith Scale (Memory & Speed)

#### Target: torvalds/linux (C)
- **Test 3**: OOM (Out of Memory) Resilience
  - **Action**: Run `batho index` on Linux Kernel source
  - **Validation**:
    - [ ] Python process stays under reasonable memory limits (2-4GB)
    - [ ] JSON outputs are streamed/batched to avoid holding entire kernel in RAM
    - [ ] No crashes during indexing
  - **Success Metric**: Peak memory usage <4GB, process completes successfully

#### Target: microsoft/vscode (TypeScript)
- **Test 4**: Deep File System Traversal
  - **Action**: Trigger file diff in deeply nested directory
  - **Validation**:
    - [ ] File monitor instantly captures `onDidSaveTextDocument` event
    - [ ] No lag in processing deep directory changes
    - [ ] Massive node_modules is properly ignored
  - **Success Metric**: File change detection <100ms for any depth

### 3.3 Syntax Edge Cases (Parser Breakage)

#### Target: rust-lang/rust (Complex Macros)
- **Test 5**: Macro Expansion Handling
  - **Action**: Run Batho on Rust compiler source
  - **Validation**:
    - [ ] Tree-sitter failures are caught gracefully
    - [ ] Unresolved macros are marked as "unresolved" in `bsg.json`
    - [ ] Process continues without crashing on complex macros
  - **Success Metric**: Parser completes with macro complexity noted but not blocking

#### Target: swiftlang/swift (Generics)
- **Test 6**: Evolution Ledger on Obscure Errors
  - **Action**: Write bad Swift generic causing massive compiler error
  - **Validation**:
    - [ ] `synthesizer.py` correlates verbose error log with file diff
    - [ ] Concise "Don't" rule generated in `evolution_ledger.json`
    - [ ] Error context is properly captured
  - **Success Metric**: Ledger entry captures semantic rule from complex error

### 3.4 Dependency Tree (Resolution Depth)

#### Target: spring-projects/spring-boot (Java/Maven)
- **Test 7**: Heavy Annotation Parsing
  - **Action**: Modify `@Autowired` or `@Bean` annotated class
  - **Validation**:
    - [ ] AST parser registers annotations as critical semantic nodes
    - [ ] Maven dependency tree is properly resolved
    - [ ] Annotation relationships are tracked
  - **Success Metric**: Annotations appear in graph with proper relationships

#### Target: vercel/next.js (TS/Monorepo)
- **Test 8**: Monorepo Workspace Linking
  - **Action**: Modify file in `packages/next` that breaks test in `examples/`
  - **Validation**:
    - [ ] Batho identifies workspace boundary correctly
    - [ ] Internal dependency map included in `Nexus Brief`
    - [ ] Cross-workspace dependencies are tracked
  - **Success Metric**: Workspace relationships preserved in dependency graph

### 3.5 Generated Code (Ignore & Heuristics)

#### Target: grpc/grpc (.proto generation)
- **Test 9**: Build Output Ignorance
  - **Action**: Run full build generating thousands of .pb.cc/.pb.go files
  - **Validation**:
    - [ ] Batho ignores auto-generated files by default
    - [ ] Build artifacts don't bloat `baseline_map.json`
    - [ ] Only source .proto files are indexed
  - **Success Metric**: Generated files excluded from index, only source tracked

#### Target: tensorflow/tensorflow (Bazel build outputs)
- **Test 10**: Agent Instruction Adherence
  - **Action**: Trigger error on generated .pb.go file in gRPC
  - **Validation**:
    - [ ] `synthesizer.py` flags editing of generated file
    - [ ] `skill.md` updated with rule: "Do not manually edit .pb files"
    - [ ] Guidance points to corresponding .proto file
  - **Success Metric**: Agent receives clear guidance about generated file handling

---

## Phase 4: "Evolution Ledger" Integration Test (Ultimate Test)

Execute this complete loop on any repository to prove end-to-end functionality:

### 4.1 Complete Feedback Loop Test
1. **Inject Bug**: Introduce logical flaw (null pointer, off-by-one error)
2. **Run Test**: Execute test suite via VS Code integrated terminal
3. **Verify Capture**: Ensure `terminalMonitor.ts` captures failure and sends to Python MCP
4. **Verify Ledger**: Check `.ctn/evolution_ledger.json` for new semantic rule
5. **Query MCP**: Query `get_nexus_brief()` for file - new rule MUST be appended

- **Validation**:
  - [ ] Bug injection triggers test failure
  - [ ] Terminal output captured and processed
  - [ ] Evolution ledger updated with "Don't" rule
  - [ ] MCP brief includes new rule for context
  - [ ] Subsequent queries include the learned rule
- **Success Metric**: Complete loop executes in <60 seconds with accurate rule generation

---

## Performance Benchmarks & Success Criteria

### Memory Usage Limits
| Repository Category | Max Memory | Duration |
|-------------------|------------|----------|
| Polyglot (React Native) | 2GB | <5 min |
| Polyglot (PyTorch) | 3GB | <8 min |
| Monolith (Linux) | 4GB | <15 min |
| Monolith (VSCode) | 3GB | <10 min |
| Syntax Edge Cases | 2GB | <5 min |
| Dependency Trees | 2GB | <5 min |
| Generated Code | 2GB | <5 min |

### Parse Speed Requirements
- **Small files** (<1KB): <10ms per file
- **Medium files** (1-100KB): <50ms per file  
- **Large files** (>100KB): <200ms per file
- **Massive files** (>1MB): <1s per file

### Accuracy Requirements
- **Cross-language references**: >95% accuracy
- **Dependency resolution**: >90% accuracy
- **Annotation parsing**: >95% accuracy
- **Generated code detection**: >99% accuracy

---

## Test Execution Framework

### Prerequisites
```bash
# Clone test repositories
git clone https://github.com/facebook/react-native
git clone https://github.com/pytorch/pytorch
git clone https://github.com/torvalds/linux
git clone https://github.com/microsoft/vscode
git clone https://github.com/rust-lang/rust
git clone https://github.com/swiftlang/swift
git clone https://github.com/spring-projects/spring-boot
git clone https://github.com/vercel/next.js
git clone https://github.com/grpc/grpc
git clone https://github.com/tensorflow/tensorflow
```

### Test Automation Script
```bash
#!/bin/bash
# run_production_tests.sh

REPOS=(
    "facebook/react-native:polyglot"
    "pytorch/pytorch:polyglot"
    "torvalds/linux:monolith"
    "microsoft/vscode:monolith"
    "rust-lang/rust:edge-case"
    "swiftlang/swift:edge-case"
    "spring-projects/spring-boot:dependency"
    "vercel/next.js:dependency"
    "grpc/grpc:generated"
    "tensorflow/tensorflow:generated"
)

for repo_info in "${REPOS[@]}"; do
    repo=$(echo $repo_info | cut -d':' -f1)
    category=$(echo $repo_info | cut -d':' -f2)
    
    echo "Testing $repo [$category]..."
    
    # Phase 1: Core CLI tests
    batho index --root $repo --verbose
    batho stats --root $repo
    batho invalidate --root $repo
    batho index --root $repo --verbose
    
    # Phase 2: Architecture tests (manual verification needed)
    
    # Phase 3: Category-specific tests
    case $category in
        "polyglot")
            # Run cross-language tests
            ;;
        "monolith")
            # Run memory/scale tests
            ;;
        "edge-case")
            # Run syntax edge case tests
            ;;
        "dependency")
            # Run dependency resolution tests
            ;;
        "generated")
            # Run generated code tests
            ;;
    esac
    
    echo "Completed $repo"
done
```

### Continuous Integration Integration
```yaml
# .github/workflows/production-tests.yml
name: Production Readiness Tests

on:
  schedule:
    - cron: '0 2 * * 0'  # Weekly on Sunday 2AM
  workflow_dispatch:

jobs:
  test-repositories:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        repo: [react-native, pytorch, linux, vscode, rust, swift, spring-boot, nextjs, grpc, tensorflow]
    
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install Batho
        run: pip install -e .
      
      - name: Clone Test Repository
        run: |
          case "${{ matrix.repo }}" in
            react-native) git clone https://github.com/facebook/react-native ;;
            pytorch) git clone https://github.com/pytorch/pytorch ;;
            linux) git clone https://github.com/torvalds/linux ;;
            vscode) git clone https://github.com/microsoft/vscode ;;
            rust) git clone https://github.com/rust-lang/rust ;;
            swift) git clone https://github.com/swiftlang/swift ;;
            spring-boot) git clone https://github.com/spring-projects/spring-boot ;;
            nextjs) git clone https://github.com/vercel/next.js ;;
            grpc) git clone https://github.com/grpc/grpc ;;
            tensorflow) git clone https://github.com/tensorflow/tensorflow ;;
          esac
      
      - name: Run Production Tests
        run: |
          timeout 1800 bash ./run_production_tests.sh ${{ matrix.repo }}
      
      - name: Upload Results
        uses: actions/upload-artifact@v3
        with:
          name: test-results-${{ matrix.repo }}
          path: .ctn/
```

---

## Success Metrics Summary

### Must Pass (Critical)
- [ ] All CLI commands complete without crashing on all repositories
- [ ] Memory usage stays within defined limits
- [ ] Parse speeds meet performance requirements
- [ ] Cross-language context switching works accurately
- [ ] Evolution Ledger captures and applies rules correctly

### Should Pass (Important)
- [ ] Green Architecture principles maintained (zero idle CPU)
- [ ] Generated code properly ignored
- [ ] Complex syntax handled gracefully
- [ ] Dependency trees resolved accurately
- [ ] Monorepo workspace linking works

### Nice to Have (Enhancement)
- [ ] Sub-60s complete Evolution Ledger loop
- [ ] >95% accuracy on all relationship types
- [ ] Seamless VS Code integration
- [ ] Comprehensive error recovery

---

## Troubleshooting Guide

### Common Issues & Solutions

1. **Memory Overflow on Linux Kernel**
   - **Issue**: Exceeds 4GB memory limit
   - **Solution**: Reduce `--max-workers`, increase `--max-file-size-kb` filtering

2. **Parse Failures on Rust Macros**
   - **Issue**: Tree-sitter crashes on complex macros
   - **Solution**: Ensure per-file exception isolation is working

3. **Cross-Language Reference Loss**
   - **Issue**: Python->C++ bindings not tracked
   - **Solution**: Verify language detector is properly categorizing files

4. **Generated Code Bloat**
   - **Issue**: .pb files included in index
   - **Solution**: Check ignore patterns and generated file detection

5. **VS Code Extension Not Activating**
   - **Issue**: Extension loads immediately instead of lazily
   - **Solution**: Verify activation conditions in package.json

### Debug Commands
```bash
# Debug memory usage
python -m memory_profiler batho.py index --root /path/to/repo

# Debug parse performance
batho index --root /path/to/repo --verbose --log-json

# Debug cross-language issues
batho stats --root /path/to/repo | jq '.current.stack'

# Debug evolution ledger
cat .ctn/evolution_ledger.json | jq .
```

---

## Conclusion

This comprehensive testing checklist validates Batho v1.0's production readiness across the most challenging repositories in open source. Successful completion of all tests demonstrates:

1. **Scalability**: Ability to handle massive codebases efficiently
2. **Accuracy**: Precise cross-language understanding and relationship tracking
3. **Robustness**: Graceful handling of edge cases and errors
4. **Architecture**: Adherence to green computing principles
5. **Integration**: End-to-end Evolution Ledger functionality

Execution of this checklist provides confidence that Batho can handle real-world, enterprise-scale codebases while maintaining its core principles of zero-bloat, never-polluting operation.
