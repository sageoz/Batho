# Design Specification and Implementation Plan for Batho Structured Graph (BSG)

## 1. Overview and Goals

Batho Structured Graph (BSG) is a next‑generation, multi-layer code knowledge graph optimized for both **agentic workflows** and **human, specs‑driven development** over large, polyglot, multi-service codebases. It builds on Batho’s existing AST-based `InMemoryGraph`, LegacyMap, TimeMachine snapshots/patches, and stack detection modules to provide a semantically rich, navigable, and scalable representation of software systems.[^1][^2][^3][^4]

### 1.1 Objectives

- Provide an **agent-optimized representation** that exposes the most relevant entities and relationships for multi-hop reasoning, code localization, and impact analysis while respecting token and latency constraints.[^5][^6]
- Enable **human-centric navigation**: high-level architectural views, semantic search, impact graphs, and test/config/infrastructure linkages for specs-driven development.
- Support **multi-repo, multi-service federated graphs** to model microservices, shared libraries, infra and data contracts as one navigable system.[^7]
- Implement a **two-layer architecture**:
  - **Layer 1: Structural Skeleton** — deterministic, LLM-free graph built from Batho core.
  - **Layer 2: Semantic Infusion** — selective LLM augmentation on anchor nodes using snapshot-aware delta refresh.
- Maintain **high indexing throughput and low query latency** for large codebases and regularly changing monorepos (100k+ entities, tens of services).[^8]

***

## 2. Landscape and Design Requirements

### 2.1 Related Work and Limitations

**Semantic Code Graph (SCG)** models detailed abstract code dependencies closely tied to source and improves software comprehension versus classical call and collaboration graphs, but focuses primarily on comprehension and not on LLM agent navigation or multi-service federation.[^9][^10]

**Structural-Semantic Code Graph (SSCG)** extends dependency graphs with semantic similarity edges and multi-level abstractions, improving retrieval-augmented code generation and repository-level completion, but does not directly expose agent-facing tools or snapshot-aware incremental enrichment.[^7]

**LocAgent** introduces a heterogeneous code graph plus three tools (`SearchEntity`, `TraverseGraph`, `RetrieveEntity`) to support LLM agents doing code localization with type-aware, multi-hop BFS traversal.[^5][^8]

**CodeCompass** exposes structural code dependencies (`IMPORTS`, `INHERITS`, `INSTANTIATES`) as a navigation tool for coding agents and identifies the “navigation paradox”: once retrieval is solved, agents fail due to poor salience and navigation support.[^6]

**GraphRAG / Multi-Agent GraphRAG / Graph-Code** show that graph-structured context significantly beats flat vector RAG for complex questions and code generation, by translating natural language queries into graph queries (e.g., Cypher) and aggregating multi-hop subgraphs.[^11][^12][^13]

**CodeGraph-like tools** (e.g., semantic code graphs for Rust) combine AST, LSP, enrichment and embeddings, and often provide tiered indexing (fast vs. rich) to trade off speed and depth.[^1]

**Key gaps BSG should address**:
- Most models lack **first-class test/config/infra/doc linkages** and change velocity, which are crucial for agents modifying real systems.[^9]
- Limited support for **multi-repo/multi-service federation** as a single graph for agent navigation.
- LLM enrichment is either absent or performed naïvely, without **anchor-node selection and snapshot delta updates**.
- Tool APIs for agents are often fragmented; LocAgent is a good starting point but not tailored to specs-driven development or federated systems.[^5]

### 2.2 Requirements

1. **Expressiveness**: Represent code entities, relationships, tests, configs, infra, docs, and cross-service links in a single, heterogeneous graph.
2. **Agent suitability**: Provide small, stable tool APIs that let agents:
   - Search entities semantically.
   - Retrieve structural neighborhoods in a single call.
   - Traverse type-aware subgraphs with bounded hops.
   - Retrieve code/spec snippets on demand.[^6][^5]
3. **Human usability**: Support hierarchical zooming (system → service → module → file → symbol), semantic search, impact radius queries, and visualizations.
4. **Scalability**: Handle ≥100k entities and ≥1M relationships per federation with:
   - Indexing in minutes, incremental updates in seconds.
   - Query latency sub-100ms for common operations on hot caches.[^8][^1]
5. **LLM efficiency**: Minimize total tokens and calls via:
   - Anchor-node selection (top ~10–15% entities).[^7]
   - Signature-first prompting (no full file content).
   - Snapshot-delta recalculation for changed files only.
