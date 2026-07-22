"""Graph module re-exports."""
from .builder.codegraph import (
    InMemoryGraph as InMemoryGraph,
    IncrementalGraphUpdater as IncrementalGraphUpdater,
    CodeGraphIndexer as CodeGraphIndexer,
)
from .builder.arrow_graph import ArrowGraph as ArrowGraph
from .builder.factory import (
    create_graph as create_graph,
    resolve_graph_backend as resolve_graph_backend,
)
from .builder.protocol import GraphBackend as GraphBackend
from .reconstructor.reconstructor import FileReconstructor as FileReconstructor
from .diff_engine.node_diff import NodeDiff as NodeDiff, diff_file_nodes as diff_file_nodes
from .incremental import (
    is_git_repo as is_git_repo,
    get_head_commit as get_head_commit,
    get_current_branch as get_current_branch,
)
from .community import (
    Community as Community,
    detect_communities as detect_communities,
    communities_to_rows as communities_to_rows,
)

__all__ = [
    "InMemoryGraph",
    "ArrowGraph",
    "GraphBackend",
    "create_graph",
    "resolve_graph_backend",
    "IncrementalGraphUpdater",
    "CodeGraphIndexer",
    "FileReconstructor",
    "NodeDiff",
    "diff_file_nodes",
    "is_git_repo",
    "get_head_commit",
    "get_current_branch",
    "Community",
    "detect_communities",
    "communities_to_rows",
]
