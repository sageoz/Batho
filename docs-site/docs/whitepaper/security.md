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
        CFG["batho.yaml"]
    end

    subgraph SB["Sandbox Layer"]
        TS["tree-sitter Parser<br/>(Static AST Only)"]
        VAL["Schema Validator<br/>(YAML/JSON-Schema)"]
    end

    subgraph Core["Batho Core Engine"]
        EX["Extractor<br/>(Symbol Resolution)"]
        CG["Code Graph<br/>(InMemoryGraph)"]
        BSG["BSG Engine<br/>(Compression and Rules)"]
    end

    subgraph Sec["Security Subsystem"]
        INT["BSG Interceptors<br/>(Security Plugins)"]
        AUD["Audit Logger<br/>(Structured Events)"]
        CHAIN["Chain of Custody<br/>(SHA-256 Hashes)"]
    end

    subgraph Out["Output Boundary"]
        DB["Arrow IPC Artifact<br/>(.batho/artifact/)"]
        CACHE["msgpack Cache<br/>(.batho/cache/)"]
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
    CHAIN -->|"Run + hash"| DB
    BSG -->|"Cached entities"| CACHE

    style Ext fill:#ffebee,stroke:#c62828,stroke-width:2px
    style SB fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Core fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Sec fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Out fill:#e1f5fe,stroke:#0277bd,stroke-width:2px
```

**Figure 9: Security Architecture Overview** - Trust boundaries and data flow through security layers from untrusted input to protected output.

### Trust Boundary Summary

| Boundary | Mechanism | Assurance |
|----------|-----------|-----------|
| **Input** | Read-only filesystem scan | No write access to source code during analysis. |
| **Parsing** | tree-sitter static AST | Zero code execution (no module imports or script evaluations). |
| **Configuration** | JSON-Schema validation | Reject malformed or unauthorized config keys. |
| **Plugin Execution** | Declarative YAML rules only | No custom code paths or script engines permitted. |
| **Storage** | Local Arrow IPC | Localized storage inside `.batho/`, preventing cloud exfiltration. |

---

## 9.2 Zero-Code-Execution Guarantee

Batho operates entirely via static analysis, ensuring safe operation on untrusted codebases. The following flow diagram details the input sanitization and processing pipeline that maintains this guarantee:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart LR
    A["Input Source"] --> B{"Input Type?"}
    B -->|Source Code| C["tree-sitter Parser"]
    B -->|Config Files| D["YAML/JSON Parser"]

    C --> F{"AST Constructed?"}
    F -->|Yes| G["Static Analysis Only"]
    F -->|No| H["Parse Error<br/>(Non-fatal)"]

    D --> I{"Schema Valid?"}
    I -->|Yes| J["Load Configuration"]
    I -->|No| K["Config Rejected<br/>(Fatal)"]

    G --> M["Safe Processing"]
    J --> M

    style A fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style B fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style C fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style D fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style G fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style J fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style M fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style K fill:#ffebee,stroke:#c62828,stroke-width:2px
    style H fill:#ffebee,stroke:#c62828,stroke-width:2px
```

**Figure 10: Zero-Code-Execution Guarantee** - Input sanitization pipeline ensuring safe processing of untrusted code and configurations.

### Processing Guarantees by Input Category

- **Source files**: Passed strictly to tree-sitter. No files are executed, imported, or dynamically run.
- **Config files**: Checked against a JSON-schema. Malformed configurations fail immediately.
- **BSG Plugins**: Declarative selectors match node patterns (e.g. naming conventions, signatures) rather than running python scripts.

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

**Figure 11: BSG Interceptor Pipeline** - Security plugin pipeline that enriches the graph with risk annotations and emits security events.

### Interceptor Catalog

