---
sidebar_position: 10
title: "9. Security & Governance"
description: "Zero-code-execution guarantee, BSG interceptors, and audit logging"
---

# 9. Security & Governance

## 9.1 Security Architecture Overview

Batho's security model is built on a **zero-code-execution guarantee** with defense-in-depth layers spanning static analysis, plugin-based interception, immutable audit trails, and cryptographic integrity verification. The following architecture diagram illustrates the trust boundaries and data flow through each security layer:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Ext["External Boundary"]
        SRC["Untrusted Source Code<br/>(Git Repository)"]
        CFG["batho.yaml / hooks.yaml"]
    end

    subgraph SB["Sandbox Layer"]
        TS["tree-sitter Parser<br/>(Static AST Only)"]
        VAL["Schema Validator<br/>(YAML/JSON/JSON-Schema)"]
    end

    subgraph Core["Batho Core Engine"]
        EX["Extractor<br/>(Symbol Resolution)"]
        CG["Code Graph<br/>(InMemoryGraph)"]
        BSG["BSG Engine<br/>(Compression and Rules)"]
    end

    subgraph Sec["Security Subsystem"]
        INT["BSG Interceptors<br/>(4 Security Plugins)"]
        AUD["Audit Logger<br/>(Structured Events)"]
        CHAIN["Chain of Custody<br/>(SHA-256 Hashes)"]
    end

    subgraph Out["Output Boundary"]
        SNAP["Immutable Snapshots<br/>(.ctn/snapshots/)"]
        CACHE["SQLite Cache<br/>(.ctn/local/cache/)"]
        API["Bridge API / Dashboard<br/>(Opt-in Network)"]
    end

    SRC -->|"Read-only filesystem access"| TS
    CFG -->|"Schema-validated config"| VAL
    TS -->|"AST nodes (no execution)"| EX
    VAL -->|"Validated rules"| BSG
    EX -->|"Entities + Relationships"| CG
    CG -->|"Graph traversal"| BSG
    BSG -->|"Enriched graph"| INT
    INT -->|"Tagged risks / warnings"| AUD
    AUD -->|"Immutable audit entry"| CHAIN
    CHAIN -->|"Snapshot + hash"| SNAP
    BSG -->|"Cached entities"| CACHE
    BSG -->|"REST/MCP (explicit opt-in)"| API

    style Ext fill:#ffebee,stroke:#c62828,stroke-width:2px
    style SB fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Core fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Sec fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Out fill:#e1f5fe,stroke:#0277bd,stroke-width:2px
```

**Figure 12: Security Architecture Overview** - Trust boundaries and data flow through security layers from untrusted input to protected output.

### Trust Boundary Summary

| Boundary | Mechanism | Assurance |
|----------|-----------|-----------|
| **Input** | Read-only filesystem scan | No write access to source |
| **Parsing** | tree-sitter static AST | Zero code execution |
| **Configuration** | JSON-Schema validation | Reject malformed/malicious config |
| **Plugin Execution** | Declarative YAML rules only | No arbitrary code in BSG plugins |
| **Network** | Explicit opt-in per bridge | No outbound by default |
| **Storage** | Local SQLite + JSON files | No cloud exfiltration |

---

## 9.2 Zero-Code-Execution Guarantee

Batho operates entirely via static analysis, ensuring safe operation on untrusted codebases. The following flow diagram details the input sanitization and processing pipeline that maintains this guarantee:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart LR
    A["Input Source"] --> B{"Input Type?"}
    B -->|Source Code| C["tree-sitter Parser"]
    B -->|Config Files| D["YAML/JSON Parser"]
    B -->|Hook Scripts| E["Shell Delegation"]

    C --> F{"AST Constructed?"}
    F -->|Yes| G["Static Analysis Only"]
    F -->|No| H["Parse Error<br/>(Non-fatal)"]

    D --> I{"Schema Valid?"}
    I -->|Yes| J["Load Configuration"]
    I -->|No| K["Config Rejected<br/>(Fatal)"]

    E --> L["User-defined Shell<br/>(User's environment)"]

    G --> M["Safe Processing"]
    J --> M
    L -->|"Isolated from Batho core"| N["External Execution<br/>(Not our guarantee)"]

    style A fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style B fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style C fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style D fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style G fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style J fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style M fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style K fill:#ffebee,stroke:#c62828,stroke-width:2px
    style H fill:#ffebee,stroke:#c62828,stroke-width:2px
    style N fill:#fce4ec,stroke:#c2185b,stroke-width:2px
```

**Figure 13: Zero-Code-Execution Guarantee** - Input sanitization pipeline ensuring safe processing of untrusted code and configurations.

### Processing Guarantees by Input Category

