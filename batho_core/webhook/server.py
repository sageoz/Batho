"""HTTP server for receiving webhooks."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

from batho_core.utils.logging import get_logger

from .config import WebhookConfig
from .handler import WebhookHandler

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
except ImportError:
    FastAPI = None
    Request = None
    JSONResponse = None

try:
    import uvicorn
except ImportError:
    uvicorn = None


logger = get_logger(__name__, component="webhook_server")


def create_webhook_app(handler: WebhookHandler, config: WebhookConfig):
    if FastAPI is None or JSONResponse is None:
        raise RuntimeError("FastAPI is not installed")

    app = FastAPI(title="Batho Webhook Server", version="1.0.0")

    @app.post(config.server.endpoint)
    async def webhook_endpoint(request: Request):
        payload_bytes = await request.body()
        headers = dict(request.headers)
        source_ip = request.client.host if request.client else None
        result = handler.handle_webhook(payload_bytes, headers, source_ip=source_ip)
        return JSONResponse(status_code=result.http_status, content=result.to_response())

    @app.get(config.server.health_endpoint)
    async def health_endpoint():
        return JSONResponse(status_code=200, content=handler.get_health())

    return app


class _FallbackWebhookRequestHandler(BaseHTTPRequestHandler):
    """Fallback handler used only when FastAPI/uvicorn is unavailable."""

    handler: Optional[WebhookHandler] = None
    config: Optional[WebhookConfig] = None

    def do_POST(self):
        if not self.config or not self.handler:
            self._send_json(500, {"status": "error", "message": "Server not initialized"})
            return

        if self.path != self.config.server.endpoint:
            self._send_json(404, {"status": "error", "message": "Not Found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json(400, {"status": "error", "message": "Empty payload"})
            return

        payload_bytes = self.rfile.read(content_length)
        headers = {k: v for k, v in self.headers.items()}
        source_ip = self.client_address[0] if self.client_address else None
        result = self.handler.handle_webhook(payload_bytes, headers, source_ip=source_ip)
        self._send_json(result.http_status, result.to_response())

    def do_GET(self):
        if not self.config or not self.handler:
            self._send_json(500, {"status": "error", "message": "Server not initialized"})
            return

        if self.path != self.config.server.health_endpoint:
            self._send_json(404, {"status": "error", "message": "Not Found"})
            return

        self._send_json(200, self.handler.get_health())

    def _send_json(self, status_code: int, payload: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, format: str, *args):
        logger.debug("http_request", message=format % args)


class WebhookServer:
    """Webhook HTTP server."""

    def __init__(self, config: WebhookConfig, repo_path: Path):
        self.config = config
        self.repo_path = repo_path
        self.handler = WebhookHandler(config, repo_path)

        self.server: Optional[HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None

        self._use_fastapi = FastAPI is not None and uvicorn is not None
        self._fastapi_app = None
        self._uvicorn_server = None

    def start(self):
        """Start the webhook server."""
        self.handler.start()

        if self._use_fastapi:
            self._start_fastapi()
        else:
            self._start_fallback_server()

        logger.info(
            "webhook_server_started",
            host=self.config.server.host,
            port=self.config.server.port,
            fastapi=self._use_fastapi,
        )

    def stop(self):
        """Stop the webhook server."""
        if self._use_fastapi and self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True

        if self.server:
            self.server.shutdown()
            self.server.server_close()

        self.handler.stop()

        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=5.0)

        logger.info("webhook_server_stopped")

    def serve_forever(self):
        """Run server in foreground (blocking)."""
        self.start()
        try:
            while self._server_thread and self._server_thread.is_alive():
                self._server_thread.join(1.0)
        except KeyboardInterrupt:
            logger.info("webhook_server_interrupted")
        finally:
            self.stop()

    def _start_fastapi(self) -> None:
        self._fastapi_app = create_webhook_app(self.handler, self.config)
        uv_config = uvicorn.Config(
            self._fastapi_app,
            host=self.config.server.host,
            port=self.config.server.port,
            log_level="info",
        )
        self._uvicorn_server = uvicorn.Server(uv_config)
        self._server_thread = threading.Thread(
            target=self._uvicorn_server.run,
            daemon=True,
        )
        self._server_thread.start()

    def _start_fallback_server(self) -> None:
        _FallbackWebhookRequestHandler.handler = self.handler
        _FallbackWebhookRequestHandler.config = self.config

        self.server = HTTPServer(
            (self.config.server.host, self.config.server.port),
            _FallbackWebhookRequestHandler,
        )
        self._server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self._server_thread.start()