6. **Polyglot and multi-service**: Leverage Batho’s existing multi-language AST extractors and stack detector to keep graph language-agnostic and service-aware.[^2][^4]

***

## 3. BSG Conceptual Model

### 3.1 Layer 1: Structural Skeleton (LLM-Free)

Layer 1 extends Batho’s `Entity`/`Relationship` model with additional dimensions and derived relationships.[^4][^2]

#### 3.1.1 Node Schema

Each node is a **BSGNode**:

```text
BSGNode {
  id:               string          # stable hash based on type, name, file, line range
  type:             EntityType      # from Batho schema (class, function, method, file, test, config, infra, doc, etc.)
  name:             string
  file:             string          # normalized, repo-relative path
  start_line:       int
  end_line:         int
  signature:        string          # function/class signature or canonical descriptor

  # Structural metadata
  scope_tier:       GLOBAL | MODULE | CLASS | LOCAL
  category:         SOURCE | TEST | CONFIG | DOC | INFRA | DATA | SCHEMA
  service_tag:      string | null   # microservice or bounded context id
  language:         string          # from LanguageDetector

  # Evolution and importance
  change_velocity:  float           # computed per entity using TimeMachine staleness
  dependency_weight:int             # in-degree centrality proxy (number of inbound edges)
  last_modified_at: datetime
  snapshot_id:      string          # TimeMachine snapshot identifier
}
```

**How it is derived**:
- `scope_tier` from nesting (top-level file entities, module-level, class members, locals) based on AST location.[^5]
- `category` via FileCategorizer and extension rules (e.g., `tests/`, `docs/`, `*.tf`).[^2]
- `service_tag` by StackDetector using framework/build tool detection and repo layout (e.g., `services/auth`, `backend/api`).[^2]
- `change_velocity` from TimeMachine’s staleness computation, normalized per entity.[^2]
- `dependency_weight` as count of inbound edges of structural types (`CALLS`, `IMPORTS`, `INHERITS`, etc.).[^9]

#### 3.1.2 Relationship Schema

Extend Batho’s `RelationshipType` enumeration with additional, deterministic relationship types:

- **Structural** (existing and extended): `CALLS`, `CALLED_BY`, `IMPORTS`, `IMPORTED_BY`, `INHERITS`, `IMPLEMENTS`, `OVERRIDES`, `DEFINES`, `USES`, `READS`, `WRITES`.[^1][^9]
- **Testing**:
  - `OWNS_TEST` (source symbol → test symbol) via filename patterns and AST assertions.
  - `TESTS` (test function → source symbol it touches) via call graph.[^5]
- **Configuration**:
  - `CONFIG_GOVERNS` (config entity → code entity that reads it) via key-name and path matching.
  - `FEATURE_FLAG_CONTROLS` (flag definition → guarded code node) via conditional patterns.
- **Documentation**:
  - `DOC_COVERS` (doc section → entities referenced in backticks or links).[^1]
- **Infrastructure / Data**:
  - `INFRA_PROVISIONS` (HCL/Terraform resource → deployed service) via naming conventions, tags.
  - `SCHEMA_GOVERNS` (DB schema/table → code entities reading it) via query string parsing.
- **Change Coupling**:
  - `CHANGE_COUPLED` (entity A ↔ entity B) if they co-occur in the same patch beyond a threshold over N patches.[^6]
- **Service Boundaries**:
  - `STACK_BOUNDARY` for calls or data flows that cross `service_tag` or bounded context.

Relationships are represented as:

```text
BSGEdge {
  id:          string
  source_id:   string
  target_id:   string
  type:        RelationshipType
  metadata:    { lineno?: int, confidence?: float, snapshot_id?: string }
}
```

#### 3.1.3 Structural Indexes

BSG builds a multi-dimensional adjacency index to optimize traversal for agents and humans:

```text
BSGIndex {
  nodes_by_id:         dict[id → BSGNode]
  nodes_by_file:       dict[file → list[id]]
  nodes_by_scope:      dict[scope_tier → list[id]]
  nodes_by_service:    dict[service_tag → list[id]]
  nodes_by_category:   dict[category → list[id]]
  inbound_edges:       dict[id → list[BSGEdge]]
  outbound_edges:      dict[id → list[BSGEdge]]
  cross_boundaries:    list[BSGEdge]   # only STACK_BOUNDARY, INFRA_PROVISIONS, SCHEMA_GOVERNS
  hot_nodes:           sorted list[(change_velocity, id)]
}
```

