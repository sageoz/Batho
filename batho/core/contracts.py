"""Interface protocols defining decoupling contracts for Batho components."""

from typing import Protocol
from .schemas import ASTExtractionResult, GraphState


class LanguageParser(Protocol):
    """Protocol for language-specific AST extraction parsers."""

    def parse(self, file_content: bytes, file_path: str) -> ASTExtractionResult:
        """Parse source file content and return entities and relationships."""
        ...


class GraphBuilder(Protocol):
    """Protocol for building/managing the relationship graph."""

    def build(self, extraction_result: ASTExtractionResult) -> GraphState:
        """Build and return updated graph state from extraction results."""
        ...
