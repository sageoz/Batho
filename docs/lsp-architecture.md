# Batho LSP Integration Architecture

## System Overview

The Batho LSP Integration creates a **100% deterministic, hermetic context engine** that combines Tree-sitter AST parsing with LSP semantic analysis across 35+ languages.

```mermaid
flowchart TB
    subgraph "Source Code"
        SRC[Source Files<br/>*.py, *.ts, *.go, etc.]
    end

    subgraph "Hermetic Execution Layer"
        direction TB
        NIX[Nix Flakes /<br/>OCI Containers]
        LSP_BIN[LSP Binaries<br/>Pyright, gopls, etc.]
        REGISTRY[LSP Version Registry<br/>SHA256 Checksums]
    end

    subgraph "Batho Core Engine"
        direction TB
        CLIENT[Universal LSP Client<br/>batho_core/context/lsp/client.py]
        SYNC[Sync Graph Injection Engine<br/>Pause AST → LSP Resolve → Continue]
        CACHE[Response Cache<br/>Content-Addressed]
        MERGE[AST + LSP Merger<br/>Semantic Enrichment]
    end

    subgraph "Output Artifacts"
        direction TB
        GRAPH[InMemoryGraph<br/>Enriched AST]
        FROZEN[.sageoz_graph<br/>Frozen Graph Artifact]
        MERKLE[Merkle Tree<br/>Cryptographic Proof]
    end

    subgraph "Agent Consumption"
        AGENT[LLM Agents<br/>Read-only Frozen Graphs]
        AUDIT[Audit System<br/>Zero-Drift Validation]
    end

    SRC --> CLIENT
    NIX --> LSP_BIN
    REGISTRY --> NIX
    LSP_BIN --> CLIENT
    CLIENT --> SYNC
    SYNC --> CACHE
    CACHE --> MERGE
    MERGE --> GRAPH
    GRAPH --> FROZEN
    FROZEN --> MERKLE
    FROZEN --> AGENT
    MERKLE --> AUDIT
```

## Component Architecture

### 1. Hermetic Container Layer

```mermaid
flowchart LR
    subgraph "LSP Registry"
        REG[registry.yaml]
    end

    subgraph "Container Build Pipeline"
        BUILD[build_lsp_container.py]
        NIX[Nix Flake / Dockerfile]
        PUSH[Push to Registry]
        VERIFY[verify_container_integrity.py]
    end

    subgraph "Runtime"
        PULL[Pull Container]
        HASH[Verify SHA256]
        SPAWN[Spawn LSP Process]
        STDIO[stdio Communication]
    end

    REG --> BUILD
    BUILD --> NIX
    NIX --> PUSH
    PUSH --> VERIFY
    VERIFY --> PULL
    PULL --> HASH
    HASH --> SPAWN
    SPAWN --> STDIO
```

**Key Design Decisions:**
- **Nix Flakes** preferred for reproducible builds
- **OCI Containers** as fallback for broader compatibility
- **SHA256 checksums** for every LSP binary
- **Immutable container registry** - never overwrite, only version

---

### 2. Universal LSP Client Architecture

```mermaid
flowchart TB
    subgraph "LSP Client Core"
        direction TB
        ASYNC[Async JSON-RPC Handler<br/>aiohttp / asyncio]
        RPC[Request/Response Queue]
        TIMEOUT[Timeout & Retry Logic]
        POOL[Connection Pool]
    end

    subgraph "LSP Methods"
        INIT[initialize]
        DEF[textDocument/definition]
        REF[textDocument/references]
        HOVER[textDocument/hover]
        TYPEDEF[textDocument/typeDefinition]
        IMPL[textDocument/implementation]
        SYM[textDocument/documentSymbol]
    end

    subgraph "Capability Management"
        CAP[LSP Capabilities<br/>Server → Client]
        NEG[Negotiation Logic]
        FALLBACK[Fallback to Tree-sitter]
    end

    ASYNC --> RPC
    RPC --> TIMEOUT
    TIMEOUT --> POOL
    POOL --> INIT
    INIT --> CAP
    CAP --> NEG
    NEG --> DEF
    NEG --> REF
    NEG --> HOVER
    NEG --> TYPEDEF
    NEG --> IMPL
    NEG --> SYM
    NEG -.->|Missing Cap| FALLBACK
```

---

### 3. Synchronous Graph Injection Flow

```mermaid
sequenceDiagram
    participant AST as Tree-sitter AST Builder
    participant QUEUE as Resolution Queue
    participant LSP as LSP Client
    participant HASH as Response Hasher
    participant MERGE as AST+LSP Merger
    participant GRAPH as InMemoryGraph

    AST->>AST: Parse file with Tree-sitter
    AST->>AST: Identify unresolved symbols
    
    loop For Each Unresolved Symbol
        AST->>QUEUE: Queue symbol for resolution
    end

    QUEUE->>LSP: Batch LSP requests
    LSP->>LSP: Send textDocument/definition
    LSP->>LSP: Send textDocument/references
    
    LSP-->>HASH: Raw JSON response
    HASH->>HASH: Compute SHA256 hash
    HASH-->>MERGE: Response + Hash

    MERGE->>MERGE: Merge LSP data into AST
    MERGE->>MERGE: Annotate nodes with hashes
    MERGE->>GRAPH: Insert enriched nodes

    GRAPH->>GRAPH: Continue AST traversal
```

