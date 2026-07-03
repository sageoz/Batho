"""Graph module re-exports."""
from .builder.codegraph import (
    InMemoryGraph as InMemoryGraph,
    IncrementalGraphUpdater as IncrementalGraphUpdater,
    CodeGraphIndexer as CodeGraphIndexer,
)
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
