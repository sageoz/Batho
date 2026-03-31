"""
Benchmark runner.
"""
import asyncio
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from batho_core.context.codegraph import CodeGraphIndexer
from batho_core.context.lsp.client import LSPClient
from batho_core.context.lsp.merger import LSPASTMerger
from batho_core.lsp.registry import LSPRegistry
from batho_core.context.lsp.adapters.factory import get_adapter

from tests.benchmark.hasher import GraphHasher

logger = logging.getLogger(__name__)

@dataclass
class BenchmarkResult:
    language: str
    repo: str
    commit: str
    run_count: int
    hashes: List[str]
    durations_ms: List[int]
    deterministic: bool
    error_runs: int
    p50_ms: int
    p95_ms: int
    p99_ms: int

class DeterminismError(AssertionError):
    pass

class BenchmarkRunner:
    def __init__(self, language: str, fixture_path: str):
        self.language = language
        self.fixture_path = str(Path(fixture_path).resolve())
        self.registry = LSPRegistry()
        
    async def run_single(self) -> Tuple[str, int]:
        """Runs a single pass and returns (hash, duration_ms)"""
        start = time.perf_counter()
        
        cache_path = Path(".ctn") / f"bench_{self.language}_cache.json"
        if cache_path.exists():
            cache_path.unlink()
            
        indexer = CodeGraphIndexer(cache_path=str(cache_path), root=self.fixture_path)
        graph = indexer.build_graph(self.fixture_path, max_workers=2)
        
        adapter = get_adapter(self.language)
        spec = self.registry.get_latest_version(self.language)
        
        client = LSPClient(
            language=self.language,
            container_config=spec.container,
            adapter=adapter,
        )
        
        # Merge LSP data into graph 
        # (Assumes client methods are mocked appropriately in tests)
        async with client:
            merger = LSPASTMerger(client)
            for file_path in set(e.file for e in graph.entities.values()):
                await merger.merge_async(graph, file_path)
                
        duration_ms = int((time.perf_counter() - start) * 1000)
        h = GraphHasher.hash_graph(graph)
        return h, duration_ms
        
    async def run(self, count: int) -> BenchmarkResult:
        hashes = []
        durations = []
        errors = 0
        for i in range(count):
            try:
                h, d = await self.run_single()
                hashes.append(h)
                durations.append(d)
            except Exception as e:
                logger.error(f"Run {i} failed: {e}")
                errors += 1
                
        if not hashes:
            deterministic = False
        else:
            deterministic = len(set(hashes)) == 1
            
        if not deterministic and errors == 0:
            raise DeterminismError(f"Hashes diverge! Unique hashes: {set(hashes)}")
            
        durations.sort()
        p50 = durations[len(durations)//2] if durations else 0
        p95 = durations[int(len(durations)*0.95)] if durations else 0
        p99 = durations[int(len(durations)*0.99)] if durations else 0
        
        return BenchmarkResult(
            language=self.language,
            repo=self.fixture_path,
            commit="dummy",
            run_count=count,
            hashes=hashes,
            durations_ms=durations,
            deterministic=deterministic,
            error_runs=errors,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99
        )
