"""Batho MCP Resources — static and dynamic resources for programmatic clients.

Resources provide read-only data that agents can read via URI references.
This complements tools (which perform actions) and prompts (which guide workflows).
"""

from __future__ import annotations

import json

from fastmcp import FastMCP

from batho.core.schemas import EntityType, RelationshipType
from batho.mcp.registry import RepoRegistry


def register_resources(
    app: FastMCP,
    registry: RepoRegistry | None = None,
) -> None:
    """Register all Batho MCP resources on the FastMCP app."""

    @app.resource("batho://schema")
    def schema() -> str:
        """Batho entity types, relation types, and response_format values.

        Returns a JSON document describing the schema of Batho's code graph:
        - Entity types: FUNCTION, CLASS, METHOD, MODULE, VARIABLE, etc.
        - Relation types: CALLS, IMPORTS, USES, REFERENCES, DEFINES, INHERITS, etc.
        - Response formats: summary, concise, detailed
        """
        schema_data = {
            "entity_types": [e.name for e in EntityType],
            "relation_types": [r.name for r in RelationshipType],
            "response_formats": {
                "summary": "~200-500 tokens, high-level overview only",
                "concise": "~50 tokens per entity, minimal detail",
                "detailed": "~150 tokens per entity, full relationships + source",
            },
            "change_kinds": ["added", "removed", "modified", "renamed"],
        }
        return json.dumps(schema_data, indent=2)

    @app.resource("batho://repos")
    def repos() -> str:
        """List all registered Batho repos with their artifact status.

        Returns a JSON array of repos with name, path, has_artifact, and entity_count.
        Similar to the list_repos tool but accessible as a read-only resource.
        """
        if not registry:
            return json.dumps({"error": "No registry configured", "repos": []})
        entries = registry.list_all()
        repos_list = []
        for entry in entries:
            has_art = RepoRegistry.has_artifact(entry)
            repos_list.append({
                "name": entry.name,
                "path": entry.path,
                "has_artifact": has_art,
            })
        return json.dumps({"repos": repos_list, "total": len(repos_list)}, indent=2)