This index avoids repeated graph scans at query time and enables constant or logarithmic-time selection of relevant neighborhoods.[^6][^5]

### 3.2 Layer 2: Semantic Infusion (LLM-Augmented)

Layer 2 enriches a subset of nodes with LLM-generated semantic fields, optimized for cost and latency.

#### 3.2.1 Anchor Node Selection

Anchor nodes are where LLM enrichment is most valuable for both agents and humans. A heuristic score ranks nodes:

```text
anchor_score = 0.6 * norm(dependency_weight)
             + 0.2 * norm(change_velocity)
             + 0.2 * scope_tier_weight
```

- `scope_tier_weight`: GLOBAL > MODULE > CLASS > LOCAL.
- Only top K% nodes (configurable, default 10–15%) per service are selected as anchors.

This mirrors the way SCG/SSCG prioritize key entities and how LocAgent focuses on graph-based localization targets.[^7][^9][^5]

#### 3.2.2 Infusion Prompt Design

For each anchor node, the infusion system constructs a compact prompt:

```text
Node: {name} ({type}) in {file}
Signature: {signature}
Language: {language}
Category: {category}
Service: {service_tag}

Inbound neighbors (names, types): {top_inbound}
Outbound neighbors (names, types): {top_outbound}

Existing docstring (if any): {docstring_or_none}

Task: Return a JSON object with these fields:
- summary: one sentence describing what this entity does.
- intent: one sentence on why this entity exists in the system.
- agent_hint: tips or caveats for an AI agent planning to modify or call this.
- human_nav: how a new developer should interpret and use this entity.
- risk_tag: one of [LOW, MEDIUM, HIGH, CRITICAL] based on coupling and inferred criticality.
- cluster_hint: a short label for the feature/domain this belongs to.
```

This follows emerging practice in structural-semantic code graph work: combining structural context and short semantic text for richer but compact representations.[^12][^7]

#### 3.2.3 Snapshot-Delta Infusion

To keep semantic data fresh without re-infusing the whole graph on each change, BSG ties infusion to TimeMachine snapshots:

1. For a new snapshot `S_n`, compute file-level diffs vs. `S_{n-1}`.
2. Determine affected nodes: any node whose `file` changed or which is structurally linked to changed configs/infra.
3. Restrict infusion to affected anchors (intersection of anchors and affected nodes).
4. Invalidate cached semantic data for those node IDs; re-run infusion only for them.

This is analogous to how lightweight graph-based systems such as LocAgent perform repository-level indexing in seconds and reuse the graph for repeated tasks.[^8][^5]

#### 3.2.4 Semantic Layer Schema

```text
BSGSemantic {
  node_id:      string
  summary:      string
  intent:       string
  agent_hint:   string
  human_nav:    string
  risk_tag:     LOW | MEDIUM | HIGH | CRITICAL
  cluster_hint: string
  infused_at:   datetime
  snapshot_id:  string
  embedding_id: string | null
}
```

### 3.3 Rule Plugin Layer (Deterministic, YAML-Extensible)

To support domain-specific graph enrichment without coupling to workspace-local files, BSG introduces a plugin-based rule layer.

#### 3.3.1 Design Constraints

- Built-in BSG rules MUST be delivered as packaged internal plugins under Batho runtime modules.
- BSG runtime MUST NOT read the root workspace `rules/` directory for graph construction.
- Users MAY define custom BSG rules in `batho.yaml` as inline entries.
- Users MAY define custom BSG rules in external YAML files referenced by `batho.yaml`.
- Rule execution MUST remain deterministic and LLM-free in Layer 1.

#### 3.3.2 Rule Contract

All built-in and custom rules normalize to the same contract:

```text
BSGRule {
  name:        string            # unique rule identifier
  description: string
  priority:    int               # higher priority wins on conflicts
  enabled:     bool
  plugin:      string            # origin plugin

  match: {
    entity_types?:  list[string] # function, class, method, etc.
    name_patterns?: list[string] # glob patterns
    file_patterns?: list[string] # repo-relative glob patterns
  }

  actions: {
    metadata?:         dict[string -> any]
    derive_scope_tier?: bool
    derive_service_tag?: bool
  }
}
```

#### 3.3.3 Configuration Surface

