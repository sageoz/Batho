"""Unit and integration tests for the progress engine (batho/utils/progress.py).

Covers the gating decision table, TTY/non-TTY render shapes, phase lifecycle
(transient bars, completion lines), keep-alive behavior, exception safety, log
interleaving, config/env handling, CLI flag plumbing, and the extraction
pipeline's parent-side progress callback.
"""

from __future__ import annotations

import io
import sys
from unittest import mock

import pytest

from batho.utils.progress import ProgressEngine, ProgressGate, _env_no_progress


class FakeTty(io.StringIO):
    """In-memory stream that reports isatty() == True."""

    def isatty(self) -> bool:
        return True


def make_engine(
    gate: ProgressGate | None = None, config: dict | None = None, stream=None
):
    return ProgressEngine(gate=gate, config=config, stream=stream)


# ---------------------------------------------------------------------------
# Gating decision table
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "gate_kwargs,expected_enabled",
    [
        ({}, True),
        ({"quiet": True}, False),
        ({"json_mode": True}, False),
        ({"no_progress": True}, False),
        ({"is_tty": True}, True),
    ],
)
def test_gate_enabled_matrix(gate_kwargs, expected_enabled):
    engine = make_engine(gate=ProgressGate(**gate_kwargs), stream=FakeTty())
    assert engine.enabled is expected_enabled


@pytest.mark.unit
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", " yes "])
def test_env_no_progress_truthy_values(value, monkeypatch):
    monkeypatch.setenv("BATHO_NO_PROGRESS", value)
    assert _env_no_progress() is True


@pytest.mark.unit
@pytest.mark.parametrize("value", ["0", "false", "no", "", "off"])
def test_env_no_progress_strict_parsing(value, monkeypatch):
    """Unlike TQDM_DISABLE, "0" must NOT disable."""
    monkeypatch.setenv("BATHO_NO_PROGRESS", value)
    assert _env_no_progress() is False


@pytest.mark.unit
def test_env_disables_engine(monkeypatch):
    monkeypatch.setenv("BATHO_NO_PROGRESS", "1")
    engine = make_engine(gate=ProgressGate(is_tty=True), stream=FakeTty())
    assert engine.enabled is False


@pytest.mark.unit
def test_env_zero_keeps_engine_enabled(monkeypatch):
    monkeypatch.setenv("BATHO_NO_PROGRESS", "0")
    engine = make_engine(gate=ProgressGate(is_tty=True), stream=FakeTty())
    assert engine.enabled is True


@pytest.mark.unit
def test_disabled_engine_produces_zero_output_and_no_tqdm_import():
    stream = FakeTty()
    engine = make_engine(gate=ProgressGate(quiet=True), stream=stream)
    with mock.patch.dict(sys.modules, {"tqdm": None}):
        with engine.phase("extract", total=10) as handle:
            handle.update(10)
    assert stream.getvalue() == ""


@pytest.mark.unit
def test_no_color_keeps_bar(monkeypatch):
    """NO_COLOR governs color only — the engine never reads it for gating."""
    monkeypatch.setenv("NO_COLOR", "1")
    engine = make_engine(gate=ProgressGate(is_tty=True), stream=FakeTty())
    assert engine.enabled is True


# ---------------------------------------------------------------------------
# TTY render shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tty_bar_render_shape():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"mininterval_s": 0, "show_after_s": 0.0},
        stream=stream,
    )
    with engine.phase("extract", total=10) as handle:
        for _ in range(5):
            handle.update(1)
    rendered = stream.getvalue()
    assert "  extract   [ 50%] 5/10" in rendered
    assert "\r" in rendered


@pytest.mark.unit
def test_tty_phase_is_transient_and_leaves_completion_line():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"mininterval_s": 0, "show_after_s": 0.0},
        stream=stream,
    )
    with engine.phase("extract", total=10) as handle:
        handle.update(10)
    lines = [ln for ln in stream.getvalue().split("\n") if ln.strip()]
    # The live bar frames are erased on close; the completion line remains.
    # The erase sequence ends with \r (no newline), so take the last \r-segment.
    assert lines[-1].split("\r")[-1] == "  extract   [100%] 10 files (0.0s)"