| Input | Processor | Guarantee |
|-------|-----------|-----------|
| Source files | tree-sitter parse only | No execution |
| Config files | YAML/JSON parse + JSON-Schema | Schema validated, no code paths |
| Hook scripts | Shell command delegation | User-defined, auditable, isolated |
| BSG Plugins | Declarative YAML matchers | No imperative logic |

### Security Boundaries

- **Parsing**: No code execution, only syntax tree construction
- **Caching**: SQLite database with parameterized queries (no SQL injection vector)
- **Networking**: Explicit opt-in, no outbound connections by default
- **Storage**: Local filesystem only, no cloud access

---

## 9.3 BSG Interceptor Plugins

Security-focused plugins run during graph construction to detect and tag risks before they enter the compressed output. The interceptor pipeline operates as a non-blocking enricher — detections are tagged, not blocked, allowing the build to continue while surfacing issues.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Input["Graph Input"]
        G["InMemoryGraph<br/>(Entities and Relationships)"]
    end

    subgraph Pipeline["Interceptor Pipeline"]
        direction TB
        P1["bsg_hardcoded_secret_catcher"]
        P2["bsg_auth_boundary_shield"]
        P3["bsg_silent_failure_catcher"]
        P4["bsg_dependency_blast_radius"]
    end

    subgraph Output["Enriched Output"]
        G2["Tagged Graph<br/>(Risk annotations)"]
        EVT["Security Event Stream<br/>(Audit Logger)"]
    end

    G --> P1
    P1 --> P2
    P2 --> P3
    P3 --> P4
    P4 --> G2
    P1 -->|"High-severity alert"| EVT
    P2 -->|"Boundary violation"| EVT
    P3 -->|"Reliability risk"| EVT
    P4 -->|"Architectural risk"| EVT

    style Input fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Output fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style P1 fill:#ffebee,stroke:#c62828,stroke-width:2px
    style P2 fill:#ffebee,stroke:#c62828,stroke-width:2px
    style P3 fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style P4 fill:#fff3e0,stroke:#f57c00,stroke-width:2px
```

**Figure 14: BSG Interceptor Pipeline** - Security plugin pipeline that enriches the graph with risk annotations and emits security events.

### Interceptor Catalog

| Plugin | Detects | Severity | Action |
|--------|---------|----------|--------|
| `bsg_hardcoded_secret_catcher` | API keys, tokens in string literals | **High** | Tag entity + log warning + emit security event |
| `bsg_auth_boundary_shield` | Missing auth decorators on API route handlers | **High** | Tag risk boundary + emit governance event |
| `bsg_silent_failure_catcher` | Bare `except:`, swallowed exceptions | Medium | Tag reliability risk + emit quality event |
| `bsg_dependency_blast_radius` | High fan-out modules (>N dependents) | Low | Tag architectural risk + emit advisory event |

### Interceptor Sequence

The following sequence diagram shows how an entity flows through the interceptor pipeline:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
sequenceDiagram
    participant EX as Extractor
    participant CG as CodeGraph
    participant P1 as SecretCatcher
    participant P2 as AuthShield
    participant P3 as SilentFailure
    participant AUD as AuditLogger
    participant BSG as BSG Engine

    EX->>CG: Register entity "DatabaseConfig.password"
    CG->>P1: Enrich(entity)
    P1->>P1: Match string_literal pattern
    P1->>CG: Tag entity ["security", "secret-exposure"]
    P1->>AUD: Emit security_event{severity: high}
    CG->>P2: Enrich(entity)
    P2->>P2: Check for auth boundary
    P2->>CG: No action (not an API route)
    CG->>P3: Enrich(entity)
    P3->>P3: Check for bare except
    P3->>CG: No action (not a function)
    CG->>BSG: Pass enriched entity to compression
```

**Figure 15: Interceptor Sequence** - Sequence diagram showing how an entity flows through the security interceptor pipeline with enrichment and event emission.

### Plugin Output Schema

```json
{
  "entity_id": "DatabaseConfig.password",
  "entity_type": "variable",
  "tags": ["security", "secret-exposure"],
  "severity": "high",
  "plugin": "bsg_hardcoded_secret_catcher",
  "message": "Hardcoded secret detected in string literal",
  "timestamp": "2026-05-17T14:32:01Z",
  "file_path": "src/config.py",
  "line_number": 42
}
```

---

## 9.4 Audit Logging

