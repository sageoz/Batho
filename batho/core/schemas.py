"""
batho/core/schemas.py — Shared type definitions, Entity and Relationship models.

All outputs from the AST engine are frozen Pydantic models — no raw dicts
leak out of this layer.
"""

from __future__ import annotations

from enum import Enum, auto, IntFlag
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, computed_field

from batho.utils.hash import compute_bytes_hash

# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------


class CoverageError(Exception):
    """Raised when byte coverage validation fails.

    Attributes:
        file_path: Path to the file being validated.
        byte_coverage: Ratio of covered bytes (0.0 to 1.0).
        overlapping_ranges: List of (start_byte, end_byte) tuples that overlap.
        gap_ranges: List of (start_byte, end_byte) tuples that are uncovered.
    """

    def __init__(
        self,
        message: str,
        file_path: str = "",
        byte_coverage: float = 0.0,
        overlapping_ranges: list[tuple[int, int]] | None = None,
        gap_ranges: list[tuple[int, int]] | None = None,
    ) -> None:
        self.file_path = file_path
        self.byte_coverage = byte_coverage
        self.overlapping_ranges = overlapping_ranges or []
        self.gap_ranges = gap_ranges or []
        super().__init__(message)


class ReconstructionError(Exception):
    """Raised when file reconstruction fails.

    Attributes:
        file_path: Path to the file being reconstructed.
        entity_count: Number of entities provided for reconstruction.
        byte_coverage: Ratio of covered bytes (0.0 to 1.0).
    """

    def __init__(
        self,
        message: str,
        file_path: str = "",
        entity_count: int = 0,
        byte_coverage: float = 0.0,
    ) -> None:
        self.file_path = file_path
        self.entity_count = entity_count
        self.byte_coverage = byte_coverage
        super().__init__(message)


class IntegrityError(Exception):
    """Raised when reconstructed content hash does not match the original.

    Attributes:
        file_path: Path to the file being validated.
        expected_hash: Expected SHA256 hash.
        actual_hash: Actual SHA256 hash of reconstructed content.
    """

    def __init__(
        self,
        message: str,
        file_path: str = "",
        expected_hash: str = "",
        actual_hash: str = "",
    ) -> None:
        self.file_path = file_path
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        super().__init__(message)


class GraphConsistencyError(Exception):
    """Raised when graph consistency check fails.

    Attributes:
        file_path: Path to the file that caused the inconsistency.
    """

    def __init__(self, message: str, file_path: str = "") -> None:
        self.file_path = file_path
        super().__init__(message)


# --------------------------------------------------------------------------
# Type aliases
# --------------------------------------------------------------------------

EntityMetadata = dict[str, Any]


class PackageManager(str, Enum):
    PIP = "pip"
    NPM = "npm"
    CARGO = "cargo"
    GO = "go"
    GRADLE = "gradle"
    MAVEN = "maven"
    UNKNOWN = "unknown"

