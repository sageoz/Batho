# Architecture

Batho is a **code intelligence engine** that transforms raw source code into structured, queryable, and AI-ready representations.

It is designed to bridge the gap between **human-written code** and **machine understanding**.

---

## 🧠 Mental Model

At its core, Batho converts:

```text
Codebase → Structure → Graph → Compressed Knowledge → AI
```

Instead of treating code as plain text, Batho understands it as a **system of entities and relationships**.

---

## 🔄 End-to-End Flow

When you run:

```bash
batho index --root .
```

Batho executes the following pipeline:

```text
1. Scan files
2. Parse AST (tree-sitter)
3. Extract entities
4. Build graph
5. Generate BSG
6. Persist artifacts
7. Enable querying / AI usage
```

---

## 🏗️ System Architecture

Batho is composed of three major subsystems:

### 1. Core Engine (Code Understanding)

Responsible for turning code into structured data.

```text
context/
```

Includes:

* Parsing (tree-sitter)
* Entity extraction
* Graph construction
* Symbol indexing
* Incremental updates

---

### 2. BSG Layer (AI Optimization)

Responsible for transforming code graphs into AI-consumable formats.

```text
bsg/
```

Includes:

* Graph compression
* Rule engine
* Plugin system
* Metadata enrichment

---

### 3. Runtime Systems (Automation & Integration)

Responsible for lifecycle management and integrations.

```text
time_machine.py + hooks/ + webhook/
```

Includes:

* Snapshots & diffs
* Incremental patching
* Git hooks
* Webhook processing

---

## 🧩 Core Components

### CLI Layer

**Entry point:** `batho_cli.py`

* Parses user commands
* Configures execution
* Triggers pipeline

---

### Parsing Layer

**Location:** `context/languages/`

* Uses tree-sitter grammars
* Provides language-specific extraction logic
* Supports 40+ languages

---

### Graph Engine

**Location:** `context/codegraph.py`

* Builds in-memory graph
* Tracks entities and relationships

Each entity includes:

* id
* name
* type
* file
* location

Each relationship includes:

* source → target
* type (CALLS, IMPORTS, etc.)

---

### BSG Engine

**Location:** `context/bsg_map.py`

Transforms graphs into:

* **Full** → detailed representation
* **Hierarchical** → directory-level structure
* **Compressed** → optimized for LLM context

---

### Time Machine

**Location:** `time_machine.py`

Provides:

* Snapshot creation
* Version comparison
* Incremental patching
* Change tracking

---

### Query Engine

**Location:** `context/query.py`

Enables:

* Entity lookup
* Relationship traversal
* File-based queries

---

### Storage Layer

**Location:** `.ctn/`

Stores:

* Graph artifacts
* BSG outputs
* Snapshots
* Patch history
* Metrics

---

## 📂 Project Structure

```text
batho/
├── assets/                 # Static assets

├── batho/                  # Core library
│   ├── config.py           # Configuration system
│   ├── synthesizer.py      # Context synthesis
│   ├── time_machine.py     # Snapshots & patching
│
│   ├── bsg/                # BSG system
│   │   ├── rules.py
│   │   ├── plugins/
│   │   └── schemas/
│
│   ├── context/            # Core engine
│   │   ├── codegraph.py
│   │   ├── extractor.py
│   │   ├── pipeline.py
│   │   ├── bsg_map.py
│   │   ├── query.py
│   │   ├── incremental.py
│   │   ├── storage.py
│   │   ├── symbol_index.py
│   │   ├── stack_detector.py
│   │   ├── cache.py
│   │   └── languages/
│
│   ├── hooks/              # Git hook automation
│   ├── utils/              # Utilities
│   └── webhook/            # Webhook system
│
├── docs/                   # Documentation
├── tests/                  # Test suite
```

---

## ⚙️ Data Flow

```text
User Command
    ↓
CLI Layer
    ↓
File Scanner
    ↓
Parser (AST)
    ↓
Entity Extraction
    ↓
Graph Construction
    ↓
BSG Generation
    ↓
Storage (.ctn/)
    ↓
Query / AI Systems
```

---

## 🔁 Incremental Update Flow

Batho avoids full reprocessing using incremental updates:

```text
1. Detect changed files (mtime + hash)
2. Re-parse only changed files
3. Update graph partially
4. Record patch
5. Update snapshot
```

---

## ⚡ Performance Design

Batho is optimized for large repositories:

* Parallel processing (multi-threaded parsing)
* File hashing (skip unchanged files)
* Incremental patching (partial updates)
* Memory-aware storage

---

## 🛡️ Fault Tolerance

* Each file is processed independently
* Failures do not stop indexing
* Partial results are preserved

---

## 🎯 Design Principles

### Language-Agnostic

Supports multiple languages via tree-sitter.

---

### Scalable

Handles large codebases efficiently.

---

### Safe

* No code execution
* Fully offline
* Works on untrusted repositories

---

### AI-First

Designed for:

* LLM context injection
* Code understanding
* Agent-based systems

---

## 🔌 Integration Points

Batho integrates with:

* Git hooks → automated indexing
* CI/CD → continuous analysis
* Webhooks → event-driven updates
* AI systems → structured context

---

## 🧩 Extensibility

Batho is designed to be extended:

* Add new language parsers
* Create custom BSG rules
* Extend query capabilities
* Build integrations

---

## 🚀 Summary

Batho transforms code into intelligence:

```text
Files → AST → Graph → BSG → AI-ready context
```

This enables:

* Deep code understanding
* Efficient LLM usage
* Scalable analysis of large repositories
