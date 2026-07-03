"""Benchmark: Patch latency and get_delta read latency.

Measures the time for `batho patch` and subsequent `get_delta` reads
to validate incremental update performance.
Usage: uv run python benchmarks/mcp/bench_patch_latency.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from batho.orchestrator.patch import run_patch, PatchOptions
from batho.mcp.tools import _get_reader
from batho.mcp.delta_reader import read_delta


def bench_patch_latency(root: Path, iterations: int = 3) -> None:
    print(f"\n=== Patch Latency Benchmark ===")
    print(f"Root: {root}")
    print(f"Iterations: {iterations}\n")

    patch_times = []
    delta_read_times = []

    for i in range(iterations):
        marker = root / f".bench_marker_{i}"
        marker.write_text(f"def bench_func_{i}(): pass\n", encoding="utf-8")

        t0 = time.monotonic()
        result = run_patch(PatchOptions(root=root, verbose=False))
        patch_ms = (time.monotonic() - t0) * 1000
        patch_times.append(patch_ms)

        marker.unlink(missing_ok=True)

        t1 = time.monotonic()
        reader = _get_reader(str(root))
        changes, delta_stats, run_info = read_delta(reader)
        delta_ms = (time.monotonic() - t1) * 1000
        delta_read_times.append(delta_ms)

        print(f"  Iteration {i+1}: patch={patch_ms:.0f}ms, get_delta={delta_ms:.1f}ms, "
              f"changes={len(changes)}, success={result.success}")

    print(f"\n{'Metric':<25} {'Avg (ms)':>10} {'Min (ms)':>10} {'Max (ms)':>10}")
    print("-" * 58)
    print(f"{'patch':<25} {sum(patch_times)/len(patch_times):>10.0f} "
          f"{min(patch_times):>10.0f} {max(patch_times):>10.0f}")
    print(f"{'get_delta':<25} {sum(delta_read_times)/len(delta_read_times):>10.1f} "
          f"{min(delta_read_times):>10.1f} {max(delta_read_times):>10.1f}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark patch and get_delta latency")
    parser.add_argument("--root", required=True, help="Repository root with .batho artifact")
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    bench_patch_latency(root, args.iterations)


if __name__ == "__main__":
    main()
