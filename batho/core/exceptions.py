"""Custom exception definitions for Batho."""

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