All patch operations produce a comprehensive, append-only audit trail. The audit subsystem captures structured events at every phase of the patch lifecycle, enabling post-hoc forensic analysis and compliance reporting.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Sources["Event Sources"]
        CLI["batho CLI Commands"]
        API["Bridge REST API"]
        DASH["Dashboard Actions"]
        HOOK["Git Hook Triggers"]
    end

    subgraph Pipeline["Audit Pipeline"]
        COL["Event Collector<br/>(In-memory buffer)"]
        VAL["Event Validator<br/>(Schema + cardinality)"]
        ENR["Enrichment<br/>(Timestamp + UUID + hash)"]
        STO["Storage Writer<br/>(Append-only files)"]
    end

    subgraph Storage["Audit Storage"]
        OPS["operations.log<br/>(JSON Lines)"]
        SEC["security_events.log<br/>(SIEM-ready)"]
        INT["integrity.log<br/>(SHA-256 chain)"]
    end

    CLI --> COL
    API --> COL
    DASH --> COL
    HOOK --> COL
    COL --> VAL
    VAL --> ENR
    ENR --> STO
    STO --> OPS
    STO --> SEC
    STO --> INT

    style Sources fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Pipeline fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Storage fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style OPS fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style SEC fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style INT fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
```

**Figure 16: Audit Logging Pipeline** - Event collection, validation, enrichment, and storage flow for comprehensive audit trail.

### Audit Event Types

| Event | Fields | Retention |
|-------|--------|-----------|
| `patch_operation_start` | base_snapshot_id, change_count, initiator | 90 days |
| `patch_progress` | processed, total, progress_pct, eta_seconds | 30 days |
| `incremental_patch_complete` | new_snapshot_id, elapsed_seconds, entity_delta | 90 days |
| `security_interceptor_triggered` | plugin, entity_id, severity, message | 1 year |
| `audit_complete` | operation_id, success, metadata_hash | 90 days |
| `api_access` | endpoint, method, client_ip, user_agent | 30 days |

### Audit Log Directory Structure

```
.ctn/local/audit/
├── operations.log          # All patch/index operations
├── security_events.log     # Interceptor + governance events
├── integrity.log          # SHA-256 chain for tamper detection
└── archive/
    ├── operations-2026-04.log.gz
    └── security-2026-04.log.gz
```

### Integrity Chain

Each audit entry includes a chain hash linking to the previous entry, creating a cryptographic tamper-evident log:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
stateDiagram-v2
    [*] --> Entry1: First operation
    Entry1 --> Entry2: chain_hash = SHA256(Entry1)
    Entry2 --> Entry3: chain_hash = SHA256(Entry2)
    Entry3 --> EntryN: chain_hash = SHA256(Entry3)
    EntryN --> [*]: Archive / Retention expiry

    note right of Entry1
        Any modification breaks
        the entire chain downstream
    end note
```

**Figure 17: Integrity Chain** - State diagram showing the cryptographic tamper-evident log structure with SHA-256 hash chaining.

---

## 9.5 Compliance & Chain of Custody

Batho maintains a complete chain of custody for all code intelligence artifacts, enabling regulatory compliance scenarios such as SOC 2, ISO 27001, and internal governance audits.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Create["Artifact Creation"]
        IDX["batho index --root ."]
        SNAP["Snapshot Created<br/>SHA-256(content)"]
        META["Metadata Record<br/>(timestamp, user, command)"]
    end

    subgraph Modify["Patch / Modification"]
        PATCH["batho patch --root ."]
        DELTA["Delta Computed<br/>(file-level hashes)"]
        NEW["New Snapshot<br/>SHA-256(content + parent_hash)"]
    end

    subgraph Verify["Verification"]
        CHK["batho storage verify"]
        HASH["Recompute SHA-256"]
        CMP{"Match?"}
    end

    subgraph Retention["Retention and Disposal"]
        POL["Retention Policy<br/>(snapshot_days, patch_days)"]
        ARCH["Archive to Gzip"]
        DEL["Secure Delete<br/>(cryptographic erase)"]
    end

    IDX --> SNAP
    SNAP --> META
    META -->|"Immutable record"| POL
    PATCH --> DELTA
    DELTA --> NEW
    NEW -->|"Appends to chain"| POL
    POL --> CHK
    CHK --> HASH
    HASH --> CMP
    CMP -->|Yes| ARCH
    CMP -->|No| ALERT["Tamper Alert<br/>(E004: Snapshot mismatch)"]
    ARCH --> DEL

    style Create fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Modify fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Verify fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Retention fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    style SNAP fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style NEW fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style CMP fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style ALERT fill:#ffebee,stroke:#c62828,stroke-width:2px
