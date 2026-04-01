"""
Universal Headless LSP Client.

Async JSON-RPC client over stdio.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from batho_core.utils.logging import get_logger
from batho_core.context.lsp.adapters.base import LSPAdapter
from batho_core.lsp.registry import ContainerSpec

from .types import (
    BatchResponse, ClientCapabilities, DefinitionResponse, 
    DocumentSymbolResponse, HoverResponse, Location, LSPResponse,
    Position, Range, ReferencesResponse, TextDocumentIdentifier, SymbolKind
)
from .errors import LSPError, LSPTimeoutError, LSPResponseError, LSPNotInitializedError
from .process_manager import LSPProcessManager, LSPProcessState
from .capabilities import CapabilityNegotiator
from .cache import LSPResponseCache
from .hasher import LSPResponseHasher


class LSPClient:
    """
    Universal LSP client for communicating with language servers.
    """

    def __init__(
        self,
        language: str,
        container_config: ContainerSpec,
        adapter: Optional[LSPAdapter] = None,
        cache: Optional[LSPResponseCache] = None,
        timeout_ms: int = 30000,
        max_retries: int = 3
    ):
        self.language = language
        self.container_config = container_config
        self.adapter = adapter
        self.cache = cache or LSPResponseCache()
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        
        self.process_manager = LSPProcessManager(
            # For Phase 1 we mock the command for local testing via Pyright/tsserver directly
            # For Phase 2 we use exact hermetic container spec
            command=container_config.command,
            env=container_config.env
        )
        self.negotiator = CapabilityNegotiator()
        self.hasher = LSPResponseHasher()
        self.logger = get_logger(__name__, component="lsp_client").bind(language=language)
        
        self._request_id = 1
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()

    async def initialize(self, root_uri: str, capabilities: ClientCapabilities) -> None:
        """
        Initialize the LSP connection.
        """
        await self.process_manager.start()
        
        self._reader_task = asyncio.create_task(self._read_loop())
        
        # Build initialize request
        # Convert ClientCapabilities to dict using pydantic methods
        caps_dict = capabilities.model_dump(exclude_none=True)
        # Handle custom Batho attributes specifically if not part of LSP spec
        for key in ["batho_deterministic_mode", "batho_include_raw_responses"]:
            caps_dict.pop(key, None)

        init_options = {}
        if self.adapter:
            # We assume root_uri is file://<path>
            # Mock root parsing
            root_path = root_uri.replace("file://", "")
            init_options = self.adapter.get_initialize_options(root_path)
            
        params = {
            "processId": None,
            "rootUri": root_uri,
            "capabilities": caps_dict,
            "initializationOptions": init_options
        }
        
        try:
            response = await self._send_request("initialize", params)
            if "capabilities" in response:
                self.negotiator.update_server_capabilities(response["capabilities"])
                
            # Send initialized notification
            await self._send_notification("initialized", {})
            self._initialized = True
            self.logger.info("lsp_initialized", language=self.language)
            
        except Exception as e:
            await self.shutdown()
            raise LSPError(f"Failed to initialize LSP for {self.language}") from e

    async def shutdown(self) -> None:
        """
        Gracefully shutdown LSP connection.
        """
        if self.process_manager.state == LSPProcessState.RUNNING and self._initialized:
            try:
                await self._send_request("shutdown", {}, _timeout_ms=5000)
                await self._send_notification("exit", {})
            except Exception as e:
                self.logger.warning("lsp_shutdown_error", error=str(e))
                
        if self._reader_task:
            self._reader_task.cancel()
            
        await self.process_manager.stop()
        self._initialized = False

    async def _send_request(self, method: str, params: dict, _timeout_ms: Optional[int] = None) -> Any:
        """
        Send a JSON-RPC request and wait for a response.
        """
        req_id = self._request_id
        self._request_id += 1
        
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[req_id] = future
        
        await self.process_manager.send_message(message)
        
        timeout = (_timeout_ms or self.timeout_ms) / 1000.0
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            
            if "error" in response:
                err = response["error"]
                raise LSPResponseError(err.get("code", -32000), err.get("message", "Unknown error"), err.get("data"))
                
            return response.get("result")
            
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise LSPTimeoutError(method, int(timeout * 1000))

    async def _send_notification(self, method: str, params: dict) -> None:
        """
        Send a JSON-RPC notification.
        """
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        await self.process_manager.send_message(message)

    async def _read_loop(self) -> None:
        """
        Background task to read messages and resolve futures.
        """
        try:
            while self.process_manager.state == LSPProcessState.RUNNING:
                msg = await self.process_manager.read_message()
                
                # Check if it's a response to a request
                if "id" in msg and msg["id"] in self._pending_requests:
                    req_id = msg["id"]
                    future = self._pending_requests.pop(req_id)
                    if not future.done():
                        future.set_result(msg)
                
                # We log server notifications or push them as needed
                elif "method" in msg:
                    self.logger.debug("lsp_notification", method=msg["method"])
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error("lsp_read_loop_error", error=str(e))
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(e)
            self._pending_requests.clear()

    # -----------------------------------------------------------------------
    # LSP Standard Methods
    # -----------------------------------------------------------------------

    async def textDocument_definition(
        self,
        text_document: TextDocumentIdentifier,
        position: Position,
        timeout_ms: Optional[int] = None
    ) -> DefinitionResponse:
        self.negotiator.require_capability("definitionProvider", "Go to Definition")
        
        params = {
            "textDocument": text_document.model_dump(),
            "position": position.model_dump()
        }
        
        # Check cache (content addressed on params)
        # Using a dummy version string for phase 1 since we aren't pulling from container 
        lsp_version = self.container_config.lsp_binary.version
        req_hash = self.cache.compute_request_hash("textDocument/definition", params, lsp_version)
        
        cached = await self.cache.get(req_hash)
        if cached:
            if isinstance(cached, DefinitionResponse):
                return cached
            # Deserialization from generic LSPResponse fallback
            locs = [] # Would parse from JSON
            return DefinitionResponse(
                raw_json=cached.raw_json,
                hash=cached.hash,
                timestamp=cached.timestamp,
                duration_ms=cached.duration_ms,
                locations=locs
            )
            
        t0 = asyncio.get_event_loop().time()
        result = await self._send_request("textDocument/definition", params, timeout_ms)
        duration = int((asyncio.get_event_loop().time() - t0) * 1000)
        
        locations = []
        if isinstance(result, list):
            for item in result:
                # Handle LocationLink vs Location
                uri = item.get("uri") or item.get("targetUri")
                r = item.get("range") or item.get("targetRange")
                if uri and r:
                    locations.append(Location(
                        uri=uri,
                        range=Range(
                            start=Position(line=r["start"]["line"], character=r["start"]["character"]),
                            end=Position(line=r["end"]["line"], character=r["end"]["character"])
                        )
                    ))
        elif isinstance(result, dict):
            locations.append(Location(
                uri=result.get("uri", ""),
                range=Range(
                    start=Position(line=result["range"]["start"]["line"], character=result["range"]["start"]["character"]),
                    end=Position(line=result["range"]["end"]["line"], character=result["range"]["end"]["character"])
                )
            ))
            
        raw_json_str = json.dumps(result)
        res_hash = self.hasher.hash_response(raw_json_str)
        
        resp = DefinitionResponse(
            raw_json=raw_json_str,
            hash=res_hash,
            duration_ms=duration,
            locations=locations
        )
        
        await self.cache.set(req_hash, resp)
        return resp

    async def textDocument_references(
        self,
        text_document: TextDocumentIdentifier,
        position: Position,
        timeout_ms: Optional[int] = None
    ) -> Any:
        self.negotiator.require_capability("referencesProvider", "Find References")
        
        params = {
            "textDocument": text_document.model_dump(),
            "position": position.model_dump(),
            "context": {"includeDeclaration": False}
        }
        
        # For phase 2, we don't necessarily cache references as they can be large and are just used for call chains
        result = await self._send_request("textDocument/references", params, timeout_ms)
        
        # Apply adapter transformation if it wants to adapt the response early
        if self.adapter:
            # We wrap this in a dummy dict since our adapter takes the whole response
            # But wait, our adapters take just the raw payload
            result = self.adapter.adapt_response("textDocument/references", result)
            
        return result
