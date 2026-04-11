"""Mine deterministic framework conventions from source files."""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Framework-specific naming convention patterns
_NAMING_PATTERNS: dict[str, dict[str, list[str]]] = {
    "python": {
        "controller": [r".*_controller\.py$", r".*_views\.py$", r"views\.py$"],
        "model": [r".*_model\.py$", r"models\.py$", r".*_schema\.py$"],
        "service": [r".*_service\.py$", r"services\.py$"],
        "middleware": [r".*_middleware\.py$", r"middleware\.py$"],
        "route": [r".*_routes\.py$", r"routes\.py$", r"urls\.py$"],
        "config": [r".*_config\.py$", r"config\.py$", r"settings\.py$"],
    },
    "javascript": {
        "controller": [r".*[-_]controller\.[jt]sx?$", r".*[-_]handler\.[jt]sx?$"],
        "model": [r".*[-_]model\.[jt]sx?$", r"models?\.[jt]sx?$"],
        "service": [r".*[-_]service\.[jt]sx?$", r"services?\.[jt]sx?$"],
        "middleware": [r".*[-_]middleware\.[jt]sx?$"],
        "route": [r".*[-_]routes?\.[jt]sx?$", r"router\.[jt]sx?$"],
        "config": [r"config\.[jt]sx?$", r".*[-_]config\.[jt]sx?$"],
    },
    "typescript": {
        "controller": [r".*[-.]controller\.ts$", r".*[-.]handler\.ts$"],
        "model": [r".*[-.]model\.ts$", r".*[-.]entity\.ts$"],
        "service": [r".*[-.]service\.ts$", r".*[-.]provider\.ts$"],
        "middleware": [
            r".*[-.]middleware\.ts$",
            r".*[-.]guard\.ts$",
            r".*[-.]interceptor\.ts$",
        ],
        "route": [r".*[-.]route\.ts$", r".*[-.]module\.ts$", r"app\.module\.ts$"],
        "config": [r".*[-.]config\.ts$", r".*[-.]options\.ts$"],
    },
    "go": {
        "controller": [r"handler[s]?\.go$", r".*_handler\.go$"],
        "model": [r"model[s]?\.go$", r".*_model\.go$"],
        "service": [r"service[s]?\.go$", r".*_service\.go$"],
        "middleware": [r"middleware[s]?\.go$", r".*_middleware\.go$"],
        "route": [r"router[s]?\.go$", r"route[s]?\.go$", r".*_route\.go$"],
        "config": [r"config[s]?\.go$", r".*_config\.go$"],
    },
    "java": {
        "controller": [
            r".*Controller\.java$",
            r".*Resource\.java$",
            r".*Endpoint\.java$",
        ],
        "model": [r".*Model\.java$", r".*Entity\.java$", r".*Dto\.java$"],
        "service": [r".*Service\.java$", r".*ServiceImpl\.java$"],
        "middleware": [
            r".*Filter\.java$",
            r".*Interceptor\.java$",
            r".*Handler\.java$",
        ],
        "route": [r".*Route\.java$", r".*Router\.java$"],
        "config": [
            r".*Config\.java$",
            r".*Configuration\.java$",
            r".*Properties\.java$",
        ],
    },
    "csharp": {
        "controller": [r".*Controller\.cs$", r".*ApiController\.cs$"],
        "model": [
            r".*Model\.cs$",
            r".*Entity\.cs$",
            r".*Dto\.cs$",
            r".*ViewModel\.cs$",
        ],
        "service": [r".*Service\.cs$", r".*IService\.cs$"],
        "middleware": [r".*Middleware\.cs$", r".*Filter\.cs$"],
        "route": [r".*Route\.cs$", r"Program\.cs$", r"Startup\.cs$"],
        "config": [r".*Config\.cs$", r".*Settings\.cs$", r"appsettings.*\.json$"],
    },
    "php": {
        "controller": [r".*Controller\.php$", r".*Resource\.php$"],
        "model": [r".*\.php$"],  # Laravel: models are just PHP classes
        "service": [r".*Service\.php$", r".*Repository\.php$"],
        "middleware": [r".*Middleware\.php$"],
        "route": [r".*routes.*\.php$"],
        "config": [r".*\.php$"],
    },
    "ruby": {
        "controller": [r".*_controller\.rb$", r"controllers/.*\.rb$"],
        "model": [r".*_model\.rb$", r"models/.*\.rb$"],
        "service": [r".*_service\.rb$", r"services/.*\.rb$"],
        "middleware": [r".*_middleware\.rb$", r"middleware/.*\.rb$"],
        "route": [r"routes\.rb$", r".*_routes\.rb$"],
        "config": [r".*_config\.rb$", r"config\.rb$", r"config/.*\.rb$"],
    },
    "rust": {
        "controller": [r"handler[s]?\.rs$", r".*_handler\.rs$"],
        "model": [r"model[s]?\.rs$", r".*types\.rs$", r".*dto\.rs$"],
        "service": [r"service[s]?\.rs$", r".*_service\.rs$"],
        "middleware": [
            r"middleware[s]?\.rs$",
            r".*layer\.rs$",
            r".*middleware/.*\.rs$",
        ],
        "route": [r"router[s]?\.rs$", r"route[s]?\.rs$", r".*_routes\.rs$"],
        "config": [r"config[s]?\.rs$", r".*_config\.rs$"],
    },
}

