"""Cross-repo index for fast BSG lookup."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Iterable

from batho.bridge.models import CrossRepoConfig


@dataclass(frozen=True)
class NodeRef:
    node_id: str
    name: str
    fqn: str
    kind: str
    file: str
    start_line: int
    end_line: int
    signature: str


@dataclass
class WorkspaceIndex:
    workspace_id: str
    file_mtime_ns: int
    file_size: int
    nodes_by_id: dict[str, NodeRef]
    name_index: dict[str, list[str]]
    fqn_segments: dict[str, list[str]]
    trigram_index: dict[str, set[str]]
    kind_index: dict[str, set[str]]
    built_at: float
    approx_bytes: int


@dataclass
class CrossRepoIndexStats:
    total_workspaces: int = 0
    total_nodes: int = 0
    total_bytes: int = 0
    workspaces: dict[str, dict[str, int]] = field(default_factory=dict)


class CrossRepoIndex:
    """Lazy, per-workspace in-memory index for cross-repo search."""

    def __init__(self, config: CrossRepoConfig, *, max_index_bytes: int) -> None:
        self._config = config
        self._max_index_bytes = max_index_bytes
        self._indexes: dict[str, WorkspaceIndex] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled)

    async def ensure_workspace(
        self,
        workspace_id: str,
        *,
        nodes: list[NodeRef],
        file_mtime_ns: int,
        file_size: int,
    ) -> None:
        """Ensure a workspace index is built and current."""
        lock = self._locks.setdefault(workspace_id, asyncio.Lock())
        async with lock:
            existing = self._indexes.get(workspace_id)
            if existing and existing.file_mtime_ns == file_mtime_ns and existing.file_size == file_size:
                return

            index = self._build_index(workspace_id, nodes, file_mtime_ns, file_size)
            self._indexes[workspace_id] = index

    def invalidate_workspace(self, workspace_id: str) -> None:
        """Drop cached index for a workspace."""
        self._indexes.pop(workspace_id, None)

    def stats(self) -> CrossRepoIndexStats:
        total_nodes = 0
        total_bytes = 0
        workspaces: dict[str, dict[str, int]] = {}
        for ws_id, index in self._indexes.items():
            node_count = len(index.nodes_by_id)
            total_nodes += node_count
            total_bytes += index.approx_bytes
            workspaces[ws_id] = {
                "nodes": node_count,
                "bytes": index.approx_bytes,
            }

        return CrossRepoIndexStats(
            total_workspaces=len(self._indexes),
            total_nodes=total_nodes,
            total_bytes=total_bytes,
            workspaces=workspaces,
        )

    def search(
        self,
        workspace_id: str,
        *,
        query: str,
        kinds: set[str] | None,
        limit_per_ws: int,
        score_fn,
    ) -> list[tuple[NodeRef, float]]:
        """Search a single workspace index and return scored hits."""
        index = self._indexes.get(workspace_id)
        if not index:
            return []

        query_lower = query.lower().strip()
        if not query_lower:
            return []

        candidate_ids = set()

        # Exact name match.
        for node_id in index.name_index.get(query_lower, []):
            candidate_ids.add(node_id)

        # Exact FQN segment match.
        for node_id in index.fqn_segments.get(query_lower, []):
            candidate_ids.add(node_id)

        # Trigram substring probe when we still need candidates.
        if len(candidate_ids) < limit_per_ws:
            trigram_ids = self._probe_trigrams(index.trigram_index, query_lower)
            candidate_ids.update(trigram_ids)

        if kinds:
            allowed: set[str] = set()
            for kind in kinds:
                allowed.update(index.kind_index.get(kind, set()))
            candidate_ids = candidate_ids & allowed if allowed else set()

        # Fallback to full scan if we have no candidates.
        if not candidate_ids:
            candidate_ids = set(index.nodes_by_id.keys())

        scored: list[tuple[NodeRef, float]] = []
        for node_id in candidate_ids:
            node = index.nodes_by_id.get(node_id)
            if not node:
                continue
            score = score_fn(query_lower, node)
            if score <= 0:
                continue
            scored.append((node, score))

        scored.sort(key=lambda item: (-item[1], len(item[0].name)))
        return scored[:limit_per_ws]

    def symbols(
        self,
        workspace_id: str,
        *,
        name: str,
        kinds: set[str] | None,
    ) -> list[NodeRef]:
        """Return exact name matches for a workspace."""
        index = self._indexes.get(workspace_id)
        if not index:
            return []

        name_lower = name.lower().strip()
        if not name_lower:
            return []

        node_ids = index.name_index.get(name_lower, [])
        if kinds:
            allowed: set[str] = set()
            for kind in kinds:
                allowed.update(index.kind_index.get(kind, set()))
            node_ids = [nid for nid in node_ids if nid in allowed]

        return [index.nodes_by_id[nid] for nid in node_ids if nid in index.nodes_by_id]

    def _build_index(
        self,
        workspace_id: str,
        nodes: Iterable[NodeRef],
        file_mtime_ns: int,
        file_size: int,
    ) -> WorkspaceIndex:
        name_index: dict[str, list[str]] = {}
        fqn_segments: dict[str, list[str]] = {}
        trigram_index: dict[str, set[str]] = {}
        kind_index: dict[str, set[str]] = {}
        nodes_by_id: dict[str, NodeRef] = {}

        for node in nodes:
            if not node.name:
                continue
            nodes_by_id[node.node_id] = node
            name_key = node.name.lower()
            name_index.setdefault(name_key, []).append(node.node_id)

            if node.fqn:
                for segment in node.fqn.split("."):
                    if not segment:
                        continue
                    fqn_segments.setdefault(segment.lower(), []).append(node.node_id)

            kind_key = node.kind.lower() if node.kind else ""
            if kind_key:
                kind_index.setdefault(kind_key, set()).add(node.node_id)

            for trigram in _trigrams(name_key):
                trigram_index.setdefault(trigram, set()).add(node.node_id)

        approx_bytes = _estimate_index_bytes(name_index, fqn_segments, trigram_index, kind_index)

        # Drop trigram index if we exceed the budget.
        if self._max_index_bytes > 0 and approx_bytes > self._max_index_bytes:
            trigram_index = {}
            approx_bytes = _estimate_index_bytes(name_index, fqn_segments, trigram_index, kind_index)

        return WorkspaceIndex(
            workspace_id=workspace_id,
            file_mtime_ns=file_mtime_ns,
            file_size=file_size,
            nodes_by_id=nodes_by_id,
            name_index=name_index,
            fqn_segments=fqn_segments,
            trigram_index=trigram_index,
            kind_index=kind_index,
            built_at=time.time(),
            approx_bytes=approx_bytes,
        )

    @staticmethod
    def _probe_trigrams(trigram_index: dict[str, set[str]], query: str) -> set[str]:
        if not trigram_index or len(query) < 3:
            return set()
        trigrams = _trigrams(query)
        if not trigrams:
            return set()
        candidate: set[str] | None = None
        for tri in trigrams:
            ids = trigram_index.get(tri)
            if not ids:
                continue
            if candidate is None:
                candidate = set(ids)
            else:
                candidate &= ids
        return candidate or set()


def _trigrams(text: str) -> list[str]:
    return [text[i : i + 3] for i in range(len(text) - 2)]


def _estimate_index_bytes(
    name_index: dict[str, list[str]],
    fqn_segments: dict[str, list[str]],
    trigram_index: dict[str, set[str]],
    kind_index: dict[str, set[str]],
) -> int:
    total = 0
    total += sum(len(k) + len(v) * 8 for k, v in name_index.items())
    total += sum(len(k) + len(v) * 8 for k, v in fqn_segments.items())
    total += sum(len(k) + len(v) * 4 for k, v in trigram_index.items())
    total += sum(len(k) + len(v) * 4 for k, v in kind_index.items())
    return total


__all__ = [
    "CrossRepoIndex",
    "CrossRepoIndexStats",
    "NodeRef",
    "WorkspaceIndex",
]
