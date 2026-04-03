# Built-in BSG Rules as Packaged Internal Plugins (Implementation Plan)

## Goal

Deliver enterprise-grade BSG enrichment through **packaged internal plugins** under Batho runtime modules, with a minimum of **10 built-in plugins**, deterministic execution, and no dependency on workspace-local `rules/`.

## Scope

- Keep plugin loading inside `batho_core` runtime code.
- Preserve existing BSG rule contract and deterministic matching.
- Add built-in plugin packs that can be enabled/disabled through `rules.builtin_plugins`.
- Keep support for custom inline/file rules as overlays.

## Target Internal Layout

```text
batho_core/bsg/
  rules.py                     # orchestrator + registry wiring
  plugins/
    __init__.py
    bsg_core.py
    bsg_security.py
    bsg_data.py
    bsg_api.py
    bsg_reliability.py
    bsg_observability.py
    bsg_performance.py
    bsg_platform.py
    bsg_integration.py
    bsg_compliance.py
```

Each plugin module exposes one provider function returning normalized rule dictionaries.

## Enterprise Built-in Plugin Catalog (10)

1. **bsg_core**  
   Baseline categorization and derivations (`bsg.category`, `bsg.scope_tier`, `bsg.service_tag`).

2. **bsg_security**  
   AuthN/AuthZ, secrets handling, crypto, permission boundaries.

3. **bsg_data**  
   Models, repositories/DAOs, migrations, schema and persistence layers.

4. **bsg_api**  
   Controllers/routes/endpoints, validation/serialization, API boundary logic.

5. **bsg_reliability**  
   Error handlers, retries, circuit-breaker/fallback patterns.

6. **bsg_observability**  
   Logging, tracing, metrics emitters, telemetry adapters.

7. **bsg_performance**  
   Caching, batching, indexing, memoization, bulk-processing code paths.

8. **bsg_platform**  
   Infrastructure/deployment artifacts (K8s, Helm, Docker, IaC).

9. **bsg_integration**  
   External clients/adapters/connectors, queue/event bridge boundaries.

10. **bsg_compliance**  
    PII/regulated domains, audit-sensitive components, policy markers.

## Rule Design Standards

- Prefix rule names by plugin (example: `security-auth-handler`).
- Use `bsg.*` metadata keys only.
- Priority bands:
  - 200–170: hard category/boundary rules
  - 169–130: domain enrichments
  - 129–100: derived metadata helpers
- Keep matches deterministic (`entity_types`, `name_patterns`, `file_patterns`).
- No LLM-dependent behavior in built-ins.

## Incremental Delivery Plan

### Phase 1: Plugin Packaging Foundation

- Create `batho_core/bsg/plugins/` modules.
- Move existing `bsg_core` rules into its plugin module.
- Keep `rules.py` as orchestration/registry entrypoint.
- Acceptance: existing `bsg_core` behavior unchanged.

### Phase 2: Add the 9 New Enterprise Plugins

- Implement providers for each plugin in isolated modules.
- Register all providers in `_BUILTIN_PLUGINS`.
- Set `list_builtin_plugins()` to return all 10 names deterministically.
- Acceptance: all plugin names load without validation errors.

### Phase 3: Configuration and Docs

- Update `README.md` and `batho.yaml.example` with plugin list examples.
- Document recommended enterprise presets (e.g., app team, platform team, compliance scan).
- Acceptance: docs demonstrate selective plugin enablement.

### Phase 4: Test Coverage

- Add targeted tests for:
  - plugin registry exposure (all 10 listed),
  - per-plugin rule loading,
  - representative metadata application,
  - disabled-rule and strict-validation behavior.
- Acceptance: new tests pass; no regressions in current BSG rule tests.

### Phase 5: Rollout and Safety

- Start with default `bsg_core` to avoid metadata-noise regressions.
- Introduce opt-in enterprise plugin presets in docs/config.
- Track rule-application metrics to monitor rule impact.
- Acceptance: deterministic output and stable indexing performance.

## Testing Strategy

- Continue using `tests/core/test_bsg_rules.py` patterns.
- Add parameterized tests per plugin to confirm:
  - plugin can load,
  - at least one rule applies on fixture graph (where applicable),
  - emitted metadata remains namespaced under `bsg.*`.
- Use strict-validation tests to verify unknown plugin handling.

## Backward Compatibility

- Keep current configuration keys unchanged:
  - `rules.enabled`
  - `rules.builtin_plugins`
  - `rules.disabled_rules`
  - `rules.custom_rules_inline`
  - `rules.custom_rules_path`
- Keep default plugin set as `["bsg_core"]`.

## Definition of Done

- 10 built-in enterprise plugins exist as packaged internal modules.
- Registry, docs, and tests cover all plugin names.
- Deterministic rule execution preserved.
- No workspace `rules/` dependency for BSG runtime.
