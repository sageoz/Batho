import re
import structlog
from pathlib import Path
from typing import List

from batho.core.schemas import Entity, EntityType
from batho.modules.extraction.extraction_result import ExtractionResult, ExtractionStatus, ExtractionError

logger = structlog.get_logger(__name__)

class FallbackParser:
    """
    Text-based fallback parser for files with syntax errors.
    
    Uses heuristics to extract basic entities when AST fails.
    """
    
    def __init__(self):
        pass
    
    def parse_file(self, file_path: Path, content: bytes) -> ExtractionResult:
        """Attempt fallback parsing for failed file."""
        try:
            content_str = content.decode("utf-8", errors="replace")
            entities = self._extract_entities_text(content_str, file_path)
            
            return ExtractionResult(
                status=ExtractionStatus.PARTIAL,
                entities=entities,
                relationships=[],
                errors=[],
                file_path=str(file_path),
                fallback_used=True
            )
        except Exception as e:
            logger.warning(f"Fallback parsing failed for {file_path}: {e}")
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                entities=[],
                relationships=[],
                errors=[ExtractionError(
                    error_type="fallback_failed",
                    message=str(e)
                )],
                file_path=str(file_path),
                fallback_used=True
            )
    
    def _extract_entities_text(self, content: str, file_path: Path) -> List[Entity]:
        """Extract entities using cross-language text-based heuristics."""
        import bisect
        entities = []
        
        # Pre-compute line start offsets for O(log N) line number lookups.
        # Each entry is the byte offset where that line starts (0-indexed).
        line_starts = [0]
        for i, char in enumerate(content):
            if char == '\n':
                line_starts.append(i + 1)
        
        def byte_offset_to_line(byte_offset: int) -> int:
            """Convert byte offset to 1-indexed line number using binary search."""
            return bisect.bisect_right(line_starts, byte_offset)
        
        # Pre-compute cumulative byte lengths for UTF-8 encoding.
        # Optimized: Try ASCII fast-path (byte offset = char offset for pure ASCII).
        # Only build cumulative_bytes table for non-ASCII content.
        try:
            # Fast path: check if content is pure ASCII
            content.encode('ascii')
            # Pure ASCII: each char = 1 byte, so offset is identity
            def char_offset_to_byte(char_offset: int) -> int:
                return min(char_offset, len(content))
        except UnicodeEncodeError:
            # Slow path: build cumulative byte offset table
            cumulative_bytes = [0] * (len(content) + 1)
            byte_pos = 0
            for i, char in enumerate(content):
                cumulative_bytes[i] = byte_pos
                byte_pos += len(char.encode('utf-8', 'replace'))
            cumulative_bytes[len(content)] = byte_pos

            def char_offset_to_byte(char_offset: int) -> int:
                return cumulative_bytes[min(char_offset, len(content))]
        
        # We run all patterns regardless of extension to salvage as much as possible.

        # 1. Python-style function definitions
        # Use Unicode-aware identifier matching so PEP 3131 identifiers are
        # preserved when tree-sitter is unavailable. [^\W0-9] matches any
        # Unicode letter or underscore for the first character.
        py_func_pattern = r'^[ \t]*def\s+([^\W0-9]\w*)\s*\('
        for match in re.finditer(py_func_pattern, content, re.MULTILINE):
            end_idx = content.find('\n', match.end())
            if end_idx == -1:
                end_idx = match.end()
            start_line = byte_offset_to_line(match.start())
            end_line = byte_offset_to_line(end_idx)
            
            entities.append(Entity(
                type=EntityType.FUNCTION,
                name=match.group(1),
                file=str(file_path),
                start_line=start_line,
                end_line=end_line,
                start_byte=char_offset_to_byte(match.start()),
                end_byte=char_offset_to_byte(end_idx),
                raw_content=content[match.start():end_idx]
            ))
        
        # 2. Python-style class definitions
        py_class_pattern = r'^[ \t]*class\s+([^\W0-9]\w*)'
        for match in re.finditer(py_class_pattern, content, re.MULTILINE):
            end_idx = content.find('\n', match.end())
            if end_idx == -1:
                end_idx = match.end()
            start_line = byte_offset_to_line(match.start())
            end_line = byte_offset_to_line(end_idx)
            
            entities.append(Entity(
                type=EntityType.CLASS,
                name=match.group(1),
                file=str(file_path),
                start_line=start_line,
                end_line=end_line,
                start_byte=char_offset_to_byte(match.start()),
                end_byte=char_offset_to_byte(end_idx),
                raw_content=content[match.start():end_idx]
            ))
            
        # 3. JS/TS/Java/C-style function declarations
        js_func_pattern = r'(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([^\W0-9]\w*)\s*\('
        for match in re.finditer(js_func_pattern, content):
            end_idx = content.find('\n', match.end())
            if end_idx == -1:
                end_idx = match.end()
            start_line = byte_offset_to_line(match.start())
            end_line = byte_offset_to_line(end_idx)
            entities.append(Entity(
                type=EntityType.FUNCTION,
                name=match.group(1),
                file=str(file_path),
                start_line=start_line,
                end_line=end_line,
                start_byte=char_offset_to_byte(match.start()),
                end_byte=char_offset_to_byte(end_idx),
                raw_content=content[match.start():end_idx]
            ))
            
        # 4. JS/TS/Java/C-style class declarations
        js_class_pattern = r'(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([^\W0-9]\w*)'
        for match in re.finditer(js_class_pattern, content):
            end_idx = content.find('\n', match.end())
            if end_idx == -1:
                end_idx = match.end()
            start_line = byte_offset_to_line(match.start())
            entities.append(Entity(
                type=EntityType.CLASS,
                name=match.group(1),
                file=str(file_path),
                start_line=start_line,
                end_line=start_line,
                start_byte=char_offset_to_byte(match.start()),
                end_byte=char_offset_to_byte(end_idx),
                raw_content=content[match.start():end_idx]
            ))

        # We deduplicate entities by (name, type, start_line) to avoid overlapping
        # patterns firing on the same definition, while preserving valid distinct
        # entities that share a name but differ in type or location.
        unique_entities = {}
        for ent in entities:
            key = (ent.name, ent.type, ent.start_line)
            if key not in unique_entities:
                unique_entities[key] = ent

        return list(unique_entities.values())
