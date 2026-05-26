#!/usr/bin/env python3
"""Verify that artifact database contains raw content and syntax glues.

This script checks the BSG data stored in the artifact database to verify:
1. Whether entities have non-null raw_content
2. Whether syntax glue entities are present
3. Overall storage view completeness
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from batho.storage.engine import get_database


def verify_storage_blobs(repo_root: Path | str = ".") -> dict:
    """Verify storage blobs in the artifact database."""
    root = Path(repo_root).resolve()
    db = get_database(root)

    # Get latest run
    run_uuid = db.get_latest_run_id()
    if not run_uuid:
        return {"error": "No completed runs found in database"}

    run_internal_id = db.get_run_internal_id(run_uuid)
    if not run_internal_id:
        return {"error": f"Could not resolve run ID for {run_uuid}"}

    # Get file artifacts
    artifacts = db.get_file_artifacts(run_internal_id, include_storage=True)
    if not artifacts:
        return {"error": "No file artifacts found in database"}

    # Statistics
    total_entities = 0
    entities_with_raw_content = 0
    entities_with_null_raw_content = 0
    syntax_glue_entities = 0
    files_with_glues = 0
    files_checked = 0

    results = {
        "run_uuid": run_uuid,
        "total_files": len(artifacts),
        "files_checked": 0,
        "total_entities": 0,
        "entities_with_raw_content": 0,
        "entities_with_null_raw_content": 0,
        "syntax_glue_entities": 0,
        "files_with_glues": 0,
        "raw_content_coverage_pct": 0.0,
        "files_by_status": {},
    }

    for artifact in artifacts:
        file_path = artifact["file_path"]
        bsg_data = artifact.get("bsg")
        
        if not bsg_data:
            results["files_by_status"][file_path] = "no_bsg_data"
            continue

        # Handle both list and dict formats
        if isinstance(bsg_data, dict):
            entities = bsg_data.get("entities", [])
        elif isinstance(bsg_data, list):
            entities = bsg_data
        else:
            results["files_by_status"][file_path] = "invalid_bsg_format"
            continue

        if not entities:
            results["files_by_status"][file_path] = "no_entities"
            continue

        files_checked += 1
        file_has_glues = False

        for entity in entities:
            total_entities += 1
            
            # Check raw_content
            raw_content = entity.get("raw_content")
            if raw_content is not None and raw_content != "":
                entities_with_raw_content += 1
            else:
                entities_with_null_raw_content += 1
            
            # Check for syntax glue
            entity_type = entity.get("type")
            if entity_type == "SYNTAX_GLUE":
                syntax_glue_entities += 1
                file_has_glues = True

        if file_has_glues:
            files_with_glues += 1
            results["files_by_status"][file_path] = "has_glues"
        else:
            results["files_by_status"][file_path] = "no_glues"

    # Calculate coverage
    results["files_checked"] = files_checked
    results["total_entities"] = total_entities
    results["entities_with_raw_content"] = entities_with_raw_content
    results["entities_with_null_raw_content"] = entities_with_null_raw_content
    results["syntax_glue_entities"] = syntax_glue_entities
    results["files_with_glues"] = files_with_glues
    
    if total_entities > 0:
        results["raw_content_coverage_pct"] = (entities_with_raw_content / total_entities) * 100

    return results


def print_results(results: dict) -> None:
    """Print verification results in a readable format."""
    if "error" in results:
        print(f"❌ Error: {results['error']}", file=sys.stderr)
        return

    print("=" * 60)
    print("Storage Blob Verification Results")
    print("=" * 60)
    print(f"Run UUID: {results['run_uuid']}")
    print(f"Total files in database: {results['total_files']}")
    print(f"Files checked: {results['files_checked']}")
    print()
    print("Entity Statistics:")
    print(f"  Total entities: {results['total_entities']}")
    print(f"  Entities with raw_content: {results['entities_with_raw_content']}")
    print(f"  Entities with null raw_content: {results['entities_with_null_raw_content']}")
    print(f"  Raw content coverage: {results['raw_content_coverage_pct']:.1f}%")
    print()
    print("Syntax Glue Statistics:")
    print(f"  Syntax glue entities: {results['syntax_glue_entities']}")
    print(f"  Files with glues: {results['files_with_glues']}")
    print()
    
    # Summary
    print("Summary:")
    if results['raw_content_coverage_pct'] == 0:
        print("  ❌ No entities have raw_content - storage view is incomplete")
    elif results['raw_content_coverage_pct'] < 100:
        print(f"  ⚠️  Partial raw_content coverage ({results['raw_content_coverage_pct']:.1f}%)")
    else:
        print("  ✅ All entities have raw_content")
    
    if results['syntax_glue_entities'] == 0:
        print("  ❌ No syntax glue entities found")
    else:
        print(f"  ✅ Found {results['syntax_glue_entities']} syntax glue entities")
    
    print()
    print("File Status Breakdown:")
    status_counts = {}
    for file_path, status in results["files_by_status"].items():
        status_counts[status] = status_counts.get(status, 0) + 1
    
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Verify storage blobs in artifact database")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    
    args = parser.parse_args()
    
    results = verify_storage_blobs(args.root)
    
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_results(results)
