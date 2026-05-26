"""Dashboard Assets — Static file discovery and serving.

Finds dashboard assets from multiple sources (env var, dev checkout, packaged)
and serves them with appropriate cache headers.
"""

from __future__ import annotations

import os
import mimetypes
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Iterator
from importlib.resources import files as _pkg_files

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="dashboard_core.assets")

# Cache control headers for development
NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def find_dashboard_assets() -> Path | None:
    """Find dashboard assets directory.
    
    Resolution order:
    1. BATHO_DASHBOARD_DIR environment variable (explicit override)
    2. Dev checkout (../dashboard relative to this file)
    3. Packaged copy in installed batho distribution
    
    Returns:
        Path to dashboard assets directory, or None if not found
    """
    # 1. Environment variable override
    override = os.environ.get("BATHO_DASHBOARD_DIR")
    if override:
        candidate = Path(override).expanduser().resolve()
        if candidate.is_dir() and (candidate / "index.html").exists():
            LOGGER.debug("assets_from_env", path=str(candidate))
            return candidate
        else:
            LOGGER.warning("assets_env_not_found", path=str(candidate))
    
    # 2. Dev checkout path
    # __file__ -> .../batho/dashboard_core/assets.py
    here = Path(__file__).resolve()
    dev_candidate = here.parent / "web"
    if dev_candidate.is_dir() and (dev_candidate / "index.html").exists():
        LOGGER.debug("assets_from_dev", path=str(dev_candidate))
        return dev_candidate
    
    # 3. Packaged copy
    try:
        packaged = Path(str(_pkg_files("batho").joinpath("dashboard_core").joinpath("web")))
        if packaged.is_dir() and (packaged / "index.html").exists():
            LOGGER.debug("assets_from_package", path=str(packaged))
            return packaged
    except Exception as e:
        LOGGER.debug("assets_package_error", error=str(e))
    
    LOGGER.warning("assets_not_found")
    return None


def guess_mime_type(path: Path) -> str:
    """Guess MIME type from file extension.
    
    Args:
        path: File path
        
    Returns:
        MIME type string
    """
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    
    # Fallback for common types
    ext = path.suffix.lower()
    return {
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".html": "text/html",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
    }.get(ext, "application/octet-stream")


def serve_asset(
    handler: BaseHTTPRequestHandler,
    asset_path: Path,
    cache: bool = False
) -> bool:
    """Serve a single asset file.
    
    Args:
        handler: HTTP request handler
        asset_path: Path to asset file
        cache: Whether to allow caching
        
    Returns:
        True if file was served, False if not found
    """
    if not asset_path.exists() or not asset_path.is_file():
        return False
    
    try:
        content = asset_path.read_bytes()
        mime_type = guess_mime_type(asset_path)
        
        handler.send_response(200)
        handler.send_header("Content-Type", mime_type)
        handler.send_header("Content-Length", str(len(content)))
        
        if not cache:
            for key, value in NO_CACHE_HEADERS.items():
                handler.send_header(key, value)
        
        handler.end_headers()
        handler.wfile.write(content)
        return True
        
    except Exception as e:
        LOGGER.error("asset_serve_error", path=str(asset_path), error=str(e))
        return False


def iter_assets(assets_dir: Path) -> Iterator[Path]:
    """Iterate all asset files in directory.
    
    Args:
        assets_dir: Dashboard assets directory
        
    Yields:
        Path objects for each asset file
    """
    if not assets_dir.exists():
        return
    
    for path in assets_dir.rglob("*"):
        if path.is_file():
            yield path


__all__ = [
    "find_dashboard_assets",
    "guess_mime_type",
    "serve_asset",
    "iter_assets",
    "NO_CACHE_HEADERS",
]
