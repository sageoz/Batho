from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from batho.core.schemas import PackageMetadata, DescriptorSuffix


@dataclass
class SymbolDefinition:
    """Definition of a symbol in a file (intermediate representation)."""
    name: str
    symbol_type: str  # class, function, variable, etc.
    start_byte: int
    end_byte: int
    enclosing_scope: str
    descriptor_chain: List[Tuple[str, DescriptorSuffix]]
    is_exported: bool = False


@dataclass
class ImportStatement:
    """Import statement information."""
    module_path: str
    imported_names: List[str]
    is_from_import: bool
    start_byte: int
    end_byte: int


@dataclass
class FileSymbolTable:
    """Intermediate representation of symbols in a file."""
    file_path: Path
    symbols: Dict[str, SymbolDefinition]
    imports: List[ImportStatement]
    package: Optional[PackageMetadata] = None

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "file_path": str(self.file_path),
            "symbols": {
                name: {
                    "name": defn.name,
                    "symbol_type": defn.symbol_type,
                    "start_byte": defn.start_byte,
                    "end_byte": defn.end_byte,
                    "enclosing_scope": defn.enclosing_scope,
                    "descriptor_chain": [(n, s.value) for n, s in defn.descriptor_chain],
                    "is_exported": defn.is_exported
                }
                for name, defn in self.symbols.items()
            },
            "imports": [
                {
                    "module_path": imp.module_path,
                    "imported_names": imp.imported_names,
                    "is_from_import": imp.is_from_import,
                    "start_byte": imp.start_byte,
                    "end_byte": imp.end_byte
                }
                for imp in self.imports
            ],
            "package": self.package.to_dict() if self.package else None
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileSymbolTable":
        """Deserialize from dictionary."""
        symbols = {}
        for name, v in data.get("symbols", {}).items():
            chain = [(n, DescriptorSuffix(s)) for n, s in v.get("descriptor_chain", [])]
            symbols[name] = SymbolDefinition(
                name=v["name"],
                symbol_type=v["symbol_type"],
                start_byte=v["start_byte"],
                end_byte=v["end_byte"],
                enclosing_scope=v["enclosing_scope"],
                descriptor_chain=chain,
                is_exported=v.get("is_exported", False)
            )

        imports = []
        for imp in data.get("imports", []):
            imports.append(
                ImportStatement(
                    module_path=imp["module_path"],
                    imported_names=imp["imported_names"],
                    is_from_import=imp["is_from_import"],
                    start_byte=imp["start_byte"],
                    end_byte=imp["end_byte"]
                )
            )

        pkg = None
        if data.get("package"):
            pkg = PackageMetadata.from_dict(data["package"])

        return cls(
            file_path=Path(data["file_path"]),
            symbols=symbols,
            imports=imports,
            package=pkg
        )

    def merge(self, other: "FileSymbolTable") -> "FileSymbolTable":
        """Merge another FileSymbolTable into this one."""
        merged_symbols = dict(self.symbols)
        for name, defn in other.symbols.items():
            merged_symbols[name] = defn

        merged_imports = list(self.imports) + list(other.imports)

        return FileSymbolTable(
            file_path=self.file_path,
            symbols=merged_symbols,
            imports=merged_imports,
            package=self.package or other.package
        )
