"""Benchmark harness for `batho patch` — phase-broken-down timing.

Measures where patch wall-time actually goes at configurable repo sizes, to
decide whether deferred Phase-3 work (``scan_changes`` path narrowing,
community-detection gating) is worthwhile:

  - ``detect_ms``  — IncrementalEngine.scan_changes tree walk + hashing
  - ``patch_ms``   — full run_patch (detect + extract + store + scope + community)
  - fixed-cost share = patch_ms - detect_ms grows with repo size → narrowing
    detection is low-value; if detect dominates → scan narrowing helps.

Usage:
    python benchmarks/bench_patch.py [--files 1000] [--files2 5000]
                                     [--change-sets 1,10,100] [--out results.json]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from pathlib import Path


def _make_repo(root: Path, n_files: int, seed: int = 42) -> list[Path]:
    """Deterministic synthetic repo: n_files small python modules."""
    rng = random.Random(seed)
    files = []
    for i in range(n_files):
        sub = root / f"pkg{i % 20}"
        sub.mkdir(exist_ok=True)
        f = sub / f"mod_{i}.py"
        body = "\n".join(
            f"def fn_{i}_{j}(x): return x + {rng.randint(0, 999)}\n" for j in range(5)
        )
        f.write_text(body, encoding="utf-8")
        files.append(f)
    return files


def _time_scan(
    root: Path,
    strict_hashing: bool = False,
    max_file_size_kb: int | None = None,
) -> tuple[float, int]:
    """Time IncrementalEngine.scan_changes alone (the detect phase).

    ``strict_hashing`` defaults to False to match the production default
    (``indexer.strict_hashing: false`` — the mtime/inode/size fast path).
    ``max_file_size_kb`` must be threaded through for parity with
    ``run_patch``'s production call. Returns (elapsed_ms, n_changes) so the
    caller can assert the harness sees the intended change-set size.
    """
    from batho.modules.storage.arrow_bundle import get_bundle
    from batho.modules.storage.arrow_bundle.incremental import IncrementalEngine
    from batho.utils.ignore import load_ignore_spec

    db = get_bundle(root)
    try:
        base_run = db.get_latest_run_id()
        engine = IncrementalEngine(db, base_run)
        t0 = time.monotonic()
        changes = engine.scan_changes(
            root=root,
            max_file_size_kb=max_file_size_kb,
            ignore_spec=load_ignore_spec(root),
            strict_hashing=strict_hashing,
        )
        return (time.monotonic() - t0) * 1000.0, len(changes)
    finally:
        db.close() if hasattr(db, "close") else None


def _time_patch(root: Path, max_file_size_kb: int | None = None) -> float:
    from batho.orchestrator.patch import PatchOptions, run_patch

    t0 = time.monotonic()
    res = run_patch(PatchOptions(
        root=root, no_progress=True, max_file_size_kb=max_file_size_kb,
    ))
    ms = (time.monotonic() - t0) * 1000.0
    if not res.success:
        raise RuntimeError(f"patch failed: {res.warnings}")
    return ms


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--files", type=int, default=1000, help="small repo size")
    ap.add_argument("--files2", type=int, default=5000, help="large repo size")
    ap.add_argument("--change-sets", type=str, default="1,10,100")
    ap.add_argument(
        "--repeats", type=int, default=3,
        help="timed repetitions per change set (reported as median/min)",
    )
    ap.add_argument(
        "--max-file-size-kb", type=int, default=None,
        help="production parity: pass through to scan_changes/run_patch",
    )
    ap.add_argument("--out", type=str, default=None, help="write JSON results here")
    args = ap.parse_args()

    from batho.orchestrator.build import BuildOptions, run_build

    change_sets = [int(x) for x in args.change_sets.split(",")]
    results = []

    for n_files in (args.files, args.files2):
        with tempfile.TemporaryDirectory(prefix=f"batho-bench-{n_files}-") as td:
            root = Path(td)
            files = _make_repo(root, n_files)

            t0 = time.monotonic()
            build = run_build(BuildOptions(root=root, no_progress=True))
            build_ms = (time.monotonic() - t0) * 1000.0
            if not build.success:
                print(f"build failed for {n_files}-file repo: {build.warnings}", file=sys.stderr)
                return 1

            # Untimed warmup: one real patch warms import/page caches so the
            # first timed repeat isn't carrying cold-start overhead.
            _time_patch(root, max_file_size_kb=args.max_file_size_kb)

            # No-op detect cost (unchanged tree) — fast path vs strict hashing
            detect_noop_ms, _ = _time_scan(root, strict_hashing=False)
            detect_noop_strict_ms, _ = _time_scan(root, strict_hashing=True)

            for k in change_sets:
                if k > len(files):
                    continue
                detect_runs: list[float] = []
                patch_runs: list[float] = []
                for _rep in range(max(1, args.repeats)):
                    # Mutate k files deterministically — each repeat re-marks
                    # the same prefix so every patch sees exactly k changes.
                    for f in files[:k]:
                        f.write_text(f.read_text(encoding="utf-8") + "\ndef bench_mark(): pass\n", encoding="utf-8")
                    # Changed-file detect uses the fast path (production
                    # default); strict-hashing cost is in detect_noop_strict.
                    detect_ms, n_changed = _time_scan(
                        root, max_file_size_kb=args.max_file_size_kb
                    )
                    if n_changed != k:
                        print(
                            f"  WARN: detect saw {n_changed} changes, expected {k} "
                            "— harness drift",
                            file=sys.stderr,
                        )
                    detect_runs.append(detect_ms)
                    patch_runs.append(
                        _time_patch(root, max_file_size_kb=args.max_file_size_kb)
                    )
                detect_med = _median(detect_runs)
                patch_med = _median(patch_runs)
                row = {
                    "files": n_files,
                    "changed": k,
                    "repeats": len(patch_runs),
                    "build_ms": round(build_ms, 1),
                    "detect_noop_ms": round(detect_noop_ms, 1),
                    "detect_noop_strict_ms": round(detect_noop_strict_ms, 1),
                    "detect_fast_ms": round(detect_med, 1),
                    "detect_fast_min_ms": round(min(detect_runs), 1),
                    "patch_ms": round(patch_med, 1),
                    "patch_min_ms": round(min(patch_runs), 1),
                    "fixed_cost_ms": round(patch_med - detect_med, 1),
                }
                results.append(row)
                print(
                    f"files={n_files:>6} changed={k:>4} | detect={detect_med:8.1f}ms "
                    f"patch={patch_med:8.1f}ms fixed={patch_med - detect_med:8.1f}ms "
                    f"(n={len(patch_runs)})"
                )
            print(
                f"  detect_noop: fast={detect_noop_ms:8.1f}ms "
                f"strict={detect_noop_strict_ms:8.1f}ms"
            )

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
