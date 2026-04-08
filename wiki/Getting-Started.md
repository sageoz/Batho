# Getting Started

Get Batho running in under a minute.

---

## 1. Install

```bash

uv add batho 
# or
pip install batho
```

---

## 2. Index your codebase

```bash
batho index --root <path to repo> --verbose --snapshot
```

This scans your project and builds a structured graph.

---

## 3. Generate LLM-ready output

```bash
batho bsg --root <path to repo> --mode compressed --budget 12000
```

---

## 4. Update incrementally

```bash
batho patch --root <path to repo> --scan
```

---

## 📂 Output Directory

Batho creates:

```
.ctn/
```

This contains:

* Graph data
* BSG outputs
* Snapshots
* Patch history
* Metrics data
* Index output
* Contex data

---

## ✅ What just happened?

Batho:

1. Parsed your code
2. Built relationships
3. Generated structured output
4. Stored everything locally