class PackageMetadata(BaseModel):
    model_config = {"frozen": True, "extra": "allow", "slots": True}

    manager: PackageManager
    name: str
    version: str
    source: str | None = None

    def __str__(self) -> str:
        return f"{self.manager.value} {self.name} {self.version}"

    def to_dict(self) -> dict:
        return {
            "manager": self.manager.value,
            "name": self.name,
            "version": self.version,
            "source": self.source
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PackageMetadata":
        return cls(
            manager=PackageManager(data["manager"]),
            name=data["name"],
            version=data["version"],
            source=data.get("source")
        )

def detect_package_from_config(root_path: Path) -> PackageMetadata | None:
    """Helper function to detect package metadata from configuration files."""
    from batho.modules.dependency.manifest_parser import ManifestParser
    return ManifestParser.detect_project_metadata(root_path)

class SymbolRole(IntFlag):
    """Semantic roles for symbol occurrences, based on SCIP specification."""
    Definition = 1
    Import = 2
    WriteAccess = 4
    ReadAccess = 8
    Generated = 16
    Declaration = 32
    Dynamic = 64
    Heuristic = 128

    def is_definition(self) -> bool:
        return bool(self & SymbolRole.Definition)

    def is_reference(self) -> bool:
        return bool(self & (SymbolRole.ReadAccess | SymbolRole.WriteAccess))

    def is_import(self) -> bool:
        return bool(self & SymbolRole.Import)

    def __str__(self) -> str:
        roles = []
        if self & SymbolRole.Definition:
            roles.append("Definition")
        if self & SymbolRole.Import:
            roles.append("Import")
        if self & SymbolRole.WriteAccess:
            roles.append("WriteAccess")
        if self & SymbolRole.ReadAccess:
            roles.append("ReadAccess")
        if self & SymbolRole.Generated:
            roles.append("Generated")
        if self & SymbolRole.Declaration:
            roles.append("Declaration")
        if self & SymbolRole.Dynamic:
            roles.append("Dynamic")
        if self & SymbolRole.Heuristic:
            roles.append("Heuristic")
        return ", ".join(roles) if roles else "None"

class DescriptorSuffix(Enum):
    """Descriptor suffixes for hierarchical symbol encoding."""
    NAMESPACE = "/"
    TYPE = "#"
    TERM = "."
    METHOD = "()."

    @property
    def value(self) -> str:
        return self._value_

def build_descriptor(name: str, suffix: DescriptorSuffix) -> str:
    """
    Build a hierarchical descriptor component.

    Args:
        name: Symbol name (must be valid identifier)
        suffix: Descriptor suffix type

    Returns:
        Descriptor string (e.g., "Database#", "connect().")

    Raises:
        ValueError: If name is not a valid identifier
    """
    if not name:
        raise ValueError("Identifier name cannot be empty")
    # Allow Unicode identifiers (PEP 3131-style word characters) in addition to
    # the ASCII-only subset and the $ / [ / ] characters used by Java/JS and
    # parameter-hash suffixes. The first character may be a Unicode letter,
    # underscore, or '$'; subsequent characters may also include digits and the
    # parameter-hash brackets.
    if not re.match(r'^(?:[^\W0-9]|\$)[\w\$\[\]]*$', name, re.UNICODE):
        raise ValueError(f"Invalid identifier: {name}")
    return f"{name}{suffix.value}"

def generate_hierarchical_id(
    package: PackageMetadata | None,
    descriptors: list[tuple[str, DescriptorSuffix]],
    commit_hash: str | None = None,
) -> str:
    """
    Generate a hierarchical symbol ID.

    Args:
        package: Optional package metadata
        descriptors: List of (name, suffix) tuples
        commit_hash: Optional commit hash (stored in metadata/ignored for ID generation)

    Returns:
        Hierarchical ID string
    """
    if not descriptors:
        raise ValueError("Descriptor chain cannot be empty")

    if package:
        prefix = f"batho {package.manager.value} {package.name} {package.version} "
    else:
        prefix = "batho local project 0.0.0 "

    descriptor_str = "".join([
        build_descriptor(name, suffix) for name, suffix in descriptors
    ])

    return prefix + descriptor_str

def parse_hierarchical_id(id: str) -> tuple[PackageMetadata | None, list[tuple[str, DescriptorSuffix]]]:
    """
    Parse a hierarchical ID back into components.

    Args:
        id: Hierarchical ID string

    Returns:
        Tuple of (package metadata, descriptor chain)
    """
    parts = id.split(" ", 4)
    if len(parts) < 5 or parts[0] != "batho":
        raise ValueError(f"Invalid hierarchical ID format: {id}")

    manager, name, version, descriptor_str = parts[1], parts[2], parts[3], parts[4]

    try:
        package = PackageMetadata(
            manager=PackageManager(manager),
            name=name,
            version=version
        )
    except ValueError:
        package = None

    descriptors = []
    pattern = re.compile(r'([a-zA-Z_\$][a-zA-Z0-9_\$\[\]]*)(\(\)\.|\/|#|\.)')
    matches = list(pattern.finditer(descriptor_str))

    reconstructed = "".join(m.group(0) for m in matches)
    if reconstructed != descriptor_str:
        raise ValueError(f"Malformed descriptor chain: {descriptor_str}")

    for m in matches:
        d_name = m.group(1)
        suffix_str = m.group(2)
        suffix = next(s for s in DescriptorSuffix if s.value == suffix_str)
        descriptors.append((d_name, suffix))

    return package, descriptors


def _escape_id_component(value: str) -> str:
    return value.replace("|", "%7C")


def build_entity_id(
    *,
    entity_type: str,
    name: str,
    file: str,
    start_byte: int | None = None,
    end_byte: int | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Build a deterministic, non-hash entity ID."""
    parts = [
        "ent",
        _escape_id_component(entity_type),
        _escape_id_component(file),
        str(start_byte) if start_byte is not None else "",
        str(end_byte) if end_byte is not None else "",
        str(start_line) if start_line is not None else "",
        str(end_line) if end_line is not None else "",
        _escape_id_component(name),
    ]
    return "|".join(parts)


def build_relationship_id(
    source_id: str,
    target_id: str,
    rel_type: str,
    *,
    reference_start_byte: int | None = None,
    reference_end_byte: int | None = None,
    definition_start_byte: int | None = None,
    definition_end_byte: int | None = None,
    line_number: int | None = None,
    roles: "SymbolRole | int | None" = None,
) -> str:
    """Build a deterministic, non-hash relationship ID."""
    role_val = int(roles) if roles is not None else 0
    parts = [
        "rel",
        _escape_id_component(source_id),
        _escape_id_component(rel_type),
        _escape_id_component(target_id),
        str(reference_start_byte) if reference_start_byte is not None else "",
        str(reference_end_byte) if reference_end_byte is not None else "",
        str(definition_start_byte) if definition_start_byte is not None else "",
        str(definition_end_byte) if definition_end_byte is not None else "",
        str(line_number) if line_number is not None else "",
        str(role_val),
    ]
    return "|".join(parts)

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
    UNRESOLVED = auto()  # Deprecated in favor of EXTERNAL_SYMBOL
    EXTERNAL_SYMBOL = auto()  # Strict SCIP external reference node
    INFRASTRUCTURE_CONFIG = auto()
    ENVIRONMENT_VARIABLE = auto()
    # Markup / Config types
    SETTING = auto()  # Key-value pairs (JSON, YAML, TOML)
    SECTION = auto()  # Named sections/objects
    ELEMENT = auto()  # HTML/CSS/Markdown structural elements
    ATTRIBUTE = auto()  # Element attributes
    DOCUMENT = auto()  # Document-level entity
    SYNTAX_GLUE = auto()  # whitespace, comments, non-semantic segments
    GLOBAL_STATEMENT = auto()  # top-level executable statements
    IMPORT_BLOCK = auto()  # import-only regions
    COMMENT_BLOCK = auto()  # comment-only regions

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


class BSGViewType(Enum):
    """View types for dual-mode BSGMap rendering.

    STORAGE: Full-fidelity view with raw_content and hashes for reconstruction.
    AGENT: Compressed view optimized for LLM context, excluding SYNTAX_GLUE.
    """

    STORAGE = auto()
    AGENT = auto()

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

    model_config = {"frozen": True, "extra": "allow", "slots": True}

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
    raw_content: str | None = None
    content_hash: str = ""
    raw_bytes: bytes | None = None
    leading_whitespace: str = ""
    trailing_whitespace: str = ""
    ast_node_type: str | None = None
    children_order: list[str] = Field(default_factory=list)
    enclosing_start_byte: int | None = None
    enclosing_end_byte: int | None = None
    is_documentation: bool = False
    id_override: str | None = None

    @computed_field  # type: ignore[misc]
    @property
    def id(self) -> str:
        """Generate a unique, deterministic ID for this entity."""
        if self.id_override is not None:
            return self.id_override
        return build_entity_id(
            entity_type=self.type.name,
            name=self.name,
            file=self.file,
            start_byte=self.start_byte,
            end_byte=self.end_byte,
            start_line=self.start_line,
            end_line=self.end_line,
        )
    
    @property
    def fqn(self) -> str | None:
        """Fully qualified name of the entity."""
        if self.signature:
            return self.signature
        if self.type in (EntityType.CLASS, EntityType.MODULE, EntityType.NAMESPACE):
            return self.name
        return None

    @property
    def is_contextual_stub(self) -> bool:
        """Check if this entity is a contextual stub for unresolved cross-file references."""
        return self.type == EntityType.UNRESOLVED and self.id.startswith("unresolved:")

    def compute_content_hash(self) -> str:
        """Return a SHA256 hash of the raw content bytes."""
        if self.raw_content is None:
            raise ValueError("raw_content is required to compute content_hash")
        return compute_bytes_hash(self.raw_content.encode("utf-8"))

    def validate_coverage(self) -> bool:
        """Verify byte coverage aligns with raw_content length.

        Prefers raw_bytes when available for accurate byte length of
        non-UTF-8 content (replacement characters would inflate length).
        """
        if self.raw_content is None:
            return False
        if self.end_byte < self.start_byte:
            return False
        # Use raw_bytes if available for accurate byte length (handles invalid UTF-8)
        if self.raw_bytes is not None:
            byte_length = len(self.raw_bytes)
        else:
            byte_length = len(self.raw_content.encode("utf-8"))
        return (self.end_byte - self.start_byte) == byte_length

    def _evolve(self, **fields: Any) -> "Entity":
        """Return a copy of this Entity with the specified fields replaced.

        Uses Pydantic v2 ``model_copy(update=...)`` for efficient frozen-model
        copies, avoiding a full field-by-field reconstruction.  This is the
        canonical way to create a modified Entity without the 3× construction
        overhead of ``Entity(..., field=new_value, ...other_fields=...)``.

        Args:
            **fields: Field names and their new values.  Only the supplied
                      fields are changed; all others are inherited verbatim.

        Returns:
            A new frozen ``Entity`` instance with the requested updates applied.

        Example::

            enriched = entity._evolve(
                parent_id=parent_id,
                leading_whitespace=leading_str,
                children_order=child_ids,
            )
        """
        return self.model_copy(update=fields)

    def to_dict(self, *, view: str = "agent") -> dict[str, Any]:
        """Serialize this entity to a dict suitable for the requested view.

        Args:
            view: ``"agent"`` (default) — compact payload for LLM/cache use.
                  ``"storage"`` — full-fidelity payload including raw_content
                  and reconstruction metadata.

        Returns:
            Dictionary representation of the entity.

        Raises:
            ValueError: If *view* is not ``"agent"`` or ``"storage"``.
        """
        payload: dict[str, Any] = {
            "id": self.id,
            "id_override": self.id_override,
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
            "ast_node_type": self.ast_node_type,
            "enclosing_start_byte": self.enclosing_start_byte,
            "enclosing_end_byte": self.enclosing_end_byte,
            "is_documentation": self.is_documentation,
            # Persist children_order in agent view so it survives the AST cache.
            # Raw content is intentionally excluded from agent view to keep the
            # cache lightweight — it is dynamically regenerated on cache hits.
            "children_order": list(self.children_order),
        }
        if view == "storage":
            payload.update(
                {
                    "raw_content": self.raw_content,
                    "content_hash": self.content_hash,
                    "raw_bytes": self.raw_bytes if (self.raw_bytes is not None and self.raw_content is None) else None,
                    "leading_whitespace": self.leading_whitespace,
                    "trailing_whitespace": self.trailing_whitespace,
                    # Note: ast_node_type is already in the base payload above;
                    # it was previously duplicated here (SCH-07).
                }
            )
        elif view != "agent":
            raise ValueError(f"Unknown serialization view: {view}")
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Entity":
        d = data.copy()
        id_val = d.pop("id", None)
        # Preserve the serialized ID unconditionally to ensure identity stability.
        # The id_override takes precedence over the computed id property.
        if id_val is not None and "id_override" not in d:
            d["id_override"] = id_val
        if "type" in d and isinstance(d["type"], str):
            # Convert lowercase string to uppercase enum key
            type_str = d["type"].upper()
            try:
                d["type"] = EntityType[type_str]
            except KeyError:
                raise ValueError(
                    f"Unknown EntityType: {d['type']!r}. "
                    f"Valid values: {[e.name for e in EntityType]}"
                )
        # Deserialize raw_bytes from hex string (backward compatible with missing field)
        if "raw_bytes" in d and isinstance(d["raw_bytes"], str):
            try:
                d["raw_bytes"] = bytes.fromhex(d["raw_bytes"])
            except ValueError as exc:
                entity_id = d.get("id", "unknown")
                raise ValueError(
                    f"Entity {entity_id!r}: malformed hex in raw_bytes field"
                ) from exc
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

    model_config = {"frozen": True, "extra": "allow", "slots": True}

    source_id: str
    target_id: str
    type: RelationshipType
    roles: SymbolRole = SymbolRole(0)
    reference_start_byte: int | None = None
    reference_end_byte: int | None = None
    definition_start_byte: int | None = None
    definition_end_byte: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0

    # Note on confidence:
    # Mutating confidence inside a model validator for a frozen Pydantic model is not
    # supported. Instead, confidence scoring (e.g. 0.7 for SymbolRole.Heuristic) is
    # handled at construction time inside the extractor.

    @computed_field  # type: ignore[misc]
    @property
    def id(self) -> str:
        """Generate a unique, deterministic ID for this relationship.
        
        Includes line_number from metadata to differentiate multiple references
        to the same target from the same source (e.g., multiple calls to foo()).
        """
        line_number = self.metadata.get("line_number") if self.metadata else None
        return build_relationship_id(
            self.source_id,
            self.target_id,
            self.type.name,
            reference_start_byte=self.reference_start_byte,
            reference_end_byte=self.reference_end_byte,
            definition_start_byte=self.definition_start_byte,
            definition_end_byte=self.definition_end_byte,
            line_number=line_number,
            roles=self.roles,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type.name,
            "roles": int(self.roles),
            "reference_start_byte": self.reference_start_byte,
            "reference_end_byte": self.reference_end_byte,
            "definition_start_byte": self.definition_start_byte,
            "definition_end_byte": self.definition_end_byte,
            "metadata": self.metadata,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Relationship":
        d = data.copy()
        d.pop("id", None)
        if "type" in d and isinstance(d["type"], str):
            # Convert lowercase string to uppercase enum key
            type_str = d["type"].upper()
            d["type"] = RelationshipType[type_str]
        if "roles" in d:
            role_val = d["roles"]
            if isinstance(role_val, str):
                if role_val.isdigit():
                    d["roles"] = SymbolRole(int(role_val))
                else:
                    parts = [p.strip() for p in role_val.split(",") if p.strip()]
                    role_bits = SymbolRole(0)
                    for part in parts:
                        role_bits |= SymbolRole[part]
                    d["roles"] = role_bits
            else:
                d["roles"] = SymbolRole(role_val)
        return cls(**d)

    def _evolve(self, **fields: Any) -> "Relationship":
        """Return a copy of this Relationship with the specified fields replaced.

        Mirrors ``Entity._evolve``.  Uses Pydantic v2 ``model_copy(update=...)``
        so callers do not need to reconstruct every field manually.

        Args:
            **fields: Field names and their new values.

        Returns:
            A new frozen ``Relationship`` instance with the requested updates applied.
        """
        return self.model_copy(update=fields)

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


# --------------------------------------------------------------------------
# File reconstruction models
# --------------------------------------------------------------------------


class FileSnapshot(BaseModel):
    """File-level snapshot metadata for reconstruction."""

    model_config = {"frozen": True, "extra": "allow"}

    file_path: str = ""
    file_hash: str = ""
    file_size: int = 0
    encoding: str = ""
    entity_ids: list[str] = Field(default_factory=list)
    gap_sections: list[dict[str, Any]] = Field(default_factory=list)
    shebang: str | None = None
    encoding_declaration: str | None = None
    file_level_comments: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def create_opaque(cls, file_path: str, content: bytes, file_size: int | None = None) -> FileSnapshot:
        """Create a FileSnapshot for unindexable/opaque files."""
        from batho.utils.hash import _is_binary, compute_bytes_hash
        encoding = "binary" if _is_binary(content) else "utf-8"
        size = file_size if file_size is not None else len(content)
        return cls(
            file_path=file_path,
            file_hash=compute_bytes_hash(content),
            file_size=size,
            encoding=encoding,
            entity_ids=[],
            gap_sections=[],
        )


class ReconstructionResult(BaseModel):
    """Result summary for a reconstruction attempt."""

    model_config = {"frozen": True, "extra": "allow"}

    success: bool = False
    file_path: str = ""
    reconstructed_content: str = ""
    original_hash: str = ""
    reconstructed_hash: str = ""
    hash_match: bool = False
    entity_count: int = 0
    gap_count: int = 0
    byte_coverage: float = 0.0
    reconstruction_time_ms: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Coverage validation
# --------------------------------------------------------------------------


def validate_byte_coverage(
    entities: list[Entity],
    file_size: int,
    *,
    strict: bool = False,
    file_path: str = "",
) -> dict[str, Any]:
    """Verify that a list of entities provides complete, non-overlapping byte coverage.

    Args:
        entities: List of entities to validate. May include SYNTAX_GLUE entities.
        file_size: Total size of the file in bytes.
        strict: If True, raise ``CoverageError`` on any violation.
                If False (default), return a report dict with violations logged.
        file_path: Optional file path for error reporting.

    Returns:
        A report dict with keys:
        - ``byte_coverage``: Ratio of covered bytes (0.0 to 1.0).
        - ``total_bytes``: Total file size.
        - ``entity_bytes``: Sum of entity byte ranges.
        - ``gap_ranges``: List of (start, end) tuples for uncovered gaps.
        - ``overlap_ranges``: List of (start, end) tuples for overlapping ranges.
        - ``valid``: True if coverage is 100% with no issues.

    Raises:
        CoverageError: If ``strict=True`` and any violation is found.
    """
    if not entities and file_size == 0:
        return {
            "byte_coverage": 1.0,
            "total_bytes": 0,
            "entity_bytes": 0,
            "gap_ranges": [],
            "overlap_ranges": [],
            "valid": True,
        }

    sorted_ents = sorted(entities, key=lambda e: e.start_byte)
    total_entity_bytes = 0
    overlap_ranges: list[tuple[int, int]] = []
    gap_ranges: list[tuple[int, int]] = []

    # Walk entities to detect gaps and overlaps in a single O(N) pass.
    # Accumulate total_entity_bytes here to avoid a second O(N) sum() pass.
    cursor = 0
    for ent in sorted_ents:
        span = ent.end_byte - ent.start_byte
        total_entity_bytes += span
        if ent.start_byte < cursor:
            overlap_ranges.append((ent.start_byte, min(ent.end_byte, cursor)))
        if ent.start_byte > cursor:
            gap_ranges.append((cursor, ent.start_byte))
        cursor = max(cursor, ent.end_byte)

    # Trailing gap
    if cursor < file_size:
        gap_ranges.append((cursor, file_size))

    byte_coverage = total_entity_bytes / file_size if file_size > 0 else 1.0

    report = {
        "byte_coverage": byte_coverage,
        "total_bytes": file_size,
        "entity_bytes": total_entity_bytes,
        "gap_ranges": gap_ranges,
        "overlap_ranges": overlap_ranges,
        "valid": not gap_ranges and not overlap_ranges,
    }

    if strict and (gap_ranges or overlap_ranges):
        raise CoverageError(
            message=(
                f"Byte coverage validation failed for {file_path or 'unknown'}: "
                f"{byte_coverage:.2%} coverage, "
                f"{len(gap_ranges)} gap(s), "
                f"{len(overlap_ranges)} overlap(s)"
            ),
            file_path=file_path,
            byte_coverage=byte_coverage,
            overlapping_ranges=overlap_ranges,
            gap_ranges=gap_ranges,
        )

    return report
