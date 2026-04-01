# LSP Container Benchmark Testing Guide

## Executive Overview

This guide documents the methodology for running deterministic benchmark tests for Batho's Tier 1 LSP containers (Python, TypeScript, Go, Rust, Java, C/C++) hosted in Podman on macOS. These benchmarks validate that the hermetic LSP integration produces 100% identical output graph hashes across 1,000 consecutive runs—a critical requirement for enterprise auditability.

### Success Criteria

| Criterion | Target |
|-----------|--------|
| Hash match rate | **100%** (0 deviations across all runs) |
| OS parity | Linux graph hash == macOS graph hash |
| Error run rate | < 0.1% (< 6 exception runs across 6,000 total) |
| p99 latency per run | < 10 seconds |
| CI smoke test runtime | < 5 minutes per language |

### Podman vs Docker on macOS

On macOS, Podman requires a virtual machine (via `podman machine`) because containers are Linux-native. Docker Desktop also uses a VM but manages it transparently. This guide focuses on Podman commands, with Docker equivalents noted where they differ.

---

## Prerequisites

### System Requirements

- macOS 13.0 (Ventura) or later
- 16GB RAM minimum (32GB recommended for Java/C++ benchmarks)
- 50GB free disk space for container images and benchmark fixtures
- Apple Silicon (M1/M2/M3) or Intel Mac

### Tool Installation

#### 1. Install Podman

```bash
# Using Homebrew
brew install podman

# Initialize Podman machine (required on macOS)
podman machine init --cpus=4 --memory=8192 --disk-size=50

# Start the machine
podman machine start

# Verify installation
podman version
```

#### 2. Docker Desktop (Alternative)

If using Docker instead of Podman:

```bash
# Install Docker Desktop from https://docs.docker.com/desktop/install/mac-install/
# Or via Homebrew
brew install --cask docker

# Start Docker Desktop application
open -a Docker

# Verify installation
docker version
```

#### 3. Install Python and uv

```bash
# Install Python 3.11+ if not present
python3 --version

# Install uv (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Verify uv installation
uv --version
```

#### 4. Clone Batho Repository

```bash
git clone https://github.com/sageoz/batho.git
cd batho

# Initialize submodules for benchmark fixtures
git submodule update --init --recursive
```

---

## Container Setup

### Building Hermetic LSP Containers

Each Tier 1 language has a pre-defined container specification in `batho_core/lsp/containers/registry.yaml`. Build containers for the languages you intend to benchmark:

#### Python (Pyright)

```bash
# Using Podman
podman build \
  -t batho-lsp/python:1.1.350 \
  -f containers/python/Containerfile \
  --build-arg PYRIGHT_VERSION=1.1.350 \
  .

# Verify image
podman images | grep batho-lsp/python
```

#### TypeScript (TSServer)

```bash
podman build \
  -t batho-lsp/typescript:5.3.3 \
  -f containers/typescript/Containerfile \
  --build-arg TSSERVER_VERSION=5.3.3 \
  .
```

#### Go (gopls)

```bash
podman build \
  -t batho-lsp/go:0.14.2 \
  -f containers/go/Containerfile \
  --build-arg GOPLS_VERSION=v0.14.2 \
  --build-arg GO_VERSION=1.21.6 \
  .
```

#### Rust (rust-analyzer)

```bash
podman build \
  -t batho-lsp/rust:2024-03-25 \
  -f containers/rust/Containerfile \
  --build-arg RUST_ANALYZER_DATE=2024-03-25 \
  --build-arg RUST_VERSION=1.76.0 \
  .
```

#### Java (Eclipse JDT LS)

```bash
podman build \
  -t batho-lsp/java:1.31.0 \
  -f containers/java/Containerfile \
  --build-arg JDTLS_VERSION=1.31.0 \
  --build-arg JDK_VERSION=21.0.2 \
  .
```

#### C/C++ (clangd)

```bash
podman build \
  -t batho-lsp/cpp:18.1.3 \
  -f containers/cpp/Containerfile \
  --build-arg CLANGD_VERSION=18.1.3 \
  --build-arg LLVM_VERSION=18 \
  .
```

### Container Image Verification

Verify container integrity before running benchmarks:

```bash
# Get image digest
podman inspect batho-lsp/python:1.1.350 --format='{{.Id}}'

# Compare with registry.yaml
# Expected: sha256:abc123... (must match registry entry)

# Run verification script
uv run python -m batho_core.lsp.containers.verify \
  --language python \
  --version 1.1.350 \
  --builder podman
```

### Podman Machine Resource Allocation

For consistent benchmark results, ensure adequate resources:

```bash
# Check current machine specs
podman machine inspect

# If needed, recreate with more resources
podman machine stop
podman machine rm
podman machine init --cpus=8 --memory=16384 --disk-size=100
podman machine start

# Verify resource allocation
podman machine ssh free -h
```

