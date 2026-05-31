from typing import Optional, List, Any
from dataclasses import dataclass, field
from enum import Enum

from batho.core.schemas import Entity, Relationship

class ExtractionStatus(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"  # Some entities extracted, some failed
    FAILED = "failed"    # Complete failure

@dataclass
class ExtractionError:
    """Error during extraction."""
    error_type: str
    message: str
    line: Optional[int] = None
    column: Optional[int] = None

@dataclass
class ExtractionResult:
    """Result of extraction with status tracking."""
    status: ExtractionStatus
    entities: List[Entity]
    relationships: List[Relationship]
    errors: List[ExtractionError]
    file_path: str
    fallback_used: bool = False
    
    @property
    def success_rate(self) -> float:
        """Calculate extraction success rate."""
        total = len(self.entities) + len(self.errors)
        if total == 0:
            return 1.0
        return len(self.entities) / total