```

**Figure 18: Chain of Custody Flow** - Artifact lifecycle from creation through modification, verification, and retention with cryptographic integrity checks.

### Compliance Feature Matrix

| Feature | Mechanism | Standard Mapping |
|---------|-----------|-----------------|
| **Immutable Snapshots** | Write-once JSON files with SHA-256 | SOC 2 CC6.1, ISO 27001 A.12.4 |
| **Chain of Custody** | Parent hash linkage across snapshots | SOC 2 CC7.2, ISO 27001 A.12.5 |
| **Integrity Verification** | `batho storage verify --root . --repair` | SOC 2 CC6.7, ISO 27001 A.12.4 |
| **Access Logging** | All API/dashboard access logged | SOC 2 CC6.2, ISO 27001 A.12.4 |
| **Retention Policies** | Configurable `snapshot_days`, `patch_days` | GDPR Article 5(1)(e) |
| **Cryptographic Erasure** | `batho storage cleanup --apply` | GDPR Article 17 |

### Snapshot Integrity Verification

```bash
# Verify all snapshots in the chain
batho storage verify --root . --repair

# Expected output for healthy chain
[INFO] snapshot-v1: SHA-256 verified
[INFO] snapshot-v2: SHA-256 verified (parent: snapshot-v1)
[INFO] snapshot-v3: SHA-256 verified (parent: snapshot-v2)
[SUCCESS] Chain of custody intact: 3 snapshots verified
```

---

## 9.6 Threat Model

The following threat model maps potential risks to Batho components and their mitigations:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart LR
    subgraph Threats["Threat Actors and Vectors"]
        T1["Malicious Source Code<br/>(e.g., __import__ in docstring)"]
        T2["Tampered Config<br/>(e.g., extra YAML tags)"]
        T3["Compromised Plugin<br/>(e.g., malicious .yaml rule)"]
        T4["Man-in-the-Middle<br/>(e.g., API interception)"]
        T5["Insider Threat<br/>(e.g., audit log deletion)"]
    end

    subgraph Mitigations["Batho Mitigations"]
        M1["tree-sitter: static parse only<br/>No eval, no import, no exec"]
        M2["JSON-Schema: strict validation<br/>Reject unknown keys and types"]
        M3["Declarative YAML only<br/>No inline code, no Jinja"]
        M4["Localhost-only by default<br/>TLS opt-in, no external calls"]
        M5["Append-only audit logs<br/>SHA-256 chain, no deletion API"]
    end

    T1 -->|"Exploits parser"| M1
    T2 -->|"Exploits config loader"| M2
    T3 -->|"Exploits plugin engine"| M3
    T4 -->|"Exploits network path"| M4
    T5 -->|"Exploits log management"| M5

    style Threats fill:#ffebee,stroke:#c62828,stroke-width:2px
    style Mitigations fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style T1 fill:#ffebee,stroke:#c62828,stroke-width:2px
    style T2 fill:#ffebee,stroke:#c62828,stroke-width:2px
    style T3 fill:#ffebee,stroke:#c62828,stroke-width:2px
    style T4 fill:#ffebee,stroke:#c62828,stroke-width:2px
    style T5 fill:#ffebee,stroke:#c62828,stroke-width:2px
    style M1 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style M2 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style M3 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style M4 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style M5 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
```

**Figure 19: Threat Model** - Mapping of potential security threats to their corresponding Batho mitigations.

### Risk Register

| Risk ID | Threat | Likelihood | Impact | Mitigation | Residual Risk |
|---------|--------|------------|--------|------------|---------------|
| SEC-001 | Parser exploited by polyglot file | Low | High | tree-sitter sandboxed parse | Low |
| SEC-002 | YAML deserialization attack | Low | High | Safe loader + JSON-Schema | Low |
| SEC-003 | Malicious BSG plugin injection | Low | Medium | Declarative-only rules | Low |
| SEC-004 | Audit log tampering | Low | High | SHA-256 chain + append-only | Very Low |
| SEC-005 | Sensitive data in cache | Medium | Medium | Local SQLite, no cloud sync | Low |

---

## 9.7 Security Configuration Reference

Minimal security-hardened `batho.yaml`:

```yaml
batho_version: "1.0"

indexer:
  max_file_size_kb: 500
  max_workers: 0
  metrics_output: ".ctn/local/metrics/metrics.json"

logging:
  level: INFO
  json_format: true          # Structured logs for SIEM ingestion
  audit_enabled: true         # Enable full audit trail

rules:
  enabled: true
  auto_load_all_plugins: false  # Explicit allowlist only
  builtin_plugins:
    - bsg_hardcoded_secret_catcher
    - bsg_auth_boundary_shield
    - bsg_silent_failure_catcher
    - bsg_dependency_blast_radius

storage:
  retention:
    snapshot_days: 90
    patch_days: 90
    max_snapshots: 500
    max_patches: 5000
    audit_days: 365           # Extended audit retention

bridge:
  enabled: false              # Explicit opt-in for network exposure
  host: "127.0.0.1"          # Bind localhost only
  port: 8080
  auth_required: true        # Require API key for all endpoints
```
