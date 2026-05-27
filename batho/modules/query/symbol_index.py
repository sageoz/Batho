"""Global symbol index for fast cross-file resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from batho.core.schemas import EntityType

if TYPE_CHECKING:
    from .codegraph import InMemoryGraph


@dataclass(frozen=True)
class SymbolIndex:
    """
    Deterministic lookup index for symbol names.

    The index stores direct names and common aliases (tail and module stem) so
    import/reference resolution can use O(1) lookups instead of repeated scans.
    """

    names: dict[str, tuple[str, ...]]
    names_lower: dict[str, tuple[str, ...]]
    files_by_id: dict[str, str]
    names_by_id: dict[str, str]

    @classmethod
    def build(cls, graph: "InMemoryGraph") -> "SymbolIndex":
        names: dict[str, list[str]] = {}
        names_lower: dict[str, list[str]] = {}
        files_by_id: dict[str, str] = {}
        names_by_id: dict[str, str] = {}

        def _add(token: str, entity_id: str) -> None:
            normalized = token.strip()
            if not normalized:
                return
            names.setdefault(normalized, []).append(entity_id)
            names_lower.setdefault(normalized.lower(), []).append(entity_id)

        # Preserve existing deterministic behavior by building from sorted IDs.
        for entity in sorted(graph.entities.values(), key=lambda item: item.id):
            # Skip UNRESOLVED entities — they are placeholders, not real symbols
            if entity.type == EntityType.UNRESOLVED:
                continue
            files_by_id[entity.id] = entity.file
            names_by_id[entity.id] = entity.name
            _add(entity.name, entity.id)

            if "." in entity.name:
                _add(entity.name.split(".")[-1], entity.id)

            if entity.type == EntityType.MODULE:
                _add(Path(entity.file).stem, entity.id)

        normalized_names: dict[str, tuple[str, ...]] = {
            token: tuple(sorted(set(ids))) for token, ids in names.items()
        }
        normalized_names_lower: dict[str, tuple[str, ...]] = {
            token: tuple(sorted(set(ids))) for token, ids in names_lower.items()
        }

        return cls(
            names=normalized_names,
            names_lower=normalized_names_lower,
            files_by_id=files_by_id,
            names_by_id=names_by_id,
        )

    @staticmethod
    def _shared_dir_depth(source: str, target: str) -> int:
        source_parts = Path(source).parts[:-1]
        target_parts = Path(target).parts[:-1]
        depth = 0
        for source_part, target_part in zip(source_parts, target_parts):
            if source_part != target_part:
                break
            depth += 1
        return depth

    def _choose_best(
        self,
        candidate_ids: tuple[str, ...],
        source_file: str | None,
    ) -> str | None:
        if not candidate_ids:
            return None
        if len(candidate_ids) == 1:
            return candidate_ids[0]

        def _score(entity_id: str) -> tuple[int, int, str]:
            target_file = self.files_by_id.get(entity_id, "")
            score = 0
            if source_file and target_file:
                if source_file == target_file:
                    score += 1000
                score += self._shared_dir_depth(source_file, target_file) * 10
            # Prefer shorter qualified names on ties; then stable ID ordering.
            name_len = len(self.names_by_id.get(entity_id, ""))
            return (score, -name_len, entity_id)

        best = max(candidate_ids, key=_score)
        return best

    def resolve_candidates(
        self,
        candidates: list[str],
        source_file: str | None = None,
        fuzzy_matching: bool = False,
    ) -> str | None:
        for candidate in candidates:
            target_ids = self.names.get(candidate)
            if target_ids:
                return self._choose_best(target_ids, source_file)

        if fuzzy_matching:
            for candidate in candidates:
                target_ids = self.names_lower.get(candidate.lower())
                if target_ids:
                    return self._choose_best(target_ids, source_file)
        return None

    @property
    def size(self) -> int:
        return len(self.names)