**Critical Design Points:**
- **Synchronous pause**: AST building stops until LSP resolves
- **Batching**: Multiple symbols resolved in parallel
- **Content hashing**: Every LSP response hashed for audit
- **Timeout handling**: Graceful degradation if LSP slow/fails

---

### 4. Cross-File Resolution Architecture

```mermaid
flowchart TB
    subgraph "File Discovery"
        ENTRY[Entry File]
        IMPORTS[Extract Imports]
        DEPS[Build Dependency Graph]
    end

    subgraph "Resolution Strategy"
        BFS[BFS Traversal]
        PARALLEL[Parallel LSP Resolution]
        MERGE[Cross-File Symbol Merge]
    end

    subgraph "Dependency Types"
        PY[Python: import / from]
        TS[TypeScript: import / require]
        GO[Go: import]
        JAVA[Java: import / package]
    end

    ENTRY --> IMPORTS
    IMPORTS --> DEPS
    DEPS --> BFS
    BFS --> PARALLEL
    PARALLEL --> MERGE
    
    PY --> IMPORTS
    TS --> IMPORTS
    GO --> IMPORTS
    JAVA --> IMPORTS
```

---

### 5. Frozen Graph & Caching Architecture

```mermaid
flowchart TB
    subgraph "Graph Freezing Pipeline"
        RAW[Raw Merged Graph<br/>AST + LSP]
        SERIAL[Serializer<br/>batho_core/graph/serializer.py]
        COMPRESS[Compression<br/>zstd/lz4]
        CHECKSUM[Integrity Checksum]
        STORE[.sageoz_graph File]
    end

    subgraph "Cache Strategy"
        KEY[Cache Key<br/>project + commit SHA]
        HIT[Cache Hit?<br/>Fast Load]
        MISS[Cache Miss?<br/>Rebuild]
        EVICT[Eviction Policy<br/>LRU + Size Limit]
    end

    subgraph "Agent Access"
        AGENT[LLM Agent]
        READ[Read-only Access]
        LAZY[Lazy Loading]
    end

    RAW --> SERIAL
    SERIAL --> COMPRESS
    COMPRESS --> CHECKSUM
    CHECKSUM --> STORE
    
    STORE --> KEY
    KEY --> HIT
    KEY --> MISS
    HIT --> EVICT
    MISS --> RAW
    
    STORE --> AGENT
    AGENT --> READ
    READ --> LAZY
```

---

### 6. Merkle Tree Audit Architecture

```mermaid
flowchart TB
    subgraph "Merkle Tree Construction"
        LEAF1[Leaf: Source SHA256]
        LEAF2[Leaf: LSP Binary SHA256]
        LEAF3[Leaf: Config SHA256]
        LEAF4[Leaf: Response Hashes]
        
        HASH12[Hash(Node1+Node2)]
        HASH34[Hash(Node3+Node4)]
        
        ROOT[Root Hash<br/>Cryptographic Proof]
    end

    subgraph "Verification"
        TIME[Time Travel<br/>Historical Context]
        RECON[Reconstruct Graph]
        COMPARE[Compare Root Hashes]
        PROOF[Mathematical Proof<br/>of Determinism]
    end

    LEAF1 --> HASH12
    LEAF2 --> HASH12
    LEAF3 --> HASH34
    LEAF4 --> HASH34
    HASH12 --> ROOT
    HASH34 --> ROOT
    
    ROOT --> TIME
    TIME --> RECON
    RECON --> COMPARE
    COMPARE --> PROOF
```

---

### 7. Language Adapter Architecture

```mermaid
flowchart TB
    subgraph "Base Adapter Interface"
        BASE[batho_core/context/lsp/adapters/base.py]
        INIT[initialize]
        CONFIG[configure]
        PARSE[parse_project_config]
        ADAPT[adapt_response]
    end

    subgraph "Language-Specific Adapters"
        PY[Python Adapter<br/>Pyright]
        TS[TypeScript Adapter<br/>TSServer]
        GO[Go Adapter<br/>gopls]
        RUST[Rust Adapter<br/>rust-analyzer]
        JAVA[Java Adapter<br/>JDT LS]
        CPP[C++ Adapter<br/>clangd]
    end

    subgraph "Adapter Responsibilities"
        LSP_CONFIG[LSP Configuration]
        PATH_MAP[Path Mapping]
        TYPE_CONV[Type Conversion]
        IMPORT_RES[Import Resolution]
    end

    BASE --> PY
    BASE --> TS
    BASE --> GO
    BASE --> RUST
    BASE --> JAVA
    BASE --> CPP
    
    PY --> LSP_CONFIG
    TS --> PATH_MAP
    GO --> TYPE_CONV
    RUST --> IMPORT_RES
```