BSG rules are configured from `batho.yaml`:

```yaml
rules:
  enabled: true
  builtin_plugins: [bsg_core]
  disabled_rules: []
  custom_rules_path: ./bsg-rules.yaml
  custom_rules_inline: []
  strict_validation: false
  cache_ttl: 3600
  fail_on_rule_error: false
```

Custom rule file format supports either:

- top-level `rules:` list
- top-level list of rule objects

#### 3.3.4 Merge and Conflict Resolution

BSG merges rule sources in this order:

1. Built-in plugin rules.
2. Inline custom rules from `rules.custom_rules_inline`.
3. File-based custom rules from `rules.custom_rules_path`.

When multiple rules share the same `name`, the later source overrides the earlier one. Final execution order is deterministic and priority-based.

#### 3.3.5 Runtime Integration

Rule execution occurs after structural extraction and import resolution in `CodeGraphIndexer.build_graph`:

1. Load effective rules from plugin registry + user YAML.
2. Match entities using deterministic glob/type filters.
3. Apply metadata enrichment (`bsg.category`, `bsg.scope_tier`, `bsg.service_tag`, cluster tags, etc.).
4. Persist rule execution stats in index metrics for auditability.


---

## References

1. [CodeGraph CLI MCP Server](https://www.mcp-gallery.jp/mcp/github/jakedismo/codegraph-rust) - A high-performance CLI tool that provides semantic code search, advanced architectural analysis, and...

2. [architecture.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/83114871/829b2c93-4a31-479f-8210-60a27b05335e/architecture.md?AWSAccessKeyId=ASIA2F3EMEYE62EGBLU4&Signature=4WVMJF5DWGXCdHVD%2F4bjLqSWtJQ%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEMX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJHMEUCIQCAKwpORt2bpb7XnGJb76VMTmPhFZhGy20OW2NDq%2FXuRwIgen8TZRmUDIGgCBJ5waWvoqe12AMADo0pYM5GdxvjxmAq%2FAQIjv%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FARABGgw2OTk3NTMzMDk3MDUiDDPKZIORtY6Mb7ynESrQBPaDB5T36z2e3M31JlDddbfX1cWmUs8fiGuItWccH%2FikTJJIAT%2FWCWZ%2BdtFFlbIBOnhqrdsg4bEfw8sNldUSd%2Bvvk3Yap51kf4to%2FqfjWbe7ppRxK5LZ7RVjlJE3%2B%2BYirLDwgiaQNV9r%2BvKhvojHIAtGgb7C9S9X2LSPoCa6I2EQMgccKnQl6XETxiuS8qhNQ5eb6qwecnjVt8nRCYmRjJXUv8CDfOrE2mllHI7voo7UZMXOD8sYNvML%2BSXkJoNUFgT7wNEopi9MXBlA%2BZhnUdJhFFTQQWTX5KgLR1CGpgYsnt9x%2BgvWj2alS9xa5Eaul%2Bnf8eTWxAhmnn6POvfbksRAiwKP786HEVJwLe3gEet588kSPFm1WFMF1rbcbN8cja2S1GwhxMzzKbH8BzFwKLJU3XAlc4JhoqsHtFJibTRdk4gsgZFFElJRoktrq1IBj95Su9drZ92SHD3ziTn4xB5egadQUvV%2FV0vgqDq1L5VA9HKMucfolfhFG8w0c%2F5DRuncKZ8bbkJTMXgdK8jUEgRnNb9n7Dj1i9M4oXmIdwHOQfCjZ06XiCIZM8ORr%2B0pYJiAFEZfSD61n6pwbXis2pEkqzTGEVadm1jw4hd64T2k%2B5%2BcxvIZKdvzNgyMz1BTr87Q5%2F01hNW6XXqEv%2BjBxqTmUyN1TzN0nWDaweNefnSRxFvmrU3o2HGPsnf3DXbrR5ZWMIBKgmv8N0UmDNHbiyS9XhhN9d%2FDS9hTV4vnljV5ebxGB%2F%2FQvdqtKjdkW7%2F12mdxwzwEA57sAt1rDVcKFOswncTAzgY6mAGbBBTKrIWE2FYdXgZ4g8hGYKLkTUIiwMeeSdw5fjl4cZK0k06duCi6p1InW%2F%2FehMdSmcNS7vB3K4VGydXtswXTGQRHSmeDnlN1MiIg1ywU4A33gzqcmLH4N%2BFwzVT4L1%2FUSgejHxdmgFKPBgvMgYel86QoxJzNU4kqvst5aaw9hEFg55fECtJXmNB2%2FN8TPp9AarkoeJ5UzQ%3D%3D&Expires=1775251440) - root batho.py 40 entities 2 entrypoint, 38 func if name main sys.exitmain L1-1736 name L1734-1734 ge...

3. [overview.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/83114871/0279cf34-6ba5-4bf8-a931-05dd3fa3bc30/overview.md?AWSAccessKeyId=ASIA2F3EMEYE62EGBLU4&Signature=obiGyjNUfWiPuaJwa0dxPvn9Gvo%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEMX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJHMEUCIQCAKwpORt2bpb7XnGJb76VMTmPhFZhGy20OW2NDq%2FXuRwIgen8TZRmUDIGgCBJ5waWvoqe12AMADo0pYM5GdxvjxmAq%2FAQIjv%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FARABGgw2OTk3NTMzMDk3MDUiDDPKZIORtY6Mb7ynESrQBPaDB5T36z2e3M31JlDddbfX1cWmUs8fiGuItWccH%2FikTJJIAT%2FWCWZ%2BdtFFlbIBOnhqrdsg4bEfw8sNldUSd%2Bvvk3Yap51kf4to%2FqfjWbe7ppRxK5LZ7RVjlJE3%2B%2BYirLDwgiaQNV9r%2BvKhvojHIAtGgb7C9S9X2LSPoCa6I2EQMgccKnQl6XETxiuS8qhNQ5eb6qwecnjVt8nRCYmRjJXUv8CDfOrE2mllHI7voo7UZMXOD8sYNvML%2BSXkJoNUFgT7wNEopi9MXBlA%2BZhnUdJhFFTQQWTX5KgLR1CGpgYsnt9x%2BgvWj2alS9xa5Eaul%2Bnf8eTWxAhmnn6POvfbksRAiwKP786HEVJwLe3gEet588kSPFm1WFMF1rbcbN8cja2S1GwhxMzzKbH8BzFwKLJU3XAlc4JhoqsHtFJibTRdk4gsgZFFElJRoktrq1IBj95Su9drZ92SHD3ziTn4xB5egadQUvV%2FV0vgqDq1L5VA9HKMucfolfhFG8w0c%2F5DRuncKZ8bbkJTMXgdK8jUEgRnNb9n7Dj1i9M4oXmIdwHOQfCjZ06XiCIZM8ORr%2B0pYJiAFEZfSD61n6pwbXis2pEkqzTGEVadm1jw4hd64T2k%2B5%2BcxvIZKdvzNgyMz1BTr87Q5%2F01hNW6XXqEv%2BjBxqTmUyN1TzN0nWDaweNefnSRxFvmrU3o2HGPsnf3DXbrR5ZWMIBKgmv8N0UmDNHbiyS9XhhN9d%2FDS9hTV4vnljV5ebxGB%2F%2FQvdqtKjdkW7%2F12mdxwzwEA57sAt1rDVcKFOswncTAzgY6mAGbBBTKrIWE2FYdXgZ4g8hGYKLkTUIiwMeeSdw5fjl4cZK0k06duCi6p1InW%2F%2FehMdSmcNS7vB3K4VGydXtswXTGQRHSmeDnlN1MiIg1ywU4A33gzqcmLH4N%2BFwzVT4L1%2FUSgejHxdmgFKPBgvMgYel86QoxJzNU4kqvst5aaw9hEFg55fECtJXmNB2%2FN8TPp9AarkoeJ5UzQ%3D%3D&Expires=1775251440) - Generated 2026-04-03T182153.0756160000 TITLE batho - Repository Overview

4. [legacy_map.json](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/83114871/7c2332c3-47ed-4e22-8f80-5a7ccfb8f037/legacy_map.json?AWSAccessKeyId=ASIA2F3EMEYE62EGBLU4&Signature=5NgQuzKB6qWu2%2BWk9TyRWm4VFJc%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEMX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJHMEUCIQCAKwpORt2bpb7XnGJb76VMTmPhFZhGy20OW2NDq%2FXuRwIgen8TZRmUDIGgCBJ5waWvoqe12AMADo0pYM5GdxvjxmAq%2FAQIjv%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FARABGgw2OTk3NTMzMDk3MDUiDDPKZIORtY6Mb7ynESrQBPaDB5T36z2e3M31JlDddbfX1cWmUs8fiGuItWccH%2FikTJJIAT%2FWCWZ%2BdtFFlbIBOnhqrdsg4bEfw8sNldUSd%2Bvvk3Yap51kf4to%2FqfjWbe7ppRxK5LZ7RVjlJE3%2B%2BYirLDwgiaQNV9r%2BvKhvojHIAtGgb7C9S9X2LSPoCa6I2EQMgccKnQl6XETxiuS8qhNQ5eb6qwecnjVt8nRCYmRjJXUv8CDfOrE2mllHI7voo7UZMXOD8sYNvML%2BSXkJoNUFgT7wNEopi9MXBlA%2BZhnUdJhFFTQQWTX5KgLR1CGpgYsnt9x%2BgvWj2alS9xa5Eaul%2Bnf8eTWxAhmnn6POvfbksRAiwKP786HEVJwLe3gEet588kSPFm1WFMF1rbcbN8cja2S1GwhxMzzKbH8BzFwKLJU3XAlc4JhoqsHtFJibTRdk4gsgZFFElJRoktrq1IBj95Su9drZ92SHD3ziTn4xB5egadQUvV%2FV0vgqDq1L5VA9HKMucfolfhFG8w0c%2F5DRuncKZ8bbkJTMXgdK8jUEgRnNb9n7Dj1i9M4oXmIdwHOQfCjZ06XiCIZM8ORr%2B0pYJiAFEZfSD61n6pwbXis2pEkqzTGEVadm1jw4hd64T2k%2B5%2BcxvIZKdvzNgyMz1BTr87Q5%2F01hNW6XXqEv%2BjBxqTmUyN1TzN0nWDaweNefnSRxFvmrU3o2HGPsnf3DXbrR5ZWMIBKgmv8N0UmDNHbiyS9XhhN9d%2FDS9hTV4vnljV5ebxGB%2F%2FQvdqtKjdkW7%2F12mdxwzwEA57sAt1rDVcKFOswncTAzgY6mAGbBBTKrIWE2FYdXgZ4g8hGYKLkTUIiwMeeSdw5fjl4cZK0k06duCi6p1InW%2F%2FehMdSmcNS7vB3K4VGydXtswXTGQRHSmeDnlN1MiIg1ywU4A33gzqcmLH4N%2BFwzVT4L1%2FUSgejHxdmgFKPBgvMgYel86QoxJzNU4kqvst5aaw9hEFg55fECtJXmNB2%2FN8TPp9AarkoeJ5UzQ%3D%3D&Expires=1775251440) - signature isavailableself - bool , name detectbyextension, type function, lines 71, 98 , signature d...

5. [LocAgent: Graph-Guided LLM Agents for Code Localization](https://arxiv.org/html/2503.09089v1)

6. [CodeCompass: Navigating the Navigation Paradox in Agentic Code Intelligence](https://arxiv.org/pdf/2602.20048.pdf)

7. [Structural-Semantic Code Graph (SSCG)](https://www.emergentmind.com/topics/structural-semantic-code-graph-sscg) - SSCG is a heterogeneous, directed and typed code graph that actively encodes structural and semantic...

8. [[PDF] LocAgent: Graph-Guided LLM Agents for Code Localization](https://aclanthology.org/2025.acl-long.426.pdf)

9. [Semantic Code Graph – an information model to facilitate ...](https://arxiv.org/html/2310.02128v2) - We propose the Semantic Code Graph (SCG), an information model that offers a detailed abstract repre...

10. [Semantic Code Graph -- an information model to facilitate software comprehension](http://arxiv.org/abs/2310.02128) - Software comprehension can be extremely time-consuming due to the ever-growing size of codebases. Co...

11. [Multi-Agent GraphRAG: A Text-to-Cypher Framework for ...](https://arxiv.org/html/2511.08274v1) - In this paper we introduce Multi-Agent GraphRAG, a system for natural language querying over propert...

12. [Code Generation with GraphRAG](https://datastax.github.io/graph-rag/examples/code-generation/) - In this notebook, we demonstrate that GraphRAG significantly outperforms standard vector-based retri...

13. [GraphRAG for Devs: Graph-Code Demo Overview](https://memgraph.com/blog/graphrag-for-devs-coding-assistant) - It serves as both a visualization tool for the code graph and an AI assistant. The tool combines the...

