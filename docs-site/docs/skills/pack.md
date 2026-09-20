# Batho Skill Pack

The Batho Skill Pack turns the Batho MCP server from a set of tools into a
workflow: a router skill that keeps the code graph fresh, and a spec-driven
lifecycle (`batho-specs` → `batho-execute` → `batho-review`) whose artifacts are
grounded in the structured graph.

## The five skills

| Skill | Role | Outputs |
|-------|------|---------|
| `batho` | Entry point: answers codebase questions via Batho MCP, ensures the `.batho` artifact exists and is fresh (`batho build` / `batho patch`), routes to the lifecycle skills | — |
| `batho-setup` | Installation + MCP registration + pack install. No building, no queries | configured MCP + installed pack |
| `batho-specs` | Research → planning → **user approval** → grounded specification | `batho-specs/NN-<name>/specs_<name>.md` |
| `batho-execute` | Loads spec(s), writes graph-ordered `plan_<name>.md`, implements with pre/post-edit grounding | implemented tasks + verification log |
| `batho-review` | Verifies implementation against the spec's graph citations | `review_<name>.md` (PASS/GAPS) |

## Install

```bash
# from the Batho repo (or after `uv tool install batho`, fetch the pack)
python skills/batho-setup/scripts/install_pack.py --agent cursor   # one agent
python install_pack.py --all                                       # every known agent
python install_pack.py --all --global                              # ~/. agents' global paths
python install_pack.py --all --remove                              # uninstall
```

Per-agent discovery paths: see `skills/batho-setup/references/agent-matrix.md`.
The vendor-neutral `.agents/skills/` path covers Cursor, Copilot, Codex, Gemini
CLI, OpenCode, and Devin; Claude Code and Windsurf need their native mirrors
(installed automatically).

Claude Code users can install everything (MCP server + skills) in one step via
the plugin bundle in `.claude-plugin/`.

## The workflow

```
batho            ensure artifact exists & fresh (build / patch / batho_status)
   │
batho-specs      research → plan → USER APPROVAL → batho-specs/01-<name>/specs_<name>.md
   │             (every claim cites graph entity_id + relationship + file:line)
   ▼
batho-execute    plan_<name>.md (graph-ordered tasks) → implement → delta-verify
   │
   ▼  (on request)
batho-review     review_<name>.md — per-criterion PASS/GAPS, dangling refs, orphans
```

- Specs are **grounded truth**: the Current-Behavior table cites `entity_id` +
  `file:line` for every row; blast radius and coverage sections are computed
  from the graph, not guessed.
- Two human gates: approval before the spec file is written, review offer after
  execution. Nothing auto-executes.
- All three artifacts live in the workspace under `batho-specs/NN-<name>/`.

## Manual invocation

| Agent | How |
|-------|-----|
| Claude Code | `/batho-specs`, `/batho-execute`, `/batho-review` (or automatic by description) |
| Cursor / Codex / Gemini CLI / OpenCode | mention the skill or rely on description-based activation |
| Devin | skills auto-discovered from `.agents/skills/` |
| Any agent without skill support | the SKILL.md bodies are plain Markdown — paste the relevant workflow |

## Token cost

Always-on cost is 5 skill descriptions (~100 tokens each ≈ 500 tokens). Bodies
load only when a skill triggers (progressive disclosure); references load only
when a workflow needs them.