@pytest.mark.unit
def test_tty_short_phase_renders_no_bar_but_completion_line():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"show_after_s": 60.0},
        stream=stream,
    )
    with engine.phase("extract", total=10) as handle:
        handle.update(10)
    assert "%" not in stream.getvalue().replace("[100%]", "")
    assert stream.getvalue().endswith("  extract   [100%] 10 files (0.0s)\n")


@pytest.mark.unit
def test_set_total_opens_bar_with_initial_count():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"mininterval_s": 0, "show_after_s": 0.0},
        stream=stream,
    )
    with engine.phase("extract") as handle:
        handle.update(3)
        assert handle.count == 3
        handle.set_total(10)
        handle.update(2)
    assert "  extract   [ 50%] 5/10" in stream.getvalue()


@pytest.mark.unit
def test_indeterminate_phase_completion_line():
    stream = FakeTty()
    engine = make_engine(gate=ProgressGate(is_tty=True), stream=stream)
    with engine.phase("deps", unit="manifests"):
        pass
    assert stream.getvalue() == "  deps      done (0.0s)\n"


@pytest.mark.unit
def test_classic_style_omits_percentage():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"mininterval_s": 0, "show_after_s": 0.0, "style": "classic"},
        stream=stream,
    )
    with engine.phase("extract", total=10) as handle:
        handle.update(5)
    assert "[" not in stream.getvalue()
    assert "  extract   5/10" in stream.getvalue()


@pytest.mark.unit
def test_completion_with_skipped_units_is_honest():
    stream = FakeTty()
    engine = make_engine(gate=ProgressGate(is_tty=False), stream=stream)
    with engine.phase("extract", total=10) as handle:
        handle.update(7)
    assert stream.getvalue() == "  extract   7/10 files (0.0s)\n"


# ---------------------------------------------------------------------------
# Non-TTY behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_non_tty_emits_single_completion_line_no_ansi():
    stream = io.StringIO()
    engine = make_engine(gate=ProgressGate(is_tty=False), stream=stream)
    with engine.phase("extract", total=100) as handle:
        for _ in range(100):
            handle.update(1)
    out = stream.getvalue()
    assert out == "  extract   [100%] 100 files (0.0s)\n"
    assert "\r" not in out
    assert "\x1b" not in out


@pytest.mark.unit
def test_non_tty_no_in_run_updates():
    stream = io.StringIO()
    engine = make_engine(gate=ProgressGate(is_tty=False), stream=stream)
    with engine.phase("extract", total=1000) as handle:
        for _ in range(500):
            handle.update(1)
        assert stream.getvalue() == ""


@pytest.mark.unit
def test_keepalive_lines_on_long_non_tty_phase():
    """Keep-alive is time-driven: a phase with NO update calls still emits.

    This is the community-detection case — without a timer the phase would
    be silent for its whole duration in non-TTY mode (frozen CI log).
    """
    import time as time_mod

    stream = io.StringIO()
    engine = make_engine(
        gate=ProgressGate(is_tty=False),
        config={"keepalive_s": 0.05},
        stream=stream,
    )
    with engine.phase("graph", total=None, unit="communities"):
        time_mod.sleep(0.16)
    out = stream.getvalue()
    # >= 2 keep-alive lines in the 160 ms window, plus the completion line.
    assert out.count("\n") >= 3
    assert "  graph     ... 0 communities (" in out
    assert "\r" not in out
    last = out.strip().splitlines()[-1]
    assert last.startswith("  graph     done (")
    # The timer thread must be gone once the phase closes.
    assert engine._active is None


@pytest.mark.unit
def test_keepalive_suppressed_while_bar_rendering():
    """With a live bar rendering, keep-alive lines must not interleave."""
    import time as time_mod

    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"keepalive_s": 0.05, "mininterval_s": 0, "show_after_s": 0.0},
        stream=stream,
    )
    with engine.phase("extract", total=1000) as handle:
        time_mod.sleep(0.12)
        handle.update(5)
    out = stream.getvalue()
    assert "..." not in out.replace("\r", "")  # no keep-alive lines, only bar frames


