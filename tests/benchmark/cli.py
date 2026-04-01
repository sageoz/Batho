"""
CLI for Benchmark Runner.
"""
import argparse
import asyncio
import json
from pathlib import Path

from tests.benchmark.runner import BenchmarkRunner

def main():
    parser = argparse.ArgumentParser(description="Batho Determinism Benchmark")
    parser.add_argument("--language", required=True, help="Language to benchmark")
    parser.add_argument("--runs", type=int, default=1000, help="Number of runs")
    parser.add_argument("--quick", action="store_true", help="Run 10 iterations")
    parser.add_argument("--output", help="Write JSON results to file")
    
    args = parser.parse_args()
    
    runs = 10 if args.quick else args.runs
    
    fixture_path = Path("tests") / "benchmark" / "fixtures" / args.language
    if not fixture_path.exists():
        print(f"Error: Fixture {fixture_path} not found.")
        return
        
    print(f"Running benchmark for {args.language} ({runs} iterations) on {fixture_path}...")
    
    runner = BenchmarkRunner(args.language, str(fixture_path))
    result = asyncio.run(runner.run(runs))
    
    print("\nBenchmark Results:")
    print("------------------")
    print(f"Language: {result.language}")
    print(f"Runs: {result.run_count} (Errors: {result.error_runs})")
    print(f"Deterministic: {'✅ YES' if result.deterministic else '❌ NO'}")
    print(f"Latency: p50={result.p50_ms}ms, p95={result.p95_ms}ms, p99={result.p99_ms}ms")
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            from dataclasses import asdict
            json.dump(asdict(result), f, indent=2)
            print(f"Results saved to {args.output}")

if __name__ == "__main__":
    main()
