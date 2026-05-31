import re
import logging
from pathlib import Path
from typing import List

from batho.core.schemas import Entity, EntityType
from batho.modules.extraction.extraction_result import ExtractionResult, ExtractionStatus, ExtractionError

logger = logging.getLogger(__name__)

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
        entities = []
        
        # We run all patterns regardless of extension to salvage as much as possible.

        # 1. Python-style function definitions
        py_func_pattern = r'^[ \t]*def\s+([a-zA-Z_]\w*)\s*\('
        for match in re.finditer(py_func_pattern, content, re.MULTILINE):
            end_idx = content.find('\n', match.end())
            if end_idx == -1:
                end_idx = match.end()
            start_line = content.count('\n', 0, match.start()) + 1
            end_line = content.count('\n', 0, end_idx) + 1
            
            entities.append(Entity(
                type=EntityType.FUNCTION,
                name=match.group(1),
                file=str(file_path),
                start_line=start_line,
                end_line=end_line,
                start_byte=len(content[:match.start()].encode('utf-8', 'replace')),
                end_byte=len(content[:end_idx].encode('utf-8', 'replace')),
                raw_content=content[match.start():end_idx]
            ))
        
        # 2. Python-style class definitions
        py_class_pattern = r'^[ \t]*class\s+([a-zA-Z_]\w*)'
        for match in re.finditer(py_class_pattern, content, re.MULTILINE):
            end_idx = content.find('\n', match.end())
            if end_idx == -1:
                end_idx = match.end()
            start_line = content.count('\n', 0, match.start()) + 1
            end_line = content.count('\n', 0, end_idx) + 1
            
            entities.append(Entity(
                type=EntityType.CLASS,
                name=match.group(1),
                file=str(file_path),
                start_line=start_line,
                end_line=end_line,
                start_byte=len(content[:match.start()].encode('utf-8', 'replace')),
                end_byte=len(content[:end_idx].encode('utf-8', 'replace')),
                raw_content=content[match.start():end_idx]
            ))
            
        # 3. JS/TS/Java/C-style function declarations
        js_func_pattern = r'(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*\('
        for match in re.finditer(js_func_pattern, content):
            end_idx = content.find('\n', match.end())
            if end_idx == -1:
                end_idx = match.end()
            start_line = content.count('\n', 0, match.start()) + 1
            entities.append(Entity(
                type=EntityType.FUNCTION,
                name=match.group(1),
                file=str(file_path),
                start_line=start_line,
                end_line=start_line,
                start_byte=len(content[:match.start()].encode('utf-8', 'replace')),
                end_byte=len(content[:end_idx].encode('utf-8', 'replace')),
                raw_content=content[match.start():end_idx]
            ))
            
        # 4. JS/TS/Java/C-style class declarations
        js_class_pattern = r'(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([a-zA-Z_]\w*)'
        for match in re.finditer(js_class_pattern, content):
            end_idx = content.find('\n', match.end())
            if end_idx == -1:
                end_idx = match.end()
            start_line = content.count('\n', 0, match.start()) + 1
            entities.append(Entity(
                type=EntityType.CLASS,
                name=match.group(1),
                file=str(file_path),
                start_line=start_line,
                end_line=start_line,
                start_byte=len(content[:match.start()].encode('utf-8', 'replace')),
                end_byte=len(content[:end_idx].encode('utf-8', 'replace')),
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
