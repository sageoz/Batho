"""
Cross-file Symbol Resolution using LSP.
"""

import asyncio
from collections import deque
from pathlib import Path
from typing import Dict, List, Set

from batho_core.utils.logging import get_logger
from batho_core.context.schema import Entity, Relationship, RelationshipType
from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.lsp.client import LSPClient
from batho_core.context.lsp.types import TextDocumentIdentifier, Position, Location


class CrossFileResolver:
    """
    Resolves "unresolved" cross-file imports and references using the LSP client.
    """

    def __init__(self, lsp_client: LSPClient):
        self.client = lsp_client
        self.logger = get_logger(__name__, component="cross_file_resolver")

    def resolve_synchronously(self, graph: InMemoryGraph) -> None:
        """Synchronous wrapper for graph indexing pipeline end-step."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self.resolve_async(graph))
        finally:
            loop.close()

    async def resolve_async(self, graph: InMemoryGraph) -> None:
        """
        Find all unresolved relationships and use LSP definition/references 
        to track them across file boundaries.
        """
        self.logger.info("cross_file_resolution_started")
        
        unresolved_rels = [
            rel for rel in graph.relationships 
            if rel.target_id.startswith("unresolved:")
        ]
        
        if not unresolved_rels:
            self.logger.info("no_unresolved_references_found")
            return
            
        if not self.client.negotiator.supports_definition():
            self.logger.warning("lsp_does_not_support_definition_resolution")
            return
            
        success_count = 0
        
        # Basic BFS logic for cross-file imports
        for rel in unresolved_rels:
            # We need to find the source entity or file
            source_entity = graph.get_entity(rel.source_id)
            if not source_entity:
                # Might be a file ID
                file_path = rel.source_id
                line = rel.metadata.get("line_number", 1)
            else:
                file_path = source_entity.file
                line = source_entity.start_line
                
            doc = TextDocumentIdentifier(uri=f"file://{file_path}")
            pos = Position(line=line - 1, character=0)
            
            try:
                resp = await self.client.textDocument_definition(doc, pos)
                if resp and resp.locations:
                    target_loc = resp.locations[0]
                    target_path = target_loc.uri.replace("file://", "")
                    target_line = target_loc.range.start.line + 1
                    
                    # Find matching entity in graph via location
                    target_entities = [
                        e for e in graph.entities_by_file(target_path)
                        if e.start_line <= target_line <= e.end_line
                    ]
                    
                    if target_entities:
                        # Found it! Update relationship
                        actual_target = target_entities[0]
                        
                        # Remove old unresolved
                        graph.relationships.remove(rel)
                        
                        # Add new resolved
                        resolved_rel = Relationship(
                            source_id=rel.source_id,
                            target_id=actual_target.id,
                            type=rel.type,
                            metadata=rel.metadata
                        )
                        graph.add_relationship(resolved_rel)
                        success_count += 1
                        
            except Exception as e:
                self.logger.debug("resolution_failed", source=rel.source_id, error=str(e))
                
        self.logger.info("cross_file_resolution_completed", 
            resolved=success_count, 
            total=len(unresolved_rels)
        )