# Cross-entity relationship motifs by language
_RELATIONSHIP_MOTIFS: dict[str, list[dict[str, Any]]] = {
    "python": [
        {
            "pattern": r"@app\.route\(['\"]",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "flask_route_decorator",
        },
        {
            "pattern": r"@router\.(get|post|put|delete|patch)\(",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "fastapi_router_decorator",
        },
        {
            "pattern": r"class \w+\(.*db\.Model",
            "edge": "INHERITS",
            "source_tag": "Orm_Model",
            "reason": "sqlalchemy_model",
        },
        {
            "pattern": r"@login_required",
            "edge": "WRAPPED_BY",
            "source_tag": "AuthMiddleware",
            "reason": "flask_login_required",
        },
    ],
    "javascript": [
        {
            "pattern": r"app\.(get|post|put|delete|use)\(",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "express_route",
        },
        {
            "pattern": r"router\.(get|post|put|delete|use)\(",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "express_router",
        },
    ],
    "typescript": [
        {
            "pattern": r"@Controller\(",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "nestjs_controller_decorator",
        },
        {
            "pattern": r"@Injectable\(\)",
            "edge": "USES",
            "source_tag": None,
            "reason": "nestjs_injectable",
        },
        {
            "pattern": r"@Get\(|@Post\(|@Put\(|@Delete\(",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "nestjs_method_decorator",
        },
        {
            "pattern": r"@UseGuards\(",
            "edge": "WRAPPED_BY",
            "source_tag": "AuthMiddleware",
            "reason": "nestjs_auth_guard",
        },
    ],
    "go": [
        {
            "pattern": r"\.(GET|POST|PUT|DELETE|Handle)\(",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "gin_route_method",
        },
        {
            "pattern": r"gin\.Engine",
            "edge": "USES",
            "source_tag": None,
            "reason": "gin_engine_usage",
        },
        {
            "pattern": r"r\.Use\(",
            "edge": "WRAPPED_BY",
            "source_tag": "AuthMiddleware",
            "reason": "gin_middleware_use",
        },
    ],
    "java": [
        {
            "pattern": r"@RestController|@Controller",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "spring_controller",
        },
        {
            "pattern": r"@GetMapping|@PostMapping|@PutMapping|@DeleteMapping",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "spring_mapping",
        },
        {
            "pattern": r"@Service",
            "edge": "USES",
            "source_tag": None,
            "reason": "spring_service",
        },
        {
            "pattern": r"@PreAuthorize|@Secured",
            "edge": "WRAPPED_BY",
            "source_tag": "AuthMiddleware",
            "reason": "spring_auth",
        },
    ],
    "csharp": [
        {
            "pattern": r"\[ApiController\]|\[Route\(",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "aspnet_controller",
        },
        {
            "pattern": r"\[HttpGet\]|\[HttpPost\]|\[HttpPut\]|\[HttpDelete\]",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "aspnet_http_method",
        },
        {
            "pattern": r"\[Authorize\]",
            "edge": "WRAPPED_BY",
            "source_tag": "AuthMiddleware",
            "reason": "aspnet_authorize",
        },
    ],
    "php": [
        {
            "pattern": r"Route::(get|post|put|delete|any)\(",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "laravel_route",
        },
        {
            "pattern": r"->middleware\(",
            "edge": "WRAPPED_BY",
            "source_tag": "AuthMiddleware",
            "reason": "laravel_middleware",
        },
        {
            "pattern": r"extends Model",
            "edge": "INHERITS",
            "source_tag": "Orm_Model",
            "reason": "eloquent_model",
        },
    ],
    "ruby": [
        {
            "pattern": r"(get|post|put|delete|patch)\s+['\"]",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "sinatra_route",
        },
        {
            "pattern": r"use\s+\w+.*Middleware",
            "edge": "WRAPPED_BY",
            "source_tag": "AuthMiddleware",
            "reason": "sinatra_middleware",
        },
    ],
    "rust": [
        {
            "pattern": r"\.(get|post|put|delete|route)\(",
            "edge": "CALLS",
            "source_tag": "ApiBoundary",
            "reason": "axum_route",
        },
        {
            "pattern": r"Router::new\(\)",
            "edge": "USES",
            "source_tag": None,
            "reason": "axum_router",
        },
        {
            "pattern": r"\.layer\(",
            "edge": "WRAPPED_BY",
            "source_tag": "AuthMiddleware",
            "reason": "axum_middleware_layer",
        },
    ],
}


