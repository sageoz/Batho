"""
LSP Process Management Lifecycle.
"""

import asyncio
import json
from enum import Enum, auto
from typing import List, Optional

from batho_core.utils.logging import get_logger
from batho_core.context.lsp.errors import LSPProcessError


class LSPProcessState(Enum):
    """Lifecycle states of the LSP process."""
    STARTING = auto()
    RUNNING = auto()
    SHUTTING_DOWN = auto()
    STOPPED = auto()
    FAILED = auto()


class LSPProcessManager:
    """
    Manages the lifecycle of an LSP process.
    Handles stdio communication and process spawning/restarting.
    
    In Phase 1, this just wraps an asyncio.subprocess.
    In Phase 2, this will orchestrate the container execution.
    """

    def __init__(self, command: List[str], env: dict[str, str] | None = None):
        self.command = command
        self.env = env or {}
        self.process: Optional[asyncio.subprocess.Process] = None
        self.state = LSPProcessState.STOPPED
        self.logger = get_logger(__name__, component="lsp_process")

    async def start(self) -> None:
        """Spawn the LSP process."""
        if self.state in (LSPProcessState.STARTING, LSPProcessState.RUNNING):
            return
            
        self.state = LSPProcessState.STARTING
        self.logger.info("lsp_process_starting", command=self.command)
        
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env
            )
            self.state = LSPProcessState.RUNNING
            self.logger.debug("lsp_process_running", pid=self.process.pid)
            
        except Exception as e:
            self.state = LSPProcessState.FAILED
            self.logger.error("lsp_process_start_failed", error=str(e))
            raise LSPProcessError(
                return_code=-1,
                stderr=f"Failed to start {self.command}: {e}"
            ) from e

    async def stop(self) -> None:
        """Terminate the LSP process."""
        if self.state == LSPProcessState.STOPPED or self.process is None:
            return
            
        self.state = LSPProcessState.SHUTTING_DOWN
        self.logger.debug("lsp_process_stopping")
        
        try:
            if self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self.logger.warning("lsp_process_kill_required")
                    self.process.kill()
                    await self.process.wait()
                    
            self.state = LSPProcessState.STOPPED
            self.logger.debug("lsp_process_stopped")
            
        except ProcessLookupError:
            self.state = LSPProcessState.STOPPED
        finally:
            self.process = None

    async def send_message(self, message: dict) -> None:
        """
        Send a JSON-RPC message over stdout.
        Format: Content-Length: <length>\\r\\n\\r\\n<json>
        """
        if self.state != LSPProcessState.RUNNING or self.process is None or self.process.stdin is None:
            raise LSPProcessError(-1, "Process not running or missing stdin")
            
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8")
        
        try:
            self.process.stdin.write(header + payload)
            await self.process.stdin.drain()
        except BrokenPipeError:
            self.state = LSPProcessState.FAILED
            raise LSPProcessError(-1, "Broken pipe while sending message")

    async def read_message(self) -> dict:
        """
        Read a JSON-RPC message from stdout.
        """
        if self.state != LSPProcessState.RUNNING or self.process is None or self.process.stdout is None:
            raise LSPProcessError(-1, "Process not running or missing stdout")
            
        # Parse Content-Length header
        content_length = -1
        while True:
            line = await self.process.stdout.readline()
            if not line:
                # EOF
                self.state = LSPProcessState.STOPPED
                raise LSPProcessError(-1, "Unexpected EOF from LSP stdout")
                
            line_str = line.decode("utf-8").strip()
            if not line_str:
                # Empty line marks end of headers
                break
                
            if line_str.startswith("Content-Length:"):
                content_length = int(line_str.split(":")[1].strip())
                
        if content_length < 0:
            raise LSPProcessError(-1, "Invalid/Missing Content-Length header")
            
        # Read exact number of bytes
        body = await self.process.stdout.readexactly(content_length)
        return json.loads(body.decode("utf-8"))
