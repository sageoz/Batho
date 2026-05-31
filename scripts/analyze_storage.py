#!/usr/bin/env python3
"""
Detailed storage analysis script for Batho .batho SQLite databases.

Analyzes storage usage by table, provides compression statistics,
and offers optimization recommendations for artifact_batho-v1-1-0.batho.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any
from datetime import datetime


def format_bytes(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def get_table_storage_estimate(conn: sqlite3.Connection, table_name: str) -> dict[str, Any]:
    """Estimate storage usage for a specific table using sampling."""
    cursor = conn.cursor()
    
    # Get row count
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    row_count = cursor.fetchone()[0]
    
    if row_count == 0:
        return {"row_count": 0, "estimated_size_bytes": 0}
    
    # Get column info
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    
    # Sample rows to estimate size
    try:
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 1000")
        sample_rows = cursor.fetchall()
        if sample_rows:
            # Calculate actual byte size using serialization
            total_sample_size = 0
            for row in sample_rows:
                # Estimate row size by summing column sizes
                row_size = 0
                for i, col_val in enumerate(row):
                    if col_val is None:
                        row_size += 1  # NULL marker
                    elif isinstance(col_val, (bytes, bytearray)):
                        row_size += len(col_val)
                    elif isinstance(col_val, str):
                        row_size += len(col_val.encode('utf-8'))
                    elif isinstance(col_val, (int, float)):
                        row_size += 8  # Approximate for numbers
                    else:
                        row_size += len(str(col_val))
                total_sample_size += row_size
            avg_row_size = total_sample_size / len(sample_rows)
        else:
            avg_row_size = 0
    except sqlite3.OperationalError:
        avg_row_size = 0
    
    estimated_size = row_count * avg_row_size if avg_row_size else 0
    
    return {
        "row_count": row_count,
        "column_count": len(columns),
        "avg_row_size_bytes": avg_row_size,
        "estimated_size_bytes": estimated_size,
    }


def get_index_storage_estimate(conn: sqlite3.Connection, table_name: str) -> dict[str, Any]:
    """Estimate storage for indexes on a table."""
    cursor = conn.cursor()
    
    # Get list of indexes for this table
    cursor.execute(f"PRAGMA index_list({table_name})")
    indexes = cursor.fetchall()
    
    index_info = []
    total_estimated_size = 0
    
    for idx in indexes:
        idx_name = idx[1]  # index name
        idx_unique = idx[2]  # is unique
        
        # Get index columns
        cursor.execute(f"PRAGMA index_info({idx_name})")
        idx_columns = cursor.fetchall()
        
        # Get row count from the table
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]
        
        # Estimate index size: roughly 2x the indexed columns per row
        # This is a rough approximation
        if row_count > 0 and idx_columns:
            # Estimate key size based on column types
            avg_key_size = 50  # Rough estimate per index entry
            estimated_size = row_count * avg_key_size
            total_estimated_size += estimated_size
        
        index_info.append({
            "name": idx_name,
            "unique": bool(idx_unique),
            "columns": len(idx_columns),
        })
    
    return {
        "index_count": len(indexes),
        "indexes": index_info,
        "estimated_size_bytes": total_estimated_size,
    }


def get_comprehensive_storage_breakdown(conn: sqlite3.Connection) -> dict[str, Any]:
    """Get comprehensive storage breakdown for all tables and indexes."""
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    
    breakdown = {}
    total_table_size = 0
    total_index_size = 0
    
    for table in tables:
        table_info = get_table_storage_estimate(conn, table)
        index_info = get_index_storage_estimate(conn, table)
        
        breakdown[table] = {
            "table": table_info,
            "indexes": index_info,
            "total_estimated_bytes": table_info["estimated_size_bytes"] + index_info["estimated_size_bytes"],
        }
        
        total_table_size += table_info["estimated_size_bytes"]
        total_index_size += index_info["estimated_size_bytes"]
    
    # Get database page info for actual total
    cursor.execute("PRAGMA page_size")
    page_size = cursor.fetchone()[0]
    cursor.execute("PRAGMA page_count")
    page_count = cursor.fetchone()[0]
    actual_total = page_size * page_count
    
    # Calculate overhead
    estimated_total = total_table_size + total_index_size
    overhead = actual_total - estimated_total
    
    return {
        "tables": breakdown,
        "total_table_bytes": total_table_size,
        "total_index_bytes": total_index_size,
        "estimated_total_bytes": estimated_total,
        "actual_total_bytes": actual_total,
        "overhead_bytes": overhead,
        "overhead_percentage": (overhead / actual_total * 100) if actual_total > 0 else 0,
    }


def get_database_page_info(conn: sqlite3.Connection) -> dict[str, Any]:
    """Get detailed page information from SQLite."""
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA page_size")
    page_size = cursor.fetchone()[0]
    
    cursor.execute("PRAGMA page_count")
    page_count = cursor.fetchone()[0]
    
    total_size = page_size * page_count
    
    cursor.execute("PRAGMA freelist_count")
    freelist_count = cursor.fetchone()[0]
    
    free_space = freelist_count * page_size
    
    cursor.execute("PRAGMA auto_vacuum")
    auto_vacuum = cursor.fetchone()[0]
    
    return {
        "page_size": page_size,
        "page_count": page_count,
        "total_size_bytes": total_size,
        "free_space_bytes": free_space,
        "auto_vacuum": auto_vacuum,
        "used_space_bytes": total_size - free_space,
    }


def analyze_blob_compression(conn: sqlite3.Connection, table: str, blob_columns: list[str]) -> dict[str, Any]:
    """Analyze compression statistics for BLOB columns."""
    cursor = conn.cursor()
    stats = {}
    
    for col in blob_columns:
        try:
            cursor.execute(f"SELECT LENGTH({col}) FROM {table} WHERE {col} IS NOT NULL")
            sizes = cursor.fetchall()
            
            if sizes:
                sizes = [s[0] for s in sizes]
                stats[col] = {
                    "count": len(sizes),
                    "total_bytes": sum(sizes),
                    "avg_bytes": sum(sizes) / len(sizes),
                    "min_bytes": min(sizes),
                    "max_bytes": max(sizes),
                }
        except sqlite3.OperationalError:
            stats[col] = {"error": "Column not accessible"}
    
    return stats


def analyze_string_dict(conn: sqlite3.Connection) -> dict[str, Any]:
    """Analyze string dictionary table for deduplication efficiency."""
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM string_dict")
    unique_strings = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(LENGTH(val)) FROM string_dict")
    total_chars = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT AVG(LENGTH(val)) FROM string_dict")
    avg_length = cursor.fetchone()[0] or 0
    
    # Sample some strings to understand distribution
    cursor.execute("SELECT val, LENGTH(val) FROM string_dict ORDER BY LENGTH(val) DESC LIMIT 10")
    longest_strings = cursor.fetchall()
    
    return {
        "unique_strings": unique_strings,
        "total_characters": total_chars,
        "avg_string_length": avg_length,
        "estimated_storage_bytes": total_chars * 2,  # UTF-16 approximation
        "longest_strings": [(s[0][:100], s[1]) for s in longest_strings],  # Truncate for display
    }


def analyze_index_runs(conn: sqlite3.Connection) -> dict[str, Any]:
    """Analyze index runs table."""
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM index_runs")
    total_runs = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM index_runs WHERE status = 'completed'")
    completed_runs = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM index_runs WHERE status = 'running'")
    running_runs = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM index_runs WHERE status = 'failed'")
    failed_runs = cursor.fetchone()[0]
    
    # Get latest run info
    cursor.execute("SELECT run_uuid, started_at, completed_at, entity_count, rel_count, file_count FROM index_runs ORDER BY started_at DESC LIMIT 1")
    latest_run = cursor.fetchone()
    
    return {
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "running_runs": running_runs,
        "failed_runs": failed_runs,
        "latest_run": {
            "uuid": latest_run[0] if latest_run else None,
            "started_at": latest_run[1] if latest_run else None,
            "completed_at": latest_run[2] if latest_run else None,
            "entity_count": latest_run[3] if latest_run else 0,
            "rel_count": latest_run[4] if latest_run else 0,
            "file_count": latest_run[5] if latest_run else 0,
        } if latest_run else None,
    }


def analyze_file_artifacts(conn: sqlite3.Connection) -> dict[str, Any]:
    """Analyze file_artifacts table in detail."""
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM file_artifacts")
    total_artifacts = cursor.fetchone()[0]
    
    # Analyze BLOB columns
    blob_stats = analyze_blob_compression(
        conn, 
        "file_artifacts", 
        ["bsg_agent_view", "bsg_storage_view", "bsg_rel_view"]
    )
    
    # Get unique files
    cursor.execute("SELECT COUNT(DISTINCT file_id) FROM file_artifacts")
    unique_files = cursor.fetchone()[0]
    
    return {
        "total_artifacts": total_artifacts,
        "unique_files": unique_files,
        "blob_statistics": blob_stats,
    }


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None


def analyze_query_tables(conn: sqlite3.Connection) -> dict[str, Any]:
    """Analyze query_entities and query_relationships tables."""
    cursor = conn.cursor()
    
    # Check if tables exist
    has_entities = table_exists(conn, "query_entities")
    has_relationships = table_exists(conn, "query_relationships")
    has_dangling = table_exists(conn, "dangling_references")
    
    # Entities
    entity_count = 0
    unique_types = 0
    type_distribution = []
    entity_table_info = {"estimated_size_bytes": 0}
    entity_index_info = {"estimated_size_bytes": 0}
    
    if has_entities:
        cursor.execute("SELECT COUNT(*) FROM query_entities")
        entity_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT entity_type) FROM query_entities")
        unique_types = cursor.fetchone()[0]
        
        cursor.execute("SELECT entity_type, COUNT(*) FROM query_entities GROUP BY entity_type ORDER BY COUNT(*) DESC")
        type_distribution = cursor.fetchall()
        
        entity_table_info = get_table_storage_estimate(conn, "query_entities")
        entity_index_info = get_index_storage_estimate(conn, "query_entities")
    
    # Relationships
    rel_count = 0
    unique_rel_types = 0
    rel_distribution = []
    rel_table_info = {"estimated_size_bytes": 0}
    rel_index_info = {"estimated_size_bytes": 0}
    
    if has_relationships:
        cursor.execute("SELECT COUNT(*) FROM query_relationships")
        rel_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT relation_type) FROM query_relationships")
        unique_rel_types = cursor.fetchone()[0]
        
        cursor.execute("SELECT relation_type, COUNT(*) FROM query_relationships GROUP BY relation_type ORDER BY COUNT(*) DESC")
        rel_distribution = cursor.fetchall()
        
        rel_table_info = get_table_storage_estimate(conn, "query_relationships")
        rel_index_info = get_index_storage_estimate(conn, "query_relationships")
    
    # Dangling references
    dangling_count = 0
    dangling_table_info = {"estimated_size_bytes": 0}
    dangling_index_info = {"estimated_size_bytes": 0}
    
    if has_dangling:
        cursor.execute("SELECT COUNT(*) FROM dangling_references")
        dangling_count = cursor.fetchone()[0]
        
        dangling_table_info = get_table_storage_estimate(conn, "dangling_references")
        dangling_index_info = get_index_storage_estimate(conn, "dangling_references")
    
    return {
        "entities": {
            "total_count": entity_count,
            "unique_types": unique_types,
            "type_distribution": type_distribution[:20],  # Top 20
            "storage": {
                "table_bytes": entity_table_info["estimated_size_bytes"],
                "index_bytes": entity_index_info["estimated_size_bytes"],
                "total_bytes": entity_table_info["estimated_size_bytes"] + entity_index_info["estimated_size_bytes"],
            }
        },
        "relationships": {
            "total_count": rel_count,
            "unique_types": unique_rel_types,
            "type_distribution": rel_distribution[:20],  # Top 20
            "storage": {
                "table_bytes": rel_table_info["estimated_size_bytes"],
                "index_bytes": rel_index_info["estimated_size_bytes"],
                "total_bytes": rel_table_info["estimated_size_bytes"] + rel_index_info["estimated_size_bytes"],
            }
        },
        "dangling_references": {
            "count": dangling_count,
            "storage": {
                "table_bytes": dangling_table_info["estimated_size_bytes"],
                "index_bytes": dangling_index_info["estimated_size_bytes"],
                "total_bytes": dangling_table_info["estimated_size_bytes"] + dangling_index_info["estimated_size_bytes"],
            }
        },
    }


def generate_optimization_recommendations(analysis: dict[str, Any]) -> list[str]:
    """Generate optimization recommendations based on analysis."""
    recommendations = []
    
    page_info = analysis.get("page_info", {})
    file_artifacts = analysis.get("file_artifacts", {})
    query_tables = analysis.get("query_tables", {})
    string_dict = analysis.get("string_dict", {})
    
    # Check free space
    free_space_pct = (page_info.get("free_space_bytes", 0) / page_info.get("total_size_bytes", 1)) * 100
    if free_space_pct > 10:
        recommendations.append(
            f"⚠️  {free_space_pct:.1f}% free space detected. "
            f"Run 'PRAGMA incremental_vacuum;' or 'VACUUM;' to reclaim space."
        )
    
    # Check dangling references
    dangling = query_tables.get("dangling_references", {}).get("count", 0)
    if dangling > 0:
        recommendations.append(
            f"⚠️  {dangling} dangling references found. "
            f"Consider running symbol resolution to clean up unresolved edges."
        )
    
    # Check compression efficiency
    blob_stats = file_artifacts.get("blob_statistics", {})
    for col, stats in blob_stats.items():
        if "error" not in stats and stats.get("count", 0) > 0:
            avg_size = stats.get("avg_bytes", 0)
            if avg_size > 100000:  # > 100KB average
                recommendations.append(
                    f"⚠️  {col} has large average size ({format_bytes(avg_size)}). "
                    f"Consider reviewing compression level or data structure."
                )
    
    # Check string dictionary efficiency
    if string_dict.get("unique_strings", 0) > 10000:
        avg_len = string_dict.get("avg_string_length", 0)
        if avg_len > 100:
            recommendations.append(
                f"⚠️  String dictionary has long strings (avg {avg_len:.1f} chars). "
                f"Consider if path normalization could reduce storage."
            )
    
    # Check WAL mode
    if page_info.get("auto_vacuum") == 0:
        recommendations.append(
            "ℹ️  Auto-vacuum is disabled. Consider enabling with 'PRAGMA auto_vacuum = INCREMENTAL' "
            "for automatic space reclamation."
        )
    
    if not recommendations:
        recommendations.append("✅ No major optimization issues detected.")
    
    return recommendations


def print_analysis_report(db_path: Path, analysis: dict[str, Any]):
    """Print a comprehensive analysis report."""
    print("=" * 80)
    print(f"STORAGE ANALYSIS REPORT: {db_path.name}")
    print("=" * 80)
    print(f"Generated: {datetime.now().isoformat()}")
    print()
    
    # Database Overview
    print("📊 DATABASE OVERVIEW")
    print("-" * 80)
    page_info = analysis["page_info"]
    print(f"Total Size:          {format_bytes(page_info['total_size_bytes'])}")
    print(f"Used Space:          {format_bytes(page_info['used_space_bytes'])}")
    print(f"Free Space:          {format_bytes(page_info['free_space_bytes'])} ({page_info['free_space_bytes']/page_info['total_size_bytes']*100:.1f}%)")
    print(f"Page Size:           {page_info['page_size']} bytes")
    print(f"Page Count:          {page_info['page_count']:,}")
    print(f"Auto-Vacuum:         {page_info['auto_vacuum']}")
    print()
    
    # Storage Breakdown
    print("📦 STORAGE BREAKDOWN BY TABLE")
    print("-" * 80)
    breakdown = analysis["storage_breakdown"]
    
    # Sort by size
    sorted_tables = sorted(
        breakdown["tables"].items(), 
        key=lambda x: x[1]["total_estimated_bytes"], 
        reverse=True
    )
    
    for table_name, info in sorted_tables:
        table_size = info["table"]["estimated_size_bytes"]
        index_size = info["indexes"]["estimated_size_bytes"]
        total_size = info["total_estimated_bytes"]
        row_count = info["table"]["row_count"]
        index_count = info["indexes"]["index_count"]
        
        percentage = (total_size / breakdown["actual_total_bytes"] * 100) if breakdown["actual_total_bytes"] > 0 else 0
        
        print(f"{table_name}:")
        print(f"  Rows:              {row_count:,}")
        print(f"  Table Data:        {format_bytes(table_size)} ({table_size/breakdown['actual_total_bytes']*100:.1f}% of total)")
        print(f"  Indexes ({index_count}): {format_bytes(index_size)} ({index_size/breakdown['actual_total_bytes']*100:.1f}% of total)")
        print(f"  Total:             {format_bytes(total_size)} ({percentage:.1f}% of database)")
        print()
    
    # Summary
    print("📊 STORAGE SUMMARY")
    print("-" * 80)
    print(f"Total Table Data:   {format_bytes(breakdown['total_table_bytes'])} ({breakdown['total_table_bytes']/breakdown['actual_total_bytes']*100:.1f}%)")
    print(f"Total Index Data:    {format_bytes(breakdown['total_index_bytes'])} ({breakdown['total_index_bytes']/breakdown['actual_total_bytes']*100:.1f}%)")
    print(f"Estimated Total:     {format_bytes(breakdown['estimated_total_bytes'])}")
    print(f"Actual Total:        {format_bytes(breakdown['actual_total_bytes'])}")
    print(f"Overhead:            {format_bytes(breakdown['overhead_bytes'])} ({breakdown['overhead_percentage']:.1f}%)")
    print(f"  (Includes: page headers, free space, WAL, schema, etc.)")
    print()
    
    # Index Runs
    print("📈 INDEX RUNS")
    print("-" * 80)
    runs = analysis["index_runs"]
    print(f"Total Runs:          {runs['total_runs']}")
    print(f"Completed:           {runs['completed_runs']}")
    print(f"Running:             {runs['running_runs']}")
    print(f"Failed:              {runs['failed_runs']}")
    if runs["latest_run"]:
        print(f"Latest Run UUID:     {runs['latest_run']['uuid']}")
        print(f"  Entities:          {runs['latest_run']['entity_count']:,}")
        print(f"  Relationships:     {runs['latest_run']['rel_count']:,}")
        print(f"  Files:             {runs['latest_run']['file_count']:,}")
    print()
    
    # File Artifacts
    print("📦 FILE ARTIFACTS (Compressed Graph Data)")
    print("-" * 80)
    artifacts = analysis["file_artifacts"]
    print(f"Total Artifacts:     {artifacts['total_artifacts']:,}")
    print(f"Unique Files:        {artifacts['unique_files']:,}")
    print()
    print("BLOB Column Statistics:")
    for col, stats in artifacts["blob_statistics"].items():
        if "error" not in stats:
            print(f"  {col}:")
            print(f"    Count:           {stats['count']:,}")
            print(f"    Total Size:      {format_bytes(stats['total_bytes'])}")
            print(f"    Avg Size:        {format_bytes(stats['avg_bytes'])}")
            print(f"    Min Size:        {format_bytes(stats['min_bytes'])}")
            print(f"    Max Size:        {format_bytes(stats['max_bytes'])}")
    print()
    
    # String Dictionary
    print("🔤 STRING DICTIONARY (Deduplication)")
    print("-" * 80)
    str_dict = analysis["string_dict"]
    print(f"Unique Strings:      {str_dict['unique_strings']:,}")
    print(f"Total Characters:    {str_dict['total_characters']:,}")
    print(f"Avg Length:          {str_dict['avg_string_length']:.1f} chars")
    print(f"Est. Storage:        {format_bytes(str_dict['estimated_storage_bytes'])}")
    print(f"Longest Strings (sample):")
    for s, length in str_dict["longest_strings"]:
        print(f"  {length:4d} chars: {s}")
    print()
    
    # Query Tables
    print("🔍 QUERY TABLES (Search Index)")
    print("-" * 80)
    query = analysis["query_tables"]
    
    print(f"query_entities:")
    print(f"  Count:              {query['entities']['total_count']:,}")
    print(f"  Unique Types:       {query['entities']['unique_types']}")
    print(f"  Storage:")
    print(f"    Table Data:       {format_bytes(query['entities']['storage']['table_bytes'])}")
    print(f"    Indexes:          {format_bytes(query['entities']['storage']['index_bytes'])}")
    print(f"    Total:            {format_bytes(query['entities']['storage']['total_bytes'])}")
    print(f"  Top Types:")
    for etype, count in query["entities"]["type_distribution"][:10]:
        print(f"    {etype:30s}: {count:7,}")
    print()
    
    print(f"query_relationships:")
    print(f"  Count:              {query['relationships']['total_count']:,}")
    print(f"  Unique Types:      {query['relationships']['unique_types']}")
    print(f"  Storage:")
    print(f"    Table Data:       {format_bytes(query['relationships']['storage']['table_bytes'])}")
    print(f"    Indexes:          {format_bytes(query['relationships']['storage']['index_bytes'])}")
    print(f"    Total:            {format_bytes(query['relationships']['storage']['total_bytes'])}")
    print(f"  Top Types:")
    for rtype, count in query["relationships"]["type_distribution"][:10]:
        print(f"    {rtype:30s}: {count:7,}")
    print()
    
    print(f"dangling_references:")
    print(f"  Count:              {query['dangling_references']['count']:,}")
    print(f"  Storage:")
    print(f"    Table Data:       {format_bytes(query['dangling_references']['storage']['table_bytes'])}")
    print(f"    Indexes:          {format_bytes(query['dangling_references']['storage']['index_bytes'])}")
    print(f"    Total:            {format_bytes(query['dangling_references']['storage']['total_bytes'])}")
    print()
    
    # Optimization Recommendations
    print("💡 OPTIMIZATION RECOMMENDATIONS")
    print("-" * 80)
    for rec in analysis["recommendations"]:
        print(rec)
    print()
    
    print("=" * 80)


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_storage.py <path_to_batho_file>")
        print("Example: python analyze_storage.py artifact_batho-v1-1-0.batho")
        sys.exit(1)
    
    db_path = Path(sys.argv[1])
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    print(f"Analyzing: {db_path}")
    print()
    
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        
        # Collect all analysis data
        analysis = {
            "page_info": get_database_page_info(conn),
            "storage_breakdown": get_comprehensive_storage_breakdown(conn),
            "index_runs": analyze_index_runs(conn),
            "file_artifacts": analyze_file_artifacts(conn),
            "string_dict": analyze_string_dict(conn),
            "query_tables": analyze_query_tables(conn),
        }
        
        # Generate recommendations
        analysis["recommendations"] = generate_optimization_recommendations(analysis)
        
        # Print report
        print_analysis_report(db_path, analysis)
        
        conn.close()
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
