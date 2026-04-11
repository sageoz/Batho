# BSG Autoresearch — Program (Mutable Strategic Instructions)

## Objective

Continuously improve BSG plugin rules by mining deterministic framework
conventions from a curated set of OSS repositories and compiling them
into `bsg-plugin.v1` YAML with metric-gated keep/revert commits.

## Loop Contract

1. **Prepare** — clone/update repos, compute baseline metrics.
2. **Train** — mine conventions from train split, emit candidate plugin.
3. **Evaluate** — score candidate on train + holdout.
4. **Gate** — keep only if strictly better than best and all hard gates pass.
5. **Repeat** until iteration budget exhausted or no improvement for N iters.

## Mutation Policy

- The loop mutates the Batho repo working tree directly.
- Accepted plugins are committed; rejected candidates are reverted via `git restore`.
- Every decision is append-only logged to `state/decisions.jsonl`.

## Priority Signals to Mine

- Framework-specific naming conventions (decorators, middleware chains, DI patterns).
- File-level structural motifs (controller/model/service layout).
- Cross-entity relationship patterns (route→handler, model→migration).
- Tag clustering from directory proximity and import graphs.
