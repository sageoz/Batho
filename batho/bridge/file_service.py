"""File service for safe file content retrieval with BSG entity mapping.

Provides secure file reading with path traversal protection and
optional BSG entity enrichment for semantic file viewing.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from batho.utils.encoding import read_text_with_fallback
from batho.utils.ignore import should_ignore_path
from batho.utils.logging import get_logger

if TYPE_CHECKING:
    pass

LOGGER = get_logger(__name__, component="bridge")


class SecurityError(Exception):
    """Raised when file access violates security constraints."""
    pass


class FileNotFoundError(Exception):
    """Raised when file does not exist."""
    pass


def safe_read_file(requested_path: str, root: Path | str) -> str:
    """
    Safely read a file from within the project root.

    Args:
        requested_path: Relative path to the file (e.g., "src/main.py")
        root: Project root directory

    Returns:
        File content as string

    Raises:
        SecurityError: If path traversal or ignored file detected
        FileNotFoundError: If file doesn't exist
    """
    root_path = Path(root).resolve()

    # Security: Block absolute paths (they start with / on Unix or drive letter on Windows)
    if requested_path.startswith("/"):
        LOGGER.warning(
            "path_traversal_blocked",
            requested=requested_path,
            pattern="absolute path",
        )
        raise SecurityError(f"Path outside project root: {requested_path}")

    # Normalize the requested path
    # Remove leading ./ but preserve .. for traversal detection
    clean_path = requested_path
    if clean_path.startswith("./"):
        clean_path = clean_path[2:]

    # Security: Check for path traversal patterns before resolving
    # Check for .. at start or anywhere in path
    if clean_path.startswith("../") or "/../" in clean_path or clean_path.endswith("/.."):
        LOGGER.warning(
            "path_traversal_blocked",
            requested=requested_path,
            pattern=".. detected",
        )
        raise SecurityError(f"Path outside project root: {requested_path}")
    # Also check for .. as a standalone component
    path_parts = clean_path.split("/")
    if ".." in path_parts:
        LOGGER.warning(
            "path_traversal_blocked",
            requested=requested_path,
            pattern=".. detected in path components",
        )
        raise SecurityError(f"Path outside project root: {requested_path}")

    # Build and resolve full path
    full_path = (root_path / clean_path).resolve()

    # Security: Ensure resolved path is within project root
    # This catches symlinks pointing outside, absolute paths, etc.
    try:
        full_path.relative_to(root_path)
    except ValueError:
        LOGGER.warning(
            "path_traversal_blocked",
            requested=requested_path,
            resolved=str(full_path),
            root=str(root_path),
        )
        raise SecurityError(f"Path outside project root: {requested_path}")

    # Security: Check if file is ignored by .bathoignore
    # Note: include_hidden=False because hidden files like .pre-commit-config.yaml
    # are legitimate source files that users should be able to view
    if should_ignore_path(full_path, root_path, include_hidden=False):
        LOGGER.warning(
            "ignored_file_blocked",
            path=str(full_path),
        )
        raise SecurityError(f"File is ignored: {requested_path}")

    # Check file exists and is a file
    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {requested_path}")

    if not full_path.is_file():
        raise FileNotFoundError(f"Not a file: {requested_path}")

    # Read file content with encoding fallback
    try:
        content = read_text_with_fallback(full_path)
        return content
    except Exception as e:
        LOGGER.error(
            "file_read_failed",
            path=str(full_path),
            error=str(e),
        )
        raise FileNotFoundError(f"Could not read file: {requested_path}") from e


def get_language_from_path(file_path: str) -> str:
    """
    Detect programming language from file extension.

    Args:
        file_path: Path to the file

    Returns:
        Language identifier for syntax highlighting
    """
    # Special case: common extension-less filenames
    basename = Path(file_path).name.lower()
    extensionless_map: dict[str, str] = {
        "makefile": "makefile",
        "dockerfile": "dockerfile",
        "jenkinsfile": "groovy",
        "rakefile": "ruby",
        "gemfile": "ruby",
        "guardfile": "ruby",
        "capfile": "ruby",
        "vagrantfile": "ruby",
        "berksfile": "ruby",
        "cheffile": "ruby",
    }
    if basename in extensionless_map:
        return extensionless_map[basename]

    ext = Path(file_path).suffix.lower()

    language_map: dict[str, str] = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".md": "markdown",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".scss": "scss",
        ".sass": "sass",
        ".less": "less",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".kt": "kotlin",
        ".scala": "scala",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".php": "php",
        ".rb": "ruby",
        ".swift": "swift",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".fish": "bash",
        ".ps1": "powershell",
        ".sql": "sql",
        ".graphql": "graphql",
        ".dockerfile": "dockerfile",
        ".tf": "hcl",
        ".hcl": "hcl",
        ".vue": "vue",
        ".svelte": "svelte",
        ".elm": "elm",
        ".erl": "erlang",
        ".ex": "elixir",
        ".exs": "elixir",
        ".clj": "clojure",
        ".cljs": "clojure",
        ".lisp": "lisp",
        ".hs": "haskell",
        ".ml": "ocaml",
        ".fs": "fsharp",
        ".dart": "dart",
        ".lua": "lua",
        ".r": "r",
        ".m": "objectivec",
        ".mm": "objectivec",
        ".groovy": "groovy",
        ".jl": "julia",
        ".nim": "nim",
        ".zig": "zig",
        ".v": "v",
        ".coq": "coq",
        ".agda": "agda",
        ".idris": "idris",
        ".purs": "purescript",
        ".dhall": "dhall",
        ".nix": "nix",
        ".bazel": "starlark",
        ".bzl": "starlark",
        ".build": "starlark",
        ".workspace": "starlark",
        ".proto": "protobuf",
    }

    return language_map.get(ext, "plaintext")


def get_entities_for_file(
    file_path: str,
    bsg_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Extract entities belonging to a specific file from BSG data.

    Args:
        file_path: Relative file path
        bsg_data: BSG payload with nodes and indexes

    Returns:
        List of entity dicts with line info for this file
    """
    if not bsg_data or not isinstance(bsg_data, dict):
        return []

    nodes = bsg_data.get("nodes", [])
    if not nodes:
        return []

    # Normalize the file path for matching
    normalized_path = file_path.lstrip("./").lstrip("/")

    entities = []
    for node in nodes:
        if not isinstance(node, dict):
            continue

        node_file = node.get("file", "")
        if not node_file:
            continue

        # Normalize node file path
        normalized_node_file = node_file.lstrip("./").lstrip("/")

        if normalized_node_file == normalized_path:
            entity = {
                "id": node.get("id", ""),
                "name": node.get("name", ""),
                "type": node.get("type", "VARIABLE"),
                "startLine": node.get("start_line", 0) or node.get("startLine", 0),
                "endLine": node.get("end_line", 0) or node.get("endLine", 0),
                "signature": node.get("signature"),
                "language": node.get("language", ""),
                "scopeTier": node.get("scope_tier") or node.get("scopeTier", ""),
                "category": node.get("category", ""),
            }
            entities.append(entity)

    # Sort by start line (check both camelCase and snake_case since entities may have either)
    entities.sort(key=lambda e: (e.get("startLine") or e.get("start_line") or 0, e.get("name", "")))

    return entities


def build_file_content_response(
    file_path: str,
    root: Path | str,
    bsg_data: dict[str, Any] | None = None,
    include_entities: bool = True,
) -> dict[str, Any]:
    """
    Build complete file content response for the dashboard.

    Args:
        file_path: Relative path to file
        root: Project root
        bsg_data: Optional BSG data for entity enrichment
        include_entities: Whether to include BSG entities

    Returns:
        Response dict with content, language, and entities
    """
    # Read file content
    content = safe_read_file(file_path, root)

    # Detect language
    language = get_language_from_path(file_path)

    # Count lines
    lines = content.split("\n")
    total_lines = len(lines)

    response: dict[str, Any] = {
        "path": file_path,
        "content": content,
        "language": language,
        "totalLines": total_lines,
        "sizeBytes": len(content.encode("utf-8")),
    }

    # Add entities if requested and BSG data available
    if include_entities and bsg_data:
        entities = get_entities_for_file(file_path, bsg_data)
        response["entities"] = entities
        response["entityCount"] = len(entities)
    else:
        response["entities"] = []
        response["entityCount"] = 0

    return response
