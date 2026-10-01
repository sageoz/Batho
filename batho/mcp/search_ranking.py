"""T8 (graph-accuracy-overhaul): deterministic, kind-aware search scoring.

`search_entities` and the `get_entity` name fallback share this scorer so real
definitions (exact-FQN, exported code symbols) outrank comments, externals, and
test-fixture noise. All weights are named module constants — tune here or
surface them under a `search.ranking` config section; never inline.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

# --- match strength ---------------------------------------------------------
SCORE_EXACT_NAME = 100
SCORE_PREFIX = 60
SCORE_SUBSTRING = 30
# Defensive floor — unreachable through search_entities (Arrow matching
# guarantees a literal or regex-meta hit, both scoring SCORE_SUBSTRING). Kept
# for direct callers that score rows matched outside Arrow.
SCORE_ID_ONLY = 10

# --- entity-kind boost ------------------------------------------------------
KIND_BOOST: dict[str, int] = {
    "CLASS": 40,
    "METHOD": 40,
    "FUNCTION": 40,
    "INTERFACE": 40,
    "MODULE": 30,
    "COMMENT_BLOCK": -40,
    # Post-quarantine these are legit externals (e.g. fastapi.Depends), demoted
    # but never hidden — ranking must not drop recall.
    "EXTERNAL_SYMBOL": -25,
}

SCORE_EXPORTED = 15
SCORE_FQN_PATH = 20
SCORE_LANGUAGE_HINT = 5
# Test fixtures demoted — the spec's motivating bug was test methods
# outranking the real definition on equal match strength.
SCORE_TEST_PATH = -15

# Emitter-side `_PARAM_HASH_PATTERN` (`_[a-fA-F0-9]+`) produces any-length
# mixed-case hex — the scorer must strip the same shape or exact-match
# scoring silently degrades to prefix/substring on e.g. `x_[80AB]`, `x_[12345]`.
_HASH_SUFFIX = re.compile(r"_\[[a-fA-F0-9]+\]$")
_REGEX_META = re.compile(r"[.\[\]{}()*+?^$|\\]")

# Qualified-name / import-path separators native to each language. The +5
# same-language hint is driven by the *hit entity's* language (derived from
# its file extension), not by guessing from query text — a `.`/`::`-only check
# would miss php `\`, go `/`, and ts `@/` alias queries.
LANGUAGE_SEPARATORS: dict[str, tuple[str, ...]] = {
    "python": (".",),
    "typescript": (".", "/", "./", "@/"),
    "javascript": (".", "/", "./", "@/"),
    "rust": ("::",),
    "go": ("/", "."),
    "java": (".",),
    "kotlin": (".",),
    "scala": (".",),
    "csharp": (".",),
    "swift": (".",),
    "dart": (".", "package:"),
    "cpp": ("::",),
    "ruby": ("::",),
    "perl": ("::",),
    "php": ("\\", "::"),
    "r": ("::",),
    "haskell": (".",),
    "ocaml": (".",),
    "julia": (".",),
    "erlang": (":",),
    "lua": (".", ":"),
    "zig": (".",),
    "verilog": (".",),
}

_EXT_TO_LANG_CACHE: dict[str, str] | None = None


def language_for_path(file_path: str) -> str:
    """Map a repo-relative file path to its parser language ("" if unknown)."""
    global _EXT_TO_LANG_CACHE
    if _EXT_TO_LANG_CACHE is None:
        # Lazy import: keeps this module dependency-free for unit tests and
        # avoids the parser_factory import chain during tools.py import.
        from batho.modules.extraction.submodules.parser_factory.registry import (
            _EXT_TO_LANG,
        )

        _EXT_TO_LANG_CACHE = _EXT_TO_LANG
    suffix = PurePosixPath(file_path).suffix
    return _EXT_TO_LANG_CACHE.get(suffix) or _EXT_TO_LANG_CACHE.get(suffix.lower(), "")


def _match_score(name: str, query: str) -> int:
    if name == query:
        return SCORE_EXACT_NAME
    if name.startswith(query):
        return SCORE_PREFIX
    if query in name:
        return SCORE_SUBSTRING
    # Regex queries (e.g. `get_.*`) never literal-match; a regex hit scores
    # like a substring rather than collapsing to the id-only floor. The user
    # pattern is never re-executed here — callers only pass rows that already
    # matched Arrow-side (RE2 `match_substring_regex` or `match_substring`),
    # and Python `re` on a user pattern is a ReDoS vector.
    if _REGEX_META.search(query):
        return SCORE_SUBSTRING
    return SCORE_ID_ONLY


def _norm_segment(text: str) -> str:
    """Case/underscore-insensitive segment comparison: `ProcessManager` ≡
    `process_manager` ≡ `process-manager`."""
    return re.sub(r"[_\-.\s]", "", text).lower()


def _path_segment_match(query: str, file_path: str) -> bool:
    """True when the normalized query appears inside a single real path
    segment — never spans the `/` boundary, so `appreg` cannot match
    `app/registry.py`. Within-segment substring is intentional (a +20 hint,
    not edge creation)."""
    if not file_path or not query:
        return False
    nq = _norm_segment(query)
    if not nq:
        return False
    return any(
        nq in _norm_segment(seg) for seg in PurePosixPath(file_path).parts
    )


_TEST_DIR_SEGMENTS = frozenset(
    {"test", "tests", "testing", "spec", "specs", "__tests__", "test_utils"}
)
_TEST_FILE_RE = re.compile(r"(^test_.+|.+_test|.+\.test|.+\.spec)\.[^.]+$")


def _is_test_path(file_path: str) -> bool:
    """True for test-directory paths (`tests/`, `__tests__/`) or test-named
    files (`test_x.py`, `x_test.go`, `x.test.ts`, `x.spec.ts`)."""
    if not file_path:
        return False
    parts = PurePosixPath(file_path).parts
    if not parts:
        return False
    if any(seg.lower() in _TEST_DIR_SEGMENTS for seg in parts[:-1]):
        return True
    return bool(_TEST_FILE_RE.match(parts[-1].lower()))


# Per-file scoring inputs: (file_path, language, path_segment_match, is_test).
# Derived once per unique file_id inside `rank_hits` — file paths repeat
# heavily across rows, so per-row path parsing/regex work is wasted.
FileInfo = tuple[str, str, bool, bool]


def _derive_file_info(file_path: str, query: str) -> FileInfo:
    return (
        file_path,
        language_for_path(file_path),
        _path_segment_match(query, file_path),
        _is_test_path(file_path),
    )


def score_hit(
    row: dict[str, Any],
    query: str,
    file_path: str = "",
    language: str = "",
    file_info: FileInfo | None = None,
) -> int:
    """Deterministic score for one search hit. Higher ranks first.

    `file_info` is an optional precomputed `(file_path, language,
    path_segment_match, is_test)` tuple (see `_derive_file_info`); when given
    it takes precedence over the `file_path`/`language` args. `rank_hits`
    precomputes it once per unique file so per-row scoring stays cheap.
    """
    if file_info is None:
        file_info = (
            file_path,
            language,
            _path_segment_match(query, file_path),
            _is_test_path(file_path),
        )
    _, language, path_match, is_test = file_info
    name = _HASH_SUFFIX.sub("", str(row.get("name") or ""))
    score = _match_score(name, query)
    score += KIND_BOOST.get(str(row.get("entity_type") or ""), 0)
    if row.get("is_exported"):
        score += SCORE_EXPORTED
    fqn = str(row.get("fqn") or "")
    if (fqn and query in fqn) or path_match:
        score += SCORE_FQN_PATH
    if language and any(
        sep in query for sep in LANGUAGE_SEPARATORS.get(language, ())
    ):
        score += SCORE_LANGUAGE_HINT
    if is_test:
        score += SCORE_TEST_PATH
    return score


def rank_hits(
    rows: list[dict[str, Any]], query: str, file_paths: dict[int, str]
) -> list[tuple[dict[str, Any], int]]:
    """Score and sort hits: score desc, then start_line asc, file asc, id asc.

    Total order is deterministic — identical inputs always produce identical
    ordering (snapshot-stable).
    """
    # Memoize per-file_id derived data once per call: without this, every row
    # pays ~3 path parses + regex subs (language_for_path, _path_segment_match,
    # _is_test_path) even though file paths repeat heavily across rows.
    info_cache: dict[int, FileInfo] = {}

    def _file_info(file_id: int) -> FileInfo:
        info = info_cache.get(file_id)
        if info is None:
            info = _derive_file_info(file_paths.get(file_id, ""), query)
            info_cache[file_id] = info
        return info

    scored = [
        (
            row,
            score_hit(row, query, file_info=_file_info(row.get("file_id", -1))),
        )
        for row in rows
    ]
    scored.sort(
        key=lambda rs: (
            -rs[1],
            rs[0].get("start_line") or 0,
            file_paths.get(rs[0].get("file_id", -1), ""),
            str(rs[0].get("entity_id") or ""),
        )
    )
    return scored
