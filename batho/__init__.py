"""
Batho Core - Code analysis and indexing library.

This package provides the core functionality for analyzing code repositories,
building dependency graphs, and generating contextual information for LLMs.
"""

__version__ = "1.0.0"

# Import and re-export public APIs from submodules
from batho.context.codegraph import CodeGraphIndexer, InMemoryGraph
from batho.context.query import QueryService
from batho.context.bsg_map import BSGMap
from batho.context.incremental import get_changed_file_status_since
from batho.time_machine import (
    create_snapshot,
    diff_snapshots,
    FileChange,
    FileChangeSummary,
    FileChangeTracker,
    FileChangeType,
    incremental_patch,
    list_snapshots,
    load_snapshot,
)
from batho.webhook import (
    WebhookConfig,
    WebhookProcessor,
    WebhookServer,
    parse_webhook_event,
)
from batho.config import get_config_cached, reload_config
from batho.utils.logging import get_logger

__all__ = [
    # Core indexing
    "CodeGraphIndexer",
    "InMemoryGraph",
    # Query service
    "QueryService",
    # BSG rendering
    "BSGMap",
    # Incremental
    "get_changed_file_status_since",
    # Time machine
    "create_snapshot",
    "diff_snapshots",
    "FileChange",
    "FileChangeSummary",
    "FileChangeTracker",
    "FileChangeType",
    "incremental_patch",
    "list_snapshots",
    "load_snapshot",
    # Webhooks
    "WebhookConfig",
    "WebhookProcessor",
    "WebhookServer",
    "parse_webhook_event",
    # Config
    "get_config_cached",
    "reload_config",
    # Logging
    "get_logger",
]