---

### 8. Error Handling & Fallback Architecture

```mermaid
flowchart TB
    subgraph "LSP Failure Scenarios"
        TIMEOUT[LSP Timeout]
        CRASH[LSP Crash]
        NOCAP[Missing Capability]
        HASH_FAIL[Hash Mismatch]
    end

    subgraph "Fallback Strategy"
        RETRY[Retry with Backoff]
        RESTART[Restart LSP Process]
        TREESITTER[Fallback to Tree-sitter Only]
        MARK[Mark as Incomplete]
    end

    subgraph "Graceful Degradation"
        WARN[Log Warning]
        CONTINUE[Continue Processing]
        FLAG[Flag in Output]
    end

    TIMEOUT --> RETRY
    CRASH --> RESTART
    NOCAP --> TREESITTER
    HASH_FAIL --> MARK
    
    RETRY --> |Max Retries| TREESITTER
    RESTART --> |Max Restarts| TREESITTER
    
    TREESITTER --> WARN
    MARK --> WARN
    WARN --> CONTINUE
    CONTINUE --> FLAG
```

---

### 9. Data Flow Overview

```mermaid
flowchart LR
    subgraph "Input"
        A[Source Files]
        B[Project Config]
    end

    subgraph "Processing"
        C[Tree-sitter Parse]
        D[LSP Container Spawn]
        E[LSP Resolution]
        F[AST+LSP Merge]
    end

    subgraph "Verification"
        G[Hash Calculation]
        H[Merkle Tree]
        I[Determinism Check]
    end

    subgraph "Output"
        J[Frozen Graph]
        K[Audit Trail]
        L[Agent Context]
    end

    A --> C
    B --> D
    C --> E
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J
    J --> K
    J --> L
```

---

## Directory Structure

```
batho_core/
├── context/
│   ├── lsp/
│   │   ├── __init__.py
│   │   ├── client.py           # Universal LSP client
│   │   ├── process_manager.py  # LSP process management
│   │   ├── cache.py            # Response caching
│   │   ├── hasher.py           # Response hashing
│   │   ├── capabilities.py     # Capability negotiation
│   │   ├── adapters/
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # Base adapter interface
│   │   │   ├── python.py       # Pyright adapter
│   │   │   ├── typescript.py   # TSServer adapter
│   │   │   ├── go.py           # gopls adapter
│   │   │   ├── rust.py         # rust-analyzer adapter
│   │   │   ├── java.py         # JDT LS adapter
│   │   │   └── cpp.py          # clangd adapter
│   │   └── containers/
│   │       ├── registry.yaml   # LSP version registry
│   │       ├── build/
│   │       │   └── build_lsp_container.py
│   │       └── verify/
│   │           └── verify_container_integrity.py
│   ├── graph.py                # Modified InMemoryGraph
│   └── merger.py               # AST+LSP merge engine
├── audit/
│   ├── __init__.py
│   ├── merkle.py               # Merkle tree implementation
│   ├── time_travel.py          # Context reconstruction
│   ├── reports.py              # Audit report generation
│   └── storage.py              # Audit data storage
└── graph/
    ├── __init__.py
    ├── serializer.py           # Graph serialization
    └── frozen_format.py        # Frozen graph format
```

---

## Integration Points

### With Existing Batho Components:

1. **Tree-sitter Integration**: `batho_core/context/` extended with LSP submodules
2. **Graph System**: `InMemoryGraph` modified for synchronous injection
3. **Config System**: Extended to support LSP configuration
4. **CLI**: New commands for cache management, audit reports

### External Integrations:

1. **Container Runtime**: Docker/Podman or Nix daemon
2. **LSP Binaries**: 35+ language servers in containers
3. **Version Control**: Git for source versioning and audit trail
4. **Storage**: Local filesystem + optional distributed cache

---

## Security Considerations

1. **Hermetic Execution**: No access to host machine environment
2. **Immutable Binaries**: SHA256 verification prevents tampering
3. **Audit Trail**: Complete cryptographic proof of every run
4. **No Network**: LSP containers should not make external network calls
5. **Resource Limits**: CPU/memory constraints on LSP processes

---

## Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Cold Start | < 30s | First run with no cache |
| Warm Start | < 5s | With frozen graph cache |
| LSP Resolution | < 500ms/symbol | For symbols in scope |
| Cross-File | < 2s/file | Dependency resolution |
| Graph Freeze | < 1s/1000 nodes | Serialization speed |
| Graph Load | < 500ms/1000 nodes | Deserialization speed |

---

**Document Version**: 1.0  
**Last Updated**: 2026-03-31
