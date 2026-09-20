"""Server instructions text injected via MCP initialize response."""

INSTRUCTIONS = """\
# Batho MCP — Code Graph Intelligence

Batho serves a precomputed code graph (Arrow IPC artifact). For structural
questions — who calls X, what depends on Y, how A reaches B, architecture,
impact, spec grounding — query Batho tools BEFORE grep/read. Read files only
for editing, or after a graph tool has named the files worth reading.

## Artifact freshness (check first)
- Call batho_status before the first graph query in a session.
- No artifact / stale artifact → tell the user to run `batho build` or
  `batho patch` in the terminal (CLI), then re-check batho_status.
- After any patch, call get_delta to see what changed structurally.
- If batho_patch / batho_build appear in your tool list (Tier-3 enabled),
  you may run them directly; otherwise use the CLI guidance above.

## Feature work flow
For feature/change work, use the Batho skill pack flow:
batho-specs (grounded spec) → batho-execute (plan + implement) →
batho-review (verify). Every claim in a spec cites graph entities.

## Tool selection
- Architecture / "what does this codebase do?" → graph_overview FIRST
- "What's in file X?" → get_file_graph
- "What calls X?" / "What breaks if I change X?" → get_entity
- "How does X reach Y?" → trace_path
- "Find functions named X" → search_entities
- "What does file F depend on?" → file_connectivity
- Filtered graph query → graph_query
- "What changed since last build/patch?" → get_delta / batho_diff
- Artifact/run status → batho_status, batho_list_runs

## Repo management
- "What repos are available?" → list_repos
- "Add repo X at path Y" → add_repo(name, path)
- "Remove repo X" → remove_repo(name)
- Query a specific repo → pass repo="name" to any query tool
- If repo is omitted, the first registered repo is used as default

## Prompts
Batho provides 7 workflow prompts with explicit tool routing:
explore_codebase, understand_function, analyze_file, trace_dependency,
review_changes, impact_analysis, architecture_overview.

## What NOT to do
- Do NOT use grep/read for structural questions — Batho is faster and exact.
- Do NOT call graph_query or get_file_graph before graph_overview on
  unfamiliar codebases.
- Do NOT use graph_query for single-entity lookup — use get_entity.
- Do NOT use graph_query for name search — use search_entities.
- Do NOT manually grep for call chains — trace_path uses BFS on the graph.
- Do NOT re-scan the codebase after a patch — use get_delta.
- Do NOT pass backslashes in file paths — use forward slashes.

## Error recovery
- Tool errors carry a `hint` field in structuredContent — follow it.
- Repo not found → list_repos. Entity not found → search_entities.
- No path found → increase max_depth or verify entity_ids.
- No patch runs → run `batho patch --root <path>` first.

## Tool availability
Tier-3 admin tools (batho_build, batho_export, batho_load, batho_gc) are
disabled by default and will NOT appear in your tool list. Indexing is a
background/CLI process; the agent is a pure consumer. Users can enable them
via batho.yaml (mcp.tools / mcp.toolsets) or `batho mcp --enable-tool <name>`.
Do NOT attempt to call tools that are not in your tool list.

## Tips
- response_format: "summary" for orientation, "concise" for queries,
  "detailed" for deep dives.
- Entity IDs from results can be passed to get_entity and trace_path.
- Check pagination hints (offset/limit) before follow-up questions.
"""
