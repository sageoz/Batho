"""Extraction module re-exports."""
from .extractor import ASTExtractor as ASTExtractor, MarkupConfigExtractor as MarkupConfigExtractor
from .pipeline import extract_and_emit_parallel as extract_and_emit_parallel
from .scope_manager import ScopeManager as ScopeManager, SymbolInfo as SymbolInfo
from .symbol_table import (
    FileSymbolTable as FileSymbolTable,
    SymbolDefinition as SymbolDefinition,
    ImportStatement as ImportStatement,
)

__all__ = [
    "ASTExtractor",
    "MarkupConfigExtractor",
    "extract_and_emit_parallel",
    "ScopeManager",
    "SymbolInfo",
    "FileSymbolTable",
    "SymbolDefinition",
    "ImportStatement",
]
