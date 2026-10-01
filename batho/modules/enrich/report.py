"""`.batho/report/` writer — human/agent-readable build reports.

After each build/patch the gap profile and rule fitness score are rendered
to markdown:

    .batho/report/overview.md  — context_overview + gap profile (merged)
    .batho/report/score.md     — rule fitness table + plugin rollup

The batho-calibrate skill reads these files; they also serve humans directly.
Both files are rewritten every run — when a payload is unavailable a stub
is written so a stale report from an earlier run can't masquerade as fresh.
"""

from __future__ import annotations

from pathlib import Path

from batho.utils.logging import get_logger

from batho.modules.enrich.gap_report import render_overview_md
from batho.modules.enrich.scoring import render_score_md

LOGGER = get_logger(__name__, component="enrich_report")

REPORT_DIR = ".batho/report"

_OVERVIEW_STUB = (
    "# Graph Overview\n\n_profile unavailable — the enrich gap report "
    "failed for this run; see logs for `enrich_profile_failed`._\n"
)
_SCORE_STUB = (
    "# Rule Fitness Score\n\n_no rule telemetry — rules disabled, or no "
    "rule_stats history yet._\n"
)


def collect_enrich_artifacts(
    db,
    run_internal_id: int,
    run_uuid: str,
    root: Path,
    rule_stats_payload: dict | None = None,
    entity_count: int | None = None,
    preloaded=None,
) -> dict:
    """Compute `enrich_profile` + `enrich_score` payloads for a run.

    Best-effort: failures log a warning and return partial/empty artifacts —
    enrichment reporting must never fail a build. Called before
    `finalize_run_artifacts` (columns are written in the same row); the
    current run's rule_stats is injected via `rule_stats_payload` and its
    entity count via `entity_count` since the row isn't flushed yet.

    The artifact graph is loaded once (agent view only — storage blobs are
    not needed) and shared between the two reports. Callers that already
    hold a loaded graph tuple (e.g. `plugins apply`, whose in-memory graph
    is already the post-apply view) pass `preloaded` to skip the reload.
    """
    from batho.modules.enrich.gap_report import build_gap_report
    from batho.modules.enrich.scoring import build_score_report

    if preloaded is None:
        try:
            from batho.orchestrator.plugins_apply import _load_graph_from_artifact

            preloaded = _load_graph_from_artifact(
                db, run_internal_id, root, include_storage=False
            )
        except Exception as exc:
            LOGGER.warning("enrich_graph_load_failed", error=str(exc))

    profile = None
    score = None
    try:
        profile = build_gap_report(
            db, run_internal_id, run_uuid, root, preloaded=preloaded
        )
    except Exception as exc:
        LOGGER.warning("enrich_profile_failed", error=str(exc))
    try:
        extra = (
            {"run_uuid": run_uuid, "stats": rule_stats_payload}
            if rule_stats_payload
            else None
        )
        score = build_score_report(
            db,
            root,
            extra_telemetry=extra,
            entity_count=entity_count,
            preloaded=preloaded,
        )
    except Exception as exc:
        LOGGER.warning("enrich_score_failed", error=str(exc))
    return {"enrich_profile": profile, "enrich_score": score}


def write_enrich_reports(
    root: Path,
    profile: dict | None = None,
    score: dict | None = None,
    context_overview: dict | None = None,
) -> dict[str, str]:
    """Render + write `.batho/report/` markdown files.

    Returns a map of report name → written path. Absent payloads are
    rendered as stubs so reports never lag a run behind reality.
    """
    written: dict[str, str] = {}
    report_dir = root / REPORT_DIR
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        LOGGER.warning("enrich_report_write_failed", error=str(exc))
        return written
    payloads = (
        ("overview", render_overview_md(profile, context_overview)
         if profile is not None else _OVERVIEW_STUB),
        ("score", render_score_md(score) if score is not None else _SCORE_STUB),
    )
    for name, content in payloads:
        p = report_dir / f"{name}.md"
        tmp = report_dir / f".{name}.md.tmp"
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(p)
            written[name] = str(p)
        except Exception as exc:
            LOGGER.warning("enrich_report_write_failed", error=str(exc))
    return written
