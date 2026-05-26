"""File service handler — Safe file reading with path traversal protection.

Provides secure file content retrieval with BSG entity enrichment
for dashboard file viewing and code editor integration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from batho.bridge_core.deps import WorkspaceDeps
from batho.utils.encoding import read_text_with_fallback
from batho.utils.ignore import should_ignore_path
from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="bridge_core.handlers.file")


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

    # Security: Block absolute paths
    if requested_path.startswith("/"):
        LOGGER.warning(
            "path_traversal_blocked",
            requested=requested_path,
            pattern="absolute path",
        )
        raise SecurityError(f"Path outside project root: {requested_path}")

    # Normalize the requested path
    clean_path = requested_path
    if clean_path.startswith("./"):
        clean_path = clean_path[2:]

    # Security: Check for path traversal patterns
    if clean_path.startswith("../") or "/../" in clean_path or clean_path.endswith("/.."):
        LOGGER.warning(
            "path_traversal_blocked",
            requested=requested_path,
            pattern=".. detected",
        )
        raise SecurityError(f"Path outside project root: {requested_path}")

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

    # Security: Check if file is ignored
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

    # Sort by start line
    entities.sort(key=lambda e: (e.get("startLine") or e.get("start_line") or 0, e.get("name", "")))

    return entities


def handle_file_content(deps: WorkspaceDeps, params: dict) -> dict:
    """Handle GET /api/v2/file/content

    Returns file content with language detection and optional BSG entity enrichment.

    Args:
        deps: Workspace dependencies
        params: Query parameters (required: file; optional: include_entities)

    Returns:
        dict with keys: path, content, language, totalLines, sizeBytes, entities, entityCount
    """
    file_path = params.get("file")
    if not file_path:
        return {
            "ok": False,
            "error": "Missing required parameter: file",
            "data": {},
        }

    include_entities = params.get("include_entities", "true").lower() == "true"

    try:
        # Read file content
        content = safe_read_file(file_path, deps.repo_root)

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

        # Add entities if requested and BSG manager available
        if include_entities and deps.bsg_manager:
            try:
                bsg_data = deps.bsg_manager.to_dict()
                entities = get_entities_for_file(file_path, bsg_data)
                response["entities"] = entities
                response["entityCount"] = len(entities)
            except Exception as e:
                LOGGER.warning("bsg_entity_extraction_failed", error=str(e))
                response["entities"] = []
                response["entityCount"] = 0
        else:
            response["entities"] = []
            response["entityCount"] = 0

        return {
            "ok": True,
            "data": response,
        }
    except SecurityError as e:
        LOGGER.warning("file_access_denied", file=file_path, error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {},
        }
    except FileNotFoundError as e:
        LOGGER.warning("file_not_found", file=file_path, error=str(e))
        return {
            "ok": False,
            "error": str(e),
            "data": {},
        }
    except Exception as e:
        LOGGER.error("file_content_error", error=str(e), file=file_path)
        return {
            "ok": False,
            "error": str(e),
            "data": {},
        }


__all__ = [
    "handle_file_content",
    "safe_read_file",
    "get_language_from_path",
    "get_entities_for_file",
]
