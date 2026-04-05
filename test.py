#!/usr/bin/env python3
"""
Batho test runner — convenience wrapper around pytest via uv.

Usage:
    uv run python test.py                  # Run all tests with coverage
    uv run python test.py --unit           # Run unit tests only
    uv run python test.py --integration    # Run integration tests only
    uv run python test.py --module utils   # Run tests/utils/ only
    uv run python test.py -k test_hash     # pytest -k passthrough
    uv run python test.py --no-cov         # Skip coverage
    uv run python test.py --parallel       # Run tests in parallel
    uv run python test.py --ci             # CI/CD mode with JUnit XML
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys


def main() -> int:
    args = sys.argv[1:]
    pytest_args: list[str] = []
    
    # CI/CD mode
    ci_mode = "--ci" in args
    if ci_mode:
        args.remove("--ci")
        # CI-friendly output formats
        pytest_args.extend([
            "--junit-xml=test-results.xml",
            "--tb=short",
            "--disable-warnings",
        ])
    
    # Parallel execution
    parallel = "--parallel" in args
    if parallel:
        args.remove("--parallel")
        pytest_args.extend(["-n", "auto"])  # Use all available CPUs

    # Marker shortcuts
    if "--unit" in args:
        args.remove("--unit")
        pytest_args.extend(["-m", "unit"])
    if "--integration" in args:
        args.remove("--integration")
        pytest_args.extend(["-m", "integration"])
    if "--slow" in args:
        args.remove("--slow")
        pytest_args.extend(["-m", "slow"])

    # Module shortcut
    if "--module" in args:
        idx = args.index("--module")
        module = args[idx + 1]
        args = args[:idx] + args[idx + 2:]
        pytest_args.append(f"tests/{module}/")

    # Coverage
    no_cov = "--no-cov" in args
    if no_cov:
        args.remove("--no-cov")
    else:
        if importlib.util.find_spec("pytest_cov") is None:
            print(
                "Warning: pytest-cov is not installed; running tests without coverage. "
                "Install with `uv sync --group dev` (after adding pytest-cov) or "
                "`uv add --group dev pytest-cov`.",
                file=sys.stderr,
            )
        else:
            pytest_args.extend([
                "--cov=batho",
                "--cov=batho_cli",
                "--cov-report=term-missing",
                "--cov-report=html:htmlcov",
            ])
            if ci_mode:
                pytest_args.extend([
                    "--cov-report=xml:coverage.xml",
                    "--cov-fail-under=80",
                ])

    # Pass remaining args through to pytest
    pytest_args.extend(args)

    cmd = ["uv", "run", "pytest", "tests/", "-v"] + pytest_args
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
