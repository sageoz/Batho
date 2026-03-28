#!/usr/bin/env python3
"""
Flask repository metadata and statistics for testing.

This script provides metadata about the Flask repository used in tests,
including file counts, language distribution, and structural analysis.
"""

from pathlib import Path
from typing import Dict, List, Any
import json


def analyze_repository(repo_path: Path) -> Dict[str, Any]:
    """Analyze repository structure and generate statistics."""
    
    stats = {
        "name": "Flask",
        "version": "2.3.3",
        "total_files": 0,
        "total_lines": 0,
        "languages": {},
        "directories": {},
        "file_extensions": {},
        "python_modules": [],
        "test_files": [],
        "config_files": [],
        "documentation_files": [],
    }
    
    # Walk through all files
    for file_path in repo_path.rglob("*"):
        if file_path.is_file():
            stats["total_files"] += 1
            
            # File extension
            ext = file_path.suffix.lower()
            if ext:
                stats["file_extensions"][ext] = stats["file_extensions"].get(ext, 0) + 1
            
            # Language detection
            if ext == ".py":
                stats["languages"]["python"] = stats["languages"].get("python", 0) + 1
                if "test" in file_path.name.lower():
                    stats["test_files"].append(str(file_path.relative_to(repo_path)))
                else:
                    stats["python_modules"].append(str(file_path.relative_to(repo_path)))
            elif ext in [".js", ".jsx", ".ts", ".tsx"]:
                stats["languages"]["javascript"] = stats["languages"].get("javascript", 0) + 1
            elif ext in [".html", ".htm"]:
                stats["languages"]["html"] = stats["languages"].get("html", 0) + 1
            elif ext in [".css", ".scss", ".sass"]:
                stats["languages"]["css"] = stats["languages"].get("css", 0) + 1
            elif ext in [".md", ".rst", ".txt"]:
                stats["languages"]["documentation"] = stats["languages"].get("documentation", 0) + 1
                stats["documentation_files"].append(str(file_path.relative_to(repo_path)))
            elif ext in [".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"]:
                stats["config_files"].append(str(file_path.relative_to(repo_path)))
            
            # Count lines (for text files)
            try:
                if file_path.suffix in [".py", ".js", ".ts", ".html", ".css", ".md", ".rst", ".txt"]:
                    lines = len(file_path.read_text(encoding="utf-8", errors="ignore").splitlines())
                    stats["total_lines"] += lines
            except Exception:
                pass
        
        elif file_path.is_dir():
            # Directory analysis
            dir_name = str(file_path.relative_to(repo_path))
            if not any(part.startswith(".") for part in dir_name.split("/")):
                stats["directories"][dir_name] = len(list(file_path.iterdir()))
    
    return stats


def main():
    """Generate and save repository metadata."""
    repo_path = Path(__file__).parent
    stats = analyze_repository(repo_path)
    
    # Save metadata as JSON
    metadata_file = repo_path / "repository_metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, sort_keys=True)
    
    # Print summary
    print(f"Repository: {stats['name']} v{stats['version']}")
    print(f"Total files: {stats['total_files']}")
    print(f"Total lines of code: {stats['total_lines']}")
    print(f"Languages: {', '.join(stats['languages'].keys())}")
    print(f"Python modules: {len(stats['python_modules'])}")
    print(f"Test files: {len(stats['test_files'])}")
    print(f"Config files: {len(stats['config_files'])}")
    print(f"Documentation files: {len(stats['documentation_files'])}")
    
    return stats


if __name__ == "__main__":
    main()
