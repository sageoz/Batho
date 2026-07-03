"""Server instructions text injected via MCP initialize response."""

INSTRUCTIONS = """\
# Batho MCP — Code Graph Intelligence

Prefer Batho tools over grep/read for structural code questions.

## Tool selection
- Architecture / "what does this codebase do?" → graph_overview FIRST
- "What's in file X?" → get_file_graph
- "What calls X?" / "What breaks if I change X?" → get_entity
- "How does X reach Y?" → trace_path
- "Find functions named X" → search_entities
- Filtered graph query → graph_query
- "What changed since last build/patch?" → get_delta

## Tips
- Start with graph_overview for unfamiliar codebases.
- Use response_format: "summary" for orientation, "concise" for queries, "detailed" for deep dives.
- Check pagination hints before follow-up questions.
- Entity IDs from results can be passed to get_entity and trace_path.
- After `batho patch`, call get_delta to see what changed. The graph is already updated — no restart needed.
"""