@pytest.mark.unit
def test_keepalive_thread_stops_on_abort():
    engine = make_engine(
        gate=ProgressGate(is_tty=False),
        config={"keepalive_s": 0.05},
        stream=io.StringIO(),
    )
    handle = engine.open_phase("extract", total=10)
    assert handle._keepalive_thread is not None
    engine.abort()
    # close() joins the timer and clears the reference.
    assert handle._keepalive_thread is None
    assert engine._active is None


# ---------------------------------------------------------------------------
# Phase lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_exception_inside_phase_closes_bar_without_completion_line():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"mininterval_s": 0, "show_after_s": 0.0},
        stream=stream,
    )
    with pytest.raises(RuntimeError, match="boom"):
        with engine.phase("extract", total=5) as handle:
            handle.update(1)
            raise RuntimeError("boom")
    # Bar erased (trailing spaces + \r), no completion line emitted.
    assert "done" not in stream.getvalue()
    assert "[100%]" not in stream.getvalue()


@pytest.mark.unit
def test_log_during_active_bar_does_not_corrupt_display():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"mininterval_s": 0, "show_after_s": 0.0},
        stream=stream,
    )
    with engine.phase("extract", total=10) as handle:
        handle.update(2)
        engine.log("warning: skipped vendor/lib.py")
        handle.update(1)
    out = stream.getvalue()
    assert "warning: skipped vendor/lib.py\n" in out
    # Bar redraws after the log line (a frame appears after the message).
    assert out.index("warning: skipped") < out.rindex("\r")


@pytest.mark.unit
def test_log_suppressed_in_json_mode():
    stream = FakeTty()
    engine = make_engine(gate=ProgressGate(json_mode=True), stream=stream)
    engine.log("should not appear")
    assert stream.getvalue() == ""


@pytest.mark.unit
def test_open_phase_force_closes_dangling_phase():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"mininterval_s": 0, "show_after_s": 0.0},
        stream=stream,
    )
    first = engine.open_phase("extract", total=10)
    second = engine.open_phase("extract", total=10)
    assert first._closed is True
    second.close()
    assert engine._active is None


@pytest.mark.unit
def test_abort_closes_dangling_phase_silently():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"mininterval_s": 0, "show_after_s": 0.0},
        stream=stream,
    )
    handle = engine.open_phase("extract", total=10)
    handle.update(1)
    engine.abort()
    assert handle._closed is True
    assert engine._active is None
    assert "done" not in stream.getvalue()


# ---------------------------------------------------------------------------
# Config handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_config_defaults_when_section_absent():
    engine = make_engine(gate=ProgressGate(is_tty=True), config=None, stream=FakeTty())
    assert engine._style == "progress"
    assert engine._mininterval == 0.2
    assert engine._show_after == 2.0
    assert engine._keepalive == 60.0


@pytest.mark.unit
def test_config_enabled_false_disables_engine():
    """progress.enabled: false is the documented master switch — it must gate."""
    engine = make_engine(
        gate=ProgressGate(is_tty=True), config={"enabled": False}, stream=FakeTty()
    )
    assert engine.enabled is False


@pytest.mark.unit
def test_config_enabled_true_keeps_engine_enabled():
    engine = make_engine(
        gate=ProgressGate(is_tty=True), config={"enabled": True}, stream=FakeTty()
    )
    assert engine.enabled is True


@pytest.mark.unit
def test_config_enabled_false_beats_tty():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True), config={"enabled": False}, stream=stream
    )
    with engine.phase("extract", total=10) as handle:
        handle.update(10)
    assert stream.getvalue() == ""


@pytest.mark.unit
def test_config_invalid_style_falls_back_with_warning():
    stream = FakeTty()
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"style": "sparkly"},
        stream=stream,
    )
    assert engine._style == "progress"


@pytest.mark.unit
def test_config_invalid_values_fall_back_to_defaults():
    engine = make_engine(
        gate=ProgressGate(is_tty=True),
        config={"mininterval_s": "not-a-number"},
        stream=FakeTty(),
    )
    assert engine._mininterval == 0.2


# ---------------------------------------------------------------------------
# CLIOutput delegation (T2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_output_progress_delegates_and_gates():
    from batho.utils.cli_output import CLIOutput

    cli = CLIOutput(quiet=True)
    with cli.progress(total=10, desc="work") as update:
        update(5)
    # quiet mode: no output, callable still works


