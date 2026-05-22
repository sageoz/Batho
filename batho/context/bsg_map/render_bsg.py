"""
batho/context/bsg_map/render_bsg.py — BSG (Developer View) rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import BSGMap


def render_full(bsg: BSGMap) -> str:
    """
    Render a full aider-style indented symbol index.
    """
    lines: list[str] = []
    for file_path, entities in bsg._by_file.items():
        lines.append(f"{file_path}:")
        for entity in entities:
            indent = "  "
            sig = entity.signature or entity.name
            type_label = str(entity.type)
            lines.append(
                f"{indent}{sig} ({type_label}) [L{entity.start_line}-{entity.end_line}]"
            )
        deps = bsg._dependencies.get(file_path, [])
        if deps:
            lines.append(f"  deps: {', '.join(deps)}")
    return "\n".join(lines)


def render_hierarchical(bsg: BSGMap, include_entities: bool = True) -> str:
    """
    Render a hierarchical directory tree with files and their entities.
    """
    lines: list[str] = []
    grouped = bsg.group_by_directory()

    for dir_path, files in grouped.items():
        display_path = dir_path if dir_path else "(root)"
        label = bsg._get_directory_label(dir_path)
        lines.append(
            f"📁 {display_path}/ ({label})" if label else f"📁 {display_path}/"
        )

        for file_name, entities in files:
            lines.append(f"  📄 {file_name}")

            # Reconstruct relative file path for dep lookup
            full_path = f"{dir_path}/{file_name}" if dir_path else file_name
            deps: list[str] = bsg._dependencies.get(full_path, [])
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
