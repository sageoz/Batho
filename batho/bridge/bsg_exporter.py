"""Streaming JSON export engine for BSGMap artifacts.

Provides memory-efficient streaming export for large repositories by yielding
JSON chunks rather than building the entire payload in memory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterator

from batho.config import BSG_SCHEMA_VERSION
from batho.utils.logging import get_logger

if TYPE_CHECKING:
    from batho.context.bsg_map import BSGMap

LOGGER = get_logger(__name__, component="bridge.bsg_exporter")


class BSGExporter:
    """Streaming JSON export for large repositories.

    Yields UTF-8 JSON chunks instead of building the full payload in memory,
    allowing callers to pipe arbitrarily large repositories without OOM risk.
    """

    def export_streaming(
        self,
        bsg_map: "BSGMap",
        view: str,
        fmt: str = "json",
    ) -> Iterator[str]:
        """Yield JSON string chunks for a given view.

        Args:
            bsg_map: The BSGMap to export.
            view: One of storage|agent|overview|files|symbols|dependencies.
                  (delta is not streamable — requires full diff).
            fmt: 'json' (compact) or 'pretty' (indented).

        Yields:
            String chunks that when concatenated form valid JSON.
        """
        view = view.lower()

        dispatch = {
            "storage": self._stream_storage_view,
            "agent": self._stream_agent_view,
            "overview": self._stream_overview_view,
            "files": self._stream_files_view,
            "symbols": self._stream_symbols_view,
            "dependencies": self._stream_dependencies_view,
        }

        handler = dispatch.get(view)
        if handler is None:
            # Fall back: render entire payload and yield as one chunk
            LOGGER.warning("bsg_exporter_no_stream_handler", view=view)
            from batho.orchestrator.export import _generate_view, ExportOptions
            from pathlib import Path
            opts = ExportOptions(root=Path(bsg_map._root), view=view, format=fmt)
            data = _generate_view(bsg_map, view, opts)
            yield self._serialize_chunk(data, fmt)
            return

        yield from handler(bsg_map, fmt)

    # ------------------------------------------------------------------
    # Per-view streaming generators
    # ------------------------------------------------------------------

    def _stream_storage_view(self, bsg_map: "BSGMap", fmt: str) -> Iterator[str]:
        """Stream the storage view file-by-file."""
        now = datetime.now(timezone.utc).isoformat()
        file_paths = sorted(bsg_map._by_file.keys())
        file_count = len(file_paths)
        entity_count = sum(len(v) for v in bsg_map._by_file.values())

        header = {
            "view_type": "storage",
            "schema_version": BSG_SCHEMA_VERSION,
            "generated_at": now,
            "includes_raw_content": True,
            "entity_count": entity_count,
            "file_count": file_count,
        }

        yield self._open_object_with_fields(header, "files", fmt)

        first = True
        for file_path in file_paths:
            entities = bsg_map._by_file[file_path]
            file_entry = {
                "file_path": file_path,
                "entity_count": len(entities),
                "entities": [
                    e.to_dict(view="storage")
                    for e in sorted(entities, key=lambda e: e.start_byte)
                ],
            }
            prefix = "" if first else ","
            if fmt == "pretty":
                yield prefix + "\n  " + json.dumps(file_entry, indent=2, sort_keys=True, ensure_ascii=True).replace("\n", "\n  ")
            else:
                yield prefix + json.dumps(file_entry, sort_keys=True, ensure_ascii=True)
            first = False

        yield self._close_object(fmt)

    def _stream_agent_view(self, bsg_map: "BSGMap", fmt: str) -> Iterator[str]:
        """Stream the agent view file-by-file."""
        from batho.context.schema import EntityType

        now = datetime.now(timezone.utc).isoformat()
        file_paths = sorted(bsg_map._by_file.keys())
        entity_count = sum(
            len([e for e in v if e.type != EntityType.SYNTAX_GLUE])
            for v in bsg_map._by_file.values()
        )
        file_count = len(file_paths)

        header = {
            "view_type": "agent",
            "schema_version": BSG_SCHEMA_VERSION,
            "generated_at": now,
            "includes_raw_content": False,
            "entity_count": entity_count,
            "file_count": file_count,
        }

        yield self._open_object_with_fields(header, "files", fmt)

        first = True
        for file_path in file_paths:
            entities = [
                e for e in sorted(bsg_map._by_file[file_path], key=lambda e: e.start_byte)
                if e.type != EntityType.SYNTAX_GLUE
            ]
            if not entities:
                continue
            file_entry = {
                "file_path": file_path,
                "entity_count": len(entities),
                "entities": [e.to_dict(view="agent") for e in entities],
            }
            prefix = "" if first else ","
            if fmt == "pretty":
                yield prefix + "\n  " + json.dumps(file_entry, indent=2, sort_keys=True, ensure_ascii=True).replace("\n", "\n  ")
            else:
                yield prefix + json.dumps(file_entry, sort_keys=True, ensure_ascii=True)
            first = False

        yield self._close_object(fmt)

    def _stream_overview_view(self, bsg_map: "BSGMap", fmt: str) -> Iterator[str]:
        """Stream overview — small payload, render fully and yield once."""
        data = bsg_map.render_overview_json()
        yield self._serialize_chunk(data, fmt)

    def _stream_files_view(self, bsg_map: "BSGMap", fmt: str) -> Iterator[str]:
        """Stream files view — small payload, render fully and yield once."""
        data = bsg_map.render_files_json()
        yield self._serialize_chunk(data, fmt)

    def _stream_symbols_view(self, bsg_map: "BSGMap", fmt: str) -> Iterator[str]:
        """Stream symbol index one file at a time."""
        from batho.orchestrator.export import _generate_symbols_view

        # symbols is flat, so we batch by file to keep memory bounded
        now = datetime.now(timezone.utc).isoformat()
        total_symbols = sum(len(v) for v in bsg_map._by_file.values())

        header_fields: dict = {
            "view_type": "symbols",
            "generated_at": now,
            "symbol_count": total_symbols,
        }
        yield self._open_object_with_fields(header_fields, "symbols", fmt)

        first = True
        for file_path in sorted(bsg_map._by_file.keys()):
            for entity in bsg_map._by_file[file_path]:
                sym = {
                    "id": entity.id,
                    "name": entity.name,
                    "type": entity.type.name,
                    "file": file_path,
                    "line": entity.start_line,
                    "signature": entity.signature,
                }
                prefix = "" if first else ","
                if fmt == "pretty":
                    yield prefix + "\n  " + json.dumps(sym, sort_keys=True, ensure_ascii=True)
                else:
                    yield prefix + json.dumps(sym, sort_keys=True, ensure_ascii=True)
                first = False

        yield self._close_object(fmt)

    def _stream_dependencies_view(self, bsg_map: "BSGMap", fmt: str) -> Iterator[str]:
        """Stream dependency view — render fully (typically small) and yield once."""
        from batho.orchestrator.export import _generate_dependencies_view

        data = _generate_dependencies_view(bsg_map)
        yield self._serialize_chunk(data, fmt)

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_chunk(data: dict, fmt: str) -> str:
        """Serialize a dict to compact or pretty JSON."""
        if fmt == "pretty":
            return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
        return json.dumps(data, sort_keys=True, ensure_ascii=True)

    @staticmethod
    def _open_object_with_fields(header_fields: dict, array_key: str, fmt: str) -> str:
        """Emit the opening of a JSON object with header fields, then open the array.

        Example output (compact):
            {"view_type":"storage","files":[
        """
        # Build prefix: all fields except the array, then open the array
        parts = []
        for k, v in sorted(header_fields.items()):
            parts.append(f"{json.dumps(k)}:{json.dumps(v, ensure_ascii=True)}")
        array_open = f"{json.dumps(array_key)}:["
        all_fields = ",".join(parts) + ("," if parts else "") + array_open

        if fmt == "pretty":
            # Rebuild nicely
            inner = json.dumps(header_fields, indent=2, sort_keys=True, ensure_ascii=True)
            # Remove closing brace and append array key
            inner = inner.rstrip().rstrip("}")
            return inner + f'  {json.dumps(array_key)}: ['
        return "{" + all_fields

    @staticmethod
    def _close_object(fmt: str) -> str:
        """Emit the closing of the JSON array and enclosing object."""
        if fmt == "pretty":
            return "\n  ]\n}"
        return "]}"
