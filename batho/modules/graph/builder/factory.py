"""Graph backend factory and auto-selection heuristics.

Selects between the ``in-memory`` and ``arrow`` graph backends. ``auto``
resolution must happen via :func:`resolve_graph_backend` *before* calling
:func:`create_graph`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from batho.utils.logging import get_logger

if TYPE_CHECKING:
    from batho.modules.graph.builder.arrow_graph import ArrowGraph
    from batho.modules.graph.builder.codegraph import InMemoryGraph

LOGGER = get_logger(__name__, component="graph_factory")

# Heuristic: average entities produced per indexed file, used by the "auto"
# backend selection to estimate entity counts from candidate file counts.
AVG_ENTITIES_PER_FILE = 65

VALID_BACKENDS = ("in-memory", "arrow")


def resolve_graph_backend(
    config_backend: str,
    candidate_count: int,
    estimated_entities: int,
    auto_threshold_files: int = 500,
    auto_threshold_entities: int = 30_000,
) -> str:
    """Resolve an effective backend from configuration and workload size.

    Explicit selections (``"in-memory"`` / ``"arrow"``) pass through. ``"auto"``
    selects ``"arrow"`` when the candidate file count *or* the estimated entity
    count meets/exceeds the configured thresholds, otherwise ``"in-memory"``.
    """
    if config_backend in VALID_BACKENDS:
        return config_backend
    if (
        candidate_count >= auto_threshold_files
        or estimated_entities >= auto_threshold_entities
    ):
        return "arrow"
    return "in-memory"


def create_graph(
    backend: str,
    staging_dir: str | Path | None = None,
    arrow_config: dict[str, Any] | None = None,
) -> "InMemoryGraph | ArrowGraph":
    """Instantiate a graph backend.

    Args:
        backend: ``"in-memory"`` or ``"arrow"`` (resolve ``"auto"`` first via
            :func:`resolve_graph_backend`).
        staging_dir: Required for ``"arrow"``; staging area for Arrow IPC files.
        arrow_config: Optional ``graph.backend`` config block with
            ``arrow_flush_rows`` / ``arrow_flush_bytes_mb`` /
            ``arrow_recompact_delta_ratio`` overrides.

    Raises:
        ValueError: On unknown backend, ``"auto"``, or arrow without staging_dir.
    """
    if backend == "in-memory":
        from batho.modules.graph.builder.codegraph import InMemoryGraph

        return InMemoryGraph()
    if backend == "arrow":
        if staging_dir is None:
            raise ValueError("create_graph('arrow') requires a staging_dir")
        from batho.core.config.models import GraphBackendConfig
        from batho.modules.graph.builder.arrow_graph import ArrowGraph

        cfg = arrow_config or {}
        defaults = GraphBackendConfig()
        return ArrowGraph(
            staging_dir=staging_dir,
            flush_rows=int(cfg.get("arrow_flush_rows", defaults.arrow_flush_rows)),
            flush_bytes_mb=float(cfg.get("arrow_flush_bytes_mb", defaults.arrow_flush_bytes_mb)),
            recompact_delta_ratio=float(cfg.get("arrow_recompact_delta_ratio", defaults.arrow_recompact_delta_ratio)),
        )
    raise ValueError(
        f"Unknown graph backend: {backend!r}. "
        f"Resolve 'auto' via resolve_graph_backend() before calling create_graph()."
    )
