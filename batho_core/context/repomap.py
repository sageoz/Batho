"""
backend/context/repomap.py — Flat Symbol Index (RepoMap).

Production port from prototype with improvements:
- Uses pathlib.Path for cross-platform path normalization
- Renders file dependencies in hierarchical and compressed views
- Token-budget-capped rendering for LLM injection

Provides three rendering modes:
- render_full()       — aider-style indented text for dev inspection
- render_compressed() — token-budget-capped summary for LLM context
- render_json()       — structured dict for programmatic consumption
- render_hierarchical() — directory tree with symbols and dependencies
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from batho_core.config import REPOMAP_SCHEMA_VERSION
from batho_core.utils.logging import get_logger

from .categorizer import FileCategorizer, FileCategory
from .schema import Entity, EntityType

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def _text_tokens(text: str) -> int:
    """Estimate token count using 4-bytes-per-token heuristic."""
    return max(1, len(text.encode("utf-8")) // 4)


# ---------------------------------------------------------------------------
# RepoMap
# ---------------------------------------------------------------------------


@dataclass
class RepoMap:
    """
    Flat symbol index built from an InMemoryGraph.

    Provides multiple rendering modes optimized for different consumers:
    - LLMs (compressed, token-budgeted)
    - Developers (full aider-style)
    - Programmatic (JSON)
    - Memory files (hierarchical tree)

    Attributes:
        _root: Absolute workspace root used to normalise all paths at build time.
        _by_file: Mapping of relative_file_path → list[Entity] sorted by start_line.
        _dependencies: Mapping of relative_file_path → list[dep_module_or_rel_path].
    """

    _root: str = field(default="", repr=False)
    _by_file: dict[str, list[Entity]] = field(default_factory=dict, repr=False)
    _dependencies: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _logger: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._logger = get_logger(__name__, operation="repomap")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, graph: "object", root: str) -> "RepoMap":
        """
        Build a RepoMap from an InMemoryGraph.

        All file paths are normalised to be relative to *root* at
        construction time, so every rendering method produces compact,
        portable output without any absolute disk paths.

        Args:
            graph: An InMemoryGraph populated by CodeGraphIndexer.
            root: Absolute workspace root (output of ``Path.cwd().resolve()``).

        Returns:
            A fresh RepoMap instance with relative-path keys.
        """
        from .codegraph import InMemoryGraph
        from .schema import RelationshipType

        assert isinstance(graph, InMemoryGraph)

        root_path = Path(root)

        def _rel(p: str) -> str:
            """Convert absolute path *p* to a path relative to *root_path*."""
            try:
                return Path(p).relative_to(root_path).as_posix()
            except ValueError:
                return p  # already relative or outside root

        by_file: dict[str, list[Entity]] = defaultdict(list)
        for entity in graph.entities.values():
            by_file[_rel(entity.file)].append(entity)

        dependencies: dict[str, set[str]] = defaultdict(set)
        for rel in graph.relationships:
            if rel.type.name in ("IMPORTS", "CALLS", "USES"):
                source_ent = graph.get_entity(rel.source_id)
                target_ent = graph.get_entity(rel.target_id)

                if source_ent:
                    source_file = _rel(source_ent.file)
                    # target_file: normalise if it looks like an absolute path,
                    # else keep as module name (e.g. "os", "pathlib")
                    raw_target = target_ent.file if target_ent else rel.target_id
                    target_file = _rel(raw_target) if raw_target.startswith("/") else raw_target
                    if source_file != target_file:
                        dependencies[source_file].add(target_file)

        sorted_map: dict[str, list[Entity]] = {
            path: sorted(entities, key=lambda e: e.start_line)
            for path, entities in sorted(by_file.items())
        }
        sorted_deps: dict[str, list[str]] = {
            path: sorted(list(deps)) for path, deps in dependencies.items()
        }

        instance = cls(_root=root, _by_file=sorted_map, _dependencies=sorted_deps)
        instance._logger.debug(
            "repomap_built",
            root=root,
            file_count=len(sorted_map),
            entity_count=sum(len(v) for v in sorted_map.values()),
        )
        return instance

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_full(self) -> str:
        """
        Render a full aider-style indented symbol index.

        Format::

            src/auth/login.py:
              AuthToken (class) [L10-25]
              login(username: str, password: str) -> AuthToken (function) [L30-55]

        Returns:
            Multi-line string — the full repo symbol tree.
        """
        lines: list[str] = []
        for file_path, entities in self._by_file.items():
            lines.append(f"{file_path}:")
            for entity in entities:
                indent = "  "
                sig = entity.signature or entity.name
                type_label = str(entity.type)
                lines.append(
                    f"{indent}{sig} ({type_label}) [L{entity.start_line}-{entity.end_line}]"
                )
            deps = self._dependencies.get(file_path, [])
            if deps:
                lines.append(f"  deps: {', '.join(deps)}")
        return "\n".join(lines)

    def render_compressed(
        self, budget: int, fail_on_overflow: bool = True
    ) -> tuple[str, dict[str, int]]:
        """
        Render a token-budget-capped summary for LLM injection.

        Iterates files in sorted order, adding name (type) entries until
        the budget is exhausted. Signatures and line numbers are omitted.

        Args:
            budget: Maximum token budget for the output.

        Returns:
            (text, stats) where stats includes tokens_used, budget, truncated_files.
        """
        lines: list[str] = []
        tokens_used = 0
        truncated_files = 0

        for file_path, entities in self._by_file.items():
            file_header = f"{file_path}:"
            header_cost = _text_tokens(file_header)
            if tokens_used + header_cost > budget:
                truncated_files += len([f for f in self._by_file if f >= file_path])
                break

            lines.append(file_header)
            tokens_used += header_cost

            for entity in entities:
                entry = f"  {entity.name} ({entity.type})"
                cost = _text_tokens(entry)
                if tokens_used + cost > budget:
                    truncated_files += 1
                    break
                lines.append(entry)
                tokens_used += cost

        if truncated_files:
            if fail_on_overflow:
                raise ValueError(
                    f"Token budget exceeded (budget={budget}, used={tokens_used}); truncated_files={truncated_files}"
                )
            lines.append(f"  [...{truncated_files} more entries truncated]")

        self._logger.debug(
            "repomap_compressed",
            budget=budget,
            tokens_used=tokens_used,
            truncated=truncated_files > 0,
        )
        stats = {
            "tokens_used": tokens_used,
            "budget": budget,
            "truncated_files": truncated_files,
        }
        return "\n".join(lines), stats

    def render_json(self) -> dict[str, Any]:
        """
        Render the symbol index as a structured dictionary.

        Structure::

            {
              "files": {
                "src/auth/login.py": [
                  {"name": "login", "type": "function", "lines": [30, 55]},
                  ...
                ]
              },
              "dependencies": {"src/auth/login.py": ["pathlib", "os"]},
              "total_files": 1,
              "total_entities": 3
            }

        Returns:
            JSON-serialisable dict.
        """
        files_data: dict[str, list[dict[str, Any]]] = {}
        total_entities = 0

        for file_path, entities in self._by_file.items():
            file_entries: list[dict[str, Any]] = []
            for entity in entities:
                entry: dict[str, Any] = {
                    "name": entity.name,
                    "type": str(entity.type),
                    "lines": [entity.start_line, entity.end_line],
                }
                if entity.signature:
                    entry["signature"] = entity.signature
                doc = entity.metadata.get("docstring")
                if isinstance(doc, str) and doc:
                    entry["docstring"] = doc[:160]
                file_entries.append(entry)
                total_entities += 1
            files_data[file_path] = file_entries

        return {
            "schema_version": REPOMAP_SCHEMA_VERSION,
            "files": files_data,
            "dependencies": self._dependencies,
            "total_files": len(files_data),
            "total_entities": total_entities,
        }

    # ------------------------------------------------------------------
    # Directory tree rendering
    # ------------------------------------------------------------------

    def _get_directory_label(self, dir_path: str) -> str | None:
        """Get a descriptive label for a directory based on heuristics."""
        parts = dir_path.strip("/").split("/")
        if not parts or parts == [""]:
            return None
        last_part = parts[-1].lower()
        labels = {
            "tests": "Testing Suite",
            "test": "Testing Suite",
            "src": "Source Code",
            "docs": "Documentation",
            "scripts": "Scripts",
            "config": "Configuration",
            "configs": "Configuration",
            ".github": "CI/CD",
            "api": "API Layer",
            "models": "Data Models",
            "utils": "Utilities",
            "lib": "Library",
        }
        return labels.get(last_part)

    def group_by_directory(self) -> dict[str, list[tuple[str, list[Entity]]]]:
        """Group files by their directory path."""
        grouped: dict[str, list[tuple[str, list[Entity]]]] = defaultdict(list)
        for file_path, entities in self._by_file.items():
            # Use PurePosixPath for cross-platform consistency
            p = PurePosixPath(file_path)
            dir_path = str(p.parent) if p.parent != PurePosixPath(".") else ""
            grouped[dir_path].append((p.name, entities))
        for dir_path in grouped:
            grouped[dir_path].sort(key=lambda x: x[0])
        return dict(sorted(grouped.items()))

    def render_hierarchical(
        self,
        include_entities: bool = True,
    ) -> str:
        """
        Render a hierarchical directory tree with files and their entities.

        All paths are already relative to the workspace root (normalised at
        ``build()`` time), so no further stripping is required.

        Format::

            📁 src/auth/ (Source Code)
              📄 login.py
                deps: pathlib, os
                - login(username, password) -> AuthToken (function) [L10-20]

        Args:
            include_entities: If True, include entity details under each file.

        Returns:
            Multi-line string — the hierarchical directory tree.
        """
        lines: list[str] = []
        grouped = self.group_by_directory()

        for dir_path, files in grouped.items():
            display_path = dir_path if dir_path else "(root)"
            label = self._get_directory_label(dir_path)
            lines.append(f"📁 {display_path}/ ({label})" if label else f"📁 {display_path}/")

            for file_name, entities in files:
                lines.append(f"  📄 {file_name}")

                # Reconstruct relative file path for dep lookup
                full_path = f"{dir_path}/{file_name}" if dir_path else file_name
                deps: list[str] = self._dependencies.get(full_path, [])
                if deps:
                    lines.append(f"    deps: {', '.join(deps)}")

                if include_entities:
                    for entity in entities:
                        sig = entity.signature or entity.name
                        type_label = str(entity.type)
                        lines.append(
                            f"    - {sig} ({type_label}) [L{entity.start_line}-{entity.end_line}]"
                        )

        return "\n".join(lines)

    def render_tree_only(self) -> str:
        """Render just the directory tree structure without entity details."""
        return self.render_hierarchical(include_entities=False)

    # ------------------------------------------------------------------
    # File categorization
    # ------------------------------------------------------------------

    def categorize_files(self) -> dict[FileCategory, dict[str, list[Entity]]]:
        """
        Categorize all files by type (tests, docs, config, source).

        Returns:
            Dict mapping FileCategory to dict of file_path -> entities
        """
        categorizer = FileCategorizer()
        categorized: dict[FileCategory, dict[str, list[Entity]]] = {
            FileCategory.TESTS: {},
            FileCategory.DOCS: {},
            FileCategory.CONFIG: {},
            FileCategory.SOURCE: {},
            FileCategory.UNCATEGORIZED: {},
        }

        for file_path, entities in self._by_file.items():
            category = categorizer.categorize(file_path)
            categorized[category][file_path] = entities

        return categorized

    def render_category(
        self,
        category: FileCategory,
        include_full_entities: bool = False,
    ) -> str:
        """
        Render a specific category of files.

        Args:
            category: The FileCategory to render
            include_full_entities: If True, include full entity details with signatures

        Returns:
            Formatted markdown string for the category
        """
        categorized = self.categorize_files()
        files_data = categorized.get(category, {})

        if not files_data:
            return f"No {category} files found."

        lines: list[str] = []
        total_entities = sum(len(ents) for ents in files_data.values())

        if not include_full_entities:
            lines.append(f"## Summary")
            lines.append(f"- Total {category} files: {len(files_data)}")
            lines.append(f"- Total entities: {total_entities}")
            lines.append("")

        grouped = self._group_by_directory_for_files(files_data)

        for dir_path, files in grouped.items():
            display_path = dir_path if dir_path else "(root)"
            label = self._get_directory_label(dir_path)
            dir_header = f"📁 {display_path}/" + (f" ({label})" if label else "")
            lines.append(dir_header)

            for file_name, entities in files:
                file_path = f"{dir_path}/{file_name}" if dir_path else file_name
                if include_full_entities:
                    lines.append(f"  📄 {file_name}")
                    for entity in entities:
                        sig = entity.signature or entity.name
                        type_label = str(entity.type)
                        lines.append(
                            f"    - {sig} ({type_label}) [L{entity.start_line}-{entity.end_line}]"
                        )
                    deps = self._dependencies.get(file_path, [])
                    if deps:
                        lines.append(f"    deps: {', '.join(deps)}")
                else:
                    entity_count = len(entities)
                    entity_types = self._summarize_entity_types(entities)
                    lines.append(f"  📄 {file_name} ({entity_count} entities: {entity_types})")

            lines.append("")

        return "\n".join(lines)

    def _group_by_directory_for_files(
        self,
        files_data: dict[str, list[Entity]],
    ) -> dict[str, list[tuple[str, list[Entity]]]]:
        """Group files by directory for categorized output."""
        grouped: dict[str, list[tuple[str, list[Entity]]]] = defaultdict(list)
        for file_path, entities in files_data.items():
            p = PurePosixPath(file_path)
            dir_path = str(p.parent) if p.parent != PurePosixPath(".") else ""
            grouped[dir_path].append((p.name, entities))
        for dir_path in grouped:
            grouped[dir_path].sort(key=lambda x: x[0])
        return dict(sorted(grouped.items()))

    def _summarize_entity_types(self, entities: list[Entity]) -> str:
        """Summarize entity types in a file."""
        type_counts: dict[str, int] = defaultdict(int)
        for ent in entities:
            type_counts[str(ent.type)] += 1
        return ", ".join(f"{count} {name}" for name, count in sorted(type_counts.items()))

    # ------------------------------------------------------------------
    # Overview generator
    # ------------------------------------------------------------------

    def render_overview(
        self,
        stack_info: dict[str, Any] | None = None,
        repo_name: str | None = None,
        timestamp: str | None = None,
    ) -> str:
        """
        Generate comprehensive repository overview.

        Args:
            stack_info: Stack detection results from detect_stack()
            repo_name: Repository name (defaults to root directory name)
            timestamp: ISO timestamp for the index

        Returns:
            Full markdown overview document
        """
        from datetime import datetime, timezone

        if repo_name is None:
            repo_name = Path(self._root).name if self._root else "repository"
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        lines: list[str] = []
        lines.append(f"# 📊 {repo_name} - Repository Overview")
        lines.append("")
        lines.append(f"*Generated: {timestamp}*")
        lines.append("")

        categorized = self.categorize_files()
        total_files = len(self._by_file)
        total_entities = self.entity_count
        total_relationships = sum(len(deps) for deps in self._dependencies.values())

        lines.append("## Repository Summary")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total Files | {total_files} |")
        lines.append(f"| Total Entities | {total_entities} |")
        lines.append(f"| Total Relationships | {total_relationships} |")
        lines.append("")

        lines.append("## File Distribution")
        lines.append("")
        cat_counts = {cat: len(files) for cat, files in categorized.items()}
        cat_entities = {
            cat: sum(len(ents) for ents in files.values()) for cat, files in categorized.items()
        }

        for cat in [
            FileCategory.SOURCE,
            FileCategory.TESTS,
            FileCategory.DOCS,
            FileCategory.CONFIG,
            FileCategory.UNCATEGORIZED,
        ]:
            count = cat_counts.get(cat, 0)
            entities = cat_entities.get(cat, 0)
            pct = (count / total_files * 100) if total_files > 0 else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            lines.append(f"- **{cat.name}**: {count} files ({pct:.1f}%) | {entities} entities")
        lines.append("")

        lines.append("## Language Breakdown")
        lines.append("")
        lang_counts = self._count_by_language()
        if lang_counts:
            lines.append("| Language | Files | Percentage |")
            lines.append("|----------|-------|------------|")
            for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
                pct = (count / total_files * 100) if total_files > 0 else 0
                lines.append(f"| {lang} | {count} | {pct:.1f}% |")
            primary = max(lang_counts.items(), key=lambda x: x[1])[0] if lang_counts else "N/A"
            lines.append(f"\n**Primary Language**: {primary}")
        else:
            lines.append("No language data available.")
        lines.append("")

        if stack_info:
            lines.append("## Technology Stack")
            lines.append("")
            categories = {
                "backend": "Backend",
                "frontend": "Frontend",
                "database": "Database",
                "devops": "DevOps",
                "testing": "Testing",
                "tools": "Tools",
            }
            for cat_key, cat_label in categories.items():
                items = stack_info.get(cat_key, [])
                if items:
                    lines.append(f"### {cat_label}")
                    for item in items:
                        lines.append(f"- {item}")
                    lines.append("")

        lines.append("## Directory Structure")
        lines.append("")
        tree_lines = self._render_high_level_tree(max_depth=3)
        for line in tree_lines:
            lines.append(line)
        lines.append("")

        lines.append("## Entity Statistics")
        lines.append("")
        lines.append("| Entity Type | Count |")
        lines.append("|-------------|-------|")
        type_counts: dict[str, int] = defaultdict(int)
        for entities in self._by_file.values():
            for ent in entities:
                type_counts[str(ent.type)] += 1
        for ent_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {ent_type} | {count} |")
        lines.append("")

        lines.append("## Top Dependencies")
        lines.append("")
        all_deps: dict[str, int] = defaultdict(int)
        for deps in self._dependencies.values():
            for dep in deps:
                all_deps[dep] += 1
        top_deps = sorted(all_deps.items(), key=lambda x: -x[1])[:10]
        if top_deps:
            lines.append("| Dependency | References |")
            lines.append("|------------|------------|")
            for dep, count in top_deps:
                lines.append(f"| {dep} | {count} |")
        else:
            lines.append("No dependency data available.")
        lines.append("")

        return "\n".join(lines)

    def _count_by_language(self) -> dict[str, int]:
        """Count files by detected language."""
        lang_counts: dict[str, int] = {}
        ext_to_lang = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript (React)",
            ".jsx": "JavaScript (React)",
            ".go": "Go",
            ".rs": "Rust",
            ".java": "Java",
            ".rb": "Ruby",
            ".php": "PHP",
            ".cs": "C#",
            ".kt": "Kotlin",
            ".swift": "Swift",
            ".scala": "Scala",
            ".c": "C",
            ".cpp": "C++",
            ".h": "C/C++ Header",
            ".hpp": "C++ Header",
            ".m": "Objective-C",
            ".mm": "Objective-C++",
            ".sh": "Shell",
            ".bash": "Bash",
            ".zsh": "Zsh",
            ".mjs": "ES Module",
            ".cjs": "CommonJS",
        }
        for file_path in self._by_file.keys():
            ext = Path(file_path).suffix.lower()
            lang = ext_to_lang.get(ext, ext.lstrip(".").upper() if ext else "Other")
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        return lang_counts

    def _render_high_level_tree(self, max_depth: int = 3) -> list[str]:
        """Render a high-level directory tree."""
        lines: list[str] = []
        grouped = self.group_by_directory()

        def get_depth(path: str) -> int:
            return len([p for p in path.split("/") if p])

        for dir_path, files in sorted(grouped.items()):
            depth = get_depth(dir_path)
            if depth > max_depth:
                continue

            indent = "  " * depth
            label = self._get_directory_label(dir_path)
            dir_name = dir_path.split("/")[-1] if dir_path else "root"

            if depth == 0:
                lines.append(f"📁 {dir_name}/")
            else:
                lines.append(
                    f"{indent}📁 {dir_name}/ ({label})" if label else f"{indent}📁 {dir_name}/"
                )

            if depth < max_depth:
                file_indent = "  " * (depth + 1)
                for file_name, _ in sorted(files)[:5]:
                    lines.append(f"{file_indent}📄 {file_name}")
                if len(files) > 5:
                    lines.append(f"{file_indent}... and {len(files) - 5} more")

        return lines

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def estimate_tokens(self) -> int:
        """Estimate the token count of the full render_full() output."""
        if not self._by_file:
            return 0
        return _text_tokens(self.render_full())

    @property
    def file_count(self) -> int:
        """Number of source files in this map."""
        return len(self._by_file)

    @property
    def entity_count(self) -> int:
        """Total number of entities across all files."""
        return sum(len(v) for v in self._by_file.values())
