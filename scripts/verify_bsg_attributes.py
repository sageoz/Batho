#!/usr/bin/env python3
"""Verify BSG attribute population in export output.

This script analyzes the exported JSON to identify which attributes
are null/empty across different entity types.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path


def analyze_bsg_attributes(export_path: Path) -> dict:
    """Analyze BSG attribute population in export file."""
    with open(export_path) as f:
        data = json.load(f)
    
    # Track attribute statistics by entity type
    # Structure: {entity_type: {attribute_name: {total: 0, null: 0, empty: 0, populated: 0}}}
    attribute_stats = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    
    # Track all possible attributes
    all_attributes = set()
    
    total_entities = 0
    
    for file_data in data["files"]:
        for entity in file_data["entities"]:
            total_entities += 1
            entity_type = entity.get("type", "UNKNOWN")
            
            for attr_name, attr_value in entity.items():
                all_attributes.add(attr_name)
                attribute_stats[entity_type][attr_name]["total"] += 1
                
                if attr_value is None:
                    attribute_stats[entity_type][attr_name]["null"] += 1
                elif attr_value == "" or attr_value == []:
                    attribute_stats[entity_type][attr_name]["empty"] += 1
                else:
                    attribute_stats[entity_type][attr_name]["populated"] += 1
    
    # Calculate percentages
    results = {
        "total_entities": total_entities,
        "total_files": len(data["files"]),
        "entity_types": sorted(attribute_stats.keys()),
        "all_attributes": sorted(all_attributes),
        "by_entity_type": {},
        "summary": {
            "most_common_null_attrs": [],
            "entity_types_with_issues": []
        }
    }
    
    # Process each entity type
    for entity_type in sorted(attribute_stats.keys()):
        type_data = {}
        attrs_with_issues = []
        
        for attr_name in sorted(attribute_stats[entity_type].keys()):
            stats = attribute_stats[entity_type][attr_name]
            total = stats["total"]
            null = stats["null"]
            empty = stats["empty"]
            populated = stats["populated"]
            
            null_pct = (null / total * 100) if total > 0 else 0
            empty_pct = (empty / total * 100) if total > 0 else 0
            populated_pct = (populated / total * 100) if total > 0 else 0
            
            type_data[attr_name] = {
                "total": total,
                "null": null,
                "empty": empty,
                "populated": populated,
                "null_pct": round(null_pct, 1),
                "empty_pct": round(empty_pct, 1),
                "populated_pct": round(populated_pct, 1)
            }
            
            # Track attributes with high null/empty rates
            if null_pct > 50 or empty_pct > 50:
                attrs_with_issues.append(attr_name)
        
        results["by_entity_type"][entity_type] = {
            "attributes": type_data,
            "issues": attrs_with_issues
        }
        
        if attrs_with_issues:
            results["summary"]["entity_types_with_issues"].append(entity_type)
    
    # Find most common null attributes across all types
    null_attr_counts = defaultdict(int)
    for entity_type, type_data in attribute_stats.items():
        for attr_name, stats in type_data.items():
            if stats["null"] > 0:
                null_attr_counts[attr_name] += stats["null"]
    
    results["summary"]["most_common_null_attrs"] = [
        (attr, count) for attr, count in sorted(null_attr_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    
    return results


def print_results(results: dict) -> None:
    """Print analysis results in a readable format."""
    print("=" * 80)
    print("BSG Attribute Population Analysis")
    print("=" * 80)
    print(f"Total entities: {results['total_entities']}")
    print(f"Total files: {results['total_files']}")
    print(f"Entity types: {len(results['entity_types'])}")
    print(f"Total attributes: {len(results['all_attributes'])}")
    print()
    
    print("Most Common Null Attributes (across all entity types):")
    print("-" * 80)
    for attr, count in results["summary"]["most_common_null_attrs"][:15]:
        print(f"  {attr:30s}: {count:5d} null")
    print()
    
    print("Entity Types with Attribute Issues:")
    print("-" * 80)
    for entity_type in results["summary"]["entity_types_with_issues"]:
        issues = results["by_entity_type"][entity_type]["issues"]
        print(f"  {entity_type:25s}: {', '.join(issues[:5])}")
        if len(issues) > 5:
            print(f"  {'':25s}  ... and {len(issues) - 5} more")
    print()
    
    print("Detailed Breakdown by Entity Type:")
    print("=" * 80)
    
    for entity_type in sorted(results["by_entity_type"].keys()):
        type_data = results["by_entity_type"][entity_type]
        print(f"\n{entity_type}")
        print("-" * 80)
        
        # Sort attributes by null percentage (highest first)
        attrs_sorted = sorted(
            type_data["attributes"].items(),
            key=lambda x: x[1]["null_pct"] + x[1]["empty_pct"],
            reverse=True
        )
        
        for attr_name, stats in attrs_sorted:
            total = stats["total"]
            null = stats["null"]
            empty = stats["empty"]
            populated = stats["populated"]
            null_pct = stats["null_pct"]
            empty_pct = stats["empty_pct"]
            populated_pct = stats["populated_pct"]
            
            status = "✓" if populated_pct == 100 else "⚠" if populated_pct > 50 else "✗"
            
            print(f"  {status} {attr_name:30s}: {populated:5d}/{total:5d} ({populated_pct:5.1f}%)  [null:{null}({null_pct:.1f}%) empty:{empty}({empty_pct:.1f}%)]")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze BSG attribute population")
    parser.add_argument(
        "export_file",
        type=Path,
        default=Path("batho_export.json"),
        nargs="?",
        help="Export file to analyze (default: batho_export.json)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    
    args = parser.parse_args()
    
    if not args.export_file.exists():
        print(f"Error: Export file not found: {args.export_file}", file=sys.stderr)
        sys.exit(1)
    
    results = analyze_bsg_attributes(args.export_file)
    
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_results(results)
