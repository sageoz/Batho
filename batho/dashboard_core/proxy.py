"""Dashboard Proxy — Transparent forwarding to bridge_core API.

The dashboard is a dumb proxy. It forwards ALL /api/* requests
directly to the bridge_core HTTP server without modification.

This ensures zero business logic in the dashboard layer.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any
from http.server import BaseHTTPRequestHandler

from batho.utils.logging import get_logger

LOGGER = get_logger(__name__, component="dashboard_core.proxy")


class BridgeProxy:
    """Proxy to bridge_core HTTP API.
    
    Forwards requests from dashboard to bridge server.
    
    Usage:
        proxy = BridgeProxy("http://127.0.0.1:8765")
        result = proxy.forward_get("/api/v2/search", {"q": "foo"})
    """
    
    def __init__(self, bridge_url: str = "http://127.0.0.1:8765"):
        """Initialize proxy.
        
        Args:
            bridge_url: Base URL of bridge_core HTTP server
        """
        self.bridge_url = bridge_url.rstrip("/")
    
    def _make_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """Build full URL with query parameters.
        
        Args:
            path: API path (e.g., /api/v2/search)
            params: Query parameters
            
        Returns:
            Full URL string
        """
        url = f"{self.bridge_url}{path}"
        if params:
            query_parts = []
            for k, v in params.items():
                if isinstance(v, list):
                    # Serialize list as repeated key-value pairs (e.g., k=v1&k=v2)
                    for item in v:
                        query_parts.append(f"{k}={urllib.request.quote(str(item))}")
                else:
                    query_parts.append(f"{k}={urllib.request.quote(str(v))}")
            query = "&".join(query_parts)
            url = f"{url}?{query}"
        return url
    
    def forward_get(
        self,
        path: str,
        params: dict[str, Any] | None = None
    ) -> tuple[bytes, int, dict[str, str]]:
        """Forward GET request to bridge.
        
        Args:
            path: API path
            params: Query parameters
            
        Returns:
            Tuple of (body_bytes, status_code, headers_dict)
        """
        url = self._make_url(path, params)
        
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json")
            
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read()
                headers = dict(response.headers)
                return body, response.status, headers
                
        except urllib.error.HTTPError as e:
            LOGGER.warning("proxy_http_error", url=url, status=e.code, error=str(e))
            body = e.read()
            return body, e.code, {}
            
        except urllib.error.URLError as e:
            LOGGER.error("proxy_url_error", url=url, error=str(e))
            error_response = json.dumps({
                "ok": False,
                "error": f"Bridge unavailable: {e.reason}",
                "data": {}
            }).encode()
            return error_response, 503, {"Content-Type": "application/json"}
            
        except Exception as e:
            LOGGER.error("proxy_error", url=url, error=str(e))
            error_response = json.dumps({
                "ok": False,
                "error": str(e),
                "data": {}
            }).encode()
            return error_response, 500, {"Content-Type": "application/json"}
    
    def forward_post(
        self,
        path: str,
        body: dict[str, Any]
    ) -> tuple[bytes, int, dict[str, str]]:
        """Forward POST request to bridge.
        
        Args:
            path: API path
            body: JSON body
            
        Returns:
            Tuple of (body_bytes, status_code, headers_dict)
        """
        url = self._make_url(path)
        
        try:
            body_bytes = json.dumps(body).encode()
            
            req = urllib.request.Request(
                url,
                data=body_bytes,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                response_body = response.read()
                headers = dict(response.headers)
                return response_body, response.status, headers
                
        except urllib.error.HTTPError as e:
            LOGGER.warning("proxy_http_error", url=url, status=e.code, error=str(e))
            body = e.read()
            return body, e.code, {}
            
        except urllib.error.URLError as e:
            LOGGER.error("proxy_url_error", url=url, error=str(e))
            error_response = json.dumps({
                "ok": False,
                "error": f"Bridge unavailable: {e.reason}",
                "data": {}
            }).encode()
            return error_response, 503, {"Content-Type": "application/json"}
            
        except Exception as e:
            LOGGER.error("proxy_error", url=url, error=str(e))
            error_response = json.dumps({
                "ok": False,
                "error": str(e),
                "data": {}
            }).encode()
            return error_response, 500, {"Content-Type": "application/json"}


def proxy_api_request(
    handler: BaseHTTPRequestHandler,
    proxy: BridgeProxy,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query_params: dict[str, Any] | None = None
) -> None:
    """Proxy an API request from dashboard handler to bridge.
    
    This is a convenience function for dashboard HTTP handlers.
    
    Args:
        handler: Dashboard HTTP request handler
        proxy: Bridge proxy instance
        method: HTTP method (GET, POST)
        path: API path
        body: POST body dict
        query_params: GET query parameters
    """
    if method == "GET":
        response_body, status, headers = proxy.forward_get(path, query_params)
    else:
        response_body, status, headers = proxy.forward_post(path, body or {})
    
    # Send response
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(response_body)))
    
    # Forward relevant headers from bridge
    for key in ["Access-Control-Allow-Origin", "Access-Control-Allow-Methods"]:
        if key in headers:
            handler.send_header(key, headers[key])
    
    handler.end_headers()
    handler.wfile.write(response_body)


__all__ = [
    "BridgeProxy",
    "proxy_api_request",
]
