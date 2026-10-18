"""tests/golden/harness.py — T27: golden-metadata harness (spec §11).

Builds a fixture repo, captures the artifact's entity/relationship counts
and full ``metadata_json`` distributions, and compares against stored
goldens. Used as the exit gate for every migration phase — any semantic
drift shows up as a distribution diff with per-file attribution.

Usage:
    capture_distribution(root)  -> dict of distributions
    compare_golden(golden, actual) -> list of diff lines (empty = match)
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def _norm_id(eid: str, root: Path) -> str:
    """Strip the absolute root prefix so goldens are repo-location stable."""
    eid = str(eid)
    root_str = str(root.resolve())
    if eid.startswith(root_str):
        eid = eid[len(root_str):].lstrip("/")
    return eid


def build_fixture(root: Path) -> bool:
    """Full build of the fixture repo. Returns success."""
    from batho.orchestrator.build import BuildOptions, run_build

    result = run_build(BuildOptions(root=root, force_full=True))
    return bool(result.success)


def capture_distribution(root: Path) -> dict[str, Any]:
    """Read the latest artifact and return the full metadata distribution."""
    import glob as _glob

    import pyarrow.ipc as ipc

    artifact_dir = Path(root) / ".batho" / "artifact"

    # file_id -> repo-relative path map for per-file attribution
    file_map: dict[int, str] = {}
    for fp in sorted(_glob.glob(str(artifact_dir / "file_tracking.v*.ipc"))):
        ft = ipc.open_file(fp).read_all()
        for i in range(ft.num_rows):
            file_map[int(ft["file_id"][i].as_py())] = str(ft["file_path"][i].as_py())
        break

    files = sorted(_glob.glob(str(artifact_dir / "agent_views.v*.ipc")))
    if not files:
        raise FileNotFoundError(f"no agent_views artifact under {artifact_dir}")
    t = ipc.open_file(files[-1]).read_all()

    meta_keys: Counter = Counter()
    categories: Counter = Counter()
    languages: Counter = Counter()
    bsg_language: Counter = Counter()
    usn: Counter = Counter()
    per_file_entities: Counter = Counter()
    rel_types: Counter = Counter()
    access: Counter = Counter()

    for i in range(t.num_rows):
        fpath = file_map.get(int(t["file_id"][i].as_py()), "?")
        per_file_entities[fpath] += 1
        m = t["metadata_json"][i].as_py()
        if not m:
            continue
        try:
            d = json.loads(m)
        except Exception:
            continue
        for k in d:
            meta_keys[k] += 1
        if d.get("bsg.category"):
            categories[str(d["bsg.category"])] += 1
        if d.get("language"):
            languages[str(d["language"])] += 1
        if d.get("bsg.language"):
            bsg_language[str(d["bsg.language"])] += 1
        if d.get("access_type"):
            access[str(d["access_type"])] += 1
        for u in d.get("bsg.usn") or []:
            usn[str(u)] += 1

    return {
        "entity_count": int(t.num_rows),
        "metadata_keys": dict(sorted(meta_keys.items())),
        "bsg.category": dict(sorted(categories.items())),
        "language": dict(sorted(languages.items())),
        "bsg.language": dict(sorted(bsg_language.items())),
        "access_type": dict(sorted(access.items())),
        "bsg.usn": dict(sorted(usn.items())),
        "per_file_entities": dict(sorted(per_file_entities.items())),
    }


def capture_relationship_counts(root: Path) -> dict[str, int]:
    """Relationship type counts from the rels artifact (best-effort)."""
    import glob as _glob

    import pyarrow.ipc as ipc

    artifact_dir = Path(root) / ".batho" / "artifact"
    files = sorted(_glob.glob(str(artifact_dir / "rels_views.v*.ipc")))
    if not files:
        return {}
    t = ipc.open_file(files[-1]).read_all()
    rel_types: Counter = Counter()
    col = "relation_type" if "relation_type" in t.column_names else (
        "type" if "type" in t.column_names else None
    )
    if col:
        for i in range(t.num_rows):
            rel_types[str(t[col][i].as_py())] += 1
    return {"rel_count": int(t.num_rows), "rel_types": dict(sorted(rel_types.items()))}


def compare_golden(golden: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Exact-match comparison. Returns a list of human-readable diff lines."""
    diffs: list[str] = []
    all_keys = set(golden) | set(actual)
    for section in sorted(all_keys):
        g, a = golden.get(section), actual.get(section)
        if g == a:
            continue
        if not isinstance(g, dict) or not isinstance(a, dict):
            diffs.append(f"{section}: golden={g!r} actual={a!r}")
            continue
        for k in sorted(set(g) | set(a)):
            gv, av = g.get(k), a.get(k)
            if gv != av:
                diffs.append(f"{section}.{k}: golden={gv!r} actual={av!r}")
    return diffs


def save_golden(dist: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dist, indent=2, sort_keys=True) + "\n")


def load_golden(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
