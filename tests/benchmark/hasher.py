"""
Canonical graph hasher for benchmark determinism.
"""
import hashlib
import json
from batho_core.context.codegraph import InMemoryGraph

class GraphHasher:
    @staticmethod
    def hash_graph(graph: InMemoryGraph) -> str:
        """
        Computes a deterministic SHA-256 root hash for the entire graph.
        Sorts entities and relationships canonically to guarantee identical output
        for identical graphs regardless of insertion order.
        """
        # Sort entities by ID
        sorted_entities = sorted(graph.entities.values(), key=lambda e: e.id)
        
        # Sort relationships by source_id, target_id, type
        sorted_rels = sorted(
            graph.relationships,
            key=lambda r: (r.source_id, r.target_id, r.type.name)
        )
        
        hasher = hashlib.sha256()
        
        for e in sorted_entities:
            # Strip non-deterministic metadata keys
            meta = dict(e.metadata)
            meta.pop("timestamp", None)
            meta.pop("duration_ms", None)
            meta.pop("lsp_hover_hash", None)
            
            canonical_meta = json.dumps(meta, sort_keys=True)
            e_str = f"{e.id}|{e.type.name}|{e.name}|{e.file}|{e.start_line}|{canonical_meta}\n"
            hasher.update(e_str.encode("utf-8"))
            
        for r in sorted_rels:
            meta = dict(r.metadata)
            meta.pop("timestamp", None)
            canonical_meta = json.dumps(meta, sort_keys=True)
            r_str = f"{r.source_id}|{r.target_id}|{r.type.name}|{canonical_meta}\n"
            hasher.update(r_str.encode("utf-8"))
            
        return hasher.hexdigest()