### Volume Mounting Strategies

Benchmarks require mounting source code into containers. Use these patterns:

```bash
# Read-only mount (recommended for determinism)
podman run \
  --rm \
  -v "$PWD/tests/benchmark/fixtures/python:/workspace:ro,z" \
  batho-lsp/python:1.1.350 \
  pyright-langserver --stdio

# Key flags:
# :ro = read-only mount
# :z = SELinux label for shared access
```

**Note**: The `:z` flag is important on macOS with Podman's VM to ensure proper permission handling.

---

## Benchmark Methodology

### Test Repository Selection

Each language uses a pinned OSS repository as the benchmark fixture:

| Language | Repository | Pinned Tag/Commit | Scope |
|----------|------------|-------------------|-------|
| Python | tiangolo/fastapi | v0.110.0 | Full repo |
| TypeScript | vercel/next.js | v14.2.3 | Monorepo root |
| Go | kubernetes/kubernetes | v1.29.3 | `pkg/api` subdirectory |
| Rust | tokio-rs/tokio | v1.37.0 | Full workspace |
| Java | spring-projects/spring-boot | v3.2.4 | Full repo |
| C/C++ | llvm/llvm-project | llvmorg-18.1.3 | `clang/lib` subset |

Repositories are registered as git submodules under `tests/benchmark/fixtures/<language>/`.

### The 1,000-Run Determinism Test Protocol

1. **Setup Phase**: Initialize fixture repository, build container, verify checksums
2. **Warmup Phase**: Run 5 iterations to warm caches (results discarded)
3. **Measurement Phase**: Run 1,000 iterations, recording each graph hash
4. **Validation Phase**: Assert all 1,000 hashes are identical
5. **Reporting Phase**: Generate latency statistics and hash comparison report

### Performance Metrics to Collect

For each of the 1,000 runs, record:

- **Total runtime**: End-to-end graph generation time
- **LSP initialization time**: Time from container start to `initialized` notification
- **File scan time**: Time to discover and parse all source files
- **Symbol resolution time**: Time for LSP `textDocument/definition` queries
- **Graph merge time**: Time to merge LSP data with Tree-sitter AST

Report percentiles:
- **p50**: Median latency
- **p95**: 95th percentile (typical worst-case)
- **p99**: 99th percentile (outlier detection)

### Hash Canonicalization Process

To ensure deterministic hashing across runs:

1. **Strip timestamps**: Remove `timestamp` and `duration_ms` fields from entities
2. **Normalize paths**: Convert absolute paths to workspace-relative paths
3. **Sort entities**: Order entities and relationships by stable ID
4. **Stable serialization**: Use sorted JSON with consistent whitespace
5. **SHA256 hash**: Generate final hash of canonical representation

---

## Step-by-Step Execution

### Step 1: Initialize Benchmark Fixtures

```bash
# Navigate to batho root
cd /path/to/batho

# Initialize all benchmark fixture submodules
git submodule update --init --recursive

# Verify fixtures are present
ls tests/benchmark/fixtures/
# Expected: python/  typescript/  go/  rust/  java/  cpp/

# Check pinned commits
cd tests/benchmark/fixtures/python && git log --oneline -1
# Should show: v0.110.0 tag
cd ../../..
```

### Step 2: Run Smoke Tests (10 Runs)

Smoke tests validate the setup without the full 1,000-run time investment:

```bash
# Run Python smoke test
uv run pytest tests/benchmark/test_python_determinism.py::test_python_smoke -v

# Run all smoke tests
uv run pytest tests/benchmark/ -m "quick" -v

# Expected output: All tests pass with 10/10 hash matches
```

### Step 3: Run Full Benchmark Suite (1,000 Runs)

**Warning**: Full benchmarks take significant time (2-4 hours per language).

```bash
# Run single language full benchmark
uv run pytest tests/benchmark/test_python_determinism.py::test_python_1000_runs -v --tb=short

# Run all full benchmarks (6+ hours total)
uv run pytest tests/benchmark/ -m "full" -v

# Or use the CLI tool
uv run python -m tests.benchmark.cli \
  --language python \
  --runs 1000 \
  --output results-python.json
```

### Step 4: Cross-Platform Comparison

To validate OS parity:

```bash
# On macOS - generate hash file
uv run python -m tests.benchmark.cli \
  --language python \
  --runs 100 \
  --output results-python-macos.json

# On Linux (or CI) - generate hash file
uv run python -m tests.benchmark.cli \
  --language python \
  --runs 100 \
  --output results-python-linux.json

# Compare hashes
diff <(jq '.hash' results-python-macos.json) <(jq '.hash' results-python-linux.json)
# Expected: No output (hashes identical)
```

---

## Troubleshooting

### Podman Machine Issues on macOS

**Issue**: `Error: podman machine is not running`

