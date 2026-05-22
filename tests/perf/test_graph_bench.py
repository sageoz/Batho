"""
tests/perf/test_graph_bench.py — Benchmarks for InMemoryGraph operations.
"""

from __future__ import annotations

import time
import pytest
from batho.context.codegraph import InMemoryGraph, IncrementalGraphUpdater
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType


def test_bench_incremental_remove():
    """
    Benchmark O(removed * degree) removal logic.
    Creates a graph with 5000 entities and 10000 relationships.
    Removes entities for 10 files.
    """
    # 1. Setup large graph
    num_files = 100
    entities_per_file = 50
    num_entities = num_files * entities_per_file
    
    graph = InMemoryGraph()
    all_eids = []
    
    # Create entities across 100 files
    for f_idx in range(num_files):
        file_path = f"src/file_{f_idx:03d}.py"
        for e_idx in range(entities_per_file):
            eid = f"f{f_idx}_e{e_idx}"
            e = Entity(
                id=eid,
                name=f"func_{e_idx}",
                type=EntityType.FUNCTION,
                file=file_path,
                start_line=e_idx + 1,
                end_line=e_idx + 1,
                start_byte=e_idx * 20,
                end_byte=(e_idx * 20) + 10,
            )
            graph.add_entity(e)
            all_eids.append(eid)
            
    # Create 10k random-ish relationships
    for i in range(10000):
        src_id = all_eids[i % num_entities]
        tgt_id = all_eids[(i * 3) % num_entities]
        if src_id == tgt_id:
            continue
        rel = Relationship(
            id=f"r{i}",
            source_id=src_id,
            target_id=tgt_id,
            type=RelationshipType.CALLS,
            line=1,
        )
        graph.add_relationship(rel)
        
    updater = IncrementalGraphUpdater()
    
    # Files to remove
    files_to_remove = [f"src/file_{i:03d}.py" for i in range(10)]
    
    # 2. Benchmark removal
    iterations = 5
    start = time.perf_counter()
    for _ in range(iterations):
        for f in files_to_remove:
            updater.remove_entities_for_file(graph, f)
    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / iterations) * 1000
    
    # 3. Stats check
    stats = graph.stats()
    assert stats["total_entities"] < num_entities
    
    # Performance assertion: O(removed * degree) should be < 100ms for 500 entities
    assert avg_ms < 100, f"Graph removal took {avg_ms:.2f}ms, expected < 100ms"


def test_bench_graph_batch_operations():
    """
    Benchmark batch entity and relationship addition.
    """
    num_entities = 1000
    num_relationships = 2000
    
    # Benchmark batch entity addition
    entities = [
        Entity(
            id=f"e{i}",
            name=f"func_{i}",
            type=EntityType.FUNCTION,
            file="test.py",
            start_line=i + 1,
            end_line=i + 1,
            start_byte=i * 20,
            end_byte=(i * 20) + 10,
        )
        for i in range(num_entities)
    ]
    
    start = time.perf_counter()
    graph = InMemoryGraph()
    graph.add_entities_batch(entities)
    entity_time_ms = (time.perf_counter() - start) * 1000
    
    # Benchmark batch relationship addition - use unique IDs to avoid deduplication
    relationships = []
    for i in range(num_relationships):
        # Create unique source/target pairs to avoid any deduplication
        src_idx = i
        tgt_idx = (i + 1) % num_entities
        relationships.append(Relationship(
            id=f"rel_unique_{i}",
            source_id=f"e{src_idx}",
            target_id=f"e{tgt_idx}",
            type=RelationshipType.CALLS,
            line=1,
        ))
    
    start = time.perf_counter()
    graph.add_relationships_batch(relationships)
    rel_time_ms = (time.perf_counter() - start) * 1000
    
    # Verify counts
    assert len(graph.entities) == num_entities
    assert len(graph.relationships) == num_relationships
    
    # Performance assertions
    assert entity_time_ms < 50, f"Batch entity add took {entity_time_ms:.2f}ms, expected < 50ms"
    assert rel_time_ms < 100, f"Batch rel add took {rel_time_ms:.2f}ms, expected < 100ms"