@pytest.mark.unit
def test_cli_output_progress_json_mode_suppresses(capsys):
    from batho.utils.cli_output import CLIOutput

    cli = CLIOutput(json_mode=True)
    with cli.progress(total=10, desc="work") as update:
        update(10)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.unit
def test_cli_output_configure_invalidates_engine():
    from batho.utils.cli_output import CLIOutput

    cli = CLIOutput()
    engine_before = cli._get_progress_engine()
    cli.configure(quiet=True)
    engine_after = cli._get_progress_engine()
    assert engine_before is not engine_after
    assert engine_after.enabled is False


# ---------------------------------------------------------------------------
# CLI flag plumbing (T7)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_parser_accepts_no_progress():
    import argparse

    from batho.cli.build import register_build_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_build_parser(subparsers)
    args = parser.parse_args(["build", "--no-progress"])
    assert args.no_progress is True


@pytest.mark.unit
def test_patch_parser_accepts_no_progress():
    import argparse

    from batho.cli.patch import register_patch_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_patch_parser(subparsers)
    args = parser.parse_args(["patch", "--no-progress"])
    assert args.no_progress is True


@pytest.mark.unit
def test_build_parser_default_progress_enabled():
    import argparse

    from batho.cli.build import register_build_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_build_parser(subparsers)
    args = parser.parse_args(["build"])
    assert args.no_progress is False


# ---------------------------------------------------------------------------
# Extraction pipeline parent-side callback (T4)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pipeline_progress_callback_counts_results(tmp_path, monkeypatch):
    """Sequential path: callback fires once per completed result, in-process."""
    from batho.modules.extraction import pipeline

    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n")

    calls = []
    results, errors, _audit = pipeline.extract_and_emit_parallel(
        [(src, str(src))],
        configured_max_file_size_kb=500,
        bsg_cfg={"parallel": {"enabled": False}, "cache": {"enabled": False}},
        progress_callback=calls.append,
    )
    assert len(results) == 1
    assert calls == [1]


@pytest.mark.unit
def test_pipeline_progress_callback_failure_does_not_break_extraction(tmp_path):
    from batho.modules.extraction import pipeline

    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n")

    results, errors, _audit = pipeline.extract_and_emit_parallel(
        [(src, str(src))],
        configured_max_file_size_kb=500,
        bsg_cfg={"parallel": {"enabled": False}, "cache": {"enabled": False}},
        progress_callback=_bad_callback,
    )
    assert len(results) == 1


def _bad_callback(_n):
    raise RuntimeError("sink exploded")


@pytest.mark.unit
def test_pipeline_no_callback_is_default_safe(tmp_path):
    """Existing callers (progress_callback=None) are unaffected."""
    from batho.modules.extraction import pipeline

    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n")
    results, errors, _audit = pipeline.extract_and_emit_parallel(
        [(src, str(src))],
        configured_max_file_size_kb=500,
        bsg_cfg={"parallel": {"enabled": False}, "cache": {"enabled": False}},
    )
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Performance guard (T9) — progress overhead must stay negligible
# ---------------------------------------------------------------------------


def _wall_clock_benchmark_valid() -> bool:
    """True when a wall-clock ratio measurement is meaningful.

    The guard compares build wall-clock with vs without the progress engine.
    Under a coverage tracer (pytest-cov / CI) the tracer's own overhead
    dwarfs the ~60ns/iter signal being measured, and shared CI runners add
    co-tenant noise plus a tight per-test timeout — two full builds of the
    fixture tree under coverage can exceed the 60s budget on 2-core runners
    (CI failure 2026-09-20). Skip there; the throttle regression it guards
    against (2-10x slowdown) still shows up in local, untraced runs.
    """
    import os

    if os.environ.get("CI", "").lower() in {"true", "1"}:
        return False
    if hasattr(sys, "monitoring"):
        try:
            if sys.monitoring.get_tool(sys.monitoring.COVERAGE_ID) is not None:
                return False
        except Exception:
            pass
    return sys.gettrace() is None