| Plugin | Detects | Severity | Action |
|--------|---------|----------|--------|
| `bsg_hardcoded_secret_catcher` | API keys, tokens in string literals | **High** | Tag entity + log warning + emit security event |
| `bsg_auth_boundary_shield` | Missing auth decorators on API route handlers | **High** | Tag risk boundary + emit governance event |
| `bsg_silent_failure_catcher` | Bare `except:`, swallowed exceptions | Medium | Tag reliability risk + emit quality event |
| `bsg_dependency_blast_radius` | High fan-out modules (>N dependents) | Low | Tag architectural risk + emit advisory event |

---

## 9.4 Audit Logging

All patch operations produce a comprehensive, append-only audit trail in the database if `flags.audit_log_enabled` is set in `batho.yaml`. The audit subsystem captures structured events at every phase of the patch lifecycle, enabling post-hoc forensic analysis and compliance reporting.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Sources["Event Sources"]
        CLI["batho CLI Commands"]
    end

    subgraph Pipeline["Audit Pipeline"]
        COL["Event Collector<br/>(In-memory buffer)"]
        VAL["Event Validator"]
        ENR["Enrichment<br/>(Timestamp + UUID + hash)"]
        STO["Storage Writer<br/>(Append-only Arrow IPC)"]
    end

    subgraph Storage["Audit Storage"]
        AUDIT["run_artifacts table<br/>(Security Detections & Deltas)"]
    end

    CLI --> COL
    COL --> VAL
    VAL --> ENR
    ENR --> STO
    STO --> AUDIT

    style Sources fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Pipeline fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Storage fill:#fff3e0,stroke:#f57c00,stroke-width:2px
```

**Figure 13: Audit Logging Pipeline** - Event collection, validation, enrichment, and storage flow for comprehensive audit trail.

---

## 9.5 Compliance & Cryptographic Verification

Batho maintains a complete chain of custody for all code intelligence artifacts, enabling regulatory compliance scenarios such as SOC 2 and ISO 27001 audits.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#ffebee', 'primaryTextColor': '#c62828', 'primaryBorderColor': '#b71c1c', 'lineColor': '#ef5350', 'secondaryColor': '#f3e5f5', 'tertiaryColor': '#e8f5e9'}}}%%
flowchart TB
    subgraph Create["Artifact Creation"]
        IDX["batho build --root ."]
        SNAP["Run Record Created<br/>SHA-256(content)"]
    end

    subgraph Modify["Patch / Modification"]
        PATCH["batho patch --root ."]
        DELTA["Delta Computed<br/>(file-level hashes)"]
        NEW["New Run Created<br/>SHA-256(content + parent_hash)"]
    end

    subgraph Verify["Verification"]
        CHK["batho fix --dry-run"]
        HASH["Recompute SHA-256"]
        CMP{"Match?"}
    end

    IDX --> SNAP
    PATCH --> DELTA
    DELTA --> NEW
    NEW --> CHK
    CHK --> HASH
    HASH --> CMP
    CMP -->|Yes| OK["Integrity Intact"]
    CMP -->|No| ALERT["Tamper Alert"]

    style Create fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Modify fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style Verify fill:#fff3e0,stroke:#f57c00,stroke-width:2px
```

**Figure 15: Chain of Custody Flow** - Artifact lifecycle from creation through modification, verification, and retention with cryptographic integrity checks.

### Compliance Feature Matrix

| Feature | Mechanism | Standard Mapping |
|---------|-----------|-----------------|
| **Durable Runs** | Run metadata with SHA-256 content hashes | SOC 2 CC6.1, ISO 27001 A.12.4 |
| **Chain of Custody** | Parent run hash linkage across patches | SOC 2 CC7.2, ISO 27001 A.12.5 |
| **Integrity Verification** | `batho fix --dry-run` and `batho fix` | SOC 2 CC6.7, ISO 27001 A.12.4 |

### Running Database Integrity Verification

```bash
# Verify the integrity of the artifact database
batho fix --dry-run

# Expected output for healthy database
[INFO] Arrow database: verified
[INFO] Run history chain: verified
[INFO] Blob contents: verified
[SUCCESS] Database integrity intact: 4 runs verified
```
