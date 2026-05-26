"""Graph Search Engine - In-memory fuzzy search for entities."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from batho.context.codegraph import InMemoryGraph
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.services.search_engine")


@dataclass
class SearchHit:
    """A search result hit."""
    id: str
    name: str
    fqn: str
    kind: str
    file: str
    line: int
    score: float
    signature: str = ""


class GraphSearchEngine:
    """
    In-memory fuzzy search over InMemoryGraph entities.
    
    Uses trigram indexing for fast substring search with
    scoring based on match quality.
    """
    
    def __init__(self, graph: InMemoryGraph, db: Any = None, run_id: str | int | None = None):
        self.graph = graph
        self.db = db
        self.run_id = run_id
        self._trigram_index: dict[str, set[str]] = {}
        self._name_index: dict[str, set[str]] = {}
        self._fqn_index: dict[str, set[str]] = {}
        self._build_indexes()
    
    def _build_indexes(self) -> None:
        """Build search indexes from graph entities."""
        for entity_id, entity in self.graph.entities.items():
            name_lower = entity.name.lower() if entity.name else ""
            fqn_lower = entity.fqn.lower() if entity.fqn else ""
            
            # Name index
            if name_lower:
                self._name_index.setdefault(name_lower, set()).add(entity_id)
                # Trigrams
                for tri in self._trigrams(name_lower):
                    self._trigram_index.setdefault(tri, set()).add(entity_id)
            
            # FQN index
            if fqn_lower:
                segments = fqn_lower.split(".")
                for segment in segments:
                    if segment:
                        self._fqn_index.setdefault(segment, set()).add(entity_id)
    
    def search(
        self,
        query: str,
        kinds: list[str] | None = None,
        limit: int = 50,
        use_sqlite_first: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Fuzzy search over entity names and FQN.
        
        Scoring:
        - Exact match: 100
        - Prefix match: 80
        - Substring match: 60
        - FQN exact match: 50
        - FQN substring: 30
        - Signature match: 20
        
        Returns: [{id, name, fqn, kind, file, score}]
        """
        if use_sqlite_first and self.db:
            run_ref = self.run_id
            if not run_ref:
                try:
                    run_ref = self.db.get_latest_run_id()
                except Exception:
                    pass
            if run_ref:
                try:
                    results = self.db.search_entities(run_ref, query, kinds, limit)
                    if results:
                        return results
                except Exception as e:
                    LOGGER.warning("sqlite_search_failed_falling_back", error=str(e))

        start_time = time.time_ns()
        query_lower = query.lower().strip()
        
        if not query_lower:
            return []
        
        # Collect candidates
        candidate_ids: set[str] = set()
        
        # Exact name match
        if query_lower in self._name_index:
            candidate_ids.update(self._name_index[query_lower])
        
        # FQN segment matches
        if query_lower in self._fqn_index:
            candidate_ids.update(self._fqn_index[query_lower])
        
        # Trigram matching for fuzzy
        if len(candidate_ids) < limit:
            trigram_matches = self._trigram_search(query_lower)
            candidate_ids.update(trigram_matches)
        
        # Score candidates
        hits: list[SearchHit] = []
        for entity_id in candidate_ids:
            entity = self.graph.get_entity(entity_id)
            if not entity:
                continue
            
            # Kind filtering
            if kinds and entity.type.value not in kinds:
                continue
            
            score = self._calculate_score(query_lower, entity)
            if score > 0:
                hits.append(SearchHit(
                    id=entity_id,
                    name=entity.name,
                    fqn=entity.fqn or "",
                    kind=entity.type.value,
                    file=entity.file,
                    line=entity.start_line,
                    score=score,
                    signature=entity.signature or "",
                ))
        
        # Sort by score (descending), then name length (ascending)
        hits.sort(key=lambda h: (-h.score, len(h.name)))
        
        # Convert to output format
        results = [
            {
                "id": h.id,
                "name": h.name,
                "fqn": h.fqn,
                "kind": h.kind,
                "file": h.file,
                "line": h.line,
                "score": h.score,
            }
            for h in hits[:limit]
        ]
        
        latency_ms = (time.time_ns() - start_time) / 1e6
        LOGGER.debug("search_complete", query=query, results=len(results), latency_ms=latency_ms)
        
        return results
    
    def _calculate_score(self, query: str, entity) -> float:
        """Calculate match score for entity."""
        score = 0
        name_lower = entity.name.lower() if entity.name else ""
        fqn_lower = entity.fqn.lower() if entity.fqn else ""
        
        # Name matches
        if name_lower == query:
            score = 100
        elif name_lower.startswith(query):
            score = 80
        elif query in name_lower:
            score = 60
        # FQN matches
        elif fqn_lower == query:
            score = 50
        elif query in fqn_lower:
            score = 30
        # Signature match
        elif entity.signature and query in entity.signature.lower():
            score = 20
        
        return score
    
    def _trigrams(self, text: str) -> list[str]:
        """Generate trigrams from text."""
        if len(text) < 3:
            return []
        return [text[i:i+3] for i in range(len(text) - 2)]
    
    def _trigram_search(self, query: str) -> set[str]:
        """Search using trigram matching."""
        if len(query) < 3:
            return set()
        
        query_trigrams = self._trigrams(query)
        if not query_trigrams:
            return set()
        
        # Find candidates that match most trigrams
        candidate_scores: dict[str, int] = {}
        for tri in query_trigrams:
            for entity_id in self._trigram_index.get(tri, set()):
                candidate_scores[entity_id] = candidate_scores.get(entity_id, 0) + 1
        
        # Keep candidates with at least 1/3 of trigrams matching
        min_matches = max(1, len(query_trigrams) // 3)
        return {eid for eid, count in candidate_scores.items() if count >= min_matches}


__all__ = ["GraphSearchEngine", "SearchHit"]
