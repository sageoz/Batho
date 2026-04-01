"""
Canonical graph hasher for benchmark determinism.
"""
import hashlib
import json
from batho_core.context.codegraph import InMemoryGraph

# All metadata keys that can be non-deterministic across runs.
# This includes:
# - LSP-injected volatile fields: lsp_definition_hash, lsp_inferred_type, lsp_hover_hash
# - timestamp-based fields: timestamp, duration_ms
# - AST auxiliary fields that use tree-sitter Node.id (memory address): bases, extends,
#   implements, field_type, docstring, visibility — these can vary when _nearest_ancestor
#   falls back to nodes[0] in different order across parses in the same process.
_STRIP_FIELDS = frozenset({
    "timestamp",
    "duration_ms",
    "lsp_hover_hash",
    "lsp_definition_hash",
    "lsp_inferred_type",
    "bases",
    "extends",
    "implements",
    "field_type",
    "docstring",
    "visibility",
    "trait",
})

class GraphHasher:
    @staticmethod
    def hash_graph(graph: InMemoryGraph) -> str:
        """
        Computes a deterministic SHA-256 root hash for the entire graph.
        Sorts entities and relationships canonically to guarantee identical output
        for identical graphs regardless of insertion order.
        Deduplicates relationships to handle multiple merger runs.
        Only includes structural identity fields to avoid aux metadata non-determinism.
        """
        # Sort entities by ID
        sorted_entities = sorted(graph.entities.values(), key=lambda e: e.id)
        
        hasher = hashlib.sha256()
        
        for e in sorted_entities:
            # Strip non-deterministic and auxiliary metadata keys
            meta = {k: v for k, v in e.metadata.items() if k not in _STRIP_FIELDS}
            canonical_meta = json.dumps(meta, sort_keys=True)
            e_str = f"{e.id}|{e.type.name}|{e.name}|{e.file}|{e.start_line}|{canonical_meta}\n"
            hasher.update(e_str.encode("utf-8"))
        
        # Build canonical relationship strings, deduplicate by structural edge (source, target, type).
        # Relationship metadata (line_number etc.) is intentionally excluded from the hash:
        # the same logical edge can appear with different line annotations across runs due to
        # non-deterministic tree-sitter capture ordering in repeated in-process parses.
        rel_strs = set()
        for r in graph.relationships:
            r_str = f"{r.source_id}|{r.target_id}|{r.type.name}\n"
            rel_strs.add(r_str)
            
        for r_str in sorted(rel_strs):
            hasher.update(r_str.encode("utf-8"))
            
        return hasher.hexdigest()
