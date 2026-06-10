---
sidebar_position: 99
title: "FAQ"
description: "Frequently asked questions about Batho"
---

# Frequently Asked Questions

## General

### What is Batho?

Batho (Bidirectional AST Traversal & Hypergraph Orchestrator) is a deterministic code intelligence engine that transforms raw codebases into queryable, time-aware structured hypergraphs.

### Is Batho free?

Yes. Batho is open-source under the Apache 2.0 license.

### What languages does Batho support?

40+ languages via tree-sitter, including Python, TypeScript, JavaScript, Go, Java, Rust, C, C++, Ruby, PHP, Swift, Kotlin, and many more.

## Installation & Setup

### Do I need Python 3.11+?

Yes. Batho uses modern Python features and requires 3.11 or newer.

### Can I use pip instead of uv?

Yes. `pip install batho` works, but `uv` is recommended for faster installs and dependency resolution.

## Usage

### How do I ignore files?

Batho respects `.gitignore` automatically along with default ignore patterns for common build artifacts and dependencies.

### What is the `.batho/` directory?

It's the content directory where Batho stores all artifacts: the Arrow IPC database bundle, msgpack AST cache, and telemetry metrics logs.

### Can I run Batho in CI?

Yes. Batho has zero code execution guarantees and is safe to run in CI pipelines. See the CI/CD integration docs.

## Performance

### How fast is indexing?

~1,000 files/sec with AST caching enabled. A 100K file repository indexes in about 3 minutes on modern hardware.

### What is the cache hit rate?

>95% on typical pull request changes. Only modified files are re-parsed.

## Troubleshooting

### My index is stale. What do I do?

Run `batho patch --root .` to auto-detect and apply incremental updates, or `batho build --root . --full` for a complete rebuild.

### How do I clear the cache?

Caches can be sweeped or compacted using:
```bash
# Deletes old runs and vacuums the database
batho gc --root . vacuum
```
Alternatively, configure cache expiration limits (e.g. `ttl_days: 30`) under the `extraction.cache` and `bsg.cache` sections in your `batho.yaml` file.

### Where are the logs?

By default, logs go to stderr. You can configure a log file in `batho.yaml`:

```yaml
logging:
  file: .batho/batho.log
```