def _classify_file(filepath: Path, language: str) -> str | None:
    """Classify a file by naming convention → role (controller/model/service/etc)."""

    patterns = _NAMING_PATTERNS.get(language, {})
    fname = filepath.name.lower()
    fpath_str = filepath.as_posix().lower()

    for role, regexes in patterns.items():
        for regex in regexes:
            if re.search(regex, fname) or re.search(regex, fpath_str):
                return role
    return None


def _count_lines(filepath: Path) -> int:
    try:
        return sum(1 for _ in filepath.open(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def mine_conventions(
    files: list[Path],
    language: str,
    repo_root: Path,
) -> dict[str, Any]:
    """Mine deterministic conventions from a set of source files.

    Returns a convention report with:
      - file_classifications: {role: [file_paths]}
      - naming_conventions: {role: frequency}
      - relationship_motifs: matched patterns with counts
      - directory_structure: common path patterns
      - tag_clusters: inferred semantic tag groups
    """

    file_classifications: dict[str, list[str]] = defaultdict(list)
    naming_counts: Counter[str] = Counter()
    motif_hits: list[dict[str, Any]] = []
    motif_counts: Counter[str] = Counter()

    # Classify files
    for fpath in files:
        role = _classify_file(fpath, language)
        if role:
            try:
                rel = fpath.relative_to(repo_root).as_posix()
            except ValueError:
                rel = fpath.as_posix()
            file_classifications[role].append(rel)
            naming_counts[role] += 1

    # Scan content for relationship motifs
    motifs = _RELATIONSHIP_MOTIFS.get(language, [])
    for fpath in files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for motif in motifs:
            matches = re.findall(motif["pattern"], content)
            if matches:
                try:
                    rel = fpath.relative_to(repo_root).as_posix()
                except ValueError:
                    rel = fpath.as_posix()

                motif_key = motif["reason"]
                motif_counts[motif_key] += len(matches)
                motif_hits.append(
                    {
                        "file": rel,
                        "motif": motif_key,
                        "edge": motif["edge"],
                        "source_tag": motif["source_tag"],
                        "count": len(matches),
                    }
                )

    # Directory structure analysis
    dir_patterns: Counter[str] = Counter()
    for fpath in files:
        try:
            rel = fpath.relative_to(repo_root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) >= 2:
            dir_patterns[parts[0]] += 1
        if len(parts) >= 3:
            dir_patterns[f"{parts[0]}/{parts[1]}"] += 1

    # Tag clusters from proximity
    tag_clusters: dict[str, list[str]] = defaultdict(list)
    for fpath in files:
        try:
            rel = fpath.relative_to(repo_root)
        except ValueError:
            continue
        dir_name = rel.parent.name.lower()
        role = _classify_file(fpath, language)
        if role:
            tag_clusters[role].append(dir_name)

    return {
        "file_classifications": dict(file_classifications),
        "naming_conventions": dict(naming_counts),
        "relationship_motifs": motif_hits,
        "motif_counts": dict(motif_counts),
        "directory_structure": dict(dir_patterns.most_common(20)),
        "tag_clusters": dict(tag_clusters),
        "total_files_scanned": len(files),
        "language": language,
    }


def aggregate_conventions(
    repo_conventions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate conventions across multiple repositories.

    Returns cross-repo signals that can be compiled into rules.
    """

    total_naming: Counter[str] = Counter()
    total_motif_counts: Counter[str] = Counter()
    languages_seen: set[str] = set()

    for conv in repo_conventions:
        for role, count in conv.get("naming_conventions", {}).items():
            total_naming[role] += count
        for motif, count in conv.get("motif_counts", {}).items():
            total_motif_counts[motif] += count
        lang = conv.get("language")
        if lang:
            languages_seen.add(lang)

    # Build cross-repo signal summary
    signals: list[dict[str, Any]] = []

    # Naming convention signals
    for role, count in total_naming.most_common():
        if count >= 3:  # threshold: at least 3 files across repos
            signals.append(
                {
                    "type": "naming_convention",
                    "role": role,
                    "total_matches": count,
                    "languages": sorted(languages_seen),
                }
            )

    # Motif signals
    for motif, count in total_motif_counts.most_common():
        if count >= 2:  # threshold: at least 2 matches across repos
            signals.append(
                {
                    "type": "relationship_motif",
                    "motif": motif,
                    "total_matches": count,
                }
            )

    return {
        "signals": signals,
        "total_naming": dict(total_naming),
        "total_motif_counts": dict(total_motif_counts),
        "languages": sorted(languages_seen),
        "repo_count": len(repo_conventions),
    }
