"""Render a GitHub Step Summary from a Batho output directory.

Reads `<output-dir>/index.json` and the current index entry, plus the sizes of
the produced artifacts, and appends a markdown summary to the file given by
`--summary-file` (typically `$GITHUB_STEP_SUMMARY`).

Designed to be dependency-free (stdlib only) so it can run before Batho's own
Python env is activated.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _human_bytes(n: int | float | None) -> str:
    if n is None:
        return "n/a"
    try:
        size = float(n)
    except (TypeError, ValueError):
        return "n/a"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _artifact_rows(index_dir: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if not index_dir.is_dir():
        return rows
    for name in ("graph.json", "bsg.json", "overview.md", "files.md"):
        p = index_dir / name
        if p.exists():
            rows.append((name, _human_bytes(p.stat().st_size)))
    return rows


def _count_bsg_entities(bsg_path: Path) -> int | None:
    data = _load_json(bsg_path)
    if not data:
        return None
    entities = data.get("entities")
    if isinstance(entities, list):
        return len(entities)
    nodes = data.get("nodes")
    if isinstance(nodes, list):
        return len(nodes)
    return None


def render(output_dir: Path, index_id: str | None) -> str:
    lines: list[str] = []
    lines.append("## Batho Index")
    lines.append("")

    index_meta = _load_json(output_dir / "index.json") or {}
    if not index_id:
        index_id = str(index_meta.get("current_index_id") or "").strip() or None

    if not index_id:
        lines.append(
            "Batho produced no index (no `current_index_id` found in "
            f"`{output_dir}/index.json`)."
        )
        return "\n".join(lines) + "\n"

    indexes = index_meta.get("indexes") or {}
    entry = indexes.get(index_id) or {}
    stats = entry.get("stats") or {}
    metrics = entry.get("metrics") or {}

    lines.append(f"- **Index id:** `{index_id}`")
    created = entry.get("created_at") or entry.get("timestamp")
    if created:
        lines.append(f"- **Created:** `{created}`")

    lines.append("")
    lines.append("### Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(
        f"| Files indexed | {_fmt(stats.get('file_count') or metrics.get('file_count'))} |"
    )
    lines.append(
        f"| Entities | {_fmt(stats.get('entity_count') or metrics.get('entity_count'))} |"
    )
    lines.append(
        f"| Relationships | {_fmt(stats.get('relationship_count') or metrics.get('relationship_count'))} |"
    )
    lines.append(
        f"| LOC total | {_fmt(stats.get('loc_total') or metrics.get('loc_total'))} |"
    )
    repo_bytes = stats.get("repo_size_bytes") or metrics.get("repo_size_bytes")
    lines.append(f"| Repo size | {_human_bytes(repo_bytes)} |")
    cr = metrics.get("compression_ratio")
    if cr is not None:
        lines.append(f"| BSG compression ratio | {_fmt(cr)} |")
    chr_ = metrics.get("cache_hit_rate")
    if chr_ is not None:
        lines.append(f"| Cache hit rate | {_fmt(chr_)} |")

    index_dir = output_dir / index_id
    bsg_entities = _count_bsg_entities(index_dir / "bsg.json")
    if bsg_entities is not None:
        lines.append(f"| BSG entities | {bsg_entities} |")

    artifact_rows = _artifact_rows(index_dir)
    if artifact_rows:
        lines.append("")
        lines.append("### Artifacts")
        lines.append("")
        lines.append("| File | Size |")
        lines.append("| --- | --- |")
        for name, size in artifact_rows:
            lines.append(f"| `{index_id}/{name}` | {size} |")

    lines.append("")
    lines.append(
        "_Full outputs are attached as a workflow artifact (see the run's Artifacts panel)._"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Path to Batho output dir (usually `<repo>/.ctn`).",
    )
    parser.add_argument(
        "--index-id",
        default="",
        help="Optional explicit index id. If empty, read from index.json.",
    )
    parser.add_argument(
        "--summary-file",
        default=os.environ.get("GITHUB_STEP_SUMMARY", ""),
        help="File to append the markdown summary to (default: $GITHUB_STEP_SUMMARY).",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    markdown = render(output_dir, args.index_id or None)

    if args.summary_file:
        try:
            with open(args.summary_file, "a", encoding="utf-8") as fh:
                fh.write(markdown)
        except OSError as exc:
            print(f"render_summary: failed to write summary file: {exc}", file=sys.stderr)
            sys.stdout.write(markdown)
            return 0
    else:
        sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
