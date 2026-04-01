"""
Synchronous AST + LSP merge engine.

Pauses AST generation, resolves symbols via LSP, and injects semantic data.
"""

import asyncio
from typing import Dict, List, Set, Tuple

from batho_core.utils.logging import get_logger
from batho_core.context.schema import Entity, Relationship, RelationshipType
from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.lsp.client import LSPClient
from batho_core.context.lsp.types import (
    TextDocumentIdentifier, Position, DefinitionResponse, HoverResponse
)


class LSPASTMerger:
    """
    Merges LSP semantic data into the Tree-sitter AST Graph.
    Can be used synchronously in the indexing pipeline using asyncio loops.
    """

    def __init__(self, lsp_client: LSPClient):
        self.client = lsp_client
        self.logger = get_logger(__name__, component="ast_lsp_merger")

    def merge_synchronously(self, graph: InMemoryGraph, file_path: str) -> None:
        """
        Synchronous wrapper around the async merge process.
        This allows it to drop into the existing threaded CodeGraphIndexer.
        """
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self.merge_async(graph, file_path))
        finally:
            loop.close()

    async def merge_async(self, graph: InMemoryGraph, file_path: str) -> None:
        """
        Analyze AST entities for the given file, resolve missing types/definitions
        via LSP, and inject the results into the entities.
        """
        self.logger.info("ast_merge_started", file=file_path)
        
        entities = graph.entities_by_file(file_path)
        if not entities:
            return
            
        doc = TextDocumentIdentifier(uri=f"file://{file_path}")
        
        # 1. Type inference enrichment
        await self._enrich_types(doc, entities, graph)
        
        # 2. Add definition hashes for determinism
        await self._annotate_hashes(doc, entities, graph)

        # 3. Call-chain analysis via references
        await self._analyze_call_chains(doc, entities, graph)

        self.logger.info("ast_merge_completed", file=file_path)

    async def _enrich_types(self, doc: TextDocumentIdentifier, entities: List[Entity], graph: InMemoryGraph) -> None:
        """Fetch type information for untyped variables/functions via Hover."""
        if not self.client.negotiator.supports_hover():
            return
            
        untyped = [
            e for e in entities 
            if e.type.name in ("VARIABLE", "FIELD", "FUNCTION", "METHOD") 
            and not e.metadata.get("return_type") 
            and not e.metadata.get("field_type")
        ]
        
        for entity in untyped:
            pos = Position(line=entity.start_line - 1, character=0)  # rough pos
            try:
                # We would batch this in a real implementation
                hover = await self.client.textDocument_hover(doc, pos)
                if hover and hover.contents:
                    # In a real implementation we parse the markdown content for signature
                    content_str = hover.contents if isinstance(hover.contents, str) else str(hover.contents)
                    
                    # Create enriched entity
                    new_meta = dict(entity.metadata)
                    new_meta["lsp_inferred_type"] = content_str
                    new_meta["lsp_hover_hash"] = hover.hash
                    
                    enriched = entity.model_copy(update={"metadata": new_meta})
                    
                    # Update in graph (InMemoryGraph requires deleting and re-adding)
                    if enriched.id in graph.entities:
                        # Since id might change if metadata affects it (it shouldn't based on schema)
                        graph.entities[enriched.id] = enriched
                        
            except Exception as e:
                self.logger.debug("hover_failed", id=entity.id, error=str(e))

    async def _annotate_hashes(self, doc: TextDocumentIdentifier, entities: List[Entity], graph: InMemoryGraph) -> None:
        """Attach definition hashes to entities for auditability."""
        if not self.client.negotiator.supports_definition():
            return
            
        for entity in entities:
            pos = Position(line=entity.start_line - 1, character=0)
            try:
                def_resp = await self.client.textDocument_definition(doc, pos)
                if def_resp:
                    new_meta = dict(entity.metadata)
                    new_meta["lsp_definition_hash"] = def_resp.hash
                    enriched = entity.model_copy(update={"metadata": new_meta})
                    
                    if enriched.id in graph.entities:
                        graph.entities[enriched.id] = enriched
                        
            except Exception as e:
                self.logger.debug("definition_failed", id=entity.id, error=str(e))

    async def _analyze_call_chains(self, doc: TextDocumentIdentifier, entities: List[Entity], graph: InMemoryGraph) -> None:
        """Trace references for functions to build CALLS relationships."""
        if not self.client.negotiator.supports_references():
            return
            
        funcs = [e for e in entities if e.type.name in ("FUNCTION", "METHOD")]
        
        for entity in funcs:
            pos = Position(line=entity.start_line - 1, character=0)
            try:
                refs = await self.client.textDocument_references(doc, pos)
                if refs and self.client.adapter and hasattr(self.client.adapter, "extract_call_chain_info"):
                    callers = self.client.adapter.extract_call_chain_info(refs)
                    
                    for caller_uri in callers:
                        # For Phase 2, we link the calling file URI to the target entity
                        call_rel = Relationship(
                            source_id=caller_uri,
                            target_id=entity.id,
                            type=RelationshipType.CALLS,
                            metadata={"lsp_resolved": True}
                        )
                        graph.add_relationship(call_rel)
                        
            except Exception as e:
                self.logger.debug("references_failed", id=entity.id, error=str(e))
