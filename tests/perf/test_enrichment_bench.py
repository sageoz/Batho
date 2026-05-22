"""
tests/perf/test_enrichment_bench.py — Benchmarks for entity enrichment.
"""

from __future__ import annotations

import time
import pytest
from batho.context.pipeline import _enrich_cached_entities
from batho.context.schema import Entity, EntityType


def test_bench_enrich_cached_entities():
    """
    Benchmark O(N log N) enrichment logic.
    Creates 1000 entities in a single file and measures enrichment time.
    """
    # 1. Synthesize 1000 entities
    num_entities = 1000
    filepath = "bench_file.py"
    
    # Create content: 1000 lines of "def func_XXX(): pass\n"
    content_lines = [f"def func_{i:04d}(): pass" for i in range(num_entities)]
    content_str = "\n".join(content_lines)
    content_bytes = content_str.encode("utf-8")
    
    # Create entities with correct byte offsets
    entities = []
    current_byte = 0
    for i in range(num_entities):
        line_text = content_lines[i]
        line_bytes = line_text.encode("utf-8")
        
        entities.append(Entity(
            id=f"e{i}",
            name=f"func_{i:04d}",
            type=EntityType.FUNCTION,
            file=filepath,
            start_line=i + 1,
            end_line=i + 1,
            start_byte=current_byte,
            end_byte=current_byte + len(line_bytes),
            raw_content=None,  # This is what we're enriching
        ))
        current_byte += len(line_bytes) + 1 # +1 for newline
        
    # 2. Benchmark the enrichment
    # Run multiple iterations and take average
    iterations = 10
    start = time.perf_counter()
    for _ in range(iterations):
        result = _enrich_cached_entities(entities, content_bytes, filepath)
    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / iterations) * 1000
    
    # 3. Verify correctness
    assert len(result) == num_entities
    assert result[0].raw_content == "def func_0000(): pass"
    assert result[1].leading_whitespace == "\n"
    
    # Performance assertion: O(N log N) should be < 50ms for 1000 entities
    assert avg_ms < 50, f"Enrichment took {avg_ms:.2f}ms, expected < 50ms"