@pytest.mark.slow
@pytest.mark.timeout(300)
@pytest.mark.skipif(
    not _wall_clock_benchmark_valid(),
    reason="wall-clock benchmark is invalid under coverage tracing / on shared CI runners",
)
def test_progress_overhead_within_budget(tmp_path):
    """Engine-on vs engine-off build wall-clock on a small fixture tree.

    Design budget is 1% (documented overhead is ~60ns/iter vs ms-scale parses);
    the asserted margin is 10% to stay robust on shared CI runners while still
    catching a broken throttle (which would show up as 2-10x slowdown).

    Skipped when a coverage tracer is active or on CI: the tracer dominates
    the measurement and the per-test timeout can fire mid-build.
    """
    import shutil
    import time as time_mod

    from batho.orchestrator.build import BuildOptions, run_build

    root = tmp_path / "perf-repo"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    for i in range(150):
        (pkg / f"mod_{i}.py").write_text(
            f"class S{i}:\n"
            f"    def m(self):\n        return {i}\n\n\n"
            f"def h{i}():\n    return S{i}()\n"
        )

    def build(no_progress: bool) -> float:
        shutil.rmtree(root / ".batho", ignore_errors=True)
        t0 = time_mod.monotonic()
        result = run_build(BuildOptions(root=root, no_progress=no_progress))
        assert result.success
        return time_mod.monotonic() - t0

    baseline = build(no_progress=True)
    instrumented = build(no_progress=False)
    assert baseline > 0
    assert (
        instrumented < baseline * 1.10
    ), f"progress overhead too high: {instrumented:.2f}s vs baseline {baseline:.2f}s"


def test_progress_phase_type_hints_resolve():
    """``-> Iterator[PhaseHandle]`` must resolve under get_type_hints —
    guards against annotations that are only safe because of
    ``from __future__ import annotations`` (issue 65767cbbaf66)."""
    import typing
    from batho.utils.progress import ProgressEngine

    hints = typing.get_type_hints(ProgressEngine.phase)
    assert "return" in hints


@pytest.mark.unit
def test_pipeline_progress_counts_skipped_candidates(tmp_path):
    """Every discovered candidate ticks exactly once — including files that
    fail stat before extraction — so the count matches the discovered total
    (issue 5445bfa46077)."""
    from batho.modules.extraction import pipeline

    ok = tmp_path / "ok.py"
    ok.write_text("def f():\n    return 1\n")
    missing = tmp_path / "missing.py"  # never created — stat() raises

    calls = []
    results, errors, _audit = pipeline.extract_and_emit_parallel(
        [(ok, str(ok)), (missing, str(missing))],
        configured_max_file_size_kb=500,
        bsg_cfg={"parallel": {"enabled": False}, "cache": {"enabled": False}},
        progress_callback=calls.append,
    )
    assert len(results) == 1
    assert errors == 1
    assert calls == [1, 1]


@pytest.mark.unit
def test_pipeline_progress_fallback_never_exceeds_total(tmp_path, monkeypatch):
    """A pool dying mid-iteration must not double-tick files it already
    reported — the sequential fallback re-ticks only unreported work items
    (issue d0e5ee8650e2)."""
    import multiprocessing
    from batho.modules.extraction import pipeline

    candidates = []
    for i in range(3):
        p = tmp_path / f"f{i}.py"
        p.write_text(f"def f{i}():\n    return {i}\n")
        candidates.append((p, str(p)))

    class _ExplodingPool:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def imap_unordered(self, fn, items, chunksize=1):
            # Report one candidate as consumed, then die mid-iteration.
            yield (items[0][1], None)
            raise RuntimeError("pool exploded")

    class _FakeCtx:
        def Pool(self, *args, **kwargs):
            return _ExplodingPool()

    monkeypatch.setattr(multiprocessing, "get_context", lambda *a, **k: _FakeCtx())

    calls = []
    results, errors, _audit = pipeline.extract_and_emit_parallel(
        candidates,
        configured_max_file_size_kb=500,
        bsg_cfg={"parallel": {"enabled": True}, "cache": {"enabled": False}},
        progress_callback=calls.append,
    )
    # All 3 candidates reprocessed by the fallback; the pool's one reported
    # file is not counted twice.
    assert len(results) == 3
    assert calls == [1, 1, 1]
