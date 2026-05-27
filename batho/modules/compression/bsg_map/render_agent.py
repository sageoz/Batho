"""
batho/context/bsg_map/render_agent.py — Agent (LLM View) rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import BSGMap


def _text_tokens(text: str) -> int:
    """Estimate token count using 4-bytes-per-token heuristic."""
    return max(1, len(text.encode("utf-8")) // 4)


def render_compressed(
    bsg: BSGMap, budget: int, fail_on_overflow: bool = True
) -> tuple[str, dict[str, int]]:
    """
    Render a token-budget-capped summary for LLM injection.
    """
    lines: list[str] = []
    tokens_used = 0
    truncated_files = 0

    for file_path, entities in bsg._by_file.items():
        file_header = f"{file_path}:"
        header_cost = _text_tokens(file_header)
        if tokens_used + header_cost > budget:
            truncated_files += len([f for f in bsg._by_file if f >= file_path])
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

    stats = {
        "tokens_used": tokens_used,
        "budget": budget,
        "truncated_files": truncated_files,
    }
    return "\n".join(lines), stats
