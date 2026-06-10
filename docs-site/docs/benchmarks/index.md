---
title: Performance Benchmarks
sidebar_label: Coming Soon
---

# Performance Benchmarks

:::caution Coming Soon
Comprehensive performance benchmarks for Batho will be published in a future release. We are currently calibrating our benchmark suite to cover a wide range of codebase sizes and environments.
:::

Batho is designed from the ground up for maximum throughput and minimal overhead. In upcoming releases, we will publish comparative benchmarks details for the following key performance areas:

---

## Planned Benchmark Metrics

### ⚡ Build Throughput
- **Description:** Speed of building the initial code hypergraph from scratch.
- **Comparison:** Scalability on repos from 10k LOC up to 10M LOC.

### ⏱️ Patch Latency
- **Description:** Time taken to parse changed files, update dependencies, and incrementally update the hypergraph representation.
- **Comparison:** Comparison of full rebuild vs. incremental patching.

### 📦 Export Compression Ratio
- **Description:** Efficiency of the Bidirectional Semantic Graph (BSG) compression algorithm.
- **Comparison:** Zip / Tar compression size versus BSG compressed map format.

### 🔄 Load Restoration Speed
- **Description:** Time needed to fully restore/reconstruct the internal code state and active graph representation from stored Arrow bundles.

---

Stay tuned for the official benchmark data and replication scripts!
