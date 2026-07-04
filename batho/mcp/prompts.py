"""Batho MCP Prompts — workflow-specific prompt templates for agent onboarding.

Each prompt provides explicit tool routing, negative guidance to prevent
hallucination, and multi-message conversations that guide agents through
optimal tool sequences.
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.prompts import Message


def register_prompts(app: FastMCP) -> None:
    """Register all Batho MCP prompts on the FastMCP app."""

    @app.prompt
    def explore_codebase(repo: str = "", focus: str = "architecture") -> list[Message]:
        """Onboarding prompt for exploring an unfamiliar codebase using Batho's code graph.

        Use this when you need to understand a codebase's structure, architecture,
        or key components. This prompt guides you through the optimal tool sequence.

        Args:
            repo: Name of the registered repo to explore. If empty, uses the default repo.
            focus: What to focus on: "architecture" (default), "dependencies", "entry_points", "communities".
        """
        repo_arg = f'repo="{repo}"' if repo else 'repo=<default>'
        return [
            Message(
                f"You are exploring a codebase using Batho's code graph intelligence. "
                f"Follow these steps in order:\n\n"
                f"1. Call list_repos to see available repos\n"
                f"2. Call graph_overview({repo_arg}, response_format='summary') for a high-level overview\n"
                f"3. Based on the overview, call graph_query({repo_arg}, entity_types=['FUNCTION','CLASS'], limit=50) "
                f"to see the main entities\n"
                f"4. For {focus}: use get_file_graph on files mentioned in the overview\n\n"
                f"Do NOT use grep, read, or file_search tools — Batho's graph tools are faster and more accurate "
                f"for structural questions. Do NOT skip graph_overview — it provides community summaries that "
                f"give context for all subsequent queries."
            ),
            Message(
                "I'll start by listing repos, then get an overview, then drill into specifics. "
                "Let me begin with list_repos and graph_overview.", role="assistant"
            ),
        ]

    @app.prompt
    def understand_function(function_name: str, repo: str = "") -> list[Message]:
        """Deep-dive into a specific function, class, or method using the code graph.

        Use this when you need to understand what a function does, what calls it,
        what it calls, and where it's defined. This is the primary prompt for
        answering "what does X do?" or "how does X work?" questions.

        Args:
            function_name: Name of the function/class/method to investigate.
            repo: Name of the registered repo. If empty, uses the default repo.
        """
        repo_arg = f', repo="{repo}"' if repo else ''
        return [
            Message(
                f"You are investigating the function/class '{function_name}' using Batho's code graph.\n\n"
                f"Follow these steps:\n"
                f"1. Call search_entities(query='{function_name}'{repo_arg}) to find matching entities\n"
                f"2. From the search results, pick the most relevant entity_id\n"
                f"3. Call get_entity(entity_id=<id>{repo_arg}, response_format='detailed') for full details\n"
                f"4. Call trace_path(source_entity_id=<id>, target_entity_id=<caller_id>{repo_arg}) "
                f"to trace dependencies\n\n"
                f"Tools to use: search_entities then get_entity then trace_path\n"
                f"Do NOT use grep or read — search_entities is faster and returns structured results "
                f"with entity_ids that can be passed directly to get_entity and trace_path."
            ),
            Message(
                f"I'll search for '{function_name}', then get its details and trace its dependencies.",
                role="assistant"
            ),
        ]

    @app.prompt
    def analyze_file(file_path: str, repo: str = "") -> list[Message]:
        """Analyze a single file's structure, entities, and cross-file dependencies.

        Use this when you need to understand what's in a specific file — its functions,
        classes, imports, and how it connects to the rest of the codebase.

        Args:
            file_path: Path to the file (relative to repo root, forward slashes).
            repo: Name of the registered repo. If empty, uses the default repo.
        """
        repo_arg = f', repo="{repo}"' if repo else ''
        return [
            Message(
                f"You are analyzing the file '{file_path}' using Batho's code graph.\n\n"
                f"Follow these steps:\n"
                f"1. Call get_file_graph(file_path='{file_path}'{repo_arg}, response_format='concise') "
                f"to get all entities and relationships in the file\n"
                f"2. For any entity you want to deep-dive: call get_entity(entity_id=<id>{repo_arg})\n"
                f"3. To see what depends on this file: call graph_query(file_path='{file_path}'{repo_arg})\n\n"
                f"Tools to use: get_file_graph then get_entity\n"
                f"Do NOT use read or grep — get_file_graph returns all entities, relationships, "
                f"and cross-file references in a single call with token-optimized markdown."
            ),
            Message(
                f"I'll get the file graph for '{file_path}', then drill into specific entities.",
                role="assistant"
            ),
        ]

    @app.prompt
    def trace_dependency(source: str, target: str, repo: str = "") -> list[Message]:
        """Trace the dependency path from one entity to another.

        Use this when you need to answer "how does X reach Y?" or "what's the
        call chain from A to B?" This finds the shortest path in the code graph.

        Args:
            source: Name of the starting function/class.
            target: Name of the ending function/class.
            repo: Name of the registered repo. If empty, uses the default repo.
        """
        repo_arg = f', repo="{repo}"' if repo else ''
        return [
            Message(
                f"You are tracing a dependency path from '{source}' to '{target}' using Batho's code graph.\n\n"
                f"Follow these steps:\n"
                f"1. Call search_entities(query='{source}'{repo_arg}) to find the source entity_id\n"
                f"2. Call search_entities(query='{target}'{repo_arg}) to find the target entity_id\n"
                f"3. Call trace_path(source_entity_id=<source_id>, target_entity_id=<target_id>{repo_arg})\n\n"
                f"Tools to use: search_entities (twice) then trace_path\n"
                f"Do NOT manually grep for call chains — trace_path uses BFS on the pre-built graph "
                f"and returns the shortest path in milliseconds."
            ),
            Message(
                f"I'll search for both entities, then trace the path between them.",
                role="assistant"
            ),
        ]

    @app.prompt
    def review_changes(repo: str = "", change_kind: str = "") -> list[Message]:
        """Review what changed in the latest batho patch run.

        Use this after running 'batho patch' to understand what was added, removed,
        modified, or renamed in the codebase. This is critical for code review and
        impact assessment workflows.

        Args:
            repo: Name of the registered repo. If empty, uses the default repo.
            change_kind: Filter to a specific kind: "added", "removed", "modified", "renamed". Empty = all.
        """
        repo_arg = f'repo="{repo}"' if repo else ''
        kind_arg = f', change_kind="{change_kind}"' if change_kind else ''
        return [
            Message(
                f"You are reviewing code changes from the latest batho patch run.\n\n"
                f"Follow these steps:\n"
                f"1. Call get_delta({repo_arg}{kind_arg}) to see what changed\n"
                f"2. For each changed entity of interest: call get_entity(entity_id=<id>{repo_arg}) "
                f"to see current state\n"
                f"3. Call graph_overview({repo_arg}) to see if community structure shifted\n\n"
                f"Tools to use: get_delta then get_entity then graph_overview\n"
                f"Do NOT re-scan the entire codebase — get_delta returns node-level changes "
                f"(added/removed/modified/renamed) from the patch run. The graph is already updated."
            ),
            Message(
                "I'll check the delta from the latest patch, then investigate specific changed entities.",
                role="assistant"
            ),
        ]

    @app.prompt
    def impact_analysis(entity_name: str, repo: str = "") -> list[Message]:
        """Analyze the blast radius of changing a specific function/class.

        Use this when you need to answer "what breaks if I change X?" or "what
        depends on X?" This traces all incoming dependencies to the entity.

        Args:
            entity_name: Name of the function/class/method to analyze.
            repo: Name of the registered repo. If empty, uses the default repo.
        """
        repo_arg = f', repo="{repo}"' if repo else ''
        return [
            Message(
                f"You are performing impact analysis for '{entity_name}' using Batho's code graph.\n\n"
                f"Follow these steps:\n"
                f"1. Call search_entities(query='{entity_name}'{repo_arg}) to find the entity\n"
                f"2. Call get_entity(entity_id=<id>{repo_arg}, response_format='detailed') — "
                f"check the 'Incoming' section for all callers/dependents\n"
                f"3. For each caller: call trace_path(source_entity_id=<caller_id>, "
                f"target_entity_id=<entity_id>{repo_arg}) to understand the dependency chain\n"
                f"4. Call get_file_graph(file_path=<file>{repo_arg}) to see co-located dependencies\n\n"
                f"Tools to use: search_entities then get_entity then trace_path then get_file_graph\n"
                f"Do NOT use grep to find references — get_entity returns all incoming relationships "
                f"(CALLS, IMPORTS, USES, REFERENCES) in a single call with file locations."
            ),
            Message(
                f"I'll find the entity, check its incoming dependencies, and trace impact paths.",
                role="assistant"
            ),
        ]

    @app.prompt
    def architecture_overview(repo: str = "") -> str:
        """Get a high-level architecture walkthrough of a codebase.

        Use this when you need a quick orientation to an unfamiliar codebase.
        Returns a single message that guides the agent to use graph_overview
        with summary format for the most token-efficient orientation.

        Args:
            repo: Name of the registered repo. If empty, uses the default repo.
        """
        repo_arg = f'repo="{repo}"' if repo else ''
        return (
            f"You are performing an architecture overview of a codebase using Batho.\n\n"
            f"Call graph_overview({repo_arg}, response_format='summary') — this returns:\n"
            f"- Entity counts by type (functions, classes, modules)\n"
            f"- Relationship breakdown (CALLS, IMPORTS, USES, etc.)\n"
            f"- Community summaries (GraphRAG-inspired clusters of related code)\n"
            f"- File list with entity counts\n\n"
            f"This is the most token-efficient way to understand a codebase (~200-500 tokens).\n"
            f"Do NOT call graph_query or get_file_graph first — always start with graph_overview.\n"
            f"After the overview, use search_entities to find specific functions, or get_file_graph "
            f"to drill into a specific file mentioned in the community summaries."
        )
