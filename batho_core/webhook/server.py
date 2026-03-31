"""HTTP server for receiving webhooks."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

from batho_core.utils.logging import get_logger
from .auth import verify_github_signature, verify_gitlab_token
from .config import WebhookConfig
from .processor import WebhookProcessor

logger = get_logger(__name__, component="webhook_server")


class WebhookRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for webhooks."""
    
    # Class-level storage for processor
    processor: Optional[WebhookProcessor] = None
    config: Optional[WebhookConfig] = None
    
    def do_POST(self):
        """Handle POST requests."""
        if self.path != "/webhook":
            self._send_error(404, "Not Found")
            return
        
        # Read payload
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_error(400, "Empty payload")
            return
        
        payload_bytes = self.rfile.read(content_length)
        
        # Verify authentication
        if not self._verify_auth(payload_bytes):
            self._send_error(401, "Unauthorized")
            return
        
        # Parse JSON
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON")
            return
        
        # Process webhook
        if self.processor:
            result = self.processor.process_webhook(payload, dict(self.headers))
            
            if result["status"] == "queued":
                # Accepted for processing
                response = {
                    "status": "accepted",
                    "event_id": result["event_id"],
                    "message": "Webhook accepted for processing"
                }
                self._send_json(202, response)
            elif result["status"] == "ignored":
                # Branch not watched
                response = {
                    "status": "ignored",
                    "message": result["message"]
                }
                self._send_json(200, response)
            else:
                # Error
                self._send_json(400, result)
        else:
            self._send_error(500, "Processor not initialized")
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            # Health check endpoint
            stats = self.processor.queue.get_stats() if self.processor else {}
            response = {
                "status": "healthy",
                "queue_stats": stats
            }
            self._send_json(200, response)
        else:
            self._send_error(404, "Not Found")
    
    def _verify_auth(self, payload: bytes) -> bool:
        """Verify webhook signature/token."""
        if not self.config or not self.config.repository:
            return False
        
        secret = self.config.repository.secret
        
        # Check GitHub signature
        if "X-Hub-Signature-256" in self.headers:
            signature = self.headers["X-Hub-Signature-256"]
            return verify_github_signature(payload, signature, secret)
        
        # Check GitLab token
        elif "X-Gitlab-Token" in self.headers:
            token = self.headers["X-Gitlab-Token"]
            return verify_gitlab_token(token, secret)
        
        return False
    
    def _send_json(self, status_code: int, data: dict):
        """Send JSON response."""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))
    
    def _send_error(self, status_code: int, message: str):
        """Send error response."""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode("utf-8"))
    
    def log_message(self, format: str, *args):
        """Override to use structured logging."""
        logger.debug("http_request", message=format % args)


class WebhookServer:
    """Webhook HTTP server."""
    
    def __init__(self, config: WebhookConfig, repo_path: Path):
        self.config = config
        self.repo_path = repo_path
        self.server: Optional[HTTPServer] = None
        self.processor = WebhookProcessor(config, repo_path)
        self._server_thread: Optional[threading.Thread] = None
    
    def start(self):
        """Start the webhook server."""
        # Configure handler class
        WebhookRequestHandler.processor = self.processor
        WebhookRequestHandler.config = self.config
        
        # Create HTTP server
        self.server = HTTPServer(
            (self.config.server.host, self.config.server.port),
            WebhookRequestHandler
        )
        
        # Start processor
        self.processor.start()
        
        # Start server in background thread
        self._server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True
        )
        self._server_thread.start()
        
        logger.info(
            "webhook_server_started",
            host=self.config.server.host,
            port=self.config.server.port
        )
    
    def stop(self):
        """Stop the webhook server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        
        if self.processor:
            self.processor.stop()
        
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=5.0)
        
        logger.info("webhook_server_stopped")
    
    def serve_forever(self):
        """Run server in foreground (blocking)."""
        self.start()
        try:
            # Keep main thread alive
            while self._server_thread and self._server_thread.is_alive():
                self._server_thread.join(1.0)
        except KeyboardInterrupt:
            logger.info("webhook_server_interrupted")
        finally:
            self.stop()
