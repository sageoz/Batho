# BSG Autoresearch v1

Standalone subsystem that mines deterministic framework conventions from multi-language OSS repos and iteratively compiles `bsg-plugin.v1` YAML rules into Batho with metric-gated keep/revert commits.

## Quick Start

```bash
cd BSGautoresearch

# Optional but recommended: enable OpenRouter LLM signal augmentation
export OPENROUTER_API_KEY=your_key_here

# 1. Prepare: clone repos, compute baseline
python prepare.py

# 2. Train: mine conventions, generate candidate plugin
python train.py

# 3. Run full loop: propose -> evaluate -> keep/revert
python run_loop.py --max-iterations 10
```

Default loop count is read from `config/system.yaml` via `max_iterations`.
CLI `--max-iterations` overrides the config value for a run.

## Structure

```
BSGautoresearch/
  README.md              # This file
  program.md             # Mutable strategic instructions for loop
  prepare.py             # Immutable bootstrap + baseline
  train.py               # Candidate generation
  run_loop.py            # Orchestrator: propose -> evaluate -> keep/revert

  config/
    system.yaml          # Paths, limits, execution budgets
    repositories.yaml    # 10 target OSS repos + metadata
    metrics.yaml         # Scoring weights + hard gates

  services/
    config_loader.py     # Load/validate YAML configs
    repo_registry.py     # Train/holdout split
    repo_cloner.py       # Shallow clone/update repos
    repo_filter.py       # Size/file/binary thresholds
    convention_miner.py  # Mine deterministic framework signals
    rule_compiler.py     # Compile signals -> bsg-plugin.v1 YAML
    plugin_validator.py  # Schema + semantic validation
    evaluator.py         # Weighted scoring + hard gates
    git_gate.py          # Commit/revert decisions
    ledger.py            # Append-only iteration state

  generated/
    candidate_plugin.yaml
    accepted/

  state/
    loop_state.json
    metrics_history.jsonl
    decisions.jsonl
```

## Seed Repo Set

| # | Repo | Language | Framework |
|---|------|----------|-----------|
| 1 | pallets/flask | Python | Micro web |
| 2 | tiangolo/fastapi | Python | Async API |
| 3 | expressjs/express | JavaScript | Middleware web |
| 4 | nestjs/nest | TypeScript | DI modular |
| 5 | gin-gonic/gin | Go | Router/middleware |
| 6 | spring-projects/spring-petclinic | Java | Spring MVC |
| 7 | dotnet-architecture/eShopOnWeb | C# | DDD architecture |
| 8 | laravel/laravel | PHP | Eloquent ORM |
| 9 | sinatra/sinatra | Ruby | DSL routing |
| 10 | tokio-rs/axum | Rust | Async tower |

## Scoring

```
score = 0.35*coverage + 0.25*precision_proxy + 0.20*holdout_generalization
      + 0.10*determinism + 0.10*runtime_efficiency
```

Hard gates (all must pass):
- Schema valid against `bsg-plugin-schema-v1.json`
- Deterministic output stable across reruns
- No metric regression on holdout split
- Runtime overhead within cap (<= +20%)
- No rule explosion (<= 30% entity touch ratio)

Metric inputs are empirical (not static proxies):
- Each candidate is evaluated by indexing train + holdout repos with Batho
- Candidate plugin is applied via `apply_rule_plugins`
- Coverage/precision/generalization/runtime are derived from actual run stats

## OpenRouter LLM Client

`config/system.yaml` includes an `llm` block configured for OpenRouter.

- Provider: `openrouter`
- Endpoint: `https://openrouter.ai/api/v1/chat/completions`
- API key source: env var from `llm.api_key_env` (default `OPENROUTER_API_KEY`)

Behavior:
- If API key is present, the loop asks OpenRouter for extra deterministic convention signals.
- Signals are sanitized, deduplicated, and merged with mined deterministic signals.
- If API key is missing or OpenRouter fails, loop continues with deterministic mined signals only.

## Integration

Generated plugin writes to `batho/bsg/plugins/autoresearch/bsg_autoresearch_generated.yaml`.
Batho's existing `rglob("*.yaml")` discovery picks it up automatically. No backward-compatibility shim required.
