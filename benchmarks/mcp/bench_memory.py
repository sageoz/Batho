"""Benchmark: Memory usage of MCP reader.

Measures RSS memory before and after loading artifacts via BathoBundleReader.
Usage: uv run python benchmarks/mcp/bench_memory.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psutil

from batho.mcp.tools import _get_reader


def get_rss_mb() -> float:
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)


def bench_memory(root: Path) -> None:
    print(f"\n=== MCP Memory Benchmark ===")
    print(f"Root: {root}\n")

    rss_before = get_rss_mb()
    print(f"RSS before reader: {rss_before:.1f} MB")

    reader = _get_reader(str(root))

    rss_after_init = get_rss_mb()
    print(f"RSS after reader init: {rss_after_init:.1f} MB (+{rss_after_init - rss_before:.1f} MB)")

    agent_table = reader._get_table("agent_views")
    rels_table = reader._get_table("rels_views")
    storage_table = reader._get_table("storage_views")
    tracking = reader.get_all_file_tracking()
    runs = reader.get_all_runs()

    rss_after_load = get_rss_mb()
    print(f"RSS after full load: {rss_after_load:.1f} MB (+{rss_after_load - rss_after_init:.1f} MB)")

    print(f"\nAgent rows: {agent_table.num_rows}")
    print(f"Rels rows: {rels_table.num_rows}")
    print(f"Storage rows: {storage_table.num_rows}")
    print(f"Files tracked: {len(tracking)}")
    print(f"Runs: {len(runs)}")

    agent_bytes = agent_table.nbytes
    rels_bytes = rels_table.nbytes
    storage_bytes = storage_table.nbytes
    print(f"\nAgent table: {agent_bytes / 1024:.0f} KB")
    print(f"Rels table: {rels_bytes / 1024:.0f} KB")
    print(f"Storage table: {storage_bytes / 1024:.0f} KB")
    print(f"Total IPC: {(agent_bytes + rels_bytes + storage_bytes) / 1024:.0f} KB")


def main():
    parser = argparse.ArgumentParser(description="Benchmark MCP reader memory usage")
    parser.add_argument("--root", required=True, help="Repository root with .batho artifact")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    bench_memory(root)


if __name__ == "__main__":
    main()
