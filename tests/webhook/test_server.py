from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

import batho.webhook.server as server_module
from batho.webhook.config import WebhookConfig
from batho.webhook.server import WebhookServer, create_webhook_app


class _DummyHandler:
    def __init__(self):
        self.calls = []

    def handle_webhook(self, payload_bytes, headers, source_ip=None):
        _ = payload_bytes, headers, source_ip
        return SimpleNamespace(http_status=200, to_response=lambda: {"ok": True})

    def get_health(self):
        return {"status": "healthy"}


def test_create_webhook_app_raises_without_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "FastAPI", None)
    monkeypatch.setattr(server_module, "JSONResponse", None)
    with pytest.raises(RuntimeError):
        create_webhook_app(_DummyHandler(), WebhookConfig())


def test_create_webhook_app_registers_routes_and_handles_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeApp:
        def __init__(self, title: str, version: str):
            self.title = title
            self.version = version
            self.post_routes: dict[str, object] = {}
            self.get_routes: dict[str, object] = {}

        def post(self, route: str):
            def _decorator(func):
                self.post_routes[route] = func
                return func

            return _decorator

        def get(self, route: str):
            def _decorator(func):
                self.get_routes[route] = func
                return func

            return _decorator

    class _RecordingHandler(_DummyHandler):
        def handle_webhook(self, payload_bytes, headers, source_ip=None):
            self.calls.append((payload_bytes, headers, source_ip))
            return SimpleNamespace(http_status=202, to_response=lambda: {"status": "accepted"})

    monkeypatch.setattr(server_module, "FastAPI", _FakeApp)
    monkeypatch.setattr(
        server_module,
        "JSONResponse",
        lambda status_code, content: {"status_code": status_code, "content": content},
    )

    cfg = WebhookConfig()
    handler = _RecordingHandler()
    app = create_webhook_app(handler, cfg)

    class _Request:
        headers = {"X-Test": "1"}
        client = SimpleNamespace(host="127.0.0.1")

        @staticmethod
        async def body():
            return b'{"ok": true}'

    webhook_response = asyncio.run(app.post_routes[cfg.server.endpoint](_Request()))
    health_response = asyncio.run(app.get_routes[cfg.server.health_endpoint]())

    assert webhook_response == {
        "status_code": 202,
        "content": {"status": "accepted"},
    }
    assert health_response["status_code"] == 200
    assert handler.calls[0][2] == "127.0.0.1"


def test_webhook_server_start_stop_fallback_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = WebhookConfig()
    server = WebhookServer(cfg, tmp_path)
    server._use_fastapi = False

    class _FakeHTTPServer:
        def __init__(self, addr, handler_cls):
            _ = addr, handler_cls
            self.shutdown_called = False
            self.closed = False

        def serve_forever(self):
            return None

        def shutdown(self):
            self.shutdown_called = True

        def server_close(self):
            self.closed = True

    monkeypatch.setattr(server_module, "HTTPServer", _FakeHTTPServer)

    started = {"start": 0, "stop": 0}
    monkeypatch.setattr(server.handler, "start", lambda: started.__setitem__("start", started["start"] + 1))
    monkeypatch.setattr(server.handler, "stop", lambda: started.__setitem__("stop", started["stop"] + 1))

    server.start()
    assert started["start"] == 1
    assert server.server is not None

    server.stop()
    assert started["stop"] == 1


def test_webhook_server_start_stop_fastapi_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = WebhookConfig()
    server = WebhookServer(cfg, tmp_path)
    server._use_fastapi = True

    monkeypatch.setattr(server.handler, "start", lambda: None)
    monkeypatch.setattr(server.handler, "stop", lambda: None)

    monkeypatch.setattr(server, "_start_fastapi", lambda: None)

    class _DummyUvicornServer:
        should_exit = False

    server._uvicorn_server = _DummyUvicornServer()
    server.start()
    server.stop()
    assert server._uvicorn_server.should_exit is True


def test_webhook_server_serve_forever_calls_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = WebhookConfig()
    server = WebhookServer(cfg, tmp_path)

    class _Thread:
        def __init__(self):
            self._alive = True

        def is_alive(self):
            alive = self._alive
            self._alive = False
            return alive

        def join(self, timeout=None):
            _ = timeout
            return None

    monkeypatch.setattr(server, "start", lambda: setattr(server, "_server_thread", _Thread()))

    stopped = {"value": 0}
    monkeypatch.setattr(server, "stop", lambda: stopped.__setitem__("value", stopped["value"] + 1))

    server.serve_forever()
    assert stopped["value"] == 1