```bash
# Check machine status
podman machine list

# Start machine
podman machine start

# If stuck, restart
podman machine stop
podman machine start
```

**Issue**: `Error: unable to connect to Podman socket`

```bash
# Reset connection
podman machine stop
podman machine rm
podman machine init
podman machine start

# Verify
podman info
```

### Performance Tuning for Containers

**Issue**: Benchmarks running slowly

```bash
# Check VM resources
podman machine ssh top -bn1 | head -20

# Increase CPU and memory
podman machine stop
podman machine rm
podman machine init --cpus=8 --memory=16384 --disk-size=100
podman machine start

# For specific containers, increase limits
podman run --memory=4096m --cpus=4 ...
```

### Volume Mount Permissions

**Issue**: `Permission denied` when reading source files

```bash
# Use :z flag for SELinux labeling
podman run -v "$PWD:/workspace:ro,z" ...

# Or disable SELinux temporarily (less secure)
podman run --security-opt label=disable -v "$PWD:/workspace:ro" ...
```

### Network Isolation Verification

**Issue**: LSP trying to access network

```bash
# Verify no network access
podman run --network=none batho-lsp/python:1.1.350 \
  python -c "import urllib.request; urllib.request.urlopen('https://example.com')"
# Expected: Connection error (this is correct for hermetic containers)
```

---

## Results Interpretation

### What Constitutes a Passing Result

A successful benchmark run meets all these criteria:

1. **Hash uniformity**: All 1,000 runs produce identical SHA256 hashes
2. **Zero exceptions**: Less than 0.1% run failure rate
3. **Performance bounds**: p99 latency under 10 seconds per run
4. **OS parity**: macOS and Linux produce identical hashes

### Handling Hash Mismatches

If hashes differ across runs:

1. **Identify the diff**: Use `tests/benchmark/hasher.py` to compare canonical forms
2. **Check for non-deterministic fields**: Look for timestamps, absolute paths, random IDs
3. **Review LSP responses**: Some LSPs may include non-deterministic metadata
4. **Strip problematic fields**: Add field exclusions to the hasher
5. **Re-run**: Verify fix with another 100-run quick test

### Performance Baseline Expectations

Approximate p50 latencies on M2 Mac with 8 CPU / 16GB VM:

| Language | Fixture Size | p50 Latency | p99 Latency |
|----------|--------------|-------------|-------------|
| Python | 500 files | 2-3s | 5-8s |
| TypeScript | 2000 files | 5-8s | 15-20s |
| Go | 1000 files | 3-5s | 10-15s |
| Rust | 800 files | 4-6s | 12-18s |
| Java | 3000 files | 10-15s | 30-45s |
| C/C++ | 1500 files | 6-10s | 20-30s |

**Note**: First run includes container startup time; subsequent runs use warm caches.

### Documentation Requirements

After completing benchmarks, update:

1. `docs/determinism-benchmark-results.md` - Add results table row
2. `LSP_integration_task.md` - Mark Milestone 3 tasks complete
3. Create PR with benchmark results and any code changes

Results table format:

```markdown
| Language | OS | Deterministic? | p50 latency | p99 latency | Hash |
|----------|----|----------------|-------------|-------------|------|
| Python | macOS 14 | Yes | 2.3s | 5.1s | a1b2c3... |
```

---

## Docker Compatibility Notes

Where Docker commands differ from Podman:

| Operation | Podman | Docker |
|-----------|--------|--------|
| Machine init | `podman machine init` | Not required |
| Machine start | `podman machine start` | Start Docker Desktop app |
| Build | `podman build` | `docker build` |
| Run | `podman run` | `docker run` |
| Images | `podman images` | `docker images` |
| Inspect | `podman inspect` | `docker inspect` |
| VM SSH | `podman machine ssh` | `docker run --rm -it alpine` |

**Docker Desktop on macOS**:
- Resource limits configured in Docker Desktop UI (Settings > Resources)
- No explicit `machine init` required
- Use `docker` instead of `podman` for all commands

---

## Quick Reference

### Essential Commands

```bash
# Full benchmark workflow
podman machine start
git submodule update --init --recursive
uv run pytest tests/benchmark/ -m "quick" -v
uv run pytest tests/benchmark/test_python_determinism.py::test_python_1000_runs -v

# Check results
uv run python scripts/update_benchmark_results.py --input results.json
```

### File Locations

| File | Purpose |
|------|---------|
| `tests/benchmark/` | Benchmark test code |
| `tests/benchmark/fixtures/` | Git submodule benchmark repositories |
| `batho_core/lsp/containers/registry.yaml` | LSP version specifications |
| `docs/determinism-benchmark-results.md` | Living results document |
| `.github/workflows/benchmark-determinism.yml` | CI workflow |

---

**Document Version**: 1.0  
**Last Updated**: 2026-03-31  
**Compatibility**: Podman 4.9+, Docker Desktop 4.27+, macOS 13+
