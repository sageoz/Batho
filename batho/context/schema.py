"""
backend/context/schema.py — Shared type definitions, Entity and Relationship models.

All outputs from the AST engine are frozen Pydantic models — no raw dicts
leak out of this layer.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any, Dict

from pydantic import BaseModel, Field, computed_field

from batho.utils.hash import generate_entity_id, generate_relationship_id

# --------------------------------------------------------------------------
# Type aliases
# --------------------------------------------------------------------------

EntityMetadata = Dict[str, Any]


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class EntityType(Enum):
    """Types of code entities that can be extracted from source code."""

    FUNCTION = auto()
    METHOD = auto()
    CLASS = auto()
    MODULE = auto()
    STRUCT = auto()
    INTERFACE = auto()
    FIELD = auto()
    ENUM = auto()
    TRAIT = auto()
    TYPE_ALIAS = auto()
    CONSTANT = auto()
    NAMESPACE = auto()
    VARIABLE = auto()
    PROPERTY = auto()
    ENTRY_POINT = auto()
    # Markup / Config types
    SETTING = auto()  # Key-value pairs (JSON, YAML, TOML)
    SECTION = auto()  # Named sections/objects
    ELEMENT = auto()  # HTML/CSS/Markdown structural elements
    ATTRIBUTE = auto()  # Element attributes
    DOCUMENT = auto()  # Document-level entity

    def __str__(self) -> str:
        return self.name.lower()


class RelationshipType(Enum):
    """Types of relationships between code entities."""

    CALLS = auto()
    IMPORTS = auto()
    INHERITS = auto()
    IMPLEMENTS = auto()
    USES = auto()
    CONTAINS = auto()
    REFERENCES = auto()
    DEFINES = auto()
    CALLED_BY = auto()
    IMPORTED_BY = auto()
    OVERRIDES = auto()
    STACK_BOUNDARY = auto()
    WRAPPED_BY = auto()
    DEPENDS_ON_API = auto()
    REFERENCED_IN = auto()
    CLEANED_BY = auto()
    CONTAINED_WITHIN = auto()
    # Markup / Config
    HAS_ATTRIBUTE = auto()
    LINKS_TO = auto()
    IMPORTS_STYLE = auto()

    def __str__(self) -> str:
        return self.name.lower()


# --------------------------------------------------------------------------
# Entity model
# --------------------------------------------------------------------------


class Entity(BaseModel):
    """
    A code entity extracted from source code.

    Attributes:
        type: The kind of entity (function, class, etc.)
        name: The identifier name of the entity
        file: Path to the source file containing this entity
        start_line: 1-based starting line number
        end_line: 1-based ending line number
        start_byte: Starting byte offset in the source file
        end_byte: Ending byte offset in the source file
        signature: Optional signature string (e.g., for functions)
        metadata: Additional language-specific metadata
        parent_id: Optional ID of the containing parent entity
    """

    model_config = {"frozen": True, "extra": "allow"}

    type: EntityType
    name: str
    file: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    signature: str | None = None
    metadata: EntityMetadata = Field(default_factory=dict)
    parent_id: str | None = None

    @computed_field  # type: ignore[misc]
    @property
    def id(self) -> str:
        """Generate a unique, deterministic ID for this entity."""
        return generate_entity_id(self.type.name, self.name, self.file, self.start_line)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.name,
            "name": self.name,
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "signature": self.signature,
            "metadata": self.metadata,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Entity":
        d = data.copy()
        d.pop("id", None)
        if "type" in d and isinstance(d["type"], str):
            # Convert lowercase string to uppercase enum key
            type_str = d["type"].upper()
            d["type"] = EntityType[type_str]
        return cls(**d)

    def __str__(self) -> str:
        sig = f" {self.signature}" if self.signature else ""
        return f"{self.name}{sig} ({self.type}) [L{self.start_line}-{self.end_line}]"

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        # Return NotImplemented for type mismatch - this is correct Python protocol
        # It allows Python to try the reflected operation on the other object
        if not isinstance(other, Entity):
            return NotImplemented
        return self.id == other.id


# --------------------------------------------------------------------------
# Relationship model
# --------------------------------------------------------------------------


class Relationship(BaseModel):
    """
    A relationship between two code entities.

    Attributes:
        source_id: ID of the source entity
        target_id: ID of the target entity
        type: The kind of relationship (calls, inherits, etc.)
        metadata: Additional metadata (line numbers, etc.)
    """

    model_config = {"frozen": True, "extra": "allow"}

    source_id: str
    target_id: str
    type: RelationshipType
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[misc]
    @property
    def id(self) -> str:
        """Generate a unique, deterministic ID for this relationship."""
        return generate_relationship_id(self.source_id, self.target_id, self.type.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type.name,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Relationship":
        d = data.copy()
        d.pop("id", None)
        if "type" in d and isinstance(d["type"], str):
            # Convert lowercase string to uppercase enum key
            type_str = d["type"].upper()
            d["type"] = RelationshipType[type_str]
        return cls(**d)

    def __str__(self) -> str:
        return f"{self.source_id} --[{self.type}]--> {self.target_id}"

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        # Return NotImplemented for type mismatch - this is correct Python protocol
        # It allows Python to try the reflected operation on the other object
        if not isinstance(other, Relationship):
            return NotImplemented
        return self.id == other.id
