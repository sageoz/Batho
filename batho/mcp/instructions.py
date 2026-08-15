"""Server instructions text injected via MCP initialize response."""

INSTRUCTIONS = """\
# Batho MCP — Code Graph Intelligence

Prefer Batho tools over grep/read for structural code questions. Batho reads pre-built Arrow IPC artifacts with zero-copy memory-mapped I/O for sub-millisecond query latency.

## Prompts
Batho provides 7 workflow-specific prompts that guide tool selection and prevent hallucination:
- explore_codebase — onboarding for unfamiliar codebases
- understand_function — deep-dive a specific function/class
- analyze_file — understand a file's structure and dependencies
- trace_dependency — trace how X reaches Y
- review_changes — review what changed in latest patch
- impact_analysis — "what breaks if I change X?"
- architecture_overview — quick high-level walkthrough

Use prompts when available — they include explicit tool routing and negative guidance.

## Repo management
- "What repos are available?" → list_repos
- "Add repo X at path Y" → add_repo(name, path)
- "Remove repo X" → remove_repo(name)
- Query a specific repo → pass repo="name" to any query tool
- If repo is omitted, the first registered repo is used as default

## Tool selection
- Architecture / "what does this codebase do?" → graph_overview FIRST
- "What's in file X?" → get_file_graph
- "What calls X?" / "What breaks if I change X?" → get_entity
- "How does X reach Y?" → trace_path
- "Find functions named X" → search_entities
- Filtered graph query → graph_query
- "What changed since last build/patch?" → get_delta

## What NOT to do
- Do NOT use grep, read, or file_search for structural code questions — Batho tools are faster and more accurate.
- Do NOT call graph_query or get_file_graph before graph_overview on unfamiliar codebases.
- Do NOT use graph_query for single-entity lookup — use get_entity instead.
- Do NOT use graph_query for name search — use search_entities instead.
- Do NOT use get_entity to search — use search_entities for name-based lookup.
- Do NOT use get_entity for path tracing — use trace_path instead.
- Do NOT manually grep for call chains — trace_path uses BFS on the pre-built graph.
- Do NOT re-scan the entire codebase after a patch — use get_delta for node-level changes.
- Do NOT pass backslashes in file paths — use forward slashes.

## Workflow chaining
- "How does authentication work?": graph_overview → search_entities("auth") → get_entity → trace_path
- "What changed?": get_delta → get_entity for each changed node
- "What breaks if I change X?": search_entities("X") → get_entity(id) → trace_path
- "What's in file X?": get_file_graph → get_entity for key entities

## Error recovery
- If a tool returns an error, check the `hint` field in structuredContent for actionable next steps.
- If repo is not found, call list_repos to see available repos.
- If entity is not found, use search_entities to find the correct entity_id.
- If no path is found, try increasing max_depth or verify entity_ids via search_entities.
- If no patch runs are found, run 'batho patch --root <path>' first.

## Tool availability
Some administrative tools (batho_build, batho_export, batho_load, batho_gc) are
disabled by default and will NOT appear in your tool list. This is intentional —
they are expensive or administrative operations that should run in the terminal
or CI, not mid-conversation. This matches the Sourcegraph/Cursor/CodeGraph pattern
where indexing is a background/automatic process and the agent is a pure consumer.
- If a repo has no artifact: tell the user to run `batho build --root <path>` in their terminal.
- If the artifact is stale and batho_patch is available: call batho_patch.
- If the artifact is corrupted and batho_fix is available: call batho_fix.
- Do NOT attempt to call tools that are not in your tool list.
- Users can enable disabled tools via batho.yaml (mcp.tools.disabled: []) or
  `batho mcp --enable-tool <tool_name>`.

## Tips
- Start with list_repos to see available repos.
- Start with graph_overview for unfamiliar codebases.
- Use response_format: "summary" for orientation, "concise" for queries, "detailed" for deep dives.
- Check pagination hints before follow-up questions.
- Entity IDs from results can be passed to get_entity and trace_path.
- After `batho patch`, call get_delta to see what changed. The graph is already updated — no restart needed.
"""
