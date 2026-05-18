# Scaling and Performance

Guide to scaling the Batho MCP hub for large workspaces.

## Residency Model

The hub uses a **lazy mount + LRU residency** model:

1. Workspaces start in `registered` state (metadata only)
2. On first access, workspace mounts (loads artifacts)
3. When memory pressure, least-recently-used workspaces are evicted
4. Evicted workspaces return to `registered` state

### Memory Budget

| Resident Workspaces | Target RAM |
|---------------------|------------|
| 32 | ≤ 800 MB |
| 64 | ≤ 2 GB |

## Tuning Parameters

### Residency Config

```yaml
residency:
  max_resident_workspaces: 32    # Max in memory
  idle_timeout_seconds: 300      # Evict after idle
  eviction_policy: "lru"         # Strategy
```

### Concurrency Config

```yaml
concurrency:
  global_inflight_limit: 100     # Total concurrent requests
  per_workspace_limit: 20        # Per-workspace limit
```

## Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Cold artifact.get (50k entities) | ≤ 80 ms | First access |
| Warm tool dispatch | ≤ 5 ms | Cached artifacts |
| Cross-search (5 workspaces) | p95 ≤ 150 ms | Warm index |
| Cross-search (50 workspaces) | p95 ≤ 400 ms | Warm index |
| Cold mount | p95 ≤ 250 ms | Registered → Ready |
| LRU eviction cost | ≤ 5 ms | Per evict |
| Startup (200 registered) | ≤ 500 ms | No mounts |

## Benchmarking

Run benchmarks with:

```bash
BATHO_RUN_BRIDGE_BENCH=1 pytest tests/bridge/bench_hub.py -v
```

## Stress Testing

Run stress tests with:

```bash
BATHO_RUN_BRIDGE_STRESS=1 pytest tests/bridge/test_stress_and_resilience.py -v
```

### Stress 1: Concurrent Cross-Search

- 100 concurrent `cross.search` calls
- 3 workspaces
- Assert: No SQLite locks, no double-construction

### Stress 2: Concurrent Artifact Gets

- 1000 concurrent `artifact.get` calls
- 50 workspaces, max 16 resident
- Assert: Residency cap honored, p99 ≤ 1s

### Stress 3: Config Reload

- Config reload while requests in-flight
- Assert: Removed workspaces get clear error

## Discovery Globs

For large-scale discovery:

```yaml
discovery:
  enabled: true
  ctn_dir_globs:
    - "**/.ctn"
    - "*/.ctn"
  exclude_patterns:
    - "**/node_modules/**"
    - "**/venv/**"
    - "**/.venv/**"
```

## Pinning Workspaces

Keep critical workspaces resident:

```yaml
workspaces:
  - id: "critical-service"
    ctn_dir: "/services/critical/.ctn"
    # No special config, but access frequently
```

Frequent access keeps workspace in LRU working set.

## Monitoring

Enable Prometheus metrics:

```bash
curl http://localhost:8765/api/v1/metrics
```

Key metrics:
- `batho_workspaces_resident` — Current resident count
- `batho_artifact_cache_hit_ratio` — Cache efficiency
- `batho_mcp_tool_latency_seconds` — Tool latency histogram
- `batho_evictions_total` — Eviction rate

## Troubleshooting

### High Latency

1. Check resident count: `batho_workspaces_resident`
2. Enable cache stats: `batho_artifact_cache_hit_ratio`
3. Consider increasing `max_resident_workspaces`

### Memory Issues

1. Reduce `max_resident_workspaces`
2. Enable eviction: Set `idle_timeout_seconds`
3. Exclude large workspaces from discovery

### SQLite Locks

1. Reduce `global_inflight_limit`
2. Increase `per_workspace_limit`
3. Check disk I/O performance
