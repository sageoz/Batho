"""
context/languages/detector.py — Multi-strategy language detection.

Provides intelligent language detection beyond simple file extension matching:
1. Extension-based detection (primary)
2. Shebang line detection
3. Magic bytes detection
4. Content-based heuristics

The detector returns the language name and confidence level, enabling
graceful handling of ambiguous or unknown files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from batho_core.utils.logging import get_logger

from .registry import (
    _EXT_TO_LANG,
    get_extractor_for_language,
    is_language_available,
)

# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------

_logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """
    Result of language detection with confidence level.

    Attributes:
        language: Detected language identifier (e.g., "python", "php", "json")
        confidence: Confidence level from 0.0 to 1.0
        method: Detection method used ("extension", "shebang", "magic_bytes", "heuristics")
        details: Additional details about the detection (optional)
    """

    language: str
    confidence: float
    method: str
    details: str | None = None

    def is_confident(self, threshold: float = 0.7) -> bool:
        """Check if detection confidence meets the threshold."""
        return self.confidence >= threshold

    def is_available(self) -> bool:
        """Check if the detected language has an available parser."""
        return is_language_available(self.language)


# ---------------------------------------------------------------------------
# Detection strategies
# ---------------------------------------------------------------------------


def detect_by_extension(filepath: Path, content: bytes) -> DetectionResult | None:
    """
    Detect language by file extension.

    This is the primary detection method with highest confidence.

    Args:
        filepath: Path to the file
        content: File content (unused for extension detection)

    Returns:
        DetectionResult with confidence 1.0 if extension matches, None otherwise
    """
    ext = filepath.suffix.lower()
    if ext in _EXT_TO_LANG:
        language = _EXT_TO_LANG[ext]
        _logger.debug(
            "detection_by_extension",
            ext=ext,
            lang=language,
        )
        return DetectionResult(
            language=language,
            confidence=1.0,
            method="extension",
            details=f"Matched extension: {ext}",
        )
    return None


# Special filename mappings for extensionless files
_SPECIAL_FILENAME_MAP: dict[str, tuple[str, float]] = {
    # Python version files
    ".python-version": ("python", 1.0),
    # Docker/Container files
    "Dockerfile": ("docker", 1.0),
    "Dockerfile.dev": ("docker", 1.0),
    "Dockerfile.prod": ("docker", 1.0),
    "Dockerfile.test": ("docker", 1.0),
    "docker-compose.yml": ("docker", 1.0),
    "docker-compose.yaml": ("docker", 1.0),
    "docker-compose.dev.yml": ("docker", 1.0),
    "docker-compose.prod.yml": ("docker", 1.0),
    # Make/Build files
    "Makefile": ("make", 1.0),
    "GNUmakefile": ("make", 1.0),
    "makefile": ("make", 1.0),
    # Environment files
    ".env": ("dotenv", 1.0),
    ".env.local": ("dotenv", 1.0),
    ".env.dev": ("dotenv", 1.0),
    ".env.development": ("dotenv", 1.0),
    ".env.test": ("dotenv", 1.0),
    ".env.production": ("dotenv", 1.0),
    ".env.prod": ("dotenv", 1.0),
    ".env.example": ("dotenv", 1.0),
    ".env.template": ("dotenv", 1.0),
    # Ignore files (treated as config)
    ".gitignore": ("gitignore", 1.0),
    ".dockerignore": ("gitignore", 1.0),
    ".bathoignore": ("gitignore", 1.0),
    # Build/Package files
    "PKGBUILD": ("bash", 0.8),
    # Scripts without extension
    "build": ("bash", 0.7),
    "install": ("bash", 0.7),
    "configure": ("bash", 0.7),
}


def detect_by_special_filename(filepath: Path, content: bytes) -> DetectionResult | None:
    """
    Detect language/format by special filename patterns.

    This handles files like .python-version, Dockerfile, Makefile, .env, etc.
    that don't have traditional extensions but are commonly recognized.

    Args:
        filepath: Path to the file
        content: File content (unused for special filename detection)

    Returns:
        DetectionResult with confidence 1.0 if special filename matches, None otherwise
    """
    # Get the filename (without directory path)
    filename = filepath.name

    # Check exact match
    if filename in _SPECIAL_FILENAME_MAP:
        language, confidence = _SPECIAL_FILENAME_MAP[filename]
        _logger.debug(
            "detection_by_special_filename",
            filename=filename,
            lang=language,
        )
        return DetectionResult(
            language=language,
            confidence=confidence,
            method="special_filename",
            details=f"Matched special filename: {filename}",
        )

    return None


# Shebang patterns for common interpreted languages
_SHEBANG_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Python
    (re.compile(rb"^#!.*\bpython[0-9.]*\b"), "python"),
    (re.compile(rb"^#!.*\bpython3\b"), "python"),
    # Ruby
    (re.compile(rb"^#!.*\bruby\b"), "ruby"),
    # Perl
    (re.compile(rb"^#!.*\bperl\b"), "perl"),
    (re.compile(rb"^#!.*\bperl5\b"), "perl"),
    # Bash/Shell
    (re.compile(rb"^#!.*\b/bash\b"), "bash"),
    (re.compile(rb"^#!.*\b/sh\b"), "bash"),
    (re.compile(rb"^#!.*\bzsh\b"), "bash"),
    (re.compile(rb"^#!.*\bfish\b"), "bash"),
    (re.compile(rb"^#!.*\bksh\b"), "bash"),
    # Node.js
    (re.compile(rb"^#!.*\bnode\b"), "javascript"),
    # PHP
    (re.compile(rb"^#!.*\bphp\b"), "php"),
    # Lua
    (re.compile(rb"^#!.*\blua\b"), "lua"),
    # R
    (re.compile(rb"^#!.*\bR\b"), "r"),
    (re.compile(rb"^#!.*\bRscript\b"), "r"),
]


def detect_by_shebang(content: bytes) -> DetectionResult | None:
    """
    Detect language by shebang line (#!).

    The shebang is typically the first line of executable script files.

    Args:
        content: File content (at least first line needed)

    Returns:
        DetectionResult with confidence 0.9 if shebang matches, None otherwise
    """
    if not content:
        return None

    # Find the first line
    first_line_end = content.find(b"\n")
    if first_line_end == -1:
        first_line = content
    else:
        first_line = content[:first_line_end]

    # Check if it starts with shebang
    if not first_line.startswith(b"#!"):
        return None

    # Try each shebang pattern
    for pattern, language in _SHEBANG_PATTERNS:
        if pattern.search(first_line):
            _logger.debug(
                "detection_by_shebang",
                lang=language,
                shebang=first_line[:50].decode("utf-8", errors="replace"),
            )
            return DetectionResult(
                language=language,
                confidence=0.9,
                method="shebang",
                details=first_line[:50].decode("utf-8", errors="replace").strip(),
            )

    return None


# Magic bytes patterns for binary/compiled formats
_MAGIC_BYTES_PATTERNS: list[tuple[bytes, str, float]] = [
    # ELF executables
    (b"\x7fELF", "c", 0.8),
    # Java class files
    (b"\xca\xfe\xba\xbe", "java", 0.8),
    # Python bytecode (PEP 3147)
    (b"#!\x00", "python", 0.7),  # Python bytecode file
    # PDF
    (b"%PDF", "html", 0.5),  # Could be embedded HTML
    # ZIP (used by many formats including docx, xlsx, odt)
    (b"PK\x03\x04", "json", 0.3),  # Could be JSON in ZIP
    # GZIP (often used for .pyc files)
    (b"\x1f\x8b", "python", 0.6),  # Could be compressed bytecode
]


def detect_by_magic_bytes(content: bytes) -> DetectionResult | None:
    """
    Detect language by magic bytes (file signature).

    Magic bytes are characteristic byte sequences at the start of files.

    Args:
        content: File content (first few bytes needed)

    Returns:
        DetectionResult with confidence based on magic byte specificity, or None
    """
    if len(content) < 4:
        return None

    # Check first 16 bytes for magic patterns
    prefix = content[:16]

    for magic, language, confidence in _MAGIC_BYTES_PATTERNS:
        if prefix.startswith(magic):
            _logger.debug(
                "detection_by_magic_bytes",
                lang=language,
                magic=magic.hex(),
            )
            return DetectionResult(
                language=language,
                confidence=confidence,
                method="magic_bytes",
                details=f"Magic bytes: {magic.hex()}",
            )

    return None


# Content-based heuristics for common patterns
_CONTENT_HEURISTICS: list[tuple[re.Pattern[str], str, float]] = [
    # PHP (<?php or <?= tag)
    (re.compile(rb"<\?php\s", re.IGNORECASE), "php", 0.9),
    (re.compile(rb"<\?="), "php", 0.7),  # Short echo tag
    # Hack (<?hh tag)
    (re.compile(rb"<\?hh\b", re.IGNORECASE), "hack", 0.9),
    # HTML/XML
    (
        re.compile(rb"^\s*<(!DOCTYPE|html|head|body|div|span|p|a|script|style)", re.IGNORECASE),
        "html",
        0.8,
    ),
    (re.compile(rb"^\s*<\?xml\s+version="), "html", 0.9),
    # TOML (table headers) - Check BEFORE JSON since [section] is valid TOML
    (re.compile(rb"^\[[\w.-]+\]"), "toml", 0.8),
    # JSON (starts with { or [ and is valid JSON)
    (re.compile(rb"^\s*\{"), "json", 0.7),
    (re.compile(rb"^\s*\["), "json", 0.7),
    # YAML (document start or common YAML patterns)
    (re.compile(rb"^---\s*$", re.MULTILINE), "yaml", 0.8),
    (re.compile(rb"^\w+:\s*$", re.MULTILINE), "yaml", 0.5),  # Key-value without quotes
    # CSS
    (re.compile(rb"^\s*[@.]?[a-z-]+\s*\{", re.IGNORECASE), "css", 0.7),
    # Markdown (common patterns)
    (re.compile(rb"^#{1,6}\s+", re.MULTILINE), "markdown", 0.6),
    (re.compile(rb"^\*\*[^*]+\*\*", re.MULTILINE), "markdown", 0.5),
    # HCL/Terraform
    (re.compile(rb"^\s*resource\s+", re.MULTILINE), "hcl", 0.8),
    (re.compile(rb"^\s*variable\s+", re.MULTILINE), "hcl", 0.8),
    (re.compile(rb"^\s*provider\s+", re.MULTILINE), "hcl", 0.8),
]


def detect_by_content_heuristics(content: bytes) -> DetectionResult | None:
    """
    Detect language by content patterns and heuristics.

    This is a fallback method when extension, shebang, and magic bytes
    don't provide a definitive answer.

    Args:
        content: File content for pattern matching

    Returns:
        DetectionResult with confidence based on pattern specificity, or None
    """
    if not content:
        return None

    # Limit content for performance
    sample = content[:4096]

    for pattern, language, confidence in _CONTENT_HEURISTICS:
        if pattern.search(sample):
            _logger.debug(
                "detection_by_heuristics",
                lang=language,
                confidence=confidence,
            )
            return DetectionResult(
                language=language,
                confidence=confidence,
                method="heuristics",
                details=f"Matched pattern: {pattern.pattern}",
            )

    return None


# ---------------------------------------------------------------------------
# Language detector
# ---------------------------------------------------------------------------


class LanguageDetector:
    """
    Multi-strategy language detector.

    Detection is performed in order of confidence:
    1. Extension (highest confidence)
    2. Shebang
    3. Magic bytes
    4. Content heuristics (lowest confidence)

    The detector automatically handles graceful degradation by checking
    if the detected language has an available parser.
    """

    # Detection strategies in order of priority
    STRATEGIES: list[tuple[str, callable]] = [
        ("extension", detect_by_extension),
        ("special_filename", detect_by_special_filename),
        ("shebang", detect_by_shebang),
        ("magic_bytes", detect_by_magic_bytes),
        ("heuristics", detect_by_content_heuristics),
    ]

    def __init__(self, min_confidence: float = 0.5) -> None:
        """
        Initialize the language detector.

        Args:
            min_confidence: Minimum confidence threshold for detection.
                           Lower confidence results are treated as unknown.
        """
        self._min_confidence = min_confidence

    def detect(
        self,
        filepath: Path,
        content: bytes,
    ) -> DetectionResult | None:
        """
        Detect language using multiple strategies.

        Strategies are tried in order until one succeeds with sufficient
        confidence. The first successful detection is returned.

        Args:
            filepath: Path to the file (used for extension detection)
            content: File content (used for shebang, magic bytes, heuristics)

        Returns:
            DetectionResult with confidence >= min_confidence, or None if
            no language could be detected with sufficient confidence.
        """
        # Try each strategy in order of priority
        for strategy_name, strategy_fn in self.STRATEGIES:
            # Extension and special_filename detection need filepath, others use content
            if strategy_name in ("extension", "special_filename"):
                result = strategy_fn(filepath, content)
            else:
                result = strategy_fn(content)

            if result and result.confidence >= self._min_confidence:
                return result

        _logger.debug(
            "detection_failed",
            filepath=str(filepath),
            min_confidence=self._min_confidence,
        )
        return None

    def detect_with_fallback(
        self,
        filepath: Path,
        content: bytes,
    ) -> DetectionResult | None:
        """
        Detect language with fallback to extension-only detection.

        If full detection fails, this method tries extension detection
        even with lower confidence, as extension is often reliable even
        if the content doesn't match expected patterns.

        Args:
            filepath: Path to the file
            content: File content

        Returns:
            DetectionResult if any detection succeeded, None otherwise
        """
        # First try full detection
        result = self.detect(filepath, content)
        if result is not None:
            return result

        # Fallback: try special filename detection
        result = detect_by_special_filename(filepath, content)
        if result is not None:
            _logger.debug(
                "detection_fallback_to_special_filename",
                filepath=str(filepath),
                lang=result.language,
            )
            return result

        # Fallback: try extension only with lower threshold
        result = detect_by_extension(filepath, content)
        if result is not None:
            _logger.debug(
                "detection_fallback_to_extension",
                filepath=str(filepath),
                lang=result.language,
            )
            return result

        return None

    def get_extractor(
        self,
        filepath: Path,
        content: bytes,
    ) -> object | None:
        """
        Detect language and return an extractor instance.

        This is a convenience method that combines detection with
        extractor retrieval. It only returns an extractor if:
        1. Language was detected with sufficient confidence
        2. The language parser is available

        Args:
            filepath: Path to the file
            content: File content

        Returns:
            An ASTExtractor instance, or None if detection failed
            or the language parser is not available.
        """
        result = self.detect_with_fallback(filepath, content)
        if result is None:
            return None

        # Check if parser is available
        if not result.is_available():
            _logger.debug(
                "detector_parser_not_available",
                lang=result.language,
                method=result.method,
            )
            return None

        return get_extractor_for_language(result.language)


# ---------------------------------------------------------------------------
# Convenience instances
# ---------------------------------------------------------------------------

# Default detector with standard confidence threshold
default_detector = LanguageDetector(min_confidence=0.5)

# Permissive detector with lower threshold for more detections
permissive_detector = LanguageDetector(min_confidence=0.3)

# Strict detector for higher confidence requirements
strict_detector = LanguageDetector(min_confidence=0.7)


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def detect_language(
    filepath: str | Path,
    content: bytes,
) -> DetectionResult | None:
    """
    Detect language for a file using the default detector.

    Args:
        filepath: Path to the file
        content: File content

    Returns:
        DetectionResult if language detected, None otherwise
    """
    return default_detector.detect(Path(filepath), content)


def detect_language_with_fallback(
    filepath: str | Path,
    content: bytes,
) -> DetectionResult | None:
    """
    Detect language with fallback strategy.

    Args:
        filepath: Path to the file
        content: File content

    Returns:
        DetectionResult if language detected, None otherwise
    """
    return default_detector.detect_with_fallback(Path(filepath), content)
