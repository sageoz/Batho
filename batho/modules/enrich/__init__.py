"""batho-calibrate runtime — graph-quality profiling, rule fitness scoring,
and plugin fixture gating.

Moved in-repo so `batho build`/`patch` emit `enrich_profile` + `enrich_score`
run-artifact rows and `.batho/report/{overview,score}.md` automatically, and
`batho plugins validate` runs the fixture gate — the agent skill stays
a thin consumer (reads report files, calls CLI verbs) with no batho imports.
"""

from batho.modules.enrich.gap_report import build_gap_report, render_overview_md
from batho.modules.enrich.scoring import build_score_report, render_score_md
from batho.modules.enrich.fixture_gate import (
    fixture_gate,
    load_gate_builtins,
    load_gate_sample_graph,
)
from batho.modules.enrich.report import collect_enrich_artifacts, write_enrich_reports

__all__ = [
    "build_gap_report",
    "render_overview_md",
    "build_score_report",
    "render_score_md",
    "fixture_gate",
    "load_gate_builtins",
    "load_gate_sample_graph",
    "collect_enrich_artifacts",
    "write_enrich_reports",
]