def test_fallback_request_handler_post_and_get_branches() -> None:
    handler = object.__new__(server_module._FallbackWebhookRequestHandler)
    responses: list[tuple[int, dict]] = []
    handler._send_json = lambda status, payload: responses.append((status, payload))

    handler.config = None
    handler.handler = None
    handler.do_POST()
    handler.do_GET()
    assert responses[0][0] == 500
    assert responses[1][0] == 500

    cfg = WebhookConfig()
    handler.config = cfg
    handler.handler = _DummyHandler()

    handler.path = "/not-found"
    handler.headers = {"Content-Length": "5"}
    handler.do_POST()
    handler.do_GET()
    assert responses[2][0] == 404
    assert responses[3][0] == 404

    handler.path = cfg.server.endpoint
    handler.headers = {"Content-Length": "0"}
    handler.do_POST()
    assert responses[4][0] == 400


def test_fallback_request_handler_success_path() -> None:
    class _Handler(_DummyHandler):
        def handle_webhook(self, payload_bytes, headers, source_ip=None):
            self.calls.append((payload_bytes, headers, source_ip))
            return SimpleNamespace(http_status=201, to_response=lambda: {"created": True})

    cfg = WebhookConfig()
    fallback = object.__new__(server_module._FallbackWebhookRequestHandler)
    captured: list[tuple[int, dict]] = []
    fallback._send_json = lambda status, payload: captured.append((status, payload))

    fallback.config = cfg
    fallback.handler = _Handler()
    fallback.path = cfg.server.endpoint
    fallback.headers = {"Content-Length": "2", "X-Test": "1"}
    fallback.rfile = io.BytesIO(b"{}")
    fallback.client_address = ("127.0.0.1", 8080)

    fallback.do_POST()
    assert captured == [(201, {"created": True})]
    assert fallback.handler.calls[0][2] == "127.0.0.1"

    fallback.path = cfg.server.health_endpoint
    fallback.do_GET()
    assert captured[-1][0] == 200


def test_fallback_send_json_and_log_message(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = object.__new__(server_module._FallbackWebhookRequestHandler)
    sent: dict[str, object] = {"headers": []}

    fallback.send_response = lambda status: sent.__setitem__("status", status)
    fallback.send_header = lambda key, value: sent["headers"].append((key, value))
    fallback.end_headers = lambda: sent.__setitem__("ended", True)
    fallback.wfile = io.BytesIO()

    fallback._send_json(201, {"ok": True})

    assert sent["status"] == 201
    assert ("Content-Type", "application/json") in sent["headers"]
    assert sent["ended"] is True
    assert b'"ok": true' in fallback.wfile.getvalue()

    logs: list[tuple[str, dict]] = []
    monkeypatch.setattr(server_module.logger, "debug", lambda event, **kwargs: logs.append((event, kwargs)))

    fallback.log_message("%s %s", "GET", "/health")
    assert logs


def test_start_helpers_build_fastapi_and_fallback_servers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = WebhookConfig()
    server = WebhookServer(cfg, tmp_path)

    monkeypatch.setattr(server_module, "create_webhook_app", lambda _handler, _cfg: "APP")

    class _FakeConfig:
        def __init__(self, app, host: str, port: int, log_level: str):
            self.app = app
            self.host = host
            self.port = port
            self.log_level = log_level

    class _FakeUvicornServer:
        def __init__(self, config):
            self.config = config

        def run(self):
            return None

    monkeypatch.setattr(
        server_module,
        "uvicorn",
        SimpleNamespace(Config=_FakeConfig, Server=_FakeUvicornServer),
    )

    class _FakeThread:
        def __init__(self, target, daemon: bool):
            self.target = target
            self.daemon = daemon
            self.started = False

        def start(self):
            self.started = True

    class _FakeHTTPServer:
        def __init__(self, address, handler_cls):
            self.address = address
            self.handler_cls = handler_cls

        def serve_forever(self):
            return None

    monkeypatch.setattr(server_module.threading, "Thread", _FakeThread)
    monkeypatch.setattr(server_module, "HTTPServer", _FakeHTTPServer)

    server._start_fastapi()
    assert server._fastapi_app == "APP"
    assert server._server_thread.started is True

    server._start_fallback_server()
    assert isinstance(server.server, _FakeHTTPServer)
    assert server._server_thread.started is True
